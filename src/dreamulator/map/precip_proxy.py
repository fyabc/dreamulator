"""Geomorphic precipitation proxy (Phase 3B — terrain-pipeline §10.2).

A pure function ``(terrain, latitude, planet params) → P`` (mm/yr) that drives the
fluvial-erosion loop without reading the climate engine (which is downstream —
a DAG cycle).

The proxy decomposes into two physically distinct parts so **one proxy serves any
circulation regime** (Earth's three-cell, a tidally-locked single-cell, and any
Hadley extent):

- **Zonal base field** ``P_base(lat)`` — circulation-dependent, mirrors the
  climate engine's zonal terms (ITCZ convective peak + subtropical suppression +
  mid-latitude storm track), parameterized by the SAME config knobs
  (``hadley_extent_deg``, ``storm_track_amplitude_mm``, ``precip_proxy_base_mm``).
- **Orographic response** ``P_orog(x)`` — circulation-independent linear upslope:
  ``w = U · ∇h`` (the zonal wind ``hadley_cell_wind`` forcing air over terrain);
  rain on the windward side, drying on the lee side.

Reference: Smith & Barstad (2004) linear theory of orographic precipitation — the
upslope term here is its zero-advection limit; the full Fourier transfer function
(downwind advection of condensed water) is a later refinement.  Fastscape/Landlab
take precipitation as an external field the same way (``water__unit_flux_in``).

Modes (``config.climate_coupling``):

- ``"none"`` — uniform precipitation (base only, no latitude/orographic structure).
- ``"proxy"`` — the decomposed proxy (default).
- ``"full"`` — read climate output (interface only; not implemented).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from .pipeline_types import TerrainPipelineConfig

# Subtropical suppression amplitude (mirrors climate_simulator.py Step 6).
_SUBTROP_AMPLITUDE = 0.6
# Orographic upslope efficiency: fractional precip change per m/s of vertical
# wind (w = U·∇h).  A gentle first-order modulation — the full Smith & Barstad
# (2004) transfer function (downwind advection) is a later refinement.
_ORO_EFF_S_PER_M = 0.2
# Clamp for the multiplicative orographic factor (±50 % — never negative).
_ORO_MIN = 0.5
_ORO_MAX = 1.5


def _zonal_base_precip(lat_deg: np.ndarray, config: TerrainPipelineConfig) -> np.ndarray:
    """Circulation-dependent zonal base precipitation (mm/yr).

    Mirrors the climate engine's zonal terms, reusing the same config knobs:

    - ITCZ convective peak: Gaussian centred on the thermal equator (0°), width
      ∝ Hadley extent (broad for a single-cell tidally-locked world, narrow for
      a fast three-cell rotator).
    - Subtropical suppression: Gaussian dry band at ``hadley_extent_deg``,
      σ = 2.5 / sin(H) (Rossby radius scaling), amplitude 0.6.
    - Storm track: mid-latitude Gaussian (only when ``storm_track_amplitude_mm``
      > 0, i.e. multi-cell worlds — disabled for single-cell).
    """
    abs_lat = np.abs(lat_deg)
    hadley = max(config.hadley_extent_deg, 1.0)

    # ITCZ width scales with Hadley extent: single-cell (H=90°) → ~31°, Earth
    # (H=30°) → ~10.5° (floored at 5°).
    itcz_sigma = max(hadley * 0.35, 5.0)
    p: np.ndarray = config.precip_proxy_base_mm * np.exp(-0.5 * (abs_lat / itcz_sigma) ** 2)

    # Subtropical suppression (mirrors climate Step 6): narrow dry band at the
    # Hadley boundary.  For single-cell (H=90°) this shrinks to the pole.
    centre = hadley
    sigma = 2.5 / np.sin(np.radians(centre))
    suppression = 1.0 - _SUBTROP_AMPLITUDE * np.exp(-0.5 * ((abs_lat - centre) / sigma) ** 2)
    p *= np.clip(suppression, 0.2, 1.0)

    # Storm track (mirrors climate Step 3.5), only for multi-cell worlds.
    if config.storm_track_amplitude_mm > 0.0:
        storm_center = hadley + 28.0
        storm_width = 14.0 * (hadley / 30.0)
        p += config.storm_track_amplitude_mm * np.exp(
            -0.5 * ((abs_lat - storm_center) / storm_width) ** 2
        )

    return p


def _orographic_factor(
    elevation: np.ndarray,
    xyz: np.ndarray,
    is_land: np.ndarray,
    neighbors: list[list[int]],
    dists_m: list[list[float]],
    config: TerrainPipelineConfig,
) -> np.ndarray:
    """Multiplicative orographic factor (windward > 1, leeward < 1).

    Computes the terrain gradient on the tangent plane and dots it with the
    zonal ``hadley_cell_wind`` field: ``w = U · ∇h`` is the vertical velocity
    forced by the terrain.  Positive ``w`` (air rises) enhances precipitation;
    negative ``w`` (air sinks) suppresses it — the linear upslope model.
    """
    from dreamulator.engine.climate_physics import hadley_cell_wind
    from dreamulator.map.ocean_circulation import east_north_basis

    n = len(elevation)
    lat_rad = np.arcsin(np.clip(xyz[:, 1], -1.0, 1.0))

    wind = hadley_cell_wind(
        lat_rad,
        xyz,
        hadley_extent_deg=config.hadley_extent_deg,
        polar_cell_start_deg=config.polar_cell_start_deg,
        rotation_period_days=config.rotation_period_days,
    )
    east, _ = east_north_basis(xyz)

    # Terrain gradient (tangent-plane least-squares from neighbours), m per m.
    grad = np.zeros((n, 3))
    for i in range(n):
        if not is_land[i]:
            continue
        acc = np.zeros(3)
        cnt = 0
        for k, j in enumerate(neighbors[i]):
            d = dists_m[i][k]
            if d <= 0.0 or not is_land[j]:
                continue
            delta = xyz[j] - xyz[i]
            delta -= float(np.dot(delta, xyz[i])) * xyz[i]  # project to tangent
            norm = float(np.linalg.norm(delta))
            if norm < 1e-12:
                continue
            delta /= norm
            acc += (elevation[j] - elevation[i]) / d * delta
            cnt += 1
        if cnt:
            grad[i] = acc / cnt

    # Vertical wind forced by terrain: w = U · ∇h (m/s).
    uplift = np.asarray(np.einsum("ij,ij->i", wind, grad))
    factor = 1.0 + _ORO_EFF_S_PER_M * uplift
    result: np.ndarray = np.where(is_land, np.clip(factor, _ORO_MIN, _ORO_MAX), 0.0)
    return result


def geomorphic_precipitation(
    elevation: np.ndarray,
    lat_deg: np.ndarray,
    xyz: np.ndarray,
    is_land: np.ndarray,
    neighbors: list[list[int]],
    dists_m: list[list[float]],
    config: TerrainPipelineConfig,
) -> np.ndarray:
    """Return a per-cell precipitation field (mm/yr) for the erosion loop.

    Args:
        elevation: (n,) elevation (m).
        lat_deg: (n,) latitude (degrees).
        xyz: (n, 3) unit-sphere positions (for the wind + terrain gradient).
        is_land: (n,) bool land mask.
        neighbors: per-cell neighbour index lists.
        dists_m: per-cell edge lengths (metres).
        config: Pipeline configuration.

    Returns:
        (n,) precipitation in mm/yr (ocean cells get 0).
    """
    mode = config.climate_coupling

    if mode == "none":
        return np.where(is_land, config.precip_proxy_base_mm, 0.0)

    if mode == "proxy":
        base = _zonal_base_precip(lat_deg, config)
        oro = _orographic_factor(elevation, xyz, is_land, neighbors, dists_m, config)
        return np.where(is_land, base * oro, 0.0)

    if mode == "full":
        raise NotImplementedError(
            "climate_coupling='full' reads the climate engine output, which is "
            "downstream of geological (DAG cycle); not implemented."
        )
    raise ValueError(f"Unknown climate_coupling mode: {mode!r}")
