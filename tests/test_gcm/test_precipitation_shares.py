"""Native quotas, unresolved states, dry children and resolution consistency."""

from __future__ import annotations

import numpy as np
import pytest

from dreamulator.gcm.precipitation_shares import ComponentDriver, monthly_component_shares


def close(baseline, area, driver):
    baseline, area = np.asarray(baseline, dtype=float), np.asarray(area, dtype=float)
    return monthly_component_shares(
        baseline,
        area,
        parent_area_m2=float(area.sum()),
        parent_budget_mm_m2=float(area @ baseline),
        driver=driver,
    )


def driver(base, adjusted, unresolved=None):
    base = np.asarray(base, dtype=float)
    return ComponentDriver(
        base,
        np.asarray(adjusted, dtype=float),
        np.zeros_like(base) if unresolved is None else np.asarray(unresolved, dtype=float),
    )


def test_dry_and_weak_children_receive_finite_water_without_local_division():
    baseline, area = np.array([0.0, 1e-20, 100.0]), np.array([1.0, 2.0, 7.0])
    result = close(baseline, area, driver([0.0, 1e-20, 10], [20, 4, 1]))
    assert np.isfinite(result.depth_mm).all() and (result.depth_mm >= 0).all()
    assert result.depth_mm[0] > 0
    np.testing.assert_allclose(area @ result.depth_mm, area @ baseline, rtol=1e-14)


def test_negative_share_projection_obeys_weighted_optimality_conditions():
    area, baseline = np.array([1.0, 2.0, 7.0]), np.array([1.0, 1.0, 1.0])
    base, changed = np.array([10.0, 0.0, 0.0]), np.array([0.0, 0.0, 10.0])
    result = close(baseline, area, driver(base, changed))
    assert result.negative_candidate_mass_fraction > 0 and result.depth_mm[0] == 0
    weights = area / area.sum()
    proposed = baseline + changed / (weights @ changed) - base / (weights @ base)
    positive = result.depth_mm > 0
    offsets = proposed[positive] - result.depth_mm[positive]
    np.testing.assert_allclose(offsets, offsets[0], atol=1e-13)
    assert (proposed[~positive] <= offsets[0] + 1e-13).all()
    np.testing.assert_allclose(weights @ result.depth_mm, 1, atol=1e-14)


def test_splitting_a_constant_child_preserves_the_intensive_solution():
    area, baseline = np.array([1.0, 2.0, 7.0]), np.array([1.0, 3.0, 2.0])
    original = close(baseline, area, driver([10, 1, 2], [0, 20, 1], [2, 4, 1]))
    index = np.array([0, 1, 1, 2, 2, 2])
    pieces = np.array([1.0, 0.5, 1.5, 1.0, 2.0, 4.0])
    refined = close(
        baseline[index],
        pieces,
        driver(
            np.array([10, 1, 2])[index], np.array([0, 20, 1])[index], np.array([2, 4, 1])[index]
        ),
    )
    np.testing.assert_allclose(refined.depth_mm, original.depth_mm[index], rtol=1e-14)


def test_unresolved_quota_retains_its_long_term_spatial_allocation():
    area, baseline = np.array([1.0, 2.0, 3.0]), np.array([2.0, 4.0, 8.0])
    supported = np.array([1.0, 2.0, 3.0])
    adjusted = np.array([8.0, 1.0, 0.0])
    all_supported = close(baseline, area, driver(supported, adjusted))
    partial = close(baseline, area, driver(supported, adjusted, 3 * supported))
    assert partial.supported_quota_fraction == 0.25
    np.testing.assert_allclose(partial.depth_mm, 0.75 * baseline + 0.25 * all_supported.depth_mm)


@pytest.mark.parametrize("kind", ["missing", "zero_response", "unsupported", "zero_adjusted"])
def test_fallbacks_preserve_baseline_values_exactly(kind):
    baseline, area = np.array([0.0, 1e-20, 100.0]), np.array([1.0, 2.0, 7.0])
    choices = {
        "missing": None,
        "zero_response": driver([1, 2, 3], [1, 2, 3]),
        "unsupported": driver([0, 0, 0], [1, 2, 3], [1, 2, 3]),
        "zero_adjusted": driver([1, 2, 3], [0, 0, 0]),
    }
    np.testing.assert_array_equal(close(baseline, area, choices[kind]).depth_mm, baseline)


def test_components_and_months_close_separately_including_ocean_area():
    area = np.array([1.0, 9.0])  # The second child represents ocean area.
    for month in range(1, 13):
        stratiform = np.array([month, 2.0 * month])
        convection = np.array([3.0 * month, month])
        result = close(stratiform, area, driver([1, 3], [5, 1]))
        np.testing.assert_allclose(area @ result.depth_mm, area @ stratiform, rtol=1e-14)
        np.testing.assert_allclose(
            area @ (result.depth_mm + convection), area @ (stratiform + convection), rtol=1e-14
        )


def test_zero_parent_has_zero_output_even_when_high_frequency_rain_is_positive():
    np.testing.assert_array_equal(close([0, 0], [1, 9], driver([1, 3], [5, 1])).depth_mm, [0, 0])
