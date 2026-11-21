"""Local climate runs and independently saved map products."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
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
    TrialInputs,
    TrialProgress,
    TrialRequest,
    TrialSource,
    TrialUnavailableError,
    resolve_trial_source,
)
from dreamulator.map.models import MapMetadata
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
_saved_route = "/{world_name}/climate-results"

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


class SavedTrial(BaseModel):
    format: Literal[1] = 1
    solver: Literal["ebm"] = "ebm"
    id: str
    planet: str
    branch: str | None
    saved_at: datetime
    cells: int
    elapsed_seconds: float
    inputs: TrialInputs
    surface: MapMetadata


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


def _saved_store(world_name: str) -> Path:
    if not re.fullmatch(r"[\w-][\w.-]*", world_name):
        raise HTTPException(404, "World not found")
    try:
        world = _manager.world_dir(world_name)
    except FileNotFoundError as error:
        raise HTTPException(404, "World not found") from error
    store = world / "experiments" / "climate"
    if store.is_symlink() or store.parent.is_symlink():
        raise HTTPException(409, "Invalid saved climate directory")
    return store


def _saved_entry(store: Path, result_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", result_id):
        raise HTTPException(404, "Saved climate result not found")
    entry = store / result_id
    metadata = entry / "result.json"
    if entry.is_symlink() or metadata.is_symlink() or not metadata.is_file():
        raise HTTPException(404, "Saved climate result not found")
    return entry


def _read_saved(entry: Path) -> SavedTrial:
    metadata = entry / "result.json"
    if metadata.is_symlink():
        raise ValueError("Saved climate result metadata cannot be a link")
    result = SavedTrial.model_validate_json(metadata.read_bytes())
    if result.id != entry.name:
        raise ValueError("Saved climate result ID does not match its directory")
    return result


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


@router.post(f"{_route}/{{job_id}}/save")
def save_trial(world_name: str, planet_id: str, job_id: str) -> SavedTrial:
    store = _saved_store(world_name)
    with _lock:
        if re.fullmatch(r"[0-9a-f]{32}", job_id) and (store / job_id / "result.json").is_file():
            result = get_saved_trial(world_name, job_id)
            if result.planet != planet_id:
                raise HTTPException(404, "Climate trial not found")
            return result
        run = _find(world_name, planet_id, job_id)
        status = run.snapshot()
        if status.state != "succeeded" or status.cells is None:
            raise HTTPException(409, "trial_not_finished")
        if not (run.output / "surface.json").is_file():
            raise HTTPException(409, "trial_surface_missing")
        try:
            request = TrialRequest.model_validate_json((run.output / "request.json").read_bytes())
            result = SavedTrial(
                id=job_id,
                planet=planet_id,
                branch=request.branch,
                saved_at=datetime.now(UTC),
                cells=status.cells,
                elapsed_seconds=status.elapsed_seconds,
                inputs=TrialInputs.model_validate_json((run.output / "inputs.json").read_bytes()),
                surface=MapMetadata.model_validate_json((run.output / "surface.json").read_bytes()),
            )
            store.mkdir(exist_ok=True, parents=True)
            with TemporaryDirectory(prefix=".saving-", dir=store) as temp:
                stage = Path(temp) / "result"
                stage.mkdir()
                names = [filename for filename, _ in _assets.values()]
                names.extend(("elevation.png", "config.json"))
                for name in names:
                    if name != _assets["yearly"][0] or (run.output / name).is_file():
                        shutil.copyfile(run.output / name, stage / name)
                (stage / "result.json").write_text(result.model_dump_json(), encoding="utf-8")
                stage.rename(store / job_id)
            return result
        except (OSError, ValueError) as error:
            logger.exception("Could not save climate trial %s", job_id)
            raise HTTPException(500, "trial_save_failed") from error


@router.get(_saved_route)
def list_saved_trials(world_name: str) -> list[SavedTrial]:
    store = _saved_store(world_name)
    if not store.is_dir():
        return []
    results = []
    for entry in store.iterdir():
        if re.fullmatch(r"[0-9a-f]{32}", entry.name) and not entry.is_symlink():
            try:
                results.append(_read_saved(entry))
            except (OSError, ValueError):
                logger.warning("Could not read saved climate result %s", entry.name)
    return sorted(results, key=lambda result: result.saved_at, reverse=True)


@router.get(f"{_saved_route}/{{result_id}}")
def get_saved_trial(world_name: str, result_id: str) -> SavedTrial:
    entry = _saved_entry(_saved_store(world_name), result_id)
    try:
        return _read_saved(entry)
    except (OSError, ValueError) as error:
        raise HTTPException(409, "Invalid saved climate result") from error


@router.get(f"{_saved_route}/{{result_id}}/products/{{asset}}")
def get_saved_product(
    world_name: str, result_id: str, asset: Asset | Literal["elevation"]
) -> FileResponse:
    entry = _saved_entry(_saved_store(world_name), result_id)
    filename, content_type = (
        ("elevation.png", "image/png") if asset == "elevation" else _assets[asset]
    )
    path = entry / filename
    if path.is_symlink() or not path.is_file():
        raise HTTPException(404, "Saved climate product not found")
    return FileResponse(
        path, media_type=content_type, headers={"Cache-Control": "private, no-store"}
    )


@router.delete(f"{_saved_route}/{{result_id}}", status_code=204)
def delete_saved_trial(world_name: str, result_id: str) -> None:
    with _lock:
        shutil.rmtree(_saved_entry(_saved_store(world_name), result_id))
