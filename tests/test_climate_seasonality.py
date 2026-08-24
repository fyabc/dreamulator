"""Tests for the insolation-driven seasonal climate model (roadmap 3A.2).

Covers the solar geometry (declination, daily-mean insolation, polar day/night),
the land-ocean heat-capacity amplitude modulation, monthly temperature, ITCZ
migration, and monthly precipitation distribution.
"""

import numpy as np
import pytest

from dreamulator.engine.climate_physics import koppen_classify
from dreamulator.engine.climate_seasonality import (
    compute_effective_obliquity,
    compute_seasonal_climate,
    daily_mean_insolation,
    itcz_latitude_monthly,
    monthly_insolation,
    monthly_precipitation_factor,
    monthly_temperature,
    orbital_distance_factor,
    seasonal_heat_capacity,
    seasonal_precip_extremes,
    solar_declination,
    solve_1d_ebm_temperature,
    warm_cold_half_precip,
)

# ---------------------------------------------------------------------------
# 1. Solar geometry
# ---------------------------------------------------------------------------


class TestSolarDeclination:
    """Solar declination over the year."""

    def test_circular_orbit_equinoxes_and_solstices(self) -> None:
        """Day 0 = vernal equinox, P/4 = summer solstice, 3P/4 = winter solstice."""
        eps = np.radians(23.44)
        period = 365.25
        assert solar_declination(0.0, 23.44, period) == pytest.approx(0.0, abs=1e-6)
        assert solar_declination(period / 4, 23.44, period) == pytest.approx(eps, abs=1e-6)
        assert solar_declination(3 * period / 4, 23.44, period) == pytest.approx(-eps, abs=1e-6)

    def test_zero_obliquity_no_declination(self) -> None:
        assert solar_declination(50.0, 0.0) == pytest.approx(0.0)


class TestDailyMeanInsolation:
    """Daily-mean insolation with polar day/night."""

    def test_equator_matches_solar_constant_over_pi(self) -> None:
        """Equator at equinox: Q = S/π."""
        q = daily_mean_insolation(np.array([0.0]), 0.0, 1361.0)
        assert q[0] == pytest.approx(1361.0 / np.pi, rel=1e-3)

    def test_polar_day_nonzero(self) -> None:
        """Summer pole (sun never sets) has nonzero insolation."""
        q = daily_mean_insolation(np.array([np.pi / 2]), np.radians(23.44), 1361.0)
        assert q[0] > 0.0

    def test_polar_night_zero(self) -> None:
        """Winter pole (sun never rises) has zero insolation."""
        q = daily_mean_insolation(np.array([np.pi / 2]), -np.radians(23.44), 1361.0)
        assert q[0] == pytest.approx(0.0)


class TestOrbitalDistanceFactor:
    """Eccentricity insolation factor."""

    def test_circular_is_one(self) -> None:
        assert orbital_distance_factor(50.0, 0.0) == pytest.approx(1.0)

    def test_eccentric_perihelion_brighter(self) -> None:
        """Near perihelion insolation factor > 1."""
        f = orbital_distance_factor(0.0, 0.093, orbital_period_days=687.0, perihelion_day=0.0)
        assert f > 1.0


# ---------------------------------------------------------------------------
# 2. Monthly insolation
# ---------------------------------------------------------------------------


class TestMonthlyInsolation:
    """12-month insolation array."""

    def test_shape(self) -> None:
        q = monthly_insolation(np.linspace(-np.pi / 2, np.pi / 2, 10), 23.44, 1361.0)
        assert q.shape == (10, 12)

    def test_zero_obliquity_all_months_equal(self) -> None:
        q = monthly_insolation(np.array([0.3, 0.6]), 0.0, 1361.0)
        assert np.allclose(q[:, 0], q[:, 5])
        assert np.allclose(q[:, 0], q[:, 11])

    def test_earth_equator_monthly_mean_plausible(self) -> None:
        """Earth equatorial monthly mean insolation ≈ 410–440 W/m²."""
        q = monthly_insolation(np.array([0.0]), 23.44, 1361.0)
        mean = q[0].mean()
        assert 400.0 < mean < 440.0, f"expected ~425, got {mean}"

    def test_nh_sh_opposite_phase(self) -> None:
        """NH max insolation month differs from SH by ~6 months.

        The solstice can fall between two monthly samples, so argmax tie-breaking
        gives a phase difference of 5–7 months on the discrete 12-month grid.
        """
        q = monthly_insolation(np.array([np.radians(45.0), np.radians(-45.0)]), 23.44, 1361.0)
        diff = (int(q[0].argmax()) - int(q[1].argmax())) % 12
        assert diff in (5, 6, 7)


# ---------------------------------------------------------------------------
# 2b. 1D Energy Balance Model (steady-state annual-mean temperature)
# ---------------------------------------------------------------------------


class TestSolve1DEBM:
    """Steady-state 1D EBM: 0 = D∇²T + Q(φ)(1−α) − (A + B·T)."""

    def _lat(self) -> np.ndarray:
        return np.linspace(-np.pi / 2, np.pi / 2, 181)

    @staticmethod
    def _area_mean(lat_rad: np.ndarray, t: np.ndarray) -> float:
        w = np.cos(lat_rad)
        return float(np.sum(t * w) / np.sum(w))

    def test_global_mean_anchored(self) -> None:
        """T_0 (the Legendre n=0 mode) equals the area-weighted global mean."""
        lat = self._lat()
        t = solve_1d_ebm_temperature(lat, 15.0, diffusion_wm2k=0.35)
        assert self._area_mean(lat, t) == pytest.approx(15.0, abs=0.5)

    def test_equator_warmer_than_pole(self) -> None:
        """Earth-like profile: equator ~27 °C, pole ~−13 °C (ΔT ≈ 40 °C)."""
        lat = self._lat()
        t = solve_1d_ebm_temperature(lat, 15.0, diffusion_wm2k=0.35)
        assert t[90] > t[0] + 30.0  # equator (idx 90) at least 30 °C above pole (idx 0)

    def test_stronger_diffusion_flattens(self) -> None:
        """Larger D transports more heat poleward → smaller equator-pole ΔT."""
        lat = self._lat()
        weak = solve_1d_ebm_temperature(lat, 15.0, diffusion_wm2k=0.1)
        strong = solve_1d_ebm_temperature(lat, 15.0, diffusion_wm2k=0.6)
        assert (weak[90] - weak[0]) > (strong[90] - strong[0]) + 5.0

    def test_obliquity_increases_equator_pole_contrast(self) -> None:
        """Lower obliquity concentrates annual insolation at the equator → larger ΔT."""
        lat = self._lat()
        low = solve_1d_ebm_temperature(lat, 15.0, obliquity_deg=0.0, diffusion_wm2k=0.35)
        high = solve_1d_ebm_temperature(lat, 15.0, obliquity_deg=45.0, diffusion_wm2k=0.35)
        assert (low[90] - low[0]) > (high[90] - high[0])

    def test_warm_poles_with_zero_obliquity(self) -> None:
        """0° obliquity still yields a warm equator and cold pole (no NaN)."""
        lat = self._lat()
        t = solve_1d_ebm_temperature(lat, 15.0, obliquity_deg=0.0, diffusion_wm2k=0.35)
        assert not np.isnan(t).any()
        assert t[90] > 0.0 > t[0]


# ---------------------------------------------------------------------------
# 3. Land-ocean heat capacity
# ---------------------------------------------------------------------------


class TestSeasonalHeatCapacity:
    """Per-cell surface heat capacity for the seasonal cycle."""

    def test_ocean_gets_ocean_capacity(self) -> None:
        is_land = np.array([False, False])
        is_ocean = np.array([True, True])
        d = np.array([0.0, 0.0])
        c = seasonal_heat_capacity(is_land, is_ocean, d)
        assert np.allclose(c, 2.0e8)

    def test_deep_land_approaches_land_capacity(self) -> None:
        is_land = np.array([True])
        is_ocean = np.array([False])
        d = np.array([5000.0])  # far inland
        c = seasonal_heat_capacity(is_land, is_ocean, d)
        assert c[0] < 4.0e7  # close to land capacity 2e7

    def test_coastal_between_land_and_ocean(self) -> None:
        is_land = np.array([True])
        is_ocean = np.array([False])
        d = np.array([300.0])
        c = seasonal_heat_capacity(is_land, is_ocean, d)
        assert 2.0e7 < c[0] < 2.0e8

    def test_decreases_with_distance(self) -> None:
        """Heat capacity drops from ocean-like (coast) to land-like (inland)."""
        is_land = np.ones(5, dtype=bool)
        is_ocean = np.zeros(5, dtype=bool)
        d = np.array([50.0, 200.0, 500.0, 1000.0, 3000.0])
        c = seasonal_heat_capacity(is_land, is_ocean, d)
        assert np.all(np.diff(c) < 0)


# ---------------------------------------------------------------------------
# 4. Monthly temperature
# ---------------------------------------------------------------------------


class TestMonthlyTemperature:
    """Monthly temperature from the seasonal energy-balance model."""

    _LAND_C = 2.0e7

    def _q_monthly(self) -> np.ndarray:
        return monthly_insolation(
            np.array([np.radians(45.0), np.radians(-45.0), 0.0]), 23.44, 1361.0
        )

    def test_shape_and_cold_hot(self) -> None:
        t_mean = np.array([15.0, 15.0, 27.0])
        q = self._q_monthly()
        c = np.full(3, self._LAND_C)
        t = monthly_temperature(q, t_mean, c)
        assert t.shape == (3, 12)
        # annual mean recovered (cosine is symmetric around the mean)
        assert np.allclose(t.mean(axis=1), t_mean, atol=1e-6)
        # mid-latitude cells have a real seasonal swing around the mean
        assert np.all(t.min(axis=1) < t_mean)
        assert np.all(t.max(axis=1) > t_mean)

    def test_nh_sh_opposite_phase(self) -> None:
        q = self._q_monthly()
        t_mean = np.array([15.0, 15.0, 27.0])
        t = monthly_temperature(q, t_mean, np.full(3, self._LAND_C))
        diff = (int(t[0].argmax()) - int(t[1].argmax())) % 12
        assert diff in (5, 6, 7)

    def test_equator_small_amplitude(self) -> None:
        q = self._q_monthly()
        t_mean = np.array([15.0, 15.0, 27.0])
        t = monthly_temperature(q, t_mean, np.full(3, self._LAND_C))
        eq_range = t[2].max() - t[2].min()
        mid_range = t[0].max() - t[0].min()
        assert eq_range < 3.0
        assert mid_range > eq_range

    def test_ocean_amplitude_smaller_than_land(self) -> None:
        """Same latitude: ocean annual range < land annual range."""
        q = monthly_insolation(np.array([np.radians(45.0)]), 23.44, 1361.0)
        t_mean = np.array([15.0])
        t_land = monthly_temperature(q, t_mean, np.array([2.0e7]))
        t_ocean = monthly_temperature(q, t_mean, np.array([2.0e8]))
        land_range = t_land.max() - t_land.min()
        ocean_range = t_ocean.max() - t_ocean.min()
        assert ocean_range < land_range


# ---------------------------------------------------------------------------
# 5. ITCZ migration and precipitation
# ---------------------------------------------------------------------------


class TestItczMonthly:
    """ITCZ follows the subsolar latitude (solar declination), damped by ocean inertia."""

    def test_itcz_migrates(self) -> None:
        itcz = itcz_latitude_monthly(23.44)
        assert itcz.shape == (12,)
        # ITCZ crosses into both hemispheres over the year
        assert itcz.max() > 0.0
        assert itcz.min() < 0.0
        # Damped by ocean thermal inertia: |ITCZ| ≤ obliquity × damping (0.6)
        assert itcz.max() <= 23.44 * 0.6 + 1e-6


class TestMonthlyPrecipitationFactor:
    """Monthly precipitation distribution factor."""

    def test_rows_sum_to_one(self) -> None:
        lat_deg = np.array([-40.0, 0.0, 40.0])
        itcz = np.array(
            [-20.0, -10.0, 0.0, 10.0, 20.0, 20.0, 10.0, 0.0, -10.0, -20.0, -20.0, -10.0]
        )
        is_land = np.ones(3, dtype=bool)
        f = monthly_precipitation_factor(lat_deg, itcz, is_land)
        assert f.shape == (3, 12)
        assert np.allclose(f.sum(axis=1), 1.0, atol=1e-9)

    def test_wet_dry_contrast(self) -> None:
        """A latitude under the ITCZ band has a distinct wet and dry season."""
        lat_deg = np.array([15.0])
        itcz = np.array(
            [15.0, 15.0, 15.0, 15.0, 15.0, 15.0, -15.0, -15.0, -15.0, -15.0, -15.0, -15.0]
        )
        is_land = np.ones(1, dtype=bool)
        f = monthly_precipitation_factor(lat_deg, itcz, is_land)
        assert f[0].max() > 2.0 * f[0].min()


class TestWarmColdHalfPrecip:
    """Warm/cold-half precipitation split."""

    def test_split_sums_to_annual(self) -> None:
        t = np.array([[0.0, 5.0, 10.0, 15.0, 20.0, 25.0, 26.0, 24.0, 18.0, 12.0, 6.0, 1.0]])
        p = np.ones((1, 12)) * 10.0
        p_warm, p_cold = warm_cold_half_precip(t, p)
        assert p_warm[0] + p_cold[0] == pytest.approx(120.0)
        assert p_warm[0] == pytest.approx(60.0)


# ---------------------------------------------------------------------------
# 6. Effective obliquity + high-level API
# ---------------------------------------------------------------------------


class TestEffectiveObliquity:
    """Compound obliquity helper."""

    def test_planet_identity(self) -> None:
        assert compute_effective_obliquity(23.44) == pytest.approx(23.44)

    def test_satellite_rms(self) -> None:
        eff = compute_effective_obliquity(
            0.0, orbital_inclination_deg=9.0, parent_axial_tilt_deg=3.0, is_satellite=True
        )
        assert eff == pytest.approx(np.hypot(9.0, 3.0))


class TestKoppenSeasonality:
    """Köppen B-group dryness-threshold offset from warm/cold-half precip."""

    def _classify(
        self,
        p_annual: float,
        p_warm: float,
        p_cold: float,
        *,
        t_mean: float = 10.0,
    ) -> str:
        return koppen_classify(
            t_mean_c=np.array([t_mean]),
            t_cold_c=np.array([0.0]),
            t_hot_c=np.array([20.0]),
            p_annual_mm=np.array([p_annual]),
            p_dry_mm=np.array([10.0]),
            p_wet_mm=np.array([50.0]),
            is_land=np.array([True]),
            p_warm_mm=np.array([p_warm]),
            p_cold_mm=np.array([p_cold]),
        )[0]

    def test_warm_season_wet_increases_aridity(self) -> None:
        """Warm-season concentration → offset 280 → higher dryness threshold."""
        # pa=400: even offset (140 → threshold 340) is humid; warm-season-wet
        # (offset 280 → threshold 480) is arid.
        assert self._classify(400.0, p_warm=350.0, p_cold=50.0).startswith("B")
        assert not self._classify(400.0, p_warm=200.0, p_cold=200.0).startswith("B")

    def test_cold_season_wet_decreases_aridity(self) -> None:
        """Cold-season concentration → offset 0 → lower dryness threshold."""
        # pa=300: even offset (140 → threshold 340) is arid; cold-season-wet
        # (offset 0 → threshold 200) is humid.
        assert not self._classify(300.0, p_warm=50.0, p_cold=250.0).startswith("B")
        assert self._classify(300.0, p_warm=150.0, p_cold=150.0).startswith("B")

    def test_backward_compatible_without_seasonality(self) -> None:
        """Without p_warm/p_cold the 'even' offset 140 still applies."""
        result = koppen_classify(
            t_mean_c=np.array([10.0]),
            t_cold_c=np.array([0.0]),
            t_hot_c=np.array([20.0]),
            p_annual_mm=np.array([300.0]),
            p_dry_mm=np.array([10.0]),
            p_wet_mm=np.array([50.0]),
            is_land=np.array([True]),
        )
        assert result[0].startswith("B")  # 300 < 20·10 + 140

    def test_cold_dry_cell_with_zero_precip_is_desert(self) -> None:
        """A cold cell with P≈0 (BFS numerical noise ~1e-5 mm) must be BWk.

        Regression: for T ≤ −7 °C the empirical 20·T + 140 goes ≤ 0, so the
        unclamped threshold classified a P≈0 polar desert as "humid" (Dfb).
        """
        result = koppen_classify(
            t_mean_c=np.array([-10.0]),
            t_cold_c=np.array([-25.0]),
            t_hot_c=np.array([15.0]),
            p_annual_mm=np.array([2.5e-05]),
            p_dry_mm=np.array([0.0]),
            p_wet_mm=np.array([0.0]),
            is_land=np.array([True]),
        )
        assert result[0] == "BWk", f"expected BWk (cold desert), got {result[0]}"


class TestKoppenSeasonalThirdLetter:
    """Season-aware s/w/f discrimination (dry summer vs dry winter)."""

    def _classify(
        self,
        p_dry_summer: float,
        p_wet_winter: float,
        p_dry_winter: float,
        p_wet_summer: float,
        *,
        t_cold: float = 5.0,
        t_hot: float = 20.0,
        p_annual: float = 1000.0,
    ) -> str:
        return koppen_classify(
            t_mean_c=np.array([12.0]),
            t_cold_c=np.array([t_cold]),
            t_hot_c=np.array([t_hot]),
            p_annual_mm=np.array([p_annual]),
            p_dry_mm=np.array([min(p_dry_summer, p_dry_winter)]),
            p_wet_mm=np.array([max(p_wet_winter, p_wet_summer)]),
            is_land=np.array([True]),
            p_dry_summer_mm=np.array([p_dry_summer]),
            p_wet_winter_mm=np.array([p_wet_winter]),
            p_dry_winter_mm=np.array([p_dry_winter]),
            p_wet_summer_mm=np.array([p_wet_summer]),
        )[0]

    def test_dry_winter_is_w_not_s(self) -> None:
        """A dry cold half → 'w' (dry winter), not mislabeled 's' (dry summer)."""
        # Cold half dry (5 mm driest winter month), warm half wet (150 mm).
        kc = self._classify(
            p_dry_summer=60.0, p_wet_winter=50.0, p_dry_winter=5.0, p_wet_summer=150.0
        )
        assert kc == "Cwb", f"expected Cwb (dry winter), got {kc}"

    def test_dry_summer_is_s(self) -> None:
        """A dry warm half → 's' (dry summer, Mediterranean)."""
        kc = self._classify(
            p_dry_summer=5.0, p_wet_winter=150.0, p_dry_winter=60.0, p_wet_summer=50.0
        )
        assert kc == "Csb", f"expected Csb (dry summer), got {kc}"

    def test_fully_humid_is_f(self) -> None:
        """No dry half → 'f' (fully humid)."""
        kc = self._classify(
            p_dry_summer=80.0, p_wet_winter=90.0, p_dry_winter=80.0, p_wet_summer=90.0
        )
        assert kc == "Cfb", f"expected Cfb (fully humid), got {kc}"


class TestSeasonalPrecipExtremes:
    """Per-half monthly precipitation extremes."""

    def test_split(self) -> None:
        # A single cell: 12 months, warm months (highest temp) are wet in summer.
        t = np.array([[0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 15.0, 16.0, 17.0, 18.0, 19.0, 20.0]])
        # Summer (warm half, months 6-11) precip: [100, 90, 80, 70, 60, 50]
        # Winter (cold half, months 0-5) precip: [10, 20, 30, 40, 50, 60]
        p = np.array([[10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 100.0, 90.0, 80.0, 70.0, 60.0, 50.0]])
        dsum, wwin, dwin, wsum = seasonal_precip_extremes(t, p)
        assert dsum[0] == pytest.approx(50.0)  # driest warm month
        assert wwin[0] == pytest.approx(60.0)  # wettest cold month
        assert dwin[0] == pytest.approx(10.0)  # driest cold month
        assert wsum[0] == pytest.approx(100.0)  # wettest warm month


class TestComputeSeasonalClimate:
    """High-level entry point."""

    def test_keys_and_shapes(self) -> None:
        lat_rad = np.linspace(-np.pi / 2, np.pi / 2, 37)
        t_mean = np.full(37, 15.0)
        is_land = np.ones(37, dtype=bool)
        heat_cap = np.full(37, 2.0e7)
        out = compute_seasonal_climate(lat_rad, t_mean, is_land, heat_cap, obliquity_deg=23.44)
        assert set(out) == {"T_monthly", "T_cold", "T_hot", "P_factor", "itcz_lat"}
        assert out["T_monthly"].shape == (37, 12)
        assert out["T_cold"].shape == (37,)
        assert out["P_factor"].shape == (37, 12)

    def test_nacrea_small_seasons_no_nan(self) -> None:
        """Nacrea: 9° obliquity, 67 d year → small but finite seasons, no NaN."""
        lat_rad = np.linspace(-np.pi / 2, np.pi / 2, 37)
        t_mean = np.full(37, 14.0)
        is_land = np.ones(37, dtype=bool)
        heat_cap = np.full(37, 2.0e7)
        out = compute_seasonal_climate(
            lat_rad,
            t_mean,
            is_land,
            heat_cap,
            obliquity_deg=9.0,
            orbital_period_days=67.0,
            eccentricity=0.005,
        )
        assert not np.isnan(out["T_monthly"]).any()
        assert out["T_monthly"].max() - out["T_monthly"].min() > 0.0
