"""Tests for the biome sheet compositor + the satellite texture pass."""

from __future__ import annotations

import numpy as np
import pytest

from dreamulator.media import biome_render as br
from dreamulator.media import satellite_color as sc
from dreamulator.media.satellite_color import ColorizeInputs

N = 64


def _inputs(n: int = N) -> ColorizeInputs:
    """Synthetic sheet: central peak, sea in the corners, four biome bands."""
    y, x = np.mgrid[0:n, 0:n]
    ridge = np.clip(3000.0 - 100.0 * np.hypot(x - n * 0.5, y - n * 0.5), -200.0, 3000.0)
    sea = ridge <= 0.0
    codes = np.where(sea, 5, 1 + (x * 3 // n)).astype(np.uint8)  # 1..3 land, 5 ocean
    return ColorizeInputs(
        height_m=ridge.astype(np.float32),
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


def test_biome_sheet_sea_is_paper_and_legend_lists_present() -> None:
    rgb, sea, entries = br.compose_biome_rgb(_inputs(), res=N, hillshade_strength=0.0)
    paper = np.asarray(br.PAPER_RGB, dtype=np.float32) / 255.0
    assert (np.abs(rgb[sea] - paper) < 0.08).all()  # ±paper grain (6% peak)
    # Legend: the three land classes present, ocean excluded, palette order.
    assert [name for name, _ in entries] == [
        "temperate_forest",
        "temperate_grassland",
        "temperate_desert",
    ]


def test_biome_sheet_reconciles_dry_ocean_cells() -> None:
    inp = _inputs()
    # Erosion lifted an ocean-coded block above the waterline: it must not
    # render in the palette's ocean blue (satellite leg shares the rule).
    block = np.zeros((N, N), dtype=bool)
    block[10:14, 10:14] = True
    inp.biome_codes[block] = 5
    rgb, sea, _ = br.compose_biome_rgb(inp, res=N, hillshade_strength=0.0)
    ocean_rgb = np.asarray((0x15, 0x65, 0xC0), dtype=np.float32) / 255.0
    land_block = block & ~sea
    assert not (np.abs(rgb[land_block] - ocean_rgb) < 0.05).all(axis=1).any()


def test_vegetation_texture_deterministic_and_land_only() -> None:
    inp = _inputs()
    land = ~inp.sea_water & (inp.biome_codes != 0)
    t1 = sc._vegetation_texture(N, inp.km_per_px, inp.biome_codes, inp.biome_legend, land)
    t2 = sc._vegetation_texture(N, inp.km_per_px, inp.biome_codes, inp.biome_legend, land)
    assert np.array_equal(t1, t2)
    assert t1.min() > 0.5 and t1.max() < 1.5  # brightness factor, not a repaint
    assert t1[~land].mean() == 1.0  # sea/missing stay neutral


def test_colorize_texture_flag_changes_land_only() -> None:
    inp = _inputs()
    flat = sc.colorize(inp, texture=False)
    tex = sc.colorize(inp, texture=True)
    assert not np.array_equal(flat, tex)
    assert np.array_equal(flat[inp.sea_water], tex[inp.sea_water])  # sea untouched


def test_biome_sheet_regime_smoke(tmp_path) -> None:
    pytest.importorskip("matplotlib")
    inp = _inputs()
    inp.river_segments = np.array(
        [
            [[10.0, 10.0], [20.0, 20.0]],
            [[20.0, 20.0], [30.0, 30.0]],
            [[30.0, 30.0], [40.0, 40.0]],
        ]
    )
    inp.river_segment_flows = np.array([100.0, 50.0, 10.0])
    inp.river_segment_regimes = np.array([0, 1, 0], dtype=np.uint8)
    br.render_biome_sheet(inp, tmp_path, res=N, dpi=72, title="时令河")
    assert (tmp_path / "biome.svg").exists()
    assert (tmp_path / "biome.png").exists()
