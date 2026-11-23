from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dreamulator.api_routes import region_refinement as routes
from dreamulator.build_jobs import BuildBusyError, BuildJobs, BuildSummary
from dreamulator.region_jobs import RSS_LIMIT, RegionJobs, RegionPlan, RegionWork

PREFIX = "/api/region-refinement"
PACK_SOURCE = {"kind": "pack", "pack": "test-coast"}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    root = tmp_path / "packs"
    td_repo = tmp_path / "td"
    python = td_repo / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    python.touch()
    monkeypatch.setenv("DREAMULATOR_TD_DIR", str(td_repo))
    monkeypatch.setenv("DREAMULATOR_PACKS_DIR", str(root))
    monkeypatch.setattr(routes, "available_memory_bytes", lambda: 2 * RSS_LIMIT)
    monkeypatch.setattr("dreamulator.region_jobs.available_memory_bytes", lambda: 2 * RSS_LIMIT)
    monkeypatch.setattr(routes, "region_jobs", RegionJobs())
    pack = root / PACK_SOURCE["pack"]
    source = pack / "input"
    source.mkdir(parents=True)
    (source / "meta.json").write_text(
        json.dumps(
            {
                "span_km": 100,
                "grid": {"w": 256, "h": 256},
                "projection": "azimuthal_equidistant",
                "extent_km": {"x": 100, "y": 100},
                "refinement_inputs": {"temperature_basis": "surface"},
                "cell_pitch_km": 0.5,
            }
        ),
        encoding="utf-8",
    )
    (source / "height.meters.npy").write_bytes(b"input")
    app = FastAPI()
    app.include_router(routes.router)
    return TestClient(app), root, pack, td_repo


@pytest.mark.parametrize("name, kind", [("NVIDIA L20", "gpu"), (None, "cpu")])
def test_local_compute_device(setup, monkeypatch, name, kind):
    client, _, _, td_repo = setup

    def probe(repo):
        assert repo == td_repo
        return name

    monkeypatch.setattr(routes, "td_compute_device", probe)
    assert client.get(f"{PREFIX}/device").json() == {"kind": kind, "name": name, "reason": None}


def test_unavailable_compute_device(setup, monkeypatch):
    client, _, _, _ = setup

    def timeout(_repo):
        raise subprocess.TimeoutExpired("td-device", 15)

    monkeypatch.setattr(routes, "td_compute_device", timeout)
    assert client.get(f"{PREFIX}/device").json() == {
        "kind": "unavailable",
        "name": None,
        "reason": "device_probe_failed",
    }
    monkeypatch.delenv("DREAMULATOR_TD_DIR")
    assert client.get(f"{PREFIX}/device").json() == {
        "kind": "unavailable",
        "name": None,
        "reason": "td_dir_missing",
    }


def test_windows_td_venv_layout_is_supported(tmp_path, monkeypatch):
    td_repo = tmp_path / "td-win"
    python = td_repo / ".venv/Scripts/python.exe"
    python.parent.mkdir(parents=True)
    python.touch()
    monkeypatch.setenv("DREAMULATOR_TD_DIR", str(td_repo))
    monkeypatch.setattr(
        routes,
        "td_compute_device",
        lambda repo: "NVIDIA GeForce RTX 3060" if repo == td_repo else None,
    )
    app = FastAPI()
    app.include_router(routes.router)
    client = TestClient(app)
    assert client.get(f"{PREFIX}/device").json() == {
        "kind": "gpu",
        "name": "NVIDIA GeForce RTX 3060",
        "reason": None,
    }


def test_pack_preflight(setup, monkeypatch):
    client, _, pack, _ = setup
    response = client.post(f"{PREFIX}/plan", json=PACK_SOURCE)
    assert response.json() == {
        "span_km": 100,
        "input_px": 256,
        "output_px": 512,
        "native_scale_km": 0.5,
        "mode": "redraw",
        "native_resolution_km": None,
        "preserve_wavelength_km": None,
        "river_threshold": None,
    }
    meta_file = pack / "input/meta.json"
    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    meta.update(span_km=551, extent_km={"x": 551, "y": 551})
    meta_file.write_text(json.dumps(meta), encoding="utf-8")
    assert client.post(f"{PREFIX}/jobs", json=PACK_SOURCE).status_code == 422
    meta.update(span_km=100, extent_km={"x": 100, "y": 100}, grid={"w": 2048, "h": 2048})
    meta_file.write_text(json.dumps(meta), encoding="utf-8")
    assert client.post(f"{PREFIX}/jobs", json=PACK_SOURCE).status_code == 422
    monkeypatch.setattr(routes, "available_memory_bytes", lambda: 2 * RSS_LIMIT - 1)
    assert client.post(f"{PREFIX}/plan", json=PACK_SOURCE).status_code == 503
    monkeypatch.delenv("DREAMULATOR_TD_DIR")
    assert "DREAMULATOR_TD_DIR" in client.post(f"{PREFIX}/plan", json=PACK_SOURCE).json()["detail"]


def test_preflight_blend_requires_spacing_larger_than_output_pixel(setup):
    client, _, _, _ = setup
    source = {**PACK_SOURCE, "mode": "blend"}
    for spacing in (0, 0.19, "inf"):
        response = client.post(f"{PREFIX}/plan", json={**source, "native_resolution_km": spacing})
        assert response.status_code == 422
    response = client.post(f"{PREFIX}/plan", json={**source, "native_resolution_km": 0.36})
    assert response.status_code == 200
    assert response.json()["mode"] == "blend"
    assert response.json()["native_resolution_km"] == 0.36


def test_preflight_blend_defaults_to_recorded_input_spacing(setup):
    client, _, pack, _ = setup
    source = {**PACK_SOURCE, "mode": "blend"}
    assert client.post(f"{PREFIX}/plan", json=source).json()["native_resolution_km"] == 0.5
    path = pack / "input/meta.json"
    meta = json.loads(path.read_text(encoding="utf-8"))
    meta["source"] = {"px_km": 9.77}
    path.write_text(json.dumps(meta), encoding="utf-8")
    plan = client.post(f"{PREFIX}/plan", json=source).json()
    assert plan["native_scale_km"] == plan["native_resolution_km"] == 9.77


def test_preflight_applies_only_valid_settings(setup):
    client, _, _, _ = setup
    blend = {**PACK_SOURCE, "mode": "blend", "native_resolution_km": 0.36}
    for source in (
        {**blend, "preserve_wavelength_km": 0.7},
        {**PACK_SOURCE, "preserve_wavelength_km": 1.6},
        {**PACK_SOURCE, "river_threshold": 0},
        {**PACK_SOURCE, "river_threshold": 1.5},
        {**PACK_SOURCE, "river_threshold": 2**31},
    ):
        assert client.post(f"{PREFIX}/plan", json=source).status_code == 422
    response = client.post(
        f"{PREFIX}/plan", json={**blend, "preserve_wavelength_km": 1.6, "river_threshold": 9000}
    )
    assert response.status_code == 200
    assert response.json()["preserve_wavelength_km"] == 1.6
    assert response.json()["river_threshold"] == 9000


def test_hydrology_job_does_not_require_td(setup, monkeypatch):
    client, _, _, _ = setup
    monkeypatch.delenv("DREAMULATOR_TD_DIR")

    def run_worker(_jobs, job, work, staging, _cancelled):
        assert job.plan.mode == "hydrology"
        assert job.plan.river_threshold == 9000
        assert work.td is None
        output = staging / "pack/refined-out"
        output.mkdir(parents=True)
        (output / "height.meters.npy").write_bytes(b"result")

    monkeypatch.setattr(RegionJobs, "_run_worker", run_worker)
    response = client.post(
        f"{PREFIX}/jobs", json={**PACK_SOURCE, "mode": "hydrology", "river_threshold": 9000}
    )
    assert response.status_code == 202
    job = client.get(f"{PREFIX}/jobs/{response.json()['id']}").json()
    assert job["state"] == "succeeded"
    assert job["plan"]["mode"] == "hydrology"


def test_world_requires_monthly_climate(setup, tmp_path, monkeypatch):
    client, _, _, _ = setup
    monkeypatch.setenv("DREAMULATOR_DATA_DIR", str(tmp_path))
    world = tmp_path / "test-world"
    world.mkdir()
    (world / "world.yaml").write_text("name: test-world\n", encoding="utf-8")
    maps = world / "maps" / "planet_gaia"
    maps.mkdir(parents=True)
    (maps / "cvt_mesh.json").touch()
    monkeypatch.setattr(routes.MapManager, "get_map_metadata", lambda *_: SimpleNamespace())
    response = client.post(
        f"{PREFIX}/plan",
        json={
            "kind": "world",
            "world": "test-world",
            "planet": "planet_gaia",
            "lat": 45,
            "lon": -123,
            "span_km": 550,
        },
    )
    assert response.status_code == 422
    assert "monthly climate" in response.json()["detail"]


@pytest.mark.parametrize("state", ["succeeded", "cancelled", "failed"])
def test_job_publication_is_atomic(setup, monkeypatch, state):
    client, root, pack, _ = setup

    def run_worker(self, job, work, staging, cancelled):
        assert work.pack == pack
        output = staging / "pack/refined-out"
        output.mkdir(parents=True)
        (output / "height.meters.npy").write_bytes(b"result")
        if state == "cancelled":
            self.get(job.id, cancel=True)
            assert cancelled.is_set()
        if state == "failed":
            raise RuntimeError("Test worker failed")

    monkeypatch.setattr(RegionJobs, "_run_worker", run_worker)
    response = client.post(f"{PREFIX}/jobs", json=PACK_SOURCE)
    assert response.status_code == 202
    key = response.json()["id"]
    job = client.get(f"{PREFIX}/jobs/{key}").json()
    assert job["state"] == state
    assert list(root.glob(".refinement-*")) == []
    assert (pack / "input/height.meters.npy").read_bytes() == b"input"
    results = list(root.glob("web-region-*"))
    if state == "succeeded":
        assert results == [root / job["result_pack"]]
        assert (results[0] / "refined-out/height.meters.npy").read_bytes() == b"result"
    else:
        assert results == []
        assert job["result_pack"] is None
        assert job["error"] == ("Test worker failed" if state == "failed" else None)


def test_region_and_world_build_share_compute_slot(setup):
    client, root, _, td_repo = setup
    builds = BuildJobs()
    build = builds.reserve(root, branch=None, engine=None, force=False)
    try:
        assert client.post(f"{PREFIX}/jobs", json=PACK_SOURCE).status_code == 409
    finally:
        builds.execute(build.id, lambda _: BuildSummary(status="success"))

    plan = RegionPlan(span_km=100, input_px=256, output_px=512, native_scale_km=None)
    job = routes.region_jobs.reserve(plan)
    try:
        with pytest.raises(BuildBusyError):
            builds.reserve(root, branch=None, engine=None, force=False)
        assert client.post(f"{PREFIX}/jobs/{job.id}/cancel").status_code == 200
    finally:
        routes.region_jobs.get(job.id, cancel=True)
        routes.region_jobs.execute(job.id, RegionWork(root, td_repo))
    assert client.get(f"{PREFIX}/jobs/{job.id}").json()["state"] == "cancelled"
