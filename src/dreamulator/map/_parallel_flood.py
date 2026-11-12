"""Tiled parallel Priority-Flood + epsilon (numba threads; private module).

The serial kernel (:func:`dreamulator.map._erosion_kernels._priority_flood_numba`)
walks one heap over the whole grid.  This variant splits the work:

1. **Exact fill by tiles** (Barnes et al. 2014, 2016).  Every tile floods from
   its outlets and from each of its own edge cells (one label per edge cell),
   recording the lowest level at which every pair of labels meets.  A
   Priority-Flood over that label graph — tile spill pairs plus the seams
   between tiles — gives every label its water level, and each cell is raised
   to its label's level.  The result equals the serial fill with eps = 0
   bit for bit.
2. **Flats drain toward their exits.**  Land cells with no lower neighbour on
   the fill (lake surfaces and level plateaus) take their receiver from a
   breadth-first search started at the flat's exits, the discovery chain the
   serial Priority-Flood + eps follows down a filled depression.
3. **Order and ramp by pointer doubling.**  Each land cell's hop count to its
   outlet orders the cells downstream first (a stable counting sort; a
   receiver is always one hop shallower), and the eps surface is the serial
   recursion ``f = max(fill, f(receiver) + eps)`` unrolled along the path.

Steepest-descent ties are broken by scan order rather than by the serial
discovery chain, so receivers differ from the serial kernel on exactly tied
slopes (integer-metre TD surfaces have many) and inside flats; the fill, the
drainage tree's validity and the trunk network are the same.
"""

from __future__ import annotations

import numba
import numpy as np
from numba import types
from numba.typed import Dict

from ._erosion_kernels import _pop, _push

_SQRT2 = np.sqrt(2.0)


@numba.njit(cache=True)
def _tile_flood(
    dem: np.ndarray,
    outlet: np.ndarray,
    y0: int,
    y1: int,
    x0: int,
    x1: int,
    lab: np.ndarray,
    fil: np.ndarray,
    pa: np.ndarray,
    pb: np.ndarray,
    plv: np.ndarray,
    cap: int,
) -> tuple[int, int]:
    """Flood one tile from its outlets (label 0) and edge land cells (labels 1..L).

    Writes ``lab``/``fil`` inside the tile and up to ``cap`` label-pair
    meetings (a < b, lowest level per pair) into ``pa``/``pb``/``plv``.
    Returns (L, pairs), or (L, -1) when ``cap`` was too small.
    """
    th, tw = y1 - y0, x1 - x0
    state = np.zeros((th, tw), np.uint8)
    heap = np.empty((2, th * tw), np.float64)
    hl = 0
    nlab = 0
    for y in range(y0, y1):
        for x in range(x0, x1):
            edge = y == y0 or y == y1 - 1 or x == x0 or x == x1 - 1
            if outlet[y, x]:
                lab[y, x] = 0
                fil[y, x] = dem[y, x]
                # an outlet without a land neighbour discovers nothing
                touches = False
                for dy in range(-1, 2):
                    for dx in range(-1, 2):
                        ny, nx = y + dy, x + dx
                        if y0 <= ny < y1 and x0 <= nx < x1 and not outlet[ny, nx]:
                            touches = True
                if not touches:
                    state[y - y0, x - x0] = 2
                    continue
            elif edge:
                nlab += 1
                lab[y, x] = nlab
            else:
                continue
            fil[y, x] = dem[y, x]
            state[y - y0, x - x0] = 1
            hl = _push(heap, hl, fil[y, x], (y - y0) * tw + (x - x0))
    best = Dict.empty(key_type=types.int64, value_type=types.float64)
    stride = nlab + 1
    while hl > 0:
        hl, _p, cf = _pop(heap, hl)
        c = int(cf)
        ly, lx = c // tw, c % tw
        if state[ly, lx] == 2:
            continue
        state[ly, lx] = 2
        y, x = ly + y0, lx + x0
        fc = fil[y, x]
        lc = lab[y, x]
        for dy in range(-1, 2):
            for dx in range(-1, 2):
                if dy == 0 and dx == 0:
                    continue
                ny, nx = y + dy, x + dx
                if ny < y0 or ny >= y1 or nx < x0 or nx >= x1:
                    continue
                if state[ny - y0, nx - x0] == 0:
                    state[ny - y0, nx - x0] = 1
                    fil[ny, nx] = max(dem[ny, nx], fc)
                    lab[ny, nx] = lc
                    hl = _push(heap, hl, fil[ny, nx], (ny - y0) * tw + (nx - x0))
                else:
                    ln = lab[ny, nx]
                    if ln != lc:
                        a, b = (lc, ln) if lc < ln else (ln, lc)
                        key = np.int64(a) * stride + b
                        lv = max(fc, fil[ny, nx])
                        if key not in best or lv < best[key]:
                            best[key] = lv
    k = 0
    for key, lv in best.items():
        if k >= cap:
            return nlab, -1
        pa[k] = key // stride
        pb[k] = key % stride
        plv[k] = lv
        k += 1
    return nlab, k


@numba.njit(parallel=True, cache=True)
def _flood_tiles(
    dem: np.ndarray,
    outlet: np.ndarray,
    tile: int,
    lab: np.ndarray,
    fil: np.ndarray,
    pa: np.ndarray,
    pb: np.ndarray,
    plv: np.ndarray,
    cap: int,
    nlab_out: np.ndarray,
    npair_out: np.ndarray,
) -> None:
    h, w = dem.shape
    nty, ntx = -(-h // tile), -(-w // tile)
    for t in numba.prange(nty * ntx):  # type: ignore[no-untyped-call,attr-defined]
        y0, x0 = (t // ntx) * tile, (t % ntx) * tile
        nl, npair = _tile_flood(
            dem, outlet, y0, min(y0 + tile, h), x0, min(x0 + tile, w), lab, fil,
            pa[t], pb[t], plv[t], cap,
        )  # fmt: skip
        nlab_out[t] = nl
        npair_out[t] = npair


@numba.njit(cache=True)
def _seam_node(lab: np.ndarray, off: np.ndarray, tile: int, ntx: int, y: int, x: int) -> int:
    lv = lab[y, x]
    if lv == 0:
        return 0
    return int(off[(y // tile) * ntx + x // tile] + lv)


@numba.njit(cache=True)
def minimax_levels(nn: int, ea: np.ndarray, eb: np.ndarray, ew: np.ndarray) -> np.ndarray:
    """Lowest spill level of every node: Priority-Flood over an undirected graph from node 0.

    A node's level is the minimum over paths to node 0 of the largest edge weight
    on the path (node 0 sits at -inf); nodes not connected to node 0 keep +inf.
    The value is unique, so edge order and duplicate edges do not change it.
    """
    m = ea.size
    deg = np.zeros(nn + 1, np.int64)
    for i in range(m):
        deg[ea[i] + 1] += 1
        deg[eb[i] + 1] += 1
    for i in range(nn):
        deg[i + 1] += deg[i]
    adj = np.empty(2 * m, np.int64)
    wgt = np.empty(2 * m, np.float64)
    pos = deg[:-1].copy()
    for i in range(m):
        a, b = ea[i], eb[i]
        adj[pos[a]], wgt[pos[a]] = b, ew[i]
        pos[a] += 1
        adj[pos[b]], wgt[pos[b]] = a, ew[i]
        pos[b] += 1
    level = np.full(nn, np.inf)
    level[0] = -np.inf
    done = np.zeros(nn, np.uint8)
    heap = np.empty((2, 2 * m + 1), np.float64)
    hl = _push(heap, 0, -np.inf, 0)
    while hl > 0:
        hl, cur, nf = _pop(heap, hl)
        node = int(nf)
        if done[node]:
            continue
        done[node] = 1
        for j in range(deg[node], deg[node + 1]):
            cand = max(cur, wgt[j])
            if cand < level[adj[j]]:
                level[adj[j]] = cand
                hl = _push(heap, hl, cand, adj[j])
    return level


@numba.njit(cache=True)
def _label_levels(
    dem: np.ndarray,
    lab: np.ndarray,
    tile: int,
    nlab: np.ndarray,
    npair: np.ndarray,
    pa: np.ndarray,
    pb: np.ndarray,
    plv: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Water level of every label (node 0 = the outlets) by Priority-Flood on the label graph."""
    h, w = dem.shape
    nty, ntx = -(-h // tile), -(-w // tile)
    nt = nty * ntx
    off = np.zeros(nt + 1, np.int64)
    for t in range(nt):
        off[t + 1] = off[t] + nlab[t]
    nn = off[nt] + 1
    ne_max = 6 * (h * ntx + w * nty) + 16
    for t in range(nt):
        ne_max += npair[t]
    ea = np.empty(ne_max, np.int64)
    eb = np.empty(ne_max, np.int64)
    ew = np.empty(ne_max, np.float64)
    m = 0
    for t in range(nt):
        for k in range(npair[t]):
            ea[m] = off[t] + pa[t, k] if pa[t, k] > 0 else 0
            eb[m] = off[t] + pb[t, k] if pb[t, k] > 0 else 0
            ew[m] = plv[t, k]
            m += 1
    for s in range(tile, w, tile):  # seams between tile columns, diagonals included
        for y in range(h):
            for dy in range(-1, 2):
                ny = y + dy
                if 0 <= ny < h:
                    u = _seam_node(lab, off, tile, ntx, y, s - 1)
                    v = _seam_node(lab, off, tile, ntx, ny, s)
                    if u != v:
                        ea[m], eb[m] = u, v
                        ew[m] = max(dem[y, s - 1], dem[ny, s])
                        m += 1
    for s in range(tile, h, tile):  # seams between tile rows; seam-corner diagonals done above
        for x in range(w):
            for dx in range(-1, 2):
                nx = x + dx
                if 0 <= nx < w and (dx == 0 or x // tile == nx // tile):
                    u = _seam_node(lab, off, tile, ntx, s - 1, x)
                    v = _seam_node(lab, off, tile, ntx, s, nx)
                    if u != v:
                        ea[m], eb[m] = u, v
                        ew[m] = max(dem[s - 1, x], dem[s, nx])
                        m += 1
    level = minimax_levels(nn, ea[:m], eb[:m], ew[:m])
    return level, off


@numba.njit(parallel=True, cache=True)
def _raise_to_levels(
    fil: np.ndarray, lab: np.ndarray, level: np.ndarray, off: np.ndarray, tile: int
) -> None:
    h, w = fil.shape
    ntx = -(-w // tile)
    for y in numba.prange(h):  # type: ignore[no-untyped-call,attr-defined]
        for x in range(w):
            lv = lab[y, x]
            if lv > 0:
                v = level[off[(y // tile) * ntx + x // tile] + lv]
                if v > fil[y, x]:
                    fil[y, x] = v


@numba.njit(parallel=True, cache=True)
def _outlet_mask(land: np.ndarray, outlet: np.ndarray) -> None:
    """Outlets: non-land cells and the frame (rivers may leave the window)."""
    h, w = land.shape
    for y in numba.prange(h):  # type: ignore[no-untyped-call,attr-defined]
        for x in range(w):
            frame = y == 0 or y == h - 1 or x == 0 or x == w - 1
            outlet[y, x] = 1 if (frame or not land[y, x]) else 0


@numba.njit(parallel=True, cache=True)
def _steepest(f0: np.ndarray, outlet: np.ndarray, rec: np.ndarray) -> None:
    """Steepest descent on the fill (outlets at or below the cell count as lower); -2 = flat."""
    h, w = f0.shape
    for y in numba.prange(h):  # type: ignore[no-untyped-call,attr-defined]
        for x in range(w):
            c = y * w + x
            if outlet[y, x]:
                rec[c] = -1
                continue
            fc = f0[y, x]
            best = -2
            best_slope = -1.0
            for dy in range(-1, 2):
                for dx in range(-1, 2):
                    if dy == 0 and dx == 0:
                        continue
                    ny, nx = y + dy, x + dx
                    if ny < 0 or ny >= h or nx < 0 or nx >= w:
                        continue
                    fn = f0[ny, nx]
                    if fn > fc or (fn == fc and not outlet[ny, nx]):
                        continue
                    slope = (fc - fn) / (_SQRT2 if (dy != 0 and dx != 0) else 1.0)
                    if slope > best_slope:
                        best_slope = slope
                        best = ny * w + nx
            rec[c] = best


@numba.njit(parallel=True, cache=True)
def _flat_exits(f0: np.ndarray, rec: np.ndarray, is_exit: np.ndarray) -> None:
    """Non-flat land cells next to an equal-height flat cell: the flat searches start there."""
    h, w = f0.shape
    for y in numba.prange(h):  # type: ignore[no-untyped-call,attr-defined]
        for x in range(w):
            c = y * w + x
            is_exit[c] = 0
            if rec[c] < 0:
                continue
            for dy in range(-1, 2):
                for dx in range(-1, 2):
                    ny, nx = y + dy, x + dx
                    if (dy == 0 and dx == 0) or ny < 0 or ny >= h or nx < 0 or nx >= w:
                        continue
                    if rec[ny * w + nx] == -2 and f0[ny, nx] == f0[y, x]:
                        is_exit[c] = 1


@numba.njit(cache=True)
def _drain_flats(f0: np.ndarray, rec: np.ndarray, exits: np.ndarray) -> None:
    """Receiver of a flat cell = its breadth-first parent among equal-height cells."""
    h, w = f0.shape
    q = np.empty(max(16, 2 * exits.size), np.int64)
    qt = 0
    for c in exits:
        q[qt] = c
        qt += 1
    qh = 0
    while qh < qt:
        c = q[qh]
        qh += 1
        y, x = c // w, c % w
        for dy in range(-1, 2):
            for dx in range(-1, 2):
                if dy == 0 and dx == 0:
                    continue
                ny, nx = y + dy, x + dx
                if ny < 0 or ny >= h or nx < 0 or nx >= w:
                    continue
                j = ny * w + nx
                if rec[j] == -2 and f0[ny, nx] == f0[y, x]:
                    rec[j] = c
                    if qt == q.size:
                        grown = np.empty(2 * q.size, np.int64)
                        grown[:qt] = q[:qt]
                        q = grown
                    q[qt] = j
                    qt += 1


@numba.njit(parallel=True, cache=True)
def _land_index(outlet: np.ndarray, nchunk: int) -> tuple[np.ndarray, np.ndarray]:
    """Land cells in scan order and the cell -> land-position map (-1 for outlets)."""
    flat = outlet.reshape(-1)
    n = flat.size
    size = -(-n // nchunk)
    cnt = np.zeros(nchunk + 1, np.int64)
    for t in numba.prange(nchunk):  # type: ignore[no-untyped-call,attr-defined]
        k = 0
        for c in range(t * size, min((t + 1) * size, n)):
            if flat[c] == 0:
                k += 1
        cnt[t + 1] = k
    for t in range(nchunk):
        cnt[t + 1] += cnt[t]
    cells = np.empty(cnt[nchunk], np.int64)
    li = np.empty(n, np.int64)
    for t in numba.prange(nchunk):  # type: ignore[no-untyped-call,attr-defined]
        k = cnt[t]
        for c in range(t * size, min((t + 1) * size, n)):
            if flat[c] == 0:
                cells[k] = c
                li[c] = k
                k += 1
            else:
                li[c] = -1
    return cells, li


@numba.njit(parallel=True, cache=True)
def _jump(nxt: np.ndarray, nxt2: np.ndarray, val: np.ndarray, val2: np.ndarray, add: bool) -> None:
    """One pointer-doubling step: combine each value with its successor's (sum or max)."""
    for i in numba.prange(nxt.size):  # type: ignore[no-untyped-call,attr-defined]
        j = nxt[i]
        if j >= 0:
            val2[i] = val[i] + val[j] if add else max(val[i], val[j])
            nxt2[i] = nxt[j]
        else:
            val2[i] = val[i]
            nxt2[i] = -1


@numba.njit(parallel=True, cache=True)
def _pending(nxt: np.ndarray) -> int:
    k = 0
    for i in numba.prange(nxt.size):  # type: ignore[no-untyped-call,attr-defined]
        if nxt[i] >= 0:
            k += 1
    return k


@numba.njit(parallel=True, cache=True)
def _successors(cells: np.ndarray, li: np.ndarray, rec: np.ndarray, nxt: np.ndarray) -> None:
    for i in numba.prange(cells.size):  # type: ignore[no-untyped-call,attr-defined]
        nxt[i] = li[rec[cells[i]]]  # -1 when the receiver is an outlet


@numba.njit(parallel=True, cache=True)
def _ramp_seed(
    cells: np.ndarray, li: np.ndarray, rec: np.ndarray, f0: np.ndarray, d: np.ndarray, eps: float,
    g: np.ndarray,
) -> None:  # fmt: skip
    """g = fill - eps * depth per land cell, folded with the outlet's own fill at depth 0."""
    for i in numba.prange(cells.size):  # type: ignore[no-untyped-call,attr-defined]
        c = cells[i]
        r = rec[c]
        g[i] = f0[c] - eps * d[i]
        if li[r] < 0 and f0[r] > g[i]:
            g[i] = f0[r]


@numba.njit(parallel=True, cache=True)
def _scatter_ramp(
    cells: np.ndarray, d: np.ndarray, g: np.ndarray, eps: float, depth: np.ndarray, out: np.ndarray
) -> None:
    for i in numba.prange(cells.size):  # type: ignore[no-untyped-call,attr-defined]
        depth[cells[i]] = d[i]
        out[cells[i]] = eps * d[i] + g[i]


@numba.njit(parallel=True, cache=True)
def _order_by_depth(cells: np.ndarray, depth: np.ndarray, order: np.ndarray, nchunk: int) -> None:
    """Stable counting sort of land cells by depth: receivers come first."""
    m = cells.size
    dmax = 0
    for i in range(m):
        dmax = max(dmax, depth[cells[i]])
    size = -(-m // nchunk)
    hist = np.zeros((nchunk, dmax + 1), np.int64)
    for t in numba.prange(nchunk):  # type: ignore[no-untyped-call,attr-defined]
        for i in range(t * size, min((t + 1) * size, m)):
            hist[t, depth[cells[i]]] += 1
    start = np.empty((nchunk, dmax + 1), np.int64)
    acc = 0
    for dv in range(dmax + 1):
        for t in range(nchunk):
            start[t, dv] = acc
            acc += hist[t, dv]
    for t in numba.prange(nchunk):  # type: ignore[no-untyped-call,attr-defined]
        pos = start[t]
        for i in range(t * size, min((t + 1) * size, m)):
            c = cells[i]
            order[pos[depth[c]]] = c
            pos[depth[c]] += 1


def _doubling(nxt: np.ndarray, val: np.ndarray, *, add: bool) -> np.ndarray:
    """Fold ``val`` along successor chains to their ends (sum or max), in log2(length) steps."""
    nxt, val = nxt.copy(), val.copy()
    nxt2, val2 = np.empty_like(nxt), np.empty_like(val)
    while _pending(nxt):
        _jump(nxt, nxt2, val, val2, add)
        nxt, nxt2 = nxt2, nxt
        val, val2 = val2, val
    return val


def priority_flood_tiled(
    dem: np.ndarray, land: np.ndarray, eps: float, tile: int = 256
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(filled, order, receiver) in the conventions of ``prog_erosion.priority_flood``."""
    dem = np.ascontiguousarray(dem, dtype=np.float64)
    h, w = dem.shape
    outlet = np.empty((h, w), np.uint8)
    _outlet_mask(np.ascontiguousarray(land, dtype=np.bool_), outlet)
    nt = (-(-h // tile)) * (-(-w // tile))
    lab = np.zeros((h, w), np.int32)
    fil = np.empty((h, w), np.float64)
    cap = 16 * tile
    while True:
        pa = np.empty((nt, cap), np.int64)
        pb = np.empty((nt, cap), np.int64)
        plv = np.empty((nt, cap), np.float64)
        nlab = np.zeros(nt, np.int64)
        npair = np.zeros(nt, np.int64)
        _flood_tiles(dem, outlet, tile, lab, fil, pa, pb, plv, cap, nlab, npair)
        if (npair >= 0).all():
            break
        cap *= 4
    level, off = _label_levels(dem, lab, tile, nlab, npair, pa, pb, plv)
    del pa, pb, plv
    _raise_to_levels(fil, lab, level, off, tile)
    del lab
    rec = np.empty(h * w, np.int64)
    _steepest(fil, outlet, rec)
    is_exit = np.empty(h * w, np.uint8)
    _flat_exits(fil, rec, is_exit)
    _drain_flats(fil, rec, np.flatnonzero(is_exit))
    del is_exit
    nchunk = max(1, numba.get_num_threads() * 4)  # type: ignore[no-untyped-call]
    cells, li = _land_index(outlet, nchunk)
    nxt = np.empty(cells.size, np.int64)
    _successors(cells, li, rec, nxt)
    d = _doubling(nxt, np.ones(cells.size, np.int64), add=True)
    g = np.empty(cells.size, np.float64)
    f0 = fil.reshape(-1)
    _ramp_seed(cells, li, rec, f0, d, eps, g)
    g = _doubling(nxt, g, add=False)
    depth = np.zeros(h * w, np.int64)
    filled = fil.copy()
    _scatter_ramp(cells, d, g, eps, depth, filled.reshape(-1))
    order = np.full(h * w, -1, np.int64)
    _order_by_depth(cells, depth, order, nchunk)
    return filled, order, rec
