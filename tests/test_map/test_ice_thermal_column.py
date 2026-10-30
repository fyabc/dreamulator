"""Analytical thermal limits and the basal heat budget."""

import numpy as np

from dreamulator.map.canvas_ice_surface import SECONDS_PER_YEAR
from dreamulator.map.ice_sheets import RHO_ICE_KG_M3
from dreamulator.map.ice_thermal_column import (
    ICE_CONDUCTIVITY_W_M_K,
    ICE_LATENT_HEAT_J_KG,
    steady_ice_column,
)


def test_conductive_limit_and_downward_transport_of_cold_ice():
    result = steady_ice_column(
        np.array([-30.0, -30.0]),
        np.array([1000.0, 1000.0]),
        np.array([0.0, 0.5]),
        np.array([0.03, 0.03]),
        gravity_m_s2=9.81,
    )
    np.testing.assert_allclose(
        result.basal_temperature_c[0], -30 + 0.03 * 1000 / ICE_CONDUCTIVITY_W_M_K
    )
    assert result.basal_temperature_c[1] < result.basal_temperature_c[0]
    np.testing.assert_array_equal(result.basal_melt_potential_m_yr, 0)


def test_pressure_melting_and_latent_heat_close_the_basal_budget():
    heat = np.array([0.0, 0.3, 0.3])
    result = steady_ice_column(
        np.full(3, -20.0),
        np.array([2000.0, 2000.0, 0.0]),
        np.full(3, 0.2),
        heat,
        gravity_m_s2=10.28,
    )
    assert result.basal_temperature_c[0] == -20
    assert result.basal_temperature_c[1] == result.pressure_melting_temperature_c[1]
    assert result.basal_melt_potential_m_yr[1] > 0
    assert result.basal_melt_potential_m_yr[2] == 0
    budget = (
        result.conductive_flux_w_m2
        + result.basal_melt_potential_m_yr * RHO_ICE_KG_M3 * ICE_LATENT_HEAT_J_KG / SECONDS_PER_YEAR
    )
    np.testing.assert_allclose(budget[:2], heat[:2], atol=1e-14)
