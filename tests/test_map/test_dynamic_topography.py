"""Dynamic topography of the mantle flow (map/dynamic_topography.py)."""

from __future__ import annotations

import numpy as np
import pytest

from dreamulator.map.cvt_mesh import generate_cvt_mesh
from dreamulator.map.dynamic_topography import (
    AMPLITUDE_AIR_M,
    AMPLITUDE_WATER_M,
    dynamic_topography,
)
from dreamulator.map.pipeline_types import TerrainPipelineConfig


def test_degree_two_about_the_axis() -> None:
    cfg = TerrainPipelineConfig(num_nodes=3000, lloyd_iterations=1, seed=5)
    mesh = generate_cvt_mesh(cfg)
    for c in mesh.cells:
        c.crust_type = "oceanic"
    axis = np.array([1.0, 0.0, 0.0])
    h = dynamic_topography(mesh, axis)
    xyz = mesh.cell_xyz / np.linalg.norm(mesh.cell_xyz, axis=1, keepdims=True)
    c = xyz @ axis
    # uplift A over both upwellings, −A/2 along the downwelling ring, symmetric
    assert h[np.argmax(c)] == pytest.approx(AMPLITUDE_WATER_M, rel=0.01)
    assert h[np.argmin(c)] == pytest.approx(AMPLITUDE_WATER_M, rel=0.01)
    assert h[np.argmin(np.abs(c))] == pytest.approx(-0.5 * AMPLITUDE_WATER_M, rel=0.01)
    # zero area mean (a pure degree-2 harmonic)
    assert abs(float(h.mean())) < 0.02 * AMPLITUDE_WATER_M
    # air-loaded continents deflect by (ρm − ρw)/ρm as much
    for cell in mesh.cells:
        cell.crust_type = "continental"
    h_air = dynamic_topography(mesh, axis)
    assert np.allclose(h_air, h * AMPLITUDE_AIR_M / AMPLITUDE_WATER_M)
    assert abs(AMPLITUDE_AIR_M - 550.0) < 5.0
