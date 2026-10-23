"""Semi-Lagrangian cloud advection on the equirectangular grid (L4 prototype).

The L4 requirement is that cloud textures move along the wind field instead of
being regenerated each frame.  This module implements the advection step
independently of rendering:

* the wind (east/north, m/s) is converted to angular displacement per time
  step, with the longitude term divided by ``cos(latitude)``;
* the field is back-traced with bilinear sampling, periodic in longitude and
  clamped at the poles;
* forward-backward error compensation (BFECC, Kim et al. 2005) subtracts half
  the round-trip error to limit the numerical diffusion of a plain
  semi-Lagrangian step.

This is a look-dev prototype: the wind is the engine's annual mean field until
the L1 layer pack supplies 6-hourly winds.  It is not a cloud microphysics
model — condensation/evaporation and the large-scale cover field are unchanged;
only the existing texture is transported.
"""

from __future__ import annotations

import math

import numpy as np


def _grid_latitude_rad(height: int) -> np.ndarray:
    """Pixel-centre latitudes (radians), row 0 = north edge."""
    return (0.5 - (np.arange(height, dtype=np.float64) + 0.5) / height) * math.pi


def _grid_longitude_rad(width: int) -> np.ndarray:
    """Pixel-centre longitudes (radians), column 0 = western edge."""
    return ((np.arange(width, dtype=np.float64) + 0.5) / width) * 2.0 * math.pi - math.pi


def _sample_wrapped(field: np.ndarray, row: np.ndarray, col: np.ndarray) -> np.ndarray:
    """Bilinear sample with periodic longitude and clamped latitude."""
    height, width = field.shape
    r0 = np.floor(row).astype(np.int64)
    c0 = np.floor(col).astype(np.int64)
    fr = row - r0
    fc = col - c0
    r0c = np.clip(r0, 0, height - 1)
    r1c = np.clip(r0 + 1, 0, height - 1)
    c0w = np.mod(c0, width)
    c1w = np.mod(c0 + 1, width)
    return np.asarray(
        field[r0c, c0w] * (1.0 - fr) * (1.0 - fc)
        + field[r1c, c0w] * fr * (1.0 - fc)
        + field[r0c, c1w] * (1.0 - fr) * fc
        + field[r1c, c1w] * fr * fc,
        dtype=np.float64,
    )


def _catmull_rom_weights(t: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Catmull–Rom cubic weights for the four samples around a cell."""
    t2 = t * t
    t3 = t2 * t
    return (
        -0.5 * t3 + t2 - 0.5 * t,
        1.5 * t3 - 2.5 * t2 + 1.0,
        -1.5 * t3 + 2.0 * t2 + 0.5 * t,
        0.5 * t3 - 0.5 * t2,
    )


def _sample_wrapped_cubic(field: np.ndarray, row: np.ndarray, col: np.ndarray) -> np.ndarray:
    """Catmull–Rom sample with periodic longitude and clamped latitude.

    Cubic interpolation substantially reduces the numerical diffusion of the
    bilinear semi-Lagrangian step, at roughly four times the sampling cost.
    The result is not renormalised: Catmull–Rom can overshoot at sharp edges,
    so the caller clips it to the field range.
    """
    height, width = field.shape
    r0 = np.floor(row).astype(np.int64)
    c0 = np.floor(col).astype(np.int64)
    fr = row - r0
    fc = col - c0
    wr = _catmull_rom_weights(fr)
    wc = _catmull_rom_weights(fc)
    rows = [np.clip(r0 + k, 0, height - 1) for k in (-1, 0, 1, 2)]
    cols = [np.mod(c0 + k, width) for k in (-1, 0, 1, 2)]

    result = np.zeros_like(field, dtype=np.float64)
    for i, ri in enumerate(rows):
        for j, cj in enumerate(cols):
            result += field[ri, cj] * (wr[i] * wc[j])
    return result


def _trace(
    field: np.ndarray,
    dlon: np.ndarray,
    dlat: np.ndarray,
    latitude: np.ndarray,
    *,
    sign: float,
    interp: str = "linear",
) -> np.ndarray:
    """Sample ``field`` at the position displaced by ``-sign * (dlon, dlat)``."""
    height, width = field.shape
    lon_src = _grid_longitude_rad(width)[None, :] - sign * dlon
    lat_src = latitude[:, None] - sign * dlat
    row = (0.5 * math.pi - lat_src) / math.pi * height - 0.5
    col = (lon_src + math.pi) / (2.0 * math.pi) * width - 0.5
    if interp == "cubic":
        return _sample_wrapped_cubic(field, row, col)
    return _sample_wrapped(field, row, col)


def advect_equirect(
    field: np.ndarray,
    wind_east_m_s: np.ndarray,
    wind_north_m_s: np.ndarray,
    *,
    dt_seconds: float,
    radius_km: float,
    substeps: int = 4,
    bfecc: bool = True,
    interp: str = "linear",
) -> np.ndarray:
    """Advect an equirectangular field by one time step.

    ``field``, ``wind_east_m_s`` and ``wind_north_m_s`` share the same grid
    (row 0 = north edge, periodic in longitude).  ``dt_seconds`` is split into
    ``substeps`` to keep the trajectory piecewise smooth; BFECC then reduces
    the diffusion of the semi-Lagrangian interpolation.  ``interp="cubic"``
    uses Catmull–Rom sampling instead of bilinear, which further limits
    diffusion at a higher per-step cost.  The result is clipped to the field's
    original [0, 1] range.
    """
    field = np.asarray(field, dtype=np.float64)
    u = np.asarray(wind_east_m_s, dtype=np.float64)
    v = np.asarray(wind_north_m_s, dtype=np.float64)
    if field.ndim != 2 or u.shape != field.shape or v.shape != field.shape:
        raise ValueError("field, wind_east_m_s and wind_north_m_s must share a 2-D grid")
    if substeps < 1:
        raise ValueError("substeps must be >= 1")
    if interp not in {"linear", "cubic"}:
        raise ValueError("interp must be 'linear' or 'cubic'")
    radius_m = radius_km * 1000.0
    height, _ = field.shape
    latitude = _grid_latitude_rad(height)
    cos_lat = np.maximum(np.cos(latitude)[:, None], 1e-3)
    step = float(dt_seconds) / substeps

    result = np.clip(field, 0.0, 1.0)
    for _ in range(substeps):
        dlon = u * step / (radius_m * cos_lat)
        dlat = v * step / radius_m
        forward = _trace(result, dlon, dlat, latitude, sign=1.0, interp=interp)
        if bfecc:
            backward = _trace(forward, dlon, dlat, latitude, sign=-1.0, interp=interp)
            forward = forward - 0.5 * (backward - result)
        result = np.clip(forward, 0.0, 1.0)
    return np.asarray(result, dtype=np.float64)


def advection_substeps(
    wind_east_m_s: np.ndarray,
    wind_north_m_s: np.ndarray,
    *,
    dt_seconds: float,
    radius_km: float,
    max_cells_per_step: float = 8.0,
    max_substeps: int = 8,
) -> int:
    """Choose a substep count that keeps the per-step displacement bounded.

    Semi-Lagrangian advection is unconditionally stable, so this is an
    accuracy/diffusion control, not a CFL stability requirement.  The default
    allows up to eight grid cells per substep and caps the count at eight.
    """
    height, width = wind_east_m_s.shape
    latitude = _grid_latitude_rad(height)
    cos_lat = np.maximum(np.cos(latitude)[:, None], 1e-3)
    radius_m = radius_km * 1000.0
    dlon = np.max(np.abs(wind_east_m_s) * dt_seconds / (radius_m * cos_lat))
    dlat = np.max(np.abs(wind_north_m_s) * dt_seconds / radius_m)
    cell = 2.0 * math.pi / width
    cells = max(dlon, dlat) / cell
    return int(min(max_substeps, max(1, math.ceil(cells / max_cells_per_step))))
