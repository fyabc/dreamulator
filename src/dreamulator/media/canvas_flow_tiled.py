"""Out-of-core S2 flow fields: flat distances, baseline directions and chunked accumulation.

The in-memory path (:func:`dreamulator.media.canvas_pipeline.canvas_flow_fields`) assembles the
whole canvas bounding box; a continent-sized canvas does not fit (world-west: 18.8 G pixels,
about 42 bytes each at the rivers stage).  This module produces the same fields one chunk at a
time, with memory bounded by a few chunks and a small cross-chunk graph:

* **Graded flats.**  The PF+ε ramp of ``_grade_flats`` gives every cell of an equal-value flat the
  level ``v + ε + ... + ε`` (``d`` additions in float64) where ``d`` is its 8-connected step count,
  through cells of the same value, to the nearest seed (a cell at or below sea level, or one with
  a strictly lower neighbour).  ``d`` is a geodesic distance, so it is solved per chunk by
  breadth-first search and exchanged across chunk seams until no chunk changes; the level is then
  rebuilt by the same additions, bit-for-bit equal to the whole-canvas kernel.
* **Directions.**  This module supplies the D8 baseline. Formal S2 replaces it through
  ``canvas_routing`` using unmodified height and integer flat distances. Consumers
  decode ``FLOW_OFFSETS``: codes 0-7 retain the D8 order, codes 8-15 hold the primitive
  two-ring offsets, and 255 means no receiver. Halo rings and chunk-exit tables carry two
  layers so an extended edge can land in the neighbouring chunk's second row or column.
* **Flow accumulation** (Barnes 2017, Environmental Modelling & Software 92:202-212): each chunk
  accumulates its own weights with outgoing links cut, the border transfers are solved on the graph
  of chunk exits in topological order, and the incoming flow is folded back by a second local
  accumulation.  Sums are float64; they equal the whole-canvas float64 accumulation to round-off.

Files live under ``<work>/flow/``: ``graded`` (float32), ``dir`` (uint8), ``acc_<name>`` (float32).
"""

from __future__ import annotations

import errno
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

import numba
import numpy as np

from dreamulator.map.river_routing import KNIGHT_OFFSETS
from dreamulator.media.canvas_hydrology import _NEIGHBOURS

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from dreamulator.media.canvas_pipeline import CanvasStore

NO_DIR = np.uint8(255)
FLOW_OFFSETS = np.vstack((np.asarray(_NEIGHBOURS, dtype=np.int64), KNIGHT_OFFSETS))
_DY = FLOW_OFFSETS[:, 0].copy()
_DX = FLOW_OFFSETS[:, 1].copy()
_UNREACHED = np.int32(2**31 - 1)


# ---------------------------------------------------------------------------
# layout
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChunkLayout:
    """Chunk keys of a canvas, the tile size and the bounding box they span."""

    tile: int
    keys: tuple[tuple[int, int], ...]

    @property
    def keyset(self) -> frozenset[tuple[int, int]]:
        return frozenset(self.keys)

    @property
    def shape(self) -> tuple[int, int]:
        return (
            (max(k[0] for k in self.keys) + 1) * self.tile,
            (max(k[1] for k in self.keys) + 1) * self.tile,
        )

    @classmethod
    def of(cls, store: CanvasStore) -> ChunkLayout:
        return cls(store.tile, tuple(sorted(store.chunks)))


def flow_path(store: CanvasStore, kind: str, key: tuple[int, int], ext: str = "npy") -> Path:
    return store.work / "flow" / kind / f"r{key[0]:03d}_c{key[1]:03d}.{ext}"


def _ring(a: np.ndarray) -> np.ndarray:
    """Two border layers, grouped as top, bottom, left and right bands."""
    radius = min(2, a.shape[0])
    return np.concatenate(
        [a[:radius].ravel(), a[-radius:].ravel(), a[:, :radius].ravel(), a[:, -radius:].ravel()]
    )


#: Retries for a chunk read that hits a stale handle, and the backoff between them.
_LOAD_RETRIES = 8
_LOAD_BACKOFF_S = 0.05

#: A Windows reader holding the old file blocks the rename, and a reader can be
#: refused while the rename is in flight; both clear in milliseconds.
_SHARING_ERRNOS = (errno.EACCES, errno.EPERM, errno.EBUSY)


def _atomic_save(path: Path, a: np.ndarray) -> None:
    """Write then rename: a concurrent reader sees the old file or the new one, never half."""
    import os
    import time

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    with open(tmp, "wb") as f:
        np.save(f, a)
    delay = _LOAD_BACKOFF_S
    for attempt in range(_LOAD_RETRIES):
        try:
            os.replace(tmp, path)
            return
        except OSError as exc:
            if exc.errno not in _SHARING_ERRNOS or attempt == _LOAD_RETRIES - 1:
                raise
            time.sleep(delay)
            delay *= 2


def save_chunk(store: CanvasStore, kind: str, key: tuple[int, int], a: np.ndarray) -> None:
    """Save a chunk array and its two-layer border ring for neighbouring halos."""
    path = flow_path(store, kind, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_save(path, a)
    _atomic_save(flow_path(store, kind, key, "ring.npy"), _ring(a))


def load_npy(path: Path, *, mmap_mode: Literal["r"] | None = None) -> np.ndarray:
    """Load a chunk file, retrying while the file is briefly unavailable.

    Chunk files are published by writing a temporary and renaming it, which is atomic on a
    local filesystem: a concurrent reader gets either the old inode or the new one.  On a
    network filesystem (the shared CPFS mount these canvases live on) a client whose cached
    directory entry still points at the replaced inode gets ESTALE instead, and the whole
    stage died on it after an hour of a world-sized run.  On Windows a reader can be refused
    with EACCES while another process replaces the target, and the writer's rename can be
    refused while a reader holds the old file.  In both cases the rename has already happened
    or is about to, so retrying after a short backoff returns the new file.
    """
    import time

    delay = _LOAD_BACKOFF_S
    for attempt in range(_LOAD_RETRIES):
        try:
            return np.asarray(np.load(path, mmap_mode=mmap_mode))
        except OSError as exc:  # ESTALE, the ENOENT a rename can show, and Windows sharing
            if (
                exc.errno not in (errno.ESTALE, errno.ENOENT, *_SHARING_ERRNOS)
                or attempt == _LOAD_RETRIES - 1
            ):
                raise
            time.sleep(delay)
            delay *= 2
    raise AssertionError("unreachable")


def load_chunk(store: CanvasStore, kind: str, key: tuple[int, int]) -> np.ndarray:
    return load_npy(flow_path(store, kind, key))


def halo(
    store: CanvasStore,
    layout: ChunkLayout,
    kind: str,
    key: tuple[int, int],
    fill: float,
    dtype: type = np.float32,
    center: np.ndarray | None = None,
    *,
    radius: int = 1,
) -> np.ndarray:
    """Add one or two halo layers; old single-layer rings remain readable."""
    t = layout.tile
    if radius not in (1, 2) or radius > t:
        raise ValueError("halo radius must be one or two pixels and no larger than a tile")
    out: np.ndarray = np.full((t + 2 * radius, t + 2 * radius), fill, dtype=dtype)
    out[radius : radius + t, radius : radius + t] = (
        load_chunk(store, kind, key) if center is None else center
    )
    keys = layout.keyset
    ci, cj = key
    for di in (-1, 0, 1):
        for dj in (-1, 0, 1):
            nk = (ci + di, cj + dj)
            if (di == 0 and dj == 0) or nk not in keys:
                continue
            ring = load_npy(flow_path(store, kind, nk, "ring.npy"))
            saved_radius = ring.size // (4 * t)
            if saved_radius not in (1, 2) or ring.size != 4 * t * saved_radius:
                raise ValueError("invalid saved halo ring")
            if saved_radius < radius:
                # Legacy stores only saved one layer. Memory mapping reads the
                # required boundary slices without loading an entire neighbour.
                a = load_npy(flow_path(store, kind, nk), mmap_mode="r")
                top, bottom, left, right = a[:radius], a[-radius:], a[:, :radius], a[:, -radius:]
            else:
                size = t * saved_radius
                top = ring[:size].reshape(saved_radius, t)[:radius]
                bottom = ring[size : 2 * size].reshape(saved_radius, t)[-radius:]
                left = ring[2 * size : 3 * size].reshape(t, saved_radius)[:, :radius]
                right = ring[3 * size :].reshape(t, saved_radius)[:, -radius:]
            if di == -1 and dj == 0:
                out[:radius, radius : radius + t] = bottom
            elif di == 1 and dj == 0:
                out[-radius:, radius : radius + t] = top
            elif di == 0 and dj == -1:
                out[radius : radius + t, :radius] = right
            elif di == 0 and dj == 1:
                out[radius : radius + t, -radius:] = left
            else:  # corners
                row = bottom if di == -1 else top
                rs = slice(None, radius) if di == -1 else slice(-radius, None)
                cs = slice(None, radius) if dj == -1 else slice(-radius, None)
                out[rs, cs] = row[:, -radius:] if dj == -1 else row[:, :radius]
    return out


@dataclass
class _Ctx:
    root: Path
    work: Path
    tile: int
    keys: tuple[tuple[int, int], ...]
    sea_level: float = 0.0
    eps: float = 1e-3
    land_floor: float = 0.0
    healed: dict[tuple[int, int], np.ndarray] | None = None
    runoff: np.ndarray | None = None  # coarse runoff (mm/yr), already cropped to the bbox cells
    weight_kind: str = ""
    dir_kind: str = "dir"
    acc_kind: str = ""
    acc_f64: bool = False
    increments: Path | None = None  # installed-surface increments (erosion product) or None
    extra: dict[str, Any] | None = None  # stage-specific shared inputs (small or shared by fork)
    open_edges: bool = False


_CTX: _Ctx | None = None


def _store_of(ctx: _Ctx) -> CanvasStore:
    from types import SimpleNamespace

    return SimpleNamespace(work=ctx.work, root=ctx.root, tile=ctx.tile, chunks=list(ctx.keys))  # type: ignore[return-value]


def _init(ctx: _Ctx) -> None:
    global _CTX
    numba.set_num_threads(1)  # type: ignore[no-untyped-call]  # the pool is the parallelism
    _CTX = ctx


def _pool_scope(ctx: _Ctx, workers: int) -> Any:
    """A pool anchored for a whole stage, or ``None`` for the serial path.

    Workers cost about a second each to start (they import numba), so a stage
    that maps many times — the seam rounds of ``tiled_graded`` — keeps one pool
    instead of building a new one per round.
    """
    import contextlib

    @contextlib.contextmanager
    def scope() -> Any:
        if workers <= 1:
            _init(ctx)
            yield None
            return
        import multiprocessing as mp
        from concurrent.futures import ProcessPoolExecutor

        from dreamulator.media.canvas_pipeline import _start_method

        with ProcessPoolExecutor(
            max_workers=workers,
            mp_context=mp.get_context(_start_method()),
            initializer=_init,
            initargs=(ctx,),
        ) as pool:
            yield pool

    return scope()


def _pool_map(
    fn: Callable[[Any], Any],
    items: list[Any],
    ctx: _Ctx,
    workers: int,
    pool: Any = None,
) -> list[Any]:
    if pool is not None:
        return list(pool.map(fn, items, chunksize=1))
    if workers <= 1 or len(items) < 2:
        _init(ctx)
        return [fn(it) for it in items]
    import multiprocessing as mp
    from concurrent.futures import ProcessPoolExecutor

    from dreamulator.media.canvas_pipeline import _start_method

    with ProcessPoolExecutor(
        max_workers=min(workers, len(items)),
        mp_context=mp.get_context(_start_method()),
        initializer=_init,
        initargs=(ctx,),
    ) as pool:
        return list(pool.map(fn, items, chunksize=1))


def _default_workers(tile: int, workers: int | None = None, *, cap: int | None = None) -> int:
    from dreamulator.utils.resources import worker_budget

    # A few float64 chunk-sized arrays per process; cap the actual pool by its task count.
    return worker_budget(64.0 * (tile + 2) ** 2, requested_workers=workers, cap=cap)


# ---------------------------------------------------------------------------
# graded flats
# ---------------------------------------------------------------------------


@numba.njit(cache=True)
def _seed_dist(
    v: np.ndarray, sea_level: float, open_edges: bool = False
) -> np.ndarray:  # pragma: no cover - numba
    """Step count 0 at seeds of the haloed values ``v``; unreached elsewhere (interior only)."""
    nr, n = v.shape
    d = np.full((nr, n), 2**31 - 1, dtype=np.int32)
    for r in range(1, nr - 1):
        for c in range(1, n - 1):
            x = v[r, c]
            if not np.isfinite(x):
                continue
            if x <= sea_level:
                d[r, c] = 0
                continue
            for k in range(8):
                y = v[r + _DY[k], c + _DX[k]]
                if y < x - 1e-9 or (open_edges and not np.isfinite(y)):
                    d[r, c] = 0
                    break
    return d


@numba.njit(cache=True)
def _flat_bfs(v: np.ndarray, d: np.ndarray) -> bool:  # pragma: no cover - numba
    """Relax step counts inside the halo frame; halo cells are fixed sources.  Returns changed."""
    nr, n = v.shape
    big = 2**31 - 1
    # bucket queue over distance values: cells are pushed when their d improves
    qcap = nr * n * 2
    queue = np.empty(qcap, dtype=np.int64)
    head = 0
    tail = 0
    for r in range(nr):
        for c in range(n):
            if d[r, c] < big:
                queue[tail] = r * n + c
                tail += 1
    # sort initial sources by distance (counting sort over small range is not guaranteed;
    # Dijkstra with unit weights from mixed sources: process in passes by distance)
    changed = False
    order = np.argsort(d.ravel()[queue[:tail]], kind="mergesort")
    src = queue[:tail][order].copy()
    head = 0
    tail = 0
    cur = np.empty(qcap, dtype=np.int64)
    i = 0
    m = src.size
    while i < m or head < tail:
        # next frontier distance: smallest of the pending source and the queue head
        if head < tail:
            c0 = cur[head]
            dq = d[c0 // n, c0 % n]
        else:
            dq = big
        if i < m:
            s0 = src[i]
            ds = d[s0 // n, s0 % n]
        else:
            ds = big
        if ds <= dq:
            cell = src[i]
            i += 1
        else:
            cell = cur[head]
            head += 1
        r = cell // n
        c = cell % n
        dc = d[r, c]
        x = v[r, c]
        for k in range(8):
            rr = r + _DY[k]
            cc = c + _DX[k]
            if rr < 1 or rr >= nr - 1 or cc < 1 or cc >= n - 1:
                continue
            if v[rr, cc] != x:
                continue
            if dc + 1 < d[rr, cc]:
                d[rr, cc] = dc + 1
                cur[tail] = rr * n + cc
                tail += 1
                changed = True
    return changed


@numba.njit(cache=True)
def _levels(v: np.ndarray, d: np.ndarray, eps: float) -> np.ndarray:  # pragma: no cover - numba
    """float32(v + eps + ... + eps) with ``d`` float64 additions; ``v`` where unreached.

    The additions are replayed once per distinct value up to that value's largest ``d`` (a
    ragged table), so a wide flat costs its own extent, not the chunk's.
    """
    t = v.shape[0]
    big = 2**31 - 1
    flat = v.ravel()
    dd = d.ravel()
    vals = np.unique(flat[np.isfinite(flat)])
    nv = vals.size
    dmax = np.zeros(nv, dtype=np.int64)
    idx = np.full(flat.size, -1, dtype=np.int64)
    for c in range(flat.size):
        x = flat[c]
        if not np.isfinite(x) or dd[c] == big:
            continue
        vi = np.searchsorted(vals, x)
        idx[c] = vi
        if dd[c] > dmax[vi]:
            dmax[vi] = dd[c]
    start = np.zeros(nv + 1, dtype=np.int64)
    for vi in range(nv):
        start[vi + 1] = start[vi] + dmax[vi] + 1
    tab = np.empty(start[nv], dtype=np.float64)
    for vi in range(nv):
        lv = np.float64(vals[vi])
        tab[start[vi]] = lv
        for k in range(1, dmax[vi] + 1):
            lv = lv + eps
            tab[start[vi] + k] = lv
    out = np.empty(flat.size, dtype=np.float32)
    for c in range(flat.size):
        vi = idx[c]
        if vi < 0:
            out[c] = flat[c]
            continue
        lv = tab[start[vi] + dd[c]]
        x = np.float64(flat[c])
        out[c] = np.float32(lv if lv > x else x)
    return out.reshape(t, t)


def _final_rings(key: tuple[int, int]) -> None:
    ctx = _CTX
    assert ctx is not None
    v = np.asarray(load_npy(_final_path(ctx, key)), np.float32)
    _atomic_save(flow_path(_store_of(ctx), "final", key, "ring.npy"), _ring(v))


def _final_path(ctx: _Ctx, key: tuple[int, int]) -> Path:
    return ctx.work / "final" / f"r{key[0]:03d}_c{key[1]:03d}.f32.npy"


def _final(ctx: _Ctx, key: tuple[int, int]) -> np.ndarray:
    return np.asarray(load_npy(_final_path(ctx, key)), np.float32)


def _graded_seed(key: tuple[int, int]) -> None:
    ctx = _CTX
    assert ctx is not None
    st = _store_of(ctx)
    layout = ChunkLayout(ctx.tile, ctx.keys)
    v = halo(st, layout, "final", key, np.nan, center=_final(ctx, key))
    d = _seed_dist(v, ctx.sea_level, ctx.open_edges)
    _flat_bfs(v, d)
    save_chunk(st, "dist", key, d[1:-1, 1:-1])


def _graded_round(key: tuple[int, int]) -> bool:
    """Relax one chunk from its neighbours' current seam distances; True if a border cell moved."""
    ctx = _CTX
    assert ctx is not None
    st = _store_of(ctx)
    layout = ChunkLayout(ctx.tile, ctx.keys)
    v = halo(st, layout, "final", key, np.nan, center=_final(ctx, key))
    dh = halo(st, layout, "dist", key, float(_UNREACHED), dtype=np.int32)
    before = dh[1:-1, 1:-1].copy()
    if not _flat_bfs(v, dh):
        return False
    new = dh[1:-1, 1:-1]
    if np.array_equal(new, before):
        return False
    save_chunk(st, "dist", key, new)
    return not np.array_equal(_ring(new), _ring(before))


def _graded_levels(key: tuple[int, int]) -> None:
    ctx = _CTX
    assert ctx is not None
    st = _store_of(ctx)
    v = _final(ctx, key)
    d = load_chunk(st, "dist", key)
    save_chunk(st, "graded", key, v if ctx.eps == 0 else _levels(v, d, ctx.eps))


def _ctx_of(store: CanvasStore, sea_level: float = 0.0, eps: float = 1e-3) -> _Ctx:
    return _Ctx(
        root=store.root,
        work=store.work,
        tile=store.tile,
        keys=tuple(sorted(store.chunks)),
        sea_level=sea_level,
        eps=eps,
    )


def tiled_graded(
    store: CanvasStore,
    *,
    sea_level: float = 0.0,
    eps: float = 1e-3,
    workers: int | None = None,
    log: Callable[[str], None] | None = None,
    keep_dist: bool = False,
    open_edges: bool = False,
) -> int:
    """Write ``flow/graded`` for every chunk; returns the number of seam-exchange rounds."""
    ctx = _ctx_of(store, sea_level, eps)
    ctx.open_edges = open_edges
    layout = ChunkLayout(ctx.tile, ctx.keys)
    n = _default_workers(ctx.tile, workers, cap=len(ctx.keys))
    keys = list(layout.keys)
    with _pool_scope(ctx, n) as pool:
        _pool_map(_final_rings, keys, ctx, n, pool)
        _pool_map(_graded_seed, keys, ctx, n, pool)
        pending = set(keys)
        rounds = 0
        while pending:
            rounds += 1
            todo = sorted(pending)
            moved = _pool_map(_graded_round, todo, ctx, n, pool)
            pending = set()
            for key, m in zip(todo, moved, strict=True):
                if not m:
                    continue
                ci, cj = key
                for di in (-1, 0, 1):
                    for dj in (-1, 0, 1):
                        nk = (ci + di, cj + dj)
                        if nk != key and nk in layout.keyset:
                            pending.add(nk)
            if log is not None:
                log(f"[flow] graded flats: seam round {rounds}, {len(pending)} chunks to revisit")
        _pool_map(_graded_levels, keys, ctx, n, pool)
    if not keep_dist:
        drop_kinds(store, "dist")
    return rounds


# ---------------------------------------------------------------------------
# D8 directions
# ---------------------------------------------------------------------------


def _direction_chunk(key: tuple[int, int]) -> None:
    """D8 code, land mask and runoff weight of one chunk (the in-memory rules, chunk-local)."""
    from dreamulator.map.prog_erosion import RUNOFF_REFERENCE_MM
    from dreamulator.map.td_canvas import PX_PER_CELL

    ctx = _CTX
    assert ctx is not None
    st = _store_of(ctx)
    layout = ChunkLayout(ctx.tile, ctx.keys)
    t = ctx.tile
    g = halo(st, layout, "graded", key, np.nan)
    fb = g[1:-1, 1:-1]
    best = np.zeros(fb.shape, dtype=np.float64)
    code = np.full(fb.shape, 255, dtype=np.uint8)
    diag = 2**0.5
    for k, (dy, dx) in enumerate(_NEIGHBOURS):
        nb = g[1 + dy : 1 + dy + t, 1 + dx : 1 + dx + t]
        slope = (fb - nb) / (diag if dy and dx else 1.0)
        better = np.isfinite(slope) & (nb < fb) & (slope > best)
        best = np.where(better, slope, best)
        code = np.where(better, np.uint8(k), code)
    land = np.isfinite(fb) & (fb >= ctx.land_floor)
    if ctx.healed is not None and key in ctx.healed:
        land.reshape(-1)[ctx.healed[key]] = True
    code[~land] = 255
    save_chunk(st, "dir", key, code)
    save_chunk(st, "land", key, land.astype(np.uint8))
    if ctx.runoff is not None:
        f = PX_PER_CELL
        rows = (key[0] * t + np.arange(t)) // f
        cols = (key[1] * t + np.arange(t)) // f
        nr, nc = ctx.runoff.shape
        w = np.zeros((t, t), dtype=np.float32)
        rv, cv = rows < nr, cols < nc
        w[np.ix_(rv, cv)] = ctx.runoff[np.ix_(rows[rv], cols[cv])] / RUNOFF_REFERENCE_MM
        w[~land] = 0.0
    else:
        w = land.astype(np.float32)
    save_chunk(st, "w_runoff", key, w)


def drop_kinds(store: CanvasStore, *kinds: str) -> None:
    """Delete the chunk files of scratch kinds nothing reads once their stage is done.

    The out-of-core chain writes about twenty kinds per chunk; most are a stage's own working
    state (the flat distances, the wet/deep component labels, the cut routings).  On a
    377M-cell canvas they come to several GB, and on a world-sized canvas to tens, so each
    stage drops its own as soon as the last reader of it has run.
    """
    for kind in kinds:
        d = store.work / "flow" / kind
        if not d.is_dir():
            continue
        for path in sorted(d.glob("*")):
            path.unlink()
        d.rmdir()


def healed_by_chunk(store: CanvasStore) -> dict[tuple[int, int], np.ndarray] | None:
    """Healed inland-pit cells (land for routing), split into chunk-local indices."""
    from dreamulator.media.canvas_pipeline import _declares_sea_mask

    heal_path = store.work / "heal.npz"
    if not heal_path.exists() or _declares_sea_mask(store):
        return None
    layout = ChunkLayout.of(store)
    t = layout.tile
    w = layout.shape[1]
    idx = np.asarray(np.load(heal_path)["idx"], dtype=np.int64)
    r, c = idx // w, idx % w
    ci, cj = r // t, c // t
    out: dict[tuple[int, int], np.ndarray] = {}
    for key in set(zip(ci.tolist(), cj.tolist(), strict=True)):
        m = (ci == key[0]) & (cj == key[1])
        out[key] = (r[m] % t) * t + c[m] % t
    return out


def runoff_on_bbox(store: CanvasStore) -> np.ndarray | None:
    """The coarse runoff cells the chunk bounding box covers (the in-memory crop rule)."""
    from dreamulator.map.td_canvas import PX_PER_CELL

    path = store.root / "climate" / "runoff.mm.npy"
    if not path.exists():
        return None
    coarse = np.maximum(np.nan_to_num(np.load(path).astype(np.float32), nan=0.0), 0.0)
    h, w = ChunkLayout.of(store).shape
    return np.ascontiguousarray(coarse[: h // PX_PER_CELL, : w // PX_PER_CELL])


def tiled_directions(
    store: CanvasStore,
    *,
    sea_level: float = 0.0,
    workers: int | None = None,
) -> None:
    """Write ``flow/dir`` (uint8 index into ``_NEIGHBOURS``, 255 = none), ``flow/land`` and
    ``flow/w_runoff`` (reference-normalised runoff weight) from ``flow/graded``."""
    from dreamulator.map.td_canvas_mosaic import INTERTIDAL_M

    ctx = _ctx_of(store, sea_level)
    ctx.land_floor = sea_level if INTERTIDAL_M is None else sea_level + INTERTIDAL_M[0]
    ctx.healed = healed_by_chunk(store)
    ctx.runoff = runoff_on_bbox(store)
    n = _default_workers(ctx.tile, workers, cap=len(ctx.keys))
    _pool_map(_direction_chunk, list(ctx.keys), ctx, n)


# ---------------------------------------------------------------------------
# flow accumulation (Barnes 2017)
# ---------------------------------------------------------------------------


@numba.njit(cache=True)
def _local_receivers(code: np.ndarray) -> tuple[np.ndarray, np.ndarray]:  # pragma: no cover
    """Decode either direction set into local receivers and outgoing direction codes."""
    t = code.shape[0]
    rec = np.full(t * t, -1, dtype=np.int64)
    out = np.full(t * t, -1, dtype=np.int8)
    for r in range(t):
        for c in range(t):
            k = code[r, c]
            if k == 255:
                continue
            if k >= len(_DY):
                raise ValueError("invalid flow direction code")
            rr = r + _DY[k]
            cc = c + _DX[k]
            if 0 <= rr < t and 0 <= cc < t:
                rec[r * t + c] = rr * t + cc
            else:
                out[r * t + c] = k
    return rec, out


@numba.njit(cache=True)
def _accumulate(order: np.ndarray, rec: np.ndarray, w: np.ndarray) -> np.ndarray:  # pragma: no cov
    acc = w.copy()
    for a in range(order.size - 1, -1, -1):
        i = order[a]
        r = rec[i]
        if r >= 0:
            acc[r] += acc[i]
    return acc


@numba.njit(cache=True)
def _exit_of(order: np.ndarray, rec: np.ndarray, out: np.ndarray) -> np.ndarray:  # pragma: no cover
    """Cell whose outgoing link a cell's water leaves the chunk through (-1: a sink inside)."""
    ex = np.full(rec.size, -1, dtype=np.int64)
    for a in range(order.size):  # downstream first: a receiver is resolved before its donors
        i = order[a]
        if out[i] >= 0:
            ex[i] = i
        elif rec[i] >= 0:
            ex[i] = ex[rec[i]]
    return ex


def chunk_order(st: CanvasStore, key: tuple[int, int]) -> np.ndarray:
    """Downstream-first order of a chunk's cells, memoised under ``flow/order``.

    With integer flat ranks, the order sorts height then rank; the D8 research reference uses
    the graded surface alone. Direction regeneration clears this cache. The monthly regime
    accumulates twenty-four times; recomputing the sort each time dominated that stage.
    ``flow/order`` is a cache:
    deleting it only costs the sorts again.
    """
    p = flow_path(st, "order", key)
    if p.exists():
        return load_npy(p).astype(np.int64)
    g = load_chunk(st, "graded", key).ravel()
    rank_path = flow_path(st, "flat_rank", key)
    if rank_path.exists():
        order = np.lexsort((load_npy(rank_path).ravel(), g))
    else:
        order = np.argsort(np.where(np.isfinite(g), g, np.inf), kind="stable")
    _atomic_save(p, order.astype(np.int32))
    return order


def _local(
    st: CanvasStore, key: tuple[int, int], dir_kind: str = "dir"
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    code = load_chunk(st, dir_kind, key)
    order = chunk_order(st, key)
    rec, out = _local_receivers(code)
    return order, rec, out


def _ring_index(t: int) -> np.ndarray:
    """All cells in the two-layer boundary band, including second-layer targets."""
    r = np.arange(t)
    band = np.arange(min(2, t))
    return np.unique(
        np.concatenate(
            [
                (band[:, None] * t + r).ravel(),
                ((t - 1 - band[:, None]) * t + r).ravel(),
                (r[:, None] * t + band).ravel(),
                (r[:, None] * t + t - 1 - band).ravel(),
            ]
        )
    )


def _acc_stage1(key: tuple[int, int]) -> tuple[Any, ...]:
    ctx = _CTX
    assert ctx is not None
    st = _store_of(ctx)
    t = ctx.tile
    keys = frozenset(ctx.keys)
    order, rec, out = _local(st, key, ctx.dir_kind)
    w = load_chunk(st, ctx.weight_kind, key).astype(np.float64).ravel()
    acc1 = _accumulate(order, rec, w)
    _atomic_save(flow_path(st, ctx.acc_kind, key, "stage1.npy"), acc1)
    g = load_chunk(st, "graded", key).ravel()
    src, tgt_key, tgt_idx, amount, level = [], [], [], [], []
    for i in np.flatnonzero(out >= 0):
        k = int(out[i])
        r, c = divmod(int(i), t)
        gr, gc = key[0] * t + r + int(_DY[k]), key[1] * t + c + int(_DX[k])
        if gr < 0 or gc < 0:
            continue
        tk = (gr // t, gc // t)
        if tk not in keys:
            continue  # leaves the canvas or enters a missing chunk: nothing to hand on
        src.append(int(i))
        tgt_key.append(tk)
        tgt_idx.append((gr % t) * t + gc % t)
        amount.append(float(acc1[i]))
        level.append(float(g[i]))
    ex = _exit_of(order, rec, out)[_ring_index(t)]
    return key, src, tgt_key, tgt_idx, amount, level, ex


def _acc_stage3(task: tuple[Any, ...]) -> None:
    key, idx, val = task
    ctx = _CTX
    assert ctx is not None
    st = _store_of(ctx)
    t = ctx.tile
    p1 = flow_path(st, ctx.acc_kind, key, "stage1.npy")
    acc = load_npy(p1)
    if len(idx):
        order, rec, _out = _local(st, key, ctx.dir_kind)
        inflow = np.zeros(t * t, dtype=np.float64)
        np.add.at(inflow, np.asarray(idx, dtype=np.int64), np.asarray(val, dtype=np.float64))
        acc = acc + _accumulate(order, rec, inflow)
    out_arr = acc.reshape(t, t)
    save_chunk(st, ctx.acc_kind, key, out_arr if ctx.acc_f64 else out_arr.astype(np.float32))
    p1.unlink()


def tiled_accumulation(
    store: CanvasStore,
    weight_kind: str,
    *,
    dir_kind: str = "dir",
    out_kind: str | None = None,
    float64: bool = False,
    workers: int | None = None,
    log: Callable[[str], None] | None = None,
) -> None:
    """Write ``flow/<out_kind>`` (default ``acc_<weight_kind>``): float64 upstream sums of the
    ``flow/<weight_kind>`` chunks along ``flow/<dir_kind>``, stored float32 unless ``float64``."""
    ctx = _ctx_of(store)
    ctx.weight_kind = weight_kind
    ctx.dir_kind = dir_kind
    ctx.acc_kind = out_kind or f"acc_{weight_kind}"
    ctx.acc_f64 = float64
    t = ctx.tile
    n = _default_workers(t, workers, cap=len(ctx.keys))
    t0 = time.time()
    (store.work / "flow" / ctx.acc_kind).mkdir(parents=True, exist_ok=True)
    with _pool_scope(ctx, n) as pool:
        res = _pool_map(_acc_stage1, list(ctx.keys), ctx, n, pool)
        ring = _ring_index(t)
        ring_pos = {int(c): p for p, c in enumerate(ring)}  # first position of each ring cell
        exits: dict[tuple[int, int], np.ndarray] = {}
        links: list[tuple[tuple[int, int], int, tuple[int, int], int, float, float]] = []
        for key, src, tk, ti, amt, lev, ex in res:
            exits[key] = ex
            links.extend(zip([key] * len(src), src, tk, ti, amt, lev, strict=True))
        node_of = {(lk[0], lk[1]): li for li, lk in enumerate(links)}
        next_link = np.full(len(links), -1, dtype=np.int64)
        for li, (_sk, _si, tk, ti, _a, _lv) in enumerate(links):
            e = int(exits[tk][ring_pos[ti]])
            if e >= 0:
                next_link[li] = node_of.get((tk, e), -1)
        total = np.array([lk[4] for lk in links], dtype=np.float64)
        from dreamulator.media.canvas_routing import downstream_order

        for li in downstream_order(next_link)[::-1]:
            nl = int(next_link[li])
            if nl >= 0:
                total[nl] += total[li]
        inflow: dict[tuple[int, int], tuple[list[int], list[float]]] = {
            k: ([], []) for k in ctx.keys
        }
        for li, (_sk, _si, tk, ti, _a, _lv) in enumerate(links):
            inflow[tk][0].append(ti)
            inflow[tk][1].append(float(total[li]))
        _pool_map(_acc_stage3, [(k, *inflow[k]) for k in ctx.keys], ctx, n, pool)
    if log is not None:
        log(
            f"[flow] accumulation {weight_kind}: {len(links)} border links, "
            f"{time.time() - t0:.0f} s"
        )
