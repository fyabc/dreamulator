"""Continental shelf on submerged continental crust (terrain_synthesizer)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pytest

from dreamulator.map.cvt_mesh import generate_cvt_mesh
from dreamulator.map.pipeline_types import TerrainPipelineConfig
from dreamulator.map.terrain_synthesizer import (
    _apply_continental_shelf,
    _apply_deferred_shelf,
)

if TYPE_CHECKING:
    from dreamulator.map.models import CVTMesh


@pytest.fixture(scope="module")
def base() -> tuple[TerrainPipelineConfig, CVTMesh]:
    cfg = TerrainPipelineConfig(num_nodes=3000, seed=7, lloyd_iterations=2, radius_km=6371.0)
    return cfg, generate_cvt_mesh(cfg)


def _world(base: tuple[TerrainPipelineConfig, CVTMesh], drowned_band_deg: float):
    """A polar-cap continent (lat > 30°) with continental crust reaching further south."""
    cfg, mesh = base
    lat = np.array([c.lat for c in mesh.cells])
    elevation = np.where(lat > 30.0, 500.0, -4000.0)
    for c, la in zip(mesh.cells, lat, strict=True):
        c.crust_type = "continental" if la > 30.0 - drowned_band_deg else "oceanic"
        c.elevation = 0.0
    return cfg, mesh, elevation, lat


def test_land_unchanged_and_ocean_stays_ocean(base) -> None:
    cfg, mesh, z, _ = _world(base, 6.0)
    out, deferred = _apply_continental_shelf(mesh, z.copy(), cfg, np.random.default_rng(0))
    assert deferred is None
    assert np.array_equal(out > 0, z > 0)
    assert np.array_equal(out[z > 0], z[z > 0])
    assert out[z <= 0].max() < 0.0


def test_shelf_only_on_submerged_continental_crust(base) -> None:
    cfg, mesh, z, lat = _world(base, 6.0)
    with_margin, _ = _apply_continental_shelf(mesh, z.copy(), cfg, np.random.default_rng(0))
    near = (lat < 30.0) & (lat > 27.0)  # first ring of ocean, on the drowned margin
    assert np.median(with_margin[near]) > -cfg.shelf_break_depth_m * 1.1

    cfg, mesh, z, lat = _world(base, 0.0)  # COB at the coastline: no shelf
    no_margin, _ = _apply_continental_shelf(mesh, z.copy(), cfg, np.random.default_rng(0))
    assert np.median(no_margin[near]) < -cfg.shelf_break_depth_m * 2


def test_disabled_by_nonpositive_width(base) -> None:
    cfg, mesh, z, _ = _world(base, 6.0)
    off = TerrainPipelineConfig(**{**cfg.__dict__, "shelf_width_km": 0.0})
    out, deferred = _apply_continental_shelf(mesh, z.copy(), off, np.random.default_rng(0))
    assert deferred is None and np.array_equal(out, z)


def test_legacy_coastline_keeps_land_mask(base) -> None:
    cfg, mesh, z, _ = _world(base, 6.0)
    legacy = TerrainPipelineConfig(**{**cfg.__dict__, "shelf_legacy_coastline": True})
    out, deferred = _apply_continental_shelf(mesh, z.copy(), legacy, np.random.default_rng(0))
    assert deferred is not None
    land_after_legacy = out > 0
    final = _apply_deferred_shelf(mesh, out.copy(), legacy, deferred)
    assert np.array_equal(final > 0, land_after_legacy)
    assert final[~land_after_legacy].max() < 0.0
