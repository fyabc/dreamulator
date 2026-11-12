"""Out-of-core S2 lakes: connected components across chunk seams, geometry lakes chunk by chunk.

Step 2 of the out-of-core rivers stage (step 1, the flow fields, is
:mod:`dreamulator.media.canvas_flow_tiled`).  The in-memory lake mask
(:func:`dreamulator.map.prog_erosion.renderable_lakes`) is four layers of 4-connected components
with size and bounding-box gates; each needs whole components, which may span chunks.  So the
generic piece here is a tiled component labelling: every chunk labels its own mask, labels that
touch across a seam are joined by union-find, and each component gets its cell count, bounding
box and first cell in the row-major scan of the canvas bounding box.  Numbering components by
that first cell reproduces ``scipy.ndimage.label`` on the whole canvas exactly.

Geometry lakes, as in ``renderable_lakes``: cores are components of ``graded - dem > 5 m`` with
at least ``LAKE_MIN_CELLS`` cells; a lake is a whole component of ``graded - dem > 0.5 m`` holding
a core; it is kept when it passes the area MMU and the minimum bounding-box width; healed
below-sea endorheic bodies are added.  Files under ``<work>/flow/``: ``deep``, ``wet``, ``lakes0``
(uint8 masks) and ``lbl_<mask>`` (int32 global component ids, 0 = none).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

from dreamulator.media.canvas_flow_tiled import (
    ChunkLayout,
    _Ctx,
    _ctx_of,
    _default_workers,
    _pool_map,
    _store_of,
    flow_path,
    load_chunk,
    save_chunk,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from dreamulator.media.canvas_pipeline import CanvasStore


@dataclass
class Components:
    """Global components of a tiled mask (index 0 is "no component")."""

    count: int
    size: np.ndarray
    rmin: np.ndarray
    rmax: np.ndarray
    cmin: np.ndarray
    cmax: np.ndarray


# ---------------------------------------------------------------------------
# tiled connected components
# ---------------------------------------------------------------------------


def _label_chunk(task: tuple[Any, ...]) -> tuple[Any, ...]:
    """4-connected labels of one chunk mask, their stats and the seam rows/columns."""
    from scipy import ndimage

    from dreamulator.media import canvas_flow_tiled as cft

    key, kind = task
    ctx = cft._CTX
    assert ctx is not None
    st = _store_of(ctx)
    t = ctx.tile
    mask = load_chunk(st, kind, key).astype(bool)
    lbl, n = ndimage.label(mask)
    lbl = lbl.astype(np.int32)
    local_path = flow_path(st, f"lbl_{kind}", key, "local.npy")
    local_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(local_path, lbl)
    if n == 0:
        z = np.zeros(0, dtype=np.int64)
        return key, 0, z, z, z, z, z, z, lbl[0], lbl[-1], lbl[:, 0], lbl[:, -1]
    flat = lbl.ravel()
    cells = np.flatnonzero(flat)
    lab = flat[cells]
    rows = cells // t + key[0] * t
    cols = cells % t + key[1] * t
    size = np.bincount(lab, minlength=n + 1)[1:]
    big = np.iinfo(np.int64).max
    rmin = np.full(n + 1, big)
    cmin = np.full(n + 1, big)
    rmax = np.full(n + 1, -1)
    cmax = np.full(n + 1, -1)
    np.minimum.at(rmin, lab, rows)
    np.maximum.at(rmax, lab, rows)
    np.minimum.at(cmin, lab, cols)
    np.maximum.at(cmax, lab, cols)
    # first cell in the bounding-box row-major scan: smallest (row, col); the column breaks ties
    first_row = rmin
    first_col = np.full(n + 1, big)
    on_first = rows == first_row[lab]
    np.minimum.at(first_col, lab[on_first], cols[on_first])
    return (
        key,
        n,
        size,
        rmin[1:],
        rmax[1:],
        cmin[1:],
        cmax[1:],
        np.stack([first_row[1:], first_col[1:]], axis=1),
        lbl[0].copy(),
        lbl[-1].copy(),
        lbl[:, 0].copy(),
        lbl[:, -1].copy(),
    )


def _find(parent: np.ndarray, x: int) -> int:
    root = x
    while parent[root] != root:
        root = parent[root]
    while parent[x] != root:
        parent[x], x = root, parent[x]
    return root


def _relabel_chunk(task: tuple[Any, ...]) -> None:
    from dreamulator.media import canvas_flow_tiled as cft

    key, kind, table = task
    ctx = cft._CTX
    assert ctx is not None
    st = _store_of(ctx)
    p = flow_path(st, f"lbl_{kind}", key, "local.npy")
    local = np.load(p)
    save_chunk(st, f"lbl_{kind}", key, np.asarray(table, dtype=np.int32)[local])
    p.unlink()


def tiled_components(
    store: CanvasStore, kind: str, *, workers: int | None = None, ctx: _Ctx | None = None
) -> Components:
    """Label the ``flow/<kind>`` masks as one canvas (4-connected); write ``flow/lbl_<kind>``."""
    ctx = ctx or _ctx_of(store)
    layout = ChunkLayout(ctx.tile, ctx.keys)
    n_work = _default_workers(ctx.tile) if workers is None else max(1, workers)
    res = _pool_map(_label_chunk, [(k, kind) for k in layout.keys], ctx, n_work)
    offset: dict[tuple[int, int], int] = {}
    total = 0
    for r in res:
        offset[r[0]] = total
        total += r[1]
    parent = np.arange(total + 1, dtype=np.int64)  # node 0 unused
    seams = {r[0]: r[8:] for r in res}  # top, bottom, left, right
    for (ci, cj), (_top, bottom, _left, right) in seams.items():
        for nk, mine, theirs in (
            ((ci + 1, cj), bottom, 0),  # my bottom row meets the top row below
            ((ci, cj + 1), right, 2),  # my right column meets the left column to the right
        ):
            if nk not in seams:
                continue
            other = seams[nk][theirs]
            both = (mine > 0) & (other > 0)
            for a, b in zip(mine[both].tolist(), other[both].tolist(), strict=True):
                ra = _find(parent, offset[(ci, cj)] + a)
                rb = _find(parent, offset[nk] + b)
                if ra != rb:
                    parent[max(ra, rb)] = min(ra, rb)
    roots = np.array([_find(parent, i) for i in range(total + 1)], dtype=np.int64)
    big = np.iinfo(np.int64).max
    first = np.full((total + 1, 2), big, dtype=np.int64)
    size = np.zeros(total + 1, dtype=np.int64)
    rmin = np.full(total + 1, big)
    cmin = np.full(total + 1, big)
    rmax = np.full(total + 1, -1)
    cmax = np.full(total + 1, -1)
    for r in res:
        if r[1] == 0:
            continue
        nodes = offset[r[0]] + np.arange(1, r[1] + 1)
        rt = roots[nodes]
        np.add.at(size, rt, r[2])
        np.minimum.at(rmin, rt, r[3])
        np.maximum.at(rmax, rt, r[4])
        np.minimum.at(cmin, rt, r[5])
        np.maximum.at(cmax, rt, r[6])
        f = r[7]
        for node, (fr, fc) in zip(rt.tolist(), f.tolist(), strict=True):
            if (fr, fc) < (first[node, 0], first[node, 1]):
                first[node] = (fr, fc)
    comp_roots = np.unique(roots[1:]) if total else np.zeros(0, dtype=np.int64)
    order = np.lexsort((first[comp_roots, 1], first[comp_roots, 0]))
    gid = np.zeros(total + 1, dtype=np.int64)
    gid[comp_roots[order]] = np.arange(1, comp_roots.size + 1)
    tables = []
    for r in res:
        tab = np.zeros(r[1] + 1, dtype=np.int64)
        if r[1]:
            tab[1:] = gid[roots[offset[r[0]] + np.arange(1, r[1] + 1)]]
        tables.append((r[0], kind, tab))
    _pool_map(_relabel_chunk, tables, ctx, n_work)
    sel = comp_roots[order]
    return Components(
        count=int(comp_roots.size),
        size=np.concatenate([[0], size[sel]]),
        rmin=np.concatenate([[0], rmin[sel]]),
        rmax=np.concatenate([[0], rmax[sel]]),
        cmin=np.concatenate([[0], cmin[sel]]),
        cmax=np.concatenate([[0], cmax[sel]]),
    )


# ---------------------------------------------------------------------------
# geometry lakes
# ---------------------------------------------------------------------------


def _raw(ctx: _Ctx, key: tuple[int, int]) -> np.ndarray:
    name = f"r{key[0]:03d}_c{key[1]:03d}.npy"
    dem = np.asarray(np.load(ctx.root / "chunks" / name), dtype=np.float64)
    if ctx.increments is not None:
        dem += np.load(ctx.increments / name)
    return dem


def _depth_masks(key: tuple[int, int]) -> None:
    """``deep`` (> LAKE_MIN_FILL_M) and ``wet`` (> 0.5 m) masks of graded minus ground."""
    from dreamulator.map.prog_erosion import LAKE_MIN_FILL_M
    from dreamulator.media import canvas_flow_tiled as cft

    ctx = cft._CTX
    assert ctx is not None
    st = _store_of(ctx)
    depth = load_chunk(st, "graded", key) - _raw(ctx, key).astype(np.float32)
    save_chunk(st, "deep", key, (depth > LAKE_MIN_FILL_M).astype(np.uint8))
    save_chunk(st, "wet", key, (depth > 0.5).astype(np.uint8))


def _seeded_wet(task: tuple[Any, ...]) -> np.ndarray:
    """Wet components holding a core cell (a deep component of at least LAKE_MIN_CELLS)."""
    from dreamulator.media import canvas_flow_tiled as cft

    key, core_ids = task
    ctx = cft._CTX
    assert ctx is not None
    st = _store_of(ctx)
    deep = load_chunk(st, "lbl_deep", key)
    core = np.isin(deep, core_ids) if len(core_ids) else np.zeros(deep.shape, bool)
    return np.unique(load_chunk(st, "lbl_wet", key)[core])


def _lake_mask_chunk(task: tuple[Any, ...]) -> None:
    from dreamulator.media import canvas_flow_tiled as cft

    key, keep_ids, inland = task
    ctx = cft._CTX
    assert ctx is not None
    st = _store_of(ctx)
    lakes = np.isin(load_chunk(st, "lbl_wet", key), keep_ids)
    if inland is not None:
        lakes.reshape(-1)[inland] = True
    save_chunk(st, "lakes0", key, lakes.astype(np.uint8))


def inland_by_chunk(store: CanvasStore) -> dict[tuple[int, int], np.ndarray]:
    """Healed below-sea endorheic bodies (``heal.npz`` ``inland_idx``), chunk-local indices."""
    from dreamulator.media.canvas_pipeline import _declares_sea_mask

    heal_path = store.work / "heal.npz"
    if not heal_path.exists() or _declares_sea_mask(store):
        return {}
    layout = ChunkLayout.of(store)
    t = layout.tile
    w = layout.shape[1]
    idx = np.asarray(np.load(heal_path)["inland_idx"], dtype=np.int64)
    r, c = idx // w, idx % w
    ci, cj = r // t, c // t
    out: dict[tuple[int, int], np.ndarray] = {}
    for key in set(zip(ci.tolist(), cj.tolist(), strict=True)):
        m = (ci == key[0]) & (cj == key[1])
        out[key] = (r[m] % t) * t + c[m] % t
    return out


def tiled_geometry_lakes(
    store: CanvasStore,
    mmu_cells: int,
    km_per_px: float,
    *,
    workers: int | None = None,
    log: Callable[[str], None] | None = None,
) -> Components:
    """Write ``flow/lakes0`` (the ``renderable_lakes`` mask) and ``flow/lbl_lakes0``.

    Returns the components of the lake mask, numbered as ``scipy.ndimage.label`` numbers them
    on the whole canvas (the labelling the terminal-lake verdict starts from).
    """
    from dreamulator.map.prog_erosion import LAKE_MIN_CELLS, LAKE_MIN_WIDTH_KM

    ctx = _ctx_of(store)
    ctx.increments = store.increments
    n = _default_workers(ctx.tile) if workers is None else max(1, workers)
    keys = list(ctx.keys)
    _pool_map(_depth_masks, keys, ctx, n)
    deep = tiled_components(store, "deep", workers=n, ctx=ctx)
    wet = tiled_components(store, "wet", workers=n, ctx=ctx)
    core_ids = np.flatnonzero(deep.size >= max(LAKE_MIN_CELLS, 1))
    core_ids = core_ids[core_ids > 0]
    seeded = np.zeros(wet.count + 1, dtype=bool)
    for ids in _pool_map(_seeded_wet, [(k, core_ids) for k in keys], ctx, n):
        seeded[ids] = True
    seeded[0] = False
    extent = np.minimum(wet.rmax - wet.rmin + 1, wet.cmax - wet.cmin + 1)
    min_px = LAKE_MIN_WIDTH_KM / max(km_per_px, 1e-9)
    keep = seeded & (wet.size >= max(mmu_cells, 1)) & (extent >= min_px)
    keep[0] = False
    keep_ids = np.flatnonzero(keep)
    inland = inland_by_chunk(store)
    _pool_map(_lake_mask_chunk, [(k, keep_ids, inland.get(k)) for k in keys], ctx, n)
    lakes = tiled_components(store, "lakes0", workers=n, ctx=ctx)
    if log is not None:
        log(
            f"[lakes] cores {core_ids.size}, wet components {wet.count}, kept {keep_ids.size}, "
            f"lakes {lakes.count}"
        )
    return lakes


def lakes_path(store: CanvasStore, key: tuple[int, int]) -> Path:
    return flow_path(store, "lakes0", key)
