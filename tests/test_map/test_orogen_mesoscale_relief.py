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


def _belt_mesh() -> tuple[np.ndarray, np.ndarray, float]:
    """Fibonacci cells (about 50 km apart on a 2000 km sphere) with an east-west belt."""
    n, radius = 20000, 2000.0
    i = np.arange(n) + 0.5
    lat = np.arcsin(1 - 2 * i / n)
    lon = np.pi * (1 + 5**0.5) * i
    xyz = np.c_[np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)]
    relief = 3000.0 * np.exp(-((np.degrees(lat) / 12.0) ** 2))
    relief[relief < 200.0] = 0.0
    return xyz, relief, radius


def test_strike_frame_follows_belt_axis() -> None:
    from dreamulator.map.orogen_mesoscale_relief import orogen_strike_frame

    xyz, relief, radius = _belt_mesh()
    support = relief > 0
    strike, coherence = orogen_strike_frame(xyz, relief, support, radius)
    lat = np.degrees(np.arcsin(xyz[:, 2]))
    flank = support & (np.abs(lat) > 4) & (np.abs(lat) < 12)
    east = np.cross([0.0, 0.0, 1.0], xyz)
    east /= np.linalg.norm(east, axis=1, keepdims=True)
    alignment = np.abs(np.einsum("ij,ij->i", strike[flank], east[flank]))
    assert np.median(alignment) > 0.9
    assert np.median(coherence[flank]) > 0.5


def _along_minus_across_correlation(anisotropy: float) -> float:
    from scipy.spatial import cKDTree

    from dreamulator.map.orogen_mesoscale_relief import orogen_strike_frame

    xyz, relief, radius = _belt_mesh()
    support = relief > 0
    strike, coherence = orogen_strike_frame(xyz, relief, support, radius)
    f = mesoscale_relief_field(
        xyz, support, radius, seed=4, strike=strike, coherence=coherence, anisotropy=anisotropy
    )
    pairs = cKDTree(xyz).query_pairs(160.0 / radius, output_type="ndarray")
    pairs = pairs[support[pairs[:, 0]] & support[pairs[:, 1]]]
    dv = xyz[pairs[:, 1]] - xyz[pairs[:, 0]]
    dv /= np.linalg.norm(dv, axis=1, keepdims=True)
    along = np.abs(np.einsum("ij,ij->i", dv, strike[pairs[:, 0]])) > 0.9
    across = np.abs(np.einsum("ij,ij->i", dv, strike[pairs[:, 0]])) < 0.3
    prod = f[pairs[:, 0]] * f[pairs[:, 1]]
    return float(prod[along].mean() - prod[across].mean())


def test_anisotropic_field_is_elongated_along_strike() -> None:
    assert _along_minus_across_correlation(3.0) > 0.2
    assert abs(_along_minus_across_correlation(1.0)) < 0.1
