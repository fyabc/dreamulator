"""Run local region refinement away from the API process."""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
from collections import OrderedDict
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Lock
from time import monotonic
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel

from dreamulator.build_jobs import BuildBusyError, local_compute_slot
from dreamulator.media.terrain_blend import RefinementMode
from dreamulator.utils.resources import available_memory_bytes

RSS_LIMIT = 8 * 2**30
MAX_SPAN_KM = 550
PACK_SIZES = (256, 512, 1024)
RegionStage = Literal["preparing", "terrain", "hydrology", "publishing"]
logger = logging.getLogger(__name__)


class RegionPlan(BaseModel):
    span_km: float
    input_px: int
    output_px: int
    native_scale_km: float | None
    mode: RefinementMode = RefinementMode.REDRAW
    native_resolution_km: float | None = None
    preserve_wavelength_km: float | None = None
    river_threshold: int | None = None


class RegionJob(BaseModel):
    id: str
    plan: RegionPlan
    state: Literal["queued", "running", "succeeded", "failed", "cancelled"] = "queued"
    stage: RegionStage = "preparing"
    elapsed_seconds: int = 0
    result_pack: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class RegionWork:
    root: Path
    td: Path | None
    pack: Path | None = None
    export_args: tuple[str, ...] = ()


def _tree_rss(pid: int) -> int:
    proc = Path("/proc") / str(pid)
    try:
        rows = (proc / "status").read_text(encoding="utf-8").splitlines()
        children = (proc / "task" / str(pid) / "children").read_text(encoding="utf-8")
    except (FileNotFoundError, ProcessLookupError):
        return 0
    own = next((int(row.split()[1]) * 1024 for row in rows if row.startswith("VmRSS:")), 0)
    return own + sum(_tree_rss(int(child)) for child in children.split())


class RegionJobs:
    def __init__(self) -> None:
        self._lock = Lock()
        self._jobs: OrderedDict[str, RegionJob] = OrderedDict()
        self._started: dict[str, float] = {}
        self._cancel: dict[str, Event] = {}

    def reserve(self, plan: RegionPlan) -> RegionJob:
        with self._lock:
            if not local_compute_slot.acquire(blocking=False):
                raise BuildBusyError("Another local compute job is already active")
            while len(self._jobs) >= 32:
                old, _ = self._jobs.popitem(last=False)
                self._started.pop(old, None)
                self._cancel.pop(old)
            job = RegionJob(id=uuid4().hex, plan=plan)
            self._jobs[job.id] = job
            self._cancel[job.id] = Event()
            return job.model_copy(deep=True)

    def get(self, key: str, *, cancel: bool = False) -> RegionJob:
        with self._lock:
            job = self._jobs[key]
            if job.state in {"queued", "running"}:
                if cancel and job.stage != "publishing":
                    self._cancel[key].set()
                if key in self._started:
                    job.elapsed_seconds = int(monotonic() - self._started[key])
            return job.model_copy(deep=True)

    def execute(self, key: str, work: RegionWork) -> None:
        with self._lock:
            job = self._jobs[key]
            cancelled = self._cancel[key]
            self._started[key] = monotonic()
            job.state = "running"
        result = None
        error = None
        try:
            available = available_memory_bytes()
            if available is None or available // 2 < RSS_LIMIT:
                raise RuntimeError("Not enough available RAM for the region refinement budget")
            if not cancelled.is_set():
                work.root.mkdir(parents=True, exist_ok=True)
                with TemporaryDirectory(prefix=".refinement-", dir=work.root) as directory:
                    staging = Path(directory)
                    self._run_worker(job, work, staging, cancelled)
                    with self._lock:
                        if not cancelled.is_set():
                            job.stage = "publishing"
                            result = f"web-region-{key}"
                            os.replace(staging / "pack", work.root / result)
        except Exception as exc:
            result = None
            error = str(exc)
        finally:
            with self._lock:
                job.elapsed_seconds = int(monotonic() - self._started[key])
                job.result_pack = result
                job.error = error if not cancelled.is_set() else None
                job.state = (
                    "succeeded" if result else "cancelled" if cancelled.is_set() else "failed"
                )
                local_compute_slot.release()

    def _run_worker(
        self, job: RegionJob, work: RegionWork, staging: Path, cancelled: Event
    ) -> None:
        args = staging / "request.json"
        args.write_text(
            json.dumps(
                {
                    "td": str(work.td) if work.td is not None else None,
                    "mode": job.plan.mode,
                    "native_resolution_km": job.plan.native_resolution_km,
                    "preserve_wavelength_km": job.plan.preserve_wavelength_km,
                    "river_threshold": job.plan.river_threshold,
                    "pack": str(work.pack) if work.pack else None,
                    "export_args": work.export_args,
                    "limit": RSS_LIMIT,
                }
            ),
            encoding="utf-8",
        )
        logfile = staging / "worker.log"
        environment = {**os.environ, "PYTHONUNBUFFERED": "1"}
        for name in (
            "OPENBLAS_NUM_THREADS",
            "MKL_NUM_THREADS",
            "OMP_NUM_THREADS",
            "NUMBA_NUM_THREADS",
        ):
            environment[name] = "2"
        with (
            logfile.open("wb") as log,
            subprocess.Popen(
                [sys.executable, "-m", "dreamulator.region_refine_worker", str(args)],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                env=environment,
                start_new_session=True,
            ) as process,
        ):
            try:
                while process.poll() is None:
                    if cancelled.wait(0.25):
                        return
                    self._read_stage(job, staging / "stage")
                    if _tree_rss(process.pid) > RSS_LIMIT:
                        raise RuntimeError("Region refinement exceeded its RAM budget")
                self._read_stage(job, staging / "stage")
                if process.returncode:
                    with logfile.open("rb") as reader:
                        reader.seek(max(0, logfile.stat().st_size - 4096))
                        detail = reader.read().decode("utf-8", errors="replace").strip()
                    logger.error("Region refinement %s failed: %s", job.id, detail)
                    message = detail.splitlines()[-1] if detail else "Region worker failed"
                    if message.startswith("subprocess.CalledProcessError:"):
                        message = f"Region worker failed during {job.stage}; see the server log"
                    raise RuntimeError(message)
            finally:
                if process.poll() is None:
                    with suppress(ProcessLookupError):
                        if sys.platform == "win32":
                            # Windows has no process groups here; kill the
                            # worker itself (it runs one refinement only).
                            process.kill()
                        else:
                            os.killpg(process.pid, signal.SIGKILL)

    def _read_stage(self, job: RegionJob, path: Path) -> None:
        if path.is_file():
            value = path.read_text(encoding="utf-8")
            if value == "terrain" or value == "hydrology":
                with self._lock:
                    job.stage = "terrain" if value == "terrain" else "hydrology"


region_jobs = RegionJobs()
