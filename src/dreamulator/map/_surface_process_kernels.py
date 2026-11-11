"""Numba kernels of the canvas surface-process solver (private module).

The hot loops of :mod:`dreamulator.map.surface_process`: the implicit
stream-power step, the threshold-slope collapse, sediment routing with lake
infill, and the fused element-wise steps of the time loop.  Each fused
kernel reproduces a numpy expression of the loop element for element, so the
surface does not depend on which form runs.  Callers go through the solver,
which hands in contiguous typed arrays.
"""

from __future__ import annotations

import numba
import numpy as np


@numba.njit(cache=True)
def _spl(
    hf: np.ndarray,
    fixed: np.ndarray,
    active: np.ndarray,
    order: np.ndarray,
    rec: np.ndarray,
    q: np.ndarray,
    dt: float,
    k: float,
    m: float,
    px_m: float,
) -> int:
    w = hf.shape[1]
    f = hf.reshape(-1)
    n = 0
    for a in range(order.size):
        i = order[a]
        if i < 0:
            break
        r = rec[i]
        if r < 0 or fixed[i] or not active[i]:
            continue
        hr = f[r]
        if hr >= f[i]:
            continue
        dy = i // w - r // w
        dx = i % w - r % w
        dist = px_m * np.sqrt(float(dy * dy + dx * dx))
        c = k * dt * q[i] ** m / dist
        f[i] = (f[i] + c * hr) / (1.0 + c)
        n += 1
    return n


@numba.njit(cache=True)
def _threshold(
    h: np.ndarray,
    mutable: np.ndarray,
    s_m: float,
) -> float:
    """Threshold slope: h[i] <- min(h[i], min_j h[j] + s_m * d_ij) on mutable cells.

    Forward and backward chamfer sweeps over the 8-neighbour graph, repeated to convergence.
    """
    nrow, ncol = h.shape
    d2 = s_m * np.sqrt(2.0)
    total = 0.0
    for _it in range(50):
        changed = 0
        for y in range(nrow):
            for x in range(ncol):
                if not mutable[y, x]:
                    continue
                v = h[y, x]
                for dy, dx, d in ((-1, -1, d2), (-1, 0, s_m), (-1, 1, d2), (0, -1, s_m)):
                    yy, xx = y + dy, x + dx
                    if 0 <= yy < nrow and 0 <= xx < ncol and h[yy, xx] + d < v:
                        v = h[yy, xx] + d
                if v < h[y, x]:
                    total += h[y, x] - v
                    h[y, x] = v
                    changed += 1
        for y in range(nrow - 1, -1, -1):
            for x in range(ncol - 1, -1, -1):
                if not mutable[y, x]:
                    continue
                v = h[y, x]
                for dy, dx, d in ((1, 1, d2), (1, 0, s_m), (1, -1, d2), (0, 1, s_m)):
                    yy, xx = y + dy, x + dx
                    if 0 <= yy < nrow and 0 <= xx < ncol and h[yy, xx] + d < v:
                        v = h[yy, xx] + d
                if v < h[y, x]:
                    total += h[y, x] - v
                    h[y, x] = v
                    changed += 1
        if changed == 0:
            break
    return total


@numba.njit(cache=True)
def _threshold_map(
    h: np.ndarray,
    mutable: np.ndarray,
    s_m: float,
    removed: np.ndarray,
) -> None:
    """Round-1 threshold collapse that also records the removed thickness per cell."""
    nrow, ncol = h.shape
    d2 = s_m * np.sqrt(2.0)
    for _it in range(50):
        changed = 0
        for y in range(nrow):
            for x in range(ncol):
                if not mutable[y, x]:
                    continue
                v = h[y, x]
                for dy, dx, d in ((-1, -1, d2), (-1, 0, s_m), (-1, 1, d2), (0, -1, s_m)):
                    yy, xx = y + dy, x + dx
                    if 0 <= yy < nrow and 0 <= xx < ncol and h[yy, xx] + d < v:
                        v = h[yy, xx] + d
                if v < h[y, x]:
                    removed[y, x] += h[y, x] - v
                    h[y, x] = v
                    changed += 1
        for y in range(nrow - 1, -1, -1):
            for x in range(ncol - 1, -1, -1):
                if not mutable[y, x]:
                    continue
                v = h[y, x]
                for dy, dx, d in ((1, 1, d2), (1, 0, s_m), (1, -1, d2), (0, 1, s_m)):
                    yy, xx = y + dy, x + dx
                    if 0 <= yy < nrow and 0 <= xx < ncol and h[yy, xx] + d < v:
                        v = h[yy, xx] + d
                if v < h[y, x]:
                    removed[y, x] += h[y, x] - v
                    h[y, x] = v
                    changed += 1
        if changed == 0:
            break


@numba.njit(cache=True)
def _fill_lake(
    hf: np.ndarray,
    cells: np.ndarray,
    level: float,
    budget: float,
) -> float:
    """Raise the lowest cells of one lake towards ``level`` with ``budget`` (m x cells).

    Bottom-up; ``cells`` is sorted by height at routing time.  Returns the unused
    budget exactly: the volume actually added is measured, so the ledger stays
    exact even if the order drifted within the step.
    """
    n = cells.size
    if n == 0 or budget <= 0.0:
        return budget
    cap = 0.0
    for j in range(n):
        cap += max(level - hf[cells[j]], 0.0)
    if budget >= cap:
        for j in range(n):
            if hf[cells[j]] < level:
                hf[cells[j]] = level
        return budget - cap
    s = hf[cells[0]]
    k = 1
    while k < n:
        hk = min(hf[cells[k]], level)
        if hk * k - s >= budget:
            break
        s += hf[cells[k]]
        k += 1
    lvl = min((budget + s) / k, level)
    added = 0.0
    for j in range(k):
        c = cells[j]
        if hf[c] < lvl:
            added += lvl - hf[c]
            hf[c] = lvl
    return budget - added


@numba.njit(cache=True)
def _route_sediment(
    hflat: np.ndarray,
    order: np.ndarray,
    rec: np.ndarray,
    q: np.ndarray,
    src_m: np.ndarray,
    lake_lbl: np.ndarray,
    lake_ptr: np.ndarray,
    lake_cells: np.ndarray,
    lake_level: np.ndarray,
    is_outlet: np.ndarray,
    terminal_lake: np.ndarray,
    mutable: np.ndarray,
    routed: np.ndarray,
    g_coef: float,
    p_m_yr: float,
    area_m2: float,
    min_donor: np.ndarray,
) -> tuple[float, float, float, float]:
    """Upstream-first sediment routing.  Volumes in m x cells (multiply by cell area for m3).
    Returns (deposited_river, filled_lake, exported, playa)."""
    vol = src_m.copy()
    dep_river = 0.0
    dep_lake = 0.0
    exported = 0.0
    playa = 0.0
    last = order.size - 1
    while last >= 0 and order[last] < 0:
        last -= 1
    for a in range(last, -1, -1):
        i = order[a]
        v = vol[i]
        r = rec[i]
        lab = lake_lbl[i]
        if not mutable[i]:
            exported += v
            continue
        if lab > 0:
            if is_outlet[i]:
                cells = lake_cells[lake_ptr[lab - 1] : lake_ptr[lab]]
                left = _fill_lake(hflat, cells, lake_level[lab - 1], v)
                dep_lake += v - left
                if terminal_lake[lab - 1] or r < 0:
                    if left > 0.0:  # closed basin over-full: aggrade the whole floor evenly
                        add = left / cells.size
                        for j in range(cells.size):
                            hflat[cells[j]] += add
                        playa += left
                    continue
                v = left
            if r >= 0 and routed[r]:
                vol[r] += v
            else:
                exported += v
            continue
        if r < 0 or not routed[r]:
            exported += v
            continue
        qi = q[i]
        # D dt = G p Qs dt / Q with Qs dt = v * area (m3): thickness in m, v is m x cells
        dd = g_coef * p_m_yr * v * area_m2 / qi if qi > 0.0 else v
        if dd > v:
            dd = v
        # an alluvial cell cannot build above the channel that feeds it: stay below the lowest donor
        room = min_donor[i] - hflat[i] - 1e-3
        if dd > room:
            dd = room if room > 0.0 else 0.0
        if dd > 0.0:
            hflat[i] += dd
            dep_river += dd
        vol[r] += v - dd
    return dep_river, dep_lake, exported, playa


@numba.njit(parallel=True, cache=True)
def _active_mask(
    mutable: np.ndarray,
    age: np.ndarray,
    t_end: float,
    t_yr: float,
    out: np.ndarray,
) -> None:
    """out = mutable & (t + dt > t_yr - age), with t_end = t + dt."""
    m = mutable.reshape(-1)
    a = age.reshape(-1)
    o = out.reshape(-1)
    for i in numba.prange(m.size):  # type: ignore[no-untyped-call,attr-defined]
        o[i] = m[i] and (t_end > t_yr - a[i])


@numba.njit(parallel=True, cache=True)
def _apply_incision(
    h: np.ndarray,
    hf: np.ndarray,
    lake: np.ndarray,
    src: np.ndarray,
) -> None:
    """h_new = where(lake, h, minimum(h, hf)); src = h - h_new; h <- h_new (in place)."""
    hh = h.reshape(-1)
    f = hf.reshape(-1)
    lk = lake.reshape(-1)
    s = src.reshape(-1)
    for i in numba.prange(hh.size):  # type: ignore[no-untyped-call,attr-defined]
        new = hh[i] if lk[i] else min(hh[i], f[i])
        s[i] = hh[i] - new
        hh[i] = new


@numba.njit(cache=True)
def _min_donor(
    hflat: np.ndarray,
    rec: np.ndarray,
) -> np.ndarray:
    """Lowest donor height of every cell (-inf without donors), np.minimum.at over donors."""
    n = hflat.size
    md = np.full(n, np.inf)
    for i in range(n):
        r = rec[i]
        if r >= 0 and hflat[i] < md[r]:
            md[r] = hflat[i]
    for i in range(n):
        if md[i] == np.inf:
            md[i] = -np.inf
    return md


@numba.njit(parallel=True, cache=True)
def _apply_anchor(
    h: np.ndarray,
    u_in: np.ndarray,
    mutable: np.ndarray,
    active: np.ndarray,
    two_sided: np.ndarray,
    use_two_sided: bool,
    z_floor: np.ndarray,
    uc: np.ndarray,
    withheld: np.ndarray,
) -> None:
    """The one-sided anchor step of the solver, fused.

    u = where(mutable & active, u_in, 0); u = where(two_sided, u, max(u, 0))
    (or max(u, 0) without a mask);
    u_c = where(mutable, max(u, min(z_floor, 1) - h), 0); withheld = u_c - u; h += u_c.
    """
    hh = h.reshape(-1)
    uf = u_in.reshape(-1)
    mu = mutable.reshape(-1)
    ac = active.reshape(-1)
    ts = two_sided.reshape(-1)
    zf = z_floor.reshape(-1)
    o = uc.reshape(-1)
    w = withheld.reshape(-1)
    for i in numba.prange(hh.size):  # type: ignore[no-untyped-call,attr-defined]
        u = uf[i] if (mu[i] and ac[i]) else 0.0
        if not (use_two_sided and ts[i]):
            u = max(u, 0.0)
        c = max(u, min(zf[i], 1.0) - hh[i]) if mu[i] else 0.0
        o[i] = c
        w[i] = c - u
        hh[i] = hh[i] + c


@numba.njit(parallel=True, cache=True)
def _apply_anchor_two(
    h: np.ndarray,
    u_in: np.ndarray,
    mutable: np.ndarray,
    active: np.ndarray,
    z_floor: np.ndarray,
    uc: np.ndarray,
    withheld: np.ndarray,
) -> None:
    """Two-sided anchor (no clipping of u at zero), same coastline guard."""
    hh = h.reshape(-1)
    uf = u_in.reshape(-1)
    mu = mutable.reshape(-1)
    ac = active.reshape(-1)
    zf = z_floor.reshape(-1)
    o = uc.reshape(-1)
    w = withheld.reshape(-1)
    for i in numba.prange(hh.size):  # type: ignore[no-untyped-call,attr-defined]
        u = uf[i] if (mu[i] and ac[i]) else 0.0
        c = max(u, min(zf[i], 1.0) - hh[i]) if mu[i] else 0.0
        o[i] = c
        w[i] = c - u
        hh[i] = hh[i] + c


@numba.njit(cache=True)
def _lake_lists(
    lf: np.ndarray,
    idx: np.ndarray,
    hflat: np.ndarray,
    filled_flat: np.ndarray,
    nl: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Members of each lake sorted by ground height (stable), segment pointers and levels.

    Equals cells = idx[lexsort((h[idx], lf[idx]))], ptr = cumulative member counts, and
    level = maximum.at(zeros, lf[idx] - 1, filled[idx]).
    """
    counts = np.zeros(nl + 1, np.int64)
    for i in idx:
        counts[lf[i]] += 1
    ptr = np.zeros(nl + 1, np.int64)
    for lk in range(1, nl + 1):
        ptr[lk] = ptr[lk - 1] + counts[lk]
    pos = ptr[:-1].copy()
    cells = np.empty(idx.size, np.int64)
    level = np.zeros(nl)
    for i in idx:  # bucket in idx order (stable)
        lk = lf[i] - 1
        cells[pos[lk]] = i
        pos[lk] += 1
        if filled_flat[i] > level[lk]:
            level[lk] = filled_flat[i]
    for lk in range(nl):
        a, b = ptr[lk], ptr[lk + 1]
        if b - a > 1:
            seg = cells[a:b].copy()
            hv = np.empty(b - a)
            for k in range(b - a):
                hv[k] = hflat[seg[k]]
            o = np.argsort(hv, kind="mergesort")
            for k in range(b - a):
                cells[a + k] = seg[o[k]]
    return cells, ptr, level


@numba.njit(parallel=True, cache=True)
def _terminal_cells(
    lbl: np.ndarray,
    term_lake: np.ndarray,
    out: np.ndarray,
) -> None:
    """out = term_lake[max(lbl, 1) - 1] & (lbl > 0)."""
    lf = lbl.reshape(-1)
    o = out.reshape(-1)
    for i in numba.prange(lf.size):  # type: ignore[no-untyped-call,attr-defined]
        o[i] = lf[i] > 0 and term_lake[lf[i] - 1]


@numba.njit(parallel=True, cache=True)
def _block_mean(
    x: np.ndarray,
    f: int,
) -> np.ndarray:
    nrow, ncol = x.shape
    hc, wc = -(-nrow // f), -(-ncol // f)
    out = np.zeros((hc, wc))
    inv = 1.0 / (f * f)
    for bi in numba.prange(hc):  # type: ignore[no-untyped-call,attr-defined]
        for i in range(bi * f, min((bi + 1) * f, nrow)):
            for j in range(ncol):
                out[bi, j // f] += x[i, j]
        for bj in range(wc):
            out[bi, bj] *= inv
    return out


@numba.njit(parallel=True, cache=True)
def _upsample(
    c: np.ndarray,
    f: int,
    nrow: int,
    ncol: int,
) -> np.ndarray:
    hc, wc = c.shape
    out = np.empty((nrow, ncol))
    for i in numba.prange(nrow):  # type: ignore[no-untyped-call,attr-defined]
        y = (i + 0.5) / f - 0.5
        y = min(max(y, 0.0), hc - 1.0)
        y0 = min(int(np.floor(y)), hc - 2) if hc > 1 else 0
        ty = y - y0
        y1 = min(y0 + 1, hc - 1)
        for j in range(ncol):
            x = (j + 0.5) / f - 0.5
            x = min(max(x, 0.0), wc - 1.0)
            x0 = min(int(np.floor(x)), wc - 2) if wc > 1 else 0
            tx = x - x0
            x1 = min(x0 + 1, wc - 1)
            out[i, j] = (1 - ty) * ((1 - tx) * c[y0, x0] + tx * c[y0, x1]) + ty * (
                (1 - tx) * c[y1, x0] + tx * c[y1, x1]
            )
    return out
