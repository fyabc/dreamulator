"""Unit tests for tidal_physics.py — Peale & Cassen heating + plate-speed scaling."""

from __future__ import annotations

import math

import pytest

from dreamulator.engine.tidal_physics import (
    AU_M,
    EARTH_MASS_KG,
    mean_motion_rad_s,
    plate_speed_cm_yr,
    tidal_heat_flux_w_m2,
    tidal_heating_power_w,
)

# gaia-m parameters (stellar.yaml + physical_params.md).
_MASS_AEGIS_KG = 508.5 * EARTH_MASS_KG
_RADIUS_GAIAM_M = 6817.0e3
_A_GAIAM_M = 0.00494 * AU_M
_E_GAIAM = 0.002
_K2_OVER_Q = 0.003


def _gaiam_flux_w_m2() -> float:
    n = mean_motion_rad_s(_MASS_AEGIS_KG, _A_GAIAM_M)
    power = tidal_heating_power_w(
        mass_primary_kg=_MASS_AEGIS_KG,
        radius_m=_RADIUS_GAIAM_M,
        semi_major_axis_m=_A_GAIAM_M,
        eccentricity=_E_GAIAM,
        mean_motion_rad_s=n,
        k2_over_q=_K2_OVER_Q,
    )
    return tidal_heat_flux_w_m2(power, _RADIUS_GAIAM_M)


def test_mean_motion_kepler() -> None:
    n = mean_motion_rad_s(_MASS_AEGIS_KG, _A_GAIAM_M)
    period_days = 2.0 * math.pi / n / 86400.0
    assert period_days == pytest.approx(3.25, rel=0.01)


def test_tidal_heating_power_gaiam() -> None:
    n = mean_motion_rad_s(_MASS_AEGIS_KG, _A_GAIAM_M)
    power = tidal_heating_power_w(
        mass_primary_kg=_MASS_AEGIS_KG,
        radius_m=_RADIUS_GAIAM_M,
        semi_major_axis_m=_A_GAIAM_M,
        eccentricity=_E_GAIAM,
        mean_motion_rad_s=n,
        k2_over_q=_K2_OVER_Q,
    )
    # ~157 TW (Peale & Cassen 1978).
    assert power == pytest.approx(1.568e14, rel=0.01)


def test_tidal_heat_flux_gaiam() -> None:
    assert _gaiam_flux_w_m2() == pytest.approx(0.2685, rel=0.01)


def test_plate_speed_gaiam_reproduces_15() -> None:
    v = plate_speed_cm_yr(_gaiam_flux_w_m2(), v_ref_cm_yr=5.0, q_ref_w_m2=0.09, beta=1.0)
    # Raw ~14.9 cm/yr; the 0.5 cm/yr rounding used in resolve_tidal_heating
    # keeps the authored 15.0 unchanged.
    assert v == pytest.approx(14.92, rel=0.01)
    assert round(v * 2.0) / 2.0 == 15.0


def test_plate_speed_earth_anchor() -> None:
    # Earth's own flux (0.09) with β=1 must reproduce Earth's 5 cm/yr.
    v = plate_speed_cm_yr(0.09, v_ref_cm_yr=5.0, q_ref_w_m2=0.09, beta=1.0)
    assert v == pytest.approx(5.0)
