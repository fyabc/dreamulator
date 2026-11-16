"""Observe actual pipeline boundaries, concurrent HTTP reads, and failure recovery."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from typing import TYPE_CHECKING

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dreamulator import engine as engine_module
from dreamulator.api_routes import worlds as worlds_module
from dreamulator.build_jobs import BuildJobs, BuildSummary
from dreamulator.engine.base import BaseEngine, EngineResult
from dreamulator.engine.pipeline import run_pipeline
from dreamulator.engine.progress import StageState
from dreamulator.models.layers import Layer
from dreamulator.world_manager import WorldManager

if TYPE_CHECKING:
    from pathlib import Path


class FirstEngine(BaseEngine):
    name = "first"
    layer = Layer.ASTRONOMY
    output_files = ["first.json"]

    def run(self, parameters=None, *, force=False):
        self.output_path("first.json").write_text('{"value": 42}', encoding="utf-8")
        return EngineResult(engine_name=self.name, success=True)


class LastEngine(FirstEngine):
    name = "last"
    layer = Layer.CLIMATE
    requires = ["first"]
    output_files = ["last.json"]

    def run(self, parameters=None, *, force=False):
        self.output_path("last.json").write_text('{"value": 43}', encoding="utf-8")
        return EngineResult(engine_name=self.name, success=True)


@pytest.fixture
def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    manager = WorldManager(tmp_path / "worlds")
    manager.create_world("sample", seed=42)
    manager.create_world("other", seed=42)
    jobs = BuildJobs()
    monkeypatch.setattr(worlds_module, "_manager", manager)
    monkeypatch.setattr(worlds_module, "build_jobs", jobs)
    monkeypatch.setattr(engine_module, "get_all_engines", lambda: [FirstEngine, LastEngine])
    app = FastAPI()
    app.include_router(worlds_module.router)
    with TestClient(app) as client:
        yield client, manager, jobs


def test_results_cache_and_forced_target(setup):
    client, manager, _ = setup
    world = manager.world_dir("sample")
    response = client.post("/api/worlds/sample/build-jobs")
    assert response.status_code == 202
    assert response.json()["state"] == "queued"
    job_id = response.json()["id"]
    first = client.get(f"/api/worlds/sample/build-jobs/{job_id}").json()
    assert first["state"] == "succeeded"
    assert [s["state"] for s in first["stages"]] == ["succeeded", "succeeded"]
    assert first["result"]["engines_run"] == 2
    assert first["started_at"] and first["finished_at"]
    assert first["current_engine"] is None
    original = (world / "layers/astronomy/derived/first.json").read_bytes()
    cached = client.post("/api/worlds/sample/build-jobs").json()
    second = client.get(f"/api/worlds/sample/build-jobs/{cached['id']}").json()
    assert [s["state"] for s in second["stages"]] == ["skipped", "skipped"]
    assert second["result"]["engines_run"] == 0
    forced = client.post(
        "/api/worlds/sample/build-jobs", json={"engine": "last", "force": True}
    ).json()
    third = client.get(f"/api/worlds/sample/build-jobs/{forced['id']}").json()
    assert [s["state"] for s in third["stages"]] == ["skipped", "succeeded"]
    assert (world / "layers/astronomy/derived/first.json").read_bytes() == original
    assert client.get(f"/api/worlds/other/build-jobs/{job_id}").status_code == 404


def test_http_reads_and_duplicate_rejection_during_execution(setup, monkeypatch):
    client, _, jobs = setup
    entered, release = Event(), Event()
    reserved = []
    reserve = jobs.reserve

    def record(*args, **kwargs):
        job = reserve(*args, **kwargs)
        reserved.append(job.id)
        return job

    def pause(self, parameters=None, *, force=False):
        entered.set()
        assert release.wait(timeout=10)
        return EngineResult(engine_name=self.name, success=True)

    monkeypatch.setattr(jobs, "reserve", record)
    monkeypatch.setattr(FirstEngine, "run", pause)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(client.post, "/api/worlds/sample/build-jobs")
        try:
            assert entered.wait(timeout=5)
            running = client.get(f"/api/worlds/sample/build-jobs/{reserved[0]}")
            assert running.status_code == 200
            assert running.json()["current_engine"] == "first"
            assert running.json()["state"] == "running"
            assert running.json()["stages"][1]["state"] == "pending"
            assert client.post("/api/worlds/sample/build-jobs").status_code == 409
            assert client.post("/api/worlds/other/build").status_code == 409
        finally:
            release.set()
        assert future.result(timeout=5).status_code == 202


@pytest.mark.parametrize("failure", ["validation", "result", "exception"])
def test_failures_preserve_reason_and_release_writer(setup, monkeypatch, failure):
    client, _, _ = setup
    reason = "Missing required terrain"
    if failure == "validation":
        monkeypatch.setattr(FirstEngine, "validate_inputs", lambda self: [reason])
    else:

        def fail(self, parameters=None, *, force=False):
            if failure == "exception":
                raise RuntimeError(reason)
            return EngineResult(engine_name=self.name, success=False, warnings=[reason])

        monkeypatch.setattr(FirstEngine, "run", fail)
    response = client.post("/api/worlds/sample/build-jobs")
    job = client.get(f"/api/worlds/sample/build-jobs/{response.json()['id']}").json()
    assert job["state"] == "failed"
    assert [s["state"] for s in job["stages"]] == ["failed", "not_run"]
    assert job["stages"][0]["errors"] == [reason]
    assert job["result"]["errors"] == [reason]
    assert client.post("/api/worlds/sample/build-jobs").status_code == 202
    legacy = client.post("/api/worlds/sample/build")
    assert legacy.status_code == (500 if failure == "exception" else 200)


def test_bad_requests_and_reference_root_never_write(setup):
    client, manager, _ = setup
    assert client.post("/api/worlds/missing/build-jobs").status_code == 404
    assert client.post("/api/worlds/sample/build-jobs", json={"engine": "bogus"}).status_code == 422
    assert (
        client.post("/api/worlds/sample/build-jobs", json={"branch": "missing"}).status_code == 404
    )
    assert client.post("/api/worlds/sample/build-jobs", json={"branch": ".."}).status_code == 422
    world = manager.world_dir("sample")
    config_path = world / "world.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["reference_anchor"] = True
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    before = {p.relative_to(world): p.read_bytes() for p in world.rglob("*") if p.is_file()}
    assert client.post("/api/worlds/sample/build-jobs").status_code == 409
    assert client.post("/api/worlds/sample/build").status_code == 409
    assert {p.relative_to(world): p.read_bytes() for p in world.rglob("*") if p.is_file()} == before


def test_branch_output_isolation_and_invalid_prefork_target(setup):
    client, manager, _ = setup
    world = manager.world_dir("sample")
    branch = world / "branches/test"
    branch.mkdir(parents=True)
    (branch / "branch.yaml").write_text(
        yaml.safe_dump({"name": "test", "fork_layer": "climate"}), encoding="utf-8"
    )
    assert (
        client.post(
            "/api/worlds/sample/build-jobs", json={"branch": "test", "engine": "first"}
        ).status_code
        == 422
    )
    response = client.post("/api/worlds/sample/build-jobs", json={"branch": "test", "force": True})
    job = client.get(f"/api/worlds/sample/build-jobs/{response.json()['id']}").json()
    assert job["branch"] == "test"
    assert [s["engine"] for s in job["stages"]] == ["last"]
    assert (branch / "layers/climate/derived/last.json").exists()
    assert not (world / "layers/climate/derived/last.json").exists()


def test_history_bound_and_snapshot_isolation(tmp_path):
    jobs = BuildJobs(history_limit=2)
    ids = []
    for _ in range(3):
        job = jobs.reserve(tmp_path, branch=None, engine=None, force=False)
        jobs.execute(job.id, lambda _: BuildSummary(status="success"))
        ids.append(job.id)
    with pytest.raises(KeyError):
        jobs.get(tmp_path, ids[0])
    snapshot = jobs.get(tmp_path, ids[-1])
    snapshot.world = "changed"
    assert jobs.get(tmp_path, ids[-1]).world == tmp_path.name


def test_exception_keeps_completed_stage_counts(setup, monkeypatch):
    client, _, _ = setup

    def fail(self, parameters=None, *, force=False):
        raise RuntimeError("Climate calculation stopped")

    monkeypatch.setattr(LastEngine, "run", fail)
    response = client.post("/api/worlds/sample/build-jobs")
    job = client.get(f"/api/worlds/sample/build-jobs/{response.json()['id']}").json()
    assert [s["state"] for s in job["stages"]] == ["succeeded", "failed"]
    assert job["result"]["engines_run"] == 2
    assert job["result"]["success"] == 1
    assert job["result"]["failed"] == 1


def test_observer_preserves_deterministic_outputs(tmp_path):
    events = []
    engines = [FirstEngine, LastEngine]
    run_pipeline(engines, tmp_path, 42, force=True)
    original = {
        p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.glob("layers/*/derived/*")
    }
    run_pipeline(engines, tmp_path, 42, force=True, on_progress=events.append)
    assert {
        p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.glob("layers/*/derived/*")
    } == original
    assert [(e.engine, e.state) for e in events if e.state == StageState.SUCCEEDED] == [
        ("first", StageState.SUCCEEDED),
        ("last", StageState.SUCCEEDED),
    ]
