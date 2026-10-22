"""Author elevation pins (terrain_synthesizer._apply_geography_pins)."""

from __future__ import annotations

import numpy as np

from dreamulator.map.cvt_mesh import generate_cvt_mesh
from dreamulator.map.geography import GeographyFeature, GeographySpec
from dreamulator.map.pipeline_types import TerrainPipelineConfig
from dreamulator.map.terrain_synthesizer import _apply_geography_pins


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
