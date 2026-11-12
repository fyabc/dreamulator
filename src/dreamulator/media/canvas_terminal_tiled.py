"""Out-of-core S2 terminal lakes: the lake-graph cascade and the equilibrium rewrite, per chunk.

Step 3 of the out-of-core rivers stage (steps 1-2: :mod:`canvas_flow_tiled`,
:mod:`canvas_lakes_tiled`).  It reproduces the canvas call of
:func:`dreamulator.map.prog_erosion.terminal_equilibrium_routing` (``h`` = the installed ground,
``keep_rewritten_h=False``) from per-chunk files plus small per-lake tables:

1. **First-touch inflow**: a tiled accumulation of the runoff weight with every lake cell cut,
   summed over the cells whose receiver is a lake cell.
2. **Lake graph**: a lake's exits are its cells whose receiver leaves the component; the lake it
   drains into is the first lake the receiver chain reaches.  "First lake reached" is resolved
   per chunk and joined across chunk borders by the same link machinery as the accumulation.
   ``downstream_of`` is set by the lowest-index exit that reaches another lake, as in memory.
3. **Cascade** (Kahn order, totals, verdicts): small, run as in memory.
4. **Equilibrium rewrite**: a terminal lake keeps its ``k`` lowest cells by ground height, ties by
   cell index (per-lake height histograms, then the tied cells' indices).
5. **Kept water, render mask, routing cut, fringe descent, records, depleted weight**.

Lake surface sums (evaporation, precipitation, first-touch inflow) are float64 sums in chunk
order, so they match the whole-canvas sums to round-off, not bit for bit.  Files under
``<work>/flow/``: ``dir_cut``, ``acc_cut``, ``lake_term``, ``term_water``, ``land2``,
``lakes_render``, ``dir_route``, ``w_depleted``, ``desc`` (int64 descent targets, -1 none).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numba
import numpy as np

from dreamulator.media import canvas_flow_tiled as cft
from dreamulator.media.canvas_flow_tiled import (
    _DX,
    _DY,
    ChunkLayout,
    _ctx_of,
    _default_workers,
    _pool_map,
    _ring_index,
    _store_of,
    drop_kinds,
    halo,
    load_chunk,
    save_chunk,
    tiled_accumulation,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from dreamulator.media.canvas_lakes_tiled import Components
    from dreamulator.media.canvas_pipeline import CanvasStore


@dataclass
class TerminalResult:
    """Per-lake tables of the cascade (index = lake id, 0 unused) and the summary."""

    n: int
    external: np.ndarray
    total: np.ndarray
    demand: np.ndarray
    downstream_of: np.ndarray
    topo: list[int]
    is_term: np.ndarray
    n_exits: np.ndarray
    kept_counts: np.ndarray
    stats: dict[str, int]
    #: one row per lake exit, in cell-index order: the exit cell, its lake, the cell its
    #: receiver lands on and the lake that receiver chain first reaches (0 = sea or frame).
    exit_cell: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int64))
    exit_lake: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int64))
    exit_target: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int64))
    exit_reach: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int64))
    lake_records: list[dict[str, object]] = field(default_factory=list)


@dataclass
class _Climate:
    precip: np.ndarray
    temp: np.ndarray
    open_water: np.ndarray | None
    block: int
    width: int  # the chunk bounding box width (pixels)
    rbar: float


# ---------------------------------------------------------------------------
# per-chunk passes
# ---------------------------------------------------------------------------


def _cut_lakes(key: tuple[int, int]) -> None:
    ctx = cft._CTX
    assert ctx is not None
    st = _store_of(ctx)
    code = load_chunk(st, "dir", key).copy()
    code[load_chunk(st, "lbl_lakes0", key) > 0] = 255
    save_chunk(st, "dir_cut", key, code)


@numba.njit(cache=True)
def _reach_local(
    order: np.ndarray, rec: np.ndarray, out: np.ndarray, lbl: np.ndarray
) -> np.ndarray:  # pragma: no cover - numba
    """First lake reached from each cell inside the chunk: label > 0, 0 = none, -(x+1) = leaves
    the chunk through cell ``x``'s outgoing link (unresolved)."""
    res = np.zeros(rec.size, dtype=np.int64)
    for a in range(order.size):  # downstream first
        i = order[a]
        if lbl[i] > 0:
            res[i] = lbl[i]
        elif out[i] >= 0:
            res[i] = -(i + 1)
        elif rec[i] >= 0:
            res[i] = res[rec[i]]
    return res


def _climate_values(clim: _Climate, gidx: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Lake-surface evaporation and precipitation (mm/yr) at global bbox cells."""
    from dreamulator.engine.climate_physics import potential_evapotranspiration_hamon
    from dreamulator.map.prog_erosion import LAKE_EVAPORATION_FACTOR, climate_cell_index

    ci = climate_cell_index(gidx, clim.width, clim.block, clim.precip.shape[1])
    p = np.nan_to_num(clim.precip.reshape(-1)[ci])
    if clim.open_water is not None:
        e = np.nan_to_num(clim.open_water.reshape(-1)[ci])
    else:
        t = np.nan_to_num(clim.temp.reshape(-1)[ci])
        t12 = np.repeat(t.reshape(-1, 1), 12, axis=1)
        e = LAKE_EVAPORATION_FACTOR * np.asarray(
            potential_evapotranspiration_hamon(t12, 365.25 / 12)
        )
    return e.astype(np.float64), p.astype(np.float64)


def _lake_info(key: tuple[int, int]) -> tuple[Any, ...]:
    """Everything one chunk contributes to the lake graph and the balances."""
    ctx = cft._CTX
    assert ctx is not None
    st = _store_of(ctx)
    layout = ChunkLayout(ctx.tile, ctx.keys)
    t = ctx.tile
    w_bbox = layout.shape[1]
    keys = layout.keyset
    assert ctx.extra is not None
    clim: _Climate = ctx.extra["climate"]
    lbl_h = halo(st, layout, "lbl_lakes0", key, 0, dtype=np.int32)
    lbl = lbl_h[1:-1, 1:-1].ravel()
    code = load_chunk(st, "dir", key)
    order, rec, out = cft._local(st, key)
    res = _reach_local(order, rec, out, lbl.astype(np.int64))
    dem_h = halo(st, layout, "dem", key, np.nan, dtype=np.float64)  # f32 on disk, exact
    rr, cc = np.divmod(np.arange(t * t), t)
    g_row, g_col = rr + key[0] * t, cc + key[1] * t
    gidx = g_row * w_bbox + g_col
    has = code.ravel() != 255
    k = np.where(has, code.ravel(), 0).astype(np.int64)
    tr = rr + _DY[k]  # receiver row/col in the halo frame minus one
    tc = cc + _DX[k]
    t_lbl = np.where(has, lbl_h[tr + 1, tc + 1], 0)
    t_dem = np.where(has, dem_h[tr + 1, tc + 1], np.nan)
    t_gidx = np.where(has, (g_row + _DY[k]) * w_bbox + (g_col + _DX[k]), -1)
    # 1. first-touch inflow donors: non-lake cells draining into a lake cell
    donors = has & (lbl == 0) & (t_lbl > 0)
    acc_cut = load_chunk(st, "acc_cut", key).ravel()
    ext_lab = t_lbl[donors].astype(np.int64)
    ext_val = acc_cut[donors].astype(np.float64)
    # 2. lake exits: lake cells whose receiver leaves the component
    ex = np.flatnonzero(has & (lbl > 0) & (t_lbl != lbl))
    inside = (tr[ex] >= 0) & (tr[ex] < t) & (tc[ex] >= 0) & (tc[ex] < t)
    reach = np.zeros(ex.size, dtype=np.int64)
    ref_key: list[tuple[int, int] | None] = [None] * ex.size
    ref_pos = np.full(ex.size, -1, dtype=np.int64)
    for j, e in enumerate(ex.tolist()):
        tl = int(t_lbl[e])
        if tl > 0:
            reach[j] = tl
        elif inside[j]:
            reach[j] = int(res[int(tr[e]) * t + int(tc[e])])  # label, 0 or a local link
        else:
            gr, gc = int(g_row[e] + _DY[k[e]]), int(g_col[e] + _DX[k[e]])
            nk = (gr // t, gc // t)
            if nk in keys:
                ref_key[j] = nk
                ref_pos[j] = (gr % t) * t + gc % t
    # 3. link machinery: ring values and outgoing links of this chunk
    ring = _ring_index(t)
    ring_res = res[ring]
    out_cells = np.flatnonzero(out >= 0)
    link_tk: list[tuple[int, int] | None] = []
    link_ti = np.full(out_cells.size, -1, dtype=np.int64)
    for j, x in enumerate(out_cells.tolist()):
        kk = int(out[x])
        gr, gc = int(g_row[x] + _DY[kk]), int(g_col[x] + _DX[kk])
        nk2 = (gr // t, gc // t) if gr >= 0 and gc >= 0 else None
        if nk2 is None or nk2 not in keys:
            link_tk.append(None)
        else:
            link_tk.append(nk2)
            link_ti[j] = (gr % t) * t + gc % t
    # 4. surface sums
    cells = np.flatnonzero(lbl > 0)
    e_v, p_v = _climate_values(clim, gidx[cells])
    sum_lab = lbl[cells].astype(np.int64)
    return (
        key,
        ext_lab,
        ext_val,
        lbl[ex].astype(np.int64),
        gidx[ex],
        ex,
        t_gidx[ex],
        t_dem[ex],
        reach,
        ref_key,
        ref_pos,
        ring_res,
        out_cells,
        link_tk,
        link_ti,
        sum_lab,
        e_v,
        p_v,
    )


def _dem_chunk(key: tuple[int, int]) -> None:
    from dreamulator.media.canvas_lakes_tiled import _raw

    ctx = cft._CTX
    assert ctx is not None
    # integer metres (int16 chunk + int16 increment): float32 holds them exactly
    save_chunk(_store_of(ctx), "dem", key, _raw(ctx, key).astype(np.float32))


def _height_hist(task: tuple[Any, ...]) -> tuple[Any, ...]:
    """(label, height, count) of the terminal lakes' cells in one chunk."""
    key, term_ids = task
    ctx = cft._CTX
    assert ctx is not None
    st = _store_of(ctx)
    lbl = load_chunk(st, "lbl_lakes0", key).ravel()
    sel = np.flatnonzero(np.isin(lbl, term_ids)) if len(term_ids) else np.zeros(0, np.int64)
    if sel.size == 0:
        z = np.zeros(0)
        return key, z.astype(np.int64), z, z.astype(np.int64)
    dem = load_chunk(st, "dem", key).ravel()[sel].astype(np.float64)
    lab = lbl[sel].astype(np.int64)
    pairs, counts = np.unique(
        np.stack([lab, dem.view(np.int64)], axis=1), axis=0, return_counts=True
    )
    return key, pairs[:, 0], pairs[:, 1].view(np.float64), counts


def _tied_cells(task: tuple[Any, ...]) -> tuple[Any, ...]:
    """Global indices of terminal cells at their lake's threshold height (ties by index)."""
    key, thr_lab, thr_h = task
    ctx = cft._CTX
    assert ctx is not None
    st = _store_of(ctx)
    t = ctx.tile
    w_bbox = ChunkLayout(ctx.tile, ctx.keys).shape[1]
    lbl = load_chunk(st, "lbl_lakes0", key).ravel().astype(np.int64)
    if not len(thr_lab):
        return key, np.zeros(0, np.int64), np.zeros(0, np.int64)
    lut = np.full(int(max(int(thr_lab.max()), int(lbl.max()))) + 1, np.nan)
    lut[thr_lab] = thr_h
    dem = load_chunk(st, "dem", key).ravel().astype(np.float64)
    hit = np.flatnonzero((lbl > 0) & (dem == lut[lbl]))
    rr, cc = np.divmod(hit, t)
    g = (rr + key[0] * t) * w_bbox + cc + key[1] * t
    return key, lbl[hit], g


def _mark(task: tuple[Any, ...]) -> tuple[Any, ...]:
    """Terminal footprints, kept water (before the MMU/width gate), land, water stats."""
    key, term_ids, thr_lab, thr_h, cut_g = task
    ctx = cft._CTX
    assert ctx is not None
    st = _store_of(ctx)
    t = ctx.tile
    w_bbox = ChunkLayout(ctx.tile, ctx.keys).shape[1]
    lbl = load_chunk(st, "lbl_lakes0", key).ravel().astype(np.int64)
    n_lut = int(max(int(lbl.max()), int(thr_lab.max()) if len(thr_lab) else 0)) + 1
    term = np.isin(lbl, term_ids) if len(term_ids) else np.zeros(lbl.size, bool)
    h_lut = np.full(n_lut, -np.inf)
    g_lut = np.full(n_lut, -1, dtype=np.int64)
    if len(thr_lab):
        h_lut[thr_lab] = thr_h
        g_lut[thr_lab] = cut_g
    dem = load_chunk(st, "dem", key).ravel().astype(np.float64)
    rr, cc = np.divmod(np.arange(t * t), t)
    g_row, g_col = rr + key[0] * t, cc + key[1] * t
    gidx = g_row * w_bbox + g_col
    hl = h_lut[lbl]
    water = term & ((dem < hl) | ((dem == hl) & (gidx <= g_lut[lbl])))
    land = load_chunk(st, "land", key).ravel().astype(bool).copy()
    land[water] = False
    land[term & ~water] = True
    save_chunk(st, "lake_term", key, term.reshape(t, t).astype(np.uint8))
    save_chunk(st, "term_water", key, water.reshape(t, t).astype(np.uint8))
    save_chunk(st, "land2", key, land.reshape(t, t).astype(np.uint8))
    wl = lbl[water]
    return key, wl, g_row[water], g_col[water]


def _render(task: tuple[Any, ...]) -> None:
    key, kept_ids = task
    ctx = cft._CTX
    assert ctx is not None
    st = _store_of(ctx)
    lbl = load_chunk(st, "lbl_lakes0", key)
    term = load_chunk(st, "lake_term", key).astype(bool)
    water = load_chunk(st, "term_water", key).astype(bool)
    lakes = load_chunk(st, "lakes0", key).astype(bool)
    kept = water & (np.isin(lbl, kept_ids) if len(kept_ids) else False)
    save_chunk(st, "lakes_render", key, ((lakes & ~term) | kept).astype(np.uint8))
    code = load_chunk(st, "dir", key).copy()
    code[term] = 255
    save_chunk(st, "dir_route", key, code)


def _deplete(task: tuple[Any, ...]) -> None:
    key, cells, amount = task
    ctx = cft._CTX
    assert ctx is not None
    st = _store_of(ctx)
    w = load_chunk(st, "w_runoff", key).copy()
    if len(cells):
        flat = w.reshape(-1)
        idx = np.asarray(cells, np.int64)
        # as in memory: float32 weight minus a float64 amount, rounded back to float32
        flat[idx] = (flat[idx].astype(np.float64) - np.asarray(amount, np.float64)).astype(
            np.float32
        )
    save_chunk(st, "w_depleted", key, w)


# ---------------------------------------------------------------------------
# fringe descent (sequential per terminal lake, in label order)
# ---------------------------------------------------------------------------


@numba.njit(cache=True)
def _fringe_kernel(
    h: np.ndarray,
    gid: np.ndarray,
    mine: np.ndarray,
    water: np.ndarray,
    resolved_out: np.ndarray,
    fringe_order: np.ndarray,
) -> np.ndarray:  # pragma: no cover - numba
    """Descent targets (global index) on a local frame: water self-loops; fringe cells, lowest
    first, point at their lowest resolved 8-neighbour (key: height, distance, global index)."""
    nr, nc = h.shape
    desc = np.full((nr, nc), -1, dtype=np.int64)
    for r in range(nr):
        for c in range(nc):
            if resolved_out[r, c]:
                desc[r, c] = gid[r, c]  # any value >= 0 marks "resolved"
            elif mine[r, c] and water[r, c]:
                desc[r, c] = gid[r, c]
    for a in range(fringe_order.size):
        cell = fringe_order[a]
        r = cell // nc
        c = cell % nc
        best = -1
        bh = np.inf
        bd = np.inf
        bg = -1
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dy == 0 and dx == 0:
                    continue
                rr = r + dy
                cc = c + dx
                if rr < 0 or rr >= nr or cc < 0 or cc >= nc:
                    continue
                if desc[rr, cc] < 0:
                    continue
                hv = h[rr, cc]
                dv = (dy * dy + dx * dx) ** 0.5
                gv = gid[rr, cc]
                if hv < bh or (hv == bh and (dv < bd or (dv == bd and gv < bg))):
                    bh, bd, bg = hv, dv, gv
                    best = gv
        desc[r, c] = best
    return desc


def _fringe_descent(
    store: CanvasStore,
    layout: ChunkLayout,
    terminal_kept: list[int],
    comps: Components,
    log: Callable[[str], None] | None,
) -> None:
    """Write ``flow/desc``: pass-through lakes self-loop; kept terminal lakes walk their fringe."""
    t = layout.tile
    w_bbox = layout.shape[1]
    keys = layout.keyset
    cache: dict[tuple[int, int], dict[str, np.ndarray]] = {}

    def get(key: tuple[int, int]) -> dict[str, np.ndarray]:
        if key not in cache:
            if len(cache) > 96:
                old = next(iter(cache))
                save_chunk(store, "desc", old, cache[old]["desc"])
                del cache[old]
            cache[key] = {
                "lbl": load_chunk(store, "lbl_lakes0", key),
                "render": load_chunk(store, "lakes_render", key).astype(bool),
                "dem": load_chunk(store, "dem", key).astype(np.float64),
                "desc": load_chunk(store, "desc", key).copy(),
            }
        return cache[key]

    for lab in terminal_kept:
        r0, r1 = int(comps.rmin[lab]) - 1, int(comps.rmax[lab]) + 2
        c0, c1 = int(comps.cmin[lab]) - 1, int(comps.cmax[lab]) + 2
        nr, nc = r1 - r0, c1 - c0
        h = np.full((nr, nc), np.inf)
        gid = np.full((nr, nc), -1, dtype=np.int64)
        lbl = np.zeros((nr, nc), dtype=np.int64)
        render = np.zeros((nr, nc), bool)
        dsc = np.full((nr, nc), -1, dtype=np.int64)
        for ci in range(max(r0, 0) // t, (r1 - 1) // t + 1):
            for cj in range(max(c0, 0) // t, (c1 - 1) // t + 1):
                if (ci, cj) not in keys:
                    continue
                ch = get((ci, cj))
                a0, a1 = max(r0, ci * t), min(r1, (ci + 1) * t)
                b0, b1 = max(c0, cj * t), min(c1, (cj + 1) * t)
                if a0 >= a1 or b0 >= b1:
                    continue
                src = np.s_[a0 - ci * t : a1 - ci * t, b0 - cj * t : b1 - cj * t]
                dst = np.s_[a0 - r0 : a1 - r0, b0 - c0 : b1 - c0]
                h[dst] = ch["dem"][src]
                lbl[dst] = ch["lbl"][src]
                render[dst] = ch["render"][src]
                dsc[dst] = ch["desc"][src]
                gr, gc = np.mgrid[a0:a1, b0:b1]
                gid[dst] = gr * w_bbox + gc
        mine = lbl == lab
        resolved_out = (~mine) & (lbl > 0) & (lbl < lab) & (dsc >= 0)
        fr = np.flatnonzero((mine & ~render).ravel())
        fr = fr[np.argsort(gid.ravel()[fr], kind="stable")]  # ascending cell index
        fr = fr[np.argsort(h.ravel()[fr], kind="stable")]  # then by height, stable
        out = _fringe_kernel(h, gid, mine, render, resolved_out, fr)
        for ci in range(max(r0, 0) // t, (r1 - 1) // t + 1):
            for cj in range(max(c0, 0) // t, (c1 - 1) // t + 1):
                if (ci, cj) not in keys:
                    continue
                ch = get((ci, cj))
                a0, a1 = max(r0, ci * t), min(r1, (ci + 1) * t)
                b0, b1 = max(c0, cj * t), min(c1, (cj + 1) * t)
                if a0 >= a1 or b0 >= b1:
                    continue
                src = np.s_[a0 - ci * t : a1 - ci * t, b0 - cj * t : b1 - cj * t]
                dst = np.s_[a0 - r0 : a1 - r0, b0 - c0 : b1 - c0]
                m = mine[dst]
                ch["desc"][src][m] = out[dst][m]
    for key, ch in cache.items():
        save_chunk(store, "desc", key, ch["desc"])
    if log is not None:
        log(f"[terminal] fringe descent for {len(terminal_kept)} kept terminal lakes")


def _desc_init(key: tuple[int, int]) -> None:
    """Descent of pass-through lakes (every cell self-loops); -1 elsewhere."""
    ctx = cft._CTX
    assert ctx is not None
    st = _store_of(ctx)
    t = ctx.tile
    w_bbox = ChunkLayout(ctx.tile, ctx.keys).shape[1]
    lbl = load_chunk(st, "lbl_lakes0", key)
    render = load_chunk(st, "lakes_render", key).astype(bool)
    term = load_chunk(st, "lake_term", key).astype(bool)
    rr, cc = np.mgrid[0:t, 0:t]
    gid = (rr + key[0] * t) * w_bbox + cc + key[1] * t
    desc = np.where((lbl > 0) & ~term & render, gid, -1).astype(np.int64)
    save_chunk(st, "desc", key, desc)


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------


def tiled_terminal_routing(
    store: CanvasStore,
    comps: Components,
    *,
    precip_mm: np.ndarray,
    temp_c: np.ndarray,
    open_water_mm: np.ndarray | None,
    runoff_land_mean_mm: float,
    mmu_cells: int,
    km_per_px: float,
    climate_block: int,
    workers: int | None = None,
    log: Callable[[str], None] | None = None,
) -> TerminalResult:
    """The canvas ``terminal_equilibrium_routing`` on chunk files (see the module docstring)."""
    from dreamulator.map.prog_erosion import LAKE_MIN_WIDTH_KM, lake_topological_order

    layout = ChunkLayout.of(store)
    t = layout.tile
    ctx = _ctx_of(store)
    ctx.increments = store.increments
    n_work = _default_workers(t) if workers is None else max(1, workers)
    keys = list(layout.keys)
    n = comps.count
    stats = {"terminal": 0, "dry_playas": 0, "shrunk": 0}
    empty = TerminalResult(
        n=n,
        external=np.zeros(n + 1),
        total=np.zeros(n + 1),
        demand=np.zeros(n + 1),
        downstream_of=np.zeros(n + 1, dtype=np.int64),
        topo=[],
        is_term=np.zeros(n + 1, bool),
        n_exits=np.zeros(n + 1, dtype=np.int64),
        kept_counts=np.zeros(n + 1, dtype=np.int64),
        stats=stats,
    )
    _pool_map(_dem_chunk, keys, ctx, n_work)
    if runoff_land_mean_mm <= 0.0 or n == 0:
        _no_verdicts(store, ctx, keys, n_work)
        return empty
    ctx.extra = {
        "climate": _Climate(
            precip=np.ascontiguousarray(precip_mm),
            temp=np.ascontiguousarray(temp_c),
            open_water=None if open_water_mm is None else np.ascontiguousarray(open_water_mm),
            block=climate_block,
            width=layout.shape[1],
            rbar=runoff_land_mean_mm,
        )
    }
    # 1. first-touch accumulation with the lakes cut
    _pool_map(_cut_lakes, keys, ctx, n_work)
    tiled_accumulation(store, "w_runoff", dir_kind="dir_cut", out_kind="acc_cut", float64=True,
                       workers=n_work)  # fmt: skip
    info = _pool_map(_lake_info, keys, ctx, n_work)
    # 2. resolve "first lake reached" across chunk borders
    ring = _ring_index(t)
    ring_pos = {int(c): p for p, c in enumerate(ring)}
    ring_res = {r[0]: r[11] for r in info}
    link_target: dict[tuple[tuple[int, int], int], tuple[tuple[int, int] | None, int]] = {}
    for r in info:
        for x, tk, ti in zip(r[12].tolist(), r[13], r[14].tolist(), strict=True):
            link_target[(r[0], int(x))] = (tk, int(ti))
    memo: dict[tuple[tuple[int, int], int], int] = {}

    def resolve(node: tuple[tuple[int, int], int]) -> int:
        path = []
        cur = node
        while True:
            if cur in memo:
                val = memo[cur]
                break
            path.append(cur)
            tk, ti = link_target.get(cur, (None, -1))
            if tk is None:
                val = 0
                break
            v = int(ring_res[tk][ring_pos[ti]])
            if v >= 0:
                val = v
                break
            cur = (tk, -v - 1)
        for p in path:
            memo[p] = val
        return val

    external = np.zeros(n + 1)
    evap = np.zeros(n + 1)
    psum = np.zeros(n + 1)
    # (global index, lake, chunk, local index, receiver global index, receiver height, lake reached)
    exits: list[tuple[int, int, tuple[int, int], int, int, float, int]] = []
    for r in info:
        key = r[0]
        np.add.at(external, r[1], r[2])
        np.add.at(evap, r[15], r[16])
        np.add.at(psum, r[15], r[17])
        for j in range(r[3].size):
            reach = int(r[8][j])
            if reach < 0:
                reach = resolve((key, -reach - 1))
            elif r[9][j] is not None:
                v = int(ring_res[r[9][j]][ring_pos[int(r[10][j])]])
                reach = v if v >= 0 else resolve((r[9][j], -v - 1))
            exits.append((int(r[4][j]), int(r[3][j]), key, int(r[5][j]), int(r[6][j]),
                          float(r[7][j]), reach))  # fmt: skip
    exits.sort(key=lambda e: e[0])
    downstream_of = np.zeros(n + 1, dtype=np.int64)
    n_exits = np.zeros(n + 1, dtype=np.int64)
    for _g, lab, _k, _loc, _tg, _th, reach in exits:
        n_exits[lab] += 1
        if downstream_of[lab] == 0 and reach != lab and reach != 0:
            downstream_of[lab] = reach
    spill_h = np.full(n + 1, np.inf)
    for _g, lab, _k, _loc, _tg, th, _reach in exits:
        spill_h[lab] = min(spill_h[lab], th)
    topo = lake_topological_order(downstream_of, spill_h)
    demand = (evap - psum) / runoff_land_mean_mm
    total = external.copy()
    is_term = np.zeros(n + 1, dtype=bool)
    for a in topo:
        is_term[a] = demand[a] > 0.0 and total[a] < demand[a]
        if is_term[a]:
            continue
        b = int(downstream_of[a])
        if b > 0:
            total[b] += total[a] - demand[a]
    term_ids = np.flatnonzero(is_term)
    # 4. equilibrium: k lowest cells per terminal lake, ties by index
    k_of = np.zeros(n + 1, dtype=np.int64)
    for a in term_ids.tolist():
        stats["terminal"] += 1
        if demand[a] <= 0.0:
            continue
        n_cells = int(comps.size[a])
        k = min(int(math.ceil(total[a] / demand[a] * n_cells)), n_cells)
        if k < mmu_cells:
            k = 1
            stats["dry_playas"] += 1
        else:
            stats["shrunk"] += 1
        k_of[a] = k
    hist = _pool_map(_height_hist, [(kk, term_ids) for kk in keys], ctx, n_work)
    per: dict[int, dict[float, int]] = {}
    for _key, labs, hs, counts in hist:
        for lab, hv, cnt in zip(labs.tolist(), hs.tolist(), counts.tolist(), strict=True):
            d = per.setdefault(lab, {})
            d[hv] = d.get(hv, 0) + cnt
    thr_lab, thr_h, need = [], [], {}
    for a in term_ids.tolist():
        if k_of[a] <= 0:
            continue
        acc = 0
        for hv in sorted(per.get(a, {})):
            c = per[a][hv]
            if acc + c >= k_of[a]:
                thr_lab.append(a)
                thr_h.append(hv)
                need[a] = int(k_of[a] - acc)
                break
            acc += c
    thr_lab_a = np.asarray(thr_lab, dtype=np.int64)
    thr_h_a = np.asarray(thr_h, dtype=np.float64)
    tied = _pool_map(_tied_cells, [(kk, thr_lab_a, thr_h_a) for kk in keys], ctx, n_work)
    tie_g: dict[int, list[np.ndarray]] = {}
    for _key, labs, gs in tied:
        for lab in np.unique(labs).tolist():
            tie_g.setdefault(lab, []).append(gs[labs == lab])
    cut_g = np.array(
        [int(np.sort(np.concatenate(tie_g[a]))[need[a] - 1]) for a in thr_lab], dtype=np.int64
    )
    marks = _pool_map(
        _mark, [(kk, term_ids, thr_lab_a, thr_h_a, cut_g) for kk in keys], ctx, n_work
    )
    # 5. kept water (MMU and width over the water cells, per lake id)
    big = np.iinfo(np.int64).max
    cnt = np.zeros(n + 1, dtype=np.int64)
    rmin = np.full(n + 1, big)
    cmin = np.full(n + 1, big)
    rmax = np.full(n + 1, -1)
    cmax = np.full(n + 1, -1)
    for _key, wl, wr, wc in marks:
        np.add.at(cnt, wl, 1)
        np.minimum.at(rmin, wl, wr)
        np.maximum.at(rmax, wl, wr)
        np.minimum.at(cmin, wl, wc)
        np.maximum.at(cmax, wl, wc)
    min_px = LAKE_MIN_WIDTH_KM / max(km_per_px, 1e-9)
    extent = np.minimum(rmax - rmin + 1, cmax - cmin + 1)
    kept = (cnt >= max(mmu_cells, 1)) & (extent >= min_px)
    kept[0] = False
    kept_ids = np.flatnonzero(kept)
    kept_counts = np.where(kept, cnt, 0)
    _pool_map(_render, [(kk, kept_ids) for kk in keys], ctx, n_work)
    # fringe descent
    _pool_map(_desc_init, keys, ctx, n_work)
    terminal_kept = [int(a) for a in term_ids.tolist() if kept[a]]
    if term_ids.size:
        _fringe_descent(store, layout, terminal_kept, comps, log)
    # depletion at the exits of pass-through lakes
    dep: dict[tuple[int, int], tuple[list[int], list[float]]] = {kk: ([], []) for kk in keys}
    for _g, lab, key, loc, _tg, _th, _reach in exits:
        if is_term[lab] or demand[lab] == 0.0:
            continue
        dep[key][0].append(loc)
        dep[key][1].append(float(demand[lab] / n_exits[lab]))
    _pool_map(_deplete, [(kk, *dep[kk]) for kk in keys], ctx, n_work)
    # records
    w_bbox = layout.shape[1]
    first_spill: dict[int, tuple[float, int, int]] = {}
    for g, lab, _k, _loc, tg, th, _reach in exits:  # exits in index order: first minimum wins
        if lab not in first_spill or th < first_spill[lab][0]:
            first_spill[lab] = (th, g, tg)
    records: list[dict[str, object]] = []
    for a in range(1, n + 1):
        draw = int(comps.size[a])
        if draw == 0:
            continue
        spill_cell = spill_elev = None
        if a in first_spill:
            th, g, _tg = first_spill[a]
            spill_cell = [int(g // w_bbox), int(g % w_bbox)]
            spill_elev = round(float(th), 3)
        k_w = int(kept_counts[a])
        if is_term[a]:
            verdict = "dry_playa" if k_w == 0 else ("shrunk" if k_w < draw else "terminal")
        else:
            verdict = "passthrough"
        records.append(
            {
                "label": a,
                "verdict": verdict,
                "draw_cells": draw,
                "kept_water_cells": k_w,
                "spill_cell": spill_cell,
                "spill_elev_m": spill_elev,
                "downstream_label": int(downstream_of[a]),
                "inflow_mm": round(float(total[a]), 3),
                "demand_mm": round(float(demand[a]), 3),
            }
        )
    if log is not None:
        log(
            f"[terminal] {n} lakes: {int(is_term.sum())} terminal "
            f"(dry playas {stats['dry_playas']}, shrunk {stats['shrunk']})"
        )
    # The cut routing and its accumulation only served the first-touch inflow.
    drop_kinds(store, "dir_cut", "acc_cut")
    return TerminalResult(
        n=n,
        external=external,
        total=total,
        demand=demand,
        downstream_of=downstream_of,
        topo=topo,
        is_term=is_term,
        n_exits=n_exits,
        kept_counts=kept_counts,
        stats=stats,
        exit_cell=np.array([e[0] for e in exits], dtype=np.int64),
        exit_lake=np.array([e[1] for e in exits], dtype=np.int64),
        exit_target=np.array([e[4] for e in exits], dtype=np.int64),
        exit_reach=np.array([e[6] for e in exits], dtype=np.int64),
        lake_records=records,
    )


def _no_verdict_chunk(key: tuple[int, int]) -> None:
    ctx = cft._CTX
    assert ctx is not None
    st = _store_of(ctx)
    t = ctx.tile
    z = np.zeros((t, t), dtype=np.uint8)
    save_chunk(st, "lake_term", key, z)
    save_chunk(st, "term_water", key, z)
    save_chunk(st, "land2", key, load_chunk(st, "land", key))
    save_chunk(st, "lakes_render", key, load_chunk(st, "lakes0", key))
    save_chunk(st, "dir_route", key, load_chunk(st, "dir", key))
    save_chunk(st, "w_depleted", key, load_chunk(st, "w_runoff", key))
    save_chunk(st, "desc", key, np.full((t, t), -1, dtype=np.int64))


def _no_verdicts(store: CanvasStore, ctx: Any, keys: list[tuple[int, int]], n_work: int) -> None:
    """No water-balance basis: the geometry lakes stand, nothing is cut or depleted."""
    _pool_map(_no_verdict_chunk, keys, ctx, n_work)
