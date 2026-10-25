"""canvas_hydrology — out-of-core hydrology on S1 canvases (S2 scaffold).

The design contract lives in ``docs/design/pipelines/canvas-chain.md``.
This module is the **correctness oracle** for S2: it implements the classic
one-shot Priority-Flood (Barnes, Lehman & Mulla 2014) as a single global
frontier over lazily-touched tiles, cross-chunk lake components, D8 flow
directions and a global descending-height accumulation, and the world-island
isthmus coupling as a joint frontier across the seam.  The production path
follows the published tiled schemes — Barnes 2016 (Computers & Geosciences
96:56–68) for filling and Barnes 2017 (Environmental Modelling & Software
92:202–212) for non-divergent accumulation — and is accepted when it matches
this oracle bit-for-bit on the pilot canvas (see the S2 design doc).

Tiles are plain ``float64`` arrays in a ``{(ci, cj): ndarray}`` mapping.
The canvas-edge rule matches the region chain: pixels on the canvas
boundary (or next to a chunk that is not part of the canvas) are open
outlets, exactly like the region window edge.  Internal chunk borders are
ordinary adjacencies, so no border protocol is needed for correctness.

Determinism: heap entries are ``(level, global index)`` tuples, so ties
resolve identically on every run.  The tests compare against an
independent classic Priority-Flood reference on the same DEM assembled
into one array.  (The region chain's kernel seeds boundary neighbours up
front instead of queueing the boundary cells themselves, so on
land-bordered DEMs it can inflate a fill by the arbitrary loop order of
high boundary cells; the classic queue-the-outlets form is used here.)
"""

from __future__ import annotations

from collections.abc import Callable, Hashable
from dataclasses import dataclass, field
from typing import cast

import numpy as np

__all__ = [
    "CanvasTiles",
    "ChunkGrid",
    "flood_canvas",
    "flow_accumulation_canvas",
    "flow_directions",
    "lake_labels",
    "solve_isthmus",
]

#: Pixel pitch of the 90 m canvas model (km): 23 km coarse cell / 256 pixels.
PX_KM = 23.0 / 256.0

#: 8-connectivity offsets, fixed order (deterministic tie behaviour).
_NEIGHBOURS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]

NeighbourFn = Callable[[Hashable, int, int, int, int], "tuple[Hashable, int, int] | None"]
OutletFn = Callable[[Hashable, int, int], bool]


@dataclass(frozen=True)
class ChunkGrid:
    """Chunk layout of one canvas: ``rows`` × ``cols`` chunks of ``tile``² pixels."""

    rows: int
    cols: int
    tile: int

    @property
    def shape(self) -> tuple[int, int]:
        return (self.rows * self.tile, self.cols * self.tile)


@dataclass
class CanvasTiles:
    """Raw S1 elevation tiles plus the filled surface built by S2.

    ``raw`` holds the S1 elevation per tile (float64, m); ``filled`` is
    filled in place by :func:`flood_canvas`.  Tiles missing from ``raw``
    are treated as open boundary (the S1 chunk list only covers the
    generation buffer).
    """

    raw: dict[tuple[int, int], np.ndarray]
    grid: ChunkGrid
    filled: dict[tuple[int, int], np.ndarray] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Generic frontier flood over a tile graph
# ---------------------------------------------------------------------------


def _flood_graph(
    tiles: dict[Hashable, np.ndarray],
    neighbour: NeighbourFn,
    outlet: OutletFn,
    *,
    sea_level: float,
    eps: float,
) -> dict[Hashable, np.ndarray]:
    """Classic Priority-Flood over an arbitrary tile graph.

    A single heap holds the frontier; a pixel is pushed exactly once, from
    the lowest-level neighbour that pops it (Dijkstra).  ``neighbour`` maps
    a pixel and one of the eight offsets to the adjacent pixel or ``None``;
    ``outlet`` marks pixels that may drain out of the domain (canvas edge,
    missing chunk) — they enter the heap at their own elevation.  Internal
    tile borders need no special handling: they are ordinary adjacencies.

    Memory is bounded by the heap (frontier) plus the tiles the caller
    keeps loaded; the caller controls the latter through ``tiles``.
    """
    import heapq

    if not tiles:
        return {}
    t = int(next(iter(tiles.values())).shape[0])
    tile_ids: dict[Hashable, int] = {key: i for i, key in enumerate(tiles)}
    n_px = t * t
    key_list = list(tiles.keys())
    filled: dict[Hashable, np.ndarray] = {k: v.copy() for k, v in tiles.items()}
    state: dict[Hashable, np.ndarray] = {k: np.zeros((t, t), dtype=np.uint8) for k in tiles}

    def gi_of(key: Hashable, r: int, c: int) -> int:
        return tile_ids[key] * n_px + r * t + c

    def decode(gi: int) -> tuple[Hashable, int, int]:
        tid, rem = divmod(gi, n_px)
        r, c = divmod(rem, t)
        return key_list[tid], r, c

    heap: list[tuple[float, int]] = []
    for key in tiles:
        dem = tiles[key]
        st = state[key]
        for r in range(t):
            for c in range(t):
                if dem[r, c] <= sea_level or outlet(key, r, c):
                    st[r, c] = 2
                    filled[key][r, c] = dem[r, c]
                    heapq.heappush(heap, (float(dem[r, c]), gi_of(key, r, c)))

    while heap:
        level, gi = heapq.heappop(heap)
        key, r, c = decode(gi)
        st = state[key]
        if st[r, c] == 1:
            st[r, c] = 2
            filled[key][r, c] = level
        for dy, dx in _NEIGHBOURS:
            nb = neighbour(key, r, c, dy, dx)
            if nb is None:
                continue
            nkey, nr, nc = nb
            nst = state[nkey]
            if nst[nr, nc] != 0:
                continue
            lvl = max(float(tiles[nkey][nr, nc]), level + eps)
            nst[nr, nc] = 1
            filled[nkey][nr, nc] = lvl
            heapq.heappush(heap, (lvl, gi_of(nkey, nr, nc)))
    return filled


def _grid_neighbour_fn(raw: dict[tuple[int, int], np.ndarray], grid: ChunkGrid) -> NeighbourFn:
    t = grid.tile
    nrows, ncols = grid.shape

    def neighbour(
        key: Hashable, r: int, c: int, dy: int, dx: int
    ) -> tuple[Hashable, int, int] | None:
        ci, cj = cast("tuple[int, int]", key)
        gr, gc = ci * t + r + dy, cj * t + c + dx
        if gr < 0 or gr >= nrows or gc < 0 or gc >= ncols:
            return None
        nkey = (gr // t, gc // t)
        if nkey not in raw:
            return None
        return nkey, gr % t, gc % t

    return neighbour


def _grid_outlet_fn(neighbour: NeighbourFn) -> OutletFn:
    def outlet(key: Hashable, r: int, c: int) -> bool:
        return any(neighbour(key, r, c, dy, dx) is None for dy, dx in _NEIGHBOURS)

    return outlet


def flood_canvas(
    tiles: CanvasTiles,
    *,
    sea_level: float = 0.0,
    eps: float = 1e-3,
) -> None:
    """Fill all canvas tiles in place (joint frontier over the chunk graph).

    Ocean cells and pixels adjacent to the canvas edge or a missing chunk
    are outlets at their own elevation (the region-chain window rule);
    everything else is an ordinary cell reached by the frontier.  The fill
    is Dijkstra-equivalent to a classic Priority-Flood on the assembled
    DEM (the tests assert byte equality with eps = 0).
    """
    neighbour = _grid_neighbour_fn(tiles.raw, tiles.grid)
    tiles.filled = cast(
        "dict[tuple[int, int], np.ndarray]",
        _flood_graph(
            cast("dict[Hashable, np.ndarray]", tiles.raw),
            neighbour,
            _grid_outlet_fn(neighbour),
            sea_level=sea_level,
            eps=eps,
        ),
    )


# ---------------------------------------------------------------------------
# D8 flow directions and accumulation across tile borders
# ---------------------------------------------------------------------------


class _TileIndex:
    """Flat global pixel ids over a tile graph (stable per call)."""

    def __init__(self, keys: list[Hashable], tile: int) -> None:
        self.keys = keys
        self.ids = {key: i for i, key in enumerate(keys)}
        self.t = tile
        self.npx = tile * tile

    def gi(self, key: Hashable, r: int, c: int) -> int:
        return self.ids[key] * self.npx + r * self.t + c

    def decode(self, gi: int) -> tuple[Hashable, int, int]:
        tid, rem = divmod(gi, self.npx)
        r, c = divmod(rem, self.t)
        return self.keys[tid], r, c


def flow_directions(
    tiles: CanvasTiles,
    *,
    sea_level: float = 0.0,
    neighbour: NeighbourFn | None = None,
) -> dict[tuple[int, int], np.ndarray]:
    """D8 steepest-descent receivers on the filled surface (global pixel ids).

    ``-1`` marks ocean cells and cells with no strictly lower neighbour
    (lake interiors on a zero-eps fill).  The neighbour order is fixed, so
    ties resolve deterministically.  ``neighbour`` defaults to the single
    canvas grid; :func:`solve_isthmus` passes a seam-aware one.
    """
    assert tiles.filled, "run flood_canvas first"
    nb_fn = neighbour if neighbour is not None else _grid_neighbour_fn(tiles.raw, tiles.grid)
    keys = list(tiles.raw.keys())
    t = tiles.grid.tile
    idx = _TileIndex(cast("list[Hashable]", keys), t)
    out: dict[tuple[int, int], np.ndarray] = {
        key: np.full((t, t), -1, dtype=np.int64) for key in keys
    }
    diag = 2**0.5
    for key in keys:
        filled = tiles.filled[key]
        rec = out[key]
        for r in range(t):
            for c in range(t):
                f0 = filled[r, c]
                if f0 <= sea_level:
                    continue
                best_slope = 0.0
                best = -1
                for dy, dx in _NEIGHBOURS:
                    nb = nb_fn(key, r, c, dy, dx)
                    if nb is None:
                        continue
                    nkey, nr, nc = nb
                    f1 = float(tiles.filled[cast("tuple[int, int]", nkey)][nr, nc])
                    if f1 >= f0:
                        continue
                    slope = (f0 - f1) / (diag if dy and dx else 1.0)
                    if slope > best_slope:
                        best_slope = slope
                        best = idx.gi(nkey, nr, nc)
                rec[r, c] = best
    return out


def flow_accumulation_canvas(
    tiles: CanvasTiles,
    weights: dict[tuple[int, int], np.ndarray],
    *,
    sea_level: float = 0.0,
    neighbour: NeighbourFn | None = None,
) -> dict[tuple[int, int], np.ndarray]:
    """Upstream sum of ``weights`` along the D8 receivers, across tile borders.

    Every pixel starts with its own weight and flow is added to the receiver
    in descending filled order — a valid downstream-first order because
    receivers strictly descend.  Because that order is global, a cross-tile
    receiver needs no tile scheduling: the neighbouring tile's pixel simply
    appears later in the same order.  (A tile-level dependency DAG is *not*
    valid here: two tiles can exchange flow through different border pixels,
    forming a pseudo-cycle even though the pixel graph is acyclic.)
    ``-1`` receivers mark ocean cells and flat lake interiors; flow entering
    a lake is stranded at its shore, which is the region-chain lake
    semantics.  Memory is one flat accumulation array per canvas — fine for
    the scaffold and the pilot; the production wavefront scheduler keeps
    only the active band in memory.
    """
    assert tiles.filled, "run flood_canvas first"
    nb_fn = neighbour if neighbour is not None else _grid_neighbour_fn(tiles.raw, tiles.grid)
    keys = list(tiles.raw.keys())
    t = tiles.grid.tile
    rec = flow_directions(tiles, sea_level=sea_level, neighbour=nb_fn)
    filled = np.concatenate([tiles.filled[k].ravel() for k in keys])
    rec_flat = np.concatenate([rec[k].ravel() for k in keys])
    acc = np.concatenate([weights[k].astype(np.float64).ravel() for k in keys])
    for flat in np.argsort(-filled, kind="stable"):
        target = rec_flat[flat]
        if target >= 0:
            acc[target] += acc[flat]
    out: dict[tuple[int, int], np.ndarray] = {}
    off = 0
    for key in keys:
        out[key] = acc[off : off + t * t].reshape(t, t).copy()
        off += t * t
    return out


# ---------------------------------------------------------------------------
# Cross-chunk lake components
# ---------------------------------------------------------------------------


def lake_labels(
    tiles: CanvasTiles,
    *,
    min_depth_m: float = 0.0,
    connectivity: int = 8,
) -> dict[tuple[int, int], np.ndarray]:
    """Label lake pixels (filled above raw) across the whole canvas.

    Per-tile 8-connected components are unioned across shared borders, so a
    lake straddling four chunks gets one global label.  Labels are assigned
    deterministically in chunk order, then raster order.  0 marks non-lake.
    """
    from scipy.ndimage import label as nd_label

    structure = np.ones((3, 3), dtype=np.uint8) if connectivity == 8 else None
    parent: dict[tuple[tuple[int, int], int], tuple[tuple[int, int], int]] = {}

    def find(a: tuple[tuple[int, int], int]) -> tuple[tuple[int, int], int]:
        parent.setdefault(a, a)
        root = a
        while parent[root] != root:
            root = parent[root]
        while parent[a] != a:
            parent[a], a = root, parent[a]
        return root

    def union(a: tuple[tuple[int, int], int], b: tuple[tuple[int, int], int]) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    per_tile: dict[tuple[int, int], np.ndarray] = {}
    for i in range(tiles.grid.rows):
        for j in range(tiles.grid.cols):
            key = (i, j)
            if key not in tiles.raw:
                continue
            depth = tiles.filled[key] - tiles.raw[key]
            lake = depth > min_depth_m
            if not lake.any():
                per_tile[key] = np.zeros(depth.shape, dtype=np.int64)
                continue
            lab, _n = nd_label(lake, structure=structure)
            per_tile[key] = lab.astype(np.int64)

    for key, lab in per_tile.items():
        i, j = key
        if lab.size == 0:
            continue
        rkey = (i, j + 1)
        if rkey in per_tile:
            right = per_tile[rkey]
            both = (lab[:, -1] > 0) & (right[:, 0] > 0)
            for a, b in zip(lab[:, -1][both], right[:, 0][both], strict=True):
                union((key, int(a)), (rkey, int(b)))
        dkey = (i + 1, j)
        if dkey in per_tile:
            down = per_tile[dkey]
            both = (lab[-1, :] > 0) & (down[0, :] > 0)
            for a, b in zip(lab[-1, :][both], down[0, :][both], strict=True):
                union((key, int(a)), (dkey, int(b)))

    remap: dict[tuple[tuple[int, int], int], int] = {}
    out: dict[tuple[int, int], np.ndarray] = {}
    for i in range(tiles.grid.rows):
        for j in range(tiles.grid.cols):
            key = (i, j)
            lab = per_tile.get(key)
            if lab is None:
                continue
            result = np.zeros_like(lab)
            for local in np.unique(lab):
                if local == 0:
                    continue
                root = find((key, int(local)))
                if root not in remap:
                    remap[root] = len(remap) + 1
                result[lab == local] = remap[root]
            out[key] = result
    return out


# ---------------------------------------------------------------------------
# Isthmus: joint frontier across two canvases
# ---------------------------------------------------------------------------


def solve_isthmus(
    a: CanvasTiles,
    b: CanvasTiles,
    pairs: list[tuple[tuple[tuple[int, int], int, int], tuple[tuple[int, int], int, int]]],
    *,
    sea_level: float = 0.0,
    eps: float = 1e-3,
) -> None:
    """Fill two canvases coupled across a land boundary (the world-island isthmus).

    ``pairs`` couples boundary pixels: ``(((a_chunk), a_row, a_col),
    ((b_chunk), b_row, b_col))``.  The two canvases are flooded as **one
    joint tile graph**: each pair adds an extra adjacency edge, so the
    frontier crosses the seam exactly like an internal chunk border.  One
    Dijkstra pass therefore equals the fill of the concatenated DEM — no
    external-level iteration is needed (the seam is only a few hundred
    edges).  Final fills land in ``a.filled`` / ``b.filled``.
    """
    t = a.grid.tile
    tiles: dict[Hashable, np.ndarray] = {}
    for cidx, canvas in ((0, a), (1, b)):
        for (ci, cj), arr in canvas.raw.items():
            tiles[(cidx, ci, cj)] = arr

    seam: dict[tuple[int, int, int, int, int], tuple[int, int, int, int, int]] = {}
    for (ka, ra, ca), (kb, rb, cb) in pairs:
        seam[(0, ka[0], ka[1], ra, ca)] = (1, kb[0], kb[1], rb, cb)
        seam[(1, kb[0], kb[1], rb, cb)] = (0, ka[0], ka[1], ra, ca)

    grids = {0: a.grid, 1: b.grid}

    def neighbour(
        key: Hashable, r: int, c: int, dy: int, dx: int
    ) -> tuple[Hashable, int, int] | None:
        cidx, ci, cj = cast("tuple[int, int, int]", key)
        grid = grids[cidx]
        gr, gc = ci * t + r + dy, cj * t + c + dx
        nrows, ncols = grid.shape
        if 0 <= gr < nrows and 0 <= gc < ncols:
            nkey = (cidx, gr // t, gc // t)
            if nkey in tiles:
                return nkey, gr % t, gc % t
        # The seam pair is an explicit adjacency edge; the offset in the two
        # canvases' local coordinate systems is not the physical direction,
        # so it is offered for every direction (the heap's state guard makes
        # the extra offers free).
        seam_key = (cidx, ci, cj, r, c)
        if seam_key in seam:
            scid, sci, scj, sr, sc = seam[seam_key]
            return (scid, sci, scj), sr, sc
        return None

    def outlet(key: Hashable, r: int, c: int) -> bool:
        cidx, ci, cj = cast("tuple[int, int, int]", key)
        grid = grids[cidx]
        gr, gc = ci * t + r, cj * t + c
        nrows, ncols = grid.shape
        if (cidx, ci, cj, r, c) in seam:
            return False  # seam pixels are coupled, never outlets
        if gr in (0, nrows - 1) or gc in (0, ncols - 1):
            return True
        return any(neighbour(key, r, c, dy, dx) is None for dy, dx in _NEIGHBOURS)

    filled = _flood_graph(tiles, neighbour, outlet, sea_level=sea_level, eps=eps)
    a.filled = {}
    b.filled = {}
    for key, arr in filled.items():
        cidx, ci, cj = cast("tuple[int, int, int]", key)
        if cidx == 0:
            a.filled[(ci, cj)] = arr
        else:
            b.filled[(ci, cj)] = arr
