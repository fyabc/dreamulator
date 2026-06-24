"""Tests for stellar_physics pure computation module."""

import math

import pytest

from dreamulator.engine.stellar_physics import (
    apply_age_metallicity,
    compute_stellar_parameters,
    condensation_lines,
    effective_temperature,
    equilibrium_temperature,
    evolution_progress,
    habitable_zone_boundaries,
    instellation,
    instellation_earth_units,
    invert_mass_from_luminosity,
    main_sequence_lifetime,
    mass_luminosity_zams,
    mass_radius_zams,
)


class TestMassLuminosityZAMS:
    """Test the four-segment Kippenhahn mass-luminosity relation."""

    def test_low_mass_star(self):
        """Fully convective low-mass star (M < 0.43)."""
        L = mass_luminosity_zams(0.2)
        expected = 0.23 * 0.2**2.3
        assert L == pytest.approx(expected, rel=1e-6)

    def test_solar_mass(self):
        """Solar-type star (0.43 ≤ M < 2): L = M^4."""
        assert mass_luminosity_zams(1.0) == pytest.approx(1.0, rel=1e-6)

    def test_mid_mass(self):
        """Mid-mass star (2 ≤ M < 55)."""
        L = mass_luminosity_zams(5.0)
        expected = 1.4 * 5.0**3.5
        assert L == pytest.approx(expected, rel=1e-6)

    def test_high_mass(self):
        """Very massive star (M ≥ 55), radiation-pressure dominated."""
        L = mass_luminosity_zams(60.0)
        expected = 32000.0 * 60.0
        assert L == pytest.approx(expected, rel=1e-6)

    def test_boundary_continuity_low(self):
        """Continuity at M = 0.43 boundary."""
        L_below = 0.23 * 0.43**2.3
        L_above = 0.43**4.0
        # These should be approximately equal (piecewise continuity)
        assert L_below == pytest.approx(L_above, rel=0.05)

    def test_boundary_continuity_mid(self):
        """Continuity at M = 2 boundary."""
        L_below = 2.0**4.0  # = 16
        L_above = 1.4 * 2.0**3.5
        assert L_below == pytest.approx(L_above, rel=0.05)


class TestMassRadiusZAMS:
    """Test the modified Demircan & Kahraman mass-radius relation."""

    def test_solar_radius(self):
        """M=1 → R=1 (by design of modified relation)."""
        assert mass_radius_zams(1.0) == pytest.approx(1.0, rel=1e-6)

    def test_low_mass(self):
        R = mass_radius_zams(0.5)
        expected = 0.5**0.945
        assert R == pytest.approx(expected, rel=1e-6)

    def test_high_mass(self):
        R = mass_radius_zams(3.0)
        expected = 1.25 * 3.0**0.555
        assert R == pytest.approx(expected, rel=1e-6)


class TestMainSequenceLifetime:
    def test_sun(self):
        assert main_sequence_lifetime(1.0) == pytest.approx(10.0, rel=1e-6)

    def test_massive_star_short_lived(self):
        t = main_sequence_lifetime(10.0)
        assert t < 0.1  # ~31 Myr

    def test_low_mass_long_lived(self):
        t = main_sequence_lifetime(0.2)
        assert t > 100  # > 100 Gyr


class TestEvolutionProgress:
    def test_sun(self):
        tau = evolution_progress(4.6, 1.0)
        assert tau == pytest.approx(0.46, rel=0.01)

    def test_newborn(self):
        assert evolution_progress(0.0, 1.0) == 0.0

    def test_clamped_at_one(self):
        """Star past MS lifetime is clamped to τ=1."""
        assert evolution_progress(100.0, 1.0) == 1.0


class TestAgeMetallicity:
    def test_solar_normalisation(self):
        """M=1, t=4.6 Gyr → L=1.0, R=1.0 (solar normalisation)."""
        tau = evolution_progress(4.6, 1.0)
        L, R = apply_age_metallicity(1.0, 1.0, tau, z=1.0)
        assert L == pytest.approx(1.0, rel=0.01)
        assert R == pytest.approx(1.0, rel=0.01)

    def test_low_metallicity_hotter(self):
        """Low metallicity → slightly higher luminosity, smaller radius."""
        L_low, R_low = apply_age_metallicity(1.0, 1.0, 0.0, z=0.1)
        L_solar, R_solar = apply_age_metallicity(1.0, 1.0, 0.0, z=1.0)
        assert L_low > L_solar  # z^-0.1 > 1 for z < 1
        assert R_low < R_solar  # z^0.05 < 1 for z < 1


class TestEffectiveTemperature:
    def test_sun(self):
        T = effective_temperature(1.0, 1.0)
        assert T == pytest.approx(5772.0, rel=1e-6)

    def test_hotter_star(self):
        """Higher L/R² → higher T."""
        T = effective_temperature(10.0, 2.0)
        assert T > 5772.0


class TestInvertMassFromLuminosity:
    def test_solar(self):
        M = invert_mass_from_luminosity(1.0)
        assert M == pytest.approx(1.0, rel=1e-3)

    def test_low_luminosity(self):
        M = invert_mass_from_luminosity(0.01)
        assert 0.1 < M < 0.4  # Should be in the low-mass segment

    def test_high_luminosity(self):
        M = invert_mass_from_luminosity(1000.0)
        assert M > 2.0  # Should be in the mid-mass segment

    @pytest.mark.parametrize("mass_in", [0.2, 0.5, 1.0, 2.0, 10.0])
    def test_roundtrip(self, mass_in):
        """Forward → inverse roundtrip should recover mass within 10%."""
        L = mass_luminosity_zams(mass_in)
        M_out = invert_mass_from_luminosity(L)
        assert M_out == pytest.approx(mass_in, rel=0.10)


class TestComputeStellarParameters:
    def test_sun_exact(self):
        """M=1, t=4.6 Gyr, Z=0 → L=1, R=1, T=5772."""
        p = compute_stellar_parameters(mass=1.0, age_gyr=4.6, metallicity_dex=0.0)
        assert p["luminosity"] == pytest.approx(1.0, rel=0.01)
        assert p["radius"] == pytest.approx(1.0, rel=0.01)
        assert p["temperature"] == pytest.approx(5772.0, rel=0.01)
        assert p["input_mode"] == "mass"

    def test_m_dwarf(self):
        """M=0.45 M dwarf — should give low luminosity and temperature."""
        p = compute_stellar_parameters(mass=0.45, age_gyr=5.0)
        assert p["luminosity"] < 0.1
        assert p["temperature"] < 4000
        assert p["ms_lifetime_gyr"] > 50

    def test_luminosity_input_mode(self):
        """Provide only luminosity → engine inverts to mass."""
        p = compute_stellar_parameters(luminosity=1.0, age_gyr=4.6)
        assert p["mass"] == pytest.approx(1.0, rel=0.05)
        assert p["input_mode"] == "luminosity"

    def test_both_mode(self):
        """Provide both mass and luminosity."""
        p = compute_stellar_parameters(mass=1.0, luminosity=1.0, age_gyr=4.6)
        assert p["input_mode"] == "both"
        assert p["luminosity"] == 1.0  # User override

    def test_neither_raises(self):
        with pytest.raises(ValueError, match="(?i)at least one"):
            compute_stellar_parameters()

    def test_metallicity_effect(self):
        """Low metallicity → higher temperature."""
        p_solar = compute_stellar_parameters(mass=1.0, metallicity_dex=0.0)
        p_poor = compute_stellar_parameters(mass=1.0, metallicity_dex=-1.0)
        assert p_poor["temperature"] > p_solar["temperature"]


class TestHabitableZone:
    def test_solar_hz(self):
        """Solar HZ boundaries should match Kopparapu (2013) values."""
        hz = habitable_zone_boundaries(1.0, 5772.0)
        assert hz["runaway_greenhouse_au"] == pytest.approx(0.976, rel=0.02)
        assert hz["max_greenhouse_au"] == pytest.approx(1.707, rel=0.02)
        assert hz["recent_venus_au"] < hz["runaway_greenhouse_au"]
        assert hz["early_mars_au"] > hz["max_greenhouse_au"]

    def test_dim_star_hz_closer(self):
        """Dimmer star → HZ closer in."""
        hz_sun = habitable_zone_boundaries(1.0, 5772.0)
        hz_m = habitable_zone_boundaries(0.03, 3500.0)
        assert hz_m["runaway_greenhouse_au"] < hz_sun["runaway_greenhouse_au"]


class TestInstellation:
    def test_solar_constant(self):
        """Earth receives ~1361 W/m² from the Sun."""
        S = instellation(1.0, 1.0)
        assert S == pytest.approx(1361.0, rel=0.01)

    def test_inverse_square(self):
        """Doubling distance → 1/4 flux."""
        S1 = instellation(1.0, 1.0)
        S2 = instellation(1.0, 2.0)
        assert S2 == pytest.approx(S1 / 4.0, rel=1e-6)

    def test_earth_units(self):
        assert instellation_earth_units(1.0, 1.0) == pytest.approx(1.0, rel=1e-6)
        assert instellation_earth_units(4.0, 2.0) == pytest.approx(1.0, rel=1e-6)


class TestEquilibriumTemperature:
    def test_earth(self):
        """Earth's equilibrium temperature ≈ 255 K (full redistribution)."""
        T = equilibrium_temperature(1.0, 1.0, albedo=0.3, f_redist=16.0)
        assert T == pytest.approx(255.0, rel=0.02)

    def test_dayside_only(self):
        """Dayside-only redistribution → higher temperature."""
        T_full = equilibrium_temperature(1.0, 1.0, f_redist=16.0)
        T_day = equilibrium_temperature(1.0, 1.0, f_redist=8.0)
        assert T_day > T_full

    def test_zero_albedo(self):
        """No reflection → higher temperature."""
        T_albedo = equilibrium_temperature(1.0, 1.0, albedo=0.3)
        T_black = equilibrium_temperature(1.0, 1.0, albedo=0.0)
        assert T_black > T_albedo


class TestCondensationLines:
    def test_solar_snow_line(self):
        """Water snow line for Sun ≈ 2.7 AU."""
        lines = condensation_lines(1.0)
        assert lines["water_snow_line_au"] == pytest.approx(2.7, rel=0.1)

    def test_ordering(self):
        """Rock < water < CO₂ < CO."""
        lines = condensation_lines(1.0)
        assert lines["rock_line_au"] < lines["water_snow_line_au"]
        assert lines["water_snow_line_au"] < lines["co2_ice_line_au"]
        assert lines["co2_ice_line_au"] < lines["co_snow_line_au"]

    def test_scales_with_sqrt_luminosity(self):
        """Snow lines scale as √L."""
        lines_1 = condensation_lines(1.0)
        lines_4 = condensation_lines(4.0)
        ratio = lines_4["water_snow_line_au"] / lines_1["water_snow_line_au"]
        assert ratio == pytest.approx(2.0, rel=0.01)
