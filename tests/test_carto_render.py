"""Tests for the cartographic sheet compositor (pure functions + tiny smoke)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pytest

if TYPE_CHECKING:
    from pathlib import Path

from dreamulator.media import carto_render as cr
from dreamulator.media.satellite_color import ColorizeInputs

N = 64


def _inputs(n: int = N) -> ColorizeInputs:
    """Synthetic sheet: one central peak over a shallow sea (corners wet)."""
    y, x = np.mgrid[0:n, 0:n]
    ridge = np.clip(3000.0 - 100.0 * np.hypot(x - n * 0.5, y - n * 0.5), -200.0, 3000.0)
    sea = ridge <= 0.0
    return ColorizeInputs(
        height_m=ridge.astype(np.float32),
        km_per_px=2364.0 / n,
        biome_codes=np.where(sea, 0, 1).astype(np.uint8),
        biome_legend={1: "temperate_forest"},
        sea_water=sea,
        sea_depth_m=np.where(sea, 200.0, 0.0).astype(np.float32),
        rivers=np.zeros((n, n), dtype=bool),
        river_depth_m=np.zeros((n, n), dtype=np.float32),
        flow=np.zeros((n, n), dtype=np.float32),
        wear=np.zeros((n, n), dtype=np.float32),
        deposits=np.zeros((n, n), dtype=np.float32),
        ice_m=np.zeros((n, n), dtype=np.float32),
        npp_gc_m2_yr=np.full((n, n), 800.0, dtype=np.float32),
    )


def test_contour_levels_land_only_and_excludes_major() -> None:
    minor, major = cr.contour_levels(-200.0, 3000.0)
    # Land only: nothing at or below sea level.
    assert minor.min() > 0 and major.min() > 0
    # Major is the 1000 m ladder; minor never duplicates it.
    assert major.tolist() == [1000.0, 2000.0]
    assert 1000.0 not in minor.tolist()
    assert minor.min() == 500.0


def test_contour_levels_flat_sea_only_sheet() -> None:
    minor, major = cr.contour_levels(-400.0, 0.0)
    assert len(minor) == 0 and len(major) == 0


def test_lut_rgb_blue_sea_green_land() -> None:
    rng = (-6000.0, 4000.0)
    h = np.array([[0.0, 1000.0, 3000.0, 3999.0]])
    sea = np.zeros_like(h, dtype=bool)
    rgb = cr._lut_rgb(h, sea, np.zeros_like(h), rng)
    # Land ramp from the shared palette: lowland vegetation-green, summit
    # neutral-to-white; blue dominance strictly fades with elevation.
    assert rgb[0, 0, 2] < rgb[0, 0, 1]
    assert rgb[0, 3].min() > 0.5
    assert rgb[0, 3, 2] - rgb[0, 3, 0] < rgb[0, 0, 2] - rgb[0, 0, 0]


def test_lut_rgb_sea_through_depth_channel() -> None:
    rng = (-6000.0, 4000.0)
    h = np.zeros((1, 2))
    sea = np.array([[True, True]])
    depth = np.array([[100.0, 5000.0]])
    rgb = cr._lut_rgb(h, sea, depth, rng)
    # Deep water is the darker blue of the shared ETOPO ramp.
    assert rgb[0, 1, 2] < rgb[0, 0, 2]
    assert (rgb[0, 1] <= rgb[0, 0] + 1e-6).all()


def test_compose_rgb_ranges_and_sea_ink() -> None:
    rgb = cr.compose_rgb(_inputs(), (-6000.0, 4000.0), res=N)
    assert rgb.shape == (N, N, 3)
    assert rgb.min() >= 0.0 and rgb.max() <= 1.0
    # The sheet corners are sea and keep the blue-dominant ink (b > r).
    assert rgb[0, 0, 2] > rgb[0, 0, 0]
    assert rgb[-1, -1, 2] > rgb[-1, -1, 0]


def test_render_carto_smoke(tmp_path: Path) -> None:
    pytest.importorskip("matplotlib")
    info = cr.render_carto(_inputs(), tmp_path, (-6000.0, 4000.0), res=N, dpi=72, title="冒烟")
    assert (tmp_path / "topo.svg").stat().st_size > 1000
    assert (tmp_path / "topo.png").exists()
    assert info["major_levels"] == 2  # 1000 + 2000 m on a 3000 m ridge


def test_render_carto_hand_smoke(tmp_path: Path) -> None:
    pytest.importorskip("matplotlib")
    pytest.importorskip("opensimplex")
    cr.render_carto(
        _inputs(), tmp_path, (-6000.0, 4000.0), res=N, dpi=72, title="手绘", hand=True
    )
    assert (tmp_path / "topo.hand.png").exists()
    assert not (tmp_path / "topo.png").exists()  # hand run replaces the output set
