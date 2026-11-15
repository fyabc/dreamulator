"""Source-preserving detail transfer on one fixed parent grid.

The sampling boundary is an author-declared assumption, not an accuracy
estimate. DCT-II uses reflective boundaries; overlapping products must be
cropped after blending the parent rather than blended independently.
"""

from __future__ import annotations

from enum import StrEnum

import numpy as np
from scipy.fft import dctn, idctn
from scipy.ndimage import distance_transform_edt


class RefinementMode(StrEnum):
    REDRAW = "redraw"
    BLEND = "blend"
    HYDROLOGY = "hydrology"


def detail_difference(
    source: np.ndarray, donor: np.ndarray, pixel_km: float, preserve_wavelength_km: float
) -> np.ndarray:
    """Return H(donor - source), with zero response in the trusted band."""
    if source.ndim != 2 or donor.shape != source.shape:
        raise ValueError("source and donor must share a two-dimensional grid")
    if not np.isfinite(source).all() or not np.isfinite(donor).all():
        raise ValueError("source and donor heights must be finite")
    if not np.isfinite(pixel_km) or pixel_km <= 0:
        raise ValueError("pixel_km must be positive")
    if not np.isfinite(preserve_wavelength_km) or preserve_wavelength_km < 4 * pixel_km:
        raise ValueError("preserve wavelength must be at least four output pixels")
    coefficients = dctn(donor.astype(np.float32) - source.astype(np.float32), norm="ortho")
    f0, f1 = 1 / preserve_wavelength_km, 2 / preserve_wavelength_km
    fx = np.arange(source.shape[1], dtype=np.float64) / (2 * source.shape[1] * pixel_km)
    for start in range(0, source.shape[0], 128):
        stop = min(start + 128, source.shape[0])
        fy = np.arange(start, stop, dtype=np.float64) / (2 * source.shape[0] * pixel_km)
        f = np.hypot(fy[:, None], fx[None, :])
        t = np.clip((f - f0) / (f1 - f0), 0, 1)
        coefficients[start:stop] *= (0.5 - 0.5 * np.cos(np.pi * t)).astype(np.float32)
    return np.asarray(idctn(coefficients, norm="ortho"), dtype=np.float32)


def blend_height(
    source: np.ndarray, delta: np.ndarray, pixel_km: float, fade_km: float, sea_level_m: float
) -> np.ndarray:
    """Fade detail at coasts/frame; retain seabed and restore crossed land pixels."""
    land = source > sea_level_m
    distance = distance_transform_edt(np.pad(land, 1))[1:-1, 1:-1] * pixel_km
    t = np.clip(np.maximum(distance - pixel_km, 0) / fade_km, 0, 1).astype(np.float32)
    height = np.asarray(source + t * t * (3 - 2 * t) * delta, dtype=np.float32)
    restore = ~land | (height <= sea_level_m)
    height[restore] = source[restore]
    return height


def cap_depression_depth(height: np.ndarray, source: np.ndarray, sea_level_m: float) -> np.ndarray:
    """Explicit terrain edit: cap geometric depression depth by the source's depth."""
    from dreamulator.map.prog_erosion import priority_flood

    source_filled, _, _ = priority_flood(source.astype(np.float64), source > sea_level_m)
    filled, _, _ = priority_flood(height.astype(np.float64), height > sea_level_m)
    excess = (filled.reshape(height.shape) - height) - (
        source_filled.reshape(source.shape) - source
    )
    edited = np.asarray(height + np.maximum(excess, 0), dtype=np.float32)
    edited[source <= sea_level_m] = source[source <= sea_level_m]
    return edited
