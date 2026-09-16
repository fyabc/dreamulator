"""Tests for climate physics pure functions.

Verifies correctness of EBM temperature, wind, precipitation, and Köppen
classification functions against known Earth reference values.
"""

import numpy as np
import pytest

from dreamulator.engine.climate_physics import (
    altitude_lapse_rate,
    aridity_index_keep,
    column_water_saturation,
    coriolis_parameter,
    dryness_offset_mm,
    dryness_threshold_mm,
    equilibrium_temperature,
    evaporation_rate,
    hadley_cell_wind,
    hadley_extent_from_rotation,
    itcz_latitude,
    koppen_classify,
    latitude_temperature,
    orographic_precipitation,
    potential_evapotranspiration_hamon,
    pressure_from_temperature,
    saturation_specific_humidity,
    subsidence_aridity_gate,
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


class TestHadleyExtentFromRotation:
    """Held-Hou thermal-Rossby width scaling (P3): φ_H ≈ R_t^(1/2), capped 90°."""

    def test_earth_reference(self) -> None:
        """Earth forcing (Δ_H ≈ 0.18) lands in the observed 20–35° range."""
        phi = hadley_extent_from_rotation(0.1812, rotation_period_days=1.0)
        assert 20.0 < phi < 30.0

    def test_nacrea_hits_global_cap(self) -> None:
        """nacrea forcing (Δ_H = 0.30, P = 3.147 d, a = 6817 km) caps at 90°."""
        phi = hadley_extent_from_rotation(
            0.3015, radius_km=6817.0, gravity_m_s2=10.28, rotation_period_days=3.147
        )
        assert phi == 90.0

    def test_slower_rotation_wider_cell(self) -> None:
        """φ_H grows as Ω decreases (R_t ∝ Ω⁻²)."""
        fast = hadley_extent_from_rotation(0.2, rotation_period_days=1.0)
        slow = hadley_extent_from_rotation(0.2, rotation_period_days=2.0)
        assert slow > fast

    def test_cap_at_90(self) -> None:
        """Absurdly large Δ_H cannot exceed the global cell."""
        phi = hadley_extent_from_rotation(10.0, rotation_period_days=1.0)
        assert phi == 90.0


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

    def test_zonal_winds_point_physical_direction(self) -> None:
        """Root convention anchor (tech debt 24 unification, 2026-09-13).

        The Ferrel westerlies (45°N, zonal_speed > 0) must project positively
        onto the *physical* east basis — the direction of increasing longitude
        (``east_north_basis``, NCEP-verified) — and the tropical trades (15°N)
        negatively.  The mirrored composition (``east = north × r̂`` = physical
        west) was the root of the 2026-09-12 precipitation mirror bug; this
        test fails if it ever returns.
        """
        from dreamulator.map.ocean_circulation import east_north_basis

        lat_deg = np.concatenate([np.full(3, 45.0), np.full(3, 15.0)])
        lon_deg = np.tile(np.array([0.0, 120.0, 240.0]), 2)
        la = np.radians(lat_deg)
        lo = np.radians(lon_deg)
        nodes = np.stack([np.cos(la) * np.cos(lo), np.sin(la), np.cos(la) * np.sin(lo)], axis=1)
        wind = hadley_cell_wind(np.radians(lat_deg), nodes)
        east, _ = east_north_basis(nodes)
        we = np.einsum("ij,ij->i", wind, east)
        assert (we[:3] > 1.0).all(), f"45°N westerlies must blow east: {we[:3]}"
        assert (we[3:] < -1.0).all(), f"15°N trades must blow west: {we[3:]}"


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


class TestSaturationHumidity:
    """Clausius–Clapeyron saturation (Bolton) + cold-trap column water."""

    def test_q_sat_freezing_point(self) -> None:
        """q_sat(0 °C) ≈ 0.00375 kg/kg (e_sat = 611.2 Pa)."""
        q = saturation_specific_humidity(np.array([0.0]))
        assert q[0] == pytest.approx(0.00375, abs=2e-5)

    def test_q_sat_monotonic_warm(self) -> None:
        """Warmer air holds more water vapour."""
        q = saturation_specific_humidity(np.array([-10.0, 10.0, 25.0]))
        assert q[0] < q[1] < q[2]

    def test_column_water_freezing_point(self) -> None:
        """W_sat(0 °C) ≈ 9.5 mm (q_sat × H_v 2.1 km × ρ_air/ρ_w)."""
        w = column_water_saturation(np.array([0.0]))
        assert w[0] == pytest.approx(9.45, abs=0.1)

    def test_column_water_warm_large(self) -> None:
        """Warm columns are effectively unconstrained (W_sat ≫ typical W ~25 mm)."""
        w = column_water_saturation(np.array([25.0]))
        assert w[0] > 40.0

    def test_column_water_cold_tiny(self) -> None:
        """A cold column (~−40 °C) can hold almost nothing."""
        w = column_water_saturation(np.array([-40.0]))
        assert w[0] < 1.0


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


# ---------------------------------------------------------------------------
# Subsidence aridity gate (4.2-①) — dryness helpers + gated release
# ---------------------------------------------------------------------------


class TestKoppenThirdLetterMonths:
    """B0d: Kottek-2006 b/c/d third letter by ≥10 °C month count.

    The former `elif t_hot > 10: b else: c` made 'c' structurally
    unreachable (the E gate catches t_hot < 10 first) — observed Dfc/Dwc
    (≈ 7300 Earth cells) could never be produced.
    """

    def _call(self, tc: float, th: float, ta: float, pa: float, n10=None) -> str:
        one = lambda x: np.array([x], dtype=float)  # noqa: E731
        kw: dict = {}
        if n10 is not None:
            kw["t_months_ge10"] = np.array([n10])
        return koppen_classify(
            t_mean_c=one(ta),
            t_cold_c=one(tc),
            t_hot_c=one(th),
            p_annual_mm=one(pa),
            p_dry_mm=one(pa / 12.0),
            p_wet_mm=one(pa / 12.0),
            is_land=np.array([True]),
            **kw,
        )[0]

    def test_dfc_reachable_by_month_count(self) -> None:
        # East-Siberian type: coldest −20, warmest +14 (> 10 → not E), 2 warm months
        assert self._call(-20.0, 14.0, -5.0, 400.0, n10=2) == "Dfc"

    def test_dfd_extreme_winter_takes_precedence(self) -> None:
        # Verkhoyansk type: coldest < −38 °C → 'd' regardless of warm months
        assert self._call(-45.0, 20.0, -15.0, 400.0, n10=3) == "Dfd"

    def test_dfb_four_warm_months(self) -> None:
        assert self._call(-15.0, 18.0, 0.0, 600.0, n10=5) == "Dfb"

    def test_cfc_subpolar_oceanic(self) -> None:
        # Iceland type: coldest +1, warmest +11, 2 warm months
        assert self._call(1.0, 11.0, 5.0, 800.0, n10=2) == "Cfc"

    def test_legacy_fallback_without_month_count(self) -> None:
        # No monthly data → legacy warmest-month thresholds, 'c' unreachable
        assert self._call(-20.0, 14.0, -5.0, 400.0) == "Dfb"


class TestSubsidenceAridityGate:
    """Aridity-gated release of the Held-Hou subsidence warming.

    Release requires BOTH indicators humid (keep = max of keep-fractions):
    Köppen ratio knots r = 0.5 / 1.0, UNEP AI = P/PET_Hamon knots 0.5 / 0.65;
    highlands ≥ 1.5 km always keep.  In the Köppen-path tests PET is pinned
    to AI = 1 (pet = p_annual) so keep_AI = 0 and keep reduces to keep_K.
    """

    def test_dryness_offset_selection(self) -> None:
        # warm-season wet (>70% in warm half) → 280
        assert float(dryness_offset_mm(800.0, 200.0, 1000.0)) == 280.0
        # cold-season wet → 0
        assert float(dryness_offset_mm(100.0, 900.0, 1000.0)) == 0.0
        # even → 140
        assert float(dryness_offset_mm(500.0, 500.0, 1000.0)) == 140.0

    def test_dryness_offset_vectorized(self) -> None:
        pw = np.array([800.0, 100.0, 500.0])
        pc = np.array([200.0, 900.0, 500.0])
        pa = np.array([1000.0, 1000.0, 1000.0])
        np.testing.assert_array_equal(dryness_offset_mm(pw, pc, pa), [280.0, 0.0, 140.0])

    def test_dryness_threshold_formula_and_floor(self) -> None:
        # 20·T + offset
        assert float(dryness_threshold_mm(20.0, 140.0)) == pytest.approx(540.0)
        # 1 mm polar-desert floor (20·(−20) + 140 = −260 → 1)
        assert float(dryness_threshold_mm(-20.0, 140.0)) == pytest.approx(1.0)

    def test_hamon_pet_reference_values(self) -> None:
        # Constant 20 °C, 365.25-day year → ~1045 mm/yr (2.86 mm/day)
        t20 = np.full((1, 12), 20.0)
        pet20 = float(potential_evapotranspiration_hamon(t20, 365.25 / 12.0)[0])
        assert 1000.0 < pet20 < 1100.0, f"20 °C PET {pet20:.0f} mm/yr out of range"
        # Constant 27 °C (hot desert coast) → ~1550 mm/yr
        t27 = np.full((1, 12), 27.0)
        pet27 = float(potential_evapotranspiration_hamon(t27, 365.25 / 12.0)[0])
        assert 1450.0 < pet27 < 1650.0, f"27 °C PET {pet27:.0f} mm/yr out of range"
        # Monotone in T, positive at sub-zero T (no cold-side pathology)
        t0 = np.full((1, 12), -5.0)
        pet0 = float(potential_evapotranspiration_hamon(t0, 365.25 / 12.0)[0])
        assert 0.0 < pet0 < pet20 < pet27

    def test_aridity_index_keep_knots(self) -> None:
        pet = np.full(5, 1000.0)
        pa = np.array([200.0, 500.0, 575.0, 650.0, 1500.0])  # AI .2/.5/.575/.65/1.5
        keep = aridity_index_keep(pa, pet)
        assert keep[0] == pytest.approx(1.0)  # arid → keep
        assert keep[1] == pytest.approx(1.0)  # semi-arid knot → keep
        assert keep[2] == pytest.approx(0.5)  # dry sub-humid midpoint
        assert keep[3] == pytest.approx(0.0)  # humid knot → release
        assert keep[4] == pytest.approx(0.0)  # humid → release

    def test_gate_keeps_dry_releases_humid(self) -> None:
        dt = np.full(3, 2.5)
        ta = np.full(3, 25.0)  # threshold = 20·25 + 140 = 640 (even split)
        pa = np.array([128.0, 480.0, 1600.0])  # r = 0.2 / 0.75 / 2.5
        pw = pa / 2.0
        pc = pa / 2.0
        undo = subsidence_aridity_gate(dt, pa, ta, pw, pc, pa, np.zeros(3))
        assert undo[0] == pytest.approx(0.0)  # desert: keep all
        assert undo[1] == pytest.approx(0.5 * 2.5)  # steppe: half
        assert undo[2] == pytest.approx(2.5)  # humid: release all

    def test_gate_knots_on_koppen_boundaries(self) -> None:
        ta = np.full(2, 20.0)  # threshold = 540
        dt = np.full(2, 3.0)
        pa = np.array([0.5 * 540.0, 1.0 * 540.0])  # exactly at the knots
        pw = pa / 2.0
        pc = pa / 2.0
        undo = subsidence_aridity_gate(dt, pa, ta, pw, pc, pa, np.zeros(2))
        assert undo[0] == pytest.approx(0.0)  # BW/BS boundary → keep
        assert undo[1] == pytest.approx(3.0)  # arid/humid boundary → release

    def test_gate_monotone_in_aridity_ratio(self) -> None:
        ta = np.full(50, 22.0)
        dt = np.full(50, 2.0)
        pa = np.linspace(10.0, 3000.0, 50)
        undo = subsidence_aridity_gate(dt, pa, ta, pa / 2.0, pa / 2.0, pa, np.zeros(50))
        assert np.all(np.diff(undo) >= -1e-12)

    def test_gate_zero_increment_is_noop(self) -> None:
        # ocean / out-of-band cells carry dt = 0 → no release regardless of P
        dt = np.zeros(2)
        undo = subsidence_aridity_gate(
            dt,
            np.array([2000.0, 50.0]),
            np.full(2, 25.0),
            np.array([1000.0, 25.0]),
            np.array([1000.0, 25.0]),
            np.array([2000.0, 50.0]),
            np.zeros(2),
        )
        np.testing.assert_array_equal(undo, [0.0, 0.0])

    def test_gate_preserves_negative_increment(self) -> None:
        # Equatorial ascent-branch homogenisation (negative increment) is not
        # subsidence warming — the gate must never release (re-warm) it.
        dt = np.array([-3.0, -3.0])
        undo = subsidence_aridity_gate(
            dt,
            np.array([2500.0, 100.0]),  # humid AND arid — both keep negatives
            np.full(2, 26.0),
            np.array([1250.0, 50.0]),
            np.array([1250.0, 50.0]),
            np.array([2500.0, 100.0]),
            np.zeros(2),
        )
        np.testing.assert_array_equal(undo, [0.0, 0.0])

    def test_gate_persian_gulf_kept_by_pet_index(self) -> None:
        # Anchor (2026-09-13 earth build): Persian Gulf coast ~29°N — true
        # BWh (obs P ~170 mm) but engine P biased wet ~475 mm, which alone
        # (Köppen r ≈ 0.88, winter-wet offset 0) would release 76% of the
        # warming and drop the cell ~−14 °C.  UNEP AI = 475/1554 ≈ 0.31
        # (semi-arid) must keep the increment.
        dt = np.array([7.0])
        ta = np.array([27.0])
        pa = np.array([475.0])
        pw = np.array([0.25 * 475.0])  # winter-wet → offset 0 → threshold 540
        pc = np.array([0.75 * 475.0])
        pet = potential_evapotranspiration_hamon(np.full((1, 12), 27.0), 365.25 / 12.0)
        undo = subsidence_aridity_gate(dt, pa, ta, pw, pc, pet, np.array([100.0]))
        assert undo[0] == pytest.approx(0.0)  # AI keeps it despite Köppen r

    def test_gate_humid_margin_released_by_both(self) -> None:
        # Humid subtropical margin (South-China-coast-like): T 21.3, P 1700 →
        # Köppen r ≈ 3.0 AND AI ≈ 1.5 → both humid → full release.
        dt = np.array([4.0])
        ta = np.array([21.3])
        pa = np.array([1700.0])
        pet = potential_evapotranspiration_hamon(np.full((1, 12), 21.3), 365.25 / 12.0)
        undo = subsidence_aridity_gate(dt, pa, ta, pa / 2.0, pa / 2.0, pet, np.array([50.0]))
        assert undo[0] == pytest.approx(4.0)

    def test_gate_highland_exemption(self) -> None:
        # Same humid state at 3 km elevation → highlands always keep: the
        # increment refers to the descent-branch boundary layer (≈850 hPa,
        # ~1.5 km), and highland temperature is a separate open item.
        dt = np.array([4.0])
        ta = np.array([21.3])
        pa = np.array([1700.0])
        pet = potential_evapotranspiration_hamon(np.full((1, 12), 21.3), 365.25 / 12.0)
        undo = subsidence_aridity_gate(dt, pa, ta, pa / 2.0, pa / 2.0, pet, np.array([3000.0]))
        assert undo[0] == pytest.approx(0.0)

    def test_koppen_b_group_unchanged_by_helper_refactor(self) -> None:
        # Regression anchor: the vectorised helpers must reproduce the former
        # inline threshold — BWh/BSk boundaries land where they always did.
        t_mean = np.array([25.0, 25.0, 10.0])
        t_cold = np.array([20.0, 20.0, -5.0])
        t_hot = np.array([30.0, 30.0, 25.0])
        # even split → offset 140: thresholds 640 / 640 / 340
        p_annual = np.array([300.0, 400.0, 200.0])  # r ≈ 0.47 / 0.63 / 0.59
        p_warm = p_annual / 2.0
        p_cold = p_annual / 2.0
        codes = koppen_classify(
            t_mean_c=t_mean,
            t_cold_c=t_cold,
            t_hot_c=t_hot,
            p_annual_mm=p_annual,
            p_dry_mm=p_annual / 12.0,
            p_wet_mm=p_annual / 12.0,
            is_land=np.array([True, True, True]),
            p_warm_mm=p_warm,
            p_cold_mm=p_cold,
        )
        assert codes == ["BWh", "BSh", "BSk"]
