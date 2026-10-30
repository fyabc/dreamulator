"""canvas_hydrology_tiled — production three-stage S2 algorithms (skeleton).

Implements the published tiled schemes the S2 design adopts:

* **Fill** — Barnes 2016, "Parallel Priority-Flood depression filling for
  trillion cell DEMs on desktops or clusters" (Computers & Geosciences
  96:56-68): stage 1 runs a watershed-labelling Priority-Flood per tile
  (local ``Open`` queue) and returns edge elevations/labels plus a spillover
  graph; stage 2 makes labels unique, joins the tile spillover graphs across
  borders and floods the much smaller watershed graph; stage 3 raises each
  tile's cells to their watershed's global level.
* **Accumulation** — Barnes 2017, "Parallel non-divergent flow accumulation
  for trillion cell DEMs on desktops or clusters" (Environmental Modelling &
  Software 92:202-212): stage 1 accumulates inside each tile and records the
  flows leaving through tile borders; stage 2 solves the border-transfer
  system (each transfer follows its downstream path to the next border exit);
  stage 3 folds the external contributions back into every tile.

The eps > 0 variant follows Priority-Flood + ε (Barnes, Lehman & Mulla 2014,
"Priority-Flood...", Computers & Geosciences 62:117-127; RichDEM's
``ResolveFlatsEpsilon`` is the reference implementation): every filled cell
gets an ε-descending path to its depression outlet.  The tiled path adds that
grading in its finalize stage as a multi-source Dijkstra over each flat level
of the filled surface (seeds = outlets and spill saddles), which reproduces
the oracle's discovery wave bit-for-bit.  The alternative flat-resolution
scheme of Barnes et al. (2014, C&G 62:128-135) is not adopted: it bends flow
directions across flats toward convergent patterns, while the region chain's
semantics (and our oracle) use plain PF+ε.  The oracle in
:mod:`dreamulator.media.canvas_hydrology` is the acceptance reference: the
tests assert bit equality on synthetic DEMs, eps = 0 and eps > 0.
"""

from __future__ import annotations

import heapq
from typing import TYPE_CHECKING

import numpy as np

from dreamulator.media.canvas_hydrology import (
    _NEIGHBOURS,
    CanvasTiles,
    _grid_neighbour_fn,
    flow_directions,
)

if TYPE_CHECKING:
    from collections.abc import Hashable

__all__ = ["accumulate_canvas_tiled", "fill_canvas_tiled"]


# ---------------------------------------------------------------------------
# Fill — Barnes 2016 (three stages)
# ---------------------------------------------------------------------------


def _local_flood(
    dem: np.ndarray,
    external: np.ndarray,
    eps: float = 0.0,
) -> tuple[np.ndarray, np.ndarray, dict[tuple[int, int], float]]:
    """Stage 1 of the tiled fill for one tile (numba kernel fast path).

    Semantics identical to :func:`_local_flood_reference` (the pure-Python
    oracle the equivalence tests compare against); see its docstring for the
    seeding and spill-graph rules.
    """
    from dreamulator.media._hydrology_kernels import _local_flood_kernel

    labels, filled, spill = _local_flood_kernel(
        np.ascontiguousarray(dem), np.ascontiguousarray(external), eps
    )
    out: dict[tuple[int, int], float] = {}
    for key, value in spill.items():
        out[(int(key) >> 32, int(key) & 0xFFFFFFFF)] = float(value)
    assert (labels >= 0).all(), "tile flood left unlabeled cells"
    return labels, filled, out


def _local_flood_reference(
    dem: np.ndarray,
    external: np.ndarray,
    eps: float = 0.0,
) -> tuple[np.ndarray, np.ndarray, dict[tuple[int, int], float]]:
    """Stage 1 of the tiled fill for one tile.

    Seeds: cells flagged ``external`` (ocean, canvas edge, missing chunk)
    share the external label 0; every other tile-edge cell starts its own
    local label.  The flood raises cells and claims them by the lowest
    popping basin, recording the minimum meeting level between every pair of
    watersheds (the local spillover graph).

    Returns (labels, filled, spill) where ``spill[(a, b)]`` is the minimum
    elevation at which watersheds ``a`` and ``b`` meet.
    """
    h, w = dem.shape
    labels = np.full((h, w), -1, dtype=np.int64)
    filled = dem.copy()
    heap: list[tuple[float, int]] = []
    spill: dict[tuple[int, int], float] = {}
    next_label = 1

    def push(y: int, x: int, level: float) -> None:
        heapq.heappush(heap, (level, y * w + x))

    for y in range(h):
        for x in range(w):
            on_edge = y in (0, h - 1) or x in (0, w - 1)
            if external[y, x]:
                labels[y, x] = 0
                filled[y, x] = dem[y, x]
                push(y, x, dem[y, x])
            elif on_edge:
                labels[y, x] = next_label
                next_label += 1
                filled[y, x] = dem[y, x]
                push(y, x, dem[y, x])

    while heap:
        level, cell = heapq.heappop(heap)
        y0, x0 = divmod(cell, w)
        for dy, dx in _NEIGHBOURS:
            ny, nx = y0 + dy, x0 + dx
            if not (0 <= ny < h and 0 <= nx < w):
                continue
            if labels[ny, nx] < 0:
                labels[ny, nx] = labels[y0, x0]
                filled[ny, nx] = max(dem[ny, nx], level + eps)
                push(ny, nx, filled[ny, nx])
            elif labels[ny, nx] != labels[y0, x0]:
                a, b = int(labels[y0, x0]), int(labels[ny, nx])
                key = (a, b) if a <= b else (b, a)
                meet = max(level, float(filled[ny, nx]))
                if key not in spill or meet < spill[key]:
                    spill[key] = meet
    assert (labels >= 0).all(), "tile flood left unlabeled cells"
    return labels, filled, spill


def fill_canvas_tiled(
    tiles: CanvasTiles,
    *,
    sea_level: float = 0.0,
    eps: float = 0.0,
) -> None:
    """Three-stage tiled Priority-Flood (Barnes 2016); fills ``tiles.filled``.

    With ``eps > 0`` the final stage adds the eps ramp on top of the flat
    spill levels: each depression's marginal cells are flooded from the
    spill cell with the same ``max(dem, level + eps)`` rule the oracle uses,
    so flat filled surfaces grade toward their outlet instead of being
    exactly level (flow directions stay well-defined).
    """
    keys = list(tiles.raw.keys())
    grid = tiles.grid
    t = grid.tile
    nrows, ncols = grid.shape

    # True external cells: ocean, the canvas edge, or next to a missing chunk.
    # Artificial tile edges are NOT external — they are seeded with their own
    # watershed labels and reconciled through the cross-tile spillover graph
    # (Barnes 2016's stage 2), otherwise each tile would drain freely at its
    # border and the shared basin would be under-filled.
    def external_mask(key: tuple[int, int]) -> np.ndarray:
        ci, cj = key
        dem = tiles.raw[key]
        ext = dem <= sea_level
        if ci == 0:
            ext[0, :] = True
        if ci == grid.rows - 1:
            ext[-1, :] = True
        if cj == 0:
            ext[:, 0] = True
        if cj == grid.cols - 1:
            ext[:, -1] = True
        # Missing chunks inside the canvas are open boundary.
        for di, dj in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nci, ncj = ci + di, cj + dj
            if (nci, ncj) in tiles.raw:
                continue
            if not (0 <= nci < grid.rows and 0 <= ncj < grid.cols):
                continue  # outside the canvas: the canvas-edge rule covers it
            if di == -1:
                ext[0, :] = True
            elif di == 1:
                ext[-1, :] = True
            elif dj == -1:
                ext[:, 0] = True
            else:
                ext[:, -1] = True
        return ext

    # Stage 1 — per-tile local floods.
    labels: dict[tuple[int, int], np.ndarray] = {}
    local_fill: dict[tuple[int, int], np.ndarray] = {}
    local_spill: dict[tuple[int, int], dict[tuple[int, int], float]] = {}
    for key in keys:
        lab, fill, spill = _local_flood(tiles.raw[key], external_mask(key))
        labels[key] = lab
        local_fill[key] = fill
        local_spill[key] = spill

    # Stage 2 — unique global labels and the global spillover graph.
    gid: dict[tuple[Hashable, int], int] = {}
    for key in keys:
        for lab in np.unique(labels[key]):
            if int(lab) == 0:
                continue
            gid[(key, int(lab))] = len(gid) + 1  # node 0 = external
    edges: dict[int, dict[int, float]] = {}

    def add_edge(a: int, b: int, level: float) -> None:
        if a == b:
            return
        ea = edges.setdefault(a, {})
        if b not in ea or level < ea[b]:
            ea[b] = level
        eb = edges.setdefault(b, {})
        if a not in eb or level < eb[a]:
            eb[a] = level

    for key in keys:
        for (a, b), spill_level in local_spill[key].items():
            ga = 0 if a == 0 else gid[(key, a)]
            gb = 0 if b == 0 else gid[(key, b)]
            add_edge(ga, gb, spill_level)

    # Cross-tile border pairs: every border cell against its outside
    # neighbours (the 2-3 cells it touches across the border).
    for key in keys:
        ci, cj = key
        lab = labels[key]
        fill = local_fill[key]
        for y in range(t):
            for x in range(t):
                if y not in (0, t - 1) and x not in (0, t - 1):
                    continue
                for dy, dx in _NEIGHBOURS:
                    ny, nx = y + dy, x + dx
                    nkey: tuple[int, int]
                    if 0 <= ny < t and 0 <= nx < t:
                        continue  # same tile
                    # The neighbour lies in an adjacent tile.
                    nci = ci
                    ncj = cj
                    nny, nnx = ny, nx
                    if ny < 0:
                        nci -= 1
                        nny = t - 1
                    elif ny >= t:
                        nci += 1
                        nny = 0
                    if nx < 0:
                        ncj -= 1
                        nnx = t - 1
                    elif nx >= t:
                        ncj += 1
                        nnx = 0
                    nkey = (nci, ncj)
                    if nkey not in tiles.raw:
                        continue
                    nlab = int(labels[nkey][nny, nnx])
                    nfill = float(local_fill[nkey][nny, nnx])
                    ga = 0 if int(lab[y, x]) == 0 else gid[(key, int(lab[y, x]))]
                    gb = 0 if nlab == 0 else gid[(nkey, nlab)]
                    add_edge(ga, gb, max(float(fill[y, x]), nfill))

    # Graph flood from the external node (min over paths of the max edge).
    level: dict[int, float] = {0: float("-inf")}
    heap: list[tuple[float, int]] = [(float("-inf"), 0)]
    while heap:
        lv, node = heapq.heappop(heap)
        if lv != level.get(node):
            continue
        for nb, w in edges.get(node, {}).items():
            cand = max(lv, w)
            if nb not in level or cand < level[nb]:
                level[nb] = cand
                heapq.heappush(heap, (cand, nb))
    missing = [k for k in gid if level.get(gid[k], float("inf")) == float("inf")]
    if missing:
        # No path to the external node: malformed canvas (chunk hole).
        raise RuntimeError(f"{len(missing)} watersheds do not reach an outlet")

    # Stage 3 — raise each tile's cells to their watershed level.
    out: dict[tuple[int, int], np.ndarray] = {}
    for key in keys:
        lab = labels[key]
        final = local_fill[key].copy()
        for local_lab in np.unique(lab):
            if int(local_lab) == 0:
                continue  # external cells keep their own elevation
            lv = level[gid[(key, int(local_lab))]]
            if lv == float("-inf"):
                continue
            mask = lab == local_lab
            final[mask] = np.maximum(final[mask], lv)
        out[key] = final
    tiles.filled = out
    if eps > 0.0:
        _apply_eps_ramp(tiles, sea_level=sea_level, eps=eps)


def _apply_eps_ramp(tiles: CanvasTiles, *, sea_level: float, eps: float) -> None:
    """Grade the flat spill levels toward their outlets (oracle-equivalent).

    The eps flood raises each depression cell by ``eps`` per step of the
    discovery wave that starts at the outlet.  On the *flat* filled surface
    that wave is a multi-source Dijkstra over equal-value cells:

    * seeds are outlets (ocean / canvas edge / missing chunk) and cells of a
      flat region that touch a strictly lower flat value (the spill saddle),
      all at their flat level;
    * moving inside the same flat level costs ``eps``; moving to a lower or
      higher flat level is not part of the wave.

    This reproduces the oracle's ``max(dem, level + eps)`` discovery exactly
    (the global heap tie-break only reorders equal levels, not the depths).
    """
    keys = list(tiles.raw.keys())
    grid = tiles.grid
    t = grid.tile
    nrows, ncols = grid.shape
    dem = np.empty((nrows, ncols * t), dtype=np.float64)
    filled = np.empty_like(dem)
    open_mask = np.zeros_like(dem, dtype=bool)
    for key, arr in tiles.raw.items():
        ci, cj = key
        dem[ci * t : (ci + 1) * t, cj * t : (cj + 1) * t] = arr
        filled[ci * t : (ci + 1) * t, cj * t : (cj + 1) * t] = tiles.filled[key]
        ext = arr <= sea_level
        if ci == 0:
            ext[0, :] = True
        if ci == nrows - 1:
            ext[-1, :] = True
        if cj == 0:
            ext[:, 0] = True
        if cj == ncols - 1:
            ext[:, -1] = True
        open_mask[ci * t : (ci + 1) * t, cj * t : (cj + 1) * t] = ext

    h, w = filled.shape
    flat = filled.ravel()
    dem_flat = dem.ravel()
    mask_flat = open_mask.ravel()
    level = np.full(flat.size, np.inf, dtype=np.float64)
    heap: list[tuple[float, int]] = []
    for c in range(flat.size):
        if mask_flat[c] or dem_flat[c] <= sea_level:
            level[c] = flat[c]
            heap.append((flat[c], c))
            continue
        cr, cc = divmod(c, w)
        low = False
        for dy, dx in _NEIGHBOURS:
            nr, nc = cr + dy, cc + dx
            if 0 <= nr < h and 0 <= nc < w and filled[nr, nc] < flat[c] - 1e-9:
                low = True
                break
        if low:
            level[c] = flat[c]
            heap.append((flat[c], c))
    heapq.heapify(heap)
    while heap:
        lv, c = heapq.heappop(heap)
        if lv != level[c]:
            continue
        cr, cc = divmod(c, w)
        for dy, dx in _NEIGHBOURS:
            nr, nc = cr + dy, cc + dx
            if not (0 <= nr < h and 0 <= nc < w):
                continue
            nid = nr * w + nc
            if filled[nr, nc] != flat[c]:
                continue  # only inside the same flat level
            nl = lv + eps
            if nl < level[nid]:
                level[nid] = nl
                heapq.heappush(heap, (nl, nid))
    out_flat = np.where(np.isfinite(level), np.maximum(level, dem_flat), flat)
    out = out_flat.reshape(h, w)
    result: dict[tuple[int, int], np.ndarray] = {}
    for key in keys:
        ci, cj = key
        result[key] = out[ci * t : (ci + 1) * t, cj * t : (cj + 1) * t].copy()
    tiles.filled = result


# ---------------------------------------------------------------------------
# Accumulation — Barnes 2017 (three stages, border-transfer event graph)
# ---------------------------------------------------------------------------


def accumulate_canvas_tiled(
    tiles: CanvasTiles,
    weights: dict[tuple[int, int], np.ndarray],
    *,
    sea_level: float = 0.0,
) -> dict[tuple[int, int], np.ndarray]:
    """Three-stage tiled accumulation (Barnes 2017) on the D8 receivers.

    Stage 1 accumulates inside each tile and records every flow leaving a
    tile (a transfer event).  Stage 2 solves the transfers: events are
    processed from the highest filled value down, and each incoming flow is
    followed along the receiver chain inside the receiving tile up to the
    next border exit.  Stage 3 folds all incoming flows back into each tile's
    accumulation.  Matches the oracle's global descending-order accumulation
    exactly (tests assert this).
    """
    assert tiles.filled, "run the fill first"
    keys = list(tiles.raw.keys())
    grid = tiles.grid
    t = grid.tile
    nb_fn = _grid_neighbour_fn(tiles.raw, grid)
    rec = flow_directions(tiles, sea_level=sea_level, neighbour=nb_fn)

    # Global flat arrays in key order (index = tile_id*t*t + r*t + c).
    filled_flat = {k: tiles.filled[k].ravel() for k in keys}
    rec_flat = {k: rec[k].ravel() for k in keys}
    local_acc: dict[tuple[int, int], np.ndarray] = {}
    extra: dict[tuple[int, int], np.ndarray] = {k: np.zeros(t * t) for k in keys}

    # Stage 1 — per-tile accumulation, transfers recorded as events.
    events: list[
        tuple[float, int, int, tuple[int, int], int]
    ] = []  # (filled, src_gid, dst_gid, key_src, idx)
    gid_off: dict[tuple[int, int], int] = {k: i * t * t for i, k in enumerate(keys)}
    key_of_gid: dict[int, tuple[int, int]] = {}
    for k in keys:
        for idx in range(t * t):
            key_of_gid[gid_off[k] + idx] = k
    for key in keys:
        order = np.argsort(-filled_flat[key], kind="stable")
        acc = weights[key].astype(np.float64).ravel().copy()
        off = gid_off[key]
        for idx in order:
            target = int(rec_flat[key][idx])
            if target < 0:
                continue
            if (target // (t * t)) == (off // (t * t)):
                # Same tile: accumulate immediately.
                local_idx = target - off
                acc[local_idx] += acc[idx]
            else:
                events.append((float(filled_flat[key][idx]), off + idx, target, key, int(idx)))
        local_acc[key] = acc

    # Stage 2 — transfer solve along receiver chains (highest filled first).
    def walk(value: float, dst_gid: int, dst_key: tuple[int, int], start: int) -> None:
        cur = start
        off = gid_off[dst_key]
        while True:
            extra[dst_key][cur] += value
            target = int(rec_flat[dst_key][cur])
            if target < 0:
                return
            tkey = key_of_gid[target]
            if tkey != dst_key:
                # Leaves the tile: the exit cell keeps its share above, and the
                # exit's own transfer event (value = local_acc + extra) carries
                # the flow on — adding here would double count it.
                return
            cur = target - off

    events.sort(key=lambda e: -e[0])
    for _filled, _src_gid, dst_gid, _key_src, src_idx in events:
        value = float(local_acc[_key_src][src_idx] + extra[_key_src][src_idx])
        dst_key = key_of_gid[dst_gid]
        walk(value, dst_gid, dst_key, dst_gid - gid_off[dst_key])

    # Stage 3 — final accumulation = local + incoming flows along chains.
    out: dict[tuple[int, int], np.ndarray] = {}
    for key in keys:
        acc = local_acc[key] + extra[key]
        out[key] = acc.reshape(t, t).astype(np.float64)
    return out
