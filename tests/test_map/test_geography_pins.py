"""Author elevation pins (terrain_synthesizer._apply_geography_pins)."""

from __future__ import annotations

import numpy as np

from dreamulator.map.cvt_mesh import generate_cvt_mesh
from dreamulator.map.geography import (
    GeographyFeature,
    GeographySpec,
    build_elevation_pins_at_xyz,
)
from dreamulator.map.pipeline_types import TerrainPipelineConfig
from dreamulator.map.terrain_synthesizer import _apply_geography_pins, apply_elevation_pin_values


def _world(crosses: bool, target: float, strength: float = 0.7, exponent: float = 0.5):
    feature = GeographyFeature(
        name="pin",
        lon=0.0,
        lat=0.0,
        radius_deg=30.0,
        strength=0.5,
        elevation_target_m=target,
        pin_strength=strength,
        pin_exponent=exponent,
        pin_crosses_sea_level=crosses,
    )
    cfg = TerrainPipelineConfig(num_nodes=2000, seed=5, lloyd_iterations=1)
    cfg.geography = GeographySpec(features=[feature])
    mesh = generate_cvt_mesh(cfg)
    lon = np.array([c.lon for c in mesh.cells])
    # land in the east, shallow sea in the west, inside the pin's footprint
    elevation = np.where(lon > 0.0, 200.0, -30.0)
    return cfg, mesh, elevation


def test_mean_elevation_pin_keeps_the_coastline() -> None:
    cfg, mesh, z = _world(crosses=False, target=800.0)
    out = _apply_geography_pins(mesh, z.copy(), cfg)
    assert np.array_equal(out > 0, z > 0)
    assert np.array_equal(out[z <= 0], z[z <= 0])  # sea untouched by a land target
    assert out[z > 0].max() > 200.0  # land pulled toward the target


def test_pin_never_overshoots_its_target() -> None:
    cfg, mesh, z = _world(crosses=False, target=210.0, strength=1.0, exponent=0.5)
    out = _apply_geography_pins(mesh, z.copy(), cfg)
    assert out[z > 0].max() <= 210.0 + 1e-9


def test_crossing_pin_may_raise_sea_into_land() -> None:
    cfg, mesh, z = _world(crosses=True, target=100.0, strength=1.0, exponent=1.0)
    out = _apply_geography_pins(mesh, z.copy(), cfg)
    assert (out[z <= 0] > 0).any()


def test_continuous_pin_query_preserves_side_rules_and_query_partition() -> None:
    """A continuous coast can move through the same author pin footprint."""
    spec = GeographySpec(
        features=[
            GeographyFeature(
                name="land height",
                lon=0,
                lat=0,
                radius_deg=30,
                strength=0.5,
                elevation_target_m=210,
                pin_strength=1,
                pin_exponent=0.5,
            )
        ]
    )
    longitude = np.radians(np.array([-10, 0, 10, 80], dtype=float))
    xyz = np.column_stack([np.cos(longitude), np.zeros(4), np.sin(longitude)])
    z = np.array([-30.0, 200.0, 500.0, 200.0])
    pins = build_elevation_pins_at_xyz(xyz, spec, crosses_sea_level=False)
    assert pins is not None
    result = apply_elevation_pin_values(z, pins, crosses_sea_level=False)
    assert result[0] == z[0]
    assert result[1] == 210
    assert 210 <= result[2] <= z[2]
    assert result[3] == z[3]
    parts = []
    for indices in np.array_split(np.arange(4), 2):
        local = build_elevation_pins_at_xyz(xyz[indices], spec, crosses_sea_level=False)
        assert local is not None
        parts.append(apply_elevation_pin_values(z[indices], local, crosses_sea_level=False))
    np.testing.assert_array_equal(result, np.concatenate(parts))
