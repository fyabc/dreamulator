"""Local-only, short-lived climate runs and their map products."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
from time import monotonic
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from dreamulator.climate_trial import (
    TrialForcing,
    TrialProgress,
    TrialRequest,
    TrialSource,
    TrialUnavailableError,
    resolve_trial_source,
)
from dreamulator.utils.resources import available_memory_bytes
from dreamulator.world_manager import WorldManager

router = APIRouter(prefix="/api/worlds", tags=["climate trials"])
logger = logging.getLogger(__name__)
_manager = WorldManager()
_scratch = TemporaryDirectory(prefix="dreamulator-climate-")
_limit = 20 * 1024**3
_retained_runs = 4
_lock = Lock()
_route = "/{world_name}/maps/{planet_id}/climate-trials"

Asset = Literal["geometry", "fields", "monthly", "yearly"]
_assets: dict[Asset, tuple[str, str]] = {
    "geometry": ("mesh_geometry.msgpack.gz", "application/gzip"),
    "fields": ("mesh_fields.msgpack.gz", "application/gzip"),
    "monthly": ("climate_monthly.msgpack", "application/x-msgpack"),
    "yearly": ("climate_yearly.msgpack", "application/x-msgpack"),
}


class TrialJob(BaseModel):
    id: str
    state: Literal["queued", "running", "succeeded", "failed"]
    stage: str
    elapsed_seconds: float
    stage_seconds: float
    cells: int | None = None
    months_done: int | None = None
    months_total: int | None = None
    moisture_pass: int | None = None
    error: str | None = None


@dataclass
class _Run:
    world: str
    planet: str
    output: Path
    started: float
    state: Literal["queued", "running", "succeeded", "failed"] = "queued"
    finished: float | None = None
    error: str | None = None

    def snapshot(self) -> TrialJob:
        try:
            progress = TrialProgress.model_validate_json(
                (self.output / "progress.json").read_bytes()
            )
        except FileNotFoundError:
            progress = TrialProgress(stage="reading", started_at=self.started)
        now = self.finished if self.finished is not None else monotonic()
        return TrialJob(
            id=self.output.name,
            state=self.state,
            stage="queued" if self.state == "queued" else progress.stage,
            elapsed_seconds=now - self.started,
            stage_seconds=max(0.0, now - progress.started_at),
            cells=progress.cells,
            months_done=progress.months_done,
            months_total=progress.months_total,
            moisture_pass=progress.moisture_pass,
            error=self.error,
        )


_runs: dict[str, _Run] = {}


def _source(world_name: str, planet_id: str, branch: str | None) -> tuple[Path, TrialSource]:
    if any(
        not re.fullmatch(r"[\w-][\w.-]*", value)
        for value in (world_name, planet_id, branch or "root")
    ):
        raise HTTPException(404, "Trial source not found")
    try:
        world = _manager.world_dir(world_name).resolve()
        return world, resolve_trial_source(world, planet_id, branch)
    except FileNotFoundError as error:
        raise HTTPException(404, "Trial source not found") from error
    except TrialUnavailableError as error:
        raise HTTPException(409, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


def _execute(run: _Run, world: Path, request: TrialRequest, memory: int) -> None:
    with _lock:
        run.state = "running"
    error: str | None = "worker_failed"
    try:
        (run.output / "request.json").write_text(request.model_dump_json(), encoding="utf-8")
        with (run.output / "worker.log").open("wb") as log:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "dreamulator.climate_trial",
                    str(world),
                    run.planet,
                    str(run.output),
                    str(memory),
                ],
                env={
                    **os.environ,
                    "DREAMULATOR_CLIMATE_WORKERS": "1",
                    "OPENBLAS_NUM_THREADS": "1",
                    "OMP_NUM_THREADS": "1",
                    "MKL_NUM_THREADS": "1",
                },
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=1800,
                check=False,
            )
        if result.returncode == 0:
            error = None
        else:
            reason = run.output / "error.txt"
            error = reason.read_text(encoding="utf-8") if reason.is_file() else "worker_failed"
            logger.warning(
                "EBM trial %s exited %d; see %s", run.output.name, result.returncode, log.name
            )
    except subprocess.TimeoutExpired:
        error = "timed_out"
    except OSError:
        error = "worker_failed"
        logger.exception("Could not execute EBM trial %s", run.output.name)
    finally:
        with _lock:
            run.error = error
            run.state = "failed" if error else "succeeded"
            run.finished = monotonic()


def _find(world_name: str, planet_id: str, job_id: str) -> _Run:
    run = _runs.get(job_id)
    if run is None or (run.world, run.planet) != (world_name, planet_id):
        raise HTTPException(404, "Climate trial not found")
    return run


@router.get(f"{_route}/inputs")
def get_trial_inputs(world_name: str, planet_id: str, branch: str | None = None) -> TrialForcing:
    _, source = _source(world_name, planet_id, branch)
    return TrialForcing.from_config(source.config)


@router.post(_route, status_code=202)
def start_trial(
    world_name: str, planet_id: str, request: TrialRequest, background_tasks: BackgroundTasks
) -> TrialJob:
    world, _ = _source(world_name, planet_id, request.branch)
    available = available_memory_bytes()
    memory = min(_limit, available // 2) if available is not None else _limit
    if memory < 512 * 1024**2:
        raise HTTPException(409, "memory_budget")
    with _lock:
        if any(run.finished is None for run in _runs.values()):
            raise HTTPException(409, "trial_busy")
        if len(_runs) >= _retained_runs:
            old = _runs.pop(next(iter(_runs)))
            shutil.rmtree(old.output, ignore_errors=True)
        output = Path(_scratch.name) / uuid4().hex
        output.mkdir()
        run = _Run(world_name, planet_id, output, monotonic())
        _runs[output.name] = run
        background_tasks.add_task(_execute, run, world, request, memory)
        return run.snapshot()


@router.get(f"{_route}/{{job_id}}")
def get_trial(world_name: str, planet_id: str, job_id: str) -> TrialJob:
    with _lock:
        return _find(world_name, planet_id, job_id).snapshot()


@router.get(f"{_route}/{{job_id}}/products/{{asset}}")
def get_trial_product(world_name: str, planet_id: str, job_id: str, asset: Asset) -> FileResponse:
    with _lock:
        run = _find(world_name, planet_id, job_id)
        filename, content_type = _assets[asset]
        path = run.output / filename
        if run.state != "succeeded" or not path.is_file():
            raise HTTPException(404, "Climate trial product not found")
        return FileResponse(
            path, media_type=content_type, headers={"Cache-Control": "private, no-store"}
        )
