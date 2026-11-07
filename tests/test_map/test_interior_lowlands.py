"""Interior lowlands start at the orogen footprint, not only at the plate edge."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from dreamulator.map.pipeline_types import TerrainPipelineConfig
from dreamulator.map.terrain_synthesizer import _apply_interior_lowlands


def _plateau_world() -> tuple[object, np.ndarray, np.ndarray]:
    """All-continental mesh at 3 km; a convergent edge at the equator and a wide
    orogen (plateau) footprint reaching 25°N, i.e. far beyond the 600 km ramp."""
    from dreamulator.map.cvt_mesh import generate_cvt_mesh

    mesh = generate_cvt_mesh(TerrainPipelineConfig(num_nodes=3000, lloyd_iterations=1, seed=3))
    lat = np.array([c.lat for c in mesh.cells])
    for c in mesh.cells:
        c.crust_type = "continental"
        c.elevation = 3000.0
        edge = abs(c.lat) < 2.0
        c.boundary_type = "convergent" if edge else None
        c.distance_to_boundary_km = 0.0 if edge else 1.0e4
    support = (lat >= 0.0) & (lat < 25.0)
    return mesh, np.full(len(lat), 3000.0), support


def _config(origin: str) -> TerrainPipelineConfig:
    return dataclasses.replace(
        TerrainPipelineConfig(),
        interior_lowland_depth_m=500.0,
        interior_lowland_distance_scale_km=600.0,
        interior_lowland_floor_m=0.0,
        interior_lowland_origin=origin,
    )


def test_orogen_origin_keeps_wide_plateau_at_its_height() -> None:
    mesh, elev, support = _plateau_world()
    lat = np.array([c.lat for c in mesh.cells])
    out, _ = _apply_interior_lowlands(mesh, elev.copy(), _config("orogen"), orogen_support=support)
    assert np.all(out[support] == 3000.0)
    # the craton beyond the plateau is lowered, fully once past the ramp
    assert np.all(out[lat > 50.0] < 2600.0)


def test_boundary_origin_lowers_plateau_interior() -> None:
    mesh, elev, support = _plateau_world()
    lat = np.array([c.lat for c in mesh.cells])
    out, _ = _apply_interior_lowlands(
        mesh, elev.copy(), _config("boundary"), orogen_support=support
    )
    far_plateau = support & (lat > 15.0)
    assert np.all(out[far_plateau] < 2600.0)


def test_unknown_origin_is_rejected() -> None:
    mesh, elev, support = _plateau_world()
    with pytest.raises(ValueError, match="interior_lowland_origin"):
        _apply_interior_lowlands(mesh, elev.copy(), _config("edge"), orogen_support=support)
