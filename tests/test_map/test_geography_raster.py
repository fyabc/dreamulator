"""Tests for dense raster bias anchoring (Gleba-style probability map)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pytest

from dreamulator.map.cvt_mesh import generate_cvt_mesh
from dreamulator.map.elevation_codec import encode_elevation
from dreamulator.map.geography import (
    GeographyFeature,
    GeographySpec,
    apply_geography_crust,
    build_land_bias_field,
    load_geography_raster,
    sample_raster_at_cells,
)
from dreamulator.map.pipeline_types import TerrainPipelineConfig
from dreamulator.map.terrain_synthesizer import synthesize_terrain

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(scope="module")
def mesh():
    cfg = TerrainPipelineConfig(seed=7, num_nodes=2500, lloyd_iterations=3)
    return generate_cvt_mesh(cfg)


def _east_west_raster() -> np.ndarray:
    """0..1 grid: west (lon<0) black, east (lon>=0) white."""
    h, w = 8, 16
    grid = np.zeros((h, w))
    grid[:, w // 2 :] = 1.0
    return grid


def test_sample_raster_constant(mesh) -> None:
    out = sample_raster_at_cells(mesh, np.full((8, 16), 0.75))
    assert np.allclose(out, 0.75)


def test_sample_raster_east_west(mesh) -> None:
    out = sample_raster_at_cells(mesh, _east_west_raster())
    for cell, v in zip(mesh.cells, out, strict=True):
        expected = 1.0 if cell.lon >= 0 else 0.0
        assert v == expected or abs(cell.lon) < 360.0 / 16  # pixel boundary


def test_load_geography_raster_missing(tmp_path: Path) -> None:
    assert load_geography_raster(None) is None
    assert load_geography_raster(tmp_path / "nope.png") is None


def test_load_geography_raster_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "geography_raster.png"
    p.write_bytes(encode_elevation(np.full((4, 8), 1.0), 0.0, 1.0))
    bias = load_geography_raster(p)
    assert bias is not None
    assert np.allclose(bias, 1.0)  # white maps to +1 (mid-grey = 0)


def test_bias_field_neutral_raster_noop(mesh) -> None:
    spec = GeographySpec(features=[GeographyFeature(name="c", lat=0.0, radius_deg=20.0)])
    base = build_land_bias_field(mesh, spec)
    neutral = build_land_bias_field(mesh, spec, raster_bias=np.zeros(len(mesh.cells)))
    assert np.allclose(base, neutral)
    white = build_land_bias_field(mesh, spec, raster_bias=np.ones(len(mesh.cells)))
    assert np.all(white >= base - 1e-9)


def test_apply_crust_raster_only(mesh) -> None:
    """Without features the raster alone drives crust assignment."""
    cfg = TerrainPipelineConfig(seed=7)
    cfg.geography = GeographySpec(land_fraction_target=0.5, features=[])
    raster_bias = 2.0 * sample_raster_at_cells(mesh, _east_west_raster()) - 1.0
    apply_geography_crust(mesh, cfg, raster_bias=raster_bias)
    # The raster splits at the lon 0/±180 seam — select by longitude.
    east = [c for c in mesh.cells if c.lon > 30.0]
    west = [c for c in mesh.cells if c.lon < -30.0]
    land_e = sum(1 for c in east if c.crust_type == "continental") / len(east)
    land_w = sum(1 for c in west if c.crust_type == "continental") / len(west)
    assert land_e > 0.8
    assert land_w < 0.2


def test_synthesize_raster_ocean_stays_submerged() -> None:
    """Authored-ocean raster keeps its core below sea level end-to-end."""
    cfg = TerrainPipelineConfig(
        seed=7,
        num_nodes=1200,
        lloyd_iterations=2,
        hotspot_count=0,
        shelf_width_km=0.0,
        coastal_plain_width_km=0.0,
        interior_orogeny_count=0,
    )
    cfg.geography = GeographySpec(land_fraction_target=0.5, features=[])
    mesh = generate_cvt_mesh(cfg)
    bias = 2.0 * sample_raster_at_cells(mesh, _east_west_raster()) - 1.0
    apply_geography_crust(mesh, cfg, raster_bias=bias)
    synthesize_terrain(mesh, [], cfg, raster_bias=bias)
    west_core = [c.elevation for c in mesh.cells if c.lon < -30.0]
    assert west_core
    assert max(west_core) < 0.0
