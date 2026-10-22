"""Numba kernels for the plate partitions (private module).

``warped_voronoi`` is the multi-source Dijkstra of
:func:`dreamulator.map.plate_generator.voronoi_partition_warped`, moved into JIT
land unchanged: the same ``(cost, cell, plate)`` heap with the same tie order, so
its partitions are identical to the pure-Python loop it replaces.
"""

from __future__ import annotations

import heapq
from typing import Any

import numba
import numpy as np


@numba.njit(cache=True)
def warped_voronoi(
    seeds: np.ndarray,
    cell_cost: np.ndarray,
    inv_speed: np.ndarray,
    is_locked: np.ndarray,
    owner: np.ndarray,
    adj_offsets: np.ndarray,
    adj_nbrs: np.ndarray,
) -> np.ndarray:
    """Owner plate index of every cell (``owner`` holds the locked cells on entry)."""
    n = cell_cost.shape[0]
    dist = np.full(n, np.inf)
    heap: list[Any] = [(0.0, np.int64(0), np.int64(0))]
    heap.pop()
    for i in range(seeds.shape[0]):
        s = seeds[i]
        if is_locked[s]:
            heapq.heappush(heap, (0.0, s, np.int64(i)))
            continue
        if dist[s] > 0.0:  # first seed at this cell wins
            dist[s] = 0.0
            owner[s] = i
            heapq.heappush(heap, (0.0, s, np.int64(i)))
    while len(heap) > 0:
        d, u, i = heapq.heappop(heap)
        if d > dist[u]:
            continue  # stale heap entry
        step_scale = inv_speed[i]
        for k in range(adj_offsets[u], adj_offsets[u + 1]):
            v = adj_nbrs[k]
            if is_locked[v]:
                continue
            nd = d + cell_cost[v] * step_scale
            if nd < dist[v]:
                dist[v] = nd
                owner[v] = i
                heapq.heappush(heap, (nd, v, i))
    return owner
