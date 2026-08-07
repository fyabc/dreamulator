"""Climate simulation on the spherical CVT mesh.

Phase 3A implementation — Energy Balance Model + geostrophic wind + BFS moisture
transport + orographic rainfall + Köppen classification.

Algorithm reference: ``docs/design/terrain-pipeline.md`` §8.

Physical constants and composable functions are in
``src/dreamulator/engine/climate_physics.py``.  This module orchestrates them
on the CVT mesh and writes results into `VoronoiCell` fields in-place.
"""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

import numpy as np

from dreamulator.engine.climate_physics import (
    altitude_lapse_rate,
    coriolis_parameter,
    equilibrium_temperature,
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
    mesh: CVTMesh,
    config: TerrainPipelineConfig,
) -> dict[str, float]:
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
        return {}

    phase_timings: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Extract data from CVT mesh
    # ------------------------------------------------------------------
    elevation_m = np.array([c.elevation for c in mesh.cells], dtype=np.float64)
    lat_deg = np.array([c.lat for c in mesh.cells], dtype=np.float64)
    lat_rad = np.radians(lat_deg)

    # Build land/ocean mask from elevation (sea surface at the offset datum)
    is_land = np.array(elevation_m >= config.sea_level_offset_m, dtype=bool)
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
        albedo=config.albedo,
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
    # anchored to the planet's global-mean surface temperature (Earth profile
    # at Earth forcing; shifts 1:1 with stellar forcing / greenhouse changes)
    t_mean_C[~land_mask_arr] = _ocean_surface_temperature(
        lat_rad[~land_mask_arr],
        t_surf_C,
    )

    # Sub-planet hemisphere warming (e.g. gaia-m: Aegis IR + reflected light)
    if config.sub_planet_warming_c > 0:
        lon_rad = np.radians(np.array([c.lon for c in mesh.cells], dtype=np.float64))
        # Cosine falloff from sub-planet point, zero on anti-planet side
        cos_lon = np.cos(lon_rad - np.radians(config.sub_planet_longitude_deg))
        warming = config.sub_planet_warming_c * np.maximum(0, cos_lon)
        t_mean_C += warming

    # Seasonal extremes
    seasonal = seasonal_temperature(
        t_mean_C,
        lat_rad,
        axial_tilt_deg=config.axial_tilt_deg,
        orbital_period_days=config.orbital_period_days,
    )
    t_jan_C = seasonal["jan"]
    t_jul_C = seasonal["jul"]
    t_cold_C = np.minimum(t_jan_C, t_jul_C)
    t_hot_C = np.maximum(t_jan_C, t_jul_C)

    # ------------------------------------------------------------------
    # Stage 2: Wind
    phase_timings["temperature"] = _time.time() - _t0
    _console.print(f"  [green]done[/green] [dim]({phase_timings['temperature']:.1f}s)[/dim]")
    _t0 = _time.time()
    _console.print("  [dim]2/5  Wind field (geostrophic + Hadley cells)[/dim]")
    # ------------------------------------------------------------------
    # Geostrophic wind from pressure gradient + Coriolis
    pressure_hpa = pressure_from_temperature(
        t_mean_C, elevation_m, config.gravity_m_s2, config.surface_pressure_hpa
    )
    grad_p = _compute_graph_gradient(mesh, pressure_hpa, nodes_xyz)
    f_coriolis = coriolis_parameter(lat_rad, config.rotation_period_days)

    wind_geostrophic = _geostrophic_wind(grad_p, f_coriolis, nodes_xyz)

    # Overlay three-cell circulation (Hadley / Ferrel / Polar); cell
    # boundaries are planet parameters (3A.3a — slow rotators get an
    # expanded Hadley cell).
    wind_cell = hadley_cell_wind(
        lat_rad,
        nodes_xyz,
        hadley_extent_deg=config.hadley_extent_deg,
        polar_cell_start_deg=config.polar_cell_start_deg,
        rotation_period_days=config.rotation_period_days,
    )

    # Combine: 40% geostrophic + 60% cell circulation
    wind = 0.4 * wind_geostrophic + 0.6 * wind_cell

    # Terrain blocking
    wind = terrain_wind_blocking(wind, elevation_m, config.wind_blocking_height_m)

    # ------------------------------------------------------------------
    # Stage 2.5: Ocean currents (Stommel gyres + SST correction)
    phase_timings["wind"] = _time.time() - _t0
    _console.print(f"  [green]done[/green] [dim]({phase_timings['wind']:.1f}s)[/dim]")
    _t0 = _time.time()
    _console.print("  [dim]3/6  Ocean currents (Stommel gyres + SST)[/dim]")
    # ------------------------------------------------------------------
    if config.ocean_currents_enabled:
        from dreamulator.map.ocean_circulation import (
            DEFAULT_BOTTOM_FRICTION,
            DEFAULT_H_ML,
            DEFAULT_COASTAL_INFLUENCE_KM,
            DEFAULT_SST_PASSES,
            DEFAULT_SST_RELAXATION,
            advect_sst_relaxation,
            compute_curl_z,
            compute_upwelling_index,
            compute_wind_stress,
            detect_ocean_basins,
            east_north_basis,
            solve_ocean_gyre,
            _build_directed_edge_table,
        )

        east, north = east_north_basis(nodes_xyz)
        tau = compute_wind_stress(wind, c_d=config.ocean_drag_coefficient)
        src, dst = _build_directed_edge_table(mesh.cells)
        curl_z = compute_curl_z(tau, nodes_xyz, src, dst, east, north)

        # Planetary β = 2Ω cos(φ) / a
        omega = 2.0 * np.pi / (config.rotation_period_days * 86400.0)
        radius_m = config.radius_km * 1000.0
        beta = 2.0 * omega * np.cos(lat_rad) / radius_m

        # Detect ocean basins
        basin_id, basins = detect_ocean_basins(mesh.cells, config.sea_level_offset_m)

        if basins:
            # Per-basin Stommel solve
            areas_km2 = np.array([c.area_km2 for c in mesh.cells], dtype=np.float64)
            all_psi: dict[int, np.ndarray] = {}
            all_velocity: dict[int, np.ndarray] = {}

            h_ml = config.ocean_mixed_layer_depth_m
            R = config.ocean_bottom_friction_s

            for b_idx, b_cells in enumerate(basins):
                n_b = len(b_cells)
                _console.print(
                    f"    [dim]Basin {b_idx + 1}/{len(basins)} ({n_b} cells)[/dim]"
                )
                psi, vel = solve_ocean_gyre(
                    b_cells,
                    mesh.cells,
                    nodes_xyz,
                    areas_km2,
                    curl_z,
                    beta,
                    bottom_friction=R,
                    h_ml=h_ml,
                    east=east,
                    sea_level_m=config.sea_level_offset_m,
                )
                all_psi[b_idx] = psi
                all_velocity[b_idx] = vel

                # SST correction (per-basin to keep memory bounded)
                sst_corrected, sst_anom = advect_sst_relaxation(
                    t_mean_C,
                    vel,
                    b_cells,
                    mesh.cells,
                    nodes_xyz,
                    n_passes=config.ocean_sst_advection_passes,
                    relaxation_rate=config.ocean_sst_relaxation_rate,
                    coastal_influence_km=config.ocean_coastal_influence_km,
                )
                t_mean_C = sst_corrected  # feeds into stage 3 (BFS evaporation) + stage 4 (Köppen)
                # Write per-cell ocean fields
                for li, gi in enumerate(b_cells):
                    c = mesh.cells[gi]
                    c.ocean_current_east_m_s = float(
                        np.dot(vel[li], east[gi])
                    )
                    c.ocean_current_north_m_s = float(
                        np.dot(vel[li], north[gi])
                    )
                    c.sst_anomaly_c = float(sst_anom[gi])

            # Upwelling diagnostic (optional, for future use)
            if config.ocean_upwelling_enabled:
                _upw = compute_upwelling_index(
                    wind, mesh.cells, nodes_xyz, east, north, lat_rad
                )
        else:
            _console.print("    [dim]No ocean basins detected[/dim]")
    else:
        _console.print("    [dim]Skipped (ocean_currents_enabled=false)[/dim]")

    # ------------------------------------------------------------------
    # Stage 3: Precipitation (multi-pass BFS moisture transport)
    phase_timings["ocean"] = _time.time() - _t0
    _console.print(f"  [green]done[/green] [dim]({phase_timings['ocean']:.1f}s)[/dim]")
    _t0 = _time.time()
    _console.print("  [dim]4/6  Precipitation (BFS moisture transport)[/dim]")
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
    phase_timings["precipitation"] = _time.time() - _t0
    _console.print(f"  [green]done[/green] [dim]({phase_timings['precipitation']:.1f}s)[/dim]")
    _t0 = _time.time()
    _console.print("  [dim]5/6  Koppen classification[/dim]")
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
    phase_timings["koppen"] = _time.time() - _t0
    _console.print(f"  [green]done[/green] [dim]({phase_timings['koppen']:.1f}s)[/dim]")
    _t0 = _time.time()
    _console.print("  [dim]6/6  Write results to mesh[/dim]")

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
        phase_timings["writeback"] = _time.time() - _t0
        _console.print(
            f"  [green]done[/green] [dim]({phase_timings['writeback']:.1f}s)[/dim]\n"
            f"  T={t_land_min:.0f}~{t_land_max:.0f} C, "
            f"P={p_land_min:.0f}~{p_land_max:.0f} mm/yr, "
            f"{n_land} land cells, {len(set(koppen_codes)) - 1} Koppen classes"
        )

    return phase_timings


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _compute_graph_gradient(
    mesh: CVTMesh,
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

    # Stage 1.3: vectorized over a flat directed-edge table (was per-cell,
    # per-neighbour scalar numpy ops).
    _src: list[int] = []
    _dst: list[int] = []
    for _i, _cell in enumerate(mesh.cells):
        for _j in _cell.neighbors:
            if 0 <= _j < n:
                _src.append(_i)
                _dst.append(_j)
    src = np.asarray(_src, dtype=np.int64)
    dst = np.asarray(_dst, dtype=np.int64)

    node_i = nodes_xyz[src]
    node_j = nodes_xyz[dst]

    # Angular distance (radians)
    dot = np.clip(np.einsum("ij,ij->i", node_i, node_j), -1.0, 1.0)
    dist = np.arccos(dot)

    # Direction from i to j (tangent to sphere)
    direction = node_j - node_i
    radial = np.einsum("ij,ij->i", direction, node_i)
    direction = direction - radial[:, None] * node_i
    dir_norm = np.linalg.norm(direction, axis=1)
    valid = (dist >= 1e-9) & (dir_norm >= 1e-9)

    # Weight = 1/distance (closer neighbours more influential); invalid
    # edges contribute zero weight, so their direction need not be unit.
    weight = np.zeros_like(dist)
    weight[valid] = 1.0 / dist[valid]

    diff = scalar[dst] - scalar[src]
    contrib = (weight * diff)[:, None] * direction

    grad = np.zeros((n, 3), dtype=np.float64)
    np.add.at(grad, src, contrib)
    weight_sum = np.zeros(n, dtype=np.float64)
    np.add.at(weight_sum, src, weight)
    mask = weight_sum > 1e-9
    grad[mask] /= weight_sum[mask, None]

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
    rho = 1.225  # air density kg/m³

    # Stage 1.3: fully vectorized (was two per-cell loops).
    weak = np.abs(f_coriolis) < 1e-8
    wind = np.cross(nodes_xyz, grad_p) / (f_coriolis[:, None] * rho)
    # Near equator the geostrophic approximation fails — fall back to
    # direct down-gradient flow (simplified trade winds).
    wind[weak] = -grad_p[weak] * 0.3

    # Clamp to reasonable wind speeds (0–30 m/s at surface)
    speed = np.linalg.norm(wind, axis=1)
    over = speed > 30.0
    wind[over] *= (30.0 / speed[over])[:, None]

    return wind


def _ocean_surface_temperature(
    lat_rad: np.ndarray,
    t_surf_c: float,
) -> np.ndarray:
    """Estimate sea surface temperature (SST) from latitude.

    Oceans have a much narrower temperature range than land (~30 °C range
    vs ~60 °C for land).  The latitude profile is Earth-calibrated
    (28 °C equator → −2 °C at ~60°) and shifted by
    ``t_surf_c − t_surf_earth_ref`` so that other stellar forcings or
    greenhouse levels move SST one-for-one with the global-mean surface
    temperature while keeping the maritime-moderation shape.
    ``t_surf_earth_ref`` is the model's own Earth value (1 L☉, 1 AU,
    albedo 0.306, +33 K greenhouse), so Earth is reproduced exactly.
    Uses a sigmoid transition to sea-ice temperature (-1.8 °C) at high
    latitudes.

    Args:
        lat_rad: Latitude in radians.
        t_surf_c: Global-mean surface temperature (°C), i.e. equilibrium
            temperature + greenhouse warming.

    Returns:
        SST estimate (°C), shape matches inputs.
    """
    abs_lat = np.abs(lat_rad)
    t_surf_earth_ref = float(
        surface_temperature(equilibrium_temperature(1.0, 1.0, 0.306), 33.0) - 273.15
    )
    # Open-ocean SST: 30 °C range from equator (28 °C) to ~60° lat (-2 °C),
    # shifted by the planet's surface temperature relative to Earth's
    sst_open = 28.0 + (t_surf_c - t_surf_earth_ref) - 30.0 * np.sin(abs_lat) ** 2

    # Sea-ice transition: sigmoid from open-ocean SST → -1.8 °C
    # Transition centered at ~70° latitude, width ~8°
    ice_weight = _sigmoid(np.degrees(abs_lat), center=70.0, width=8.0)
    sst = sst_open * (1.0 - ice_weight) + (-1.8) * ice_weight

    return np.asarray(np.clip(sst, -2.0, 30.0))


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
    mesh: CVTMesh,
    wind: np.ndarray,
    is_land: np.ndarray,
    is_ocean: np.ndarray,
    elevation_m: np.ndarray,
    temperature_c: np.ndarray,
    nodes_xyz: np.ndarray,
    config: TerrainPipelineConfig,
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
    land_moisture = np.where(
        is_land, evaporation_rate(temperature_c, is_land, config.evaporation_base_mm * 0.40), 0.0
    )

    # Stage 1.3 precompute: the wind field is invariant across passes, so
    # build the directed-edge table and per-cell downwind candidate lists
    # ONCE. Each cell's candidates are its valid neighbours sorted by wind
    # alignment (descending, dot > −0.3 kept) — this exactly reproduces the
    # original "best unvisited downwind neighbour" selection: the original
    # picks the highest-alignment unvisited neighbour, i.e. the first
    # unvisited entry in this sorted list.
    wind_speed_all = np.linalg.norm(wind, axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        wind_unit = wind / np.maximum(wind_speed_all, 1e-9)[:, None]

    _src: list[int] = []
    _dst: list[int] = []
    for _i, _cell in enumerate(mesh.cells):
        for _j in _cell.neighbors:
            if 0 <= _j < n:
                _src.append(_i)
                _dst.append(_j)
    src = np.asarray(_src, dtype=np.int64)
    dst = np.asarray(_dst, dtype=np.int64)
    edge_vec = nodes_xyz[dst] - nodes_xyz[src]
    radial = np.einsum("ij,ij->i", edge_vec, nodes_xyz[src])
    edge_vec = edge_vec - radial[:, None] * nodes_xyz[src]
    edge_norm = np.linalg.norm(edge_vec, axis=1)
    valid_edge = edge_norm >= 1e-9
    edge_dir = np.zeros_like(edge_vec)
    edge_dir[valid_edge] = edge_vec[valid_edge] / edge_norm[valid_edge, None]
    align = np.where(valid_edge, np.einsum("ij,ij->i", edge_dir, wind_unit[src]), -1.0)

    # CSR layout: per-cell candidates sorted by alignment (descending).
    keep = align > -0.3
    src_k = src[keep]
    align_k = align[keep]
    order = np.lexsort((-align_k, src_k))  # src asc, align desc (stable ties)
    cand_dst = dst[keep][order]
    counts = np.bincount(src_k[order], minlength=n)
    offsets = np.zeros(n + 1, dtype=np.int64)
    np.cumsum(counts, out=offsets[1:])

    # Step 2: Multi-pass advection
    # Each pass: start from ocean + land moisture, then BFS downwind.
    for _pass in range(_MOISTURE_ADVECTION_STEPS):
        # Reset moisture to ocean evaporation + land recycling for this pass
        moisture = ocean_moisture.copy()
        moisture[is_land] += land_moisture[is_land]

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

            if wind_speed_all[node] < _MIN_WIND_SPEED or cell_moisture < 1.0:
                continue

            # Best downwind neighbour = first unvisited candidate (the list
            # is pre-sorted by wind alignment; see precompute above).
            best_neighbor = -1
            for k in range(offsets[node], offsets[node + 1]):
                j = cand_dst[k]
                if not visited[j]:
                    best_neighbor = j
                    break

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
                    pass_moisture[best_neighbor] + remaining,
                    5000.0,
                )
            elif elev_diff < 0.0 and is_land[best_neighbor]:
                # Descending air → rain shadow (minimal precip, most passes through)
                pass_precip[best_neighbor] += cell_moisture * 0.02
                pass_moisture[best_neighbor] = min(
                    pass_moisture[best_neighbor] + cell_moisture * 0.92,
                    5000.0,
                )
            elif is_land[best_neighbor]:
                # Flat terrain: slow moisture loss, most passes inland
                pass_precip[best_neighbor] += cell_moisture * 0.05
                pass_moisture[best_neighbor] = min(
                    pass_moisture[best_neighbor] + cell_moisture * 0.90,
                    5000.0,
                )
            elif is_ocean[best_neighbor]:
                # Ocean → ocean: gradual moisture loss (precip over ocean)
                ocean_rain = cell_moisture * 0.04  # ~4% per hop
                pass_precip[best_neighbor] += ocean_rain
                pass_moisture[best_neighbor] = min(
                    pass_moisture[best_neighbor] + cell_moisture * 0.90,
                    5000.0,
                )
            else:
                # Ocean → ocean: no net precipitation
                pass

            # NB: direct index check — `x not in ndarray` is an O(n) scan
            if not visited[best_neighbor]:
                queue.append(best_neighbor)

        # After pass: accumulate precipitation into global totals
        precip += pass_precip
        # Capped for debugging: max plausible annual precip on Earth ~12000 mm
        precip = np.minimum(precip, 12000.0)

    # Step 3: Convective (ITCZ) precipitation — wide tropical rain belt
    lat_deg = np.degrees(lat_rad)

    # ITCZ Gaussian centered on mean position with ~12° width
    itcz_lat = itcz_latitude(
        day_of_year=config.orbital_period_days / 2.0,  # northern summer solstice
        axial_tilt_deg=config.axial_tilt_deg,
        lag_days=float(config.itcz_lag_days),
        orbital_period_days=config.orbital_period_days,
    )
    # Wide Gaussian: σ=12° covers 20°N–20°S with significant rain
    # ITCZ: strong convective rainfall band, wider coverage for tropics
    itcz_enhancement = 1200.0 * np.exp(-0.5 * ((lat_deg - itcz_lat) / 15.0) ** 2)
    # Apply to both land and ocean (ITCZ rains over ocean too)
    precip += itcz_enhancement

    # Step 4: Monsoon enhancement — coastal tropical regions get extra rain
    # (vectorized over the edge table, Stage 1.3)
    abs_lat = np.abs(lat_deg)
    tropical_land = is_land & (abs_lat <= 35.0)
    coastal_edges = tropical_land[src] & is_ocean[dst]
    has_ocean_neighbor = np.zeros(n, dtype=bool)
    has_ocean_neighbor[src[coastal_edges]] = True
    monsoon_cells = tropical_land & has_ocean_neighbor
    precip[monsoon_cells & (abs_lat < 20.0)] *= 1.5
    precip[monsoon_cells & (abs_lat >= 20.0)] *= 1.3

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
