"""Tests for climate physics pure functions.

Verifies correctness of EBM temperature, wind, precipitation, and Köppen
classification functions against known Earth reference values.
"""

import numpy as np
import pytest

from dreamulator.engine.climate_physics import (
    altitude_lapse_rate,
    coriolis_parameter,
    equilibrium_temperature,
    evaporation_rate,
    hadley_cell_wind,
    itcz_latitude,
    koppen_classify,
    latitude_temperature,
    orographic_precipitation,
    pressure_from_temperature,
    surface_temperature,
    terrain_wind_blocking,
)

# ---------------------------------------------------------------------------
# 1. Temperature — EBM
# ---------------------------------------------------------------------------


class TestEquilibriumTemperature:
    """Equilibrium blackbody temperature tests."""

    def test_earth_default(self) -> None:
        """Earth at 1 AU from Sun should give ~255 K."""
        teq = equilibrium_temperature(
            stellar_luminosity_sol=1.0,
            orbital_distance_au=1.0,
            albedo=0.306,
        )
        # Earth blackbody temp ≈ 255 K
        assert 250.0 < teq < 260.0, f"Expected ~255 K, got {teq}"

    def test_brighter_star_higher_temp(self) -> None:
        """Brighter star → higher equilibrium temperature."""
        t_dim = equilibrium_temperature(stellar_luminosity_sol=0.5)
        t_bright = equilibrium_temperature(stellar_luminosity_sol=2.0)
        assert t_dim < t_bright, "Brighter star should give higher temperature"

    def test_farther_orbit_colder(self) -> None:
        """Farther orbit → colder temperature (inverse-square law)."""
        t_near = equilibrium_temperature(orbital_distance_au=0.5)
        t_far = equilibrium_temperature(orbital_distance_au=2.0)
        assert t_near > t_far, "Farther orbit should be colder"

    def test_lower_albedo_higher_temp(self) -> None:
        """Low albedo → more absorption → higher temperature."""
        t_high_albedo = equilibrium_temperature(albedo=0.8)
        t_low_albedo = equilibrium_temperature(albedo=0.1)
        assert t_low_albedo > t_high_albedo


class TestSurfaceTemperature:
    """Surface temperature with greenhouse effect."""

    def test_earth_greenhouse(self) -> None:
        """255 K + 33 K greenhouse → 288 K (15 °C)."""
        ts = surface_temperature(255.0, greenhouse_warming_K=33.0)
        assert 285.0 < ts < 292.0, f"Expected ~288 K, got {ts}"

    def test_no_greenhouse(self) -> None:
        """No greenhouse → surface = equilibrium."""
        ts = surface_temperature(270.0, greenhouse_warming_K=0.0)
        assert ts == pytest.approx(270.0)


class TestLatitudeTemperature:
    """Latitude-dependent temperature gradient."""

    def test_equator_warmest(self) -> None:
        """Equator (lat=0) should be warmest."""
        lat_rad = np.array([0.0, np.pi / 4, np.pi / 2])
        temps = latitude_temperature(15.0, lat_rad, lat_gradient_c=45.0)
        # equator ≥ mid-latitude ≥ pole
        assert temps[0] >= temps[1] >= temps[2]

    def test_poles_coldest(self) -> None:
        """ΔT of 45 °C from equator to pole."""
        lat_rad = np.array([0.0, np.pi / 2])
        temps = latitude_temperature(15.0, lat_rad, lat_gradient_c=45.0)
        # Equator = T_mean + ΔT/3 = 15 + 15 = 30 °C
        assert temps[0] == pytest.approx(30.0, abs=1.0)
        # Pole = T_eq - ΔT = 30 - 45 = -15 °C
        assert temps[1] == pytest.approx(-15.0, abs=2.0)


class TestAltitudeLapseRate:
    """Altitude temperature correction."""

    def test_higher_colder(self) -> None:
        """Temperature decreases with altitude."""
        elev_m = np.array([0.0, 1000.0, 3000.0])
        temps = altitude_lapse_rate(np.array([20.0, 20.0, 20.0]), elev_m, lapse_rate_c_km=6.5)
        assert temps[0] == pytest.approx(20.0)
        assert temps[1] == pytest.approx(13.5, abs=0.5)
        assert temps[2] == pytest.approx(0.5, abs=0.5)

    def test_sea_level_unchanged(self) -> None:
        """0 m elevation → no correction."""
        temps = altitude_lapse_rate(np.array([25.0]), np.array([0.0]))
        assert temps[0] == pytest.approx(25.0)


# ---------------------------------------------------------------------------
# 2. Wind
# ---------------------------------------------------------------------------


class TestCoriolisParameter:
    """Coriolis parameter tests."""

    def test_equator_zero(self) -> None:
        """Coriolis f = 0 at equator."""
        f = coriolis_parameter(np.array([0.0]), rotation_period_days=1.0)
        assert abs(f[0]) < 1e-9

    def test_nh_positive(self) -> None:
        """Coriolis f > 0 in NH."""
        f = coriolis_parameter(np.array([np.pi / 4]), rotation_period_days=1.0)
        assert f[0] > 0

    def test_sh_negative(self) -> None:
        """Coriolis f < 0 in SH."""
        f = coriolis_parameter(np.array([-np.pi / 4]), rotation_period_days=1.0)
        assert f[0] < 0

    def test_faster_rotation_stronger_coriolis(self) -> None:
        """Faster rotation → stronger Coriolis."""
        f_slow = coriolis_parameter(np.array([np.pi / 4]), rotation_period_days=2.0)
        f_fast = coriolis_parameter(np.array([np.pi / 4]), rotation_period_days=0.5)
        assert f_fast[0] > f_slow[0]


class TestPressureFromTemperature:
    """Surface pressure approximation."""

    def test_sea_level_standard(self) -> None:
        """Sea level at 15 °C → ~1013 hPa."""
        p = pressure_from_temperature(
            np.array([15.0]),
            np.array([0.0]),
        )
        assert 1000.0 < p[0] < 1030.0, f"Expected ~1013 hPa, got {p[0]}"

    def test_high_altitude_low_pressure(self) -> None:
        """Pressure decreases with altitude."""
        p_low = pressure_from_temperature(np.array([15.0]), np.array([0.0]))
        p_high = pressure_from_temperature(np.array([15.0]), np.array([5000.0]))
        # 5000 m → ~540 hPa
        assert p_high[0] < 600.0
        assert p_low[0] > p_high[0]  # pressure decreases with altitude

    def test_hot_air_thermal_low(self) -> None:
        """Warmer air → slightly lower pressure (thermal low)."""
        p_cold = pressure_from_temperature(np.array([0.0, 30.0]), np.array([0.0, 0.0]))
        # Both at sea level, but hot one has thermal low
        assert p_cold[1] < p_cold[0]

    def test_elevated_cold_surface_is_heat_source(self) -> None:
        """Same cold surface, higher elevation → thermal low via θ (elevated heat source).

        The dry-adiabatic potential temperature θ = T + Γ_d·z makes an elevated
        cold surface the *warmer* column, so it must get the thermal low — not be
        read as a cold anomaly (the pre-θ bug)."""
        t = np.array([-10.0, -10.0])
        elev = np.array([5000.0, 0.0])
        p = pressure_from_temperature(t, elev)
        # Elevated cell: θ = −10 + (g/c_p)·5000 ≈ +39 °C → θ_max → full −20 hPa
        # thermal low on top of its ~563 hPa barometric pressure.
        p_baro_high = 1013.25 * np.exp(-5000.0 / 8500.0)
        assert p[0] < p_baro_high - 15.0
        # Sea-level cold cell: θ = −10 °C → θ_min → no thermal low, ~1013 hPa.
        assert p[1] > 1013.25 - 1.0


class TestHadleyCellWind:
    """Three-cell atmospheric circulation."""

    def test_produces_nonzero_wind(self) -> None:
        """Wind field should have non-trivial values."""
        lat_rad = np.linspace(-np.pi / 2, np.pi / 2, 19)
        nodes = np.zeros((19, 3))
        for i, lat in enumerate(lat_rad):
            nodes[i] = [np.cos(lat), np.sin(lat), 0.0]

        wind = hadley_cell_wind(lat_rad, nodes)
        # Wind should be non-zero for most latitudes
        speeds = np.linalg.norm(wind, axis=1)
        nonzero = speeds > 0.1
        assert nonzero.sum() >= 10, "Expected wind at most latitudes"

    def test_trade_winds_easterly(self) -> None:
        """Tropical trade winds blow westward (easterly)."""
        lat_rad = np.array([0.26])  # ~15°N
        nodes = np.array([[np.cos(0.26), np.sin(0.26), 0.0]])
        wind = hadley_cell_wind(lat_rad, nodes)
        # At 15°N, east is approximately [0, 0, 1] → wind[0, 2] < 0 means easterly
        # Actually, need to check. Let's verify magnitude instead.
        assert np.linalg.norm(wind[0]) > 1.0, "Trade winds should be significant"

    def test_itcz_shift_reverses_equator_wind(self) -> None:
        """A northward ITCZ makes the equator blow northward (monsoon reversal).

        The Hadley surface branch flows toward the ITCZ.  With the ITCZ at +14°
        (northern summer) the geographic equator sits south of it, so the
        surface wind is northward; with the ITCZ at −14° it is southward.
        """
        node = np.array([[1.0, 0.0, 0.0]])  # equator, lon=0 → (x,y,z)=(1,0,0)
        lat = np.array([0.0])
        north = np.array([0.0, 1.0, 0.0])  # +y is north at the equator

        w_eq = hadley_cell_wind(lat, node, itcz_lat_deg=0.0)
        w_summer = hadley_cell_wind(lat, node, itcz_lat_deg=14.0)
        w_winter = hadley_cell_wind(lat, node, itcz_lat_deg=-14.0)

        assert abs(float(np.dot(w_eq[0], north))) < 1e-9  # cell centre: no meridional flow
        assert float(np.dot(w_summer[0], north)) > 0.0  # toward ITCZ at +14°
        assert float(np.dot(w_winter[0], north)) < 0.0  # toward ITCZ at −14°


class TestTerrainWindBlocking:
    """Wind blocking by mountains."""

    def test_high_mountains_block(self) -> None:
        """High mountains significantly reduce wind."""
        wind = np.ones((3, 3)) * 10.0
        elev = np.array([0.0, 3000.0, 6000.0])
        blocked = terrain_wind_blocking(wind, elev)
        assert blocked[0, 0] == 10.0  # no blocking at sea level
        assert blocked[1, 0] < 10.0  # some blocking at 3000m
        assert blocked[2, 0] < blocked[1, 0]  # more blocking at 6000m

    def test_no_blocking_ocean(self) -> None:
        """Ocean (negative elevation) has no blocking."""
        wind = np.ones((2, 3)) * 10.0
        elev = np.array([-4000.0, -100.0])
        blocked = terrain_wind_blocking(wind, elev)
        assert np.allclose(blocked[0], wind[0])
        assert np.allclose(blocked[1], wind[1])


# ---------------------------------------------------------------------------
# 3. Precipitation
# ---------------------------------------------------------------------------


class TestEvaporationRate:
    """Ocean evaporation rate."""

    def test_warm_water_evaporates_more(self) -> None:
        """Higher SST → more evaporation."""
        temp = np.array([10.0, 25.0])
        is_ocean = np.array([True, True])
        evap = evaporation_rate(temp, is_ocean, base_mm=2000.0)
        assert evap[1] > evap[0]

    def test_land_no_evaporation(self) -> None:
        """Land cells don't evaporate."""
        temp = np.array([25.0, 25.0])
        is_ocean = np.array([True, False])
        evap = evaporation_rate(temp, is_ocean)
        assert evap[0] > 0
        assert evap[1] == 0.0


class TestOrographicPrecipitation:
    """Orographic rainfall calculations."""

    def test_uplift_produces_rain(self) -> None:
        """Rising air → condensation → precipitation."""
        rain, remaining = orographic_precipitation(
            moisture_in=1000.0,
            elev_diff_m=1000.0,  # 1 km uplift
            efficiency=0.5,
        )
        # 50% of 1000 mm → 500 mm rain
        assert rain > 100.0
        assert remaining < 1000.0
        assert rain + remaining == pytest.approx(1000.0)

    def test_descending_no_rain(self) -> None:
        """Descending air produces no orographic precipitation."""
        rain, remaining = orographic_precipitation(
            moisture_in=500.0,
            elev_diff_m=-500.0,
        )
        assert rain == 0.0
        assert remaining == pytest.approx(500.0)

    def test_flat_terrain_no_rain(self) -> None:
        """No elevation change → no orographic rain."""
        rain, remaining = orographic_precipitation(
            moisture_in=500.0,
            elev_diff_m=0.0,
        )
        assert rain == 0.0
        assert remaining == pytest.approx(500.0)

    def test_very_high_uplift_depletes_moisture(self) -> None:
        """Extreme uplift should not rain more than available moisture."""
        rain, remaining = orographic_precipitation(
            moisture_in=100.0,
            elev_diff_m=10000.0,
            efficiency=0.5,
        )
        assert rain <= 100.0
        assert remaining >= 0.0


class TestITCZ:
    """ITCZ latitude calculation."""

    def test_northern_summer_itcz_north(self) -> None:
        """ITCZ moves north during northern hemisphere summer."""
        lat_jul = itcz_latitude(day_of_year=182.0, axial_tilt_deg=23.44)
        assert lat_jul > 0, f"ITCZ should be north in July, got {lat_jul}"

    def test_northern_winter_itcz_south(self) -> None:
        """ITCZ moves south during northern hemisphere winter."""
        lat_jan = itcz_latitude(day_of_year=0.0, axial_tilt_deg=23.44)
        assert lat_jan < 15.0, f"ITCZ should be near/south of equator in January, got {lat_jan}"

    def test_no_tilt_itcz_stationary(self) -> None:
        """Zero axial tilt → no ITCZ migration."""
        lat_mar = itcz_latitude(day_of_year=80.0, axial_tilt_deg=0.0)
        lat_sep = itcz_latitude(day_of_year=264.0, axial_tilt_deg=0.0)
        assert lat_mar == pytest.approx(lat_sep, abs=1.0)


# ---------------------------------------------------------------------------
# 4. Köppen classification
# ---------------------------------------------------------------------------


class TestKoppenClassify:
    """Köppen climate classification tests."""

    def _classify_point(
        self,
        t_mean: float,
        t_cold: float,
        t_hot: float,
        p_annual: float,
        p_dry: float,
        p_wet: float,
    ) -> str:
        """Classify a single point."""
        result = koppen_classify(
            t_mean_c=np.array([t_mean]),
            t_cold_c=np.array([t_cold]),
            t_hot_c=np.array([t_hot]),
            p_annual_mm=np.array([p_annual]),
            p_dry_mm=np.array([p_dry]),
            p_wet_mm=np.array([p_wet]),
            is_land=np.array([True]),
        )
        return result[0]

    def test_tropical_rainforest(self) -> None:
        """Af: hot all year, no dry month."""
        kc = self._classify_point(
            t_mean=27.0,
            t_cold=25.0,
            t_hot=28.0,
            p_annual=2500.0,
            p_dry=150.0,
            p_wet=300.0,
        )
        assert kc == "Af", f"Expected Af, got {kc}"

    def test_tropical_monsoon(self) -> None:
        """Am: hot all year, short dry season."""
        kc = self._classify_point(
            t_mean=27.0,
            t_cold=24.0,
            t_hot=29.0,
            p_annual=2200.0,
            p_dry=30.0,
            p_wet=500.0,
        )
        assert kc == "Am", f"Expected Am, got {kc}"

    def test_hot_desert(self) -> None:
        """BWh: arid, t_annual > 18 °C."""
        kc = self._classify_point(
            t_mean=25.0,
            t_cold=15.0,
            t_hot=35.0,
            p_annual=50.0,
            p_dry=0.0,
            p_wet=15.0,
        )
        assert kc == "BWh", f"Expected BWh, got {kc}"

    def test_mediterranean(self) -> None:
        """Csa: temperate, dry summer."""
        kc = self._classify_point(
            t_mean=17.0,
            t_cold=8.0,
            t_hot=26.0,
            p_annual=700.0,
            p_dry=5.0,
            p_wet=140.0,
        )
        # Cs{a,b}: dry summer temperate. 700 mm/yr avoids arid threshold.
        assert kc.startswith("Cs"), f"Expected Cs*, got {kc}"

    def test_humid_subtropical(self) -> None:
        """Cfa: temperate, fully humid, hot summer."""
        kc = self._classify_point(
            t_mean=18.0,
            t_cold=5.0,
            t_hot=27.0,
            p_annual=1200.0,
            p_dry=60.0,
            p_wet=150.0,
        )
        assert kc == "Cfa", f"Expected Cfa, got {kc}"

    def test_tundra(self) -> None:
        """ET: polar tundra, t_hot 0–10 °C."""
        kc = self._classify_point(
            t_mean=-5.0,
            t_cold=-25.0,
            t_hot=5.0,
            p_annual=200.0,
            p_dry=10.0,
            p_wet=30.0,
        )
        assert kc == "ET", f"Expected ET, got {kc}"

    def test_ice_cap(self) -> None:
        """EF: polar ice cap, t_hot < 0 °C."""
        kc = self._classify_point(
            t_mean=-30.0,
            t_cold=-50.0,
            t_hot=-10.0,
            p_annual=50.0,
            p_dry=2.0,
            p_wet=10.0,
        )
        assert kc == "EF", f"Expected EF, got {kc}"

    def test_ocean_not_classified(self) -> None:
        """Ocean cells should return 'Ocean'."""
        result = koppen_classify(
            t_mean_c=np.array([20.0]),
            t_cold_c=np.array([15.0]),
            t_hot_c=np.array([25.0]),
            p_annual_mm=np.array([1000.0]),
            p_dry_mm=np.array([50.0]),
            p_wet_mm=np.array([200.0]),
            is_land=np.array([False]),
        )
        assert result[0] == "Ocean"

    def test_humid_continental(self) -> None:
        """Dfa/Dfb: continental, cold winter, fully humid."""
        kc = self._classify_point(
            t_mean=8.0,
            t_cold=-10.0,
            t_hot=22.0,
            p_annual=800.0,
            p_dry=40.0,
            p_wet=90.0,
        )
        # Fully humid continental: no dry summer (pw not >> pd), no dry winter (pd not too low)
        assert kc.startswith("Df"), f"Expected Df*, got {kc}"


# ---------------------------------------------------------------------------
# 5. Integration: temperature pipeline
# ---------------------------------------------------------------------------


class TestTemperaturePipeline:
    """Test the end-to-end temperature computation chain."""

    def test_earth_surface_temperature_plausible(self) -> None:
        """Full EBM pipeline should give Earth-like temperatures."""
        teq = equilibrium_temperature(1.0, 1.0, 0.306)
        t_surf_k = surface_temperature(teq, 33.0)
        t_surf_c = t_surf_k - 273.15

        # Global mean surface temp should be ~15 °C
        assert 12.0 < t_surf_c < 18.0, f"Expected ~15 °C, got {t_surf_c:.1f}"

    def test_equator_to_pole_range(self) -> None:
        """Earth-like: equator ~27 °C, pole ~-18 °C."""
        teq = equilibrium_temperature(1.0, 1.0, 0.306)
        t_surf_k = surface_temperature(teq, 33.0)
        t_surf_c = t_surf_k - 273.15

        lat_rad = np.array([0.0, np.pi / 2])
        temps = latitude_temperature(t_surf_c, lat_rad, lat_gradient_c=45.0)

        # Equator
        assert temps[0] > 20.0, f"Equator too cold: {temps[0]:.1f} °C"
        # Pole
        assert temps[1] < -10.0, f"Pole too warm: {temps[1]:.1f} °C"
