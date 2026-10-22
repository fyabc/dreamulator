"""Temperature-first kernel for the experimental browser playground.

This module runs inside Pyodide (or host CPython for validation).  It imports
the repository's pure temperature functions from ``engine.climate_physics`` and
``engine.climate_seasonality``; it deliberately does **not** import the climate
simulator, pydantic cell models, the CVT mesh, or any I/O layer.

Scope: a regular lon/lat grid (the playground demo uses 180 × 90), an uploaded
or bundled heightmap, and the engine's annual 1-D EBM + seasonal heat-capacity
model.  Precipitation, winds, ocean circulation and Köppen are out of scope.
"""

from __future__ import annotations

import json
import time

import numpy as np

from dreamulator.engine.climate_physics import (
    altitude_lapse_rate,
    equilibrium_temperature,
    moist_lapse_rate,
    surface_temperature,
)
from dreamulator.engine.climate_seasonality import (
    monthly_insolation,
    monthly_temperature,
    seasonal_heat_capacity,
    solve_1d_ebm_temperature,
)

_SOLAR_CONSTANT_1AU = 1361.0


def _distance_to_coast_km(land: np.ndarray, width: int, height: int) -> np.ndarray:
    """Multi-source BFS from ocean cells over the regular grid.

    The grid is 2° × 2°, so one cell step is ~222 km in latitude and
    ~222·cos(lat) km in longitude; using a flat 222 km is adequate for the
    playground's coastal moderation scale (500 km at Earth's year).
    """
    dist = np.full(width * height, np.inf, dtype=np.float64)
    queue: list[int] = []
    flat_land = land.reshape(-1)
    for idx in range(width * height):
        if not flat_land[idx]:
            dist[idx] = 0.0
            queue.append(idx)
    if not queue:
        return np.zeros(width * height, dtype=np.float64)

    head = 0
    while head < len(queue):
        idx = queue[head]
        head += 1
        y, x = divmod(idx, width)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx = (x + dx) % width
            ny = y + dy
            if ny < 0 or ny >= height:
                continue
            nidx = ny * width + nx
            if not flat_land[nidx] or np.isfinite(dist[nidx]):
                continue
            dist[nidx] = dist[idx] + 1.0
            queue.append(nidx)
    dist[~np.isfinite(dist)] = 0.0
    return dist * 222.0


def compute_temperature(
    elevation_json: str,
    params_json: str,
) -> str:
    """Compute annual and monthly temperature on a regular lon/lat grid.

    ``elevation_json`` is a row-major (north → south) list of metres;
    ``params_json`` carries the planet parameters from the UI.  Returns a JSON
    object with ``annual`` (°C), ``monthly`` (°C, row-major month-major), and
    timing/statistics.  JSON keeps the Pyodide boundary simple and allocation-
    free enough for a 16k-cell demo.
    """
    t0 = time.perf_counter()
    params = json.loads(params_json)
    elevation = np.asarray(json.loads(elevation_json), dtype=np.float64)
    width = int(params.get("width", 180))
    height = int(params.get("height", 90))
    if elevation.size != width * height:
        raise ValueError(f"elevation size {elevation.size} != {width}x{height}")

    rows = np.arange(height, dtype=np.float64)
    lat_deg = 90.0 - (rows + 0.5) * (180.0 / height)
    lat = np.repeat(lat_deg, width)
    lat_rad = np.radians(lat)

    sea_level = float(params.get("sea_level_m", 0.0))
    land = elevation > sea_level
    ocean = ~land

    luminosity = float(params.get("stellar_luminosity_sol", 1.0))
    distance_au = float(params.get("orbital_distance_au", 1.0))
    albedo = float(params.get("albedo", 0.3))
    greenhouse_k = float(params.get("greenhouse_warming_K", 33.0))
    tilt = float(params.get("axial_tilt_deg", 23.44))
    year_days = float(params.get("orbital_period_days", 365.25))
    rotation_days = float(params.get("rotation_period_days", 1.0))
    # Same slow-rotator meridional-transport scaling as climate_simulator:
    # D ∝ Ω^-0.3 (Kaspi & Showman 2015), with the engine's 0.35 W/m²/K base.
    diffusion = float(params.get("ebm_diffusion_wm2k", 0.35)) * max(rotation_days, 1e-6) ** 0.3

    solar_constant = _SOLAR_CONSTANT_1AU * luminosity / max(distance_au * distance_au, 1e-12)
    t_global_mean_c = (
        surface_temperature(
            equilibrium_temperature(luminosity, distance_au, albedo),
            greenhouse_k,
        )
        - 273.15
    )

    t_mean = solve_1d_ebm_temperature(
        lat_rad,
        t_global_mean_c,
        albedo=albedo,
        obliquity_deg=tilt,
        solar_constant=solar_constant,
        orbital_period_days=year_days,
        diffusion_wm2k=diffusion,
    )

    if land.any():
        if bool(params.get("variable_lapse_rate", True)):
            lapse = moist_lapse_rate(t_mean[land])
        else:
            lapse = 6.5
        t_mean[land] = altitude_lapse_rate(t_mean[land], elevation[land], lapse)

    coast_km = _distance_to_coast_km(land, width, height)
    heat_capacity = seasonal_heat_capacity(
        land,
        ocean,
        coast_km,
        orbital_period_days=year_days,
    )

    q_monthly = monthly_insolation(
        lat_rad,
        tilt,
        solar_constant,
        year_days,
        0.0,
        0.0,
    )
    t_monthly = monthly_temperature(
        q_monthly,
        t_mean,
        heat_capacity,
        orbital_period_days=year_days,
        albedo=albedo,
        diffusion_wm2k=diffusion,
    )

    elapsed = time.perf_counter() - t0
    annual = np.asarray(t_mean, dtype=np.float64).reshape(height, width)
    monthly = np.asarray(t_monthly, dtype=np.float64).reshape(height, width, 12)
    # The grid is equirectangular: weight by cos(lat) for an area mean.
    area_weight = np.cos(lat_rad)
    annual_mean_c = float(np.sum(t_mean * area_weight) / np.sum(area_weight))
    return json.dumps(
        {
            "annual": [round(float(v), 3) for v in annual.reshape(-1)],
            "monthly": [
                [round(float(v), 3) for v in monthly[:, :, m].reshape(-1)]
                for m in range(12)
            ],
            "latDeg": [round(float(v), 4) for v in lat_deg],
            "globalMeanC": round(float(t_global_mean_c), 3),
            "annualMeanC": round(annual_mean_c, 3),
            "minC": round(float(np.min(annual)), 3),
            "maxC": round(float(np.max(annual)), 3),
            "elapsedS": round(elapsed, 3),
        },
        ensure_ascii=False,
    )
