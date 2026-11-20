"""Acceptance checks for API elevation imports consumed by the build pipeline."""

from __future__ import annotations

import gzip
import hashlib
import math
import os
import shutil
from typing import TYPE_CHECKING

import numpy as np
import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dreamulator.api_routes import maps as maps_module
from dreamulator.engine.astronomy import AstronomyEngine
from dreamulator.engine.climate import ClimateEngine
from dreamulator.engine.geological import GeologicalEngine
from dreamulator.engine.pipeline import run_pipeline
from dreamulator.map.elevation_input import SOURCE_MANIFEST, load_elevation_sources
from dreamulator.map.export import MESH_FILENAME, load_cvt_mesh
from dreamulator.map.manager import MapManager
from dreamulator.world_manager import WorldManager
from tests.test_map.test_import_elevation import _png8, _tiff_float

if TYPE_CHECKING:
    from pathlib import Path


def _write_yaml(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


@pytest.fixture
def imported_world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, TestClient]:
    manager = WorldManager(tmp_path / "worlds")
    world = manager.create_world("import-test", template="earthlike", seed=42)
    geo = world / "layers" / "geological" / "input"
    planets = yaml.safe_load((geo / "planets.yaml").read_text(encoding="utf-8"))
    planets["planets"][0]["radius"] = 0.5
    planets["planets"][0]["lithosphere"].pop("num_plates", None)
    _write_yaml(geo / "planets.yaml", planets)
    _write_yaml(geo / "terrain_config.yaml", {"num_nodes": 256, "lloyd_iterations": 1})
    _write_yaml(
        world / "maps" / "planet_gaia" / "map.yaml",
        {"planet_id": "planet_gaia", "width": 64, "height": 32},
    )
    app = FastAPI()
    app.include_router(maps_module.router)
    monkeypatch.setattr(maps_module, "_manager", manager)
    return world, TestClient(app)


def _upload(client: TestClient, *, branch: str | None = None, reverse: bool = False) -> None:
    grey = np.zeros((32, 64), np.uint8)
    grey[:, :32] = 255
    if reverse:
        grey = 255 - grey
    response = client.post(
        "/api/worlds/import-test/maps/planet_gaia/import-elevation",
        params={"branch": branch} if branch else {},
        files={"file": ("authored.png", _png8(grey), "image/png")},
        data={"mode": "threshold", "max_m": 4000, "seafloor_m": -2500},
    )
    assert response.status_code == 200, response.text


def _branch(world: Path, name: str, layer: str) -> None:
    _write_yaml(world / "branches" / name / "branch.yaml", {"name": name, "fork_layer": layer})


def _geo_build(world: Path, branch: str | None = None):
    results = run_pipeline(
        [AstronomyEngine, GeologicalEngine], world, seed=42, start_layer="geological", branch=branch
    )
    assert len(results) == 1 and results[0].success, results
    return results[0]


def test_import_build_and_deleted_products_reconstruct_from_input(imported_world) -> None:
    world, client = imported_world
    _upload(client)
    result = _geo_build(world)
    assert result.metadata["elevation_source"] == "imported"
    assert result.metadata["radius_km"] == pytest.approx(6371 * 0.5)
    mesh_path = world / "maps" / "planet_gaia" / MESH_FILENAME
    mesh = load_cvt_mesh(mesh_path)
    assert mesh["num_cells"] == 256
    for cell in mesh["cells"]:
        land = cell["lon"] < 0
        assert cell["elevation"] == (4000 if land else -2500)
        assert cell["water_class"] == ("land" if land else "ocean")
        assert cell["plate_id"] is None and cell["temperature_C"] is None
    assert sum(c["area_km2"] for c in mesh["cells"]) == pytest.approx(
        4 * math.pi * (6371 * 0.5) ** 2
    )
    assert not (mesh_path.parent / "voronoi.json").exists()
    assert MapManager(world).get_plates("planet_gaia") == []
    original = gzip.decompress(mesh_path.read_bytes())
    assert (
        run_pipeline([AstronomyEngine, GeologicalEngine], world, seed=42, start_layer="geological")
        == []
    )
    shutil.rmtree(world / "maps")
    _geo_build(world)
    assert gzip.decompress(mesh_path.read_bytes()) == original
    meta = MapManager(world).get_map_metadata("planet_gaia")
    assert meta is not None and meta.elevation_import is not None
    assert (meta.width, meta.height) == (64, 32)
    assert meta.elevation_import.source_filename == "authored.png"


def test_large_import_keeps_pixels_independent_of_mesh_size(imported_world):
    world, client = imported_world
    grey = np.full((2048, 4096), 12, np.uint8)
    grey[1024, 2048:2052] = [40, 220, 40, 220]
    response = client.post(
        "/api/worlds/import-test/maps/planet_gaia/import-elevation",
        files={"file": ("fine.png", _png8(grey), "image/png")},
    )
    assert response.status_code == 200, response.text
    assert response.json()["output_resolution"] == [4096, 2048]
    assert not response.json()["was_resampled"]
    _geo_build(world)
    mgr = MapManager(world)
    meta = mgr.get_map_metadata("planet_gaia")
    heightmap = mgr.get_elevation("planet_gaia")
    assert meta is not None and meta.voronoi_num_cells == 256
    assert heightmap is not None and heightmap.shape == grey.shape
    metres = meta.elevation_min_m + heightmap[1024, 2048:2052] * (
        meta.elevation_max_m - meta.elevation_min_m
    )
    assert metres == pytest.approx(-11000 + 20000 / 255 * grey[1024, 2048:2052], abs=0.2)


def test_full_climate_build_reads_imported_water_mask_and_sea_datum(imported_world, monkeypatch):
    world, client = imported_world
    heights = np.full((32, 64), 1000.0)
    heights[:, :32] = 5000.0
    response = client.post(
        "/api/worlds/import-test/maps/planet_gaia/import-elevation",
        files={"file": ("metres.tif", _tiff_float(heights), "image/tiff")},
        data={"mode": "metres", "sea_level_m": 2000},
    )
    assert response.status_code == 200, response.text
    from dreamulator.map import climate_simulator

    original = climate_simulator.simulate_climate
    used_datums = []

    def capture(mesh, config):
        used_datums.append(config.sea_level_offset_m)
        return original(mesh, config)

    monkeypatch.setattr(climate_simulator, "simulate_climate", capture)
    results = run_pipeline([AstronomyEngine, GeologicalEngine, ClimateEngine], world, seed=42)
    assert [r.engine_name for r in results] == ["astronomy", "geological", "climate"]
    assert all(r.success for r in results), results
    assert used_datums == [2000.0]
    mesh = load_cvt_mesh(world / "maps" / "planet_gaia" / MESH_FILENAME)
    for cell in mesh["cells"]:
        assert cell["water_class"] == ("land" if cell["lon"] < 0 else "ocean")
        assert cell["elevation"] == (5000 if cell["lon"] < 0 else 1000)
        assert np.isfinite(cell["temperature_C"])
        assert np.isfinite(cell["precipitation_mm"])
    assert MapManager(world).get_map_metadata("planet_gaia").sea_level_m == 2000


def test_geological_branch_import_and_inheritance_leave_parent_unchanged(imported_world):
    world, client = imported_world
    _upload(client)
    _geo_build(world)
    baseline = {
        p.relative_to(world): hashlib.sha256(p.read_bytes()).hexdigest()
        for folder in (world / "maps", world / "layers" / "geological" / "input")
        for p in folder.rglob("*")
        if p.is_file()
    }
    _branch(world, "inherited", "geological")
    _geo_build(world, "inherited")
    _branch(world, "reversed", "geological")
    _upload(client, branch="reversed", reverse=True)
    _geo_build(world, "reversed")
    for name, reversed_ in [("inherited", False), ("reversed", True)]:
        mesh = load_cvt_mesh(world / "branches" / name / "maps" / "planet_gaia" / MESH_FILENAME)
        for cell in mesh["cells"]:
            land = (cell["lon"] >= 0) if reversed_ else (cell["lon"] < 0)
            assert cell["water_class"] == ("land" if land else "ocean")
    for path, digest in baseline.items():
        assert hashlib.sha256((world / path).read_bytes()).hexdigest() == digest


@pytest.mark.parametrize("damage", ["missing", "corrupt", "invalid_manifest"])
def test_bad_retained_source_fails_even_with_existing_mesh(imported_world, damage):
    world, client = imported_world
    _upload(client)
    _geo_build(world)
    mesh_path = world / "maps" / "planet_gaia" / MESH_FILENAME
    original = mesh_path.read_bytes()
    geo = world / "layers" / "geological" / "input"
    manifest = geo / SOURCE_MANIFEST
    source = load_elevation_sources(manifest)["planet_gaia"]
    blob = geo / source.relative_path
    if damage == "missing":
        blob.unlink()
    elif damage == "corrupt":
        blob.write_bytes(b"broken image")
        newer = mesh_path.stat().st_mtime + 10
        os.utime(blob, (newer, newer))
    else:
        manifest.write_text("bad: [unclosed", encoding="utf-8")
    results = run_pipeline(
        [AstronomyEngine, GeologicalEngine], world, seed=42, start_layer="geological"
    )
    assert len(results) == 1 and not results[0].success
    assert mesh_path.read_bytes() == original


@pytest.mark.parametrize("target", ["earth", "reference", "climate_branch"])
def test_import_rejects_reference_roots_and_branches_that_inherit_geology(imported_world, target):
    world, client = imported_world
    name, params = "import-test", {}
    if target == "earth":
        world.rename(world.parent / "earth")
        world = world.parent / "earth"
        name = "earth"
    elif target == "reference":
        _write_yaml(world / "world.yaml", {"reference_anchor": True})
    else:
        _branch(world, "climate-only", "climate")
        params = {"branch": "climate-only"}
    response = client.post(
        f"/api/worlds/{name}/maps/planet_gaia/import-elevation",
        params=params,
        files={"file": ("map.png", _png8(np.zeros((4, 8))), "image/png")},
    )
    assert response.status_code == 400, response.text
    assert not list(world.rglob(SOURCE_MANIFEST))


def test_import_samples_at_the_coordinates_written_to_the_mesh(tmp_path: Path) -> None:
    """Decimal truncation near a source pixel edge must not move the sampled coast."""
    from dreamulator.map.elevation_input import sample_elevation_import
    from dreamulator.map.export import save_cvt_mesh
    from dreamulator.map.importer import import_heightmap_metres
    from dreamulator.map.models import CVTMesh, ElevationMapping, VoronoiCell

    longitude = -53.87696
    width = 4096
    original_column = int((longitude + 180) / 360 * width)
    saved_column = int((-53.8769 + 180) / 360 * width)
    assert saved_column == original_column + 1
    grey = np.zeros((2, width), dtype=np.uint8)
    grey[:, saved_column:] = 255
    imported = import_heightmap_metres(
        _png8(grey), ElevationMapping(mode="range", min_m=-2000, max_m=1000)
    )
    mesh = CVTMesh(seed=42, num_cells=1, cells=[VoronoiCell(id=0, lon=longitude, lat=0)])
    sample_elevation_import(mesh, imported)
    path = tmp_path / MESH_FILENAME
    save_cvt_mesh(path, mesh)
    saved = load_cvt_mesh(path)["cells"][0]
    assert saved["lon"] == -53.8769
    assert saved["elevation"] == 1000 and saved["water_class"] == "land"
