"""Physical invariants for the local shallow-ice surface trial."""

import numpy as np
import pytest

from dreamulator.map.canvas_ice_surface import (
    redistribute_ice,
    source_ice_bed,
    subgrid_ice_relaxation_fraction,
    subgrid_ice_surface_level,
)


def test_ice_bed_uses_native_mean_and_relief_instead_of_td_amplitude():
    rng = np.random.default_rng(18)
    td = 2500 + rng.normal(0, 1000, (96, 96))
    condition = np.full(td.shape, 2500.0)
    ice = np.full(td.shape, 2200.0)
    ice[:, :8] = 0
    result = source_ice_bed(
        td,
        condition,
        ice,
        np.full(td.shape, 40.0),
        spacing_m=1000,
        source_spacing_m=50_000,
    )
    np.testing.assert_array_equal(result[:, :8], td[:, :8])
    assert result[:, 8:].mean() == pytest.approx(300, abs=1e-10)
    assert result[:, 8:].std() == pytest.approx(40, rel=0.06)


def test_native_ice_fraction_connects_bed_sources_continuously():
    td = np.full((6, 9), 2800.0)
    condition = np.full(td.shape, 2500.0)
    ice = np.full(td.shape, 100.0)
    fraction = np.broadcast_to(np.linspace(0, 1, 9), td.shape)
    bed = source_ice_bed(
        td,
        condition,
        ice,
        np.zeros(td.shape),
        spacing_m=1000,
        source_spacing_m=50_000,
        ice_fraction=fraction,
    )
    surface = bed + ice
    assert np.max(np.abs(np.diff(surface, axis=1))) == pytest.approx(37.5)
    np.testing.assert_array_equal(surface[:, 0], td[:, 0])
    np.testing.assert_array_equal(surface[:, -1], condition[:, -1])


def test_ice_flows_into_dry_valley_without_clipping_or_volume_loss():
    bed = np.zeros((9, 11))
    ice = np.zeros_like(bed)
    ice[3:6, 3:6] = 800.0
    land = np.ones_like(bed, dtype=bool)
    land[:, -1] = False
    result, budget = redistribute_ice(
        bed, ice, land, spacing_m=500.0, elapsed_yr=0.1, gravity_m_s2=9.81
    )
    assert result.min() >= 0
    assert result.max() < ice.max()
    assert result[4, 6] > 0
    np.testing.assert_array_equal(result[:, -1], 0)
    assert budget.final_volume_m3 == pytest.approx(budget.initial_volume_m3, rel=1e-12)
    assert np.sum(result**2) < np.sum(ice**2)


def test_flat_ice_surface_over_rough_bed_is_stationary():
    y, x = np.indices((8, 10))
    bed = 400 * np.sin(x) * np.cos(y)
    ice = 900.0 - bed
    result, budget = redistribute_ice(
        bed,
        ice,
        np.ones_like(bed, dtype=bool),
        spacing_m=1000.0,
        elapsed_yr=100,
        gravity_m_s2=10.28,
    )
    np.testing.assert_array_equal(result, ice)
    assert budget.residual_m3 == 0


def test_bare_rock_has_no_mobile_ice():
    bed = np.arange(35, dtype=float).reshape(5, 7) * 100
    result, budget = redistribute_ice(
        bed,
        np.zeros_like(bed),
        np.ones_like(bed, dtype=bool),
        spacing_m=500,
        elapsed_yr=100,
        gravity_m_s2=9.81,
    )
    np.testing.assert_array_equal(result, 0)
    assert budget.initial_volume_m3 == budget.final_volume_m3 == 0


def test_subgrid_level_preserves_volume_and_exposes_peaks_in_thin_ice():
    bed = np.array([[0.0, 30.0, 100.0, 400.0]] * 3)
    ice = np.array([0.0, 20.0, 500.0])
    level = subgrid_ice_surface_level(bed, ice)
    thickness = np.maximum(level[:, None] - bed, 0)
    np.testing.assert_allclose(thickness.mean(axis=-1), ice)
    assert np.count_nonzero(thickness[1]) == 2
    assert np.all(thickness[2] > 0)
    response = subgrid_ice_relaxation_fraction(
        np.array([50.0, 2000.0]),
        np.array([200.0, 200.0]),
        spacing_m=5750,
        elapsed_yr=10,
        gravity_m_s2=10.28,
    )
    assert response[0] < 0.001
    assert response[1] > 0.99


def test_partial_cells_use_support_thickness_and_conserve_volume():
    bed = np.zeros((6, 6))
    land = np.ones(bed.shape, bool)
    fraction = np.ones(bed.shape)
    fraction[:, 3:] = 0.5
    # Equal surfaces on support: half-area cells hold half the cell-mean volume.
    still, _ = redistribute_ice(
        bed,
        np.where(fraction < 1, 400.0, 800.0),
        land,
        spacing_m=5750,
        elapsed_yr=10,
        gravity_m_s2=10.28,
        support_fraction=fraction,
    )
    np.testing.assert_allclose(still, np.where(fraction < 1, 400.0, 800.0), atol=1e-6)
    stepped = np.where(fraction < 1, 100.0, 800.0)
    result, budget = redistribute_ice(
        bed,
        stepped,
        land,
        spacing_m=5750,
        elapsed_yr=50,
        gravity_m_s2=10.28,
        support_fraction=fraction,
    )
    assert abs(budget.residual_m3) < 1e-6 * budget.initial_volume_m3
    assert result[:, 3:].mean() > 100
    full, _ = redistribute_ice(
        bed, stepped, land, spacing_m=5750, elapsed_yr=50, gravity_m_s2=10.28
    )
    same, _ = redistribute_ice(
        bed,
        stepped,
        land,
        spacing_m=5750,
        elapsed_yr=50,
        gravity_m_s2=10.28,
        support_fraction=np.ones(bed.shape),
    )
    np.testing.assert_array_equal(full, same)
