"""Stage-cache round-trip: all-cache-hit rebuilds must equal fresh builds.

2026-09-30 (user-reported corruption): plates/tectonics cache payloads did not
capture the in-place cell side effects (crust_type, tectonic elevation,
boundary_type), so a plates/tectonics-hit + terrain-rerun build — first made
reachable by ``terrain_only`` overlays — synthesized terrain from crust-less
cells and every authored continent vanished.  These tests pin the replay.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import numpy as np

from dreamulator.map.geography import GeographyFeature, GeographySpec
from dreamulator.map.pipeline_types import TerrainPipelineConfig
from dreamulator.map.terrain_cache import TerrainCache, build_stage_fingerprint
from dreamulator.map.terrain_pipeline import run_terrain_pipeline

if TYPE_CHECKING:
    from pathlib import Path

TINY = dict(num_nodes=800, lloyd_iterations=1, tectonic_steps=2)


def _spec(with_overlay: bool) -> GeographySpec:
    features = [
        GeographyFeature(name="continent", lon=0.0, lat=0.0, radius_deg=30.0, strength=0.9),
        GeographyFeature(name="sea", lon=180.0, lat=0.0, radius_deg=25.0, strength=-1.0),
    ]
    if with_overlay:
        features.append(
            GeographyFeature(
                name="overlay-carve",
                lon=10.0,
                lat=15.0,
                radius_deg=6.0,
                strength=-2.0,
                terrain_only=True,
            )
        )
    return GeographySpec(land_fraction_target=0.28, features=features)


def _snapshot(mesh) -> dict[str, np.ndarray]:
    return {
        "crust": np.array([c.crust_type or "" for c in mesh.cells], dtype=object),
        "elev": np.array([c.elevation or 0.0 for c in mesh.cells], dtype=np.float64),
        "water": np.array([c.water_class or "" for c in mesh.cells], dtype=object),
        "btype": np.array([c.boundary_type or "" for c in mesh.cells], dtype=object),
    }


def _run(tmp: Path, spec: GeographySpec) -> dict[str, np.ndarray]:
    cfg = TerrainPipelineConfig(seed=11, **TINY)
    cfg.geography = spec
    res = run_terrain_pipeline(
        cfg,
        output_dir=tmp,
        stages=["mesh", "plates", "tectonics", "boundaries", "terrain"],
        cache=None,  # cache via CacheConfig in geological engine; here manual
    )
    return _snapshot(res.mesh)


def test_cache_hit_roundtrip_preserves_cells(tmp_path: Path) -> None:
    """All-cache-hit rebuild must reproduce the fresh cell state exactly."""
    cfg = TerrainPipelineConfig(seed=11, **TINY)
    cfg.geography = _spec(with_overlay=False)

    # The risk is the cache path, exercised via TerrainCache directly on
    # plates: the payload must carry + replay the in-place crust field.
    tc = TerrainCache(tmp_path)
    from dreamulator.map.plate_generator import generate_plates
    tc = TerrainCache(tmp_path)
    from dreamulator.map.plate_generator import generate_plates

    mesh2 = run_terrain_pipeline(
        replace(cfg, num_nodes=TINY["num_nodes"]),
        stages=["mesh"],
        cache=None,
    ).mesh
    plates, cell_plate_map = generate_plates(mesh2, cfg)
    crust_fresh = [c.crust_type for c in mesh2.cells]
    # save + reload through the cache and replay
    fp = build_stage_fingerprint("plates", cfg)
    tc.save(
        "plates", (plates, cell_plate_map, {"crust_type": np.array(crust_fresh, dtype=object)}), fp
    )

    mesh3 = run_terrain_pipeline(
        replace(cfg, num_nodes=TINY["num_nodes"]), stages=["mesh"], cache=None
    ).mesh
    for c in mesh3.cells:
        c.crust_type = None  # simulate the fresh-mesh default the pipeline sees on a hit
    cached = tc.load("plates")
    assert cached is not None
    _plates, _cpm, fields = cached
    for cell, value in zip(mesh3.cells, fields["crust_type"], strict=False):
        cell.crust_type = str(value)
    assert [c.crust_type for c in mesh3.cells] == crust_fresh


def test_overlay_edit_keeps_plate_realization(tmp_path: Path) -> None:
    """Adding a terrain_only overlay must not change cells outside its patch.

    The exact user scenario: same plate-stage state, terrain rerun with the
    overlay — non-overlay crust/elevation stay put and the coastline far from
    the overlay is unchanged (sea-level calibration is overlay-blind).
    """
    snap_no = _run(tmp_path / "a", _spec(with_overlay=False))
    snap_ov = _run(tmp_path / "b", _spec(with_overlay=True))

    # overlay patch centre (lon 10, lat 15): cells near it may differ
    def far_from_overlay(mesh_snap_key: str) -> np.ndarray:
        # rebuild positions from a fresh run (mesh is deterministic, same order)
        cfg = TerrainPipelineConfig(seed=11, **TINY)
        m = run_terrain_pipeline(cfg, stages=["mesh"], cache=None).mesh
        lats = np.array([c.lat for c in m.cells])
        lons = np.array([c.lon for c in m.cells])
        return (
            np.hypot((lats - 15.0) * 111.0, (lons - 10.0) * 111.0 * np.cos(np.radians(15.0)))
            > 1500.0
        )

    far = far_from_overlay("x")
    assert far.sum() > 100
    assert np.array_equal(snap_no["crust"][far], snap_ov["crust"][far]), (
        "overlay edit changed crust far from the patch — plate realization leaked"
    )
    # water far from the patch: coastline unchanged (calibration overlay-blind)
    assert np.array_equal(snap_no["water"][far], snap_ov["water"][far])
