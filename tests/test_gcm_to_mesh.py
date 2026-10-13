"""Tests for the GCM-to-mesh projection helpers (dreamulator.gcm.to_mesh)."""

from __future__ import annotations

import numpy as np

from dreamulator.gcm.to_mesh import band_ocean_anomaly, bilinear_to_points, phase_climatology


def test_bilinear_reproduces_linear_field_and_wraps_longitude() -> None:
    lat = np.array([-60.0, -20.0, 20.0, 60.0])
    lon = np.arange(8) * 45.0
    field = lat[:, None] * 2.0 + np.cos(np.radians(lon))[None, :] * 0.0  # linear in latitude
    out = bilinear_to_points(lat, lon, field, np.array([0.0, 40.0]), np.array([10.0, 350.0]))
    assert np.allclose(out, [0.0, 80.0])
    # longitude wraps: halfway between the last column (315°) and the first (0°)
    ring = np.zeros((4, 8))
    ring[:, 0], ring[:, 7] = 1.0, 3.0
    assert np.allclose(bilinear_to_points(lat, lon, ring, np.array([0.0]), np.array([337.5])), 2.0)


def test_bilinear_clamps_latitude_beyond_outer_rows() -> None:
    lat = np.array([-45.0, 45.0])
    lon = np.array([0.0, 180.0])
    field = np.array([[1.0, 1.0], [5.0, 5.0]])
    out = bilinear_to_points(lat, lon, field, np.array([89.0, -89.0]), np.array([0.0, 0.0]))
    assert np.allclose(out, [5.0, 1.0])


def test_bilinear_keeps_leading_axes() -> None:
    lat = np.array([-30.0, 30.0])
    lon = np.array([0.0, 120.0, 240.0])
    field = np.stack([np.full((2, 3), m) for m in range(12)])
    out = bilinear_to_points(
        lat, lon, field, np.array([0.0, 10.0, 20.0]), np.array([5.0, 6.0, 7.0])
    )
    assert out.shape == (12, 3)
    assert np.allclose(out[:, 0], np.arange(12))


def test_band_ocean_anomaly_uses_ocean_mean_of_each_band() -> None:
    slp = np.array([[1000.0, 1004.0, 1010.0], [1012.0, 1012.0, 1012.0]])
    ocean = np.array([[True, True, False], [False, False, False]])
    dp = band_ocean_anomaly(slp, ocean)
    assert np.allclose(dp[0], [-2.0, 2.0, 8.0])  # ocean mean 1002
    assert np.allclose(dp[1], 0.0)  # no ocean: falls back to the band mean


def test_phase_climatology_bins_and_fills_empty_bins() -> None:
    phase = np.array([0.01, 0.02, 0.50, 0.51])
    values = np.array([[1.0], [3.0], [10.0], [20.0]])
    clim = phase_climatology(values, phase, n_bins=4)
    assert clim.shape == (4, 1)
    assert clim[0, 0] == 2.0 and clim[2, 0] == 15.0
    assert np.isfinite(clim).all()  # bins 1 and 3 filled from their nearest neighbour
