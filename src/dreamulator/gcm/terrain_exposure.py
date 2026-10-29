"""Terrain-exposure increments for conservative large-scale precipitation refinement.

The geometric index follows Böhner & Antonic (2009), as used by the SAGA
wind-effect method. Its metre-based angle transform, logarithmic response,
300 km support and quarter-power damping are empirical geomorphometric
parameters. They are not atmospheric conservation laws. CHELSA's within-parent
allocation supplies the separate water-budget constraint (Karger et al., 2017,
2023). Only the large-scale component receives this increment; convection
retains its existing shape and quota.

A whole-sphere terrain sampler fixes the physical support before any target
window is read. Fine and native topography use the same index; their ratio
represents the terrain contribution unresolved by the native atmosphere.
Rain-weighted directional quadrature preserves changes of wind direction
that disappear from the monthly mean vector.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from collections.abc import Callable

from .native_partition import NativePrecipitationField

METHOD_VERSION = "terrain-exposure-increment-v1"
SEARCH_KM = 300.0
STEP_ACCELERATION = 1.5


def upwind_coordinates(
    latitude: np.ndarray,
    longitude: np.ndarray,
    bearing_rad: float,
    distance_km: float,
    radius_km: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Great-circle destination opposite a north-clockwise flow bearing."""
    phi, lam = np.radians(latitude), np.radians(longitude)
    bearing = bearing_rad + np.pi
    distance = distance_km / radius_km
    lat = np.arcsin(
        np.clip(
            np.sin(phi) * np.cos(distance) + np.cos(phi) * np.sin(distance) * np.cos(bearing),
            -1,
            1,
        )
    )
    lon = lam + np.arctan2(
        np.sin(bearing) * np.sin(distance) * np.cos(phi),
        np.cos(distance) - np.sin(phi) * np.sin(lat),
    )
    return np.degrees(lat), np.degrees(lon) % 360


def terrain_exposure_index(
    latitude: np.ndarray,
    longitude: np.ndarray,
    bearing_rad: float,
    radius_km: float,
    sample_height_m: Callable[[np.ndarray, np.ndarray], np.ndarray],
    *,
    integration_spacing_km: float,
) -> np.ndarray:
    """Positive empirical exposure index; flat terrain has index one.

    Elevation differences are in metres and distance enters the published
    numerical index in metres. This dimensional convention belongs to its
    Earth parameterization. The spherical ray changes the geometry used by
    planar implementations and supplies complete periodic and polar support.
    """
    height = sample_height_m(latitude, longitude)
    near = np.zeros_like(height, dtype=np.float64)
    far = np.zeros_like(near)
    near_weight, far_weight = 0.0, 0.0
    step = distance = integration_spacing_km
    if not 0 < step <= SEARCH_KM:
        raise ValueError("integration spacing must be positive and within the search support")
    while distance <= SEARCH_KM:
        lat, lon = upwind_coordinates(latitude, longitude, bearing_rad, distance, radius_km)
        angle = np.arctan2(height - sample_height_m(lat, lon), np.sqrt(distance * 1000))
        a = step / distance
        b = step * 1000 / np.log1p(distance * 1000)
        near += a * angle
        far += b * angle
        near_weight += a
        far_weight += b
        step *= STEP_ACCELERATION
        distance += step

    def positive_transform(value: np.ndarray) -> np.ndarray:
        response = 1 + np.log1p(np.abs(value))
        result: np.ndarray = np.where(value >= 0, response, 1 / response)
        return result

    return (
        positive_transform(2 * near / near_weight) ** 0.25
        * positive_transform(far / far_weight) ** 0.125
    )


def refine_large_scale_precipitation(
    baseline: NativePrecipitationField,
    exposure_ratio: np.ndarray,
    rain_direction_weights: np.ndarray,
    *,
    provenance: dict[str, object],
) -> NativePrecipitationField:
    """Apply rain-weighted fine/native exposure ratios and retain all month quotas.

    ``exposure_ratio`` has shape (directions, integration cells); nonnegative
    directional weights have shape (12, directions, native parents). Each
    raining parent-month integrates to one over directions; dry ones may
    contain all zeros. A missing rain-weighted direction leaves that month's
    existing spatial prior unchanged.
    """
    p = baseline.partition
    ratio = np.asarray(exposure_ratio, dtype=np.float64)
    weights = np.asarray(rain_direction_weights, dtype=np.float64)
    if (
        ratio.ndim != 2
        or ratio.shape[1] != len(p.area_km2)
        or weights.shape != (12, ratio.shape[0], len(p.parent_area_km2))
        or not np.isfinite(ratio).all()
        or (ratio <= 0).any()
        or not np.isfinite(weights).all()
        or (weights < 0).any()
    ):
        raise ValueError("exposure ratios and wind weights must cover the complete partition")
    totals = weights.sum(axis=1)
    if not np.allclose(totals[totals > 0], 1, rtol=0, atol=1e-12):
        raise ValueError("raining directional weights must sum to one for each parent-month")
    result = baseline.component_monthly_mm.copy()
    for month in range(12):
        factor = np.sum(weights[month][:, p.parent_index] * ratio, axis=0)
        factor = np.where(totals[month, p.parent_index] > 0, factor, 1.0)
        result[0, month] = p.conservative_depths(
            baseline.native_component_mm[0, month],
            prior_mm=result[0, month] * factor,
        )
    return NativePrecipitationField(
        p,
        baseline.native_component_mm,
        result,
        {
            **baseline.provenance,
            "terrain_refinement": {
                "method_version": METHOD_VERSION,
                "epistemic_class": "empirical terrain exposure with conservative allocation",
                "search_km": SEARCH_KM,
                "integration_spacing_km": p.spacing_km,
                "step_acceleration": STEP_ACCELERATION,
                "directions": ratio.shape[0],
                "terrain_response": "fine/native exposure ratio",
                "wind_weighting": "native large-scale precipitation at each weather state",
                "refined_component": "prl",
                "convective_component": "retained long-term spatial prior and native quota",
                **provenance,
            },
            "weather_response": "rain-weighted terrain-exposure increment on prl",
        },
    )
