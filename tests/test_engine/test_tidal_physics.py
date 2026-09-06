"""Unit tests for tidal_physics.py — Peale & Cassen heating + plate-speed scaling."""

from __future__ import annotations

import math

import pytest

from dreamulator.engine.tidal_physics import (
    AU_M,
    EARTH_MASS_KG,
    mean_motion_rad_s,
    ocean_equilibrium_tide_range_m,
    ocean_natural_period_h,
    plate_speed_cm_yr,
    resonance_factor,
    resonant_tidal_range_m,
    tidal_heat_flux_w_m2,
    tidal_heating_power_w,
    tidal_potential_scale_m,
)

# nacrea parameters (stellar.yaml + physical_params.md).
_MASS_AEGIS_KG = 508.5 * EARTH_MASS_KG
_RADIUS_NACREA_M = 6817.0e3
_A_NACREA_M = 0.00494 * AU_M
_E_NACREA = 0.002
_K2_OVER_Q = 0.003


def _nacrea_flux_w_m2() -> float:
    n = mean_motion_rad_s(_MASS_AEGIS_KG, _A_NACREA_M)
    power = tidal_heating_power_w(
        mass_primary_kg=_MASS_AEGIS_KG,
        radius_m=_RADIUS_NACREA_M,
        semi_major_axis_m=_A_NACREA_M,
        eccentricity=_E_NACREA,
        mean_motion_rad_s=n,
        k2_over_q=_K2_OVER_Q,
    )
    return tidal_heat_flux_w_m2(power, _RADIUS_NACREA_M)


def test_mean_motion_kepler() -> None:
    n = mean_motion_rad_s(_MASS_AEGIS_KG, _A_NACREA_M)
    period_days = 2.0 * math.pi / n / 86400.0
    assert period_days == pytest.approx(3.25, rel=0.01)


def test_tidal_heating_power_nacrea() -> None:
    n = mean_motion_rad_s(_MASS_AEGIS_KG, _A_NACREA_M)
    power = tidal_heating_power_w(
        mass_primary_kg=_MASS_AEGIS_KG,
        radius_m=_RADIUS_NACREA_M,
        semi_major_axis_m=_A_NACREA_M,
        eccentricity=_E_NACREA,
        mean_motion_rad_s=n,
        k2_over_q=_K2_OVER_Q,
    )
    # ~157 TW (Peale & Cassen 1978).
    assert power == pytest.approx(1.568e14, rel=0.01)


def test_tidal_heat_flux_nacrea() -> None:
    assert _nacrea_flux_w_m2() == pytest.approx(0.2685, rel=0.01)


def test_plate_speed_nacrea_reproduces_15() -> None:
    v = plate_speed_cm_yr(_nacrea_flux_w_m2(), v_ref_cm_yr=5.0, q_ref_w_m2=0.09, beta=1.0)
    # Raw ~14.9 cm/yr; the 0.5 cm/yr rounding used in resolve_tidal_heating
    # keeps the authored 15.0 unchanged.
    assert v == pytest.approx(14.92, rel=0.01)
    assert round(v * 2.0) / 2.0 == 15.0


def test_plate_speed_earth_anchor() -> None:
    # Earth's own flux (0.09) with β=1 must reproduce Earth's 5 cm/yr.
    v = plate_speed_cm_yr(0.09, v_ref_cm_yr=5.0, q_ref_w_m2=0.09, beta=1.0)
    assert v == pytest.approx(5.0)


# Tidal-range parameters (tidal_effects.md): the ~44 m resonant equilibrium tide.
_MASS_NACREA_KG = 1.2 * EARTH_MASS_KG
_GRAVITY_NACREA_M_S2 = 10.282
_OCEAN_DEPTH_NACREA_M = 4000.0
_TIDAL_PERIOD_H = 3.25 * 24.0  # 78 h


def test_tidal_potential_scale_nacrea() -> None:
    z = tidal_potential_scale_m(_MASS_AEGIS_KG, _MASS_NACREA_KG, _RADIUS_NACREA_M, _A_NACREA_M)
    assert z == pytest.approx(2267.0, rel=0.01)


def test_ocean_equilibrium_tide_range_nacrea() -> None:
    z = tidal_potential_scale_m(_MASS_AEGIS_KG, _MASS_NACREA_KG, _RADIUS_NACREA_M, _A_NACREA_M)
    rng = ocean_equilibrium_tide_range_m(z, _E_NACREA)
    # 19.0 m peak-to-trough (tidal_effects.md).
    assert rng == pytest.approx(19.0, rel=0.01)


def test_ocean_natural_period_nacrea() -> None:
    period_h = ocean_natural_period_h(_RADIUS_NACREA_M, _GRAVITY_NACREA_M_S2, _OCEAN_DEPTH_NACREA_M)
    # 58.7 h (tidal_effects.md).
    assert period_h == pytest.approx(58.7, rel=0.01)


def test_resonance_factor_nacrea() -> None:
    rf = resonance_factor(58.7, _TIDAL_PERIOD_H)
    # 2.3× (tidal_effects.md).
    assert rf == pytest.approx(2.3, rel=0.01)


def test_resonant_tidal_range_nacrea() -> None:
    rng = resonant_tidal_range_m(
        mass_primary_kg=_MASS_AEGIS_KG,
        mass_satellite_kg=_MASS_NACREA_KG,
        radius_m=_RADIUS_NACREA_M,
        semi_major_axis_m=_A_NACREA_M,
        eccentricity=_E_NACREA,
        gravity_m_s2=_GRAVITY_NACREA_M_S2,
        ocean_depth_m=_OCEAN_DEPTH_NACREA_M,
        tidal_period_h=_TIDAL_PERIOD_H,
    )
    # ~44 m (tidal_effects.md).
    assert rng == pytest.approx(43.9, rel=0.01)
