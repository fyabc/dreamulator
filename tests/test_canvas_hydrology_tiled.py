"""Tiled three-stage S2 algorithms (Barnes 2016/2017) vs the oracle."""

from __future__ import annotations

import numpy as np
import pytest

from dreamulator.media.canvas_hydrology import (
    CanvasTiles,
    ChunkGrid,
    flood_canvas,
    flow_accumulation_canvas,
)
from dreamulator.media.canvas_hydrology_tiled import (
    accumulate_canvas_tiled,
    fill_canvas_tiled,
)


def _dem(seed: int = 7, shape: tuple[int, int] = (32, 32), sea: bool = False) -> np.ndarray:
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0 : shape[0], 0 : shape[1]]
    dem = 200.0 + 8.0 * y + 3.0 * x + 60.0 * np.sin(x / 5.0) * np.cos(y / 7.0)
    dem += rng.normal(0.0, 4.0, size=shape)
    dem -= 120.0 * np.exp(
        -((y - shape[0] / 2) ** 2 + (x - shape[1] / 2) ** 2) / (2 * (shape[0] / 6) ** 2)
    )
    if sea:
        dem[:, :3] = -50.0  # western sea column
    return dem


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


@pytest.mark.parametrize(
    ("rows", "cols", "seed", "sea"),
    [(1, 1, 3, False), (2, 2, 7, False), (2, 3, 11, True), (3, 2, 19, True)],
)
def test_tiled_fill_matches_oracle(rows: int, cols: int, seed: int, sea: bool) -> None:
    t = 16
    dem = _dem(seed=seed, shape=(rows * t, cols * t), sea=sea)
    grid = ChunkGrid(rows, cols, t)
    oracle = CanvasTiles(raw=_split(dem, grid), grid=grid)
    flood_canvas(oracle, sea_level=0.0, eps=0.0)
    tiled = CanvasTiles(raw=_split(dem, grid), grid=grid)
    fill_canvas_tiled(tiled, sea_level=0.0)
    assert np.array_equal(_assemble(tiled.filled, grid), _assemble(oracle.filled, grid))


@pytest.mark.parametrize(
    ("rows", "cols", "seed", "sea"), [(1, 1, 5, False), (2, 2, 13, False), (2, 3, 23, True)]
)
def test_tiled_accumulation_matches_oracle(rows: int, cols: int, seed: int, sea: bool) -> None:
    t = 16
    dem = _dem(seed=seed, shape=(rows * t, cols * t), sea=sea)
    grid = ChunkGrid(rows, cols, t)
    weights = (dem > 0.0).astype(np.float64)
    tiles = CanvasTiles(raw=_split(dem, grid), grid=grid)
    fill_canvas_tiled(tiles, sea_level=0.0)
    got = _assemble(accumulate_canvas_tiled(tiles, _split(weights, grid)), grid)
    oracle = CanvasTiles(raw=_split(dem, grid), grid=grid)
    flood_canvas(oracle, sea_level=0.0, eps=0.0)
    ref = _assemble(flow_accumulation_canvas(oracle, _split(weights, grid)), grid)
    assert np.allclose(got, ref, rtol=1e-12, atol=1e-9)


@pytest.mark.parametrize(
    ("rows", "cols", "seed", "sea"),
    [(1, 1, 3, False), (2, 2, 7, False), (2, 3, 11, True)],
)
def test_tiled_fill_eps_ramp_matches_oracle(rows: int, cols: int, seed: int, sea: bool) -> None:
    """eps > 0: the per-depression ramp must reproduce the oracle's grading."""
    eps = 1e-3
    t = 16
    dem = _dem(seed=seed, shape=(rows * t, cols * t), sea=sea)
    grid = ChunkGrid(rows, cols, t)
    oracle = CanvasTiles(raw=_split(dem, grid), grid=grid)
    flood_canvas(oracle, sea_level=0.0, eps=eps)
    ref = _assemble(oracle.filled, grid)
    tiled = CanvasTiles(raw=_split(dem, grid), grid=grid)
    fill_canvas_tiled(tiled, sea_level=0.0, eps=eps)
    got = _assemble(tiled.filled, grid)
    assert np.array_equal(got, ref), f"eps={eps}: max |diff| = {np.abs(got - ref).max():.3e}"
