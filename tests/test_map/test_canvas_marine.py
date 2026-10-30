"""Connected sea, channel width and floatation for canvas ice."""

import numpy as np
import pytest

from dreamulator.map.canvas_ice_surface import subgrid_ice_relaxation_fraction
from dreamulator.map.canvas_marine import (
    FLOATATION_RATIO,
    channel_fill_fraction,
    connect_sea,
    grounded_ice,
    water_width_px,
)


def test_floatation_needs_column_heavier_than_displaced_water():
    bed = np.array([-100.0, -100.0, -100.0, 5.0])
    ice = np.array([100.0, FLOATATION_RATIO * 100 - 1, FLOATATION_RATIO * 100, 0.0])
    np.testing.assert_array_equal(grounded_ice(ice, bed), [False, False, True, True])
    assert pytest.approx(1028 / 917) == FLOATATION_RATIO
    with pytest.raises(ValueError):
        grounded_ice(np.array([-1.0]), np.array([0.0]))


def test_water_width_measures_channels_and_caps_open_water():
    water = np.zeros((40, 60), bool)
    water[5, 2:30] = True  # one pixel wide
    water[10:13, 2:30] = True  # three pixels wide
    water[20:40, 35:60] = True  # open water touching the frame edge
    width = water_width_px(water, max_radius_px=4)
    assert np.all(width[5, 3:29] == 1)
    assert np.all(width[10:13, 4:28] == 3)
    assert np.isinf(width[30, 47])
    assert np.all(width[~water] == 0)


def test_channel_fill_matches_subgrid_relaxation_at_channel_wavenumber():
    ice, depth, width = np.array([800.0]), np.array([900.0]), 1500.0
    expected = subgrid_ice_relaxation_fraction(
        ice, depth / np.sqrt(8), spacing_m=width, elapsed_yr=10, gravity_m_s2=10.28
    )
    result = channel_fill_fraction(ice, depth, np.array([width]), elapsed_yr=10, gravity_m_s2=10.28)
    np.testing.assert_allclose(result, expected)
    wide = channel_fill_fraction(
        np.array([3000.0, 3000.0]),
        np.array([3000.0, 3000.0]),
        np.array([500.0, np.inf]),
        elapsed_yr=10,
        gravity_m_s2=10.28,
    )
    assert wide[0] > 0.999
    assert wide[1] == 0


def test_sea_connects_across_chunks_but_not_through_diagonal_corners():
    # Two 6x6 chunks side by side. A channel from the seeded left chunk crosses
    # the shared edge; an inland pit touches the channel only diagonally.
    left = np.zeros((6, 6), bool)
    right = np.zeros((6, 6), bool)
    left[2, :] = True
    right[2, :3] = True
    right[3, 3] = True  # diagonal to (2, 2): separate under 4-connectivity
    right[0, 5] = True  # isolated
    seeds = {(0, 0): np.zeros((6, 6), bool), (0, 1): np.zeros((6, 6), bool)}
    seeds[(0, 0)][2, 0] = True
    water = {(0, 0): left, (0, 1): right}
    sea = connect_sea(water, lambda key: (water[key], seeds[key]), workers=2)
    np.testing.assert_array_equal(sea.mask((0, 0), left), left)
    expected = np.zeros((6, 6), bool)
    expected[2, :3] = True
    np.testing.assert_array_equal(sea.mask((0, 1), right), expected)


def test_sea_connects_vertically_and_ignores_missing_neighbours():
    top = np.zeros((4, 4), bool)
    bottom = np.zeros((4, 4), bool)
    top[:, 1] = True
    bottom[:, 1] = True
    bottom[3, 3] = True
    water = {(0, 0): top, (1, 0): bottom, (5, 5): np.ones((4, 4), bool)}
    seeds = {k: np.zeros((4, 4), bool) for k in water}
    seeds[(1, 0)][3, 1] = True
    sea = connect_sea(water, lambda key: (water[key], seeds[key]), workers=3)
    assert sea.mask((0, 0), top)[:, 1].all()
    assert not sea.mask((1, 0), bottom)[3, 3]
    assert not sea.mask((5, 5), water[(5, 5)]).any()
