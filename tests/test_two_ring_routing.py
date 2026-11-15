"""Production contracts for zero-epsilon drainage and exact river geometry."""

import numpy as np

from dreamulator.map.prog_erosion import (
    flow_accumulation,
    priority_flood,
    river_segments,
)
from dreamulator.map.river_routing import two_ring_receivers


def test_zero_epsilon_flat_retains_a_complete_downstream_first_graph() -> None:
    height = np.full((19, 23), 20.0)
    height[8:11, 8:11] = 2
    height[9, 0] = 10
    land = np.ones(height.shape, dtype=bool)
    filled, order, receiver = priority_flood(height, land, eps=0)
    cells = order[order >= 0]
    assert cells.size == 17 * 21
    assert (receiver[cells] >= 0).all()
    positions = np.full(height.size, -1)
    positions[cells] = np.arange(len(cells))
    assert (positions[receiver[cells]] < positions[cells]).all()
    assert np.unique(filled[1:-1, 1:-1]).tolist() == [20.0]
    weight = np.zeros(height.shape)
    weight.ravel()[cells] = 1
    acc = flow_accumulation(order, receiver, weight)
    assert acc.ravel()[receiver < 0].sum() == weight.sum()


def test_two_ring_edges_preserve_production_flood_order_and_dtype() -> None:
    row, col = np.indices((19, 23))
    height = 100.0 - 2 * row - col
    filled, order, base = priority_flood(height, np.ones(height.shape, bool), eps=0)
    rec, stats = two_ring_receivers(filled, np.ones(height.shape, bool), base.astype(np.int32))
    assert rec.dtype == np.int32
    assert stats["accepted_extensions"] > 0
    positions = np.full(height.size, -1)
    cells = order[order >= 0]
    positions[cells] = np.arange(len(cells))
    assert (positions[rec[cells]] < positions[cells]).all()
    weight = np.zeros(height.shape)
    weight.ravel()[cells] = 1
    acc = flow_accumulation(order, rec, weight)
    assert acc.ravel()[rec < 0].sum() == weight.sum()


def test_lake_cells_keep_original_receiver_and_long_edges_do_not_enter_water() -> None:
    row, col = np.indices((19, 23))
    height = 100.0 - 2 * row - col
    filled, _order, base = priority_flood(height, np.ones(height.shape, bool), eps=0)
    lake = np.zeros(height.shape, bool)
    lake[7:12, 8:13] = True
    rec, _stats = two_ring_receivers(filled, np.ones(height.shape, bool), base, lake)
    np.testing.assert_array_equal(rec[lake.ravel()], base[lake.ravel()])
    cells = np.flatnonzero((rec != base) & (rec >= 0))
    assert not lake.ravel()[rec[cells]].any()


def test_exact_receiver_segments_keep_long_edges_flow_and_monthly_boundary() -> None:
    rivers = np.zeros((7, 8), bool)
    rec = np.full(rivers.size, -1, np.int64)
    acc = np.zeros(rivers.shape)
    month = np.full(rivers.shape, 12, np.uint8)
    path = [(1, 1), (3, 2), (5, 3), (6, 3)]
    for i, (a, b) in enumerate(zip(path[:-1], path[1:], strict=True)):
        rivers[a] = True
        rec[a[0] * 8 + a[1]] = b[0] * 8 + b[1]
        acc[a] = 10 + i * 10
    month[path[0]] = 6
    segments, flows, regimes = river_segments(rivers, rec, acc, 1, month_active=month, smooth=False)
    expected = np.array([[[1, 5], [2, 3]], [[2, 3], [3, 1]], [[3, 1], [3, 0]]])
    np.testing.assert_array_equal(segments, expected)
    np.testing.assert_array_equal(regimes, [1, 0, 0])
    np.testing.assert_array_equal(flows, [15, 25, 30])
