"""Elevation codec — encode/decode heightmaps as 16-bit PNG.

The heightmap is stored as a normalised numpy array with values in [0, 1].
For persistent storage it is quantised to 16-bit unsigned integers and saved
as a single-channel PNG.  On load the values are de-quantised back to [0, 1].

Pillow's ``I;16`` mode is used for 16-bit grayscale I/O.
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

import numpy as np
from PIL import Image

if TYPE_CHECKING:
    pass

# 16-bit quantisation range
_UINT16_MAX = np.uint16(65535)
_UINT16_MAX_F = 65535.0


# ---------------------------------------------------------------------------
# Encode / decode
# ---------------------------------------------------------------------------


def encode_elevation(
    elevation: np.ndarray,
    min_m: float = -11_000.0,
    max_m: float = 9_000.0,
) -> bytes:
    """Encode a normalised heightmap to 16-bit PNG bytes.

    Args:
        elevation: 2-D array with values in [0, 1].
        min_m: Minimum elevation in metres (stored in metadata, not encoded).
        max_m: Maximum elevation in metres (stored in metadata, not encoded).

    Returns:
        PNG file content as bytes.
    """
    if elevation.ndim != 2:
        raise ValueError(f"Expected 2-D array, got shape {elevation.shape}")

    # Clamp to [0, 1] then quantise to uint16
    clamped = np.clip(elevation, 0.0, 1.0)
    quantised = (clamped * _UINT16_MAX_F).astype(np.uint16)

    img = Image.fromarray(quantised, mode="I;16")
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=False)
    return buf.getvalue()


def decode_elevation(png_bytes: bytes) -> np.ndarray:
    """Decode 16-bit PNG bytes to a normalised heightmap.

    Args:
        png_bytes: PNG file content (single-channel, ideally 16-bit).

    Returns:
        2-D numpy float64 array with values in [0, 1].
    """
    buf = io.BytesIO(png_bytes)
    img = Image.open(buf)

    # Handle different bit depths Pillow may return
    if img.mode == "I;16":
        arr = np.array(img, dtype=np.uint16).astype(np.float64) / _UINT16_MAX_F
    elif img.mode == "I":
        # Pillow sometimes loads 16-bit PNG as 32-bit signed int
        arr = np.array(img, dtype=np.float64)
        arr_max = arr.max()
        if arr_max > _UINT16_MAX_F:
            # Likely 32-bit data; normalise by its own max
            arr = arr / arr_max if arr_max > 0 else arr
        else:
            arr = arr / _UINT16_MAX_F
    elif img.mode == "L":
        # 8-bit fallback
        arr = np.array(img, dtype=np.float64) / 255.0
    else:
        # Convert anything else to grayscale first
        gray = img.convert("L")
        arr = np.array(gray, dtype=np.float64) / 255.0

    return np.clip(arr, 0.0, 1.0)


# ---------------------------------------------------------------------------
# Elevation ↔ metres conversions
# ---------------------------------------------------------------------------


def elevation_to_meters(normalised: float, min_m: float, max_m: float) -> float:
    """Convert a normalised elevation value to metres.

    Args:
        normalised: Value in [0, 1].
        min_m: Elevation corresponding to 0.
        max_m: Elevation corresponding to 1.

    Returns:
        Elevation in metres.
    """
    return min_m + normalised * (max_m - min_m)


def meters_to_elevation(meters: float, min_m: float, max_m: float) -> float:
    """Convert metres to a normalised elevation value.

    Args:
        meters: Elevation in metres.
        min_m: Elevation corresponding to 0.
        max_m: Elevation corresponding to 1.

    Returns:
        Normalised value clamped to [0, 1].
    """
    if max_m <= min_m:
        return 0.5
    return float(np.clip((meters - min_m) / (max_m - min_m), 0.0, 1.0))


# ---------------------------------------------------------------------------
# Spatial sampling
# ---------------------------------------------------------------------------


def lon_lat_to_pixel(
    lon: float,
    lat: float,
    width: int,
    height: int,
) -> tuple[int, int]:
    """Convert (lon, lat) to pixel (x, y) in equirectangular projection.

    Args:
        lon: Longitude in degrees [-180, 180].
        lat: Latitude in degrees [-90, 90].
        width: Raster width in pixels.
        height: Raster height in pixels.

    Returns:
        (x, y) pixel coordinates, clamped to valid range.
    """
    x = int((lon + 180.0) / 360.0 * width)
    y = int((90.0 - lat) / 180.0 * height)
    return (
        max(0, min(width - 1, x)),
        max(0, min(height - 1, y)),
    )


def pixel_to_lon_lat(
    x: int,
    y: int,
    width: int,
    height: int,
) -> tuple[float, float]:
    """Convert pixel (x, y) to (lon, lat) in equirectangular projection.

    Args:
        x: Pixel x coordinate.
        y: Pixel y coordinate.
        width: Raster width in pixels.
        height: Raster height in pixels.

    Returns:
        (lon, lat) in degrees.
    """
    lon = (x / width) * 360.0 - 180.0
    lat = 90.0 - (y / height) * 180.0
    return lon, lat


def sample_elevation_at(
    elevation: np.ndarray,
    lon: float,
    lat: float,
) -> float:
    """Sample the normalised elevation at a given (lon, lat).

    Args:
        elevation: 2-D normalised heightmap array.
        lon: Longitude in degrees [-180, 180].
        lat: Latitude in degrees [-90, 90].

    Returns:
        Normalised elevation value in [0, 1].
    """
    h, w = elevation.shape
    x, y = lon_lat_to_pixel(lon, lat, w, h)
    return float(elevation[y, x])
