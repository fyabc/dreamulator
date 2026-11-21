"""Local trial products use formal EBM fields and never write to their source world."""

from __future__ import annotations

from typing import TYPE_CHECKING

import msgpack
import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dreamulator.api_routes import climate_trials
from dreamulator.engine.climate import ClimateEngine
from dreamulator.map.cvt_mesh import generate_cvt_mesh
from dreamulator.map.export import MESH_FILENAME, load_cvt_mesh_model, save_cvt_mesh
from dreamulator.map.pipeline_types import TerrainPipelineConfig
from dreamulator.resolver import LayerResolver
from dreamulator.world_manager import WorldManager

if TYPE_CHECKING:
    from pathlib import Path

ENDPOINT = "/api/worlds/sample/maps/planet_gaia/climate-trials"


@pytest.fixture
def trial_world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Path, Path]:
    manager = WorldManager(tmp_path / "worlds")
    world = manager.create_world("sample", seed=5, template="earthlike")
    derived = world / "layers/astronomy/derived"
    derived.mkdir(parents=True)
    (derived / "stellar_derived.yaml").write_text("{}\n", encoding="utf-8")
    config_path = world / "layers/geological/input/terrain_config.yaml"
    config_path.write_text("terrain:\n  export_width: 128\n  export_height: 64\n", encoding="utf-8")
    branch = world / "branches/pinned"
    branch.mkdir(parents=True)
    (branch / "branch.yaml").write_text(
        "name: pinned\nfork_layer: climate\nclimate_source: gcm\n", encoding="utf-8"
    )
    monkeypatch.setattr(climate_trials, "_manager", manager)
    monkeypatch.setattr(climate_trials, "_runs", {})
    monkeypatch.setenv("DREAMULATOR_CLIMATE_WORKERS", "1")
    app = FastAPI()
    app.include_router(climate_trials.router)
    return TestClient(app), world, world / "maps/planet_gaia" / MESH_FILENAME


def test_trial_requires_correct_body_mesh_and_ignores_reference_root(trial_world) -> None:
    client, world, _ = trial_world
    other_mesh = world / "maps/planet_other" / MESH_FILENAME
    save_cvt_mesh(other_mesh, {"num_cells": 0, "cells": []})
    assert client.get(f"{ENDPOINT}/inputs").json() == {"detail": "build_mesh"}
    assert client.get(f"{ENDPOINT}/inputs", params={"branch": "missing"}).status_code == 404
    assert client.post(ENDPOINT, json={"branch": ".."}).status_code == 422
    assert client.post(ENDPOINT, json={"forcing": {"albedo": 2}}).status_code == 422
    world_yaml = world / "world.yaml"
    values = yaml.safe_load(world_yaml.read_text(encoding="utf-8"))
    values["reference_anchor"] = True
    world_yaml.write_text(yaml.safe_dump(values), encoding="utf-8")
    assert client.post(ENDPOINT, json={}).json() == {"detail": "reference_anchor"}


def test_branch_trial_matches_formal_ebm_and_drops_inherited_results(trial_world, tmp_path) -> None:
    client, world, mesh_path = trial_world
    mesh = generate_cvt_mesh(TerrainPipelineConfig(num_nodes=320, lloyd_iterations=1, seed=5))
    for cell in mesh.cells:
        cell.elevation = 500.0 if cell.lon < 0 else -500.0
        cell.cloud_total_frac = 0.7
        cell.biome = "inherited"
    save_cvt_mesh(mesh_path, mesh)
    before = {path: path.read_bytes() for path in world.rglob("*") if path.is_file()}
    response = client.get(f"{ENDPOINT}/inputs", params={"branch": "pinned"})
    assert response.status_code == 200
    assert response.json()["axial_tilt_deg"] == 23.4

    response = client.post(ENDPOINT, json={"branch": "pinned"})
    assert response.status_code == 202
    assert response.json()["state"] == "queued"
    job_id = response.json()["id"]
    status = client.get(f"{ENDPOINT}/{job_id}").json()
    assert status["state"] == "succeeded", status
    assert status["cells"] == 320
    assert status["stage"] == "export"
    assert client.get(f"{ENDPOINT}/{job_id}/products/yearly").status_code == 200
    assert client.get(f"{ENDPOINT}/{job_id}/products/geometry").status_code == 200
    assert client.get(f"{ENDPOINT}/{job_id}/products/fields").status_code == 200
    assert (
        client.get(ENDPOINT.replace("planet_gaia", "planet_other") + f"/{job_id}").status_code
        == 404
    )
    assert client.get(f"{ENDPOINT}/{job_id}/products/request.json").status_code == 422

    trial_dir = climate_trials._runs[job_id].output
    trial = load_cvt_mesh_model(trial_dir / MESH_FILENAME)
    assert all(cell.cloud_total_frac is None and cell.biome is None for cell in trial.cells)
    assert all(cell.koppen_class for cell in trial.cells)

    layers = LayerResolver(world).resolve_all_layers()
    formal_maps = tmp_path / "formal-maps"
    formal_output = tmp_path / "formal-derived"
    formal_output.mkdir()
    formal = ClimateEngine(
        world,
        5,
        layer_input_dirs={
            layer.value: source.input_dir for layer, source in layers.items() if source.input_dir
        },
        layer_derived_dirs={
            layer.value: source.derived_dir
            for layer, source in layers.items()
            if source.derived_dir
        },
        maps_output_dir=formal_maps,
        layer_output_dir=formal_output,
    ).run()
    assert formal.success, formal.warnings
    formal_dir = formal_maps / "planet_gaia"
    for actual, expected in zip(
        trial.cells, load_cvt_mesh_model(formal_dir / MESH_FILENAME).cells, strict=True
    ):
        assert (actual.temperature_C, actual.precipitation_mm, actual.koppen_class) == (
            expected.temperature_C,
            expected.precipitation_mm,
            expected.koppen_class,
        )
    trial_monthly = client.get(f"{ENDPOINT}/{job_id}/products/monthly")
    assert trial_monthly.status_code == 200
    assert msgpack.unpackb(trial_monthly.content) == msgpack.unpackb(
        (formal_dir / "climate_monthly.msgpack").read_bytes()
    )
    assert {path: path.read_bytes() for path in world.rglob("*") if path.is_file()} == before
