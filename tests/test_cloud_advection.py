"""Tests for the L4 semi-Lagrangian cloud advection."""

from __future__ import annotations

import math

import numpy as np

from dreamulator.media.cloud_advection import advect_equirect, advection_substeps


def _grid(height: int = 180, width: int = 360) -> tuple[np.ndarray, np.ndarray]:
    lat = 90.0 - (np.arange(height) + 0.5) / height * 180.0
    lon = (np.arange(width) + 0.5) / width * 360.0 - 180.0
    return np.meshgrid(lon, lat)  # (lon2d, lat2d), shape (h, w)


def _blob(lon0: float, lat0: float, sigma_deg: float = 2.0) -> np.ndarray:
    lon2d, lat2d = _grid()
    dlon = (lon2d - lon0 + 180.0) % 360.0 - 180.0
    return np.exp(-0.5 * ((dlon / sigma_deg) ** 2 + ((lat2d - lat0) / sigma_deg) ** 2))


def _circular_mean_lon(field: np.ndarray) -> float:
    lon2d, _ = _grid()
    radians = np.radians(lon2d)
    return float(
        np.degrees(math.atan2(np.sum(field * np.sin(radians)), np.sum(field * np.cos(radians))))
    )


def test_uniform_field_stays_uniform() -> None:
    field = np.ones((90, 180))
    u = np.full_like(field, 12.0)
    v = np.full_like(field, 3.0)
    out = advect_equirect(field, u, v, dt_seconds=6.0 * 3600.0, radius_km=6371.0)
    np.testing.assert_allclose(out, 1.0, atol=1e-6)


def test_zero_wind_is_identity() -> None:
    field = _blob(10.0, 20.0)
    zeros = np.zeros_like(field)
    out = advect_equirect(field, zeros, zeros, dt_seconds=6.0 * 3600.0, radius_km=6371.0)
    np.testing.assert_allclose(out, field, atol=1e-6)


def test_blob_moves_east_with_the_wind() -> None:
    field = _blob(0.0, 0.0)
    u = np.full_like(field, 10.0)
    v = np.zeros_like(field)
    dt = 6.0 * 3600.0
    out = advect_equirect(field, u, v, dt_seconds=dt, radius_km=6371.0)
    expected = math.degrees(10.0 * dt / (6371.0 * 1000.0))
    before = _circular_mean_lon(field)
    after = _circular_mean_lon(out)
    assert abs(after - before - expected) < 0.1
    assert out.max() > 0.9
    assert np.all(out >= 0.0) and np.all(out <= 1.0)
    assert np.all(np.isfinite(out))


def test_blob_wraps_across_the_seam() -> None:
    field = _blob(179.0, 0.0)
    u = np.full_like(field, 10.0)
    v = np.zeros_like(field)
    dt = 6.0 * 3600.0
    out = advect_equirect(field, u, v, dt_seconds=dt, radius_km=6371.0)
    expected = (179.0 + 1.94 + 180.0) % 360.0 - 180.0
    after = _circular_mean_lon(out)
    assert abs((after - expected + 180.0) % 360.0 - 180.0) < 0.2


def test_cubic_interpolation_keeps_a_constant_field() -> None:
    field = np.ones((90, 180))
    u = np.full_like(field, 12.0)
    v = np.full_like(field, 3.0)
    out = advect_equirect(field, u, v, dt_seconds=6.0 * 3600.0, radius_km=6371.0, interp="cubic")
    np.testing.assert_allclose(out, 1.0, atol=1e-6)


def test_cubic_limits_edge_diffusion_versus_linear() -> None:
    # A sharp longitude step is smoothed by the semi-Lagrangian interpolation;
    # cubic sampling should retain more of the edge (higher total variation)
    # at the same displacement.
    height, width = 180, 360
    lon = np.linspace(-180.0, 180.0, width, endpoint=False)[None, :]
    field = ((lon > -10.0) & (lon < 10.0)).astype(np.float64) * np.ones((height, 1))
    u = np.full((height, width), 10.0)
    v = np.zeros_like(u)
    linear = advect_equirect(
        field, u, v, dt_seconds=6.0 * 3600.0, radius_km=6371.0, substeps=2, interp="linear"
    )
    cubic = advect_equirect(
        field, u, v, dt_seconds=6.0 * 3600.0, radius_km=6371.0, substeps=2, interp="cubic"
    )
    tv_linear = float(np.sum(np.abs(np.diff(linear, axis=1))))
    tv_cubic = float(np.sum(np.abs(np.diff(cubic, axis=1))))
    assert tv_cubic >= tv_linear
    # Catmull–Rom can overshoot slightly before the clip; the domain mean is
    # preserved to the same order as the interpolation error.
    assert abs(float(cubic.mean() - linear.mean())) < 1e-4


def test_substeps_bounded() -> None:
    u = np.full((90, 180), 30.0)
    v = np.zeros_like(u)
    n = advection_substeps(u, v, dt_seconds=24.0 * 3600.0, radius_km=6371.0)
    assert 1 <= n <= 8
