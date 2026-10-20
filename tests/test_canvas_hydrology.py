"""Tests for the S2 out-of-core hydrology scaffold (chunked flood/lakes/isthmus)."""

from __future__ import annotations

import heapq

import numpy as np
import pytest

from dreamulator.media.canvas_hydrology import (
    CanvasTiles,
    ChunkGrid,
    flood_canvas,
    flow_accumulation_canvas,
    lake_labels,
    solve_isthmus,
)


def _flood_ref(dem: np.ndarray, eps: float = 0.0) -> np.ndarray:
    """Classic Priority-Flood (Barnes 2014): border cells are the queue seeds."""
    h, w = dem.shape
    filled = dem.astype(np.float64).copy()
    visited = np.zeros((h, w), dtype=bool)
    heap: list[tuple[float, int, int]] = []
    for r in range(h):
        for c in range(w):
            if r in (0, h - 1) or c in (0, w - 1):
                visited[r, c] = True
                heapq.heappush(heap, (float(dem[r, c]), r, c))
    nbrs = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
    while heap:
        level, r, c = heapq.heappop(heap)
        for dy, dx in nbrs:
            nr, nc = r + dy, c + dx
            if 0 <= nr < h and 0 <= nc < w and not visited[nr, nc]:
                visited[nr, nc] = True
                filled[nr, nc] = max(float(dem[nr, nc]), level + eps)
                heapq.heappush(heap, (filled[nr, nc], nr, nc))
    return filled


def _dem(seed: int = 7, shape: tuple[int, int] = (32, 32)) -> np.ndarray:
    """A smooth random surface with several basins (m)."""
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0 : shape[0], 0 : shape[1]]
    base = 200.0 + 8.0 * y + 3.0 * x
    waves = 60.0 * np.sin(x / 5.0) * np.cos(y / 7.0)
    noise = rng.normal(0.0, 4.0, size=shape)
    return base + waves + noise


def _split(dem: np.ndarray, grid: ChunkGrid) -> dict[tuple[int, int], np.ndarray]:
    t = grid.tile
    return {
        (i, j): dem[i * t : (i + 1) * t, j * t : (j + 1) * t].copy()
        for i in range(grid.rows)
        for j in range(grid.cols)
    }


def _assemble(tiles: dict[tuple[int, int], np.ndarray], grid: ChunkGrid) -> np.ndarray:
    t = grid.tile
    out = np.empty(grid.shape, dtype=np.float64)
    for (i, j), arr in tiles.items():
        out[i * t : (i + 1) * t, j * t : (j + 1) * t] = arr
    return out


def test_flood_single_tile_matches_global() -> None:
    dem = _dem()
    ref = _flood_ref(dem)
    tiles = CanvasTiles(raw={(0, 0): dem.copy()}, grid=ChunkGrid(1, 1, dem.shape[0]))
    flood_canvas(tiles, sea_level=0.0, eps=0.0)
    assert np.array_equal(tiles.filled[(0, 0)], ref)


@pytest.mark.parametrize("seed", [3, 11, 29])
def test_flood_four_chunks_matches_global(seed: int) -> None:
    dem = _dem(seed=seed, shape=(32, 32))
    # Carve one basin that straddles all four chunk borders.
    yy, xx = np.mgrid[0:32, 0:32]
    dem -= 120.0 * np.exp(-(((yy - 16.0) ** 2 + (xx - 16.0) ** 2) / (2 * 5.0**2)))
    ref = _flood_ref(dem)

    grid = ChunkGrid(2, 2, 16)
    tiles = CanvasTiles(raw=_split(dem, grid), grid=grid)
    flood_canvas(tiles, sea_level=0.0, eps=0.0)
    got = _assemble(tiles.filled, grid)
    assert np.array_equal(got, ref)


def test_flood_with_eps_is_close_to_global() -> None:
    dem = _dem(seed=5, shape=(32, 32))
    eps = 1e-3
    ref = _flood_ref(dem, eps=eps)
    grid = ChunkGrid(2, 2, 16)
    tiles = CanvasTiles(raw=_split(dem, grid), grid=grid)
    flood_canvas(tiles, sea_level=0.0, eps=eps)
    got = _assemble(tiles.filled, grid)
    # Graded depression interiors differ by a few eps steps of path length;
    # the spill levels themselves agree.
    assert np.allclose(got, ref, atol=5 * eps)


def test_lake_labels_merge_across_chunks() -> None:
    yy, xx = np.mgrid[0:32, 0:32]
    # A clean bowl centred on the 2x2 seam: the filled lake must get one
    # label across all four chunks (per-tile labelling alone would fragment it).
    dem = 100.0 + 0.1 * ((yy - 16.0) ** 2 + (xx - 16.0) ** 2)
    grid = ChunkGrid(2, 2, 16)
    tiles = CanvasTiles(raw=_split(dem, grid), grid=grid)
    flood_canvas(tiles, sea_level=0.0, eps=0.0)
    labels = lake_labels(tiles)
    full = _assemble(labels, grid)
    lake = full > 0
    assert lake.any()
    # The big cross-seam basin (nearest the centre) is one label and spans
    # all four chunks.
    ys, xs = np.nonzero(lake)
    d2 = (ys - 16) ** 2 + (xs - 16) ** 2
    big_id = int(full[ys[d2.argmin()], xs[d2.argmin()]])
    for key in ((0, 0), (0, 1), (1, 0), (1, 1)):
        assert big_id in set(np.unique(labels[key]).tolist()), key


def test_isthmus_exchange_matches_global() -> None:
    dem = _dem(seed=21, shape=(16, 32))
    yy, xx = np.mgrid[0:16, 0:32]
    # A depression straddling the vertical seam (columns 15/16).
    dem -= 150.0 * np.exp(-(((yy - 8.0) ** 2 + (xx - 16.0) ** 2) / (2 * 4.0**2)))

    # Ground truth: the two canvases treated as one 1x2 canvas.
    grid_full = ChunkGrid(1, 2, 16)
    full_tiles = CanvasTiles(raw=_split(dem, grid_full), grid=grid_full)
    flood_canvas(full_tiles, sea_level=0.0, eps=0.0)
    ref = _assemble(full_tiles.filled, grid_full)

    # Two separate canvases, each one 16x16 chunk, coupled at the seam.
    grid_a = ChunkGrid(1, 1, 16)
    a = CanvasTiles(raw={(0, 0): dem[:, :16].copy()}, grid=grid_a)
    b = CanvasTiles(raw={(0, 0): dem[:, 16:].copy()}, grid=grid_a)
    pairs = [(((0, 0), r, 15), ((0, 0), r, 0)) for r in range(16)]
    solve_isthmus(a, b, pairs, sea_level=0.0, eps=0.0)

    got = np.empty_like(dem)
    got[:, :16] = a.filled[(0, 0)]
    got[:, 16:] = b.filled[(0, 0)]
    assert np.array_equal(got, ref)


# ---------------------------------------------------------------------------
# Flow directions and accumulation
# ---------------------------------------------------------------------------


def _accum_ref(
    dem: np.ndarray, filled: np.ndarray, weights: np.ndarray, sea_level: float = 0.0
) -> np.ndarray:
    """Global D8 receivers + downstream-first accumulation (fixed tie order)."""
    h, w = dem.shape
    nbrs = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
    rec = -np.ones((h, w), dtype=np.int64)
    diag = 2**0.5
    for r in range(h):
        for c in range(w):
            f0 = filled[r, c]
            if f0 <= sea_level:
                continue
            best, best_s = -1, 0.0
            for dy, dx in nbrs:
                nr, nc = r + dy, c + dx
                if not (0 <= nr < h and 0 <= nc < w):
                    continue
                f1 = filled[nr, nc]
                if f1 >= f0:
                    continue
                s = (f0 - f1) / (diag if dy and dx else 1.0)
                if s > best_s:
                    best_s, best = s, nr * w + nc
            rec[r, c] = best
    acc = weights.astype(np.float64).ravel().copy()
    order = np.argsort(-filled.ravel(), kind="stable")
    rec_flat = rec.ravel()
    for flat in order:
        tgt = rec_flat[flat]
        if tgt >= 0:
            acc[tgt] += acc[flat]
    return acc.reshape(h, w)


def test_flow_accumulation_matches_global() -> None:
    dem = _dem(seed=17, shape=(32, 32))
    # Strict gradients: tiny deterministic tilt removes exact-height ties.
    dem += 1e-3 * (np.mgrid[0:32, 0:32][0] * 32 + np.mgrid[0:32, 0:32][1])
    grid = ChunkGrid(2, 2, 16)
    tiles = CanvasTiles(raw=_split(dem, grid), grid=grid)
    flood_canvas(tiles, sea_level=0.0, eps=0.0)
    filled = _assemble(tiles.filled, grid)
    weights = (dem > 0.0).astype(np.float64)
    w_tiles = _split(weights, grid)
    acc = _assemble(
        {k: v for k, v in flow_accumulation_canvas(tiles, w_tiles).items()},
        grid,
    )
    ref = _accum_ref(dem, filled, weights)
    assert np.allclose(acc, ref, rtol=1e-12, atol=1e-9)


def test_flow_crosses_chunk_border() -> None:
    # A tilted plane draining east: every cell flows east across the seam.
    h, w = 32, 32
    yy, xx = np.mgrid[0:h, 0:w]
    dem = 1000.0 - 2.0 * xx + 0.01 * yy
    grid = ChunkGrid(2, 2, 16)
    tiles = CanvasTiles(raw=_split(dem, grid), grid=grid)
    flood_canvas(tiles, sea_level=0.0, eps=0.0)
    weights = np.ones((h, w))
    acc = _assemble(flow_accumulation_canvas(tiles, _split(weights, grid)), grid)
    # Crossing the seam must not reset the accumulation (chunk (i,1) sees the
    # flow of chunk (i,0)); compare against the global reference, which also
    # carries the edge flow north along the eastern border.
    filled = _assemble(tiles.filled, grid)
    ref = _accum_ref(dem, filled, weights)
    assert np.allclose(acc, ref, rtol=1e-12, atol=1e-9)
    # The seam column (col 15) must already carry the full 16-cell row flow.
    assert acc[0, 15] == pytest.approx(16.0)
