"""Independent pit, flat, cycle and analytic controls for the original treatment."""

import numpy as np
import pytest

from scripts.media.compare_dinf_routing import frame, plane
from scripts.media.dinf_local import Routing
from scripts.media.dinf_original import accumulate, prepare, routing, topological_order
from scripts.media.triangular_flowline import TriangularSurface, trace_triangles


def test_pit_is_raised_only_to_spill_without_epsilon() -> None:
    h = np.full((9, 9), 10.0)
    h[1:-1, 1:-1] = 2
    h[0, 4] = 5
    prepared = prepare(h, frame(h.shape))
    np.testing.assert_array_equal(prepared.height_m[1:-1, 1:-1], 5)
    np.testing.assert_array_equal(prepared.height_m[frame(h.shape)], h[frame(h.shape)])
    route = routing(prepared)
    order = topological_order(prepared.height_m, route)
    assert order.size == h.size
    source = (~prepared.absorbing).astype(float)
    acc = accumulate(prepared, route, source)
    assert acc[prepared.absorbing].sum() == source.sum()
    path = trace_triangles(TriangularSurface(prepared), (4, 4), prepared.absorbing)
    assert path.status == "absorbed"
    assert (np.diff(path.height_m) == 0).all()


def test_flats_resolve_to_existing_d8_without_changing_heights() -> None:
    h = np.zeros((19, 23))
    prepared = prepare(h, frame(h.shape))
    np.testing.assert_array_equal(prepared.height_m, h)
    route = routing(prepared)
    assert (route.proportion[~prepared.absorbing, 0] == 1).all()
    rec = route.receiver[..., 0]
    for r, c in zip(*np.nonzero(~prepared.absorbing), strict=True):
        tr, tc = divmod(rec[r, c], h.shape[1])
        assert prepared.flat_rank[tr, tc] < prepared.flat_rank[r, c]
    source = np.ones(h.shape)
    acc = accumulate(prepared, route, source)
    assert acc[prepared.absorbing].sum() == h.size


def test_declared_internal_lake_is_not_filled_to_outer_rim() -> None:
    row, col = np.indices((17, 17))
    h = (row - 8) ** 2 + (col - 8) ** 2
    stop = frame(h.shape)
    stop[8, 8] = True
    prepared = prepare(h, stop)
    np.testing.assert_array_equal(prepared.height_m, h)
    path = trace_triangles(TriangularSurface(prepared), (5, 5), stop)
    assert path.status == "absorbed"
    assert path.sink_cell == (8, 8)


def test_equal_height_cycles_are_rejected_even_with_closed_local_budgets() -> None:
    rec = np.full((2, 2, 2), -1, dtype=int)
    p = np.zeros(rec.shape)
    rec[0, 0, 0], rec[0, 1, 0] = 1, 0
    p[0, :, 0] = 1
    route = Routing(rec, p, np.zeros((2, 2)), np.zeros((2, 2)))
    with pytest.raises(ValueError, match="cycle"):
        topological_order(np.zeros((2, 2)), route)


def test_missing_height_is_closed_and_disconnected_component_is_reported() -> None:
    h = np.zeros((11, 11))
    h[:, 5] = np.nan
    stop = np.zeros(h.shape, dtype=bool)
    stop[:, 0] = True
    prepared = prepare(h, stop)
    assert prepared.reached[:, :5].all()
    assert not prepared.reached[:, 6:].any()
    assert (prepared.d8_receiver[:, 6:] == -1).all()
    assert np.isnan(prepared.height_m[:, 5]).all()
    path = trace_triangles(TriangularSurface(prepared), (5, 8), stop)
    assert path.status == "unresolved"


@pytest.mark.parametrize("angle_deg", [0.25, 22.5, 44.99, 89.5, 130.25, 179.75, 269.5, 359.75])
def test_triangle_events_preserve_analytic_plane_direction(angle_deg: float) -> None:
    h = plane((33, 33), angle_deg)
    prepared = prepare(h, frame(h.shape))
    surface = TriangularSurface(prepared)
    paths = [
        trace_triangles(surface, (16, 16), prepared.absorbing, sample_px=s) for s in (0.5, 0.25)
    ]
    for path in paths:
        assert path.status == "absorbed"
        assert (np.diff(path.height_m) < 0).all()
        dr, dc = np.diff(path.points_rc, axis=0).T
        error = np.abs(np.angle(np.exp(1j * (np.arctan2(-dr, dc) - np.radians(angle_deg)))))
        assert np.max(error) < np.radians(1e-7)
    np.testing.assert_allclose(paths[0].points_rc[-1], paths[1].points_rc[-1], atol=1e-12)


def test_piecewise_linear_surface_has_no_cubic_overshoot_and_reaches_outlet() -> None:
    row, col = np.indices((25, 33))
    h = -(col // 4) * 5 - col * 1e-4 + 0.2 * (row - 10.4) ** 2
    prepared = prepare(h, frame(h.shape))
    surface = TriangularSurface(prepared)
    for point in np.random.default_rng(483).uniform([0, 0], [24, 32], (200, 2)):
        for _, z, _, _ in surface.incident(point):
            assert z.min() - 1e-12 <= surface.height(point) <= z.max() + 1e-12
    path = trace_triangles(surface, (10.4, 4), prepared.absorbing)
    assert path.status == "absorbed"
    assert path.sink_cell is not None and path.sink_cell[1] == 32
    assert (np.diff(path.height_m) <= 1e-9).all()


def test_valley_edge_sliding_avoids_opposing_gradient_oscillations() -> None:
    row, col = np.indices((33, 33))
    h = -col + 2 * abs(row - 16)
    prepared = prepare(h, frame(h.shape))
    for r in (8, 16, 23):
        path = trace_triangles(TriangularSurface(prepared), (r, 3), prepared.absorbing)
        assert path.status == "absorbed"
        assert path.points_rc[-1, 0] == 16
        assert (np.diff(path.height_m) < 0).all()


def test_triangle_lake_first_touch_is_at_boundary() -> None:
    h = plane((17, 17), 0)
    stop = frame(h.shape)
    stop[:, 9] = True
    prepared = prepare(h, stop)
    path = trace_triangles(TriangularSurface(prepared), (8, 3), stop)
    assert path.status == "absorbed"
    assert path.sink_cell == (8, 9)
    np.testing.assert_allclose(path.points_rc[-1], [8, 8.5], atol=1e-12)


def test_triangular_circular_valley_stays_within_half_pixel() -> None:
    row, col = np.indices((129, 129))
    radius = np.hypot(col + 20, 148 - row)
    theta = np.arctan2(148 - row, col + 20)
    h = -60 * theta + 0.03 * (radius - 100) ** 2
    seed = (148 - 100 * np.sin(np.radians(20)), 100 * np.cos(np.radians(20)) - 20)
    prepared = prepare(h, frame(h.shape))
    surface = TriangularSurface(prepared)
    paths = [trace_triangles(surface, seed, prepared.absorbing, sample_px=s) for s in (0.5, 0.25)]
    for path in paths:
        assert path.status == "absorbed"
        radius = np.hypot(path.points_rc[:, 1] + 20, 148 - path.points_rc[:, 0])
        assert np.max(abs(radius - 100)) < 0.5
    np.testing.assert_array_equal(paths[0].points_rc[-1], paths[1].points_rc[-1])


def test_integer_sources_are_accumulated_as_fractional_water() -> None:
    h = plane((19, 19), 22.5)
    prepared = prepare(h, frame(h.shape))
    route = routing(prepared)
    source = np.zeros(h.shape, dtype=int)
    source[9, 9] = 1
    acc = accumulate(prepared, route, source)
    assert np.isclose(acc[prepared.absorbing].sum(), 1, atol=1e-14)
    assert ((acc > 0) & (acc < 1)).any()


def test_equal_diagonal_edge_is_not_classified_as_tiny_downhill_slope() -> None:
    h = np.full((17, 17), 124.58970642089844)
    h[5, 10] += 0.075347900390625
    prepared = prepare(h, frame(h.shape))
    surface = TriangularSurface(prepared)
    point = np.array([4.25898652908546, 10.2589865290854])
    event = surface.next_event(point)
    assert event is not None and event[1]
    path = trace_triangles(surface, tuple(point), prepared.absorbing)
    assert path.status == "absorbed"
    np.testing.assert_allclose(path.height_m, h[0, 0], atol=1e-12)
