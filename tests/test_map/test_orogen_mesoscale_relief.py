"""Zero-mean mesoscale relief on orogen-supported cells."""

from __future__ import annotations

import numpy as np
import pytest

from dreamulator.map.orogen_mesoscale_relief import (
    apply_orogen_mesoscale_relief,
    mesoscale_relief_field,
)
from dreamulator.map.pipeline_types import TerrainPipelineConfig


@pytest.fixture(scope="module")
def mesh_xyz() -> np.ndarray:
    from dreamulator.map.cvt_mesh import generate_cvt_mesh

    mesh = generate_cvt_mesh(TerrainPipelineConfig(num_nodes=4000, lloyd_iterations=1, seed=5))
    return np.asarray(mesh.cell_xyz, dtype=np.float64)


def test_field_is_unit_std_zero_mean_and_reproducible(mesh_xyz: np.ndarray) -> None:
    lat = np.degrees(np.arcsin(mesh_xyz[:, 2] / np.linalg.norm(mesh_xyz, axis=1)))
    support = lat > 20.0
    a = mesoscale_relief_field(mesh_xyz, support, 6371.0, seed=1)
    b = mesoscale_relief_field(mesh_xyz, support, 6371.0, seed=1)
    assert np.array_equal(a, b)
    assert abs(a[support].mean()) < 1e-9 and abs(a[support].std() - 1.0) < 1e-9
    assert np.all(a[~support] == 0.0)
    assert not np.array_equal(a, mesoscale_relief_field(mesh_xyz, support, 6371.0, seed=2))


def test_relief_scales_with_orogen_and_keeps_land_above_sea() -> None:
    elevation = np.array([4500.0, 4500.0, 30.0, -2000.0])
    orogen = np.array([4000.0, 2000.0, 3000.0, 3000.0])
    field = np.array([1.0, 1.0, -1.0, 1.0])
    new, delta = apply_orogen_mesoscale_relief(elevation, orogen, field, 75.0, 0.0)
    assert delta[0] == pytest.approx(300.0) and delta[1] == pytest.approx(150.0)
    assert new[2] == pytest.approx(1.0)  # land never crosses the sea surface
    assert new[3] == -2000.0  # ocean untouched


def test_zero_amplitude_is_identity() -> None:
    elevation = np.array([4500.0, 10.0, -50.0])
    new, delta = apply_orogen_mesoscale_relief(elevation, np.full(3, 4000.0), np.ones(3), 0.0, 0.0)
    assert np.array_equal(new, elevation) and np.all(delta == 0.0)
