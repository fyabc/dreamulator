"""Numba kernels for the programmatic erosion solver (private module).

Everything here is the hot loop of :mod:`dreamulator.map.prog_erosion`:
the heap-walk Priority-Flood, the downstream-first accumulation and the
implicit SPL update.  Callers go through the public wrappers, which
guarantee contiguous typed arrays before entering JIT land.
"""

from __future__ import annotations

import numba
import numpy as np


@numba.njit(cache=True)
def _push(heap: np.ndarray, heap_len: int, prio: float, cell: int) -> int:
    """Binary min-heap push into (prio, cell) parallel arrays."""
    i = heap_len
    heap_len += 1
    while i > 0:
        parent = (i - 1) // 2
        if heap[0, parent] <= prio:
            break
        heap[0, i], heap[1, i] = heap[0, parent], heap[1, parent]
        i = parent
    heap[0, i], heap[1, i] = prio, cell
    return heap_len


@numba.njit(cache=True)
def _pop(heap: np.ndarray, heap_len: int) -> tuple[int, float, float]:
    prio = heap[0, 0]
    cell = heap[1, 0]
    heap_len -= 1
    if heap_len > 0:
        prio_last, cell_last = heap[0, heap_len], heap[1, heap_len]
        i = 0
        while True:
            left = 2 * i + 1
            if left >= heap_len:
                break
            child = left
            right = left + 1
            if right < heap_len and heap[0, right] < heap[0, left]:
                child = right
            if heap[0, child] >= prio_last:
                break
            heap[0, i], heap[1, i] = heap[0, child], heap[1, child]
            i = child
        heap[0, i], heap[1, i] = prio_last, cell_last
    return heap_len, prio, cell


@numba.njit(cache=True)
def _priority_flood_numba(
    dem: np.ndarray, land: np.ndarray, eps: float, breach: bool = False
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    n = dem.size
    filled = np.empty_like(dem)
    order = np.empty(n, dtype=np.int64)
    receiver = np.full(n, -1, dtype=np.int64)
    _pf_core(dem, land, eps, filled, order, receiver, breach)
    return filled, order, receiver


@numba.njit(cache=True)
def _priority_flood_into(
    dem: np.ndarray,
    land: np.ndarray,
    eps: float,
    filled: np.ndarray,
    order: np.ndarray,
    receiver: np.ndarray,
    breach: bool = False,
) -> None:
    _pf_core(dem, land, eps, filled, order, receiver, breach)


@numba.njit(cache=True)
def _pf_core(
    dem: np.ndarray,
    land: np.ndarray,
    eps: float,
    filled: np.ndarray,
    order: np.ndarray,
    receiver: np.ndarray,
    breach: bool,
) -> None:
    h, w = dem.shape
    # Boundary cells act as outlets (the window edge truncates the world;
    # rivers may leave the frame, same semantics as the Gaea build) — a
    # fully landlocked window still drains.
    land = land.copy()
    land[0, :] = 0
    land[-1, :] = 0
    land[:, 0] = 0
    land[:, -1] = 0
    # State: 0 unseen, 1 in heap, 2 popped.
    state = np.zeros((h, w), dtype=np.uint8)
    heap = np.empty((2, h * w), dtype=np.float64)
    heap[1] = 0.0  # cell ids stored as float — safe below 2^52 cells
    heap_len = 0
    order_len = 0

    # Seed: all ocean cells at their own height, then push their land
    # neighbours (shore seeds — matches Barnes' Priority-Flood + ε).
    for y in range(h):
        for x in range(w):
            if not land[y, x]:
                state[y, x] = 2
                filled[y, x] = dem[y, x]
    for y in range(h):
        for x in range(w):
            if land[y, x]:
                continue
            for dy in range(-1, 2):
                for dx in range(-1, 2):
                    if dx == 0 and dy == 0:
                        continue
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < h and 0 <= nx < w and land[ny, nx] and state[ny, nx] == 0:
                        state[ny, nx] = 1
                        base = filled[y, x] - eps if breach else filled[y, x] + eps
                        filled[ny, nx] = max(dem[ny, nx], base)
                        receiver[ny * w + nx] = y * w + x
                        heap_len = _push(heap, heap_len, filled[ny, nx], ny * w + nx)

    while heap_len > 0:
        heap_len, _prio, cell = _pop(heap, heap_len)
        cell = int(cell)
        y0, x0 = cell // w, cell % w
        if state[y0, x0] == 2:
            continue  # stale entry (pushed twice before pop)
        state[y0, x0] = 2
        order[order_len] = cell
        order_len += 1
        for dy in range(-1, 2):
            for dx in range(-1, 2):
                if dx == 0 and dy == 0:
                    continue
                ny, nx = y0 + dy, x0 + dx
                if 0 <= ny < h and 0 <= nx < w and land[ny, nx] and state[ny, nx] == 0:
                    state[ny, nx] = 1
                    filled[ny, nx] = max(dem[ny, nx], filled[y0, x0] + eps)
                    receiver[ny * w + nx] = cell
                    heap_len = _push(heap, heap_len, filled[ny, nx], ny * w + nx)

    # Unused tail slots would hold garbage int64s - downstream consumers
    # index receiver[order[a]]; -1 marks 'no cell' and is skipped there.
    for a in range(order_len, order.size):
        order[a] = -1

    # Steepest descent receiver on the filled surface (D8), with the
    # discovery-order predecessor (recorded above) as the tie-break.
    # A filled depression grades at eps/step toward its spill; on that
    # near-flat rim band every strictly-lower neighbour has an eps-scale
    # slope, so the plain steepest rule picks by scan order and the path
    # wanders the perimeter — channels hugged the shoreline instead of
    # entering the lake (user-reported 2026-10-17).  Preferring the
    # predecessor when its slope ties the best (within eps) makes fill
    # cells follow the Barnes Priority-Flood +FlowDirs convention: the
    # discovery chain is the direct ramp descent to the spill.  On
    # ordinary terrain the true gradient dwarfs eps, the predecessor
    # loses, and the receiver is bit-identical to plain steepest descent.
    # Predecessors are always popped first (they discovered this cell),
    # so `order` stays a topological order of the tree; filled[predecessor]
    # <= filled[cell] - eps keeps it acyclic.
    dist_card = 1.0
    dist_diag = np.sqrt(2.0)
    for a in range(order_len):
        cell = order[a]
        y0, x0 = cell // w, cell % w
        f0 = filled[y0, x0]
        best = -1
        best_slope = 0.0
        for dy in range(-1, 2):
            for dx in range(-1, 2):
                if dx == 0 and dy == 0:
                    continue
                ny, nx = y0 + dy, x0 + dx
                if 0 <= ny < h and 0 <= nx < w:
                    fj = filled[ny, nx]
                    if land[ny, nx] and fj >= f0:
                        continue
                    dist = dist_diag if (dx != 0 and dy != 0) else dist_card
                    slope = (f0 - fj) / dist
                    if slope > best_slope:
                        best_slope = slope
                        best = ny * w + nx
        pred = receiver[cell]
        if pred >= 0:
            py, px = pred // w, pred % w
            fp = filled[py, px]
            dy = abs(py - y0) + abs(px - x0)
            dist = dist_diag if dy == 2 else dist_card
            pred_slope = (f0 - fp) / dist
            if fp < f0 and best_slope - pred_slope <= eps:
                best = pred
        receiver[cell] = best


@numba.njit(cache=True)
def _accumulate_numba(order: np.ndarray, receiver: np.ndarray, weight: np.ndarray) -> np.ndarray:
    out = weight.copy()
    flat = out.reshape(-1)
    for a in range(order.size - 1, -1, -1):
        i = order[a]
        if i < 0:
            continue
        r = receiver[i]
        if r >= 0:
            flat[r] += flat[i]
    return out


@numba.njit(cache=True)
def _spl_step_numba(
    h: np.ndarray,
    land: np.ndarray,
    order: np.ndarray,
    receiver: np.ndarray,
    acc: np.ndarray,
    dt: float,
    k: float,
    m: float,
    uplift: float,
    sea_level: float,
) -> None:
    """One implicit Braun–Willett SPL step over the drainage order."""
    w = h.shape[1]
    flat_h = h.reshape(-1)
    for a in range(order.size):
        i = order[a]
        if i < 0:
            continue
        r = receiver[i]
        if r < 0:
            continue
        hr = flat_h[r] if land.reshape(-1)[r] else sea_level
        y0, x0 = i // w, i % w
        yr, xr = r // w, r % w
        dist = np.sqrt(float((yr - y0) ** 2 + (xr - x0) ** 2))
        f_coef = k * dt * acc.reshape(-1)[i] ** m / dist
        flat_h[i] = (flat_h[i] + dt * uplift + f_coef * hr) / (1.0 + f_coef)
