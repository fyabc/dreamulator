"""Tarboton (1997) pit filling and equal-height D8 resolution, local reference.

Use the accepted eight-facet direction calculation on a zero-epsilon filled
DEM. Unresolved flats receive a previously resolved equal-height D8 neighbor.
This pilot is independent of the production external-memory hydrology solver.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass

import numpy as np
from numba import njit

from scripts.media.dinf_local import Routing, _accumulate, directions


@njit(cache=True)
def _fill(height: np.ndarray, absorbing: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    nr, nc = height.shape
    filled = height.copy()
    reached = np.zeros(height.shape, dtype=np.bool_)
    heap = [(0.0, -1)]
    heap.pop()
    for row in range(nr):
        for col in range(nc):
            if absorbing[row, col] and np.isfinite(height[row, col]):
                reached[row, col] = True
                heapq.heappush(heap, (height[row, col], row * nc + col))
    while heap:
        level, cell = heapq.heappop(heap)
        row, col = divmod(cell, nc)
        for dr in range(-1, 2):
            for dc in range(-1, 2):
                r, c = row + dr, col + dc
                if not (0 <= r < nr and 0 <= c < nc):
                    continue
                if reached[r, c] or not np.isfinite(height[r, c]):
                    continue
                reached[r, c] = True
                filled[r, c] = max(height[r, c], level)
                heapq.heappush(heap, (filled[r, c], r * nc + c))
    return filled, reached


@njit(cache=True)
def _flats(height: np.ndarray, receiver: np.ndarray, absorbing: np.ndarray) -> np.ndarray:
    """Breadth-first resolution toward equal-height cells with an existing route."""
    nr, nc = height.shape
    rank = np.full(height.size, -1, dtype=np.int64)
    queue = np.empty(height.size, dtype=np.int64)
    tail = 0
    for cell in range(height.size):
        r, c = divmod(cell, nc)
        if np.isfinite(height[r, c]) and (absorbing[r, c] or receiver[cell] >= 0):
            rank[cell] = 0
            queue[tail] = cell
            tail += 1
    head = 0
    while head < tail:
        cell = queue[head]
        head += 1
        row, col = divmod(cell, nc)
        for dr in range(-1, 2):
            for dc in range(-1, 2):
                r, c = row + dr, col + dc
                if not (0 <= r < nr and 0 <= c < nc):
                    continue
                neighbor = r * nc + c
                if rank[neighbor] < 0 and height[r, c] == height[row, col]:
                    rank[neighbor] = rank[cell] + 1
                    receiver[neighbor] = cell
                    queue[tail] = neighbor
                    tail += 1
    return rank.reshape(height.shape)


@njit(cache=True)
def _topology(receiver: np.ndarray) -> np.ndarray:
    count = receiver.shape[0]
    indegree = np.zeros(count, dtype=np.int64)
    for cell in range(count):
        for edge in range(2):
            target = receiver[cell, edge]
            if target >= 0:
                indegree[target] += 1
    order = np.empty(count, dtype=np.int64)
    tail = 0
    for cell in range(count):
        if indegree[cell] == 0:
            order[tail] = cell
            tail += 1
    head = 0
    while head < tail:
        cell = order[head]
        head += 1
        for edge in range(2):
            target = receiver[cell, edge]
            if target >= 0:
                indegree[target] -= 1
                if indegree[target] == 0:
                    order[tail] = target
                    tail += 1
    if tail != count:
        raise ValueError("flow graph contains a cycle")
    return order


@dataclass
class Prepared:
    height_m: np.ndarray
    d8_receiver: np.ndarray
    flat_rank: np.ndarray
    reached: np.ndarray
    absorbing: np.ndarray


def prepare(height_m: np.ndarray, absorbing: np.ndarray) -> Prepared:
    h = np.asarray(height_m, dtype=np.float64)
    if h.ndim != 2 or min(h.shape) < 2 or max(h.shape) > 1024:
        raise ValueError("local DEM requires 2 to 1024 rows and columns")
    if absorbing.shape != h.shape or not (absorbing & np.isfinite(h)).any():
        raise ValueError("absorbing mask needs a finite outlet and the DEM shape")
    stop = np.asarray(absorbing, dtype=bool)
    filled, reached = _fill(h, stop)
    d8 = directions(filled, 1, stop, method="d8")
    receiver = d8.receiver[..., 0].copy().ravel()
    rank = _flats(filled, receiver, stop)
    return Prepared(filled, receiver.reshape(h.shape), rank, reached, stop)


def routing(prepared: Prepared, spacing_m: float = 1) -> Routing:
    route = directions(prepared.height_m, spacing_m, prepared.absorbing)
    unresolved = (route.proportion.sum(axis=2) == 0) & ~prepared.absorbing
    resolved = unresolved & (prepared.d8_receiver >= 0)
    target = prepared.d8_receiver[resolved]
    route.receiver[resolved, 0] = target
    route.proportion[resolved, 0] = 1
    row, col = np.nonzero(resolved)
    tr, tc = np.divmod(target, prepared.height_m.shape[1])
    route.angle_rad[resolved] = np.arctan2(row - tr, tc - col) % (2 * np.pi)
    return route


def topological_order(height_m: np.ndarray, route: Routing) -> np.ndarray:
    h = np.asarray(height_m).ravel()
    rec, p = route.receiver.reshape(-1, 2), route.proportion.reshape(-1, 2)
    if rec.shape[0] != h.size or p.shape != rec.shape:
        raise ValueError("routing shape differs from height")
    if not np.isfinite(p).all() or (p < 0).any():
        raise ValueError("proportions must be finite and nonnegative")
    positive = p > 0
    if (rec[~positive] != -1).any() or (rec[positive] < 0).any() or (rec[positive] >= h.size).any():
        raise ValueError("positive edges need valid receivers; unused edges must be -1")
    source = np.broadcast_to(np.arange(h.size)[:, None], rec.shape)[positive]
    target = rec[positive]
    if not (h[source] >= h[target]).all():
        raise ValueError("flow edges cannot go uphill")
    sr, sc = np.divmod(source, height_m.shape[1])
    tr, tc = np.divmod(target, height_m.shape[1])
    if (np.maximum(abs(sr - tr), abs(sc - tc)) != 1).any():
        raise ValueError("receivers must be neighboring cells")
    if not np.allclose(p.sum(axis=1), positive.any(axis=1), atol=1e-14, rtol=0):
        raise ValueError("outgoing fractions must sum to one")
    return _topology(rec)


def accumulate(prepared: Prepared, route: Routing, source: np.ndarray) -> np.ndarray:
    order = topological_order(prepared.height_m, route)
    if (
        source.shape != prepared.height_m.shape
        or not np.isfinite(source).all()
        or (source < 0).any()
    ):
        raise ValueError("source must be finite, nonnegative and have the DEM shape")
    if (source[~np.isfinite(prepared.height_m)] != 0).any():
        raise ValueError("missing cells cannot produce water")
    return _accumulate(
        order,
        route.receiver.reshape(-1, 2),
        route.proportion.reshape(-1, 2),
        np.asarray(source, dtype=float).ravel(),
    ).reshape(source.shape)
