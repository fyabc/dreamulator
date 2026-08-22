"""Unit tests for the single-source palette module (map/palettes.py)."""

import numpy as np

from dreamulator.map import palettes


def test_hex_to_rgb():
    assert palettes.hex_to_rgb("#0000ff") == (0, 0, 255)
    assert palettes.hex_to_rgb("#1a5276") == (26, 82, 118)
    # Accepts a missing '#' prefix.
    assert palettes.hex_to_rgb("023858") == (2, 56, 88)


def test_categorical_palettes_load():
    koppen = palettes.koppen_colors()
    assert koppen["Af"] == "#0000ff"
    assert koppen["Ocean"] == "#1a5276"
    assert "ET" in koppen

    assert palettes.whittaker_colors()["tropical_rainforest"] == "#1B5E20"
    assert palettes.soil_colors()["mollisol"] == "#33691E"
    assert len(palettes.plate_colors()) == 20


def test_continuous_scale_shape():
    habitability = palettes.continuous_scale("habitability")
    assert habitability[0]["value"] == 0.0
    assert habitability[-1]["value"] == 1.0
    assert habitability[0]["color"] == [40, 44, 52]


def test_sequential_color_endpoints_and_clamp():
    scale = palettes.continuous_scale("habitability")
    assert palettes.sequential_color(0.0, scale) == (40, 44, 52)
    assert palettes.sequential_color(1.0, scale) == (0, 172, 193)
    # Values outside [0, 1] clamp to the endpoints.
    assert palettes.sequential_color(-5.0, scale) == (40, 44, 52)
    assert palettes.sequential_color(5.0, scale) == (0, 172, 193)


def test_sequential_color_midpoint_hits_stop():
    # agriculture scale: 0.5 → yellow (238,210,90)
    scale = palettes.continuous_scale("agriculture")
    assert palettes.sequential_color(0.5, scale) == (238, 210, 90)


def test_build_adaptive_terrain_lut_shape_and_ends():
    lut = palettes.build_adaptive_terrain_lut(-11_000.0, 9_000.0, 0.0)
    assert lut.shape == (1024, 3)
    assert lut.dtype == np.uint8
    # index 0 = deepest ocean (first break #023858 → (2,56,88))
    assert tuple(int(v) for v in lut[0]) == (2, 56, 88)
    # last index = peak white (#FFFFFF)
    assert tuple(int(v) for v in lut[1023]) == (255, 255, 255)
