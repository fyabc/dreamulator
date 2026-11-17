"""Geometry constraints independent of the existing water-routing algorithms."""

import numpy as np
import pytest

from scripts.media.bounded_river_lines import smooth_line
from scripts.media.compare_bounded_river_lines import preserves_first_water_touch


@pytest.mark.parametrize("angle", [0.25, 22.5, 89.75, 179.5])
def test_straight_line_retains_direction_and_endpoints(angle: float) -> None:
    direction = np.array([np.cos(np.radians(angle)), np.sin(np.radians(angle))])
    points = np.arange(0, 17, 0.25)[:, None] * direction
    result = smooth_line(points, sample_spacing=2)
    np.testing.assert_array_equal(result.points[[0, -1]], points[[0, -1]])
    vector = np.diff(result.points, axis=0)
    delta = abs(np.angle(np.exp(1j * (np.arctan2(vector[:, 1], vector[:, 0]) - np.radians(angle)))))
    assert delta.max() < np.radians(1e-7)


def test_continuous_correspondence_stays_within_bound_between_output_vertices() -> None:
    points = np.array([[0, 0], [0, 5], [5, 5], [5, 10], [10, 10]], dtype=float)
    result = smooth_line(points, sample_spacing=2, maximum_offset=0.5)
    station = np.r_[0, np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))]
    query = np.linspace(0, station[-1], 3001)
    actual = np.column_stack(
        [np.interp(query, result.source_station, result.points[:, k]) for k in (0, 1)]
    )
    reference = np.column_stack([np.interp(query, station, points[:, k]) for k in (0, 1)])
    assert np.linalg.norm(actual - reference, axis=1).max() <= 0.5 + 1e-12
    assert (np.diff(result.source_station) > 0).all()


def test_junction_remains_fixed_and_shared_downstream_reach_is_identical() -> None:
    downstream = np.array([[0, 0], [2, 0], [2, 3], [5, 3]], dtype=float)
    a = np.vstack(([-3, 0], downstream))
    b = np.vstack(([0, -4], downstream))
    sa = smooth_line(a, sample_spacing=1, anchors=(1,))
    sb = smooth_line(b, sample_spacing=1, anchors=(1,))
    ia = np.flatnonzero((sa.points == [0, 0]).all(axis=1))[0]
    ib = np.flatnonzero((sb.points == [0, 0]).all(axis=1))[0]
    np.testing.assert_array_equal(sa.points[ia:], sb.points[ib:])


def test_zero_offset_retains_entire_original_piecewise_linear_curve() -> None:
    points = np.array([[0, 0], [0, 4], [3, 4], [3, 7]], dtype=float)
    result = smooth_line(points, sample_spacing=2, maximum_offset=0)
    assert result.maximum_offset == 0
    np.testing.assert_array_equal(result.points, result.reference)


def test_circle_smoothing_stays_within_half_pixel_of_known_centerline() -> None:
    theta = np.linspace(0, np.pi / 2, 101)
    points = 100 * np.column_stack((np.cos(theta), np.sin(theta)))
    result = smooth_line(points, sample_spacing=2)
    assert abs(np.linalg.norm(result.points, axis=1) - 100).max() < 0.5


def test_duplicate_points_and_singleton_do_not_create_empty_or_nonfinite_lines() -> None:
    points = np.array([[1, 2], [1, 2], [3, 4], [3, 4]], dtype=float)
    result = smooth_line(points, sample_spacing=1)
    assert np.isfinite(result.points).all()
    np.testing.assert_array_equal(result.points[[0, -1]], points[[0, -1]])
    result = smooth_line(np.array([[1, 2]]), sample_spacing=1)
    np.testing.assert_array_equal(result.points, [[1, 2]])


def test_bad_coordinates_and_bounds_are_rejected() -> None:
    for points in (np.array([1, 2]), np.array([[1, np.nan]]), np.empty((0, 2))):
        with pytest.raises(ValueError, match="points"):
            smooth_line(points, sample_spacing=1)
    with pytest.raises(ValueError, match="sample"):
        smooth_line(np.ones((3, 2)), sample_spacing=0)
    with pytest.raises(ValueError, match="offset"):
        smooth_line(np.ones((3, 2)), sample_spacing=1, maximum_offset=-1)
    with pytest.raises(ValueError, match="anchor"):
        smooth_line(np.ones((3, 2)), sample_spacing=1, anchors=(4,))


def test_water_entry_at_either_side_of_pixel_boundary_is_valid() -> None:
    stop = np.zeros((9, 9), dtype=bool)
    stop[:, 4] = True
    assert preserves_first_water_touch(np.array([[1, 4], [3.5, 4]]), stop)
    assert preserves_first_water_touch(np.array([[7, 4], [4.5, 4]]), stop)
    assert not preserves_first_water_touch(np.array([[1, 4], [3.4, 4]]), stop)


def test_line_entering_water_before_its_endpoint_is_rejected() -> None:
    stop = np.zeros((9, 9), dtype=bool)
    stop[:, 4] = True
    stop[:, 7] = True
    assert not preserves_first_water_touch(np.array([[1, 4], [6.5, 4]]), stop)
