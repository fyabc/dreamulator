"""Analytical expectations and closed water budgets for the local D-infinity pilot."""

from __future__ import annotations

import numpy as np
import pytest

from scripts.media.dinf_local import (
    accumulate,
    check_routing,
    directions,
    displacement_angle,
    tiled_directions,
)


def plane(shape: tuple[int, int], angle_deg: float) -> np.ndarray:
    row, col = np.indices(shape)
    theta = np.radians(angle_deg)
    return row * np.sin(theta) - col * np.cos(theta)


def frame(shape: tuple[int, int]) -> np.ndarray:
    stop = np.zeros(shape, dtype=bool)
    stop[[0, -1], :] = True
    stop[:, [0, -1]] = True
    return stop


def test_rotated_planes_have_analytical_continuous_direction() -> None:
    for angle in np.arange(0.25, 360, 2.5):
        h = plane((17, 19), angle)
        route = directions(h, 1)
        delta = np.angle(np.exp(1j * (route.angle_rad[1:-1, 1:-1] - np.radians(angle))))
        assert np.max(np.abs(delta)) < np.radians(1e-7)
        np.testing.assert_allclose(route.slope[1:-1, 1:-1], 1, atol=1e-13)
        check_routing(h, route)


def test_landlab_published_plane_has_known_receivers_and_proportions() -> None:
    # Landlab's documented z=2*x+y example, with our rows running south.
    row, col = np.indices((3, 3))
    route = directions(2 * col - row, 1)
    assert list(route.receiver[1, 1]) == [3, 6]  # west and southwest
    np.testing.assert_allclose(route.proportion[1, 1], [0.4096655293982669, 0.590334470601733])
    assert route.slope[1, 1] == pytest.approx(np.sqrt(5))


def test_d8_baseline_matches_existing_reference_receivers() -> None:
    from dreamulator.media.canvas_hydrology import CanvasTiles, ChunkGrid, flow_directions

    h = 100 + np.random.default_rng(744).normal(size=(17, 17))
    tiles = CanvasTiles(raw={(0, 0): h}, grid=ChunkGrid(1, 1, 17), filled={(0, 0): h})
    existing = flow_directions(tiles)[0, 0]
    local = directions(h, 7, method="d8")
    np.testing.assert_array_equal(existing, local.receiver[..., 0])


def test_lake_cascade_has_independent_source_loss_and_outlet_expectations() -> None:
    from scripts.media.compare_dinf_routing import lake_control

    result = lake_control()
    assert result["first_touch_inflow"] == pytest.approx([100, 20])
    assert result["first_lake_release"] == pytest.approx(97)
    assert result["second_lake_total_inflow"] == pytest.approx(117)
    assert result["final_outlet"] == pytest.approx(110)
    assert result["monthly_outlet_sum"] == pytest.approx(110)


def test_half_facet_splits_water_but_displacement_remains_biased() -> None:
    h = plane((9, 9), 22.5)
    route = directions(h, 1)
    np.testing.assert_allclose(route.proportion[4, 4], [0.5, 0.5])
    assert np.degrees(displacement_angle(route)[4, 4]) == pytest.approx(np.degrees(np.arctan(0.5)))
    assert np.degrees(route.angle_rad[4, 4]) == pytest.approx(22.5)


def test_two_receivers_cross_tile_seam_without_losing_water() -> None:
    h = plane((9, 9), 22.5)
    stop = frame(h.shape)
    tiled = tiled_directions(h, 1, stop, 4)
    np.testing.assert_array_equal(tiled.receiver[4, 3], [40, 31])
    np.testing.assert_allclose(tiled.proportion[4, 3], [0.5, 0.5])
    source = np.zeros_like(h)
    source[4, 3] = 8
    total = accumulate(h, tiled, source)
    assert total[4, 4] == pytest.approx(4)
    assert total[3, 4] == pytest.approx(4)
    assert total[stop].sum() == pytest.approx(8)


@pytest.mark.parametrize("tile", [1, 3, 8, 30])
def test_real_halo_matches_whole_on_irregular_surface(tile: int) -> None:
    h = np.random.default_rng(723).normal(size=(23, 29))
    stop = frame(h.shape)
    whole = directions(h, 7, stop)
    tiled = tiled_directions(h, 7, stop, tile)
    np.testing.assert_array_equal(whole.receiver, tiled.receiver)
    np.testing.assert_array_equal(whole.proportion, tiled.proportion)
    np.testing.assert_array_equal(whole.angle_rad, tiled.angle_rad)


def test_absorbing_lake_gets_first_touch_inflow_exactly_once() -> None:
    h = plane((9, 13), 22.5)
    stop = frame(h.shape)
    lake = np.zeros_like(stop)
    lake[:, 5] = True
    route = directions(h, 1, stop | lake)
    source = np.zeros_like(h)
    source[6, 2] = 10
    source[5, 7] = 4
    total = accumulate(h, route, source)
    assert total[lake].sum() == pytest.approx(10)
    assert total[stop & ~lake].sum() == pytest.approx(4)
    assert (route.receiver[lake] == -1).all()


def test_missing_vertices_are_closed_and_single_valid_link_still_drains() -> None:
    h = np.full((3, 3), np.nan)
    h[1, 1], h[1, 2] = 5, 2
    route = directions(h, 1)
    np.testing.assert_array_equal(route.receiver[1, 1], [5, -1])
    check_routing(h, route)
    source = np.zeros_like(h)
    source[1, 1] = 7
    assert accumulate(h, route, source)[1, 2] == 7


def test_closed_flat_keeps_local_water_and_d8_has_one_receiver() -> None:
    h = np.ones((5, 5))
    route = directions(h, 1)
    assert (route.receiver == -1).all()
    np.testing.assert_array_equal(accumulate(h, route, h), h)
    d8 = directions(plane((5, 5), 17), 1, method="d8")
    assert (d8.proportion[..., 1] == 0).all()
    assert np.degrees(d8.angle_rad[2, 2]) == 0


def test_invalid_geometry_and_nonconservative_inputs_fail() -> None:
    h = plane((5, 5), 22.5)
    for spacing in (0, -1, np.nan):
        with pytest.raises(ValueError, match="spacing"):
            directions(h, spacing)
    with pytest.raises(ValueError, match="mask shape"):
        directions(h, 1, np.zeros((2, 2), dtype=bool))
    route = directions(h, 1)
    route.proportion[2, 2, :] = [0.3, 0.3]
    with pytest.raises(ValueError, match="sum to one"):
        accumulate(h, route, np.ones_like(h))
    route = directions(h, 1)
    route.receiver[2, 2, 0] = 12
    with pytest.raises(ValueError, match="strictly descend"):
        check_routing(h, route)
