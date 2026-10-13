"""Tests for the parchment illustrated sheet (pure helpers + tiny smoke)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pytest

if TYPE_CHECKING:
    from pathlib import Path

from dreamulator.media import medieval_render as mr
from dreamulator.media.satellite_color import ColorizeInputs

N = 64


def _inputs(n: int = N) -> ColorizeInputs:
    """Central peak over a shallow sea (corners wet), forested flanks."""
    y, x = np.mgrid[0:n, 0:n]
    ridge = np.clip(4000.0 - 100.0 * np.hypot(x - n / 2, y - n / 2), -200.0, 4000.0)
    sea = ridge <= 0.0
    return ColorizeInputs(
        height_m=ridge.astype(np.float32),
        km_per_px=2364.0 / n,
        biome_codes=np.where(~sea, 1, 0).astype(np.uint8),
        biome_legend={1: "tropical_rainforest"},
        sea_water=sea,
        sea_depth_m=np.where(sea, 150.0, 0.0).astype(np.float32),
        rivers=np.zeros((n, n), dtype=bool),
        river_depth_m=np.zeros((n, n), dtype=np.float32),
        flow=np.zeros((n, n), dtype=np.float32),
        wear=np.zeros((n, n), dtype=np.float32),
        deposits=np.zeros((n, n), dtype=np.float32),
        ice_m=np.zeros((n, n), dtype=np.float32),
        npp_gc_m2_yr=np.full((n, n), 900.0, dtype=np.float32),
    )


def test_mode_pool_categorical() -> None:
    codes = np.arange(16, dtype=np.uint8).reshape(4, 4) // 4  # blocks of one value
    assert (mr._mode_pool(codes, 2, 2) == codes[::2, ::2]).all()


def test_jitter_grid_respects_mask_and_spacing() -> None:
    mask = np.zeros((100, 100), dtype=bool)
    mask[:, 50:] = True  # east half only
    ys, xs = mr._jitter_grid(mask, step=10, seed=3)
    assert len(ys) > 0
    assert xs.min() >= 50
    # One candidate per step-cell: max count bounded by the cell census.
    assert len(ys) <= mask[:, 50:].size / (10 * 10) + 50


def test_parchment_ranges_and_scorch() -> None:
    rgb = mr._parchment(128, np.zeros((128, 128), dtype=bool),
                        np.zeros((128, 128)), (-400.0, 8000.0), seed=1)
    assert rgb.shape == (128, 128, 3)
    assert rgb.min() >= 0.0 and rgb.max() <= 1.0
    # Corners are scorched darker than the centre.
    assert rgb[:8, :8].mean() < rgb[56:72, 56:72].mean()


def test_render_medieval_smoke(tmp_path: Path) -> None:
    pytest.importorskip("matplotlib")
    info = mr.render_medieval(_inputs(), tmp_path, (-6000.0, 8000.0), res=N, dpi=72, title="测试")
    out = tmp_path / "medieval.png"
    assert out.exists()
    # The synthetic peak is high ground with real slope — the herd draws.
    assert info["mountains"] > 0
    # Rainforest legend entry draws stands.
    assert info["trees"] > 0
