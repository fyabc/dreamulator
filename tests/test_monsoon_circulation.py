"""Tests for the monsoon circulation pure functions (engine/monsoon_circulation.py)."""

import numpy as np

from dreamulator.engine.monsoon_circulation import (
    monsoon_boundary_layer_wind,
    pressure_anomaly_monthly,
    zonal_mean_monthly,
)


def _sphere_points(lat_deg: np.ndarray, lon_deg: np.ndarray) -> np.ndarray:
    """Unit sphere positions from lat/lon (same convention as the CVT mesh:
    y = sin(lat), lon = atan2(z, x))."""
    la = np.radians(lat_deg)
    lo = np.radians(lon_deg)
    return np.stack(
        [np.cos(la) * np.cos(lo), np.sin(la), np.cos(la) * np.sin(lo)],
        axis=1,
    )


class TestZonalMeanMonthly:
    def test_band_constant_field_reproduced(self):
        # A field constant within each latitude band is its own zonal mean,
        # and distinct bands keep their distinct values.
        lat = np.array([-58.0, -56.0, 10.0, 12.0, 55.0, 57.0])
        band_value = np.array([15.0, 15.0, 25.0, 25.0, -5.0, -5.0])
        t = np.repeat(band_value[:, None], 12, axis=1)
        zm = zonal_mean_monthly(t, lat, band_deg=5.0)
        assert np.allclose(zm, t, atol=1e-10)

    def test_band_average_kills_local_anomaly(self):
        # One warm + one cool cell in each band: the band mean drops the anomaly.
        lat = np.array([10.0, 11.0])
        base = np.full((2, 12), 25.0)
        t = base + np.array([[+5.0], [-5.0]])
        zm = zonal_mean_monthly(t, lat, band_deg=5.0)
        assert np.allclose(zm, base)

    def test_empty_band_filled_from_nearest(self):
        # Cells only in two far-apart bands; a latitude between them must not
        # produce NaN or zero.
        lat = np.array([-80.0, 80.0])
        t = np.array([np.full(12, -30.0), np.full(12, 30.0)])
        zm = zonal_mean_monthly(t, lat, band_deg=5.0)
        assert np.isfinite(zm).all()
        # Every latitude maps to one of the two populated bands' values.
        assert set(np.round(zm[:, 0], 6)) == {-30.0, 30.0}


class TestPressureAnomalyMonthly:
    def test_warm_anomaly_is_a_thermal_low(self):
        # Summer hemisphere: land cell warmer than its latitude band in the
        # warm months → negative ΔP (thermal low).
        lat = np.array([30.0, 31.0])
        t = np.full((2, 12), 20.0)
        # Cell 0: +10 K for months 0-5, −10 K for months 6-11 (zero annual mean)
        t[0, 0:6] += 10.0
        t[0, 6:12] -= 10.0
        t[1, 0:6] -= 10.0
        t[1, 6:12] += 10.0

        dp = pressure_anomaly_monthly(t, lat, band_deg=5.0)

        # Zonal mean is 20 °C for both cells → dt = ±10 K exactly.
        assert (dp[0, 0:6] < 0).all()  # warm → low pressure
        assert (dp[0, 6:12] > 0).all()  # cold → high pressure
        # Magnitude: ΔP = −P_sfc · 0.25 · ΔT / T̄_K
        expected = -1013.25 * 0.25 * 10.0 / (20.0 + 273.15)
        assert np.isclose(dp[0, 0], expected, rtol=1e-6)

    def test_annual_mean_anomaly_is_removed(self):
        # A constant land-sea contrast all year belongs to the annual
        # geostrophic wind, not the monsoon — it must not appear here.
        lat = np.array([30.0, 31.0])
        t = np.full((2, 12), 20.0)
        t[0, :] += 5.0
        t[1, :] -= 5.0
        dp = pressure_anomaly_monthly(t, lat, band_deg=5.0)
        assert np.allclose(dp, 0.0, atol=1e-12)

    def test_months_sum_to_zero(self):
        rng = np.random.default_rng(7)
        lat = rng.uniform(-90.0, 90.0, 50)
        t = 25.0 - 40.0 * np.abs(lat)[:, None] / 90.0 + rng.normal(0, 8, (50, 12))
        dp = pressure_anomaly_monthly(t, lat, band_deg=5.0)
        assert np.allclose(dp.sum(axis=1), 0.0, atol=1e-9)


class TestMonsoonBoundaryLayerWind:
    def test_equator_flows_down_gradient(self):
        # f = 0: v = G/k_d, straight toward low pressure (cross-equatorial
        # monsoon flow — no Coriolis turning at the equator).
        nodes = _sphere_points(np.zeros(4), np.array([0.0, 90.0, 180.0, 270.0]))
        f = np.zeros(4)
        rho = 1.225
        k_d = 1.0e-5
        # Pressure falling northward → G points north.
        g_north = 1.0e-4  # m/s²
        grad_dp = np.zeros((12, 4, 3))
        north = np.array([0.0, 1.0, 0.0]) - nodes[:, 1:2] * nodes
        north /= np.linalg.norm(north, axis=1)[:, None]
        grad_dp[:] = -rho * g_north * north[None, :, :]

        wind = monsoon_boundary_layer_wind(grad_dp, f, nodes, drag_rate_s=k_d)

        expected_speed = g_north / k_d  # 10 m/s
        speed = np.linalg.norm(wind, axis=2)
        assert np.allclose(speed, expected_speed, rtol=1e-6)
        # Direction: northward (positive y component away from poles).
        assert (wind[:, :, 1] > 0).all()

    def test_geostrophic_limit(self):
        # k_d → 0: flow turns 90° from G (along the isobars), |v| = |G|/|f|.
        lat = np.full(3, 45.0)
        nodes = _sphere_points(lat, np.array([0.0, 40.0, 80.0]))
        f = np.full(3, 5.0e-5)
        rho = 1.225
        # G eastward (pressure falling eastward).
        east = np.cross(
            np.array([0.0, 1.0, 0.0]) - nodes[:, 1:2] * nodes, nodes
        )  # hadley-convention east
        east /= np.linalg.norm(east, axis=1)[:, None]
        g_east = 2.0e-4
        grad_dp = -rho * g_east * east[None, :, :]

        wind = monsoon_boundary_layer_wind(grad_dp, f, nodes, drag_rate_s=1.0e-12)

        speed = np.linalg.norm(wind, axis=2)
        assert np.allclose(speed, g_east / 5.0e-5, rtol=1e-3)
        # Perpendicular to G: no east component left.
        east_comp = np.einsum("mij,ij->mi", wind, east)
        assert np.allclose(east_comp, 0.0, atol=1e-3)
        # NH (f > 0), low pressure to the east → flow toward the south.
        assert (wind[:, :, 1] < 0).all()

    def test_speed_clamp(self):
        nodes = _sphere_points(np.zeros(2), np.array([0.0, 90.0]))
        f = np.zeros(2)
        north = np.array([0.0, 1.0, 0.0]) - nodes[:, 1:2] * nodes
        north /= np.linalg.norm(north, axis=1)[:, None]
        grad_dp = -1.225 * 1.0 * north[None, :, :]  # G = 1 m/s² — absurd forcing
        wind = monsoon_boundary_layer_wind(
            grad_dp, f, nodes, drag_rate_s=1.0e-5, max_speed_m_s=30.0
        )
        speed = np.linalg.norm(wind, axis=2)
        assert (speed <= 30.0 + 1e-9).all()

    def test_wind_is_tangent(self):
        rng = np.random.default_rng(3)
        lat = rng.uniform(-89.0, 89.0, 10)
        lon = rng.uniform(-180.0, 180.0, 10)
        nodes = _sphere_points(lat, lon)
        f = 1.0e-4 * np.sin(np.radians(lat))
        grad_dp = rng.normal(0, 1.0e-3, (12, 10, 3))
        # Make the gradient tangent (drop the radial part) as the map side does.
        radial = np.einsum("mij,ij->mi", grad_dp, nodes)
        grad_dp = grad_dp - radial[:, :, None] * nodes[None, :, :]

        wind = monsoon_boundary_layer_wind(grad_dp, f, nodes)

        radial_wind = np.einsum("mij,ij->mi", wind, nodes)
        assert np.allclose(radial_wind, 0.0, atol=1e-9)

    def test_zero_gradient_gives_zero_wind(self):
        nodes = _sphere_points(np.array([10.0, -10.0]), np.array([0.0, 180.0]))
        f = np.array([1.0e-4, -1.0e-4])
        wind = monsoon_boundary_layer_wind(np.zeros((12, 2, 3)), f, nodes)
        assert np.allclose(wind, 0.0)
