"""Constrained two-ring canvas routing, with integer flat ranks and scanline arbitration.

The physical filled surface stays unchanged. Equal-height D8 links descend in
integer distance to an outlet. Two-ring candidates use the regional terrain and
water checks; crossing arbitration scans global rows in a fixed order, keeping
only a small strip of direction bytes in memory.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numba
import numpy as np

from dreamulator.map.river_routing import KNIGHT_OFFSETS, clear_descent, crosses
from dreamulator.media import canvas_flow_tiled as cft

if TYPE_CHECKING:
    from collections.abc import Callable

    from dreamulator.media.canvas_pipeline import CanvasStore


@numba.njit(cache=True)
def downstream_order(receiver: np.ndarray) -> np.ndarray:
    """Topological order, receivers first; reject invalid targets and cycles."""
    n = receiver.size
    degree = np.zeros(n, np.int32)
    queue = np.empty(n, np.int64)
    for target in receiver:
        if target < -1 or target >= n:
            raise ValueError("receiver outside graph")
        if target >= 0:
            degree[target] += 1
    head, tail = 0, 0
    for cell in range(n):
        if degree[cell] == 0:
            queue[tail] = cell
            tail += 1
    while head < tail:
        cell = queue[head]
        head += 1
        target = receiver[cell]
        if target >= 0:
            degree[target] -= 1
            if degree[target] == 0:
                queue[tail] = target
                tail += 1
    if tail != n:
        raise ValueError("flow graph contains a cycle")
    return queue[::-1].copy()


@numba.njit(cache=True)
def flat_d8_codes(height: np.ndarray, rank: np.ndarray, land: np.ndarray) -> np.ndarray:
    """D8 on a one-layer padded surface; flat links reduce the separate integer rank."""
    rows, columns = height.shape
    code = np.full(height.shape, 255, np.uint8)
    for r in range(1, rows - 1):
        for c in range(1, columns - 1):
            if not land[r, c]:
                continue
            best = 0.0
            for k in range(8):
                dy, dx = cft.FLOW_OFFSETS[k]
                delta = height[r, c] - height[r + dy, c + dx]
                slope = delta / np.hypot(dy, dx)
                if np.isfinite(slope) and slope > best:
                    best, code[r, c] = slope, k
            if code[r, c] != 255 or rank[r, c] == 2**31 - 1:
                continue
            best = 0.0
            for k in range(8):
                dy, dx = cft.FLOW_OFFSETS[k]
                if height[r + dy, c + dx] != height[r, c]:
                    continue
                slope = (float(rank[r, c]) - rank[r + dy, c + dx]) / np.hypot(dy, dx)
                if slope > best:
                    best, code[r, c] = slope, k
    return code


@numba.njit(cache=True)
def proposed_codes(height: np.ndarray, stop: np.ndarray, base: np.ndarray) -> np.ndarray:
    """Candidates on a two-layer padded grid, using the accepted regional constraints."""
    out = base.copy()
    rows, columns = height.shape
    for r in range(2, rows - 2):
        for c in range(2, columns - 2):
            k = int(base[r, c])
            if stop[r, c] or k == 255:
                continue
            dy, dx = cft.FLOW_OFFSETS[k]
            best = (height[r, c] - height[r + dy, c + dx]) / np.hypot(dy, dx)
            if best <= 0:
                continue
            for extra in range(len(KNIGHT_OFFSETS)):
                dr, dc = KNIGHT_OFFSETS[extra]
                slope = (height[r, c] - height[r + dr, c + dc]) / np.sqrt(5.0)
                if slope > best and clear_descent(height, stop, r, c, dr, dc):
                    best = slope
                    out[r, c] = 8 + extra
    return out


@numba.njit(cache=True)
def prune_code_rows(current: np.ndarray, proposed: np.ndarray, start: int, end: int) -> int:
    """Greedy global row-major arbitration; a four-row context covers all edge crossings.

    Earlier rows contain accepted directions; later rows retain baseline D8.
    The same kernel consumes whole-grid arrays and file-backed scanline bands.
    """
    rows, columns = current.shape
    rejected = 0
    for r in range(start, end):
        for c in range(columns):
            code = int(proposed[r, c])
            if code == current[r, c] or code == 255:
                continue
            dy, dx = cft.FLOW_OFFSETS[code]
            cell, target = r * columns + c, (r + dy) * columns + c + dx
            conflict = False
            for rr in range(max(0, r - 4), min(rows, r + 5)):
                for cc in range(max(0, c - 4), min(columns, c + 5)):
                    other_code = int(current[rr, cc])
                    if (rr == r and cc == c) or other_code == 255:
                        continue
                    dr, dc = cft.FLOW_OFFSETS[other_code]
                    other = rr * columns + cc
                    down = (rr + dr) * columns + cc + dc
                    if crosses(cell, target, other, down, columns):
                        conflict = True
                        break
                if conflict:
                    break
            if conflict:
                rejected += 1
            else:
                current[r, c] = code
    return rejected


def flat_ranks(height: np.ndarray, sea_level: float) -> np.ndarray:
    """Whole-grid reference for the tiled distance exchange, including open frame outlets."""
    padded = np.pad(height, 1, constant_values=np.nan)
    ranks = cft._seed_dist(padded, sea_level, True)
    cft._flat_bfs(padded, ranks)
    return ranks[1:-1, 1:-1].copy()


def whole_grid_routing(
    height: np.ndarray, rank: np.ndarray, land: np.ndarray, water: np.ndarray
) -> tuple[np.ndarray, dict[str, int]]:
    """Whole-grid receiver reference, with the same candidate and scanline kernels as tiles."""
    h1 = np.pad(height, 1, constant_values=np.nan)
    rank1 = np.pad(rank, 1, constant_values=2**31 - 1)
    land1 = np.pad(land, 1, constant_values=False)
    base = flat_d8_codes(h1, rank1, land1)[1:-1, 1:-1].copy()
    h2 = np.pad(height, 2, constant_values=np.nan)
    stop = np.pad(~land | water, 2, constant_values=True)
    proposal = proposed_codes(h2, stop, np.pad(base, 2, constant_values=255))[2:-2, 2:-2]
    changed = int(np.count_nonzero(proposal != base))
    rejected = int(prune_code_rows(base, proposal, 0, height.shape[0]))
    rows, columns = np.indices(height.shape, dtype=np.int64)
    has = base != 255
    k = np.where(has, base, 0)
    offsets = cft.FLOW_OFFSETS[k]
    receiver = np.where(
        has, (rows + offsets[..., 0]) * height.shape[1] + columns + offsets[..., 1], -1
    ).ravel()
    return receiver, {
        "proposed_extensions": changed,
        "crossing_rejected": rejected,
        "accepted_extensions": changed - rejected,
    }


def _base_chunk(key: tuple[int, int]) -> None:
    ctx = cft._CTX
    assert ctx is not None
    store = cft._store_of(ctx)
    layout = cft.ChunkLayout(ctx.tile, ctx.keys)
    rank = cft.load_chunk(store, "dist", key)
    cft.save_chunk(store, "flat_rank", key, rank)
    height = cft.halo(store, layout, "graded", key, np.nan)
    rank_h = cft.halo(store, layout, "dist", key, 2**31 - 1, dtype=np.int32)
    land = cft.halo(store, layout, "land", key, 0, dtype=np.bool_)
    code = flat_d8_codes(height, rank_h, land)[1:-1, 1:-1].copy()
    cft.save_chunk(store, "dir_base", key, code)
    cft.save_chunk(store, "dir", key, code)


def _candidate_chunk(key: tuple[int, int]) -> int:
    ctx = cft._CTX
    assert ctx is not None
    store = cft._store_of(ctx)
    layout = cft.ChunkLayout(ctx.tile, ctx.keys)
    height = cft.halo(store, layout, "graded", key, np.nan, radius=2)
    land = cft.halo(store, layout, "land", key, 0, dtype=np.bool_, radius=2)
    water = cft.halo(store, layout, "lakes0", key, 0, dtype=np.bool_, radius=2)
    base = cft.halo(store, layout, "dir_base", key, 255, dtype=np.uint8, radius=2)
    proposal = proposed_codes(height, ~land | water, base)[2:-2, 2:-2].copy()
    cft.save_chunk(store, "dir_proposed", key, proposal)
    return int(np.count_nonzero(proposal != base[2:-2, 2:-2]))


def _read_band(store: CanvasStore, kind: str, r0: int, r1: int) -> np.ndarray:
    layout = cft.ChunkLayout.of(store)
    out = np.full((r1 - r0, layout.shape[1]), 255, np.uint8)
    t = layout.tile
    for key in layout.keys:
        row, col = key[0] * t, key[1] * t
        a, b = max(row, r0), min(row + t, r1)
        if a < b:
            mapped = cft.load_npy(cft.flow_path(store, kind, key), mmap_mode="r")
            out[a - r0 : b - r0, col : col + t] = mapped[a - row : b - row]
    return out


def _write_band(store: CanvasStore, band: np.ndarray, r0: int) -> None:
    t = store.tile
    r1 = r0 + len(band)
    for key in store.chunks:
        row, col = key[0] * t, key[1] * t
        a, b = max(row, r0), min(row + t, r1)
        if a < b:
            mapped = np.lib.format.open_memmap(cft.flow_path(store, "dir", key), mode="r+")
            mapped[a - row : b - row] = band[a - r0 : b - r0, col : col + t]
            mapped.flush()
            del mapped


def tiled_two_ring_routing(
    store: CanvasStore,
    *,
    workers: int | None = None,
    band_rows: int = 256,
    log: Callable[[str], None] | None = None,
) -> dict[str, int]:
    """Replace baseline directions from exact height, saved distances and protected lakes.

    Call after ``tiled_graded(eps=0, keep_dist=True, open_edges=True)``,
    ``tiled_directions`` (land and runoff), and ``tiled_geometry_lakes``.
    """
    from dreamulator.utils.resources import available_memory_bytes

    layout = cft.ChunkLayout.of(store)
    ctx = cft._ctx_of(store)
    n = cft._default_workers(store.tile, workers, cap=len(ctx.keys))
    cft.drop_kinds(store, "order", "flat_rank")
    cft._pool_map(_base_chunk, list(layout.keys), ctx, n)
    cft.drop_kinds(store, "dist")
    proposed = sum(cft._pool_map(_candidate_chunk, list(layout.keys), ctx, n))
    rows, width = layout.shape
    free = available_memory_bytes()
    if free is not None:
        band_rows = min(band_rows, max(1, int(free * 0.125 / (2 * width)) - 8))
    if band_rows < 1:
        raise ValueError("band_rows must be positive")
    rejected = 0
    for r0 in range(0, rows, band_rows):
        r1 = min(rows, r0 + band_rows)
        a, b = max(0, r0 - 4), min(rows, r1 + 4)
        current = _read_band(store, "dir", a, b)
        candidate = _read_band(store, "dir_proposed", a, b)
        rejected += int(prune_code_rows(current, candidate, r0 - a, r1 - a))
        _write_band(store, current[r0 - a : r1 - a], r0)
    # Main files were updated strip by strip; publish their halo rings after arbitration.
    for key in layout.keys:
        code = cft.load_chunk(store, "dir", key)
        cft._atomic_save(cft.flow_path(store, "dir", key, "ring.npy"), cft._ring(code))
    cft.drop_kinds(store, "dir_proposed", "dir_base")
    stats = {
        "proposed_extensions": int(proposed),
        "crossing_rejected": rejected,
        "accepted_extensions": int(proposed) - rejected,
    }
    if log is not None:
        log(f"[flow] constrained two-ring routing: {stats}")
    return stats
