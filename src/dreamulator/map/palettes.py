"""Single-source map-layer colour palettes (shared with the frontend).

The ground truth lives in ``palettes.json`` (a plain JSON file next to this
module), which both the Python backend and the TypeScript frontend read —
the frontend via a Vite ``@dreamulator/palettes`` alias, the backend via
``Path(__file__).with_name("palettes.json")``.  Nothing here computes a new
colour; it only exposes the JSON data plus the colormap math that must match
``frontend/src/viewers/map/utils/colorScales.ts`` byte-for-byte.

All functions are pure (no RNG, no I/O beyond the one module-load read) so
they can be unit-tested independently.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, TypedDict

import numpy as np

_PALETTES: dict[str, Any] = json.loads(
    (Path(__file__).with_name("palettes.json")).read_text(encoding="utf-8")
)


class ColorStop(TypedDict):
    """A single stop in a continuous colour scale (mirrors the TS ``ColorStop``)."""

    value: float  # normalised position 0..1
    color: list[int]  # RGB 0..255


def _js_round(x: float) -> int:
    """Round half away from zero, matching JavaScript ``Math.round``.

    Python's built-in ``round`` uses banker's rounding (half-to-even), which
    differs from JS on exact ``.5`` values.  Interpolated colour components are
    always in ``[0, 255]``, so ``floor(x + 0.5)`` is the exact equivalent.
    """
    return math.floor(x + 0.5)


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Parse a ``#RRGGBB`` hex string into an ``(r, g, b)`` tuple (0..255)."""
    h = hex_color.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def sequential_color(value: float, stops: list[ColorStop]) -> tuple[int, int, int]:
    """Interpolate a normalised ``[0, 1]`` value along a sequential scale.

    Port of ``layerBakes.ts::sequentialColor`` (which itself mirrors the
    frontend's per-stop linear interpolation).
    """
    t = max(0.0, min(1.0, value))
    for i in range(len(stops) - 1, -1, -1):
        if t >= stops[i]["value"]:
            if i == len(stops) - 1:
                c = stops[i]["color"]
                return (c[0], c[1], c[2])
            s = stops[i]
            e = stops[i + 1]
            frac = (t - s["value"]) / (e["value"] - s["value"])
            return (
                _js_round(s["color"][0] + (e["color"][0] - s["color"][0]) * frac),
                _js_round(s["color"][1] + (e["color"][1] - s["color"][1]) * frac),
                _js_round(s["color"][2] + (e["color"][2] - s["color"][2]) * frac),
            )
    c = stops[0]["color"]
    return (c[0], c[1], c[2])


def build_adaptive_terrain_lut(
    min_elev: float,
    max_elev: float,
    sea_level: float,
) -> np.ndarray:
    """Build the adaptive hypsometric terrain LUT (``(lut_size, 3)`` uint8 RGB).

    Port of ``colorScales.ts::generateAdaptiveTerrainScale``: breaks are
    resolved from ``anchor``/``fraction``/``clamp_m``/``sign`` in the JSON,
    sorted by elevation, then interpolated across ``lut_size`` entries.
    """
    range_ = max_elev - min_elev or 1.0
    break_specs = _PALETTES["adaptive_terrain"]["breaks"]

    anchors = {"min": min_elev, "sea": sea_level, "max": max_elev}
    color_breaks: list[tuple[float, tuple[int, int, int]]] = []
    for b in break_specs:
        anchor_elev = anchors[b["anchor"]]
        fraction = float(b["fraction"])
        clamp_m = b["clamp_m"]
        if clamp_m is not None:
            offset = max(range_ * fraction, float(clamp_m))
        else:
            offset = range_ * fraction
        elev = anchor_elev + float(b["sign"]) * offset
        color_breaks.append((elev, hex_to_rgb(b["color"])))
    color_breaks.sort(key=lambda item: item[0])

    lut_size = int(_PALETTES["adaptive_terrain"]["lut_size"])
    lut = np.zeros((lut_size, 3), dtype=np.uint8)

    for i in range(lut_size):
        elev = min_elev + (i / (lut_size - 1)) * range_
        lower = color_breaks[0]
        upper = color_breaks[-1]
        for s in range(len(color_breaks) - 1):
            if color_breaks[s][0] <= elev <= color_breaks[s + 1][0]:
                lower = color_breaks[s]
                upper = color_breaks[s + 1]
                break
        seg_range = upper[0] - lower[0]
        t = (elev - lower[0]) / seg_range if seg_range > 0 else 0.0
        for ch in range(3):
            lut[i, ch] = _js_round(lower[1][ch] + t * (upper[1][ch] - lower[1][ch]))

    return lut


# ---------------------------------------------------------------------------
# Read-only accessors (typed views over the JSON single source)
# ---------------------------------------------------------------------------


def koppen_colors() -> dict[str, str]:
    """Köppen-Geiger class → hex colour (incl. ``Ocean``)."""
    return dict(_PALETTES["categorical"]["koppen"])


def whittaker_colors() -> dict[str, str]:
    """Whittaker biome name → hex colour."""
    return dict(_PALETTES["categorical"]["whittaker"])


def soil_colors() -> dict[str, str]:
    """USDA soil order → hex colour."""
    return dict(_PALETTES["categorical"]["soil"])


def plate_colors() -> list[str]:
    """Distinct categorical hex palette for tectonic plates."""
    return list(_PALETTES["categorical"]["plate"])


def continuous_scale(name: str) -> list[ColorStop]:
    """Return a named continuous scale (terrain/landsea/npp/... )."""
    return list(_PALETTES["continuous"][name])


def adaptive_terrain_lut_size() -> int:
    """Number of entries in the adaptive terrain LUT."""
    return int(_PALETTES["adaptive_terrain"]["lut_size"])
