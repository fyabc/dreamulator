"""Climate simulation on the spherical CVT mesh.

Phase 3A implementation — Energy Balance Model + geostrophic wind + BFS moisture
transport + orographic rainfall + Köppen classification.

Algorithm reference: ``docs/usage/terrain-pipeline.md`` §8.

Physical constants and composable functions are in
``src/dreamulator/engine/climate_physics.py``.  This module orchestrates them
on the CVT mesh and writes results into `VoronoiCell` fields in-place.
"""

from __future__ import annotations

import math
from collections import deque
from typing import TYPE_CHECKING

import numpy as np

from dreamulator.engine.climate_physics import (
    altitude_lapse_rate,
    coriolis_parameter,
    evaporation_rate,
    hadley_cell_wind,
    itcz_latitude,
    koppen_classify,
    latitude_temperature,
    orographic_precipitation,
    pressure_from_temperature,
    seasonal_temperature,
    surface_temperature,
    terrain_wind_blocking,
    equilibrium_temperature,
)

if TYPE_CHECKING:
    from .models import CVTMesh
    from .pipeline_types import TerrainPipelineConfig

import time as _time

from rich.console import Console as _Console

_console = _Console()

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

# Convergence tolerance for temperature-pressure iteration (unused for now)
_CONV_TOL: float = 0.01

# Minimum wind speed magnitude to be considered "blowing" (m/s)
_MIN_WIND_SPEED: float = 0.1

# Number of advection steps for moisture transport.  Higher values mean
# moisture can travel farther from its source (ocean → deep interior).
#  8: coast only (~200 km inland)
# 16: moderate interior (~400 km at 32K nodes)
_MOISTURE_ADVECTION_STEPS: int = 12


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def simulate_climate(
    mesh: "CVTMesh",
    config: "TerrainPipelineConfig",
) -> None:
    """Run climate simulation on the CVT mesh, filling cell climate fields.

    Modifies *mesh.cells* in-place, setting ``temperature_C``,
    ``precipitation_mm``, and ``koppen_class`` on each `VoronoiCell`.

    The simulation proceeds in four stages:

    1. **Temperature** — equilibrium blackbody → latitude gradient →
       altitude lapse rate → seasonal extremes.
    2. **Wind** — geostrophic approximation + three-cell circulation +
       terrain blocking.
    3. **Precipitation** — ocean evaporation → wind-driven moisture
       transport (multi-pass BFS on the adjacency graph) → orographic
       rainfall → rain shadow.
    4. **Köppen classification** — from annual and seasonal
       temperature + precipitation.

    Args:
        mesh: The CVT mesh with elevation, crust_type, and plate data set.
        config: Pipeline configuration (planet physics, climate params).
    """
    n = mesh.num_cells

    if n == 0:
        return

    # ------------------------------------------------------------------
    # Extract data from CVT mesh
    # ------------------------------------------------------------------
    elevation_m = np.array([c.elevation for c in mesh.cells], dtype=np.float64)
    lat_deg = np.array([c.lat for c in mesh.cells], dtype=np.float64)
    lat_rad = np.radians(lat_deg)
    lon_deg = np.array([c.lon for c in mesh.cells], dtype=np.float64)
    lon_rad = np.radians(lon_deg)

    # Build land/ocean mask from elevation (sea level at 0 m)
    is_land = np.array(elevation_m >= 0.0, dtype=bool)
    is_ocean = ~is_land

    # 3D unit-sphere node positions for vector operations
    nodes_xyz = np.zeros((n, 3), dtype=np.float64)
    for i, c in enumerate(mesh.cells):
        nodes_xyz[i, 0] = c.x
        nodes_xyz[i, 1] = c.y
        nodes_xyz[i, 2] = c.z

    # ------------------------------------------------------------------
    # Stage 1: Temperature
    # ------------------------------------------------------------------
    _t0 = _time.time()
    _console.print("  [dim]1/5  Temperature (EBM + latitude + altitude)[/dim]")
    teq_K = equilibrium_temperature(
        stellar_luminosity_sol=config.stellar_luminosity_sol,
        orbital_distance_au=config.orbital_distance_au,
        albedo=0.306,  # Earth default; could be per-cell later
    )
    t_surf_K = surface_temperature(teq_K, config.greenhouse_warming_K)
    t_surf_C = t_surf_K - 273.15

    # Latitude correction → surface temperature at latitude
    t_mean_C = latitude_temperature(t_surf_C, lat_rad, config.lat_gradient_c)
    # Altitude correction (land only — ocean surface is at 0 m regardless of depth)
    land_mask_arr = np.array(is_land, dtype=bool)
    t_mean_C[land_mask_arr] = altitude_lapse_rate(
        t_mean_C[land_mask_arr],
        elevation_m[land_mask_arr],
        config.lapse_rate_c_km,
    )
    # Ocean surface temperature: damped latitude gradient (maritime moderation)
    # SST ranges ~28°C (tropics) to ~-2°C (polar), much narrower than land
    t_mean_C[~land_mask_arr] = _ocean_surface_temperature(
        t_mean_C[~land_mask_arr], lat_rad[~land_mask_arr],
    )

    # Seasonal extremes
    seasonal = seasonal_temperature(
        t_mean_C,
        lat_rad,
        axial_tilt_deg=config.axial_tilt_deg,
        orbital_period_days=365.25,
    )
    t_jan_C = seasonal["jan"]
    t_jul_C = seasonal["jul"]
    t_cold_C = np.minimum(t_jan_C, t_jul_C)
    t_hot_C = np.maximum(t_jan_C, t_jul_C)

    # ------------------------------------------------------------------
    # Stage 2: Wind
    _console.print(f"  [green]done[/green] [dim]({_time.time()-_t0:.1f}s)[/dim]")
    _t0 = _time.time()
    _console.print("  [dim]2/5  Wind field (geostrophic + Hadley cells)[/dim]")
    # ------------------------------------------------------------------
    # Geostrophic wind from pressure gradient + Coriolis
    pressure_hpa = pressure_from_temperature(t_mean_C, elevation_m)
    grad_p = _compute_graph_gradient(mesh, pressure_hpa, nodes_xyz)
    f_coriolis = coriolis_parameter(lat_rad, config.rotation_period_days)

    wind_geostrophic = _geostrophic_wind(grad_p, f_coriolis, nodes_xyz)

    # Overlay three-cell circulation (Hadley / Ferrel / Polar)
    wind_cell = hadley_cell_wind(lat_rad, nodes_xyz)

    # Combine: 40% geostrophic + 60% cell circulation
    wind = 0.4 * wind_geostrophic + 0.6 * wind_cell

    # Terrain blocking
    wind = terrain_wind_blocking(wind, elevation_m, config.wind_blocking_height_m)

    # ------------------------------------------------------------------
    # Stage 3: Precipitation (multi-pass BFS moisture transport)
    _console.print(f"  [green]done[/green] [dim]({_time.time()-_t0:.1f}s)[/dim]")
    _t0 = _time.time()
    _console.print("  [dim]3/5  Precipitation (BFS moisture transport)[/dim]")
    # ------------------------------------------------------------------
    precipitation_mm = _compute_precipitation_bfs(
        mesh=mesh,
        wind=wind,
        is_land=is_land,
        is_ocean=is_ocean,
        elevation_m=elevation_m,
        temperature_c=t_mean_C,
        nodes_xyz=nodes_xyz,
        config=config,
    )

    # ------------------------------------------------------------------
    # Stage 4: Köppen classification
    _console.print(f"  [green]done[/green] [dim]({_time.time()-_t0:.1f}s)[/dim]")
    _t0 = _time.time()
    _console.print("  [dim]4/5  Koppen classification[/dim]")
    # ------------------------------------------------------------------
    # Estimate driest and wettest month from annual + seasonal patterns
    p_annual = precipitation_mm
    # Rough monthly distribution: sinusoidal with summer maximum
    #  - Wettest month: ~annual / 12 * (1 + seasonality)
    #  - Driest month:  ~annual / 12 * (1 - seasonality)
    seasonality = 0.4  # fraction of annual precip that varies seasonally
    p_dry_mm = p_annual / 12.0 * (1.0 - seasonality)
    p_wet_mm = p_annual / 12.0 * (1.0 + seasonality)

    koppen_codes = koppen_classify(
        t_mean_c=t_mean_C,
        t_cold_c=t_cold_C,
        t_hot_c=t_hot_C,
        p_annual_mm=p_annual,
        p_dry_mm=p_dry_mm,
        p_wet_mm=p_wet_mm,
        is_land=is_land,
    )

    # ------------------------------------------------------------------
    # Write back to cells
    # ------------------------------------------------------------------
    _console.print(f"  [green]done[/green] [dim]({_time.time()-_t0:.1f}s)[/dim]")
    _t0 = _time.time()
    _console.print("  [dim]5/5  Write results to mesh[/dim]")

    for i in range(n):
        mesh.cells[i].temperature_C = float(t_mean_C[i])
        mesh.cells[i].precipitation_mm = float(precipitation_mm[i])
        mesh.cells[i].koppen_class = koppen_codes[i]

    # Summary
    n_land = int(is_land.sum())
    if n_land > 0:
        t_land_min = float(t_mean_C[is_land].min())
        t_land_max = float(t_mean_C[is_land].max())
        p_land_min = float(precipitation_mm[is_land].min())
        p_land_max = float(precipitation_mm[is_land].max())
        _console.print(
            f"  [green]done[/green] [dim]({_time.time()-_t0:.1f}s)[/dim]\n"
            f"  T={t_land_min:.0f}~{t_land_max:.0f} C, "
            f"P={p_land_min:.0f}~{p_land_max:.0f} mm/yr, "
            f"{n_land} land cells, {len(set(koppen_codes)) - 1} Koppen classes"
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _compute_graph_gradient(
    mesh: "CVTMesh",
    scalar: np.ndarray,
    nodes_xyz: np.ndarray,
) -> np.ndarray:
    """Finite-difference gradient of a scalar field on the CVT adjacency graph.

    For each cell i, the gradient is estimated as the weighted average of
    (scalar[j] - scalar[i]) / distance_ij × direction_ij over all neighbours j.

    Args:
        mesh: CVT mesh with adjacency information.
        scalar: Scalar field values, shape (N,).
        nodes_xyz: Unit sphere coordinates, shape (N, 3).

    Returns:
        Gradient vectors tangent to sphere, shape (N, 3).
    """
    n = mesh.num_cells
    grad = np.zeros((n, 3), dtype=np.float64)

    for i in range(n):
        neighbors = mesh.cells[i].neighbors
        if not neighbors:
            continue

        node_i = nodes_xyz[i]
        g = np.zeros(3, dtype=np.float64)
        total_weight = 0.0

        for j in neighbors:
            if j < 0 or j >= n:
                continue
            node_j = nodes_xyz[j]

            # Angular distance (radians)
            dot = np.clip(np.dot(node_i, node_j), -1.0, 1.0)
            dist = math.acos(float(dot))
            if dist < 1e-9:
                continue

            # Direction from i to j (tangent to sphere)
            direction = node_j - node_i
            # Remove radial component
            radial_component = np.dot(direction, node_i)
            direction = direction - radial_component * node_i
            dir_norm = np.linalg.norm(direction)
            if dir_norm < 1e-9:
                continue
            direction /= dir_norm

            # Weight = 1/distance (closer neighbours more influential)
            weight = 1.0 / dist
            diff = scalar[j] - scalar[i]
            g += weight * diff * direction
            total_weight += weight

        if total_weight > 1e-9:
            grad[i] = g / total_weight

    return grad


def _geostrophic_wind(
    grad_p: np.ndarray,
    f_coriolis: np.ndarray,
    nodes_xyz: np.ndarray,
) -> np.ndarray:
    """Geostrophic wind from pressure gradient and Coriolis force.

    v_g = (1 / fρ) × ∇P × k̂

    where k̂ is the local vertical (radial direction on the sphere).
    In NH (f > 0): wind blows with low pressure to the left.
    In SH (f < 0): wind blows with low pressure to the right.

    Args:
        grad_p: Pressure gradient vectors, shape (N, 3).
        f_coriolis: Coriolis parameter, shape (N,).
        nodes_xyz: Unit sphere node positions, shape (N, 3).

    Returns:
        Geostrophic wind vectors (m/s), shape (N, 3).
    """
    n = len(grad_p)
    wind = np.zeros((n, 3), dtype=np.float64)
    rho = 1.225  # air density kg/m³

    for i in range(n):
        if abs(f_coriolis[i]) < 1e-8:
            # Near equator: geostrophic approximation fails.
            # Fall back to direct down-gradient flow (simplified trade winds).
            wind[i] = -grad_p[i] * 0.3
            continue

        # k̂ × ∇P, where k̂ is the local radial direction
        k_hat = nodes_xyz[i]
        # k_hat × grad_p[i] (right-hand rule)
        wind[i] = np.cross(k_hat, grad_p[i]) / (f_coriolis[i] * rho)

    # Clamp to reasonable wind speeds (0–30 m/s at surface)
    for i in range(n):
        speed = np.linalg.norm(wind[i])
        if speed > 30.0:
            wind[i] *= 30.0 / speed

    return wind


def _ocean_surface_temperature(
    t_lat_c: np.ndarray,
    lat_rad: np.ndarray,
) -> np.ndarray:
    """Estimate sea surface temperature (SST) from latitude-band air temperature.

    Oceans have a much narrower temperature range than land (~30 °C range
    vs ~60 °C for land).  Uses a sigmoid transition to sea-ice temperature
    (-1.8 °C) at high latitudes.

    Args:
        t_lat_c: Latitude-only temperature (°C) for ocean cells.
        lat_rad: Latitude in radians.

    Returns:
        SST estimate (°C), shape matches inputs.
    """
    abs_lat = np.abs(lat_rad)
    # Open-ocean SST: 30 °C range from equator (28 °C) to ~60° lat (-2 °C)
    sst_open = 28.0 - 30.0 * np.sin(abs_lat) ** 2

    # Sea-ice transition: sigmoid from open-ocean SST → -1.8 °C
    # Transition centered at ~70° latitude, width ~8°
    ice_weight = _sigmoid(np.degrees(abs_lat), center=70.0, width=8.0)
    sst = sst_open * (1.0 - ice_weight) + (-1.8) * ice_weight

    return np.clip(sst, -2.0, 30.0)


def _sigmoid(x: np.ndarray, center: float, width: float) -> np.ndarray:
    """Smooth sigmoid from 0 (x ≪ center) to 1 (x ≫ center).

    Args:
        x: Input values.
        center: Transition center.
        width: Transition width (σ ≈ width/4).

    Returns:
        Sigmoid values in [0, 1].
    """
    return 1.0 / (1.0 + np.exp(-(x - center) / (width / 4.0)))


def _compute_precipitation_bfs(
    mesh: "CVTMesh",
    wind: np.ndarray,
    is_land: np.ndarray,
    is_ocean: np.ndarray,
    elevation_m: np.ndarray,
    temperature_c: np.ndarray,
    nodes_xyz: np.ndarray,
    config: "TerrainPipelineConfig",
) -> np.ndarray:
    """Multi-pass BFS moisture transport with orographic precipitation.

    Algorithm:
    1. Initialize moisture on ocean cells (evaporation as a function of SST).
    2. For *k* advection passes:
       a. Sort cells by downwind propagation order.
       b. For each cell, find the most-downwind neighbour.
       c. Transport moisture downwind.
       d. If elevation rises → orographic rain.
       e. If elevation falls → rain shadow (minimal precipitation).
    3. Add convective (ITCZ) precipitation in tropical regions.
    4. Rain over ocean also contributes to coastal precipitation.

    Args:
        mesh: CVT mesh.
        wind: Wind vector field, shape (N, 3).
        is_land: Boolean land mask, shape (N,).
        is_ocean: Boolean ocean mask, shape (N,).
        elevation_m: Elevation in metres, shape (N,).
        temperature_c: Temperature in °C, shape (N,).
        nodes_xyz: Unit sphere node positions, shape (N, 3).
        config: Pipeline configuration.

    Returns:
        Annual precipitation in mm, shape (N,).
    """
    n = mesh.num_cells
    precip = np.zeros(n, dtype=np.float64)
    lat_rad = np.radians(np.array([c.lat for c in mesh.cells], dtype=np.float64))

    # Step 1: Base moisture from ocean evaporation
    ocean_moisture = evaporation_rate(temperature_c, is_ocean, config.evaporation_base_mm)
    # Land evapotranspiration: ~40% of ocean rate (soil + vegetation recycling)
    land_moisture = np.where(is_land, evaporation_rate(temperature_c, is_land, config.evaporation_base_mm * 0.40), 0.0)

    # Step 2: Multi-pass advection
    # Each pass: start from ocean + land moisture, then BFS downwind.
    for _pass in range(_MOISTURE_ADVECTION_STEPS):
        # Reset moisture to ocean evaporation + land recycling for this pass
        moisture = ocean_moisture.copy()
        moisture[is_land] += land_moisture[is_land]

        # Find coastal cells for seeding
        coastal = np.zeros(n, dtype=bool)
        for i in range(n):
            if not is_ocean[i]:
                continue
            for j in mesh.cells[i].neighbors:
                if j >= 0 and j < n and is_land[j]:
                    coastal[i] = True
                    break

        # BFS queue: propagate from ocean cells downwind
        queue: deque[int] = deque()
        visited = np.zeros(n, dtype=bool)

        # Seed with all ocean cells sorted by moisture (high → low)
        ocean_indices = np.where(is_ocean)[0]
        ocean_order = ocean_indices[np.argsort(-moisture[ocean_indices])]
        for idx in ocean_order:
            queue.append(idx)

        # Per-pass accumulated moisture for land cells
        pass_moisture = np.zeros(n, dtype=np.float64)
        pass_precip = np.zeros(n, dtype=np.float64)

        while queue:
            node = queue.popleft()
            if visited[node]:
                continue
            visited[node] = True

            # Use pass_moisture for land, moisture for ocean
            cell_moisture = pass_moisture[node] if is_land[node] else moisture[node]
            moisture[node] = cell_moisture  # sync for tracking

            wind_i = wind[node]
            wind_speed = float(np.linalg.norm(wind_i))

            if wind_speed < _MIN_WIND_SPEED or cell_moisture < 1.0:
                continue

            # Find the best downwind neighbour
            best_neighbor = -1
            best_dot = -0.3  # minimum alignment to consider "downwind"

            for j in mesh.cells[node].neighbors:
                if j < 0 or j >= n:
                    continue
                if visited[j]:
                    continue

                # Edge direction from node to neighbour
                edge = nodes_xyz[j] - nodes_xyz[node]
                # Remove radial component
                radial = np.dot(edge, nodes_xyz[node])
                edge = edge - radial * nodes_xyz[node]
                edge_norm = float(np.linalg.norm(edge))
                if edge_norm < 1e-9:
                    continue
                edge /= edge_norm

                # Alignment with wind direction
                dot = float(np.dot(wind_i / max(wind_speed, 1e-9), edge))
                if dot > best_dot:
                    best_dot = dot
                    best_neighbor = j

            if best_neighbor < 0:
                continue

            # Transport moisture downwind
            elev_diff = elevation_m[best_neighbor] - elevation_m[node]

            if elev_diff > 0.0 and is_land[best_neighbor]:
                # Air forced to rise → condensation → rain
                rain, remaining = orographic_precipitation(
                    moisture_in=cell_moisture,
                    elev_diff_m=elev_diff,
                    efficiency=0.20,  # lower than config: avoid first-mountain depletion
                )
                pass_precip[best_neighbor] += rain
                pass_moisture[best_neighbor] = min(
                    pass_moisture[best_neighbor] + remaining, 5000.0,
                )
            elif elev_diff < 0.0 and is_land[best_neighbor]:
                # Descending air → rain shadow (minimal precip, most passes through)
                pass_precip[best_neighbor] += cell_moisture * 0.02
                pass_moisture[best_neighbor] = min(
                    pass_moisture[best_neighbor] + cell_moisture * 0.92, 5000.0,
                )
            elif is_land[best_neighbor]:
                # Flat terrain: slow moisture loss, most passes inland
                pass_precip[best_neighbor] += cell_moisture * 0.05
                pass_moisture[best_neighbor] = min(
                    pass_moisture[best_neighbor] + cell_moisture * 0.90, 5000.0,
                )
            elif is_ocean[best_neighbor]:
                # Ocean → ocean: gradual moisture loss (precip over ocean)
                ocean_rain = cell_moisture * 0.04  # ~4% per hop
                pass_precip[best_neighbor] += ocean_rain
                pass_moisture[best_neighbor] = min(
                    pass_moisture[best_neighbor] + cell_moisture * 0.90, 5000.0,
                )
            else:
                # Ocean → ocean: no net precipitation
                pass

            if best_neighbor not in visited:
                queue.append(best_neighbor)

        # After pass: accumulate precipitation into global totals
        precip += pass_precip
        # Capped for debugging: max plausible annual precip on Earth ~12000 mm
        precip = np.minimum(precip, 12000.0)

    # Step 3: Convective (ITCZ) precipitation — wide tropical rain belt
    lat_deg = np.degrees(lat_rad)

    # ITCZ Gaussian centered on mean position with ~12° width
    itcz_lat = itcz_latitude(
        day_of_year=182.0,
        axial_tilt_deg=config.axial_tilt_deg,
        lag_days=float(config.itcz_lag_days),
    )
    # Wide Gaussian: σ=12° covers 20°N–20°S with significant rain
    # ITCZ: strong convective rainfall band, wider coverage for tropics
    itcz_enhancement = 1200.0 * np.exp(-0.5 * ((lat_deg - itcz_lat) / 15.0) ** 2)
    # Apply to both land and ocean (ITCZ rains over ocean too)
    precip += itcz_enhancement

    # Step 4: Monsoon enhancement — coastal tropical regions get extra rain
    for i in range(n):
        if not is_land[i] or abs(lat_deg[i]) > 35.0:
            continue
        has_ocean_neighbor = any(
            j >= 0 and j < n and is_ocean[j] for j in mesh.cells[i].neighbors
        )
        if has_ocean_neighbor:
            monsoon_factor = 1.5 if abs(lat_deg[i]) < 20.0 else 1.3
            precip[i] *= monsoon_factor

    # Step 5: Local convection (afternoon thunderstorms over warm land)
    # Temperature > 10 °C → thermal convection produces background precipitation.
    # This fills in continental interiors that BFS moisture can't reach.
    conv_trigger = np.maximum(temperature_c - 10.0, 0.0)  # °C above 10 °C
    conv_precip = 30.0 * conv_trigger  # ~30 mm/yr per °C above 10 °C
    precip[is_land] += conv_precip[is_land]

    # Step 6: Subtropical suppression (descending air at ~30°N/S)
    # Applied AFTER convection to ensure deserts stay dry.
    subtropical_suppression = 0.5 + 0.5 * np.cos(np.pi * (np.abs(lat_deg) - 30.0) / 15.0)
    subtropical_mask = (np.abs(lat_deg) > 18.0) & (np.abs(lat_deg) < 40.0)
    precip[subtropical_mask] *= np.clip(subtropical_suppression[subtropical_mask], 0.2, 1.0)

    # Step 7: Tropical precipitation boost (soft, with natural variation)
    # Deep tropics (|lat| < 15°, T > 20°C) get boosted toward a target that
    # varies by latitude (equator wetter, edges drier). This prevents inland
    # tropical areas from being classified as arid (B) when BFS can't reach them,
    # while avoiding an artificial spike at a single value.
    # Real Earth: Congo/Amazon interior 1500-2000mm, Sahel 400-800mm.
    tropical_land = is_land & (np.abs(lat_deg) < 15.0) & (temperature_c > 20.0)
    if tropical_land.any():
        # Target decreases from equator (1200mm) to 15° latitude (700mm)
        tropical_target = 1200.0 - 500.0 * (np.abs(lat_deg[tropical_land]) / 15.0)
        # Soft boost: move 70% of the way toward target (preserves BFS variation)
        current = precip[tropical_land]
        deficit = np.maximum(tropical_target - current, 0.0)
        precip[tropical_land] = current + deficit * 0.7

    # Step 6: Minimum precipitation floor for all land cells
    # Even the driest deserts get ~20 mm/yr. Semi-arid steppes get ~100-200.
    precip = np.maximum(precip, np.where(is_land, 20.0, 0.0))

    return precip
