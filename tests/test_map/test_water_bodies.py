"""Tests for water-body classification (water_bodies.py pure functions)."""

from __future__ import annotations

import struct

import numpy as np
import pytest

from dreamulator.map.water_bodies import (
    classify_ocean_land,
    points_in_rings,
    read_shp_polygons,
    rings_area_km2,
)

# ---------------------------------------------------------------------------
# .shp reader
# ---------------------------------------------------------------------------


def _make_shp(rings: list[list[tuple[float, float]]]) -> bytes:
    """Craft a minimal ESRI .shp file (one polygon, possibly multi-ring)."""
    num_parts = len(rings)
    num_points = sum(len(r) for r in rings)
    parts = [0]
    for r in rings[:-1]:
        parts.append(parts[-1] + len(r))
    points = [p for r in rings for p in r]

    content = struct.pack("<i", 5)  # shape type
    content += struct.pack("<4d", 0.0, 0.0, 10.0, 10.0)  # bbox
    content += struct.pack("<ii", num_parts, num_points)
    content += struct.pack(f"<{num_parts}i", *parts)
    content += struct.pack(f"<{num_points * 2}d", *(c for p in points for c in p))

    content_len = len(content) // 2
    record = struct.pack(">ii", 1, content_len) + content
    file_len = (100 + len(record)) // 2

    header = struct.pack(">i", 9994) + b"\x00" * 20
    header += struct.pack(">i", file_len)
    header += struct.pack("<ii", 1000, 5)
    header += struct.pack("<4d", 0.0, 0.0, 10.0, 10.0)
    header += b"\x00" * (100 - len(header))
    return header + record


def test_read_shp_polygons_single_square() -> None:
    data = _make_shp([[(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0, 0.0)]])
    polys = read_shp_polygons(data)
    assert len(polys) == 1
    assert len(polys[0]) == 1  # one ring
    assert polys[0][0][0] == (0.0, 0.0)
    assert len(polys[0][0]) == 5


def test_read_shp_polygons_empty() -> None:
    assert read_shp_polygons(b"") == []
    assert read_shp_polygons(b"\x00" * 50) == []


# ---------------------------------------------------------------------------
# Even-odd point-in-polygon + area
# ---------------------------------------------------------------------------


def test_points_in_rings_square() -> None:
    rings = [[(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0, 0.0)]]
    lons = np.array([5.0, 15.0, 5.0])
    lats = np.array([5.0, 5.0, 20.0])
    inside = points_in_rings(lons, lats, rings)
    assert list(inside) == [True, False, False]


def test_rings_area_km2_square() -> None:
    rings = [[(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0, 0.0)]]
    # 10° × 10° at the equator ≈ 10*111.32 * 10*110.57 ≈ 1.23e6 km²
    assert rings_area_km2(rings) == pytest.approx(1.23e6, rel=0.05)


# ---------------------------------------------------------------------------
# classify_ocean_land — land / large-lake / small-lake
# ---------------------------------------------------------------------------


def test_classify_ocean_land_small_lake_is_land() -> None:
    # One land polygon covering everything; one small lake inside it.
    land = [[(-180.0, -90.0), (180.0, -90.0), (180.0, 90.0), (-180.0, 90.0), (-180.0, -90.0)]]
    tiny_lake = [[(0.0, 0.0), (0.1, 0.0), (0.1, 0.1), (0.0, 0.1), (0.0, 0.0)]]  # ~123 km²
    lons = np.array([5.0, 0.05])
    lats = np.array([5.0, 0.05])
    out = classify_ocean_land(lons, lats, [land], [tiny_lake])
    # (5,5) is land (in land, not lake); (0.05,0.05) is a tiny lake → land.
    assert list(out) == [True, True]


def test_classify_ocean_land_large_lake_is_ocean() -> None:
    land = [[(-180.0, -90.0), (180.0, -90.0), (180.0, 90.0), (-180.0, 90.0), (-180.0, -90.0)]]
    big_lake = [[(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0, 0.0)]]  # ~1.23e6 km²
    lons = np.array([5.0, 20.0])
    lats = np.array([5.0, 20.0])
    out = classify_ocean_land(lons, lats, [land], [big_lake])
    # (5,5) is in a large lake → ocean; (20,20) is land (in land, no lake).
    assert list(out) == [False, True]


def test_classify_ocean_land_open_ocean() -> None:
    # A single island; everything else is ocean.
    island = [[(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0, 0.0)]]
    lons = np.array([5.0, 50.0])
    lats = np.array([5.0, 5.0])
    out = classify_ocean_land(lons, lats, [island], [])
    assert list(out) == [True, False]
