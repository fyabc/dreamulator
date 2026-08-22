"""Climate simulation on the spherical CVT mesh.

Phase 3A implementation — Energy Balance Model + geostrophic wind + graph-diffusion
moisture transport + orographic rainfall + Köppen classification.

Algorithm reference: ``docs/design/climate-engine.md`` §2.2a (moisture transport).

Physical constants and composable functions are in
``src/dreamulator/engine/climate_physics.py``.  This module orchestrates them
on the CVT mesh and writes results into `VoronoiCell` fields in-place.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from scipy import sparse
from scipy.sparse.linalg import gmres

from dreamulator.engine.climate_physics import (
    SOLAR_CONSTANT,
    altitude_lapse_rate,
    coriolis_parameter,
    diffuse_heat_graph,
    equilibrium_temperature,
    evaporation_rate,
    hadley_cell_wind,
    ice_albedo_feedback,
    koppen_classify,
    lat_gradient_from_omega,
    latitude_temperature,
    moist_lapse_rate,
    pressure_from_temperature,
    spectral_ice_albedo,
    surface_temperature,
    terrain_wind_blocking,
)
from dreamulator.engine.climate_seasonality import (
    compute_seasonal_climate,
    seasonal_heat_capacity,
    seasonal_precip_extremes,
    solve_1d_ebm_temperature,
    solve_held_hou_temperature,
    warm_cold_half_precip,
)

if TYPE_CHECKING:
    from .models import CVTMesh, VoronoiCell
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
#
# The optimal value scales with wind speed ∝ Ω^(−1/3) (Hill et al. 2019):
# slower rotators have stronger winds → moisture travels farther → more
# steps are needed to cover the same angular distance.  Earth reference:
# 12 steps at Ω=Ω⊕.  For gaia-m (Ω=0.31 Ω⊕): 12 × 1.48 ≈ 18 steps.
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

    # Solar constant scaled to the planet's distance and stellar luminosity.
    # Hoisted here so the 1D EBM and the seasonal model share a single value.
    solar_const = SOLAR_CONSTANT * config.stellar_luminosity_sol / config.orbital_distance_au**2

    land_mask_arr = np.array(is_land, dtype=bool)

    if config.ebm_1d:
        # ── 1D EBM (North 1975 / climlab.EBM) — formal steady-state solve ──
        # 0 = D d/dx[(1−x²)dT/dx] + Q(x)(1−α) − (A + B·T),  x = sin(φ), replaces
        # the sin² latitude profile + 3-pass graph diffusion.  The ocean is
        # overwritten by ``_ocean_surface_temperature`` below, so this solve
        # gives the LAND temperature.  Two regimes (energy_balance.md §3):
        if config.hadley_extent_deg >= 90.0:
            # Single-Hadley-cell regime (slow rotators, P ≳ 3 d): heat transport
            # is by direct overturning (MOC), not eddies — a different mechanism
            # than the diffusive EBM.  Held & Hou (1980) quartic profile (flat
            # subtropics + polar cap), ΔT ∝ Ω².  The overturning homogenises
            # land and ocean, so there is no separate land-only D.
            t_mean_C = solve_held_hou_temperature(
                lat_rad,
                t_surf_C,
                radius_km=config.radius_km,
                gravity_m_s2=config.gravity_m_s2,
                rotation_period_days=config.rotation_period_days,
            )
        else:
            # Three-cell regime (Earth-like): eddy-driven transport, D ∝ Ω^0.3
            # (Kaspi & Showman 2015).  Land uses the atmospheric fraction
            # D_land < D_total — warmer subtropics, colder poles (continentality).
            d_scaled = config.ebm_diffusion_land_wm2k * (config.rotation_period_days**0.3)
            t_mean_C = solve_1d_ebm_temperature(
                lat_rad,
                t_surf_C,
                albedo=config.albedo,
                obliquity_deg=config.axial_tilt_deg,
                solar_constant=solar_const,
                orbital_period_days=config.orbital_period_days,
                eccentricity=config.eccentricity,
                perihelion_day=config.perihelion_day,
                olr_b_wm2k=config.ebm_olr_b_wm2k,
                diffusion_wm2k=d_scaled,
            )
    else:
        # ── 3A.3a: auto-compute latitudinal gradient from rotation rate? ──
        if config.auto_lat_gradient:
            lat_grad = lat_gradient_from_omega(
                config.rotation_period_days,
                earth_gradient_c=config.lat_gradient_earth_c,
            )
        else:
            lat_grad = config.lat_gradient_c

        # Latitude correction → surface temperature at latitude
        t_mean_C = latitude_temperature(t_surf_C, lat_rad, lat_grad)

        # ── 3A.3a: diffusive meridional heat transport ──
        if config.diffusive_heat_transport:
            # Build per-cell neighbour index lists from the CVT graph
            nbr_indices: list[list[int]] = [[] for _ in range(n)]
            for i, c in enumerate(mesh.cells):
                nbr_indices[i] = [mesh.cells[j].id for j in c.neighbors]
            # Map neighbour IDs → array indices, then filter to valid
            id_to_idx = {c.id: i for i, c in enumerate(mesh.cells)}
            nbrs: list[list[int]] = []
            for _i, c in enumerate(mesh.cells):
                idx_list = [id_to_idx[nid] for nid in c.neighbors if nid in id_to_idx]
                nbrs.append(idx_list)

            # Diffusion strength from total meridional heat transport
            # (Kaspi & Showman 2015 Fig.5 — mass streamfunction ∝ Ω^(-0.5)).
            omega_ratio = 1.0 / config.rotation_period_days
            strength = 0.15 * omega_ratio**0.3
            passes = 3

            t_mean_C = diffuse_heat_graph(
                t_mean_C,
                nbrs,
                diffusion_passes=passes,
                diffusion_strength=strength,
                land_mask=land_mask_arr,
            )

    # ── 3A.3: ice-albedo feedback ──
    if config.ice_albedo_feedback:
        t_mean_C = ice_albedo_feedback(
            t_mean_C,
            max_cooling_c=config.ice_albedo_max_cooling_c,
            ice_threshold_c=config.ice_albedo_threshold_c,
        )

    # Altitude correction (land only — ocean surface is at 0 m regardless of depth)
    lapse: float | np.ndarray = config.lapse_rate_c_km
    if config.variable_lapse_rate:
        lapse = moist_lapse_rate(t_mean_C[land_mask_arr])
    t_mean_C[land_mask_arr] = altitude_lapse_rate(
        t_mean_C[land_mask_arr],
        elevation_m[land_mask_arr],
        lapse,
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

    # Seasonality (3A.2): seasonal energy-balance model — insolation-driven
    # monthly temperature with physical surface heat capacity (land/ocean/coastal).
    # Distance-to-coast is computed once here and reused by the precipitation
    # stage's inland-aridity gradient (Step 6.5).
    distance_to_coast_km = _graph_distance_to_coast(
        mesh.cells, n, is_land, radius_km=config.radius_km
    )
    heat_capacity = seasonal_heat_capacity(
        is_land,
        is_ocean,
        distance_to_coast_km,
        land_capacity=config.seasonal_land_heat_capacity,
        ocean_capacity=config.seasonal_ocean_heat_capacity,
        coastal_scale_km=config.seasonal_coastal_scale_km,
    )
    seasonal = compute_seasonal_climate(
        lat_rad,
        t_mean_C,
        is_land,
        heat_capacity,
        obliquity_deg=config.axial_tilt_deg,
        solar_constant=solar_const,
        orbital_period_days=config.orbital_period_days,
        eccentricity=config.eccentricity,
        perihelion_day=config.perihelion_day,
        olr_b_wm2k=config.ebm_olr_b_wm2k,
        diffusion_wm2k=config.ebm_diffusion_wm2k,
        albedo=config.albedo,
        ice_albedo=spectral_ice_albedo(
            config.stellar_temperature_k,
            ice_albedo_visible=config.ice_albedo_surface,
        ),
        ice_threshold_c=config.seasonal_ice_threshold_c,
        ice_albedo_feedback=config.seasonal_ice_albedo,
    )
    t_cold_C = seasonal["T_cold"]
    t_hot_C = seasonal["T_hot"]
    t_monthly_C = seasonal["T_monthly"]
    p_factor = seasonal["P_factor"]
    itcz_lat_monthly = seasonal["itcz_lat"]

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

    # Write wind to cells for frontend visualisation
    from dreamulator.map.ocean_circulation import (
        decompose_tangent as _dec_wind,
    )
    from dreamulator.map.ocean_circulation import (
        east_north_basis as _enb_wind,
    )

    _east_w, _north_w = _enb_wind(nodes_xyz)
    _we, _wn = _dec_wind(wind, _east_w, _north_w)
    _we = -_we  # FIXME: wind_east sign convention; remove after verification
    for i, c in enumerate(mesh.cells):
        c.wind_east_m_s = float(_we[i])
        c.wind_north_m_s = float(_wn[i])

    # ------------------------------------------------------------------
    # Stage 2.5: Ocean currents (Stommel gyres + SST correction)
    phase_timings["wind"] = _time.time() - _t0
    _console.print(f"  [green]done[/green] [dim]({phase_timings['wind']:.1f}s)[/dim]")
    _t0 = _time.time()
    _console.print("  [dim]3/6  Ocean currents (Stommel gyres + SST)[/dim]")
    # ------------------------------------------------------------------
    if config.ocean_currents_enabled:
        from dreamulator.map.ocean_circulation import (
            _build_directed_edge_table,
            advect_sst_semilagrangian,
            advect_temperature_anomaly,
            apply_upwelling_sst_correction,
            compute_curl_z,
            compute_upwelling_index,
            compute_wind_stress,
            detect_ocean_basins,
            east_north_basis,
            solve_ocean_gyre,
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

            # Tiny basins (< 20 cells) contribute no visible surface currents;
            # skipping them saves GMRES setup cost (sparse matrix assembly etc.).
            _MIN_BASIN_CELLS = 20
            for b_idx, b_cells in enumerate(basins):
                n_b = len(b_cells)
                if n_b < _MIN_BASIN_CELLS:
                    _console.print(
                        f"    [dim]Basin {b_idx + 1}/{len(basins)} ({n_b} cells — skipped)[/dim]"
                    )
                    continue
                _console.print(f"    [dim]Basin {b_idx + 1}/{len(basins)} ({n_b} cells)[/dim]")
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
                sst_corrected, sst_anom = advect_sst_semilagrangian(
                    t_mean_C,
                    vel,
                    b_cells,
                    mesh.cells,
                    nodes_xyz,
                    radius_m=radius_m,
                    tau_days=config.ocean_sst_advection_days,
                    coastal_influence_km=config.ocean_coastal_influence_km,
                )
                t_mean_C = sst_corrected  # feeds into stage 3 (BFS evaporation) + stage 4 (Köppen)
                # Write per-cell ocean fields
                for li, gi in enumerate(b_cells):
                    c = mesh.cells[gi]
                    c.ocean_current_east_m_s = float(np.dot(vel[li], east[gi]))
                    c.ocean_current_north_m_s = float(np.dot(vel[li], north[gi]))
                    c.sst_anomaly_c = float(sst_anom[gi])

            # ── 3A.3: upwelling → SST cooling ──
            if config.ocean_upwelling_enabled:
                _upw = compute_upwelling_index(wind, mesh.cells, nodes_xyz, east, north, lat_rad)
                t_mean_C = apply_upwelling_sst_correction(_upw, t_mean_C)
        else:
            _console.print("    [dim]No ocean basins detected[/dim]")
    else:
        _console.print("    [dim]Skipped (ocean_currents_enabled=false)[/dim]")

    # ── 3A.3: ocean → land temperature-anomaly advection ──
    # Ocean-current / upwelling SST anomalies are advected onto land along the
    # prevailing wind (signed: warm WBCs warm their downwind coasts, cold EBCs
    # cool theirs).  Replaces the old isotropic diffuse_heat_graph coupling.
    if config.ocean_currents_enabled:
        _radius_m = config.radius_km * 1000.0
        _sst_anom = np.array(
            [c.sst_anomaly_c if c.sst_anomaly_c is not None else 0.0 for c in mesh.cells],
            dtype=np.float64,
        )
        _temp_anom = advect_temperature_anomaly(
            _sst_anom,
            wind,
            is_ocean,
            mesh.cells,
            nodes_xyz,
            radius_m=_radius_m,
            diffusivity=config.ocean_temperature_diffusivity,
        )
        t_mean_C = np.where(is_land, t_mean_C + _temp_anom, t_mean_C)

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
        distance_to_coast_km=distance_to_coast_km,
        config=config,
        itcz_lat_monthly=itcz_lat_monthly,
    )

    # ------------------------------------------------------------------
    # Stage 4: Köppen classification
    phase_timings["precipitation"] = _time.time() - _t0
    _console.print(f"  [green]done[/green] [dim]({phase_timings['precipitation']:.1f}s)[/dim]")
    _t0 = _time.time()
    _console.print("  [dim]5/6  Koppen classification[/dim]")
    # ------------------------------------------------------------------
    # Monthly precipitation from the ITCZ-migration factor (3A.2), conserving
    # the BFS annual total.  Real driest/wettest months and the warm/cold-half
    # split un-dead-code the Köppen third letter (s/w/f/m) and B-group offset.
    p_annual = precipitation_mm
    p_monthly = p_annual[:, None] * p_factor
    p_dry_mm = p_monthly.min(axis=1)
    p_wet_mm = p_monthly.max(axis=1)
    p_warm_mm, p_cold_mm = warm_cold_half_precip(t_monthly_C, p_monthly)
    p_dry_summer_mm, p_wet_winter_mm, p_dry_winter_mm, p_wet_summer_mm = seasonal_precip_extremes(
        t_monthly_C, p_monthly
    )

    koppen_codes = koppen_classify(
        t_mean_c=t_mean_C,
        t_cold_c=t_cold_C,
        t_hot_c=t_hot_C,
        p_annual_mm=p_annual,
        p_dry_mm=p_dry_mm,
        p_wet_mm=p_wet_mm,
        p_warm_mm=p_warm_mm,
        p_cold_mm=p_cold_mm,
        p_dry_summer_mm=p_dry_summer_mm,
        p_wet_winter_mm=p_wet_winter_mm,
        p_dry_winter_mm=p_dry_winter_mm,
        p_wet_summer_mm=p_wet_summer_mm,
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
        mesh.cells[i].temperature_hottest_month_C = float(t_hot_C[i])
        mesh.cells[i].temperature_coldest_month_C = float(t_cold_C[i])
        # Distance to coast (already computed for seasonal heat capacity + inland
        # aridity) is stored on the cell so the civilization engine's "habitable
        # coast" layer can reuse it without re-running the graph Dijkstra.
        _d = distance_to_coast_km[i]
        mesh.cells[i].distance_to_coast_km = float(_d) if np.isfinite(_d) else None

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


def _graph_distance_to_coast(
    cells: list[VoronoiCell],
    n: int,
    is_land: np.ndarray,
    *,
    radius_km: float = 6371.0,
) -> np.ndarray:
    """Shortest graph-path distance from each cell to the nearest ocean (km).

    Multi-source Dijkstra: all ocean cells start at distance 0.  The
    distance between adjacent cells is the great-circle arc length
    computed from their unit-sphere coordinates.  Landlocked cells that
    cannot reach any ocean (should never happen on a connected mesh)
    get infinity.

    Args:
        cells: All VoronoiCell objects.
        n: Number of cells.
        is_land: Boolean land mask, shape (n,).
        radius_km: Planet radius in km.

    Returns:
        Distance to nearest ocean in km, shape (n,).  Ocean cells = 0.
    """
    import heapq

    dist = np.full(n, np.inf, dtype=np.float64)
    visited = np.zeros(n, dtype=bool)

    # Seed: all ocean cells at distance 0
    heap: list[tuple[float, int]] = []
    for i in range(n):
        if not is_land[i]:
            dist[i] = 0.0
            heapq.heappush(heap, (0.0, i))

    while heap:
        d, i = heapq.heappop(heap)
        if visited[i]:
            continue
        visited[i] = True
        for j in cells[i].neighbors:
            if j < 0 or j >= n or visited[j]:
                continue
            # Great-circle distance between cell centres (unit sphere)
            ci, cj = cells[i], cells[j]
            dot = ci.x * cj.x + ci.y * cj.y + ci.z * cj.z
            dot = max(-1.0, min(1.0, dot))
            edge_km = radius_km * np.arccos(dot)
            nd = d + edge_km
            if nd < dist[j]:
                dist[j] = nd
                heapq.heappush(heap, (nd, j))

    return dist


def _detect_coastal_cells(
    cells: list[VoronoiCell],
    n: int,
    is_land: np.ndarray,
    is_ocean: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Identify coastal land cells and determine whether each faces west or east.

    A cell is *coastal* if at least one neighbour is ocean.  Its *coast
    orientation* is determined by counting ocean neighbours to the west
    vs. east.  The comparison is based on the longitude difference between
    the land cell and each ocean neighbour, normalised to [−180°, +180°].

    Returns:
        coastal:    bool array, shape (n,).  True for coastal land cells.
        west_coast: bool array, shape (n,).  True when more ocean neighbours
                    lie to the west than to the east (only meaningful for
                    coastal cells; False otherwise).
    """
    coastal = np.zeros(n, dtype=bool)
    west_coast = np.zeros(n, dtype=bool)

    for i in range(n):
        if not is_land[i]:
            continue
        c = cells[i]
        n_west = 0
        n_east = 0
        for j in c.neighbors:
            if j < 0 or j >= n or not is_ocean[j]:
                continue
            # Normalised longitude difference
            dlon = cells[j].lon - c.lon
            if dlon > 180.0:
                dlon -= 360.0
            elif dlon < -180.0:
                dlon += 360.0
            if dlon > 0:
                n_east += 1
            elif dlon < 0:
                n_west += 1
            # dlon == 0: ignore (same meridian)
        if n_west + n_east > 0:
            coastal[i] = True
            west_coast[i] = n_west > n_east

    return coastal, west_coast


def _surface_divergence(
    nodes_xyz: np.ndarray,
    wind: np.ndarray,
    neighbors: list[list[int]],
    areas_ster: np.ndarray,
) -> np.ndarray:
    """Finite-volume surface divergence ∇·u (1/radian) on the CVT graph.

    ``div_i = (1/A_i) ∮ u · n̂ dl``, discretised over the Voronoi edges as the
    net outward flux of the edge-averaged wind.  Positive = outward flux
    (divergence → sinking / dry); negative = inward flux (convergence → rising
    / rain).  ``areas_ster`` is each cell's area in steradians (area_km2/R²).

    Args:
        nodes_xyz: Unit sphere coordinates, shape (N, 3).
        wind: Surface wind vectors (m/s), shape (N, 3).
        neighbors: Per-cell neighbour index lists.
        areas_ster: Per-cell area in steradians, shape (N,).

    Returns:
        Surface divergence in 1/radian, shape (N,).
    """
    n = len(nodes_xyz)
    div = np.zeros(n, dtype=np.float64)
    for i in range(n):
        xi = nodes_xyz[i]
        for j in neighbors[i]:
            if j < 0 or j >= n:
                continue
            xj = nodes_xyz[j]
            # tangent unit vector from i toward j (outward edge normal)
            d = xj - xi
            d = d - float(np.dot(d, xi)) * xi
            dn = float(np.linalg.norm(d))
            if dn < 1e-12:
                continue
            d = d / dn
            # edge length (angular, unit sphere)
            length = float(np.arccos(np.clip(float(np.dot(xi, xj)), -1.0, 1.0)))
            # outward flux of the edge-averaged wind
            flux = 0.5 * (float(np.dot(wind[i], d)) + float(np.dot(wind[j], d))) * length
            div[i] += flux
        div[i] /= areas_ster[i]
    return div


def _meridional_convergence(
    lat_rad: np.ndarray,
    hadley_extent_deg: float = 30.0,
    polar_cell_start_deg: float = 60.0,
    rotation_period_days: float = 1.0,
    itcz_lat_deg: float = 0.0,
) -> np.ndarray:
    """Smooth zonal-mean surface convergence (1/radian) of the meridional cell wind.

    The large-scale rain belt is driven by the convergence of the three-cell
    meridional circulation, which is a smooth function of latitude only.
    Computing ∇·u per cell (``_surface_divergence``) picks up Voronoi-geometry
    noise that spuriously rains in the subtropical divergence zone, so this
    evaluates the analytical divergence ``(1/cos φ)·d(v·cos φ)/dφ`` of the
    meridional wind on a fine latitude grid and interpolates back to the cells.

    Args:
        lat_rad: Cell latitudes in radians, shape (N,).
        hadley_extent_deg: Hadley cell boundary H (°).
        polar_cell_start_deg: Polar cell boundary P (°).
        rotation_period_days: Rotation period (scales the wind speed).

    Returns:
        Surface convergence in 1/radian, shape (N,); positive = rising.
    """
    grid_deg = np.linspace(-89.0, 89.0, 179)
    grid_rad = np.radians(grid_deg)
    nodes = np.zeros((len(grid_deg), 3))
    nodes[:, 0] = np.cos(grid_rad)
    nodes[:, 1] = np.sin(grid_rad)

    wind = hadley_cell_wind(
        grid_rad,
        nodes,
        hadley_extent_deg,
        polar_cell_start_deg,
        rotation_period_days,
        itcz_lat_deg=itcz_lat_deg,
    )
    # Local north = +y projected to the tangent plane; meridional wind = wind·north.
    north = np.zeros_like(nodes)
    north[:, 1] = 1.0
    north -= nodes * (nodes * north).sum(axis=1, keepdims=True)
    north /= np.linalg.norm(north, axis=1, keepdims=True)
    v = (wind * north).sum(axis=1)  # northward meridional wind (m/s)

    # divergence = (1/cos φ)·d(v·cos φ)/dφ  →  1/radian
    vcos = v * np.cos(grid_rad)
    dvcos = np.gradient(vcos, grid_rad)
    div = dvcos / np.cos(grid_rad)
    conv = np.maximum(0.0, -div)

    return np.asarray(np.interp(np.degrees(lat_rad), grid_deg, conv))


def _compute_precipitation_bfs(
    mesh: CVTMesh,
    wind: np.ndarray,
    is_land: np.ndarray,
    is_ocean: np.ndarray,
    elevation_m: np.ndarray,
    temperature_c: np.ndarray,
    nodes_xyz: np.ndarray,
    distance_to_coast_km: np.ndarray,
    config: TerrainPipelineConfig,
    itcz_lat_monthly: np.ndarray | None = None,
) -> np.ndarray:
    """Multi-pass graph-diffusion moisture transport with orographic precipitation.

    Algorithm (2026-08: replaces single-path BFS):
    1. Build wind-biased symmetric graph Laplacian on CVT adjacency.
       Edge weight = max(0, wind_dir · edge_dir).
    2. Initialize moisture source: ocean evaporation (SST-dependent) + land recycling.
    3. For *k* advection passes:
       a. Solve steady-state diffusion (I + α̅L) q_new = q_source (GMRES).
       b. Compute upwind elevation gain per cell (edge-level sweep).
       c. Apply orographic rain where elev_gain > 0; rain shadow elsewhere.
    4. Add convective (ITCZ) precipitation in tropical regions.

    Single free parameter: D₀ (moisture_diffusivity), scaling with local wind speed.
    Rotation-rate dependence (Ω^(-1/3)) inherited automatically from wind field.

    Args:
        mesh: CVT mesh.
        wind: Wind vector field, shape (N, 3).
        is_land: Boolean land mask, shape (N,).
        is_ocean: Boolean ocean mask, shape (N,).
        elevation_m: Elevation in metres, shape (N,).
        temperature_c: Temperature in °C, shape (N,).
        nodes_xyz: Unit sphere node positions, shape (N, 3).
        distance_to_coast_km: Distance to nearest ocean in km, shape (N,).
        config: Pipeline configuration.

    Returns:
        Annual precipitation in mm, shape (N,).
    """
    n = mesh.num_cells
    precip = np.zeros(n, dtype=np.float64)
    lat_rad = np.radians(np.array([c.lat for c in mesh.cells], dtype=np.float64))
    lon_rad = np.radians(np.array([c.lon for c in mesh.cells], dtype=np.float64))

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

    # ---- Edge table reuse: the BFS precompute (src_k, cand_dst, offsets, counts,
    #   align) is already built above.  For diffusion we convert those directed
    #   wind-aligned edges into a symmetric graph Laplacian.
    #   Weight = max(0, wind_alignment) — edges aligned with wind get higher
    #   diffusivity, counter-wind edges get zero.
    _align_pos = np.maximum(align[keep][order], 0.0)  # keep only positive alignment
    _src_lap = src_k[order]
    _dst_lap = cand_dst
    # Symmetrise: L = (L_dir + L_dir^T) / 2 for SPD property (CG-compatible).
    _row = np.concatenate([_src_lap, _dst_lap])
    _col = np.concatenate([_dst_lap, _src_lap])
    _val = np.concatenate([_align_pos, _align_pos]) * 0.5
    # Remove zero-weight entries
    _nz = _val > 1e-12
    _row, _col, _val = _row[_nz], _col[_nz], _val[_nz]
    _W = sparse.coo_matrix((_val, (_row, _col)), shape=(n, n)).tocsr()
    _degree = np.asarray(_W.sum(axis=1)).ravel()
    _L = sparse.diags(_degree) - _W  # symmetric graph Laplacian

    # Diffusion coefficient: single global D₀ scaled by local wind speed.
    # Fast winds → larger effective diffusivity.  Rotation-rate scaling
    # (Ω^(-1/3)) is inherited from wind speed automatically.
    _wind_mag = np.maximum(wind_speed_all, 1e-9)
    _cell_radius_km = config.radius_km * np.sqrt(4.0 * np.pi / n)
    # D₀ calibrated on Earth; ~0.3 gives good Köppen accuracy trade-off.
    _D0 = config.moisture_diffusivity
    _alpha = _D0 * _wind_mag / _cell_radius_km  # per-cell diffusion strength
    _alpha_avg = float(np.mean(_alpha))

    # Step 2: Multi-pass advection-diffusion
    # Each pass: solve steady-state diffusion (I + α̅*L) q_new = q_source,
    # then apply orographic precipitation from the flux.
    if config.moisture_advection_steps > 0:
        n_steps = config.moisture_advection_steps
    else:
        n_steps = max(8, int(12 * config.rotation_period_days ** (1.0 / 3.0)))
    for _pass in range(n_steps):
        # Reset moisture to ocean evaporation + land recycling
        q_source = ocean_moisture.copy()
        q_source[is_land] += land_moisture[is_land]

        # Solve (I + α̅*L) q = q_source — steady-state diffusion
        _A = sparse.eye(n, format="csr") + _alpha_avg * _L
        q_new, _info = gmres(_A, q_source, rtol=1e-3, atol=1e-6, maxiter=200)
        if _info != 0 and _pass == 0:
            import logging as _log

            _log.getLogger(__name__).warning(
                "Moisture diffusion did not converge (info=%d); result may be approximate.", _info
            )

        # Orographic precipitation from diffused moisture.
        # For each cell with upwind elevation gain, apply orographic rain.
        _upwind_gain = np.zeros(n, dtype=np.float64)
        _upwind_q = np.zeros(n, dtype=np.float64)
        for _ei in range(len(_src_lap)):
            _i, _j = _src_lap[_ei], _dst_lap[_ei]
            _gain = elevation_m[_j] - elevation_m[_i]
            if _gain > 0 and _align_pos[_ei] > 0.1 and _gain > _upwind_gain[_j]:
                _upwind_gain[_j] = _gain
                _upwind_q[_j] = q_new[_i]  # moisture from upwind source

        # Orographic rain applies only to LAND (mountains lift air); the sea
        # surface is flat regardless of ocean-floor relief, so an upwind
        # "elevation gain" over the ocean must not produce rain.
        _q_mask = (_upwind_q > 0.5) & is_land
        _rain = np.zeros(n, dtype=np.float64)
        # Vectorised orographic precipitation:
        # rain_fraction = min(efficiency * elev_gain / 1000, 0.9)
        _frac = np.minimum(0.20 * _upwind_gain[_q_mask] / 1000.0, 0.9)
        _rain[_q_mask] = _upwind_q[_q_mask] * _frac
        # Rain shadow where moisture present but no upwind elevation gain
        _shadow = is_land & (_upwind_gain <= 0) & (_upwind_q > 0.5)
        _rain[_shadow] = _upwind_q[_shadow] * 0.03

        pass_precip = _rain

        # After pass: accumulate
        precip += pass_precip
        precip = np.minimum(precip, 12000.0)

    # Step 3: Baseline precipitation (moisture recycling).  A fraction of the
    # diffused moisture rains out locally even without large-scale convergence —
    # marine stratocumulus, the weak-subsidence rain under the subtropical high,
    # and land evapotranspiration recycling.  This keeps the subtropical
    # divergence zone from drying to absolute zero: the observed zonal mean there
    # is still ~1000 mm/yr, not 0.  ``q_new`` is the diffused moisture from the
    # BFS pass above (mm/yr, high over the warm ocean).
    precip += config.recycling_fraction * q_new

    # Step 3.5: Convergence-driven enhancement.  Rising air (convergence,
    # −∇·u > 0) condenses additional column water vapour on top of the baseline;
    # sinking air (divergence) contributes none.  The ITCZ and the polar front
    # emerge from the wind field itself — no latitude hardcoding, correct for
    # Earth's three cells and gaia-m's single cell alike.
    #
    # The moisture is the Clausius–Clapeyron column water vapour (a function of
    # temperature), capped at ``convergence_moisture_cap_mm``: tropical
    # precipitation is *energy*-limited, not moisture-limited, so it does not
    # scale with the (huge) tropical vapour reservoir.  The cap removes the ~6×
    # moisture dynamic range that a bare q × ∇·u would otherwise inherit.
    lat_deg = np.degrees(lat_rad)
    # Large-scale convergence from the meridional cell circulation (a smooth
    # latitude function — no per-cell Voronoi-geometry noise).  When the monthly
    # ITCZ positions are available, the annual convergence is the 12-month
    # average of the migrating convergence belt: the ITCZ follows the seasonal
    # thermal equator, so the annual rain belt is much broader than the
    # stationary Hadley-cell convergence (which is a narrow equatorial peak).
    if itcz_lat_monthly is not None:
        _conv = np.zeros(n, dtype=np.float64)
        for _m in range(12):
            _conv += _meridional_convergence(
                lat_rad,
                hadley_extent_deg=config.hadley_extent_deg,
                polar_cell_start_deg=config.polar_cell_start_deg,
                rotation_period_days=config.rotation_period_days,
                itcz_lat_deg=float(itcz_lat_monthly[_m]),
            )
        _conv /= 12.0
    else:
        _conv = _meridional_convergence(
            lat_rad,
            hadley_extent_deg=config.hadley_extent_deg,
            polar_cell_start_deg=config.polar_cell_start_deg,
            rotation_period_days=config.rotation_period_days,
        )
    _t_k = np.maximum(temperature_c + 273.15, 230.0)
    _e_sat = 611.2 * np.exp(17.67 * (_t_k - 273.15) / (_t_k - 29.65))  # Pa (Magnus)
    _q_sat = 0.622 * _e_sat / 101325.0  # saturation specific humidity (kg/kg)
    # Column (precipitable) water: q_sat × ρ_air × H_w, with the water-vapour
    # scale height H_w ≈ 2500 m (≈60 mm at 27 °C, ≈16 mm at 5 °C).
    _col_water_mm = _q_sat * 1.2 * 2500.0
    _rainable = np.minimum(_col_water_mm, config.convergence_moisture_cap_mm)
    precip += config.convergence_efficiency * _rainable * _conv

    # Step 3.5: Mid-latitude storm tracks (baroclinic eddies) — a distinct
    # mechanism.  The convergence above captures the Hadley rising branch (ITCZ)
    # and descending branch (subtropical dry belt), but the extratropical
    # cyclones that deliver the ~800–1000 mm/yr mid-latitude rain are driven by
    # baroclinic instability, whose ascent + moisture transport the mean surface
    # convergence does not resolve.  Amplitude scales with the Eady growth rate
    # (∇T × Ω^0.3) and the available moisture (evaporation); centre at the
    # polar front.
    _lat_grad = (
        lat_gradient_from_omega(
            config.rotation_period_days,
            earth_gradient_c=config.lat_gradient_earth_c,
        )
        if config.auto_lat_gradient
        else config.lat_gradient_c
    )
    _storm_center = config.polar_cell_start_deg - 2.0  # polar front
    _storm_width = 14.0 * (config.hadley_extent_deg / 30.0)
    _storm_amp = (
        config.storm_track_amplitude_mm
        * (_lat_grad / 45.0)
        * (1.0 / config.rotation_period_days) ** 0.3
        * (config.evaporation_base_mm / 2000.0)
    )
    precip += _storm_amp * np.exp(-0.5 * ((np.abs(lat_deg) - _storm_center) / _storm_width) ** 2)

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

    # Step 6.5: Inland aridity gradient (3A.4).
    # BFS moisture transport has finite range (~12 graph hops).  Cells deep
    # in continental interiors receive no direct ocean moisture and must
    # rely on recycled precipitation (not yet modelled).  Apply an exponential
    # decay beyond the BFS effective range so that hyper-arid interiors
    # (e.g. Taklamakan, central Sahara) are realistically dry.
    #
    # The distance-to-coast is computed once on the CVT graph via Dijkstra
    # from all ocean cells — this is the shortest graph-path to any ocean.
    if is_land.any():
        _dist_km = distance_to_coast_km
        # E-folding distance scales with wind speed only: moisture travels
        # farther where winds are stronger.  Humidity affects the *amount* of
        # moisture carried (via evaporation), not the transport distance —
        # coupling q_sat into e_fold collapsed the distance in cold polar air
        # and hyper-dried continental interiors (see 2026-08-13 fix).
        # Reference: 800 km at Earth trade-wind speed (5 m/s).
        _zwind_inland = hadley_cell_wind(
            lat_rad,
            nodes_xyz,
            hadley_extent_deg=config.hadley_extent_deg,
            polar_cell_start_deg=config.polar_cell_start_deg,
            rotation_period_days=config.rotation_period_days,
        )
        from dreamulator.map.ocean_circulation import east_north_basis as _enb3

        _e_inland, _ = _enb3(nodes_xyz)
        _uz_abs = np.abs(np.einsum("ij,ij->i", _zwind_inland, _e_inland))
        for i in range(n):
            if not is_land[i]:
                continue
            u_local = max(_uz_abs[i], 1.0)
            e_fold = 800.0 * (u_local / 5.0)
            threshold = 500.0 * (u_local / 5.0)
            excess = max(_dist_km[i] - threshold, 0.0)
            precip[i] *= np.exp(-excess / e_fold)

    # Step 6.6: West-coast / east-coast asymmetry (3A.4).
    # Onshore winds carry ocean moisture → coastal precipitation is
    # enhanced; offshore winds carry dry continental air → suppressed.
    #
    # The onshore moisture flux is  ρ_air × |U_zonal| × q_sat(T).  A
    # small fraction ε ≈ 1.3×10⁻⁴ of this flux precipitates at the
    # coast (the "coastal precipitation efficiency").  The enhancement
    # factor is therefore
    #
    #     f = 1 ± ε × ρ_air × |U| × q_sat(T) × s_per_year / P_bg
    #
    # where P_bg ≈ 1000 mm/yr is a reference background precipitation.
    # For Earth (U=5 m/s, T=15°C): f ≈ 1.25 (windward), 0.85 (leeward),
    # matching the old hard-coded values — but now the formula adapts
    # automatically to different wind speeds, temperatures, and gravities.
    if is_land.any():
        _coastal, _west_coast = _detect_coastal_cells(
            mesh.cells,
            n,
            is_land,
            is_ocean,
        )
        _zwind = hadley_cell_wind(
            lat_rad,
            nodes_xyz,
            hadley_extent_deg=config.hadley_extent_deg,
            polar_cell_start_deg=config.polar_cell_start_deg,
            rotation_period_days=config.rotation_period_days,
        )
        from dreamulator.map.ocean_circulation import east_north_basis as _enb2

        _east, _ = _enb2(nodes_xyz)
        _uzonal = np.einsum("ij,ij->i", _zwind, _east)

        # Physical constants
        _rho_air = 1.2  # kg/m³
        _s_per_year = 365.25 * 86400.0
        _p_bg = 1000.0  # mm/yr reference background precipitation
        _eps_windward = 1.3e-4  # coastal precipitation efficiency (windward)
        _eps_leeward = 0.8e-4  # coastal precipitation efficiency (leeward)

        for i in range(n):
            if not _coastal[i]:
                continue
            u_abs = abs(_uzonal[i])
            t_k = max(temperature_c[i] + 273.15, 230.0)
            # Specific humidity (kg/kg) from Clausius–Clapeyron
            e_sat = 611.2 * np.exp(17.67 * (t_k - 273.15) / (t_k - 29.65))  # Pa
            q_sat = 0.622 * e_sat / 101325.0  # kg/kg
            # Onshore moisture flux → precipitation enhancement
            moisture_flux = _rho_air * u_abs * q_sat  # kg/m²/s
            delta_p = moisture_flux * _s_per_year  # mm/yr equivalent

            is_west_coast = _west_coast[i]
            is_westerly = _uzonal[i] > 0
            windward = (is_westerly and is_west_coast) or (not is_westerly and not is_west_coast)
            eps = _eps_windward if windward else _eps_leeward
            factor = 1.0 + eps * delta_p / _p_bg if windward else (1.0 - eps * delta_p / _p_bg)
            precip[i] *= np.clip(factor, 0.5, 1.5)

    # Step 6.7: Physics-based Föhn rain shadow (3A.4).
    #
    # As moist air rises on the windward slope it cools at the moist
    # adiabatic lapse rate Γ_m(T).  The saturation vapour pressure drops
    # exponentially with temperature (Clausius–Clapeyron).  The surviving
    # moisture fraction after crossing a barrier of height Δz is
    #
    #     f = exp(−Δz / H_scale)
    #
    # where  H_scale = R_v · T² / (L_v · Γ_m)  (moisture scale height).
    # At T ≈ 280 K, Γ_m ≈ 5.5 K/km → H_scale ≈ 2.6 km.
    #
    # BFS already handles windward-side orographic precipitation, so this
    # step only applies the leeward-side Föhn drying.  No redistribution
    # to windward cells — BFS covers that physics.
    if is_land.any():
        _westerly_rs = (np.abs(lat_deg) >= config.hadley_extent_deg) & (
            np.abs(lat_deg) < config.polar_cell_start_deg
        )
        for i in range(n):
            if not is_land[i] or elevation_m[i] < 0:
                continue
            ci = mesh.cells[i]
            max_upwind_elev = elevation_m[i]
            for j in ci.neighbors:
                if j < 0 or j >= n:
                    continue
                cj = mesh.cells[j]
                dlon = cj.lon - ci.lon
                if dlon > 180.0:
                    dlon -= 360.0
                elif dlon < -180.0:
                    dlon += 360.0
                is_upwind = (_westerly_rs[i] and dlon < 0) or (not _westerly_rs[i] and dlon > 0)
                if is_upwind and elevation_m[j] > max_upwind_elev:
                    max_upwind_elev = elevation_m[j]
            elev_drop = max_upwind_elev - elevation_m[i]
            if elev_drop > 500.0:
                t_k = max(temperature_c[i] + 273.15, 230.0)
                gamma = moist_lapse_rate(np.array([temperature_c[i]]))[0]
                h_scale_m = 461.0 * t_k**2 / (2.5e6 * gamma / 1000.0)
                fohn_factor = np.exp(-elev_drop / h_scale_m)
                precip[i] *= fohn_factor

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

    # Step 8: Sub-planet / sub-stellar convective enhancement (3A.7).
    # A tidally-locked planet (or a satellite like gaia-m) has a permanently
    # warmer hemisphere facing the host body.  The extra heating drives
    # low-level convergence → rising air → convective precipitation,
    # analogous to the ITCZ but fixed at a (lat, lon) point rather than a
    # latitude band.  The same mechanism applies to:
    #   - satellites (host-planet IR + reflected light)
    #   - tidally-locked planets (sub-stellar insolation)
    #   - circumbinary planets (dual heat sources — future)
    #
    # The enhancement is a Gaussian in angular distance from the sub-body
    # point, with amplitude ∝ sub_planet_warming_c.  A 1 °C warming gives
    # ~200 mm/yr peak enhancement (≈ weak ITCZ).
    if config.sub_planet_warming_c > 0:
        sub_lat = np.radians(config.sub_planet_latitude_deg)
        sub_lon = np.radians(config.sub_planet_longitude_deg)
        cos_ang = np.sin(lat_rad) * np.sin(sub_lat) + np.cos(lat_rad) * np.cos(sub_lat) * np.cos(
            lon_rad - sub_lon
        )
        ang_dist_deg = np.degrees(np.arccos(np.clip(cos_ang, -1.0, 1.0)))
        amplitude = config.sub_planet_warming_c * 200.0  # mm/yr per °C
        sub_boost = amplitude * np.exp(-0.5 * (ang_dist_deg / 15.0) ** 2)
        precip += sub_boost

    # Final cap after ALL precipitation steps.  Real-Earth maximum annual
    # precipitation is ~11000 mm/yr (Mawsynram/Cherrapunji).  The per-pass cap
    # inside the BFS loop (12000 mm) only guards the diffusion accumulation and
    # runs *before* the ITCZ / storm-track / monsoon / convection additions, so
    # it never limited the final field (P_max reached ~30500 mm/yr — see
    # roadmap §6).  Cap once here to keep the wettest cells physical.
    precip = np.minimum(precip, 11000.0)

    return precip
