"""Official grid editing preserves the active map and respects branch boundaries."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dreamulator.api_routes import worlds as worlds_route
from dreamulator.branch_manager import BranchManager
from dreamulator.build_jobs import local_compute_slot
from dreamulator.engine.physical_inputs import resolve_and_apply_physical_parameters
from dreamulator.engine.pipeline import _is_dirty
from dreamulator.map.pipeline_types import TerrainPipelineConfig
from dreamulator.models.layers import Layer
from dreamulator.resolver import LayerResolver
from dreamulator.world_manager import WorldManager
from dreamulator.world_parameters import grid_engine

if TYPE_CHECKING:
    from pathlib import Path

ROOT = "/api/worlds/grid-world/world-parameters"


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Path]:
    manager = WorldManager(tmp_path)
    world = manager.create_world("grid-world", template="minimal", seed=42)
    monkeypatch.setattr(worlds_route, "_manager", manager)
    api = FastAPI()
    api.include_router(worlds_route.router)
    return TestClient(api), world


def test_save_targets_existing_formal_input_and_leaves_old_map(workspace: tuple[TestClient, Path]):
    client, world = workspace
    grid = client.get(ROOT).json()
    assert grid["num_cells"] == 100_000
    assert grid["built_cells"] is None
    planet = world / "layers/geological/input/planets.yaml"
    initial = planet.read_text(encoding="utf-8")
    response = client.put(ROOT, json={"num_cells": 256, "revision": grid["revision"]})
    assert response.status_code == 200, response.text
    assert response.json()["num_cells"] == 256
    assert not (world / "maps").exists()

    map_dir = world / "maps/planet_terra"
    map_dir.mkdir(parents=True)
    files = {"map.yaml": "voronoi_num_cells: 256\n", "cvt_mesh.msgpack.gz": "mesh"}
    for filename, data in files.items():
        (map_dir / filename).write_text(data, encoding="utf-8")
    saved = client.put(ROOT, json={"num_cells": 320, "revision": response.json()["revision"]})
    assert saved.status_code == 200, saved.text
    assert saved.json()["built_cells"] == 256
    assert saved.json()["num_cells"] == 320
    assert (map_dir / "cvt_mesh.msgpack.gz").read_text(encoding="utf-8") == "mesh"
    assert (map_dir / "map.yaml").read_text(encoding="utf-8") == files["map.yaml"]
    updated = planet.read_text(encoding="utf-8")
    assert "# Planets for the minimal template" in updated
    inputs = yaml.safe_load(initial)
    inputs["planets"][0]["terrain"] = {"num_nodes": 320}
    assert yaml.safe_load(updated) == inputs
    assert _is_dirty(grid_engine(LayerResolver(world), 42))
    assert client.get("/api/worlds/grid-world/build-grid").json()["num_cells"] == 320


def test_branch_overrides_only_owned_geology_and_preserves_yaml(workspace: tuple[TestClient, Path]):
    client, world = workspace
    terrain = world / "layers/geological/input/terrain_config.yaml"
    config = "# author note\nterrain:\n  num_nodes: 400\n  voronoi_num_cells: 420 # active\n"
    terrain.write_text(config, encoding="utf-8")
    branches = BranchManager(world)
    fork = branches.create_branch("local-grid", Layer.GEOLOGICAL)
    late = branches.create_branch("climate-only", Layer.CLIMATE)
    url = f"{ROOT}?branch=local-grid"
    settings = client.get(url).json()
    assert settings["num_cells"] == 420
    assert settings["source"].startswith("layers/")
    saved = client.put(url, json={"num_cells": 500, "revision": settings["revision"]})
    assert saved.status_code == 200, saved.text
    assert saved.json()["num_cells"] == 500
    assert saved.json()["source"].startswith("branches/local-grid/")
    assert terrain.read_text(encoding="utf-8") == config
    assert (fork / "layers/geological/input/terrain_config.yaml").read_text(
        encoding="utf-8"
    ) == config.replace("420", "500")
    assert client.get(f"{ROOT}?branch=climate-only").json()["read_only"] == "inherited"
    assert (
        client.put(
            f"{ROOT}?branch=climate-only", json={"num_cells": 100, "revision": "0" * 64}
        ).status_code
        == 409
    )
    assert not (late / "layers/geological/input/terrain_config.yaml").exists()


def test_revision_validation_busy_and_reference_protection(workspace: tuple[TestClient, Path]):
    client, world = workspace
    settings = client.get(ROOT).json()
    update = {"num_cells": 512, "revision": settings["revision"]}
    for invalid in (99, 200_001, True, 200.5, "400"):
        assert client.put(ROOT, json={**update, "num_cells": invalid}).status_code == 422
    with local_compute_slot:
        assert client.put(ROOT, json=update).status_code == 409
    assert client.put(ROOT, json=update).status_code == 200
    assert client.put(ROOT, json={**update, "num_cells": 1024}).status_code == 409
    planet = world / "layers/geological/input/planets.yaml"
    original = planet.read_bytes()
    config = world / "world.yaml"
    data = yaml.safe_load(config.read_text(encoding="utf-8"))
    config.write_text(yaml.safe_dump({**data, "reference_anchor": True}), encoding="utf-8")
    assert client.get(ROOT).json()["read_only"] == "reference"
    assert client.put(ROOT, json=update).status_code == 409
    assert planet.read_bytes() == original


def test_save_planet_updates_formal_forcing_without_rewriting_results(workspace):
    client, world = workspace
    planet_path = world / "layers/geological/input/planets.yaml"
    existing = yaml.safe_load(planet_path.read_text(encoding="utf-8"))
    summary = world / "layers/climate/derived/climate_summary.yaml"
    summary.parent.mkdir(parents=True)
    summary.write_text("planet_id: planet_terra\n", encoding="utf-8")
    before = client.get(ROOT).json()["planet"]
    assert before["id"] == "planet_terra"
    assert not before["needs_rebuild"]
    values = {"rotation_period_days": 1.75, "albedo": 0.0}
    update = {"planet": values, "revision": before["revision"]}
    for invalid in ({"rotation_period_days": 0}, {"albedo": 1.01}, {"albedo": True}):
        assert client.put(ROOT, json={**update, "planet": values | invalid}).status_code == 422
    with local_compute_slot:
        assert client.put(ROOT, json=update).status_code == 409
    result = client.put(ROOT, json=update)
    assert result.status_code == 200, result.text
    assert result.json()["planet"]["needs_rebuild"]
    assert client.put(ROOT, json=update).status_code == 409
    assert summary.read_text(encoding="utf-8") == "planet_id: planet_terra\n"
    existing["planets"][0].update(values)
    assert yaml.safe_load(planet_path.read_text(encoding="utf-8")) == existing
    config = TerrainPipelineConfig()
    resolve_and_apply_physical_parameters(grid_engine(LayerResolver(world), 42), config)
    assert config.rotation_period_days == 1.75
    assert config.albedo == 0.0
    new_mtime = planet_path.stat().st_mtime_ns + 1_000_000
    os.utime(summary, ns=(new_mtime, new_mtime))
    assert not client.get(ROOT).json()["planet"]["needs_rebuild"]


def test_planet_settings_follow_geological_branch_and_reference_protection(workspace):
    client, world = workspace
    planet_path = world / "layers/geological/input/planets.yaml"
    original = planet_path.read_bytes()
    branches = BranchManager(world)
    branch = branches.create_branch("local-planet", Layer.GEOLOGICAL)
    inherited = branches.create_branch("climate-only", Layer.CLIMATE)
    url = f"{ROOT}?branch=local-planet"
    update = {
        "planet": {"rotation_period_days": 0.5, "albedo": 0.4},
        "revision": client.get(url).json()["planet"]["revision"],
    }
    result = client.put(url, json=update)
    assert result.status_code == 200, result.text
    assert result.json()["planet"]["source"].startswith("branches/local-planet/")
    assert (branch / "layers/geological/input/planets.yaml").exists()
    assert not (inherited / "layers/geological/input/planets.yaml").exists()
    inherited_url = f"{ROOT}?branch=climate-only"
    assert client.get(inherited_url).json()["planet"]["read_only"] == "inherited"
    assert client.put(inherited_url, json=update).status_code == 409
    config_path = world / "world.yaml"
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config_path.write_text(yaml.safe_dump({**data, "reference_anchor": True}), encoding="utf-8")
    assert client.get(ROOT).json()["planet"]["read_only"] == "reference"
    assert client.put(ROOT, json=update).status_code == 409
    assert planet_path.read_bytes() == original
