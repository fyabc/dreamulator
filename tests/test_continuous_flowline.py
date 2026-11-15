"""Independent analytical trajectories, export orientation, and first-hit semantics."""

from __future__ import annotations

import numpy as np
import pytest

from scripts.media.continuous_flowline import CubicSurface, export_segments, first_absorber, trace


def frame(shape: tuple[int, int]) -> np.ndarray:
    stop = np.zeros(shape, dtype=bool)
    stop[[0, -1], :] = True
    stop[:, [0, -1]] = True
    return stop


def test_precomputed_derivatives_equal_direct_spline_derivatives() -> None:
    surface = CubicSurface(np.random.default_rng(408).normal(size=(19, 23)))
    for point in np.random.default_rng(765).uniform([2, 2], [16, 20], size=(12, 2)):
        expected = [surface.spline.ev(*point, dx=1).item(), surface.spline.ev(*point, dy=1).item()]
        np.testing.assert_allclose(surface.gradient(point), expected, atol=1e-13, rtol=0)


@pytest.mark.parametrize("angle_deg", [0.25, 22.5, 44.99, 89.5, 130.25, 179.75, 269.5, 359.75])
def test_exported_line_follows_analytical_plane(angle_deg: float) -> None:
    row, col = np.indices((33, 33))
    angle = np.radians(angle_deg)
    h = row * np.sin(angle) - col * np.cos(angle)
    path = trace(CubicSurface(h), (16.0, 16.0), frame(h.shape))
    assert path.status == "absorbed"
    assert (np.diff(path.height_m) < 0).all()
    vectors = np.diff(export_segments(path, h.shape, 0.1), axis=1)[:, 0]
    actual = np.arctan2(vectors[:, 1], vectors[:, 0])
    error = np.abs(np.angle(np.exp(1j * (actual - angle))))
    assert np.max(error) < np.radians(1e-7)


def test_circular_valley_tracks_known_radius_and_step_halving_converges() -> None:
    row, col = np.indices((129, 129))
    x, y = col + 20, 128 - row + 20
    radius, theta = np.hypot(x, y), np.arctan2(y, x)
    h = -60 * theta + 0.03 * (radius - 100) ** 2
    surface = CubicSurface(h)
    seed = (128 - (100 * np.sin(np.radians(20)) - 20), 100 * np.cos(np.radians(20)) - 20)
    stop = frame(h.shape)
    coarse = trace(surface, seed, stop, step_px=0.5)
    fine = trace(surface, seed, stop, step_px=0.25)
    for path in (coarse, fine):
        assert path.status == "absorbed"
        r = np.hypot(path.points_rc[:, 1] + 20, 128 - path.points_rc[:, 0] + 20)
        assert np.max(abs(r - 100)) < 0.5
    assert np.linalg.norm(coarse.points_rc[-1] - fine.points_rc[-1]) < 0.01


def test_straight_valley_attracts_offset_paths() -> None:
    row, col = np.indices((65, 65))
    h = -col + 0.1 * (row - 31.4) ** 2
    surface = CubicSurface(h)
    for start in (20, 31.4, 44):
        path = trace(surface, (start, 5), frame(h.shape))
        assert path.status == "absorbed"
        assert abs(path.points_rc[-1, 0] - 31.4) < 0.02


def test_first_touch_stops_at_lake_edge_without_snapping_to_center() -> None:
    row, col = np.indices((17, 17))
    stop = frame(row.shape)
    stop[:, 9] = True
    path = trace(CubicSurface(-col.astype(float)), (8, 3), stop)
    assert path.status == "absorbed"
    assert path.sink_cell == (8, 9)
    np.testing.assert_allclose(path.points_rc[-1], [8, 8.5], atol=1e-12)


def test_segment_hits_a_thin_barrier_even_when_both_endpoints_are_outside() -> None:
    stop = np.zeros((9, 9), dtype=bool)
    stop[:, 4] = True
    hit = first_absorber(np.array([4.0, 2.0]), np.array([4.0, 6.0]), stop)
    assert hit is not None
    point, cell = hit
    np.testing.assert_array_equal(point, [4, 3.5])
    assert cell == (4, 4)


def test_missing_stencil_and_closed_minimum_have_explicit_stops() -> None:
    row, col = np.indices((17, 17))
    h = -col.astype(float)
    h[:, 9] = np.nan
    path = trace(CubicSurface(h), (8, 3), frame(h.shape), max_steps=300)
    assert path.status in {"missing_support", "stagnated"}
    assert path.points_rc[:, 1].max() < 8
    h = (row - 8) ** 2 + (col - 8) ** 2
    path = trace(CubicSurface(h), (8, 8), frame(h.shape))
    assert path.status == "critical_point"
    assert len(path.points_rc) == 1


def test_invalid_geometry_and_unresolved_step_limit_are_not_success() -> None:
    row, col = np.indices((17, 17))
    surface = CubicSurface(-col.astype(float))
    stop = frame(row.shape)
    with pytest.raises(ValueError, match="seed"):
        trace(surface, (-1, 4), stop)
    with pytest.raises(ValueError, match="step_px"):
        trace(surface, (8, 8), stop, step_px=2)
    path = trace(surface, (8, 8), stop, max_steps=1)
    assert path.status == "step_limit"


def test_ordinary_cubic_surface_can_close_a_strictly_descending_nodal_valley() -> None:
    row, col = np.indices((25, 33))
    h = -(col // 4) * 5 - col * 1e-4 + 0.2 * (row - 10.4) ** 2
    # Every nodal row descends strictly eastward, all the way to the boundary.
    assert (np.diff(h, axis=1) < 0).all()
    path = trace(CubicSurface(h), (10.4, 4), frame(h.shape))
    assert path.status == "stagnated"
    assert path.points_rc[-1, 1] < 6
    assert path.height_m[-1] < h[10, 4]
