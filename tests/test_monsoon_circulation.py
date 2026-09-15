"""Tests for the monsoon circulation pure functions (engine/monsoon_circulation.py)."""

import numpy as np
import pytest

from dreamulator.engine.monsoon_circulation import (
    _MONSOON_PROJECTION_FRACTION,
    cross_equatorial_monsoon_wind,
    monsoon_boundary_layer_wind,
    monsoon_trough_latitude,
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

    def test_mask_ocean_only_reference(self):
        # B2: with an ocean mask, every cell in the band gets the OCEAN mean
        # (the land-sea contrast reference) — hot land cells no longer pull
        # their own reference up.
        lat = np.array([25.0, 26.0, 27.0])  # one 5° band
        t = np.array([np.full(12, 38.0), np.full(12, 36.0), np.full(12, 28.0)])  # land, land, ocean
        ocean = np.array([False, False, True])
        zm = zonal_mean_monthly(t, lat, band_deg=5.0, mask=ocean)
        assert np.allclose(zm, 28.0)  # ocean-only mean everywhere
        zm_all = zonal_mean_monthly(t, lat, band_deg=5.0)
        assert np.allclose(zm_all, (38.0 + 36.0 + 28.0) / 3.0)

    def test_mask_band_without_ocean_falls_back(self):
        # A band with no masked cells borrows the nearest band that has one —
        # no NaN/zero reference over all-land polar bands.
        lat = np.array([-82.0, -60.0, -58.0])
        t = np.array([np.full(12, -40.0), np.full(12, 0.0), np.full(12, 5.0)])
        ocean = np.array([False, False, True])  # only the -60..-55 band has ocean
        zm = zonal_mean_monthly(t, lat, band_deg=5.0, mask=ocean)
        assert np.isfinite(zm).all()
        assert np.allclose(zm[0], 5.0)  # polar band filled from nearest
        assert np.allclose(zm[1], 5.0)  # the -60..-55 band itself


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
        # Magnitude: ΔP = −P_sfc · E · ΔT / T̄_K  (E = M4 projection factor)
        expected = -1013.25 * _MONSOON_PROJECTION_FRACTION * 10.0 / (20.0 + 273.15)
        assert np.isclose(dp[0, 0], expected, rtol=1e-6)

    def test_full_contrast_retained(self):
        # B0b: a constant year-round land-sea contrast produces a constant
        # ΔP (a steady thermal low) — the annual mean is NOT removed, so the
        # derived annual wind keeps its stationary land-sea structure.
        lat = np.array([30.0, 31.0])
        t = np.full((2, 12), 20.0)
        t[0, :] += 5.0
        t[1, :] -= 5.0
        dp = pressure_anomaly_monthly(t, lat, band_deg=5.0)
        expected = -1013.25 * _MONSOON_PROJECTION_FRACTION * 5.0 / (20.0 + 273.15)
        assert (dp[0] < 0).all()  # warmer land → steady thermal low
        assert (dp[1] > 0).all()  # cooler land → steady high
        assert np.allclose(dp[0], expected, rtol=1e-6)

    def test_monthly_sensitivity_uses_monthly_reference(self):
        # The 1/T̄ hydrostatic sensitivity follows the monthly zonal
        # reference: the same ±10 K contrast in a colder column produces a
        # stronger hPa response (the winter high responds harder per kelvin).
        lat = np.array([30.0, 31.0])
        t = np.full((2, 12), 20.0)
        t[0, 1] += 10.0
        t[1, 1] -= 10.0
        dp = pressure_anomaly_monthly(t, lat, band_deg=5.0)
        t2 = t - 30.0  # colder world, same contrast
        dp2 = pressure_anomaly_monthly(t2, lat, band_deg=5.0)
        assert np.abs(dp2[0, 1]) > np.abs(dp[0, 1])
        assert np.allclose(dp[0, 1], -dp[1, 1])  # symmetric contrast

    def test_elevation_derating(self):
        # B1: a 4844 m plateau cell responds at exp(−z/8500)·exp(−z/3000)
        # ≈ 0.113 of an identical lowland cell — the Tibetan-dominance
        # artifact suppression (Boos & Kuang: the heat source is the lowland
        # non-orographic heating; Wu 2012: 85% of vapour below 3 km).
        lat = np.full(3, 30.0)
        t = np.zeros((3, 12))
        t[0, 5] = t[1, 5] = 12.0  # two identical warm cells (z = 0 / 4844)
        t[2, 5] = -24.0  # cold ballast so the zonal mean stays 0 → dt = +12
        elev = np.array([0.0, 4844.0, 0.0])

        dp = pressure_anomaly_monthly(t, lat, band_deg=5.0, elevation_m=elev)
        ratio = dp[1, 5] / dp[0, 5]
        expected = np.exp(-4844.0 / 8500.0) * np.exp(-4844.0 / 3000.0)
        assert ratio == pytest.approx(expected, rel=1e-6)
        # Both are thermal lows (warm anomaly).
        assert dp[0, 5] < 0.0 and dp[1, 5] < 0.0


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

    def test_land_drag_weaker_equatorial_wind(self):
        # At the equator (f=0) v = G/k_d, so a land cell (rough, high drag) gets
        # a much weaker down-gradient wind than an ocean cell (smooth, low drag)
        # for the same pressure gradient — the Amazon-vs-Somali-jet calibration.
        nodes = _sphere_points(np.zeros(2), np.array([0.0, 90.0]))
        f = np.zeros(2)
        rho = 1.225
        g_north = 1.0e-4
        north = np.array([0.0, 1.0, 0.0]) - nodes[:, 1:2] * nodes
        north /= np.linalg.norm(north, axis=1)[:, None]
        grad_dp = np.zeros((12, 2, 3))
        grad_dp[:] = -rho * g_north * north[None, :, :]

        drag = np.array([2.0e-4, 1.0e-5])  # land, ocean
        wind = monsoon_boundary_layer_wind(grad_dp, f, nodes, drag_rate_s=drag)
        speed = np.linalg.norm(wind, axis=2)

        assert speed[0, 0] < speed[0, 1]  # land slower than ocean
        assert np.allclose(speed[0, 0], g_north / 2.0e-4, rtol=1e-3)  # 0.5 m/s
        assert np.allclose(speed[0, 1], g_north / 1.0e-5, rtol=1e-3)  # 10 m/s

    def test_geostrophic_limit(self):
        # k_d → 0: flow turns 90° from G (along the isobars), |v| = |G|/|f|.
        lat = np.full(3, 45.0)
        nodes = _sphere_points(lat, np.array([0.0, 40.0, 80.0]))
        f = np.full(3, 5.0e-5)
        rho = 1.225
        # G eastward (pressure falling eastward).
        east = np.cross(
            nodes, np.array([0.0, 1.0, 0.0]) - nodes[:, 1:2] * nodes
        )  # physical east (r̂ × north, root unification 2026-09-13)
        east /= np.linalg.norm(east, axis=1)[:, None]
        g_east = 2.0e-4
        grad_dp = -rho * g_east * east[None, :, :]

        wind = monsoon_boundary_layer_wind(grad_dp, f, nodes, drag_rate_s=1.0e-12)

        speed = np.linalg.norm(wind, axis=2)
        assert np.allclose(speed, g_east / 5.0e-5, rtol=1e-3)
        # Perpendicular to G: no east component left.
        east_comp = np.einsum("mij,ij->mi", wind, east)
        assert np.allclose(east_comp, 0.0, atol=1e-3)
        # NH (f > 0) Buys-Ballot: low pressure (the direction of G) stays to
        # the LEFT of the geostrophic flow — equivalently the flow is G turned
        # 90° to the right (seen from above): right of physical +east is
        # −north, so G = +east → southward flow, matching _geostrophic_wind's
        # r̂×∇p/(fρ).
        assert (wind[:, :, 1] < 0).all()

    def test_nh_thermal_low_gets_cyclonic_inflow(self):
        # NH boundary-layer cyclone: a cell south of a thermal low feels G
        # northward (toward the low) and answers with an eastward (cyclonic)
        # component plus frictional inflow toward the low — the pattern that
        # spins up the southwesterly monsoon current around the Indian low.
        nodes = _sphere_points(np.array([20.0]), np.array([0.0]))
        f = np.array([5.0e-5])
        rho = 1.225
        north = np.array([0.0, 1.0, 0.0]) - nodes[:, 1:2] * nodes
        north /= np.linalg.norm(north, axis=1)[:, None]
        east = np.cross(nodes, north)  # physical east (root unification)
        # ΔP falling northward → G = −∇(ΔP)/ρ points north, 1e-4 m/s².
        grad_dp = np.zeros((12, 1, 3))
        grad_dp[:] = -rho * 1.0e-4 * north[None, :, :]

        wind = monsoon_boundary_layer_wind(grad_dp, f, nodes, drag_rate_s=1.0e-5)

        v_e = float(np.einsum("ij,ij->i", wind[0], east)[0])
        v_n = float(np.einsum("ij,ij->i", wind[0], north)[0])
        assert v_e > 0.0  # cyclonic (eastward) on the low's south flank
        assert v_n > 0.0  # frictional inflow toward the low

    def test_sh_thermal_low_gets_cyclonic_inflow(self):
        # Mirror check in the southern hemisphere: f < 0 deflects left, so SH
        # cyclones circulate clockwise seen from above — eastward on the low's
        # north flank — with frictional inflow toward the low.
        nodes = _sphere_points(np.array([-20.0]), np.array([0.0]))
        f = np.array([-5.0e-5])
        rho = 1.225
        north = np.array([0.0, 1.0, 0.0]) - nodes[:, 1:2] * nodes
        north /= np.linalg.norm(north, axis=1)[:, None]
        east = np.cross(nodes, north)  # physical east (root unification)
        # ΔP falling southward → G points south.
        grad_dp = np.zeros((12, 1, 3))
        grad_dp[:] = rho * 1.0e-4 * north[None, :, :]

        wind = monsoon_boundary_layer_wind(grad_dp, f, nodes, drag_rate_s=1.0e-5)

        v_e = float(np.einsum("ij,ij->i", wind[0], east)[0])
        v_n = float(np.einsum("ij,ij->i", wind[0], north)[0])
        assert v_e > 0.0  # eastward on the SH low's north flank (clockwise)
        assert v_n < 0.0  # frictional inflow toward the low (southward)

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


class TestCrossEquatorialMonsoonWind:
    """Cross-equatorial monsoon westerlies (D/F 子项 2)."""

    @staticmethod
    def _east_comp(w: np.ndarray, lat_deg: float) -> float:
        node = _sphere_points(np.array([lat_deg]), np.array([0.0]))
        north = np.array([0.0, 1.0, 0.0]) - node[:, 1:2] * node
        north /= np.linalg.norm(north, axis=1)[:, None]
        east = np.cross(node, north)
        east /= np.linalg.norm(east, axis=1)[:, None]
        return float(np.einsum("j,j->", w, east[0]))

    @staticmethod
    def _net(lat: np.ndarray, itcz: float, itcz_max: float = 14.0) -> np.ndarray:
        from dreamulator.engine.climate_physics import hadley_cell_wind

        n = len(lat)
        nodes = _sphere_points(lat, np.zeros(n))
        bg = hadley_cell_wind(np.radians(lat), nodes, itcz_lat_deg=itcz)
        sw = cross_equatorial_monsoon_wind(np.radians(lat), nodes, itcz, 6371.0, 1.0, itcz_max, bg)
        return bg + sw  # net wind = background + westerly (replacement)

    def test_nh_summer_westerly(self):
        # NH summer: within the belt the net zonal wind is westerly (u > 0) —
        # the Guinea/Somali westerlies.
        lat = np.array([4.0, 8.0])
        net = self._net(lat, 14.0)
        for i, la in enumerate(lat):
            assert self._east_comp(net[i], la) > 0.0

    def test_sh_summer_westerly(self):
        # SH summer mirror: the westerly belt appears in the SH cross-equatorial
        # belt too (the same westward sign in both hemispheres).
        lat = np.array([-4.0, -8.0])
        net = self._net(lat, -14.0)
        for i, la in enumerate(lat):
            assert self._east_comp(net[i], la) > 0.0

    def test_zero_outside_belt(self):
        # Poleward of the ITCZ (trades) and the opposite hemisphere are
        # untouched — the replacement wind is strictly equatorward of the ITCZ.
        lat = np.array([15.0, 20.0, -8.0])
        nodes = _sphere_points(lat, np.zeros(3))
        from dreamulator.engine.climate_physics import hadley_cell_wind

        bg = hadley_cell_wind(np.radians(lat), nodes, itcz_lat_deg=14.0)
        sw = cross_equatorial_monsoon_wind(np.radians(lat), nodes, 14.0, 6371.0, 1.0, 14.0, bg)
        assert np.allclose(sw, 0.0)

    def test_zero_when_itcz_at_equator(self):
        # No ITCZ excursion → no cross-equatorial belt (backward compatible with
        # the symmetric Hadley easterly at 15°N).
        lat = np.array([8.0, 15.0, -8.0])
        nodes = _sphere_points(lat, np.zeros(3))
        from dreamulator.engine.climate_physics import hadley_cell_wind

        bg = hadley_cell_wind(np.radians(lat), nodes, itcz_lat_deg=0.0)
        sw = cross_equatorial_monsoon_wind(np.radians(lat), nodes, 0.0, 6371.0, 1.0, 14.0, bg)
        assert np.allclose(sw, 0.0)

    def test_replaces_background_easterly(self):
        # The net wind is the westerly, NOT background + a weak westerly: the
        # Hadley background easterly is subtracted within the belt.
        lat = np.array([8.0])
        net = self._net(lat, 14.0)
        # ~8°N mid-belt: westerly of order ~1.5 m/s, magnitude bounded.
        speed = np.linalg.norm(net[0])
        assert 0.5 < speed < 4.0

    def test_tangent(self):
        lat = np.array([2.0, 8.0])
        nodes = _sphere_points(lat, np.zeros(2))
        net = self._net(lat, 14.0)
        radial = np.einsum("ij,ij->i", net, nodes)
        assert np.allclose(radial, 0.0, atol=1e-9)


class TestMonsoonTroughLatitude:
    """Monsoon-trough latitude (the ITCZ's land northward shift)."""

    def test_cross_equatorial_sector_shifts_poleward(self):
        # SH ocean + EQ ocean + hot NH land → the trough shifts poleward of the
        # ocean ITCZ (toward the warm land).
        lat = np.array([-10.0, 0.0, 20.0, 25.0])
        lon = np.array([5.0, 5.0, 5.0, 5.0])
        ocean = np.array([True, True, False, False])
        t = np.array([20.0, 25.0, 30.0, 32.0])
        trough = monsoon_trough_latitude(t, lat, lon, ocean, itcz_ocean_deg=14.0)
        assert (trough > 14.0).all()

    def test_non_cross_equatorial_no_shift(self):
        # NH ocean + NH land with no SH ocean and no EQ ocean corridor (South
        # China / East Asia, behind the Indonesian archipelago) → no shift.
        lat = np.array([10.0, 20.0, 25.0])
        lon = np.array([15.0, 15.0, 15.0])
        ocean = np.array([True, False, False])
        t = np.array([25.0, 30.0, 32.0])
        trough = monsoon_trough_latitude(t, lat, lon, ocean, itcz_ocean_deg=14.0)
        assert np.allclose(trough, 14.0)

    def test_pure_ocean_no_shift(self):
        # No land at all → the trough stays at the ocean ITCZ.
        lat = np.array([-10.0, 0.0, 10.0, 20.0])
        lon = np.array([5.0, 5.0, 5.0, 5.0])
        ocean = np.array([True, True, True, True])
        t = np.array([20.0, 25.0, 27.0, 25.0])
        trough = monsoon_trough_latitude(t, lat, lon, ocean, itcz_ocean_deg=14.0)
        assert np.allclose(trough, 14.0)
