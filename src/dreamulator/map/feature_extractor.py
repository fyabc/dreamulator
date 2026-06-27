"""Feature extractor — extract linear/point features from heightmaps.

Provides basic extraction of coastlines, ridges, and river networks
from a normalised elevation array.  Output is a list of (lon, lat)
polylines suitable for SVG rendering.
"""

from __future__ import annotations

import numpy as np
from scipy import ndimage

from .elevation_codec import pixel_to_lon_lat
from .models import FeatureType, MapFeature


def extract_coastlines(
    elevation: np.ndarray,
    sea_level: float,
    width: int,
    height: int,
    *,
    min_length: int = 20,
) -> list[MapFeature]:
    """Extract coastlines as contour lines at the sea level.

    Args:
        elevation: 2-D normalised heightmap.
        sea_level: Normalised sea level threshold.
        width: Map width in pixels.
        height: Map height in pixels.
        min_length: Minimum contour length (in pixels) to keep.

    Returns:
        List of MapFeature objects with type COASTLINE.
    """
    # Binary land/water mask
    land = elevation >= sea_level

    # Find contour at sea level using morphological gradient
    kernel = np.ones((3, 3), dtype=bool)
    dilated = ndimage.binary_dilation(land, structure=kernel)
    eroded = ndimage.binary_erosion(land, structure=kernel)
    coast_mask = dilated & ~eroded

    # Trace connected components as polylines
    return _mask_to_polylines(coast_mask, width, height, FeatureType.COASTLINE, min_length)


def extract_ridges(
    elevation: np.ndarray,
    width: int,
    height: int,
    *,
    threshold: float = 0.7,
    min_length: int = 15,
) -> list[MapFeature]:
    """Extract mountain ridges using local maxima detection.

    Args:
        elevation: 2-D normalised heightmap.
        width: Map width in pixels.
        height: Map height in pixels.
        threshold: Minimum normalised elevation to consider as ridge.
        min_length: Minimum ridge length to keep.

    Returns:
        List of MapFeature objects with type RIDGE.
    """
    # Local maximum along horizontal axis (ridge crests)
    left = np.roll(elevation, 1, axis=1)
    right = np.roll(elevation, -1, axis=1)
    ridge_mask = (elevation > left) & (elevation > right) & (elevation > threshold)

    return _mask_to_polylines(ridge_mask, width, height, FeatureType.RIDGE, min_length)


def extract_rivers(
    elevation: np.ndarray,
    width: int,
    height: int,
    *,
    sea_level: float = 0.4,
    flow_threshold: int = 100,
) -> list[MapFeature]:
    """Extract river networks using simple flow accumulation.

    Water flows from each cell to its lowest neighbour.  Cells with
    accumulated flow above ``flow_threshold`` are classified as rivers.

    Args:
        elevation: 2-D normalised heightmap.
        width: Map width in pixels.
        height: Map height in pixels.
        sea_level: Normalised sea level (rivers stop at coast).
        flow_threshold: Minimum accumulation to be classified as river.

    Returns:
        List of MapFeature objects with type RIVER.
    """
    h, w = elevation.shape

    # Flow direction: each cell flows to its lowest neighbour
    flow_dir = _compute_flow_direction(elevation)

    # Flow accumulation: count how many cells flow through each cell
    accumulation = _compute_flow_accumulation(flow_dir, h, w)

    # River mask: high accumulation + above sea level
    river_mask = (accumulation >= flow_threshold) & (elevation > sea_level)

    return _mask_to_polylines(river_mask, width, height, FeatureType.RIVER, min_length=10)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compute_flow_direction(elevation: np.ndarray) -> np.ndarray:
    """Compute flow direction for each cell (index of steepest downhill neighbour).

    Returns an array where each value is the flat index of the neighbour
    the cell flows toward.  -1 for cells with no downhill neighbour.
    """
    h, w = elevation.shape
    # 8-connected offsets (dy, dx)
    offsets = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]

    flow_dir = np.full((h, w), -1, dtype=np.int32)

    for dy, dx in offsets:
        shifted = np.roll(np.roll(elevation, -dy, axis=0), -dx, axis=1)
        drop = elevation - shifted
        # Only consider downhill flows, and pick the steepest
        current_drop = np.where(
            flow_dir >= 0,
            elevation - np.take(elevation.ravel(), np.clip(flow_dir, 0, h * w - 1)).reshape(h, w),
            -999.0,
        )
        better = drop > current_drop
        # Compute flat index of the neighbour
        ys = np.clip(np.arange(h)[:, None] + dy, 0, h - 1)
        xs = np.clip(np.arange(w)[None, :] + dx, 0, w - 1)
        neighbour_idx = ys * w + xs
        flow_dir = np.where(better, neighbour_idx, flow_dir)

    return flow_dir


def _compute_flow_accumulation(
    flow_dir: np.ndarray, h: int, w: int
) -> np.ndarray:
    """Compute flow accumulation from flow directions.

    Each cell starts with 1 unit of water.  Water flows downstream,
    accumulating as it goes.
    """
    accumulation = np.ones((h, w), dtype=np.int32)
    flat_flow = flow_dir.ravel()

    # Process cells from highest to lowest elevation
    # (simplified — full D8 would use topological sort)
    # For performance, just do a few passes
    for _ in range(3):
        for y in range(h):
            for x in range(w):
                target = flow_dir[y, x]
                if target >= 0:
                    ty, tx = divmod(int(target), w)
                    accumulation[ty, tx] += accumulation[y, x]

    return accumulation


def _mask_to_polylines(
    mask: np.ndarray,
    width: int,
    height: int,
    feature_type: FeatureType,
    min_length: int,
) -> list[MapFeature]:
    """Convert a binary mask to a list of MapFeature polylines.

    Traces connected components and converts pixel coordinates to (lon, lat).
    """
    h, w = mask.shape

    # Label connected components
    labelled, num_features = ndimage.label(mask)

    features: list[MapFeature] = []
    for label_id in range(1, num_features + 1):
        component = labelled == label_id
        # Count pixels
        pixel_count = component.sum()
        if pixel_count < min_length:
            continue

        # Extract pixel coordinates (sample every N pixels for efficiency)
        ys, xs = np.where(component)
        if len(ys) == 0:
            continue

        # Sort by x then y to create a reasonable polyline
        # (a proper implementation would trace the skeleton)
        step = max(1, len(ys) // 200)  # max 200 points per feature
        indices = np.argsort(ys * w + xs)[::step]

        coords: list[tuple[float, float]] = []
        for idx in indices:
            lon, lat = pixel_to_lon_lat(int(xs[idx]), int(ys[idx]), width, height)
            coords.append((round(lon, 2), round(lat, 2)))

        if len(coords) >= 2:
            features.append(
                MapFeature(
                    id=f"{feature_type.value}_{label_id}",
                    type=feature_type,
                    coordinates=coords,
                )
            )

    return features
