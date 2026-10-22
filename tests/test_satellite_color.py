"""Tests for the satellite true-color compositor (step ③)."""

from __future__ import annotations

import numpy as np
import pytest

from dreamulator.media.satellite_color import (
    BIOME_COLORS,
    MISSING_COLOR,
    SEA_DEEP,
    SEA_SHALLOW,
    ColorizeInputs,
    colorize,
    hillshade,
    upsample_nearest,
)

N = 64


def _inputs(**overrides: object) -> ColorizeInputs:
    """A flat temperate-grassland tile at mid elevations; everything else off."""
    kw: dict[str, object] = dict(
        height_m=np.full((N, N), 500.0),
        km_per_px=1.0,
        biome_codes=np.full((N, N), 1, dtype=np.uint8),
        biome_legend={1: "temperate_grassland"},
        sea_water=np.zeros((N, N), dtype=bool),
        sea_depth_m=np.zeros((N, N)),
        rivers=np.zeros((N, N), dtype=bool),
        river_depth_m=np.zeros((N, N)),
        flow=np.zeros((N, N)),
        wear=np.zeros((N, N)),
        deposits=np.zeros((N, N)),
        ice_m=np.zeros((N, N)),
        npp_gc_m2_yr=np.full((N, N), np.nan),  # missing → no modulation
    )
    kw.update(overrides)
    return ColorizeInputs(**kw)  # type: ignore[arg-type]


def test_base_biome_color() -> None:
    rgb = colorize(_inputs(), texture=False)
    assert rgb.shape == (N, N, 3)
    assert rgb.dtype == np.uint8
    assert tuple(rgb[0, 0]) == BIOME_COLORS["temperate_grassland"]


def test_missing_biome_gets_neutral_grey() -> None:
    rgb = colorize(
        _inputs(biome_codes=np.zeros((N, N), dtype=np.uint8), biome_legend={}),
        texture=False,
    )
    assert tuple(rgb[0, 0]) == MISSING_COLOR


def test_sea_overrides_biome_and_grades_by_depth() -> None:
    sea = np.zeros((N, N), dtype=bool)
    sea[:, : N // 2] = True
    depth = np.zeros((N, N))
    depth[:, : N // 4] = 0.0  # shallow
    depth[:, N // 4 : N // 2] = 10_000.0  # deep
    rgb = colorize(texture=False, inp=_inputs(sea_water=sea, sea_depth_m=depth))
    assert tuple(rgb[0, 0]) == SEA_SHALLOW
    assert tuple(rgb[0, N // 3]) == SEA_DEEP
    # land side keeps the biome colour
    assert tuple(rgb[0, N - 1]) == BIOME_COLORS["temperate_grassland"]


def test_rivers_override_land() -> None:
    riv = np.zeros((N, N), dtype=bool)
    riv[N // 2, :] = True
    rgb = colorize(texture=False, inp=_inputs(rivers=riv))
    land = BIOME_COLORS["temperate_grassland"]
    assert tuple(rgb[N // 2, 0]) != land
    assert tuple(rgb[0, 0]) == land


def test_ice_beats_biome() -> None:
    rgb = colorize(texture=False, inp=_inputs(ice_m=np.full((N, N), 50.0)))
    assert tuple(rgb[0, 0]) == (238, 242, 245)


def test_steep_slope_exposes_rock() -> None:
    # A cliff: height ramps 0 → 800 m across 8 px at 1 km/px → slope 0.1 …
    # use a sharper ramp: 4000 m over 4 px → slope 1.0.
    h = np.zeros((N, N))
    h[:, N // 2 :] = np.clip(np.arange(N // 2), 0, 4) * 1000.0  # steep west face
    h = np.broadcast_to(h, (N, N)).copy()
    rgb = colorize(texture=False, inp=_inputs(height_m=h, km_per_px=1.0))
    grass = np.asarray(BIOME_COLORS["temperate_grassland"], dtype=int)
    rock = np.array((107, 97, 90))
    steep_px = rgb[N // 2, N // 2 + 2].astype(int)
    flat_px = rgb[N // 2, -1].astype(int)
    assert np.linalg.norm(steep_px - rock) < np.linalg.norm(steep_px - grass)
    assert tuple(flat_px) == tuple(grass)


def test_deterministic() -> None:
    inp = _inputs()
    assert np.array_equal(colorize(inp), colorize(inp))


def test_npp_modulates_within_biome() -> None:
    # Same biome everywhere; left half twice as productive as the median.
    npp = np.full((N, N), 500.0)
    npp[:, : N // 2] = 1000.0  # median over the biome = 750; left rel = 1.33
    rgb = colorize(_inputs(npp_gc_m2_yr=npp), texture=False)
    base = np.asarray(BIOME_COLORS["temperate_grassland"], dtype=int)
    left = rgb[0, 0].astype(int)
    right = rgb[0, -1].astype(int)
    assert left.sum() > base.sum()  # lusher side is brighter
    assert right.sum() < base.sum()  # stressed side is dimmer


def test_npp_missing_is_noop() -> None:
    rgb = colorize(_inputs(), texture=False)
    assert tuple(rgb[0, 0]) == BIOME_COLORS["temperate_grassland"]


def test_ocean_on_land_filled_from_neighbour() -> None:
    """Engine-ocean pixels left dry by the Gaea sea mask must not paint navy."""
    codes = np.full((N, N), 2, dtype=np.uint8)  # 2 = ocean
    codes[:, N // 2 :] = 1  # 1 = temperate_grassland
    rgb = colorize(
        _inputs(
            biome_codes=codes,
            biome_legend={1: "temperate_grassland", 2: "ocean"},
        ),
        texture=False,
    )
    # Dry ocean (left half) takes the land biome's colour, not the navy fallback.
    assert tuple(rgb[0, 0]) == BIOME_COLORS["temperate_grassland"]
    assert tuple(rgb[0, 0]) != BIOME_COLORS["ocean"]


def test_ocean_under_sea_stays_sea() -> None:
    codes = np.full((N, N), 2, dtype=np.uint8)
    codes[:, N // 2 :] = 1
    sea = np.zeros((N, N), dtype=bool)
    sea[:, : N // 2] = True  # the ocean half is actually wet
    rgb = colorize(
        _inputs(
            biome_codes=codes,
            biome_legend={1: "temperate_grassland", 2: "ocean"},
            sea_water=sea,
        ),
        texture=False,
    )
    assert tuple(rgb[0, 0]) == SEA_SHALLOW  # depth 0 → shallow end


def test_upsample_nearest() -> None:
    a = np.array([[1, 2], [3, 4]], dtype=np.uint8)
    up = upsample_nearest(a, 2)
    assert up.shape == (4, 4)
    assert up[0, 0] == 1 and up[1, 1] == 1 and up[0, 2] == 2 and up[3, 3] == 4
    with pytest.raises(ValueError, match="factor"):
        upsample_nearest(a, 0)


def test_hillshade_flat_is_uniform() -> None:
    hs = hillshade(np.full((N, N), 100.0), 1.0)
    assert hs.min() == pytest.approx(hs.max(), abs=1e-9)


def test_river_lake_clip_keeps_shore_crossing() -> None:
    """Only segments fully inside a lake are dropped; the entry bridge stays."""
    from dreamulator.media.satellite_color import _river_lake_keep

    lake = np.zeros((20, 20), dtype=bool)
    lake[5:10, 5:10] = True
    # Row 0 is north: a pixel (col, y) maps to row = n - 1 - y.
    land = (3.0, 4.0)  # row 15, col 3
    water = (7.0, 12.0)  # row 7, col 7 (inside)
    deep = (5.0, 14.0)  # row 5, col 5 (inside)
    segs = np.array(
        [
            [land, water],  # crosses the shore: keep
            [deep, water],  # wholly inside: drop
            [land, (1.0, 1.0)],  # dry land: keep
        ],
        dtype=np.float32,
    )
    keep = _river_lake_keep(segs, lake, 1.0)
    assert keep.tolist() == [True, False, True]
