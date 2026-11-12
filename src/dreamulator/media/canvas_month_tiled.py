"""Out-of-core S2 monthly regime: the twenty-four monthly accumulations, per chunk.

Step 4 of the out-of-core rivers stage (steps 1-3: :mod:`canvas_flow_tiled`,
:mod:`canvas_lakes_tiled`, :mod:`canvas_terminal_tiled`).  It reproduces the canvas call of
:func:`dreamulator.map.prog_erosion.month_active_counts` on the routing step 3 leaves behind
(``flow/dir_route``, the terminal footprints cut by the annual verdict):

1. **Pass-through lakes**: the lakes the annual verdict did not make terminal.  Their cells are
   cut from the routing into ``flow/dir_month`` and their monthly surface demand
   (evaporation minus precipitation over the lake's cells) is summed chunk by chunk.
2. **Twelve inflow accumulations**: each month's runoff weight, zeroed on the lake cells, is
   accumulated on the cut routing; a lake's inflow for that month is the sum over its cells.
3. **The cascade** (:func:`dreamulator.map.prog_erosion.monthly_outflow_cascade`) turns inflow
   minus demand into the outflow of the periodic steady state, upstream lakes first.
4. **Twelve counting accumulations**: the same weights plus each lake's outflow injected at its
   exits' receivers; a cell's count is the number of months its accumulation clears the active
   rule.  The result is ``flow/month_active`` (uint8, 0-12).

The monthly weights are rebuilt in the workers from the coarse monthly pack, so only one
accumulation's chunk files (``flow/w_month`` and ``flow/acc_month``, both reused month by
month and deleted at the end) live on disk at a time.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np

from dreamulator.media import canvas_flow_tiled as cft
from dreamulator.media.canvas_flow_tiled import (
    ChunkLayout,
    _ctx_of,
    _default_workers,
    _pool_map,
    _store_of,
    drop_kinds,
    load_chunk,
    save_chunk,
    tiled_accumulation,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from dreamulator.media.canvas_lakes_tiled import Components
    from dreamulator.media.canvas_pipeline import CanvasStore
    from dreamulator.media.canvas_terminal_tiled import TerminalResult

#: Chunk kinds this stage writes.  The two working kinds are reused by every month.
WEIGHT_KIND = "w_month"
ACC_KIND = "acc_month"
DIR_KIND = "dir_month"
OUT_KIND = "month_active"


@dataclass
class MonthResult:
    """Summary of the monthly pass (``stats`` as in :func:`lake_monthly_outflow`)."""

    months: int
    pass_through: int
    stats: dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# chunk workers
# ---------------------------------------------------------------------------


def _extra() -> dict[str, Any]:
    ctx = cft._CTX
    assert ctx is not None and ctx.extra is not None
    return ctx.extra


def _lake_cells(st: CanvasStore, key: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
    """Local indices of this chunk's pass-through lake cells and their compact lake ids."""
    ids = _extra()["ids"]
    lbl = load_chunk(st, "lbl_lakes0", key).ravel()
    lid = np.where(lbl > 0, ids[lbl], -1)
    loc = np.flatnonzero(lid >= 0)
    return loc, lid[loc]


def _month_prep(key: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
    """Cut the pass-through lake cells from the routing; sum their monthly surface demand."""
    from dreamulator.map.prog_erosion import climate_cell_index

    ctx = cft._CTX
    assert ctx is not None
    st = _store_of(ctx)
    x = _extra()
    loc, lid = _lake_cells(st, key)
    code = load_chunk(st, "dir_route", key).copy()
    code.reshape(-1)[loc] = 255
    save_chunk(st, DIR_KIND, key, code)
    if loc.size == 0:
        return np.zeros(0, dtype=np.int64), np.zeros((0, 12), dtype=np.float64)
    t = ctx.tile
    g = (key[0] * t + loc // t) * x["width"] + (key[1] * t + loc % t)
    block = int(x["block"])
    evap, precip = x["evap_monthly"], x["precip_monthly"]
    idx = g if block <= 1 else climate_cell_index(g, x["width"], block, evap.shape[-1])
    present = np.unique(lid)
    out = np.zeros((present.size, 12), dtype=np.float64)
    pos = np.searchsorted(present, lid)
    for m in range(12):
        e = np.nan_to_num(evap[m].reshape(-1)[idx].astype(np.float64))
        p = np.nan_to_num(precip[m].reshape(-1)[idx].astype(np.float64))
        out[:, m] = np.bincount(pos, weights=e - p, minlength=present.size)
    return present, out


def _month_weight(task: tuple[Any, ...]) -> None:
    """One month's runoff weight: the coarse pack, lake cells zeroed, outflow injected."""
    key, month, inject_loc, inject_val = task
    ctx = cft._CTX
    assert ctx is not None
    st = _store_of(ctx)
    x = _extra()
    t = ctx.tile
    pack = x["pack"]  # (nr, nc, 12) coarse, already cropped to the bounding box
    f = int(x["factor"])
    rows = (key[0] * t + np.arange(t)) // f
    cols = (key[1] * t + np.arange(t)) // f
    nr, nc = pack.shape[0], pack.shape[1]
    w = np.zeros((t, t), dtype=np.float32)
    rv, cv = rows < nr, cols < nc
    w[np.ix_(rv, cv)] = pack[np.ix_(rows[rv], cols[cv])][..., month] / x["reference_mm"]
    flat = w.reshape(-1)
    if x["count"]:
        loc, _lid = _lake_cells(st, key)
        flat[loc] = 0.0  # the lake's own surface is in the demand, not in the inflow
    if len(inject_loc):
        np.add.at(flat, np.asarray(inject_loc, np.int64), np.asarray(inject_val, np.float32))
    save_chunk(st, WEIGHT_KIND, key, w)


def _month_inflow(key: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
    """This chunk's share of each pass-through lake's inflow for the accumulated month."""
    ctx = cft._CTX
    assert ctx is not None
    st = _store_of(ctx)
    loc, lid = _lake_cells(st, key)
    if loc.size == 0:
        return np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.float64)
    acc = load_chunk(st, ACC_KIND, key).reshape(-1)[loc].astype(np.float64)
    present = np.unique(lid)
    return present, np.bincount(np.searchsorted(present, lid), weights=acc, minlength=present.size)


def _month_count(key: tuple[int, int]) -> None:
    """Add this month to the per-cell active count."""
    ctx = cft._CTX
    assert ctx is not None
    st = _store_of(ctx)
    x = _extra()
    acc = load_chunk(st, ACC_KIND, key)
    if int(x["month"]) == 0:
        counts = np.zeros(acc.shape, dtype=np.uint8)
    else:
        counts = load_chunk(st, OUT_KIND, key)
    counts += (acc >= x["active_cells"]).astype(np.uint8)
    save_chunk(st, OUT_KIND, key, counts)


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------


def tiled_month_active(
    store: CanvasStore,
    comps: Components,
    term: TerminalResult,
    *,
    runoff_monthly_pack: np.ndarray,
    evaporation_monthly_mm: np.ndarray | None,
    precip_monthly_mm: np.ndarray | None,
    active_cells: float,
    factor: int,
    climate_block: int = 1,
    reference_mm: float | None = None,
    workers: int | None = None,
    log: Callable[[str], None] | None = None,
) -> MonthResult:
    """Write ``flow/month_active``: months per cell whose streamflow clears the active rule.

    The chunk twin of :func:`dreamulator.map.prog_erosion.month_active_counts` (see the module
    docstring).  ``runoff_monthly_pack`` is the coarse (n, n, 12) mm/month pack, upsampled by
    ``factor`` pixels per cell.  Without the monthly lake channels no lake loses water month by
    month, which biases the months below desert lakes toward perennial, so the two monthly
    arrays are optional only for inputs that lack them.
    """
    from dreamulator.map.prog_erosion import RUNOFF_REFERENCE_MM, monthly_outflow_cascade

    if active_cells <= 0.0:
        raise ValueError(f"active_cells must be positive, got {active_cells}")
    ref = RUNOFF_REFERENCE_MM if reference_mm is None else reference_mm
    layout = ChunkLayout.of(store)
    ctx = _ctx_of(store)
    ctx.increments = store.increments
    keys = list(ctx.keys)
    n_work = _default_workers(ctx.tile) if workers is None else max(1, workers)
    months = int(runoff_monthly_pack.shape[-1])
    t0 = time.time()

    # 1. pass-through lakes: not terminal, and their exits must leave the lake
    keep = ~term.is_term
    keep[0] = False
    keep &= comps.size > 0
    labels = np.flatnonzero(keep)
    ids = np.full(term.n + 1, -1, dtype=np.int64)
    ids[labels] = np.arange(labels.size)
    k = int(labels.size)
    nr = min(runoff_monthly_pack.shape[0], layout.shape[0] // factor)
    nc = min(runoff_monthly_pack.shape[1], layout.shape[1] // factor)
    ctx.extra = {
        "ids": ids,
        "count": k,
        "width": layout.shape[1],
        "block": climate_block,
        "factor": factor,
        "reference_mm": ref,
        "active_cells": float(active_cells),
        "month": 0,
        "pack": np.ascontiguousarray(
            np.nan_to_num(runoff_monthly_pack[:nr, :nc].astype(np.float32), nan=0.0)
        ),
        "evap_monthly": evaporation_monthly_mm,
        "precip_monthly": precip_monthly_mm,
    }
    have_lakes = k > 0 and evaporation_monthly_mm is not None and precip_monthly_mm is not None
    if not have_lakes:
        ctx.extra["count"] = k = 0
        ctx.extra["ids"] = np.full(term.n + 1, -1, dtype=np.int64)
    demand = np.zeros((k, 12), dtype=np.float64)
    for present, part in _pool_map(_month_prep, keys, ctx, n_work):
        if present.size:
            demand[present] += part
    (store.work / "flow" / WEIGHT_KIND).mkdir(parents=True, exist_ok=True)
    (store.work / "flow" / OUT_KIND).mkdir(parents=True, exist_ok=True)
    demand /= ref

    # 2. twelve inflow accumulations on the cut routing
    no_inject: dict[tuple[int, int], tuple[list[int], list[float]]] = {kk: ([], []) for kk in keys}
    inflow = np.zeros((k, months), dtype=np.float64)
    if k:
        for m in range(months):
            _pool_map(_month_weight, [(kk, m, *no_inject[kk]) for kk in keys], ctx, n_work)
            tiled_accumulation(
                store, WEIGHT_KIND, dir_kind=DIR_KIND, out_kind=ACC_KIND, workers=n_work
            )
            for present, part in _pool_map(_month_inflow, keys, ctx, n_work):
                if present.size:
                    inflow[present, m] += part
        if log is not None:
            log(f"[month] {k} pass-through lakes, inflow in {time.time() - t0:.0f} s")

    # 3. the cascade, then 4. twelve counting accumulations
    stats: dict[str, int] = {}
    inject: dict[tuple[int, int], tuple[list[int], list[np.ndarray]]] = {
        kk: ([], []) for kk in keys
    }
    if k:
        down = np.where(term.downstream_of[labels] > 0, ids[term.downstream_of[labels]], -1)
        topo = np.array([ids[a] for a in term.topo if keep[a]], dtype=np.int64)
        outflow, stats = monthly_outflow_cascade(topo, down, k, inflow, demand)
        # the lake's water leaves through the exits that drain out of it, split evenly
        lake_of_exit = ids[term.exit_lake]
        leaves = (lake_of_exit >= 0) & (term.exit_reach != term.exit_lake)
        ex_lake = lake_of_exit[leaves]
        share = outflow[ex_lake] / np.bincount(ex_lake, minlength=k)[ex_lake][:, None]
        t = ctx.tile
        tgt = term.exit_target[leaves]
        gr, gc = tgt // layout.shape[1], tgt % layout.shape[1]
        for key, loc, row in zip(
            zip((gr // t).tolist(), (gc // t).tolist(), strict=True),
            ((gr % t) * t + gc % t).tolist(),
            share,
            strict=True,
        ):
            if key in inject:
                inject[key][0].append(loc)
                inject[key][1].append(row)
    for m in range(months):
        ctx.extra["month"] = m
        _pool_map(
            _month_weight,
            [(kk, m, inject[kk][0], [float(r[m]) for r in inject[kk][1]] or []) for kk in keys],
            ctx,
            n_work,
        )
        tiled_accumulation(store, WEIGHT_KIND, dir_kind=DIR_KIND, out_kind=ACC_KIND, workers=n_work)
        _pool_map(_month_count, keys, ctx, n_work)
    drop_kinds(store, WEIGHT_KIND, ACC_KIND, DIR_KIND)
    if log is not None:
        log(f"[month] {months} months in {time.time() - t0:.0f} s")
    return MonthResult(months=months, pass_through=k, stats=stats)
