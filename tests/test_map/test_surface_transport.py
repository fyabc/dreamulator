"""Physical diffusion scales, sea datum and material-volume budget."""

import numpy as np
import pytest

from dreamulator.map.surface_transport import hillslope_transport


def test_closed_transport_preserves_volume_and_range_at_large_time_step() -> None:
    h = np.random.default_rng(9).uniform(0, 1000, (20, 24))
    result, budget = hillslope_transport(
        h,
        np.ones(h.shape, bool),
        spacing_m=100,
        diffusivity_m2_yr=1,
        elapsed_yr=1e5,
    )
    assert result.min() >= h.min() and result.max() <= h.max()
    assert budget.substeps == 40 and budget.exported_volume_m3 == 0
    assert budget.final_land_volume_m3 == pytest.approx(budget.initial_land_volume_m3, rel=1e-13)


def test_sea_is_fixed_and_boundary_export_accounts_for_land_loss() -> None:
    h = np.full((10, 10), 100.0)
    land = np.ones(h.shape, bool)
    land[:, 0] = False
    h[:, 0] = -4000
    result, budget = hillslope_transport(
        h,
        land,
        spacing_m=100,
        diffusivity_m2_yr=1,
        elapsed_yr=1000,
    )
    np.testing.assert_array_equal(result[~land], h[~land])
    assert result[land].min() >= 0 and budget.exported_volume_m3 > 0
    assert budget.initial_land_volume_m3 - budget.final_land_volume_m3 == pytest.approx(
        budget.exported_volume_m3
    )
    shifted, _ = hillslope_transport(
        h + 700,
        land,
        spacing_m=100,
        diffusivity_m2_yr=1,
        elapsed_yr=1000,
        sea_level_m=700,
    )
    np.testing.assert_allclose(shifted - 700, result, rtol=0, atol=1e-12)


def test_impulse_spread_matches_physical_diffusion_second_moment() -> None:
    for dx in (250.0, 500.0):
        h = np.zeros((21, 21))
        h[10, 10] = 1
        result, _ = hillslope_transport(
            h,
            np.ones(h.shape, bool),
            spacing_m=dx,
            diffusivity_m2_yr=1,
            elapsed_yr=1000,
        )
        y, x = np.indices(h.shape) - 10
        second = float(np.sum(result * (x * x + y * y) * dx**2) / result.sum())
        assert second == pytest.approx(4 * 1000, rel=1e-13)
