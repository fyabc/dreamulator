"""Snow/ice budgets and the effect of submonthly warm excursions."""

import numpy as np
import pytest

from dreamulator.map.ice_mass_balance import (
    annual_ice_balance,
    annual_snow_storage_and_ice_melt,
    fixed_climate_ice_minimum,
    monthly_snow_and_pdd,
)


def test_cold_dry_and_cold_wet_climates_have_distinct_accumulation():
    t = np.full((12, 2), -20.0)
    p = np.broadcast_to([0.0, 50.0], t.shape)
    snow, pdd = monthly_snow_and_pdd(t, p, np.zeros_like(t))
    result = annual_ice_balance(np.zeros(2), snow, pdd)
    np.testing.assert_allclose(result.ice_equivalent_m, [0, 600 / 917])
    np.testing.assert_array_equal(result.residual_mm, 0)


def test_warm_excursions_melt_snow_despite_negative_monthly_mean():
    t = np.full((12, 1), -1.0)
    p = np.full_like(t, 10.0)
    snow, pdd = monthly_snow_and_pdd(t, p, np.full_like(t, 3.0))
    assert np.all((snow > 0) & (snow < p))
    assert np.all(pdd > 0)
    result = annual_ice_balance(np.array([0.1]), snow, pdd)
    assert result.ice_equivalent_m[0] == 0
    assert result.ice_melt_mm[0] == pytest.approx(91.7)
    np.testing.assert_allclose(result.residual_mm, 0, atol=1e-12)


def test_seasonal_snow_melts_before_ice_and_closes_water_budget():
    snow, pdd = np.zeros((12, 1)), np.zeros((12, 1))
    snow[0] = 30
    pdd[0] = 12
    result = annual_ice_balance(np.array([1.0]), snow, pdd)
    assert result.snow_melt_mm[0] == 30
    assert result.ice_melt_mm[0] == 16
    assert result.ice_equivalent_m[0] == pytest.approx(1 - 16 / 917)
    np.testing.assert_allclose(result.residual_mm, 0, atol=1e-12)


def test_fixed_climate_response_matches_monthly_repetition_through_depletion():
    t = np.broadcast_to(np.linspace(-18, 4, 12)[:, None], (12, 3))
    p = np.broadcast_to([30.0, 150.0, 450.0], t.shape)
    snow, pdd = monthly_snow_and_pdd(t, p, np.full_like(t, 2.0))
    retained, melt = annual_snow_storage_and_ice_melt(snow, pdd)
    initial = np.array([8.0, 0.1, 0.0])
    final = initial.copy()
    for _ in range(100):
        final = annual_ice_balance(final, snow, pdd).ice_equivalent_m
    np.testing.assert_allclose(
        fixed_climate_ice_minimum(initial, retained, melt, 100), final - retained, atol=1e-12
    )
