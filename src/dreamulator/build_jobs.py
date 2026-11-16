"""Bounded, process-local API build status with one active writer."""

from __future__ import annotations

from collections import OrderedDict
from datetime import UTC, datetime
from enum import StrEnum
from threading import Lock
from time import monotonic
from typing import TYPE_CHECKING
from uuid import uuid4

from pydantic import BaseModel, Field

from dreamulator.engine.progress import PipelineEvent, StageState
from dreamulator.models.layers import Layer  # noqa: TC001 — Pydantic resolves this at runtime.

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


class JobState(StrEnum):
    """A request is reserved before its background function starts."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class BuildSummary(BaseModel):
    """The existing synchronous build response."""

    status: str
    engines_run: int = 0
    success: int = 0
    failed: int = 0
    errors: list[str] = Field(default_factory=list)


class BuildStage(BaseModel):
    """An engine stage, distinguished from upstream preparation."""

    engine: str
    layer: Layer
    bootstrap: bool = False
    state: StageState = StageState.PENDING
    started_at: datetime | None = None
    finished_at: datetime | None = None
    errors: list[str] = Field(default_factory=list)


class BuildJob(BaseModel):
    """A snapshot; elapsed time is measured from execution start."""

    id: str
    world: str
    branch: str | None
    engine: str | None
    force: bool
    state: JobState = JobState.QUEUED
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    elapsed_seconds: float = 0.0
    current_engine: str | None = None
    stages: list[BuildStage] = Field(default_factory=list)
    result: BuildSummary | None = None
    error: str | None = None


class BuildBusyError(RuntimeError):
    """A second API build would overlap the active writer."""


class BuildJobs:
    """Retain recent snapshots; FastAPI owns execution and graceful shutdown.

    This registry is for the single-process local server. It does not queue
    heavy computations or persist across server restarts.
    """

    def __init__(self, *, history_limit: int = 100) -> None:
        if history_limit < 1:
            raise ValueError("history_limit must be positive")
        self._limit = history_limit
        self._lock = Lock()
        self._active: str | None = None
        self._jobs: OrderedDict[str, BuildJob] = OrderedDict()
        self._worlds: dict[str, Path] = {}
        self._started: dict[str, float] = {}

    def reserve(
        self, world_dir: Path, *, branch: str | None, engine: str | None, force: bool
    ) -> BuildJob:
        """Reserve the writer before the response, rejecting duplicate clicks."""
        with self._lock:
            if self._active is not None:
                raise BuildBusyError(f"Build '{self._active}' is already active")
            while len(self._jobs) >= self._limit:
                old_id, _ = self._jobs.popitem(last=False)
                self._worlds.pop(old_id)
                self._started.pop(old_id, None)
            job = BuildJob(
                id=str(uuid4()), world=world_dir.name, branch=branch, engine=engine, force=force
            )
            self._jobs[job.id] = job
            self._worlds[job.id] = world_dir.resolve()
            self._active = job.id
            return job.model_copy(deep=True)

    def get(self, world_dir: Path, job_id: str) -> BuildJob:
        """Read a detached snapshot scoped to the current world's directory."""
        with self._lock:
            if self._worlds.get(job_id) != world_dir.resolve():
                raise KeyError(job_id)
            snapshot = self._jobs[job_id].model_copy(deep=True)
            if snapshot.state == JobState.RUNNING:
                snapshot.elapsed_seconds = round(monotonic() - self._started[job_id], 3)
            return snapshot

    def _observe(self, job_id: str, event: PipelineEvent) -> None:
        with self._lock:
            job = self._jobs[job_id]
            now = datetime.now(UTC)
            job.updated_at = now
            stage = next(
                (
                    s
                    for s in job.stages
                    if (s.engine, s.bootstrap) == (event.engine, event.bootstrap)
                ),
                None,
            )
            if stage is None:
                stage = BuildStage(
                    engine=event.engine, layer=event.layer, bootstrap=event.bootstrap
                )
                if event.bootstrap:
                    position = next(
                        (i for i, s in enumerate(job.stages) if not s.bootstrap), len(job.stages)
                    )
                    job.stages.insert(position, stage)
                else:
                    job.stages.append(stage)
            stage.state = event.state
            stage.errors = list(event.errors)
            if event.state in {StageState.VALIDATING, StageState.RUNNING}:
                stage.started_at = stage.started_at or now
                job.current_engine = event.engine
            elif event.state != StageState.PENDING:
                stage.finished_at = now
                job.current_engine = None

    def execute(
        self, job_id: str, run: Callable[[Callable[[PipelineEvent], None]], BuildSummary]
    ) -> BuildJob:
        """Run once, store every outcome, and release the writer on failure."""
        with self._lock:
            job = self._jobs[job_id]
            if self._active != job_id or job.state != JobState.QUEUED:
                raise RuntimeError("Build is no longer reserved")
            job.state = JobState.RUNNING
            job.started_at = job.updated_at = datetime.now(UTC)
            self._started[job_id] = monotonic()
        result = BuildSummary(status="failed", failed=1, errors=["Build interrupted"])
        try:
            result = run(lambda event: self._observe(job_id, event))
        except Exception as error:
            with self._lock:
                job.error = str(error)
                attempted = [
                    stage
                    for stage in job.stages
                    if not stage.bootstrap
                    and stage.state
                    in {
                        StageState.SUCCEEDED,
                        StageState.FAILED,
                        StageState.VALIDATING,
                        StageState.RUNNING,
                    }
                ]
                succeeded = sum(stage.state == StageState.SUCCEEDED for stage in attempted)
            result = BuildSummary(
                status="failed",
                engines_run=len(attempted),
                success=succeeded,
                failed=len(attempted) - succeeded,
                errors=[str(error)],
            )
        finally:
            with self._lock:
                now = datetime.now(UTC)
                job.finished_at = job.updated_at = now
                job.elapsed_seconds = round(monotonic() - self._started[job_id], 3)
                job.current_engine = None
                self._active = None
                # Finalization also runs if the hosting process is shutting down.
                job.result = result
                job.state = JobState.SUCCEEDED if result.status == "success" else JobState.FAILED
                for stage in job.stages:
                    if stage.state in {StageState.VALIDATING, StageState.RUNNING}:
                        stage.state = StageState.FAILED
                        stage.errors = [job.error or "Build interrupted"]
                        stage.finished_at = now
                    elif stage.state == StageState.PENDING:
                        stage.state = StageState.NOT_RUN
                snapshot = job.model_copy(deep=True)
        return snapshot


build_jobs = BuildJobs()
