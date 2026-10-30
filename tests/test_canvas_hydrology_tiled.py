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
    _local_flood,
    _local_flood_reference,
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


@pytest.mark.parametrize(
    ("shape", "sea", "eps", "dtype"),
    [
        ((32, 32), False, 0.0, np.float64),
        ((32, 32), True, 0.0, np.float64),
        ((24, 40), True, 0.01, np.float32),
        ((17, 13), False, 0.5, np.float32),
        ((64, 48), True, 1e-3, np.float32),
    ],
)
def test_local_flood_kernel_matches_reference(
    shape: tuple[int, int], sea: bool, eps: float, dtype: type[np.floating]
) -> None:
    """The numba stage-1 kernel must be bit-identical to the pure-Python
    reference: labels, filled surface and the spill graph."""
    rng = np.random.default_rng(sum(shape) + int(eps * 1000))
    dem = (rng.integers(0, 300, size=shape).astype(np.float64) / 7.0).astype(dtype)
    dem[2:5, 3:8] = dem.min()  # closed pit
    dem[shape[0] // 2 : shape[0] // 2 + 3, shape[1] // 2 : shape[1] // 2 + 4] = dtype(80)  # plateau
    external = np.zeros(shape, dtype=bool)
    if sea:
        external[:, :3] = True
        dem[:, :3] = -50.0
    lab_ref, fill_ref, spill_ref = _local_flood_reference(dem, external, eps)
    lab_k, fill_k, spill_k = _local_flood(dem, external, eps)
    assert np.array_equal(lab_ref, lab_k)
    assert fill_ref.dtype == fill_k.dtype
    assert np.array_equal(fill_ref, fill_k), f"max |diff| = {np.abs(fill_ref - fill_k).max():.3e}"
    assert spill_k == spill_ref


@pytest.mark.parametrize(
    ("shape", "sea", "eps"),
    [((40, 40), True, 1e-3), ((33, 25), False, 0.01), ((56, 40), True, 0.05)],
)
def test_grade_flats_kernel_matches_reference(
    shape: tuple[int, int], sea: bool, eps: float
) -> None:
    """The numba PF+ε grading must be bit-identical to the pure-Python one."""
    from dreamulator.media.canvas_pipeline import _grade_flats, _grade_flats_reference

    rng = np.random.default_rng(shape[0] * 100 + shape[1])
    # Stepped DEM: quantising produces large same-value flats at every level.
    dem = (rng.integers(0, 40, size=shape).astype(np.float64) * 7.0).astype(np.float32)
    dem[8:14, 6:18] = np.float32(42.0)  # broad closed flat
    if sea:
        dem[:, :4] = np.float32(-30.0)
    assert np.array_equal(_grade_flats(dem, 0.0, eps), _grade_flats_reference(dem, 0.0, eps))
