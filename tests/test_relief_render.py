"""Tests for the natural-colour shaded-relief sheet compositor."""

from __future__ import annotations

import numpy as np
import pytest

from dreamulator.media import relief_render as rr
from dreamulator.media.satellite_color import colorize

N = 64


def _inputs(n: int = N):
    """Synthetic sheet: central peak, sea in the corners, four biome bands."""
    y, x = np.mgrid[0:n, 0:n]
    ridge = np.clip(3000.0 - 100.0 * np.hypot(x - n * 0.5, y - n * 0.5), -200.0, 3000.0)
    sea = ridge <= 0.0
    codes = np.where(sea, 5, 1 + (x * 3 // n)).astype(np.uint8)  # 1..3 land, 5 ocean
    return y, x, sea, codes


def _colorize_inputs(y, x, sea, codes):  # type: ignore[no-untyped-def]
    from dreamulator.media.satellite_color import ColorizeInputs

    n = sea.shape[0]
    return ColorizeInputs(
        height_m=np.clip(3000.0 - 100.0 * np.hypot(x - n * 0.5, y - n * 0.5), -200.0, 3000.0)
        .astype(np.float32)
        .copy(),
        km_per_px=550.0 / n,
        biome_codes=codes,
        biome_legend={
            1: "temperate_forest",
            2: "temperate_grassland",
            3: "temperate_desert",
            5: "ocean",
        },
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


def test_relief_sea_flat_land_shaded() -> None:
    y, x, sea, codes = _inputs()
    inp = _colorize_inputs(y, x, sea, codes)
    rgb, sea_out, _ = rr.compose_relief_rgb(inp, res=N, texture=False)
    base = colorize(inp, texture=False).astype(np.float32) / 255.0
    # Sea: the bathy gradient passes through untouched (no shade, no gamma).
    assert np.array_equal(rgb[sea_out], base[sea_out])
    # Land: centred shade + mid-tone lift change the compositor output.
    assert not np.array_equal(rgb[~sea_out], base[~sea_out])


def test_relief_sea_depth_gradient_survives() -> None:
    y, x, sea, codes = _inputs()
    inp = _colorize_inputs(y, x, sea, codes)
    n = sea.shape[0]
    deep_patch = np.zeros((n, n), dtype=bool)
    deep_patch[: n // 4, : n // 4] = True  # one sea corner
    inp.sea_depth_m = np.where(sea, np.where(deep_patch, 380.0, 40.0), 0.0).astype(np.float32)
    rgb, sea_out, _ = rr.compose_relief_rgb(inp, res=N, texture=False)
    lum = rgb.mean(axis=2)
    assert lum[sea_out & deep_patch].mean() < lum[sea_out & ~deep_patch].mean() - 0.05


def test_relief_legend_lists_land_classes_in_palette_order() -> None:
    y, x, sea, codes = _inputs()
    inp = _colorize_inputs(y, x, sea, codes)
    _, _, entries = rr.compose_relief_rgb(inp, res=N, texture=False)
    assert [name for name, _ in entries] == [
        "temperate_forest",
        "temperate_grassland",
        "temperate_desert",
    ]


def test_relief_sheet_smoke(tmp_path) -> None:
    pytest.importorskip("matplotlib")
    y, x, sea, codes = _inputs()
    inp = _colorize_inputs(y, x, sea, codes)
    inp.river_segments = np.array(
        [
            [[10.0, 10.0], [20.0, 20.0]],
            [[20.0, 20.0], [30.0, 30.0]],
        ]
    )
    inp.river_segment_flows = np.array([100.0, 50.0])
    inp.river_segment_regimes = np.array([0, 1], dtype=np.uint8)
    info = rr.render_relief_sheet(
        inp, tmp_path, res=N, dpi=72, title="自然色", center_lat=21.5, center_lon=95.5
    )
    assert (tmp_path / "relief.png").exists()
    assert not (tmp_path / "relief.svg").exists()  # SVG is opt-in
    assert info["classes"] == 3


def test_colorize_lake_mask_renders_without_biome_code() -> None:
    y, x, sea, codes = _inputs()
    inp = _colorize_inputs(y, x, sea, codes)
    n = sea.shape[0]
    lake = np.zeros((n, n), dtype=bool)
    lake[n // 2 - 4 : n // 2 + 4, n // 2 - 4 : n // 2 + 4] = True  # land block
    inp.lake = lake
    out = colorize(inp, texture=False).astype(np.float32) / 255.0
    interior = lake & ~np.zeros_like(lake)
    # Freshwater palette is blue-dominant; the dry-land class underneath is not.
    assert (out[interior][..., 2] - out[interior][..., 0]).mean() > 0.05


def test_colorize_texture_gain_zero_equals_texture_off() -> None:
    y, x, sea, codes = _inputs()
    inp = _colorize_inputs(y, x, sea, codes)
    off = colorize(inp, texture=False)
    zero = colorize(inp, texture=True, texture_gain=0.0)
    assert np.array_equal(off, zero)
