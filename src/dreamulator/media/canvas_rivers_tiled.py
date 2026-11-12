"""Out-of-core S2 river extraction: the channel mask and the chain table, per chunk.

Step 5 of the out-of-core rivers stage (steps 1-4: :mod:`canvas_flow_tiled`,
:mod:`canvas_lakes_tiled`, :mod:`canvas_terminal_tiled`, :mod:`canvas_month_tiled`).  Chains are
sparse — a channel cell needs an upstream catchment of hundreds of cells — so this stage does
not tile the walk itself.  It gathers the cells a chain can visit into the sorted table
:class:`dreamulator.map.prog_erosion.ChannelGraph` and hands that to the shared walk, which the
whole-grid path uses as well:

1. **Channel mask** (``flow/rivers``): land cells whose depleted accumulation clears the
   cartographic threshold, written chunk by chunk.
2. **Chain-breaking lakes**: the drawn lakes that pass the minimum mapping unit and the minimum
   width, read off the component table step 2 already built.
3. **The table**: the channel cells, the chain-breaking lake cells, the cell each of them drains
   into and the dried-fringe descent, with their accumulation, active-month count and receiver.

The lake products S3 windows read (``lakes.sparse/``) come from the same component labels, so
this stage never labels or holds a whole-canvas field.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import numpy as np

from dreamulator.media import canvas_flow_tiled as cft
from dreamulator.media.canvas_flow_tiled import (
    _DX,
    _DY,
    ChunkLayout,
    _ctx_of,
    _default_workers,
    _pool_map,
    _store_of,
    drop_kinds,
    load_chunk,
    save_chunk,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from dreamulator.map.prog_erosion import ChannelGraph
    from dreamulator.media.canvas_lakes_tiled import Components
    from dreamulator.media.canvas_pipeline import CanvasStore

RIVER_KIND = "rivers"

#: Peak bytes per cell of the whole-grid rivers chain (about ten canvas-sized fields).
WHOLE_GRID_BYTES_PER_CELL = 100.0

#: Long side of the channel QA raster ``hydro/rivers.png``; bigger canvases are max-pooled.
RASTER_MAX_PX = 16384


def _extra() -> dict[str, Any]:
    ctx = cft._CTX
    assert ctx is not None and ctx.extra is not None
    return ctx.extra


def _receivers(code: np.ndarray, key: tuple[int, int], tile: int, width: int) -> np.ndarray:
    """Global receiver index of every cell of a chunk, -1 where the D8 code is 255."""
    rr, cc = np.divmod(np.arange(code.size, dtype=np.int64), tile)
    k = code.ravel()
    has = k != 255
    ki = np.where(has, k, 0).astype(np.int64)
    gr = key[0] * tile + rr + _DY[ki]
    gc = key[1] * tile + cc + _DX[ki]
    return np.where(has, gr * width + gc, -1)


def _river_chunk(key: tuple[int, int]) -> tuple[np.ndarray, ...]:
    """Write the chunk's channel mask; return the cells a chain can visit from it."""
    ctx = cft._CTX
    assert ctx is not None
    st = _store_of(ctx)
    x = _extra()
    t = ctx.tile
    width = int(x["width"])
    acc = load_chunk(st, x["acc_kind"], key).ravel()
    land = load_chunk(st, "land2", key).ravel().astype(bool)
    rivers = land & (acc > x["threshold_cells"])
    save_chunk(st, RIVER_KIND, key, rivers.reshape(t, t).astype(np.uint8))
    keep = x["lake_keep"]
    lbl = load_chunk(st, "lbl_lakes0", key).ravel()
    is_lake = np.where(lbl > 0, keep[lbl], False)
    rec = _receivers(load_chunk(st, "dir_route", key), key, t, width)
    here = np.flatnonzero(rivers | is_lake)
    desc = load_chunk(st, "desc", key).ravel() if x["has_desc"] else None
    out = [here, rec[here]]
    if desc is not None:
        src = np.flatnonzero(desc >= 0)
        out += [src, desc[src]]
    base = (key[0] * t + here // t) * width + (key[1] * t + here % t)
    out[0] = base
    if desc is not None:
        out[2] = (key[0] * t + out[2] // t) * width + (key[1] * t + out[2] % t)
    return tuple(np.asarray(a, dtype=np.int64) for a in out)


def _gather_chunk(key: tuple[int, int]) -> tuple[np.ndarray, ...]:
    """Attributes of the wanted cells that live in this chunk, in table order."""
    ctx = cft._CTX
    assert ctx is not None
    st = _store_of(ctx)
    x = _extra()
    t = ctx.tile
    width = int(x["width"])
    cells = x["cells"]
    lo = np.searchsorted(cells, (key[0] * t) * width + key[1] * t)
    hi = np.searchsorted(cells, ((key[0] + 1) * t - 1) * width + (key[1] + 1) * t)
    rows = np.arange(lo, hi, dtype=np.int64)
    g = cells[lo:hi]
    gr, gc = np.divmod(g, width)
    inside = (gr // t == key[0]) & (gc // t == key[1])
    rows, g = rows[inside], g[inside]
    if rows.size == 0:
        empty = np.zeros(0, dtype=np.int64)
        return (empty,) * 2 + (np.zeros(0, np.float64), np.zeros(0, np.uint8), empty, empty)
    loc = (g // width % t) * t + g % width % t
    acc = load_chunk(st, x["acc_kind"], key).ravel()[loc].astype(np.float64)
    land = load_chunk(st, "land2", key).ravel()[loc].astype(bool)
    is_river = land & (acc > x["threshold_cells"])
    lbl = load_chunk(st, "lbl_lakes0", key).ravel()[loc]
    is_lake = np.where(lbl > 0, x["lake_keep"][lbl], False)
    rec = _receivers(load_chunk(st, "dir_route", key), key, t, width)[loc]
    month = (
        load_chunk(st, x["month_kind"], key).ravel()[loc].astype(np.uint8)
        if x["month_kind"]
        else np.full(loc.size, 12, dtype=np.uint8)
    )
    desc = (
        load_chunk(st, "desc", key).ravel()[loc].astype(np.int64)
        if x["has_desc"]
        else np.full(loc.size, -1, dtype=np.int64)
    )
    return rows, is_river.astype(np.int64) + 2 * is_lake.astype(np.int64), acc, month, rec, desc


def chain_breaking_lakes(comps: Components, mmu_cells: int, km_per_px: float) -> np.ndarray:
    """Per-label mask of the drawn lakes a channel may visibly end in (MMU and width gates).

    The chain stops of the whole-grid path are ``lakes_render | lake_term``, which is the drawn
    lake set itself: a terminal lake contributes its pre-verdict footprint and a pass-through
    lake its whole surface.  So the gates read off the component table of step 2 instead of
    labelling a whole-canvas mask (the ``labels=`` branch of
    :func:`dreamulator.map.prog_erosion.keep_large_lakes`).
    """
    from dreamulator.map.prog_erosion import LAKE_MIN_WIDTH_KM

    min_px = LAKE_MIN_WIDTH_KM / max(km_per_px, 1e-9)
    extent = np.minimum(comps.rmax - comps.rmin + 1, comps.cmax - comps.cmin + 1)
    keep = (comps.size >= max(mmu_cells, 1)) & (extent >= min_px)
    keep[0] = False
    return np.asarray(keep)


def tiled_channel_graph(
    store: CanvasStore,
    comps: Components,
    *,
    threshold_cells: int,
    mmu_cells: int,
    km_per_px: float,
    pixel_rows: int,
    acc_kind: str = "acc_w_depleted",
    month_kind: str | None = "month_active",
    has_descent: bool = True,
    workers: int | None = None,
    log: Callable[[str], None] | None = None,
) -> ChannelGraph:
    """Write ``flow/rivers`` and return the chain table for the shared walk.

    ``acc_kind`` is the accumulation of the depleted weight on the final routing (step 3/4),
    ``month_kind`` the active-month counts (step 4, ``None`` grades everything perennial) and
    ``has_descent`` says whether step 3 wrote a fringe descent.
    """
    from dreamulator.map.prog_erosion import ChannelGraph

    layout = ChunkLayout.of(store)
    ctx = _ctx_of(store)
    ctx.increments = store.increments
    keys = list(ctx.keys)
    n_work = _default_workers(ctx.tile) if workers is None else max(1, workers)
    t0 = time.time()
    ctx.extra = {
        "width": layout.shape[1],
        "threshold_cells": float(threshold_cells),
        "lake_keep": chain_breaking_lakes(comps, mmu_cells, km_per_px),
        "acc_kind": acc_kind,
        "month_kind": month_kind or "",
        "has_desc": has_descent,
        "cells": np.zeros(0, dtype=np.int64),
    }
    parts = _pool_map(_river_chunk, keys, ctx, n_work)
    cells = np.unique(np.concatenate([a for p in parts for a in p] + [np.zeros(0, np.int64)]))
    cells = cells[cells >= 0]
    del parts
    ctx.extra["cells"] = cells
    n = cells.size
    is_river = np.zeros(n, dtype=bool)
    is_lake = np.zeros(n, dtype=bool)
    acc = np.zeros(n, dtype=np.float64)
    month = np.full(n, 12, dtype=np.uint8)
    rec = np.full(n, -1, dtype=np.int64)
    desc = np.full(n, -1, dtype=np.int64)
    for rows, flags, a, m, r, d in _pool_map(_gather_chunk, keys, ctx, n_work):
        if rows.size == 0:
            continue
        is_river[rows] = (flags & 1).astype(bool)
        is_lake[rows] = (flags & 2).astype(bool)
        acc[rows], month[rows], rec[rows], desc[rows] = a, m, r, d
    if log is not None:
        log(
            f"[rivers] chain table: {int(is_river.sum())} channel cells, "
            f"{int(is_lake.sum())} lake cells, {time.time() - t0:.0f} s"
        )
    return ChannelGraph(
        cells=cells,
        is_river=is_river,
        is_lake=is_lake,
        receiver=rec,
        acc=acc,
        month=month,
        descend=desc,
        width=layout.shape[1],
        rows=pixel_rows,
        km_per_px=km_per_px,
    )


def _sparse_chunk(key: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
    """Write one chunk of ``hydro/lakes.sparse``; return the rendered cells per lake label."""
    ctx = cft._CTX
    assert ctx is not None
    st = _store_of(ctx)
    lbl = load_chunk(st, "lbl_lakes0", key).ravel().astype(np.int64)
    lbl = np.where(load_chunk(st, "lakes_render", key).ravel().astype(bool), lbl, 0)
    idx = np.flatnonzero(lbl)
    out = st.root / "hydro" / "lakes.sparse" / f"lake.r{key[0]:03d}_c{key[1]:03d}.npz"
    if idx.size == 0:
        out.unlink(missing_ok=True)
        return np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.int64)
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez(out, idx=idx.astype(np.uint32), lake_id=lbl[idx].astype(np.uint16))
    present = np.unique(lbl[idx])
    return present, np.bincount(np.searchsorted(present, lbl[idx]), minlength=present.size)


def run_canvas_rivers_tiled(
    store: CanvasStore,
    *,
    sea_level: float = 0.0,
    threshold_cells: int = 27000,
    workers: int | None = None,
    keep_work: bool = False,
    verbose: bool = True,
) -> dict[str, object]:
    """The rivers stage of :func:`canvas_pipeline.run_canvas_rivers`, out of core.

    Runs steps 1-5 on chunk files and writes the same products: the river vectors, the channel
    raster, the lake tables and ``rivers.meta.json``.  Nothing but the chain table, the
    per-lake tables and the channel raster is whole-canvas, so the peak scales with the
    channels and the lakes rather than with the grid.
    """
    import json

    from PIL import Image

    from dreamulator.map.prog_erosion import (
        LAKE_MIN_WIDTH_KM,
        lake_mmu_cells,
        regime_active_cells,
        river_segments_from_graph,
    )
    from dreamulator.map.td_canvas import PX_PER_CELL
    from dreamulator.media.canvas_flow_tiled import (
        tiled_accumulation,
        tiled_directions,
        tiled_graded,
    )
    from dreamulator.media.canvas_lakes_tiled import tiled_geometry_lakes
    from dreamulator.media.canvas_month_tiled import tiled_month_active
    from dreamulator.media.canvas_pipeline import (
        _declares_sea_mask,
        read_river_climate_inputs,
        write_lake_tables_from_counts,
    )
    from dreamulator.media.canvas_surface_process import write_surface_tag
    from dreamulator.media.canvas_terminal_tiled import tiled_terminal_routing

    log = print if verbose else None
    km = store.geometry.px_km
    mmu = lake_mmu_cells(km)
    inputs = read_river_climate_inputs(store)
    if verbose and inputs.has_basis:
        print(f"[hydrology] lake evaporation: {inputs.lake_evaporation_source}")
    layout = ChunkLayout.of(store)

    tiled_graded(store, sea_level=sea_level, workers=workers)
    tiled_directions(store, sea_level=sea_level, workers=workers)
    comps = tiled_geometry_lakes(store, mmu, km, workers=workers)
    term = tiled_terminal_routing(
        store, comps, precip_mm=inputs.precip, temp_c=inputs.temp_c,
        open_water_mm=inputs.open_water, runoff_land_mean_mm=inputs.runoff_land_mean_mm,
        mmu_cells=mmu, km_per_px=km, climate_block=inputs.climate_block,
        workers=workers, log=log,
    )  # fmt: skip
    tiled_accumulation(store, "w_depleted", dir_kind="dir_route", workers=workers, log=log)

    # Monthly regime on the final routing, with the pass-through lakes' own monthly balance
    # when the canvas carries the monthly channels.
    climate = store.root / "climate"
    monthly_path = climate / "runoff_monthly.mm.npy"
    month_kind: str | None = None
    monthly_lakes = "no monthly runoff"
    monthly_lake_stats: dict[str, int] = {}
    if monthly_path.exists():
        monthly = np.load(monthly_path).astype(np.float32)
        if monthly.ndim == 3:
            monthly = np.moveaxis(monthly, 0, -1)  # (12,n,n) -> (n,n,12)
            evap_m_path = climate / "lake_evaporation_monthly.mm.npy"
            precip_m_path = climate / "precipitation_monthly.mm.npy"
            evap_m = precip_m = None
            if evap_m_path.exists() and precip_m_path.exists():
                evap_m = np.load(evap_m_path).astype(np.float32)
                precip_m = np.load(precip_m_path).astype(np.float32)
                monthly_lakes = "monthly balance with storage below the sill"
            else:
                monthly_lakes = (
                    "no monthly depletion (no lake_evaporation_monthly.mm channel; "
                    "plan --backfill lake-evaporation)"
                )
            res = tiled_month_active(
                store, comps, term, runoff_monthly_pack=monthly, evaporation_monthly_mm=evap_m,
                precip_monthly_mm=precip_m, active_cells=regime_active_cells(km),
                factor=PX_PER_CELL, climate_block=PX_PER_CELL, workers=workers, log=log,
            )  # fmt: skip
            if res.pass_through == 0 and evap_m is not None:
                monthly_lakes = "no pass-through lakes"
            monthly_lake_stats = res.stats
            month_kind = "month_active"
            if verbose:
                print(f"[hydrology] monthly lakes: {monthly_lakes}")

    graph = tiled_channel_graph(
        store, comps, threshold_cells=threshold_cells, mmu_cells=mmu, km_per_px=km,
        pixel_rows=store.geometry.size_px, month_kind=month_kind,
        has_descent=(store.work / "flow" / "desc").is_dir(), workers=workers, log=log,
    )  # fmt: skip
    segs, flows, regimes = river_segments_from_graph(graph)

    hydro = store.root / "hydro"
    hydro.mkdir(exist_ok=True)
    write_surface_tag(hydro, store.surface)
    np.save(hydro / "rivers.line.npy", segs.astype(np.float32))
    np.save(hydro / "rivers.flow.npy", flows.astype(np.float32))
    np.save(hydro / "rivers.regime.npy", regimes.astype(np.uint8))
    # The channel raster is a QA image, so it is max-pooled to at most RASTER_MAX_PX on the long
    # side: at canvas pitch a world-sized bounding box is 1.9e10 pixels, which neither fits in
    # memory nor opens anywhere.  Pooling by the maximum keeps one-pixel channels visible, and
    # a canvas under the cap is written at full pitch.  The per-chunk rasters under
    # ``hydro-work/flow/rivers`` stay at full resolution for anything that needs them.
    t = store.tile
    pool = max(1, -(-max(layout.shape) // RASTER_MAX_PX))
    ph, pw = -(-layout.shape[0] // pool), -(-layout.shape[1] // pool)
    png = np.zeros((ph, pw), dtype=np.uint8)
    for key in store.chunks:
        rivers = load_chunk(store, RIVER_KIND, key).astype(bool)
        rivers &= ~load_chunk(store, "lakes_render", key).astype(bool)
        loc = np.flatnonzero(rivers.ravel())
        if loc.size == 0:
            continue
        gr = (key[0] * t + loc // t) // pool
        gc = (key[1] * t + loc % t) // pool
        png.reshape(-1)[gr * pw + gc] = 255
    Image.fromarray(png, mode="L").save(hydro / "rivers.png")
    del png

    ctx = _ctx_of(store)
    counts = np.zeros(term.n + 1, dtype=np.int64)
    for present, part in _pool_map(
        _sparse_chunk, list(ctx.keys), ctx, _default_workers(t) if workers is None else workers
    ):
        if present.size:
            counts[present] += part
    write_lake_tables_from_counts(store, counts, term.lake_records, term.stats, km)

    heal_path = store.work / "heal.npz"
    healed_cells = (
        int(np.load(heal_path)["idx"].size)
        if heal_path.exists() and not _declares_sea_mask(store)
        else 0
    )
    meta = {
        "threshold_cells": threshold_cells,
        "weight_source": inputs.weight_source,
        "km_per_px": km,
        "segments": int(len(flows)),
        "perennial": int((regimes == 0).sum()),
        "non_perennial": int((regimes == 1).sum()),
        "regime_source": "monthly-runoff" if month_kind else "annual-default",
        "regime_lakes": {"method": monthly_lakes, **monthly_lake_stats},
        "terminal_lakes": term.stats,
        "sea_source": (
            "surface-boundary-connectivity" if _declares_sea_mask(store) else "sea-level"
        ),
        "healed_pit_cells": healed_cells,
        "lake_mmu_cells": mmu,
        "lake_min_width_km": LAKE_MIN_WIDTH_KM,
        "solver": "out-of-core",
        "raster_pool": pool,
    }
    (hydro / "rivers.meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    if not keep_work:
        flow = store.work / "flow"
        kinds = sorted(d.name for d in flow.iterdir() if d.is_dir()) if flow.is_dir() else []
        drop_kinds(store, *kinds)
        if flow.is_dir() and not any(flow.iterdir()):
            flow.rmdir()
    if verbose:
        print(
            f"[hydrology] rivers: {len(flows)} segments "
            f"({int((regimes == 0).sum())} perennial / {int((regimes == 1).sum())} non-perennial); "
            f"terminal {term.stats.get('terminal', 0)} "
            f"(dry playas {term.stats.get('dry_playas', 0)}, shrunk {term.stats.get('shrunk', 0)})"
        )
    return {
        "segments": float(len(flows)),
        "perennial": float((regimes == 0).sum()),
        "non_perennial": float((regimes == 1).sum()),
    }


def prefer_out_of_core(store: CanvasStore, memory_fraction: float = 0.5) -> bool:
    """Whether the rivers stage should run out of core on this canvas and this machine.

    The whole-grid chain holds on the order of ten canvas-sized fields at its peak (the graded
    surface, the receivers, two accumulations, the masks and the sort order), measured at
    roughly 100 bytes per cell on the canvases profiled so far.  When that estimate exceeds
    ``memory_fraction`` of the memory actually available, the chunked chain is the only one
    that finishes, so it is the default; the choice is reported in ``rivers.meta.json``.  A
    platform that does not report free memory gets the chunked chain.
    """
    from dreamulator.utils.resources import available_memory_bytes

    free = available_memory_bytes()
    if free is None:
        return True  # the platform will not say: the chain that always fits is the safe default
    cells = float(np.prod(ChunkLayout.of(store).shape))
    return cells * WHOLE_GRID_BYTES_PER_CELL > memory_fraction * free
