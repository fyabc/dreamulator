"""Tests for the parameter lab read/save/save-as-branch API."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dreamulator.api_routes import worlds as worlds_module
from dreamulator.world_manager import WorldManager

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    manager = WorldManager(tmp_path / "worlds")
    manager.create_world("sample", seed=42)
    monkeypatch.setattr(worlds_module, "_manager", manager)
    app = FastAPI()
    app.include_router(worlds_module.router)
    with TestClient(app) as client:
        yield client, manager


def _lab(client: TestClient, branch: str | None = None) -> dict:
    params = {"planet": "planet_terra"}
    if branch:
        params["branch"] = branch
    response = client.get("/api/worlds/sample/parameter-lab", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _value(state: dict, parameter_id: str) -> float | None:
    return next(item["value"] for item in state["parameters"] if item["id"] == parameter_id)


def test_read_lab_returns_registry_values(setup) -> None:
    client, _ = setup
    state = _lab(client)
    assert state["planet"] == "planet_terra"
    assert state["read_only"] is False
    assert len(state["parameters"]) == 4
    assert _value(state, "planet.axial_tilt_deg") == 23.4
    assert _value(state, "planet.albedo") == 0.3
    assert _value(state, "planet.greenhouse_warming_k") == 33.0


def test_save_lab_writes_the_planet_file(setup) -> None:
    client, manager = setup
    state = _lab(client)
    response = client.put(
        "/api/worlds/sample/parameter-lab",
        params={"planet": "planet_terra"},
        json={"revision": state["revision"], "values": {"planet.albedo": 0.35}},
    )
    assert response.status_code == 200, response.text
    updated = response.json()
    assert _value(updated, "planet.albedo") == 0.35
    assert updated["affected"] == ["astronomy", "climate"]
    assert updated["start_layer"] == "astronomy"

    path = manager.world_dir("sample") / "layers/geological/input/planets.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["planets"][0]["albedo"] == 0.35


def test_save_rejects_a_stale_revision(setup) -> None:
    client, _ = setup
    response = client.put(
        "/api/worlds/sample/parameter-lab",
        params={"planet": "planet_terra"},
        json={"revision": "stale", "values": {"planet.albedo": 0.4}},
    )
    assert response.status_code == 409


def test_save_rejects_out_of_range_values(setup) -> None:
    client, _ = setup
    state = _lab(client)
    response = client.put(
        "/api/worlds/sample/parameter-lab",
        params={"planet": "planet_terra"},
        json={"revision": state["revision"], "values": {"planet.albedo": 1.5}},
    )
    assert response.status_code == 422


def test_save_as_branch_forks_at_the_earliest_consumer(setup) -> None:
    client, manager = setup
    response = client.post(
        "/api/worlds/sample/parameter-lab/branch",
        params={"planet": "planet_terra"},
        json={"name": "albedo-high", "values": {"planet.albedo": 0.4}},
    )
    assert response.status_code == 200, response.text
    state = response.json()
    assert state["branch"] == "albedo-high"
    assert state["fork_layer"] == "astronomy"
    assert _value(state, "planet.albedo") == 0.4

    branch_file = (
        manager.world_dir("sample") / "branches/albedo-high/layers/geological/input/planets.yaml"
    )
    data = yaml.safe_load(branch_file.read_text(encoding="utf-8"))
    assert data["planets"][0]["albedo"] == 0.4

    assert _value(_lab(client, "albedo-high"), "planet.albedo") == 0.4


def test_save_as_branch_for_climate_only_parameter_forks_at_climate(setup) -> None:
    client, manager = setup
    response = client.post(
        "/api/worlds/sample/parameter-lab/branch",
        params={"planet": "planet_terra"},
        json={"name": "warm-greenhouse", "values": {"planet.greenhouse_warming_k": 40.0}},
    )
    assert response.status_code == 200, response.text
    state = response.json()
    assert state["fork_layer"] == "climate"
    assert _value(state, "planet.greenhouse_warming_k") == 40.0
    branch_file = (
        manager.world_dir("sample")
        / "branches/warm-greenhouse/layers/geological/input/planets.yaml"
    )
    assert (
        yaml.safe_load(branch_file.read_text(encoding="utf-8"))["planets"][0]["atmosphere"][
            "greenhouse_factor"
        ]
        == 40.0
    )
    assert _value(_lab(client, "warm-greenhouse"), "planet.greenhouse_warming_k") == 40.0


def test_branch_blocks_parameters_before_its_fork_layer(setup) -> None:
    client, manager = setup
    from dreamulator.branch_manager import BranchManager

    BranchManager(manager.world_dir("sample")).create_branch("climate-dev", "climate")
    state = _lab(client, "climate-dev")
    tilt = next(item for item in state["parameters"] if item["id"] == "planet.axial_tilt_deg")
    greenhouse = next(
        item for item in state["parameters"] if item["id"] == "planet.greenhouse_warming_k"
    )
    assert tilt["editable"] is False and tilt["reason"] == "fork"
    assert greenhouse["editable"] is True

    response = client.put(
        "/api/worlds/sample/parameter-lab",
        params={"planet": "planet_terra", "branch": "climate-dev"},
        json={"revision": None, "values": {"planet.axial_tilt_deg": 30.0}},
    )
    assert response.status_code == 409
