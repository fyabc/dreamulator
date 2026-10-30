"""Numba kernels for the tiled canvas hydrology (private module).

The hot loop of :mod:`dreamulator.media.canvas_hydrology_tiled`'s stage 1:
the per-tile labelled Priority-Flood.  The pure-Python reference
(``canvas_hydrology_tiled._local_flood_reference``) is the correctness
oracle; this kernel replicates it bit-exactly — same seed scan order, same
``max(dem, level + eps)`` fill rule computed in float64 and stored back into
the DEM's own dtype, and the same ``(level, cell)`` lexicographic heap order
so plateau ties pop in identical order.  Spill-graph meetings are aggregated
in a ``numba.typed.Dict`` keyed by ``a << 32 | b`` (labels normalised
``a < b``), which the wrapper unpacks into the reference's tuple-keyed dict.
"""

from __future__ import annotations

import numba
import numpy as np
from numba import types


@numba.njit(cache=True)
def _push(prio: np.ndarray, cell: np.ndarray, n: int, p: float, c: int) -> int:
    """Binary min-heap push ordered by (prio, cell), lexicographic."""
    i = n
    n += 1
    while i > 0:
        parent = (i - 1) >> 1
        pp, pc = prio[parent], cell[parent]
        if pp < p or (pp == p and pc < c):
            break
        prio[i], cell[i] = pp, pc
        i = parent
    prio[i], cell[i] = p, c
    return n


@numba.njit(cache=True)
def _push_grow(
    prio: np.ndarray, cell: np.ndarray, n: int, p: float, c: int
) -> tuple[np.ndarray, np.ndarray, int]:
    """Push with capacity doubling for the relaxation-heavy Dijkstra heap."""
    if n == prio.size:
        cap = max(1024, n * 2)
        new_p = np.empty(cap, dtype=np.float64)
        new_c = np.empty(cap, dtype=np.int64)
        new_p[:n] = prio[:n]
        new_c[:n] = cell[:n]
        prio, cell = new_p, new_c
    return prio, cell, _push(prio, cell, n, p, c)


@numba.njit(cache=True)
def _grade_flats_kernel(filled: np.ndarray, sea_level: float, eps: float) -> np.ndarray:
    """Numba twin of ``canvas_pipeline._grade_flats_reference``.

    Multi-source Dijkstra over same-value flats: seeds are cells at or below
    sea level and cells with a strictly lower neighbour (tolerance 1e-9);
    each pop relaxes same-value neighbours to ``level + eps``.  Lazy-deletion
    heap — stale entries (``lv != level[c]``) are skipped on pop, exactly as
    the reference.  Returns the per-cell level (inf where ungraded).
    """
    h, w = filled.shape
    n_cells = h * w
    flat = filled.reshape(n_cells).astype(np.float64)
    level = np.full(n_cells, np.inf)
    cap = max(1024, n_cells // 4)
    prio = np.empty(cap, dtype=np.float64)
    heap_cell = np.empty(cap, dtype=np.int64)
    heap_len = 0

    for c in range(n_cells):
        v = flat[c]
        if not np.isfinite(v):
            continue
        r = c // w
        col = c - r * w
        if v <= sea_level:
            level[c] = v
            prio, heap_cell, heap_len = _push_grow(prio, heap_cell, heap_len, v, c)
            continue
        low = False
        for k in range(9):
            dy = (k // 3) - 1
            dx = (k - (k // 3) * 3) - 1
            if dy == 0 and dx == 0:
                continue
            nr = r + dy
            nc = col + dx
            if nr < 0 or nr >= h or nc < 0 or nc >= w:
                continue
            if flat[nr * w + nc] < v - 1e-9:
                low = True
                break
        if low:
            level[c] = v
            prio, heap_cell, heap_len = _push_grow(prio, heap_cell, heap_len, v, c)

    while heap_len > 0:
        heap_len, lv, c = _pop(prio, heap_cell, heap_len)
        if lv != level[c]:
            continue
        r = c // w
        col = c - r * w
        v0 = flat[c]
        for k in range(9):
            dy = (k // 3) - 1
            dx = (k - (k // 3) * 3) - 1
            if dy == 0 and dx == 0:
                continue
            nr = r + dy
            nc = col + dx
            if nr < 0 or nr >= h or nc < 0 or nc >= w:
                continue
            nid = nr * w + nc
            if flat[nid] != v0:
                continue
            nl = lv + eps
            if nl < level[nid]:
                level[nid] = nl
                prio, heap_cell, heap_len = _push_grow(prio, heap_cell, heap_len, nl, nid)
    return level


@numba.njit(cache=True)
def _pop(prio: np.ndarray, cell: np.ndarray, n: int) -> tuple[int, float, int]:
    """Pop the minimum (prio, cell); returns (new_len, prio, cell)."""
    p, c = prio[0], cell[0]
    n -= 1
    if n > 0:
        lp, lc = prio[n], cell[n]
        i = 0
        while True:
            left = 2 * i + 1
            if left >= n:
                break
            best = left
            bp, bc = prio[left], cell[left]
            right = left + 1
            if right < n:
                rp, rc = prio[right], cell[right]
                if rp < bp or (rp == bp and rc < bc):
                    best = right
                    bp, bc = rp, rc
            if bp > lp or (bp == lp and bc > lc):
                break
            prio[i], cell[i] = bp, bc
            i = best
        prio[i], cell[i] = lp, lc
    return n, p, c


@numba.njit(cache=True)
def _local_flood_kernel(
    dem: np.ndarray,
    external: np.ndarray,
    eps: float,
):
    """Numba twin of ``_local_flood_reference``; see the module docstring."""
    h, w = dem.shape
    n_cells = h * w
    labels = np.full((h, w), -1, dtype=np.int64)
    filled = dem.copy()
    prio = np.empty(n_cells, dtype=np.float64)
    heap_cell = np.empty(n_cells, dtype=np.int64)
    heap_len = 0
    next_label = 1
    spill = numba.typed.Dict.empty(types.int64, types.float64)

    for y in range(h):
        for x in range(w):
            on_edge = (y == 0 or y == h - 1 or x == 0 or x == w - 1) and h > 1 and w > 1
            if h == 1 or w == 1:
                on_edge = True  # a 1-wide tile is all edge
            if external[y, x]:
                labels[y, x] = 0
                heap_len = _push(prio, heap_cell, heap_len, float(dem[y, x]), y * w + x)
            elif on_edge:
                labels[y, x] = next_label
                next_label += 1
                heap_len = _push(prio, heap_cell, heap_len, float(dem[y, x]), y * w + x)

    while heap_len > 0:
        heap_len, level, c0 = _pop(prio, heap_cell, heap_len)
        y0 = c0 // w
        x0 = c0 - y0 * w
        lab0 = labels[y0, x0]
        for k in range(9):
            dy = (k // 3) - 1
            dx = (k - (k // 3) * 3) - 1
            if dy == 0 and dx == 0:
                continue
            ny = y0 + dy
            nx = x0 + dx
            if ny < 0 or ny >= h or nx < 0 or nx >= w:
                continue
            nl = labels[ny, nx]
            if nl < 0:
                labels[ny, nx] = lab0
                v = float(dem[ny, nx])
                cand = level + eps
                if cand > v:
                    v = cand
                filled[ny, nx] = v
                # Push the *stored* value: with float32 DEMs the candidate is
                # computed in float64 and narrowed on store — the reference
                # heap carries the narrowed value, so must this one.
                v = float(filled[ny, nx])
                heap_len = _push(prio, heap_cell, heap_len, v, ny * w + nx)
            elif nl != lab0:
                a = lab0
                b = nl
                if a > b:
                    a, b = b, a
                key = (np.int64(a) << np.int64(32)) | np.int64(b)
                meet = level
                fn = float(filled[ny, nx])
                if fn > meet:
                    meet = fn
                if key not in spill or meet < spill[key]:
                    spill[key] = meet
    return labels, filled, spill
