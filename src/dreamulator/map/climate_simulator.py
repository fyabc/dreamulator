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
from dreamulator.engine.monsoon_circulation import (
    _DRAG_RATE_LAND_S,
    _DRAG_RATE_S,
    monsoon_boundary_layer_wind,
    pressure_anomaly_monthly,
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


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def simulate_climate(
    mesh: CVTMesh,
    config: TerrainPipelineConfig,
    debug: dict[str, np.ndarray] | None = None,
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

    # Land/ocean split is geological (water_class is written by the terrain
    # pipeline via ocean-connectivity flood-fill).  A bare `elevation >= 0`
    # would misclassify endorheic basins below sea level (Turpan −154 m,
    # Qattara, Afar, Death Valley) as ocean.  Fall back to connectivity if
    # water_class is unset (legacy mesh with no water_class written).
    is_land = np.array([c.water_class == "land" for c in mesh.cells], dtype=bool)
    if not is_land.any():
        from dreamulator.map.water_bodies import compute_land_mask

        is_land = compute_land_mask(mesh.cells, config.sea_level_offset_m)
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
    _console.print("  [dim]1/6  Temperature (EBM + latitude + altitude)[/dim]")
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

    # Ocean surface temperature: damped latitude gradient (maritime moderation)
    # anchored to the planet's global-mean surface temperature (Earth profile
    # at Earth forcing; shifts 1:1 with stellar forcing / greenhouse changes)
    t_mean_C[~land_mask_arr] = _ocean_surface_temperature(
        lat_rad[~land_mask_arr],
        t_surf_C,
    )

    # Coastal moderation (maritime influence on the annual mean): mix the
    # *sea-level* land temperature toward the nearest ocean's SST, decaying
    # inland over the maritime scale.  Applied *before* the altitude lapse rate
    # so the elevation cooling still acts on the moderated coastal lowlands and
    # the high ice sheet stays cold.  The ice-covered ocean's SST (~−2 °C) is
    # already cold, so this is automatically ice-aware.
    distance_to_coast_km, nearest_sst = _graph_distance_to_coast(
        mesh.cells, n, is_land, radius_km=config.radius_km, ocean_value=t_mean_C
    )
    assert nearest_sst is not None  # ocean_value always passed
    # Ocean-less worlds: _graph_distance_to_coast has no seed cells, so
    # nearest_sst is NaN.  Mask the maritime term to exactly zero there —
    # (NaN − T)·0 would still be NaN, so sanitise the SST too.
    _has_sst = np.isfinite(nearest_sst)
    nearest_sst = np.where(_has_sst, nearest_sst, t_mean_C)
    _maritime = np.where(
        is_land & _has_sst,
        np.exp(-distance_to_coast_km / config.coastal_moderation_scale_km),
        0.0,
    )
    t_mean_C = t_mean_C + (nearest_sst - t_mean_C) * _maritime

    # Altitude correction (land only — ocean surface is at 0 m regardless of depth)
    lapse: float | np.ndarray = config.lapse_rate_c_km
    if config.variable_lapse_rate:
        lapse = moist_lapse_rate(t_mean_C[land_mask_arr])
    t_mean_C[land_mask_arr] = altitude_lapse_rate(
        t_mean_C[land_mask_arr],
        elevation_m[land_mask_arr],
        lapse,
    )

    # Sub-planet hemisphere warming (e.g. nacrea: Aegis IR + reflected light)
    if config.sub_planet_warming_c > 0:
        lon_rad = np.radians(np.array([c.lon for c in mesh.cells], dtype=np.float64))
        # Cosine falloff from sub-planet point, zero on anti-planet side
        cos_lon = np.cos(lon_rad - np.radians(config.sub_planet_longitude_deg))
        warming = config.sub_planet_warming_c * np.maximum(0, cos_lon)
        t_mean_C += warming

    # Seasonality (3A.2): seasonal energy-balance model — insolation-driven
    # monthly temperature with physical surface heat capacity (land/ocean/coastal).
    # Distance-to-coast is computed above and reused by the heat capacity.
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
    itcz_lat_monthly = seasonal["itcz_lat"]

    # ------------------------------------------------------------------
    # Stage 2: Wind
    phase_timings["temperature"] = _time.time() - _t0
    _console.print(f"  [green]done[/green] [dim]({phase_timings['temperature']:.1f}s)[/dim]")
    _t0 = _time.time()
    _console.print("  [dim]2/6  Wind field (geostrophic + Hadley cells)[/dim]")
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
    # expanded Hadley cell).  The circulation follows the migrating ITCZ:
    # averaging the cells over the 12 monthly ITCZ positions makes the
    # annual-mean convergence band span the ITCZ's full seasonal excursion
    # rather than sitting pinned at the geographic equator (roadmap 20 ①).
    wind_cell = _seasonal_mean_cell_wind(lat_rad, nodes_xyz, config, itcz_lat_monthly)

    # Combine: 40% geostrophic + 60% cell circulation
    wind = 0.4 * wind_geostrophic + 0.6 * wind_cell

    # ── Monsoon wind anomaly (tech debt 23) ──
    # Summer continents warm above the zonal mean → thermal lows; the boundary-
    # layer wind answers the anomaly pressure gradient against Coriolis and drag
    # (engine/monsoon_circulation.py).  Near the equator f → 0 and the flow goes
    # straight down-gradient — the cross-equatorial monsoon current.  The anomaly
    # is added onto the annual background, giving 12 monthly winds that drive the
    # monthly moisture budget in Stage 3.
    from dreamulator.map.ocean_circulation import _build_directed_edge_table

    _msrc, _mdst = _build_directed_edge_table(mesh.cells)

    _dp_hpa = pressure_anomaly_monthly(
        t_monthly_C,
        lat_deg,
        surface_pressure_hpa=config.surface_pressure_hpa,
    )
    # Scale separation before differentiation: the anomaly field inherits the
    # cell-level land-ocean mosaic (~51 km at 200k cells), whose coastline
    # jumps dominate the raw gradient and drive sea-breeze-scale winds far
    # stronger than any monsoon.  Pressure anomalies adjust hydrostatically over
    # the synoptic scale (the Rossby deformation radius, O(500 km)), so smooth
    # each month's field over that scale first — the continental thermal lows
    # (1000–4000 km wide) survive, the mosaic noise does not.  Each Jacobi pass
    # is a lazy random-walk step (σ = √(passes/2)·cell_spacing).
    _cell_km = 2.0 * config.radius_km * np.sqrt(np.pi / n)
    _smooth_passes = 2 * int((_MONSOON_PRESSURE_SMOOTHING_KM / _cell_km) ** 2)
    _mdeg = np.maximum(np.bincount(_msrc, minlength=n).astype(np.float64), 1.0)
    # Neighbour-averaging operator M (row i = mean over i's neighbours),
    # applied as a sparse matmul so all 12 months smooth in one pass.
    _avg = sparse.csr_matrix(
        (1.0 / _mdeg[_msrc], (_msrc, _mdst)),
        shape=(n, n),
    )
    _dp_fields = _dp_hpa  # (N, 12)
    for _ in range(_smooth_passes):
        _dp_fields = 0.5 * _dp_fields + 0.5 * _avg.dot(_dp_fields)
    _dp_hpa = np.asarray(_dp_fields)

    _radius_m = config.radius_km * 1000.0
    # Least-squares gradient per radian on the unit sphere → Pa/m (hPa × 100).
    _grad_dp_pa_m = np.stack(
        [
            _graph_least_squares_gradient(mesh, _dp_hpa[:, m], nodes_xyz) * 100.0 / _radius_m
            for m in range(12)
        ]
    )
    # Per-cell drag: land (rough vegetation) drags harder than ocean, so the
    # f→0 degeneracy v = G/k_d doesn't over-amplify the equatorial land wind
    # (Amazon → ~1 m/s instead of ~20 m/s; see atmospheric_circulation.md §4.5).
    _drag = np.where(is_land, _DRAG_RATE_LAND_S, _DRAG_RATE_S)
    _wind_monsoon = monsoon_boundary_layer_wind(
        _grad_dp_pa_m, f_coriolis, nodes_xyz, drag_rate_s=_drag
    )

    # Monthly wind = annual background + monsoon anomaly.  The 12-month
    # average of the monthly winds is the background field itself (the
    # anomaly averages to zero), so the annual-mean state is unchanged.  The
    # monthly migration of the circulation cells is part of the monthly-vector
    # winds work (tech debt 24): tested here, giving each month its own
    # ITCZ-shifted circulation sharpened the convergence band into a sweeping
    # rain belt that over-seasoned the subtropics (Csa/Dsb inflation) and
    # overshot land-mean precipitation, so v1 keeps the calibrated
    # annual-mean circulation as the advecting field and lets the anomaly
    # carry the seasonal land-sea reversal.
    wind_monthly = np.stack([wind + _wind_monsoon[m] for m in range(12)])

    # Terrain blocking (the annual field and each monthly field exactly once —
    # blocking is a per-cell linear scaling of the wind vector).
    wind = terrain_wind_blocking(wind, elevation_m, config.wind_blocking_height_m)
    wind_monthly = np.stack(
        [
            terrain_wind_blocking(wind_monthly[m], elevation_m, config.wind_blocking_height_m)
            for m in range(12)
        ]
    )

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
    # Stage 3: Precipitation (monthly mass-conserving moisture budget)
    phase_timings["ocean"] = _time.time() - _t0
    _console.print(f"  [green]done[/green] [dim]({phase_timings['ocean']:.1f}s)[/dim]")
    _t0 = _time.time()
    _console.print("  [dim]4/6  Precipitation (monthly moisture budget)[/dim]")
    # ------------------------------------------------------------------
    precipitation_mm, p_monthly = _compute_precipitation_monthly_budget(
        mesh=mesh,
        wind=wind,
        wind_monthly=wind_monthly,
        is_land=is_land,
        is_ocean=is_ocean,
        elevation_m=elevation_m,
        temperature_c=t_mean_C,
        t_monthly_c=t_monthly_C,
        nodes_xyz=nodes_xyz,
        config=config,
        itcz_lat_monthly=itcz_lat_monthly,
        debug=debug,
        edge_table=(_msrc, _mdst),
    )

    # ------------------------------------------------------------------
    # Stage 4: Köppen classification
    phase_timings["precipitation"] = _time.time() - _t0
    _console.print(f"  [green]done[/green] [dim]({phase_timings['precipitation']:.1f}s)[/dim]")
    _t0 = _time.time()
    _console.print("  [dim]5/6  Koppen classification[/dim]")
    # ------------------------------------------------------------------
    # Monthly precipitation now comes directly from the monthly moisture budget
    # (Stage 3): each month's wind (background + monsoon anomaly) and
    # evaporation (from that month's temperature) drive that month's column
    # water and rainout.  The ITCZ-Gaussian redistribution factor is gone —
    # driest/wettest months and the warm/cold-half split are real monthly
    # values, which is what the Köppen third letter (s/w/f/m) needs.
    p_annual = precipitation_mm
    p_dry_mm = p_monthly.min(axis=1)
    p_wet_mm = p_monthly.max(axis=1)
    p_warm_mm, p_cold_mm = warm_cold_half_precip(t_monthly_C, p_monthly)
    p_dry_summer_mm, p_wet_winter_mm, p_dry_winter_mm, p_wet_summer_mm = seasonal_precip_extremes(
        t_monthly_C, p_monthly
    )

    # Store the monthly climate arrays for the export stage (Phase 4 monthly
    # display).  These are *not* serialized to cvt_mesh.json — the full N×12
    # fields would double the mesh — so export_climate_layers reads them off the
    # mesh object and writes a separate compact MessagePack file.
    object.__setattr__(mesh, "_t_monthly_c", t_monthly_C.astype(np.float32))
    object.__setattr__(mesh, "_p_monthly_mm", np.maximum(p_monthly, 0.0).astype(np.float32))

    # Monthly vector field + pressure (tech debt 24): decompose the monthly winds
    # into local east/north components (same sign convention as the Stage 2 annual
    # wind write-back) and carry the smoothed monsoon pressure anomaly ΔP (hPa).
    _we_monthly = np.empty((n, 12), dtype=np.float32)
    _wn_monthly = np.empty((n, 12), dtype=np.float32)
    for _m in range(12):
        _we_m, _wn_m = _dec_wind(wind_monthly[_m], _east_w, _north_w)
        _we_monthly[:, _m] = -_we_m
        _wn_monthly[:, _m] = _wn_m
    object.__setattr__(mesh, "_wind_east_monthly", _we_monthly)
    object.__setattr__(mesh, "_wind_north_monthly", _wn_monthly)
    object.__setattr__(mesh, "_pressure_monthly", _dp_hpa.astype(np.float32))

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


def _graph_least_squares_gradient(
    mesh: CVTMesh,
    scalar: np.ndarray,
    nodes_xyz: np.ndarray,
) -> np.ndarray:
    """Per-cell least-squares gradient of a scalar field, in radians on the unit sphere.

    Unlike ``_compute_graph_gradient`` (a weighted difference average whose
    magnitude depends on the mesh spacing and which the geostrophic wind absorbs
    into its calibration), this solves the local normal equations

        (Σ_j d_j d_jᵀ) g = Σ_j Δf_j d_j

    over each cell's neighbours, with d_j the tangent vector from the cell to
    neighbour j (length = angular distance, radians).  The result is the true
    gradient per radian of arc, independent of the local mesh spacing — needed
    wherever a physical gradient magnitude matters (the monsoon pressure-gradient
    force).  Convert to per-metre by dividing by the planet radius.

    Args:
        mesh: CVT mesh with adjacency information.
        scalar: Scalar field values, shape (N,).
        nodes_xyz: Unit sphere coordinates, shape (N, 3).

    Returns:
        Gradient vectors tangent to the sphere, per radian, shape (N, 3).
    """
    n = mesh.num_cells
    _src: list[int] = []
    _dst: list[int] = []
    for _i, _cell in enumerate(mesh.cells):
        for _j in _cell.neighbors:
            if 0 <= _j < n:
                _src.append(_i)
                _dst.append(_j)
    src = np.asarray(_src, dtype=np.int64)
    dst = np.asarray(_dst, dtype=np.int64)

    # Tangent vector from src cell toward its neighbour (unit sphere).
    edge_vec = nodes_xyz[dst] - nodes_xyz[src]
    radial = np.einsum("ij,ij->i", edge_vec, nodes_xyz[src])
    edge_vec = edge_vec - radial[:, None] * nodes_xyz[src]

    # Local (east, north) basis at each src cell — the same convention as
    # hadley_cell_wind (north = (0,1,0) projected tangent, east = north × r̂,
    # a right-handed ENU frame; see engine/monsoon_circulation.py).
    node_s = nodes_xyz[src]
    north = np.array([0.0, 1.0, 0.0]) - node_s[:, 1:2] * node_s
    north_norm = np.linalg.norm(north, axis=1)
    ok_n = north_norm >= 1e-9
    north[ok_n] /= north_norm[ok_n, None]
    east = np.cross(north, node_s)
    east_norm = np.linalg.norm(east, axis=1)
    ok_e = east_norm >= 1e-9
    east[ok_e] /= east_norm[ok_e, None]

    dx = np.einsum("ij,ij->i", edge_vec, east)
    dy = np.einsum("ij,ij->i", edge_vec, north)
    df = scalar[dst] - scalar[src]

    # Accumulate the 2×2 normal equations per cell.
    m11 = np.zeros(n, dtype=np.float64)
    m12 = np.zeros(n, dtype=np.float64)
    m22 = np.zeros(n, dtype=np.float64)
    b1 = np.zeros(n, dtype=np.float64)
    b2 = np.zeros(n, dtype=np.float64)
    np.add.at(m11, src, dx * dx)
    np.add.at(m12, src, dx * dy)
    np.add.at(m22, src, dy * dy)
    np.add.at(b1, src, dx * df)
    np.add.at(b2, src, dy * df)

    det = m11 * m22 - m12 * m12
    valid = det > 1e-18
    gx = np.zeros(n, dtype=np.float64)
    gy = np.zeros(n, dtype=np.float64)
    gx[valid] = (m22[valid] * b1[valid] - m12[valid] * b2[valid]) / det[valid]
    gy[valid] = (m11[valid] * b2[valid] - m12[valid] * b1[valid]) / det[valid]

    # Recompose in the per-cell basis (recomputed at every cell, not just edge
    # sources, so isolated cells still get a zero vector).
    north_c = np.array([0.0, 1.0, 0.0]) - nodes_xyz[:, 1:2] * nodes_xyz
    north_c_norm = np.linalg.norm(north_c, axis=1)
    ok_nc = north_c_norm >= 1e-9
    north_c[ok_nc] /= north_c_norm[ok_nc, None]
    east_c = np.cross(north_c, nodes_xyz)
    east_c_norm = np.linalg.norm(east_c, axis=1)
    ok_ec = east_c_norm >= 1e-9
    east_c[ok_ec] /= east_c_norm[ok_ec, None]
    grad = gx[:, None] * east_c + gy[:, None] * north_c
    return np.asarray(grad)


def _seasonal_mean_cell_wind(
    lat_rad: np.ndarray,
    nodes_xyz: np.ndarray,
    config: TerrainPipelineConfig,
    itcz_lat_monthly: np.ndarray | None,
) -> np.ndarray:
    """Time-average of the three-cell circulation over the seasonal ITCZ.

    The circulation is symmetric about the thermal equator, which follows the
    subsolar point through the year (``itcz_lat_monthly``).  The annual-mean
    wind that drives the steady moisture budget is therefore the time average
    of the circulation evaluated at each month's ITCZ position: the surface
    convergence band ends up spread over the ITCZ's full seasonal excursion
    instead of being pinned at the geographic equator.  With ``None`` (or an
    all-zero array) this reduces to the single classic call.

    Args:
        lat_rad: Latitude in radians, shape (N,).
        nodes_xyz: Unit sphere node positions, shape (N, 3).
        config: Pipeline configuration (cell extents, rotation period).
        itcz_lat_monthly: ITCZ latitude per month (degrees), shape (12,), or
            None for no migration.

    Returns:
        Annual-mean cell-circulation wind vectors (m/s), shape (N, 3).
    """
    if itcz_lat_monthly is None:
        itcz_lat_monthly = np.zeros(12)
    winds = [
        hadley_cell_wind(
            lat_rad,
            nodes_xyz,
            hadley_extent_deg=config.hadley_extent_deg,
            polar_cell_start_deg=config.polar_cell_start_deg,
            rotation_period_days=config.rotation_period_days,
            itcz_lat_deg=float(itcz),
        )
        for itcz in itcz_lat_monthly
    ]
    mean_wind: np.ndarray = np.mean(np.stack(winds), axis=0)
    return mean_wind


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
    ocean_value: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray | None]:
    """Shortest graph-path distance from each cell to the nearest ocean (km).

    Multi-source Dijkstra: all ocean cells start at distance 0.  The
    distance between adjacent cells is the great-circle arc length
    computed from their unit-sphere coordinates.  Landlocked cells that
    cannot reach any ocean (should never happen on a connected mesh)
    get infinity.

    When ``ocean_value`` is supplied, the Dijkstra also propagates that
    per-cell value from the nearest ocean to every cell (a land cell inherits
    its *nearest* ocean's value — e.g. the SST for coastal moderation).

    Args:
        cells: All VoronoiCell objects.
        n: Number of cells.
        is_land: Boolean land mask, shape (n,).
        radius_km: Planet radius in km.
        ocean_value: Optional per-cell value to propagate from the nearest ocean.

    Returns:
        Distance to nearest ocean in km, shape (n,).  Ocean cells = 0.
        If ``ocean_value`` is given, also returns the nearest ocean's value.
    """
    import heapq

    dist = np.full(n, np.inf, dtype=np.float64)
    val = np.full(n, np.nan, dtype=np.float64)
    visited = np.zeros(n, dtype=bool)

    # Seed: all ocean cells at distance 0
    heap: list[tuple[float, int]] = []
    for i in range(n):
        if not is_land[i]:
            dist[i] = 0.0
            if ocean_value is not None:
                val[i] = ocean_value[i]
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
                if ocean_value is not None:
                    val[j] = val[i]
                heapq.heappush(heap, (nd, j))

    return dist, val if ocean_value is not None else None


def _upwind_distance_to_coast(
    cells: list[VoronoiCell],
    n: int,
    is_land: np.ndarray,
    wind: np.ndarray,
    nodes_xyz: np.ndarray,
    *,
    radius_km: float = 6371.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Upwind distance from each cell to the nearest ocean (km), following the wind.

    Multi-source Dijkstra that only relaxes *downwind* edges — from cell ``i``
    we move to neighbour ``j`` only when the surface wind at ``i`` blows toward
    ``j`` (``wind[i] · e(i→j) > 0``).  This traces the path moisture actually
    travels from the ocean inland, so the distance is directional (moisture
    travels along the wind, not isotropically) and resolution-independent
    (great-circle arc length in km, not a hop count).

    Returns:
        dist:   upwind distance in km (ocean cells = 0; unreachable land = inf).
        source: index of the upwind ocean cell the moisture came from
            (ocean cells = own index; unreachable = -1).
    """
    import heapq

    dist = np.full(n, np.inf, dtype=np.float64)
    source = np.full(n, -1, dtype=np.int64)
    visited = np.zeros(n, dtype=bool)
    heap: list[tuple[float, int]] = []
    for i in range(n):
        if not is_land[i]:
            dist[i] = 0.0
            source[i] = i
            heapq.heappush(heap, (0.0, i))

    with np.errstate(invalid="ignore", divide="ignore"):
        wind_unit = wind / np.maximum(np.linalg.norm(wind, axis=1), 1e-9)[:, None]

    while heap:
        d, i = heapq.heappop(heap)
        if visited[i]:
            continue
        visited[i] = True
        ci = nodes_xyz[i]
        for j in cells[i].neighbors:
            if j < 0 or j >= n or visited[j]:
                continue
            cj = nodes_xyz[j]
            edge_vec = cj - ci
            edge_vec = edge_vec - float(np.dot(edge_vec, ci)) * ci
            en = float(np.linalg.norm(edge_vec))
            if en < 1e-9:
                continue
            edge_dir = edge_vec / en
            if float(np.dot(wind_unit[i], edge_dir)) <= 0.0:
                continue  # j is not downwind of i — moisture does not reach it
            dot = max(-1.0, min(1.0, float(np.dot(ci, cj))))
            edge_km = radius_km * float(np.arccos(dot))
            nd = d + edge_km
            if nd < dist[j]:
                dist[j] = nd
                source[j] = source[i]
                heapq.heappush(heap, (nd, j))

    return dist, source


# Water-vapour residence time in the atmosphere (days).  Global mean column
# water ~25 mm ÷ global precip ~2.7 mm/day ≈ 9 days (Trenberth 1998; the value
# is re-confirmed by van der Ent & Tuinenburg 2016).  This is the rainout
# timescale τ in the moisture budget P = W/τ, a physical constant — not a free
# calibration knob — so it is shared by every world (only wind speed and
# evaporation differ, and the advective e-folding length L = u·τ adapts
# automatically with Ω).
_MOISTURE_RESIDENCE_DAYS: float = 9.0

# Turbulent moisture diffusivity (m²/s).  Atmospheric eddy diffusivity is
# ~1e6 m²/s; this sets the sub-grid spreading of the advected moisture (the
# physical ITCZ rain belt is ~10° wide, not a single cell).  At κ=1e6 the
# diffusion over-transported ocean moisture onto land (ocean→land transport
# ~2× the observed ~268 mm/yr land-mean), so κ is calibrated down toward the
# observed transport.  Shared across worlds.
_MOISTURE_DIFFUSIVITY_M2S: float = 7.5e5

# Land evapotranspiration as a fraction of the ocean evaporation *rate* at the
# same temperature.  Earth's land surface returns ~490 mm/yr against the ocean's
# ~1143 mm/yr (Trenberth et al. 2009 global water budget), i.e. ~43% — but land
# is colder than the ocean on average, so the reference is the shared 15 °C
# evaporation rate and this factor absorbs the soil/vegetation reduction of
# evapotranspiration relative to open water.  Calibrated so the global
# land-mean evapotranspiration lands near the observed ~490 mm/yr.  A single
# physical constant, shared by every world (only temperature differs).
_LAND_EVAPOTRANSPIRATION_FRACTION: float = 0.55

# Monsoon pressure-anomaly smoothing scale (km).  The monsoon wind responds to
# the gradient of the seasonal pressure anomaly, which must be evaluated on the
# synoptic scale — hydrostatic/geostrophic adjustment spreads local heating over
# the Rossby deformation radius, O(500 km) in the tropics and mid-latitudes —
# not on the 51 km cell scale of the land-ocean mosaic (see Stage 2 wiring).
# This is a physical scale separation, shared by all worlds: the mesh resolves
# the anomaly, the atmosphere does not feel it at that resolution.
_MONSOON_PRESSURE_SMOOTHING_KM: float = 500.0

# Land recycling (Budyko 1974; Savenije 1995; van der Ent & Savenije 2011): land
# evapotranspiration is water-limited, not just energy-limited — wet land
# (Amazon) evaporates near its potential, dry land (Sahara) evaporates only the
# rain that falls.  This is the physical mechanism behind the "inland aridity"
# that the old distance-to-coast decay (removed) approximated: the recycled
# fraction of precipitation decays inland with a *region-dependent* length scale
# λ ∈ 500–7000 km (van der Ent & Savenije 2011), set by the local E/P, not by
# distance from the coast.  A fixed-point iteration couples E_land to the local
# precipitation via the Budyko reciprocal form E = E_pot·P/(E_pot+P).
_LAND_RECYCLING_MAX_ITER: int = 12
_LAND_RECYCLING_RELAX: float = 0.5
_LAND_RECYCLING_TOL_MM: float = 1.0  # max |ΔE| over land cells (mm/yr)


def _solve_moisture_budget(
    mesh: CVTMesh,
    wind: np.ndarray,
    is_ocean: np.ndarray,
    temperature_c: np.ndarray,
    nodes_xyz: np.ndarray,
    config: TerrainPipelineConfig,
    rainout_enhancement: np.ndarray | None = None,
    diffusivity_enhancement: np.ndarray | None = None,
    edge_table: tuple[np.ndarray, np.ndarray] | None = None,
    land_evapotranspiration: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Solve the steady upwind advection–decay moisture budget for column water.

    The mass-conserving hydrological cycle (Held & Soden 2006: P − E = −∇·(W u))
    in its rainout form,

        ∇·(W u) + W/τ = E ,   P = W/τ

    is discretised with a first-order upwind finite-volume scheme on the CVT
    graph and solved for the column-water field W (mm).  The upwind flux across
    each edge carries the *upwind* cell's W, so the resulting linear system is a
    diagonally-dominant M-matrix (the rainout W/τ provides strict dominance).

    Because the advection flux terms cancel globally (Σ ∇·(Wu) = 0), the total
    precipitation equals the total evaporation *by construction* — global water
    mass is conserved with no calibration constant.

    Args:
        mesh: CVT mesh (adjacency + cell areas).
        wind: Surface wind vectors (m/s), shape (N, 3).
        is_ocean: Boolean ocean mask, shape (N,).
        temperature_c: Temperature (°C), shape (N,), for the evaporation source.
        nodes_xyz: Unit sphere node positions, shape (N, 3).
        config: Pipeline configuration.
        rainout_enhancement: Optional dimensionless field (shape N, > −1) that
            scales the rainout rate spatially: k_rain = (1/τ)·(1 + enhancement).
            ``None`` → uniform τ.  ΣP = ΣE holds for any enhancement field, so
            the storm track / convection become mass-conserving modulations
            rather than additive precipitation sources.
        diffusivity_enhancement: Optional dimensionless field (shape N, > −1)
            that scales the eddy diffusivity spatially: κ = κ₀·(1 + enhancement).
            ``None`` → uniform κ₀.  Models the baroclinic eddies' poleward
            moisture mixing (larger in the storm track); the finite-volume flux
            uses the edge-averaged κ so the term stays symmetric.
        land_evapotranspiration: Optional fixed land evapotranspiration field
            (mm/yr), shape (N,).  The Budyko water-limitation curve
            E = E_pot·P/(E_pot+P) is an *annual* water-balance relation; the
            monthly solves must not re-apply it per month (that underestimates
            land ET by Jensen's inequality).  The annual solve runs the fixed
            point and hands the converged field to the monthly solves here.
            ``None`` → run the internal Budyko fixed point (annual path).
        edge_table: Optional pre-built directed edge table (src, dst).  The
            monthly budget solves call this 12 times; building the table once
            upstream saves a Python loop per month.

    The land evapotranspiration source is water-limited by the Budyko recycling
    feedback (see ``_LAND_RECYCLING_*`` constants): E_land = E_pot·P/(E_pot+P),
    solved as a fixed point by re-solving the RHS against the (constant) matrix
    A — wet land evaporates near its potential, dry land evaporates only the
    rain that falls.

    Returns:
        (W, P): column water (mm) and rainout precipitation (mm/yr), shape (N,).
    """
    n = mesh.num_cells
    s_per_year = 365.25 * 86400.0
    tau_yr = _MOISTURE_RESIDENCE_DAYS / 365.25
    k_rain = 1.0 / tau_yr  # base rainout rate [1/yr]
    if rainout_enhancement is not None:
        k_rain_field = k_rain * (1.0 + rainout_enhancement)
    else:
        k_rain_field = np.full(n, k_rain)

    # Evaporation source E (mm/yr): energy-limited ocean evaporation + land
    # evapotranspiration (see _LAND_EVAPOTRANSPIRATION_FRACTION).  The monthly
    # solves receive a pre-converged land ET field (Budyko is an annual
    # relation — see ``land_evapotranspiration``); the annual solve iterates
    # the fixed point itself.
    is_land = ~is_ocean
    e_ocean = evaporation_rate(temperature_c, is_ocean, config.evaporation_base_mm)
    if land_evapotranspiration is not None:
        e = np.where(is_land, land_evapotranspiration, e_ocean)
    else:
        e_land_init = evaporation_rate(
            temperature_c,
            is_land,
            config.evaporation_base_mm * _LAND_EVAPOTRANSPIRATION_FRACTION,
        )
        e = np.where(is_land, e_land_init, e_ocean)

    # Directed edge table (reuse the flat (src, dst) convention).  Monthly
    # budget loops solve this 12 times — build the table once upstream and pass
    # it in via ``edge_table``.
    if edge_table is not None:
        src, dst = edge_table
    else:
        from dreamulator.map.ocean_circulation import _build_directed_edge_table

        src, dst = _build_directed_edge_table(mesh.cells)

    # Smooth the wind over the graph: large-scale moisture transport responds to
    # the large-scale wind, not the noisy local field.  Near the equator the
    # geostrophic component is degenerate (1/f) and the terrain blocking adds
    # per-cell jumps; without smoothing these concentrate the ITCZ into a single
    # spurious cell-wide spike.  A few Jacobi passes damp the small-scale noise
    # while preserving the Hadley/ferrel structure (and the solver below stays
    # conservative for any wind field).
    _wdeg = np.bincount(src, minlength=n).astype(np.float64)
    _wdeg = np.maximum(_wdeg, 1.0)
    for _ in range(40):
        _wsum = np.zeros_like(wind)
        np.add.at(_wsum, src, wind[dst])
        wind = 0.5 * wind + 0.5 * (_wsum / _wdeg[:, None])

    # Outward tangent unit vector from src → dst, and great-circle edge length.
    edge_vec = nodes_xyz[dst] - nodes_xyz[src]
    radial = np.einsum("ij,ij->i", edge_vec, nodes_xyz[src])
    edge_vec = edge_vec - radial[:, None] * nodes_xyz[src]
    en = np.linalg.norm(edge_vec, axis=1)
    valid = en > 1e-9
    edge_dir = np.zeros_like(edge_vec)
    edge_dir[valid] = edge_vec[valid] / en[valid, None]
    dot = np.clip(np.einsum("ij,ij->i", nodes_xyz[src], nodes_xyz[dst]), -1.0, 1.0)
    l_m = config.radius_km * 1000.0 * np.arccos(dot)

    # Outward wind component across the edge (m/s): positive = outflow from src.
    # Use the edge-averaged wind so the two directed edges of each neighbour pair
    # carry equal-and-opposite fluxes — with a per-cell wind the upwind scheme
    # would not be conservative (mass balance breaks where the wind varies).
    u_out = np.einsum("ij,ij->i", 0.5 * (wind[src] + wind[dst]), edge_dir)

    area_m2 = np.array([c.area_km2 for c in mesh.cells], dtype=np.float64) * 1e6

    # Upwind advection coefficient c = u_out · l / A · s_per_year  [1/yr].
    c = u_out * l_m / area_m2[src] * s_per_year

    # Assemble the M-matrix A:  A W = e.
    #   diagonal  A[i,i] = k + Σ_{outflow} c  (> 0)
    #   off-diag  A[i,j] = c  for inflow edges (c < 0)
    #
    # A is not always strictly diagonally dominant — in the ITCZ the surface
    # convergence (∇·u < 0) can add more inflow than the rainout k offsets,
    # which makes Jacobi/GMRES stall.  But A = kI + L_upwind is non-singular:
    # the first-order upwind scheme's numerical dissipation keeps the real part
    # of every eigenvalue ≥ k > 0.  A direct sparse LU solve is therefore both
    # robust and exact; the CVT graph is ~6-connected so fill-in stays bounded.
    pos = c > 0.0
    neg = c < 0.0
    # Add a turbulent-diffusion term κ∇²W alongside the upwind advection.  The
    # pure upwind scheme concentrates the ITCZ into a single spurious cell-wide
    # spike at the equator, because the ~1° CVT mesh cannot resolve the
    # Hadley-cell wind reversal and the finite-volume divergence is ~100× too
    # strong.  Real moisture transport is advection + turbulent mixing; κ ≈
    # 1e6 m²/s (atmospheric eddy diffusivity) spreads the spike to the observed
    # ~10° rain belt (diffusion length √(κτ) ≈ 900 km) and makes A more
    # diagonally dominant.  Finite-volume flux form (coefficient κ/A_i, flux
    # κ(W_i−W_j) per edge) so the term stays exactly conservative on the
    # non-uniform CVT mesh, matching the area-weighted advection.
    if diffusivity_enhancement is not None:
        kappa = _MOISTURE_DIFFUSIVITY_M2S * (1.0 + diffusivity_enhancement)
    else:
        kappa = np.full(n, _MOISTURE_DIFFUSIVITY_M2S)
    kappa_edge = 0.5 * (kappa[src] + kappa[dst])  # edge-averaged (symmetric)
    _diff_edge = kappa_edge * s_per_year / area_m2[src]  # 1/yr, per directed edge
    diag = k_rain_field.copy()
    np.add.at(diag, src[pos], c[pos])
    np.add.at(diag, src, _diff_edge)  # diffusion: +κ_edge/A_src per neighbour
    row = np.concatenate([np.arange(n), src[neg], src])
    col = np.concatenate([np.arange(n), dst[neg], dst])
    val = np.concatenate([diag, c[neg], -_diff_edge])
    a = sparse.coo_matrix((val, (row, col)), shape=(n, n)).tocsr()

    from scipy.sparse.linalg import splu

    lu = splu(a.tocsc())

    # Budyko land-recycling fixed point (see the module-level constants).  The
    # matrix A is independent of the evaporation source E, so factor once and
    # iterate only the RHS solve: E_land = E_pot·P/(E_pot+P) couples the land
    # evapotranspiration to the local precipitation — wet land evaporates near
    # its potential, dry land evaporates nearly nothing (water-limited).
    # Skipped when a converged annual land-ET field is supplied (monthly path).
    if land_evapotranspiration is None and _LAND_RECYCLING_MAX_ITER > 0:
        _e_pot_land = evaporation_rate(temperature_c, is_land, config.evaporation_base_mm)
        _e_land = e_land_init
        for _ in range(_LAND_RECYCLING_MAX_ITER):
            w = lu.solve(e)
            w = np.maximum(w, 0.0)
            p = w * k_rain_field
            _e_new = _e_pot_land * p / (_e_pot_land + p + 1e-9)
            _delta = float(np.max(np.abs(_e_new - _e_land)))
            _e_land = _LAND_RECYCLING_RELAX * _e_new + (1.0 - _LAND_RECYCLING_RELAX) * _e_land
            e = np.where(is_land, _e_land, e_ocean)
            if _delta < _LAND_RECYCLING_TOL_MM:
                break

    w = lu.solve(e)

    # Clamp against numerical under/overshoot (W ≥ 0), then P = W/τ.
    w = np.maximum(w, 0.0)
    p = w * k_rain_field
    return w, p


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


def _baroclinic_band(
    temperature_c: np.ndarray,
    lat_deg: np.ndarray,
    band_deg: float = 5.0,
    min_lat_deg: float = 20.0,
) -> tuple[float, float]:
    """Centre and half-width (degrees) of the baroclinic storm-track band.

    Transient eddies grow where the meridional temperature gradient is
    steepest (Eady instability follows ∇T), so the band is derived from the
    zonal-mean temperature profile rather than from circulation-cell
    boundaries.  Cell boundaries degenerate for single-cell slow rotators —
    yet GCMs of slow rotators show weakened-but-nonzero eddy activity, with
    the baroclinic zone at the mid-to-high-latitude gradient maximum of the
    broad temperature profile (Held–Hou quartic: gradient ∝ sin³φ·cosφ,
    peak near 50–60°).

    Args:
        temperature_c: Annual-mean temperature field (°C), shape (N,).
        lat_deg: Latitude in degrees, shape (N,).
        band_deg: Latitude bin width for the zonal mean.
        min_lat_deg: Ignore gradients equatorward of this (ITCZ region).

    Returns:
        (centre_latitude, gaussian_half_width); falls back to the classic
        (45°, 15°) when the profile is too flat to locate a peak.
    """
    abs_lat = np.abs(lat_deg)
    edges = np.arange(0.0, 90.0 + band_deg, band_deg)
    centers = 0.5 * (edges[:-1] + edges[1:])
    idx = np.clip(((abs_lat - edges[0]) / band_deg).astype(np.int64), 0, len(centers) - 1)
    sums = np.zeros(len(centers))
    counts = np.zeros(len(centers))
    np.add.at(sums, idx, temperature_c)
    np.add.at(counts, idx, 1.0)
    if (counts < 1).any():
        return 45.0, 15.0  # incomplete latitudinal coverage — classic fallback
    t_zonal = sums / counts

    grad = np.abs(np.gradient(t_zonal, band_deg))
    # Smooth bin noise (twice-over 3-point kernel ≈ Gaussian σ≈1 bin).
    kernel = np.array([0.25, 0.5, 0.25])
    for _ in range(2):
        grad = np.convolve(grad, kernel, mode="same")

    search = centers >= min_lat_deg
    if not search.any() or grad[search].max() < 0.05:
        return 45.0, 15.0  # flat profile (no baroclinicity) — fallback
    peak = int(np.argmax(np.where(search, grad, 0.0)))
    centre = float(centers[peak])
    half_max = 0.5 * grad[peak]
    # Walk outward from the peak to the half-max crossings (equatorward and
    # poleward) and convert the full width at half maximum to a Gaussian σ.
    left = peak
    while left > 0 and grad[left - 1] >= half_max:
        left -= 1
    right = peak
    while right < len(grad) - 1 and grad[right + 1] >= half_max:
        right += 1
    fwhm = float(centers[right] - centers[left])
    width = float(np.clip(fwhm / 2.355, 5.0, 20.0))
    return centre, width


def _compute_precipitation_monthly_budget(
    mesh: CVTMesh,
    wind: np.ndarray,
    wind_monthly: np.ndarray,
    is_land: np.ndarray,
    is_ocean: np.ndarray,
    elevation_m: np.ndarray,
    temperature_c: np.ndarray,
    t_monthly_c: np.ndarray,
    nodes_xyz: np.ndarray,
    config: TerrainPipelineConfig,
    itcz_lat_monthly: np.ndarray | None = None,
    debug: dict[str, np.ndarray] | None = None,
    edge_table: tuple[np.ndarray, np.ndarray] | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Precipitation from the monthly mass-conserving moisture budget.

    Each month's wind (annual background + monsoon anomaly) and that month's
    temperature-dependent evaporation drive a steady moisture budget
    (``_solve_moisture_budget``): ∇·(W u) + k_rain(x)·W − ∇·(κ∇W) = E,
    P = k_rain(x)·W.  Monthly precipitation is P_m/12, annual the sum over
    months; mass is conserved per month (ΣP = ΣE), hence also annually.
    Monsoon seasonality, ITCZ migration, and evaporation seasonality all enter
    through the monthly wind and temperature fields — the former ITCZ-Gaussian
    redistribution factor and the ×1.5/×1.3 tropical-coastal monsoon gain are
    gone (tech debt 23).

    On top of each month's budget precipitation: orographic rain from that
    month's column water and wind, then the mechanisms that do not vary by
    month in this model — west/east-coast asymmetry (annual cell circulation),
    Föhn rain shadow (latitude-regime based), sub-planet convective
    enhancement (steady on a locked body) — and finally the annual cap applied
    to the monthly values proportionally.

    Args:
        mesh: CVT mesh.
        wind: Annual background wind field, shape (N, 3).
        wind_monthly: Monthly winds (background + monsoon anomaly), shape
            (12, N, 3).
        is_land: Boolean land mask, shape (N,).
        is_ocean: Boolean ocean mask, shape (N,).
        elevation_m: Elevation in metres, shape (N,).
        temperature_c: Annual-mean temperature in °C, shape (N,).
        t_monthly_c: Monthly temperature in °C, shape (N, 12).
        nodes_xyz: Unit sphere node positions, shape (N, 3).
        config: Pipeline configuration.
        itcz_lat_monthly: ITCZ latitude per month (degrees), shape (12,).
            The west/east-coast asymmetry evaluates the cell circulation
            averaged over these positions, the same annual-mean wind the
            background field contains.
        debug: Optional dict collecting diagnostic fields (mm/yr).
        edge_table: Optional pre-built directed edge table (src, dst), shared
            with the Stage 2 wiring.

    Returns:
        (p_annual_mm shape (N,), p_monthly_mm shape (N, 12)).
    """
    n = mesh.num_cells
    lat_rad = np.radians(np.array([c.lat for c in mesh.cells], dtype=np.float64))
    lon_rad = np.radians(np.array([c.lon for c in mesh.cells], dtype=np.float64))
    lat_deg = np.degrees(lat_rad)

    # Directed edge table built once, shared by the 12 budget solves and the
    # orographic step.
    if edge_table is not None:
        src, dst = edge_table
    else:
        from dreamulator.map.ocean_circulation import _build_directed_edge_table

        src, dst = _build_directed_edge_table(mesh.cells)

    edge_vec = nodes_xyz[dst] - nodes_xyz[src]
    radial = np.einsum("ij,ij->i", edge_vec, nodes_xyz[src])
    edge_vec = edge_vec - radial[:, None] * nodes_xyz[src]
    edge_norm = np.linalg.norm(edge_vec, axis=1)
    valid_edge = edge_norm >= 1e-9
    edge_dir = np.zeros_like(edge_vec)
    edge_dir[valid_edge] = edge_vec[valid_edge] / edge_norm[valid_edge, None]

    # Step 3.5: Mid-latitude storm tracks (baroclinic eddies) — a spatial
    # modulation of the rainout rate k_rain, NOT an additive precipitation
    # source (Held & Soden 2006).  The band is derived from the zonal-mean
    # temperature gradient (``_baroclinic_band``); the amplitude scales with
    # the Eady growth rate (∇T × Ω^0.3) and the available moisture.  Annual
    # fields — the band's seasonal excursion is a second-order effect here.
    _lat_grad = (
        lat_gradient_from_omega(
            config.rotation_period_days,
            earth_gradient_c=config.lat_gradient_earth_c,
        )
        if config.auto_lat_gradient
        else config.lat_gradient_c
    )
    _storm_center, _storm_width = _baroclinic_band(temperature_c, lat_deg)
    _storm_amp = (
        config.storm_track_amplitude_mm
        * (_lat_grad / 45.0)
        * (1.0 / config.rotation_period_days) ** 0.3
        * (config.evaporation_base_mm / 1000.0)
    )
    _storm_enhance = (_storm_amp / config.evaporation_base_mm) * np.exp(
        -0.5 * ((np.abs(lat_deg) - _storm_center) / _storm_width) ** 2
    )
    # The same baroclinic eddies also transport moisture poleward (transient-
    # eddy mixing): eddy-diffusivity enhancement ∝ rainout enhancement.
    _eddy_enhance = config.storm_track_kappa_enhancement * _storm_enhance

    # Deep-tropics rainout floor (Amazon/Congo interior analogue), annual —
    # the permanent heating of the deep tropics does not vary by month here.
    _tropical_land = is_land & (np.abs(lat_deg) < 15.0) & (temperature_c > 20.0)
    _boost_enhance = np.zeros(n, dtype=np.float64)
    _boost_enhance[_tropical_land] = (
        1200.0 - 500.0 * (np.abs(lat_deg[_tropical_land]) / 15.0)
    ) / config.evaporation_base_mm

    _k_base = 365.25 / _MOISTURE_RESIDENCE_DAYS  # base rainout rate, 1/yr

    # Annual solve first: the Budyko recycling curve E = E_pot·P/(E_pot+P) is
    # an annual water-balance relation, and its fixed point converges against
    # the annual P.  Re-applying it inside each monthly solve would depress
    # land evapotranspiration by Jensen's inequality (concave in P), starving
    # the land recycling loop.  Converge it once here and hand the annual
    # water limitation to the monthly solves.
    _conv_annual = np.where(
        is_land,
        30.0 * np.maximum(temperature_c - 10.0, 0.0) / config.evaporation_base_mm,
        0.0,
    )
    _, p_ann = _solve_moisture_budget(
        mesh,
        wind,
        is_ocean,
        temperature_c,
        nodes_xyz,
        config,
        rainout_enhancement=_storm_enhance + _conv_annual + _boost_enhance,
        diffusivity_enhancement=_eddy_enhance,
        edge_table=(src, dst),
    )
    # Converged land ET re-extracted from the annual P (the fixed point ended
    # within 1 mm/yr of this relation).
    _e_pot_ann = evaporation_rate(temperature_c, is_land, config.evaporation_base_mm)
    _e_land_ann = _e_pot_ann * p_ann / (_e_pot_ann + p_ann + 1e-9)

    p_monthly = np.zeros((n, 12), dtype=np.float64)
    _dbg_storm = np.zeros(n)
    _dbg_conv = np.zeros(n)
    _dbg_boost = np.zeros(n)

    for m in range(12):
        t_m = t_monthly_c[:, m]
        # Local convection (afternoon thunderstorms over warm land) is a
        # temperature-driven rainout efficiency — monthly with t_m.
        _conv_enhance_m = np.where(
            is_land,
            30.0 * np.maximum(t_m - 10.0, 0.0) / config.evaporation_base_mm,
            0.0,
        )
        # Monthly land ET: energy limitation from that month's temperature,
        # water limitation from the annual precipitation (soil moisture
        # integrates the annual water input, not a single month's).
        _e_pot_m = evaporation_rate(t_m, is_land, config.evaporation_base_mm)
        _e_land_m = _e_pot_m * p_ann / (_e_pot_m + p_ann + 1e-9)
        w_m, p_m = _solve_moisture_budget(
            mesh,
            wind_monthly[m],
            is_ocean,
            t_m,
            nodes_xyz,
            config,
            rainout_enhancement=_storm_enhance + _conv_enhance_m + _boost_enhance,
            diffusivity_enhancement=_eddy_enhance,
            edge_table=(src, dst),
            land_evapotranspiration=_e_land_m,
        )

        # Orographic rain from this month's column water: upwind elevation gain
        # along this month's wind rains out a fraction of W per km of uplift.
        _speed_m = np.linalg.norm(wind_monthly[m], axis=1)
        _wind_unit_m = wind_monthly[m] / np.maximum(_speed_m, 1e-9)[:, None]
        align_m = np.where(valid_edge, np.einsum("ij,ij->i", edge_dir, _wind_unit_m[src]), -1.0)
        gain_e = elevation_m[dst] - elevation_m[src]
        ok = (gain_e > 0.0) & (align_m > 0.1)
        up_gain = np.zeros(n, dtype=np.float64)
        np.maximum.at(up_gain, dst[ok], gain_e[ok])
        # Column water of the edge carrying the maximum gain into each cell.
        is_max = ok & (gain_e == up_gain[dst])
        up_w = np.zeros(n, dtype=np.float64)
        np.maximum.at(up_w, dst[is_max], w_m[src[is_max]])

        oro_m = np.zeros(n, dtype=np.float64)
        q_mask = is_land & (up_w > 0.5) & (up_gain > 0.0)
        frac = np.minimum(0.20 * up_gain[q_mask] / 1000.0, 0.9)
        oro_m[q_mask] = up_w[q_mask] * frac

        p_monthly[:, m] = (p_m + oro_m) / 12.0

        _dbg_storm += (w_m * _k_base * _storm_enhance) / 12.0
        _dbg_conv += (w_m * _k_base * _conv_enhance_m) / 12.0
        _dbg_boost += (w_m * _k_base * _boost_enhance) / 12.0

    if debug is not None:
        debug["moisture_budget"] = p_monthly.sum(axis=1).copy()
        debug["storm"] = _dbg_storm
        debug["convection"] = _dbg_conv
        debug["tropical_boost"] = _dbg_boost

    # Step 6.6: West-coast / east-coast asymmetry (annual cell circulation —
    # the seasonality of the westerlies is not modelled yet, so the same
    # factor applies to every month).  Onshore winds carry ocean moisture →
    # coastal precipitation enhanced; offshore winds → suppressed.  The onshore
    # moisture flux is ρ_air × |U_zonal| × q_sat(T); a fraction ε of it
    # precipitates at the coast:
    #     f = 1 ± ε × ρ_air × |U| × q_sat(T) × s_per_year / P_bg
    if is_land.any():
        _coastal, _west_coast = _detect_coastal_cells(mesh.cells, n, is_land, is_ocean)
        _zwind = _seasonal_mean_cell_wind(lat_rad, nodes_xyz, config, itcz_lat_monthly)
        from dreamulator.map.ocean_circulation import east_north_basis as _enb2

        _east, _ = _enb2(nodes_xyz)
        _uzonal = np.einsum("ij,ij->i", _zwind, _east)

        _rho_air = 1.2  # kg/m³
        _s_per_year = 365.25 * 86400.0
        _p_bg = 1000.0  # mm/yr reference background precipitation
        _eps_windward = 1.3e-4  # coastal precipitation efficiency (windward)
        _eps_leeward = 0.8e-4  # coastal precipitation efficiency (leeward)

        _coastal_factor = np.ones(n, dtype=np.float64)
        for i in range(n):
            if not _coastal[i]:
                continue
            u_abs = abs(_uzonal[i])
            t_k = max(temperature_c[i] + 273.15, 230.0)
            e_sat = 611.2 * np.exp(17.67 * (t_k - 273.15) / (t_k - 29.65))  # Pa
            q_sat = 0.622 * e_sat / 101325.0  # kg/kg
            moisture_flux = _rho_air * u_abs * q_sat  # kg/m²/s
            delta_p = moisture_flux * _s_per_year  # mm/yr equivalent

            is_westerly = _uzonal[i] > 0
            windward = (is_westerly and _west_coast[i]) or (not is_westerly and not _west_coast[i])
            eps = _eps_windward if windward else _eps_leeward
            factor = 1.0 + eps * delta_p / _p_bg if windward else (1.0 - eps * delta_p / _p_bg)
            _coastal_factor[i] = np.clip(factor, 0.5, 1.5)
        p_monthly *= _coastal_factor[:, None]

    # Step 6.7: Föhn rain shadow — leeward drying from the moisture scale
    # height of the barrier the air crossed.  The wind regime (westerlies vs
    # trades) is latitude-based and steady through the year, so one factor
    # applies to every month.  BFS already handles windward orographic rain.
    if is_land.any():
        _westerly_rs = (np.abs(lat_deg) >= config.hadley_extent_deg) & (
            np.abs(lat_deg) < config.polar_cell_start_deg
        )
        _fohn_factor = np.ones(n, dtype=np.float64)
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
                _fohn_factor[i] = np.exp(-elev_drop / h_scale_m)
        p_monthly *= _fohn_factor[:, None]

    # Step 8: Sub-planet / sub-stellar convective enhancement — steady on a
    # tidally locked body, so it splits evenly across the 12 months.
    if config.sub_planet_warming_c > 0:
        sub_lat = np.radians(config.sub_planet_latitude_deg)
        sub_lon = np.radians(config.sub_planet_longitude_deg)
        cos_ang = np.sin(lat_rad) * np.sin(sub_lat) + np.cos(lat_rad) * np.cos(sub_lat) * np.cos(
            lon_rad - sub_lon
        )
        ang_dist_deg = np.degrees(np.arccos(np.clip(cos_ang, -1.0, 1.0)))
        amplitude = config.sub_planet_warming_c * 200.0  # mm/yr per °C
        sub_boost = amplitude * np.exp(-0.5 * (ang_dist_deg / 15.0) ** 2)
        if debug is not None:
            debug["sub_planet"] = sub_boost.copy()
        p_monthly += sub_boost[:, None] / 12.0

    # Annual cap (real-Earth maximum ~11000 mm/yr, Mawsynram/Cherrapunji),
    # applied to the monthly values proportionally so the seasonal shape is
    # preserved where the cap engages.
    p_annual = p_monthly.sum(axis=1)
    if debug is not None:
        debug["pre_cap"] = p_annual.copy()
    scale = np.where(p_annual > 11000.0, 11000.0 / np.maximum(p_annual, 1e-9), 1.0)
    p_monthly *= scale[:, None]
    p_annual = p_monthly.sum(axis=1)
    if debug is not None:
        debug["final"] = p_annual.copy()

    return p_annual, p_monthly
