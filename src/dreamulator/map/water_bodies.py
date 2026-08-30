"""Water-body classification — ocean / land split from a real or derived mask.

The climate engine's land/ocean split cannot be a bare ``elevation >= 0`` test:
it misclassifies (a) dry endorheic basins below sea level (Turpan −154 m) as
ocean, and (b) inland seas/lakes (Caspian, Dead Sea) as indistinguishable from
either ocean or land.  Instead the split comes from a **water mask** plus a
**size criterion**:

- **Ocean** — cells connected to the global ocean, *or* inland water bodies
  large enough to moderate climate (Caspian, ~371 000 km²).
- **Land** — dry land (including below-sea-level basins like Turpan) *and*
  water bodies too small to matter (Dead Sea, ~600 km²).

The size threshold is the existing maritime-moderation scale
(``seasonal_coastal_scale_km``): a water body has to be at least that wide for
its influence to extend beyond itself, hence the area threshold
``(scale_km)²``.

For the real Earth this is driven by the GSHHG hierarchy (ocean = level 1,
lakes = level 2); for generated worlds by flood-fill connectivity on the
synthesised elevation (see :func:`compute_land_mask`).  This module provides
the pure geometry/classification helpers, independent of the data source.
"""

from __future__ import annotations

import math
import struct
from collections import deque
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from .models import VoronoiCell

# Minimum area (km²) for an enclosed water body to be treated as "ocean-like"
# for climate.  = (maritime-moderation scale)²; the scale is 250 km (see
# pipeline_types.seasonal_coastal_scale_km).  Caspian (371k) / Red Sea (438k) /
# Black Sea (436k) pass; Dead Sea (605) fails — a two-order-of-magnitude gap, so
# the exact value is not sensitive.
_MIN_OCEAN_LIKE_LAKE_KM2: float = 6.0e4

# km per degree at the equator (longitude) and latitude (WGS84 spheroid mean).
_KM_PER_DEG_LON = 111.32
_KM_PER_DEG_LAT = 110.57


# ---------------------------------------------------------------------------
# Shapefile parsing (minimal ESRI .shp reader — no external dependency)
# ---------------------------------------------------------------------------


def read_shp_polygons(data: bytes) -> list[list[list[tuple[float, float]]]]:
    """Parse a polygon ``.shp`` file's bytes → list of polygons.

    Each polygon is a list of rings; each ring is a list of ``(lon, lat)``
    floats.  Reads only polygon records (shape type 5); other shapes are
    skipped.  Assumes the standard ESRI shapefile layout (100-byte header +
    big-endian record headers + little-endian geometry).

    Args:
        data: Raw ``.shp`` file bytes.

    Returns:
        List of polygons, each a list of rings.
    """
    if len(data) < 100:
        return []
    shape_type = struct.unpack("<i", data[32:36])[0]
    if shape_type != 5:  # 5 = Polygon
        return []

    polygons: list[list[list[tuple[float, float]]]] = []
    off = 100
    while off + 8 <= len(data):
        _, content_len = struct.unpack(">ii", data[off : off + 8])
        content = data[off + 8 : off + 8 + content_len * 2]
        if len(content) < 4:
            break
        stype = struct.unpack("<i", content[0:4])[0]
        if stype == 5:
            num_parts, num_points = struct.unpack("<ii", content[36:44])
            parts = struct.unpack(f"<{num_parts}i", content[44 : 44 + 4 * num_parts])
            pts = np.frombuffer(
                content[44 + 4 * num_parts : 44 + 4 * num_parts + 16 * num_points],
                dtype="<f8",
            ).reshape(-1, 2)
            rings: list[list[tuple[float, float]]] = []
            for p in range(num_parts):
                a = parts[p]
                b = parts[p + 1] if p + 1 < num_parts else num_points
                rings.append([(float(x), float(y)) for x, y in pts[a:b]])
            polygons.append(rings)
        off += 8 + content_len * 2
    return polygons


# ---------------------------------------------------------------------------
# Geometry — even-odd point-in-polygon and area
# ---------------------------------------------------------------------------


def points_in_rings(
    lons: np.ndarray, lats: np.ndarray, rings: list[list[tuple[float, float]]]
) -> np.ndarray:
    """Even-odd point-in-polygon over the union of *rings*, with bbox pruning.

    Args:
        lons: Cell longitudes (deg), shape (N,).
        lats: Cell latitudes (deg), shape (N,).
        rings: A single polygon as a list of ``(lon, lat)`` rings.

    Returns:
        Boolean array, shape (N,), True where the cell is inside any ring.
    """
    n = len(lons)
    inside = np.zeros(n, dtype=bool)
    for ring in rings:
        if len(ring) < 3:
            continue
        rlons = np.array([p[0] for p in ring])
        rlats = np.array([p[1] for p in ring])
        in_bbox = (
            (lons >= rlons.min())
            & (lons <= rlons.max())
            & (lats >= rlats.min())
            & (lats <= rlats.max())
        )
        if not in_bbox.any():
            continue
        idx = np.flatnonzero(in_bbox)
        inside[idx] |= _points_in_ring(lons[idx], lats[idx], ring)
    return inside


def _points_in_ring(
    lons: np.ndarray, lats: np.ndarray, ring: list[tuple[float, float]]
) -> np.ndarray:
    """Vectorised even-odd for one closed ring (no bbox pruning)."""
    m = len(ring)
    inside = np.zeros(lons.shape, dtype=bool)
    j = m - 1
    for i in range(m):
        xi, yi = ring[i]
        xj, yj = ring[j]
        cond = (yi > lats) != (yj > lats)
        denom = yj - yi
        with np.errstate(divide="ignore", invalid="ignore"):
            x_int = xj - (xj - xi) * (yj - lats) / denom
        hit = cond & (lons < x_int)
        inside[hit] = ~inside[hit]
        j = i
    return inside


def rings_area_km2(rings: list[list[tuple[float, float]]]) -> float:
    """Approximate equirectangular area (km²) of a polygon (all rings)."""
    total = 0.0
    for ring in rings:
        if len(ring) < 3:
            continue
        xs = np.array([p[0] for p in ring])
        ys = np.array([p[1] for p in ring])
        # Shoelace in deg², then scale by the local km/deg at the mean latitude.
        shoelace = 0.5 * abs(float(np.sum(xs[:-1] * ys[1:] - xs[1:] * ys[:-1])))
        mean_lat = float(np.mean(ys))
        total += shoelace * _KM_PER_DEG_LON * _KM_PER_DEG_LAT * math.cos(math.radians(mean_lat))
    return total


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def classify_ocean_land(
    lons: np.ndarray,
    lats: np.ndarray,
    land_polys: list[list[list[tuple[float, float]]]],
    lake_polys: list[list[list[tuple[float, float]]]],
    lake_threshold_km2: float = _MIN_OCEAN_LIKE_LAKE_KM2,
) -> np.ndarray:
    """Classify cells as ocean (False) or land (True).

    - A cell inside a *land* polygon (and no lake) is land.
    - A cell inside a *lake* polygon is land if the lake is small (negligible
      climate effect), ocean if large (ocean-like moderation) — e.g. Caspian.
    - Anything else (the open ocean) is ocean.

    Args:
        lons, lats: Cell coordinates (deg), shape (N,).
        land_polys: Land polygons (GSHHG level 1).
        lake_polys: Lake polygons (GSHHG level 2).
        lake_threshold_km2: Minimum lake area (km²) to count as ocean-like.

    Returns:
        Boolean land mask, shape (N,).  True = land, False = ocean.
    """
    n = len(lons)
    in_land = np.zeros(n, dtype=bool)
    in_lake = np.zeros(n, dtype=bool)
    # A cell inside a large lake is "ocean" even though it is also inside land.
    in_large_lake = np.zeros(n, dtype=bool)

    for rings in land_polys:
        in_land |= points_in_rings(lons, lats, rings)
    for rings in lake_polys:
        is_in = points_in_rings(lons, lats, rings)
        in_lake |= is_in
        if rings_area_km2(rings) >= lake_threshold_km2:
            in_large_lake |= is_in

    land = in_land & ~in_lake  # emergent land (not a lake)
    land |= in_lake & ~in_large_lake  # small inland lakes are treated as land
    return land


def compute_land_mask(cells: list[VoronoiCell], sea_level_m: float = 0.0) -> np.ndarray:
    """Land mask via ocean connectivity (flood-fill from the global ocean).

    The land/ocean split cannot be a bare ``elevation >= 0`` test: endorheic
    basins below sea level (Turpan −154 m, Qattara, Afar, Death Valley) are dry
    LAND, not ocean.  This marks a cell as "ocean" only when it is part of a
    water body connected to the *global ocean* (the largest connected water
    basin); closed below-sea-level basins fall out as land.

    This is a **geological** property — elevation + sea level + connectivity on
    the synthesised terrain — not a climate field.  The terrain pipeline writes
    the resulting ``water_class``; the climate engine and frontend read it.

    Args:
        cells: All VoronoiCell objects (needs ``neighbors``).
        sea_level_m: Sea-level offset (from TerrainPipelineConfig).

    Returns:
        Boolean land mask, shape (N,).  True = land, False = ocean.
    """
    n = len(cells)
    is_water = np.array([c.elevation <= sea_level_m for c in cells], dtype=bool)

    basin_id = np.full(n, -1, dtype=np.int64)
    basins: list[np.ndarray] = []
    for seed in range(n):
        if not is_water[seed] or basin_id[seed] >= 0:
            continue
        queue: deque[int] = deque([seed])
        basin_id[seed] = len(basins)
        members: list[int] = [seed]
        while queue:
            i = queue.popleft()
            for j in cells[i].neighbors:
                if 0 <= j < n and is_water[j] and basin_id[j] < 0:
                    basin_id[j] = len(basins)
                    queue.append(j)
                    members.append(j)
        basins.append(np.array(members, dtype=np.int64))

    if not basins:
        # No water anywhere → the whole surface is land.
        return np.ones(n, dtype=bool)

    # Global ocean = largest connected water basin.  Everything else is land
    # (emergent land AND closed below-sea-level basins / inland lakes).
    ocean = np.zeros(n, dtype=bool)
    ocean[max(basins, key=len)] = True
    return ~ocean
