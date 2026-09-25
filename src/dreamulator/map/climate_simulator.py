"""Climate simulation on the spherical CVT mesh.

Stage sequence — annual temperature (1D EBM or Held-Hou single-cell regime) +
seasonal EBM, monsoon pressure-anomaly wind field, Stommel ocean gyres + SST
advection, monthly mass-conserving moisture budget, Köppen classification.

Architecture reference: ``docs/design/pipelines/climate-pipeline.md``.

Physical constants and composable functions are in
``src/dreamulator/engine/climate_physics.py``.  This module orchestrates them
on the CVT mesh and writes results into `VoronoiCell` fields in-place.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np
from scipy import sparse

from dreamulator.engine.climate_physics import (
    SOLAR_CONSTANT,
    altitude_lapse_rate,
    cc_lift_drying_scale,
    column_water_saturation,
    convective_pickup_gate,
    coriolis_parameter,
    diffuse_heat_graph,
    equilibrium_temperature,
    evaporation_rate,
    hadley_cell_wind,
    hadley_extent_from_rotation,
    ice_albedo_feedback,
    koppen_classify,
    lat_gradient_from_omega,
    latitude_temperature,
    moist_lapse_rate,
    potential_evapotranspiration_hamon,
    soil_bucket_monthly,
    spectral_ice_albedo,
    sst_convection_gate,
    subsidence_aridity_gate,
    subsidence_rainout_gate,
    surface_temperature,
    terrain_wind_blocking,
)
from dreamulator.engine.climate_seasonality import (
    apply_eddy_relaxation,
    compute_seasonal_climate,
    eddy_diffusion_single_cell,
    radiative_equilibrium_contrast,
    seasonal_heat_capacity,
    seasonal_precip_extremes,
    solve_1d_ebm_temperature,
    solve_held_hou_temperature,
    warm_cold_half_precip,
)
from dreamulator.engine.monsoon_circulation import (
    _DRAG_RATE_LAND_S,
    _DRAG_RATE_S,
    cross_equatorial_monsoon_wind,
    monsoon_boundary_layer_wind,
    pressure_anomaly_monthly,
)

if TYPE_CHECKING:
    from .models import CVTMesh, VoronoiCell
    from .pipeline_types import TerrainPipelineConfig

import time as _time

from rich.console import Console as _Console

_console = _Console()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

# Convergence tolerance for temperature-pressure iteration (unused for now)
_CONV_TOL: float = 0.01

# Minimum wind speed magnitude to be considered "blowing" (m/s)
_MIN_WIND_SPEED: float = 0.1

# Convergence-sentinel multiplier (CLIM-02 slice 5): per-cell annual
# precipitation cap = α · k_rain(cell) · W_sat(T_cell) — the local saturated
# column's maximum annual rainout, times a convergence multiplier.  α = 8
# anchors the order of the strongest terrestrial orographic funnels
# (Cherrapunji/Mawsynram receive ~5-10× their local column processing;
# observation-fitted class, discipline #9).  World-independent and
# temperature-adaptive — replaces the former fixed 11000 mm/yr clip (a
# real-Earth *station* record: an arbitrary ceiling for alien worlds, astra
# rethinking §2.1).  Numerical-stabilisation class closure: it clips the
# slice-1 per-edge orographic over-concentration artifact (steep tropical
# terrain reached ~10× Earth records pre-sentinel; known limitation, to be
# revisited with the stage-D supply-route work) — loudly, via logger.warning,
# never silently.
_P_CONVERGENCE_SENTINEL_ALPHA: float = 8.0


def _convergence_sentinel(
    temperature_c: np.ndarray,
    k_rain_field: np.ndarray,
    alpha: float = _P_CONVERGENCE_SENTINEL_ALPHA,
) -> np.ndarray:
    """Per-cell annual precipitation sentinel: α · k_rain · W_sat_eff, mm/yr.

    The saturated column rained out at the cell's full modulated rainout rate
    gives the maximum annual precipitation the *local* column processing can
    support; α allows for advective convergence (orographic funnels
    concentrate several times the local supply — Cherrapunji/Mawsynram run at
    ~5-7× theirs, so α = 8 passes real extremes).

    ``W_sat_eff = W_sat(max(T, 0 °C))``: below freezing the sentinel floors at
    the 0 °C saturated column (~1.6 m/yr at base k).  A pure local-column
    limit would falsely starve cold cells whose precipitation is *advectively*
    supplied by warmer upwind air (Antarctic/Greenland coasts receive
    200-800 mm/yr at local W_sat of only ~0.3-2 mm) — the 0 °C floor proxies
    that warm-air supply without per-cell flux bookkeeping.

    Net effect: cold highland artifact cells (slice-1 per-edge
    over-concentration, ~10× Earth records) are clipped hard, warm lowland
    physical extremes pass, and polar advective regimes are never bitten.
    """
    t_eff = np.maximum(np.asarray(temperature_c, dtype=np.float64), 0.0)
    w_sat_eff = np.asarray(column_water_saturation(t_eff), dtype=np.float64)
    return alpha * np.asarray(k_rain_field, dtype=np.float64) * w_sat_eff


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
    # Inland lakes that are ocean-like in size (Caspian, Great Lakes, nacrea's
    # endorheic seas) are ``water_class == "ocean"`` but *not* the open ocean:
    # they are continental water bodies that equilibrate with the overlying air,
    # not a deep maritime heat reservoir.  Stage 1 gives them the land (EBM)
    # temperature + the land heat capacity + a 0 °C freeze clamp, instead of the
    # open-ocean SST profile.
    is_lake = np.array([c.is_lake for c in mesh.cells], dtype=bool)
    is_lake_ocean = is_lake & is_ocean

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

    # P3 (2026-09-16): Hadley-cell extent.  ``hadley_extent_deg = 0`` means
    # "derive" — the Held-Hou thermal-Rossby scaling φ_H ≈ R_t^(1/2) with Δ_H
    # from the model's own radiative-equilibrium contrast (same insolation
    # geometry as the EBM).  An explicit config value pins it (escape hatch
    # for the GCM-evidenced global-cell regime — nacrea's PoC mass
    # streamfunction is single-signed to the pole where the axisymmetric
    # formula only reaches ~60°; see hadley_extent_from_rotation).
    if config.hadley_extent_deg > 0.0:
        hadley_extent_deg = config.hadley_extent_deg
    else:
        _delta_h = radiative_equilibrium_contrast(
            t_surf_C,
            albedo=config.albedo,
            obliquity_deg=config.axial_tilt_deg,
            solar_constant=solar_const,
            orbital_period_days=config.orbital_period_days,
            eccentricity=config.eccentricity,
            perihelion_day=config.perihelion_day,
        )
        hadley_extent_deg = hadley_extent_from_rotation(
            _delta_h,
            radius_km=config.radius_km,
            gravity_m_s2=config.gravity_m_s2,
            rotation_period_days=config.rotation_period_days,
        )
        _console.print(
            f"    [dim]hadley extent derived: {hadley_extent_deg:.1f} deg"
            f" (Δ_H={_delta_h:.3f})[/dim]"
        )
    # Anti-overlap clamp: the polar cell cannot start inside the Hadley cell.
    polar_cell_start_deg = max(config.polar_cell_start_deg, hadley_extent_deg)

    # Archived 4.2 subsidence-warming increment (°C), released over humid land
    # by the Stage 3.5 aridity gate (subsidence_aridity_gate).  Stays zero for
    # single-cell worlds (nacrea) and when subsidence_warming_c = 0.
    _dt_subsidence = np.zeros(n)

    if config.ebm_1d:
        # ── 1D EBM (North 1975 / climlab.EBM) — formal steady-state solve ──
        # 0 = D d/dx[(1−x²)dT/dx] + Q(x)(1−α) − (A + B·T),  x = sin(φ), replaces
        # the sin² latitude profile + 3-pass graph diffusion.  The ocean is
        # overwritten by ``_ocean_surface_temperature`` below, so this solve
        # gives the LAND temperature.  Two regimes (energy_balance.md §3):
        if hadley_extent_deg >= 90.0:
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
            # E1 (2026-09-16): eddy heat transport on top of the overturning.
            # Held-Hou is the axisymmetric (eddy-free) limit; the slow-rotation
            # eddy residual — weakened but nonzero, ~50% of Earth's eddy peak at
            # nacrea's Ω = 0.318 (Kaspi & Showman 2015 Fig. 8b) — further
            # flattens the profile toward the global mean.  Same (B, D, n(n+1))
            # machinery as the EBM branch, with the eddy-only D.  The ocean is
            # overwritten by the SST profile below; this acts on the land field.
            t_mean_C = apply_eddy_relaxation(
                t_mean_C,
                lat_rad,
                olr_b_wm2k=config.ebm_olr_b_wm2k,
                eddy_diffusion_wm2k=eddy_diffusion_single_cell(
                    config.rotation_period_days, config.ebm_diffusion_land_wm2k
                ),
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
            # ── 4.2: Held-Hou subsidence warming (subtropical desert) ──
            # The diffusive EBM's meridional transport is purely down-gradient,
            # so it cools the subtropics by diffusing heat poleward; the real
            # Hadley cell instead warms them by subsidence — its overturning
            # homogenises the tropics-subtropics (Held & Hou 1980).  Relax land
            # toward the cell's area-weighted mean (the equal-area constraint),
            # tapering across the cell edge (~8°-wide descent band).  Land-only
            # — the ocean is overwritten by the SST profile below.  (The
            # single-Hadley-cell branch above already has flat subtropics, and
            # the legacy sin² path below is a separate, unmaintained model.)
            if config.subsidence_warming_c > 0.0:
                phi_h = np.radians(hadley_extent_deg)
                _cell = np.abs(lat_rad) < phi_h
                t_cell = float(np.average(t_mean_C[_cell], weights=np.cos(lat_rad[_cell])))
                _edge = np.radians(8.0)  # Ferrel/Hadley boundary transition width
                _w = np.clip((phi_h + _edge - np.abs(lat_rad)) / _edge, 0.0, 1.0)
                # Archive the increment — the Stage 3.5 aridity gate releases
                # it over humid land (4.2-①): subsidence warming physically
                # belongs to the dry descending branch only.
                _dt_subsidence[land_mask_arr] = (
                    config.subsidence_warming_c
                    * _w[land_mask_arr]
                    * (t_cell - t_mean_C[land_mask_arr])
                )
                t_mean_C[land_mask_arr] += _dt_subsidence[land_mask_arr]
            # (4.2-①: the homogenisation above is aridity-gated at Stage 3.5 —
            #  ``subsidence_aridity_gate``, knots on the Köppen BW/BS and
            #  arid/humid boundaries, no new tunable.  The dry-side radiative-
            #  balance term (+~2 °C over deserts) needs the T↔P fixed point:
            #  proposals/climate-steady-coupling.md.)
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

    # E2 (2026-09-16): archive the ice-albedo increment for the baroclinic
    # band.  The feedback is a *response* to the climate, not a radiative
    # forcing — letting its sharpened gradient (the 58-72° ice edge on nacrea)
    # steer the storm band is a positive coupling the single-pass annual chain
    # cannot equilibrate.  The precipitation budget feeds ``_baroclinic_band``
    # the ice-free field instead (land cells only — the ocean is overwritten by
    # the SST profile below, so its archived increment is stale by then).
    _t_pre_ice = t_mean_C.copy()

    # ── 3A.3: ice-albedo feedback ──
    if config.ice_albedo_feedback:
        t_mean_C = ice_albedo_feedback(
            t_mean_C,
            max_cooling_c=config.ice_albedo_max_cooling_c,
            ice_threshold_c=config.ice_albedo_threshold_c,
        )
    _t_ice_increment = t_mean_C - _t_pre_ice

    # Ocean surface temperature: damped latitude gradient (maritime moderation)
    # anchored to the planet's global-mean surface temperature (Earth profile
    # at Earth forcing; shifts 1:1 with stellar forcing / greenhouse changes)
    _land_t = t_mean_C.copy()  # land EBM temperature (before the SST override)
    t_mean_C[~land_mask_arr] = _ocean_surface_temperature(
        lat_rad[~land_mask_arr],
        t_surf_C,
        config,
        solar_const=solar_const,
    )
    # Inland lakes split by their annual-mean land temperature:
    #  - seasonal-ice lakes (annual land T ≥ 0) keep the land temperature —
    #    a freshwater lake equilibrates with the continental air, so the Great
    #    Lakes sit ~0 °C in winter, not the +12 °C the latitude profile gives;
    #  - permanent-ice lakes (annual land T < 0) keep the open-ocean SST
    #    override — the sea-ice surface is already the correct frozen surface.
    #
    # NOTE: the annual mean is a first-order proxy for "does the lake melt in
    # summer" (the exact criterion is summer T > 0).  They differ only for a
    # lake whose annual mean hugs 0 °C — but every lake large enough to be
    # ocean-like (≥ 6e4 km²) sits far from freezing on the current Earth/nacrea
    # meshes, so the proxy is safe.  Lower the lake-area threshold and it must
    # be re-derived from the summer temperature.
    _seasonal_lake = is_lake_ocean & (_land_t >= 0.0)
    t_mean_C[_seasonal_lake] = _land_t[_seasonal_lake]

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

    # Directional annual maritime advection (4.1-B annual): relax the annual-mean
    # land temperature toward its *upwind* ocean's SST, decaying over the maritime
    # air-mass e-folding length (the classical advection-mixing ω — Berg 1944).
    # The prevailing westerlies carry the ocean's warmth inland, warming the
    # mid-lat continents.  Gated to non-ice land so the polar ice sheets are not
    # warmed toward the cold polar ocean.  Applied before the lapse rate.
    if config.maritime_advection_scale_km > 0.0:
        _wind_ann = terrain_wind_blocking(
            _seasonal_mean_cell_wind(
                lat_rad,
                nodes_xyz,
                config,
                None,
                hadley_extent_deg=hadley_extent_deg,
                polar_cell_start_deg=polar_cell_start_deg,
            ),
            elevation_m,
            config.wind_blocking_height_m,
        )
        # `_wind_ann` is already physical (root unification, 2026-09-13).
        _dist_up_ann, _src_up_ann = _upwind_distance_to_coast(
            mesh.cells, n, is_land, _wind_ann, nodes_xyz, radius_km=config.radius_km
        )
        _valid_ann = is_land & (_src_up_ann >= 0)
        _w_up_ann = np.where(
            _valid_ann, np.exp(-_dist_up_ann / config.maritime_advection_scale_km), 0.0
        )
        # Ice gate: exclude the polar ice sheets (annual mean < −10 °C) — relaxing
        # them toward the cold polar ocean would warm the ice surface.
        _non_ice_ann = is_land & (t_mean_C > -10.0)
        _t_src_ann = np.where(_valid_ann, t_mean_C[np.maximum(_src_up_ann, 0)], 0.0)
        t_mean_C += _w_up_ann * (_t_src_ann - t_mean_C) * _non_ice_ann

    # Altitude correction (land only — ocean surface is at 0 m regardless of
    # depth).  The surface lapse rate is temperature-dependent (moist
    # adiabatic: warm air → latent heat release → shallower Γ) — tropical
    # highlands cool ~4.7 °C/km, polar ice sheets ~6.5 °C/km.  This replaces
    # both the constant 6.5 and the former hard [15°, 35°] subtropical band
    # (removed 2026-09-11): the station-implied effective lapse splits along
    # temperature, not latitude, and the band edges printed artificial step
    # lines across Tibet/Andes/Rockies.
    lapse: float | np.ndarray = config.lapse_rate_c_km
    if config.variable_lapse_rate:
        lapse = moist_lapse_rate(t_mean_C[land_mask_arr])
    # The lapse rate is an atmospheric cooling-with-altitude effect and only
    # applies *above* sea level.  Below-sea-level "land" cells (Antarctic ice
    # whose stored elevation is the bedrock, below-sea-level endorheic basins,
    # and island cells whose centre samples the surrounding shelf) must not be
    # *warmed* by extrapolating Γ below h = 0 — that turns a −2.9 km ocean-floor
    # sample into a spurious +19 °C hot spot.  Clamp to sea level.
    _elev_above_sea = np.maximum(elevation_m[land_mask_arr], 0.0)
    t_mean_C[land_mask_arr] = altitude_lapse_rate(
        t_mean_C[land_mask_arr],
        _elev_above_sea,
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
    # Seasonal-ice lakes are continental water bodies, not a 50 m maritime mixed
    # layer: they take the lake heat capacity (a ~10 m epilimnion — continental
    # amplitude, moderated by the water's inertia), then the 0 °C freeze clamp
    # below caps the winter surface.
    heat_capacity[_seasonal_lake] = config.seasonal_lake_heat_capacity
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
        # E1: Ω-scale the seasonal damping exactly like the annual EBM caller
        # (D ∝ P^0.3 = Ω^−0.3 — bigger cells smear anomalies meridionally
        # faster).  Earth (P = 1 d) is unchanged.
        diffusion_wm2k=config.ebm_diffusion_wm2k * config.rotation_period_days**0.3,
        albedo=config.albedo,
        ice_albedo=spectral_ice_albedo(
            config.stellar_temperature_k,
            ice_albedo_visible=config.ice_albedo_surface,
        ),
        ice_threshold_c=config.seasonal_ice_threshold_c,
        ice_albedo_feedback=config.seasonal_ice_albedo,
    )
    t_monthly_C = seasonal["T_monthly"]
    itcz_lat_monthly = seasonal["itcz_lat"]

    # ── B0c handoff (2026-09-13): anchor the monthly series to the
    # calibrated annual field.  The seasonal EBM solves its own
    # radiative/heat-capacity cycle and has no elevation dimension, so
    # highland cells sat at their sea-level-equivalent latitude temperature
    # (Andes 4 km: ⟨t_m⟩ +16 °C vs t_mean −3.3; Greenland 3 km: −11 vs −30)
    # — poisoning t_hot/t_cold → Köppen (only 9% of >4.5 km cells classified
    # E), monthly evaporation and the monthly display layer.  Keep the EBM's
    # seasonal *shape/amplitude*, take the *level* from the Stage-1 annual
    # field (lapse, subsidence gate, coastal moderation, advection, SST).
    # This is the one place where the annual chain sets the monthly level:
    # downstream the monthly series is the authority, and the exported annual
    # field is re-derived from it at the terminal aggregation (slice 6):
    t_monthly_C = t_monthly_C + (t_mean_C - t_monthly_C.mean(axis=1))[:, None]
    # Uniform per-cell shift ⇒ min/max re-derivation is the exact transform.
    t_cold_C = t_monthly_C.min(axis=1)
    t_hot_C = t_monthly_C.max(axis=1)

    # Freshwater lakes freeze at 0 °C: the winter surface sits at the freezing
    # point (the ice caps the radiative heat loss) rather than following the
    # land's sub-zero cycle.  A physical constant, not an Earth calibration.
    if _seasonal_lake.any():
        t_monthly_C[_seasonal_lake] = np.maximum(t_monthly_C[_seasonal_lake], 0.0)
        t_cold_C[_seasonal_lake] = np.maximum(t_cold_C[_seasonal_lake], 0.0)

    # ------------------------------------------------------------------
    # Stage 2: Wind
    phase_timings["temperature"] = _time.time() - _t0
    _console.print(f"  [green]done[/green] [dim]({phase_timings['temperature']:.1f}s)[/dim]")
    _t0 = _time.time()
    _console.print("  [dim]2/6  Wind field (Hadley cells + monsoon)[/dim]")
    # ------------------------------------------------------------------
    # Directed edge table + neighbour-averaging operator, built once here and
    # shared by the monsoon-DP synoptic smoothing below.
    from dreamulator.map.ocean_circulation import _build_directed_edge_table

    _msrc, _mdst = _build_directed_edge_table(mesh.cells)
    _cell_km = 2.0 * config.radius_km * np.sqrt(np.pi / n)
    _mdeg = np.maximum(np.bincount(_msrc, minlength=n).astype(np.float64), 1.0)
    _avg = sparse.csr_matrix(
        (1.0 / _mdeg[_msrc], (_msrc, _mdst)),
        shape=(n, n),
    )
    # Scale-separation smoothing passes for the mosaic-noise scale (~175 km —
    # see the constant's note): each Jacobi pass is a lazy random-walk step
    # (σ = √(passes/2)·cell_km).
    _n_smooth = 2 * int((_MONSOON_PRESSURE_SMOOTHING_KM / _cell_km) ** 2)
    _radius_m = config.radius_km * 1000.0
    f_coriolis = coriolis_parameter(lat_rad, config.rotation_period_days)

    # Large-scale surface wind = the three-cell circulation (Hadley / Ferrel /
    # Polar) — the model's complete zonal wind field (trades, mid-latitude
    # westerlies, polar easterlies).  Cell boundaries are planet parameters
    # (3A.3a: slow rotators get an expanded Hadley cell); the circulation
    # follows the migrating ITCZ (roadmap 20 ①).  A separate geostrophic
    # (thermal) wind component was removed: the model has no dynamical
    # subtropical high, so its θ-based thermal wind is easterly at every
    # latitude and only weakens the Ferrel westerlies, while the raw surface
    # pressure gradient (barometric exp(−h/H)) adds ~30 m/s of topographic
    # noise over land that swamps the coherent flow.  The three-cell wind
    # alone gives coherent ~3–4 m/s westerlies at 30–60°.
    wind = _seasonal_mean_cell_wind(
        lat_rad,
        nodes_xyz,
        config,
        itcz_lat_monthly,
        hadley_extent_deg=hadley_extent_deg,
        polar_cell_start_deg=polar_cell_start_deg,
    )
    # ④ pass-2 needs the pure three-cell background (below, `wind` gets
    # reassigned to the monthly mean = background + monsoon anomaly).
    _wind_bg = wind

    # ── Monsoon wind (tech debt 23; M4/B0b 2026-09-14) ──
    # Continents thermally contrasted against the same-latitude ocean (full
    # monthly value, annual mean included) → thermal lows/highs; the boundary-
    # layer wind answers the pressure gradient against Coriolis and drag
    # (engine/monsoon_circulation.py).  Near the equator f → 0 and the flow goes
    # straight down-gradient — the cross-equatorial monsoon current.  The
    # monthly thermal component is added onto the three-cell background, giving
    # 12 monthly winds that drive the monthly moisture budget in Stage 3 and
    # whose vector mean is the annual wind (with its stationary structure).
    # Raw (unsmoothed) field kept for ④: the stationary-wave ΔSLP is added
    # *before* smoothing so both components get the same scale separation.
    # B4: the per-cell lapse field for the ΔP airmass decomposition — the
    # SAME Γ the temperature stage applied (moist_lapse_rate on land; the
    # config default elsewhere — ocean cells sit at z=0 and contribute
    # nothing), so ΔT + Γ·z exactly undoes the engine's altitude cooling.
    _lapse_by_cell = np.full(len(lat_deg), float(config.lapse_rate_c_km))
    if config.variable_lapse_rate:
        _lapse_by_cell[land_mask_arr] = np.asarray(lapse)
    _dp_hpa_raw = pressure_anomaly_monthly(
        t_monthly_C,
        lat_deg,
        surface_pressure_hpa=config.surface_pressure_hpa,
        elevation_m=elevation_m,
        ocean_mask=is_ocean,  # B2: land-vs-same-latitude-ocean contrast
        lapse_rate_c_per_km=_lapse_by_cell,
    )
    _dp_hpa = _dp_hpa_raw
    # Scale separation before differentiation: the anomaly field inherits the
    # cell-level land-ocean mosaic (~51 km at 200k cells), whose coastline
    # jumps dominate the raw gradient and drive sea-breeze-scale winds far
    # stronger than any monsoon.  The smoothing target is that mosaic scale —
    # ~175 km (a few cells) kills it while keeping the maintained thermal
    # lows (1000–2500 km wide) and their inflow channels; see the constant's
    # note for why the earlier 500 km Rossby-radius rationale was misapplied
    # to a forced (not freely adjusting) anomaly field.
    _dp_hpa = _smooth_graph(_dp_hpa, _avg, _n_smooth)

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

    # Monthly wind = annual background + cross-equatorial westerly + monsoon
    # anomaly (the annual field is then *derived* from these — see below).  The
    # monthly migration of the circulation cells is part of the monthly-vector
    # winds work (tech debt 24): tested here, giving each month its own
    # ITCZ-shifted circulation sharpened the convergence band into a sweeping
    # rain belt that over-seasoned the subtropics (Csa/Dsb inflation) and
    # overshot land-mean precipitation, so v1 keeps the calibrated annual-mean
    # circulation as the advecting field and lets the anomaly carry the seasonal
    # land-sea reversal.  The cross-equatorial westerly (D/F 子项 2, 2026-09-14)
    # is the one seasonal cell term kept *monthly*: within the cross-equatorial
    # belt it *replaces* the background zonal wind with the westerly — restoring
    # the Somali-jet / Guinea-westerly moisture route without moving the
    # meridional convergence structure (the tech-debt-24 sweeping rain belt
    # stays retired; the meridional branch and the monsoon-trough poleward shift
    # were falsified this round, see proposal §5).
    _itcz_max = float(np.max(np.abs(itcz_lat_monthly)))
    _sw_wind = np.stack(
        [
            cross_equatorial_monsoon_wind(
                lat_rad,
                nodes_xyz,
                float(itcz_lat_monthly[m]),
                config.radius_km,
                config.rotation_period_days,
                _itcz_max,
                wind,
            )
            for m in range(12)
        ]
    )
    wind_monthly = np.stack([wind + _sw_wind[m] + _wind_monsoon[m] for m in range(12)])

    # Terrain blocking on each monthly field (a per-cell scalar scaling of the
    # wind vector — linear, so the mean identity below is exact).
    wind_monthly = np.stack(
        [
            terrain_wind_blocking(wind_monthly[m], elevation_m, config.wind_blocking_height_m)
            for m in range(12)
        ]
    )

    # Annual-mean wind = vector mean of the (blocked) monthly fields — the
    # observational definition itself (NCEP annual climatology is the vector
    # mean of the monthly winds).  Tech-debt-24 data contract (2026-09-13):
    # the monthly field is primary, the annual one derived, so the identity
    # holds by construction — and since B0b (2026-09-14) the full-value
    # monthly ΔP makes that average carry the stationary land-sea structure
    # (winter Siberian high ≫ summer thermal lows).  Every annual consumer
    # (cell storage, the Stommel chain via wind_mirror, 4.1-B advection, the
    # annual moisture budget, the coast asymmetry step) reads this single
    # source.
    wind = wind_monthly.mean(axis=0)

    # Write wind to cells for frontend visualisation
    from dreamulator.map.ocean_circulation import (
        decompose_tangent as _dec_wind,
    )
    from dreamulator.map.ocean_circulation import (
        east_north_basis as _enb_wind,
    )

    # `wind` is in the physical convention (tech debt 24 root unification,
    # 2026-09-13: `hadley_cell_wind` now composes on the true east basis), so
    # the decomposition maps 1:1 onto the stored/frontend/NCEP convention —
    # the former `_we = -_we` compensating flip is gone.
    _east_w, _north_w = _enb_wind(nodes_xyz)
    _we, _wn = _dec_wind(wind, _east_w, _north_w)
    for i, c in enumerate(mesh.cells):
        c.wind_east_m_s = float(_we[i])
        c.wind_north_m_s = float(_wn[i])

    # ── 4.1-B: directional maritime moderation (anomaly form) ──
    # Relax each land cell's seasonal *anomaly* toward its upwind ocean's
    # anomaly, decaying over the maritime air-mass e-folding length.  The
    # upwind ocean is traced against the *physical* annual wind — the
    # prevailing westerlies carry the ocean's small-amplitude seasonal cycle
    # inland, so this warms the deep continental winter (Moscow-type) while
    # the ocean's own small amplitude keeps the summer cooling mild.  The
    # annual *level* is set by the Stage-1 4.1-B twin (ice-gated, pre-lapse),
    # and the anomaly form preserves it exactly, so the terminal aggregation
    # composes without double-counting the moderation.  This is the "smart
    # explicit preset" for the missing zonal maritime advection (SotE-style
    # directional continentality), not a wind coupling: the annual circulation
    # is a fixed advecting field, and the relaxation is one-pass (the monsoon
    # above already used the unrelaxed temperature).  The remaining East Asian
    # over-warm (Harbin) is the missing winter monsoon (tech debt 24).
    if config.maritime_advection_scale_km > 0.0:
        # `wind` is already in the physical convention (tech debt 24 root
        # unification, 2026-09-13) — the former `-we·east + wn·north` flip
        # recipe here is gone.
        _dist_up, _src_up = _upwind_distance_to_coast(
            mesh.cells, n, is_land, wind, nodes_xyz, radius_km=config.radius_km
        )
        _valid_up = is_land & (_src_up >= 0)
        _w_up = np.where(_valid_up, np.exp(-_dist_up / config.maritime_advection_scale_km), 0.0)
        # Anomaly-form relaxation (twin reconciliation, 2026-09-19): blend the
        # land *seasonal anomaly* toward the upwind ocean's anomaly instead of
        # pulling the monthly level toward the ocean's monthly level.  Setting
        # the annual level is Stage-1 4.1-B's job (ice-gated, applied before
        # the lapse rate); a level pull here applies the same moderation a
        # second time, and the terminal aggregation then pushes the double-
        # count into the exported annual field (measured: mid-lat Dfb→Cfb /
        # BSk→Dfa flips on Earth; nacrea polar coast +34 °C).  The anomaly
        # form is mean-preserving by construction — both anomaly series
        # average to zero over the year — so it keeps the shape effects
        # (Moscow-type winter warming, the Arctic maritime-tundra summer
        # cooling that anchors t_hot < 10 °C / ET, highland amplitude damping)
        # without moving the annual level.
        _src_idx = np.maximum(_src_up, 0)
        _ann = t_monthly_C.mean(axis=1)  # ocean sources are never modified below
        for _m in range(12):
            _src_anom = t_monthly_C[_src_idx, _m] - _ann[_src_idx]
            _land_anom = t_monthly_C[:, _m] - _ann
            t_monthly_C[:, _m] = np.where(
                _valid_up,
                _ann + (1.0 - _w_up) * _land_anom + _w_up * _src_anom,
                t_monthly_C[:, _m],
            )
        t_cold_C = t_monthly_C.min(axis=1)
        t_hot_C = t_monthly_C.max(axis=1)

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
            apply_subgrid_wbc_boost,
            apply_upwelling_sst_correction,
            compute_curl_z,
            compute_upwelling_index,
            compute_wind_stress,
            detect_ocean_basins,
            east_north_basis,
            solve_ocean_gyre,
        )

        east, north = east_north_basis(nodes_xyz)
        # The Stommel chain (stress → curl → gyre), the upwelling index and
        # the ocean→land anomaly advection below were all *calibrated* on the
        # legacy mirrored wind (verified outputs: Gulf Stream / Kuroshio /
        # Canary signs).  The root unification (2026-09-13) made `wind`
        # physical, so these consumers get its mirror image — a reflection
        # about the east axis — instead of a re-derivation of the chain.
        # Historical lesson: flipping a calibrated chain at its root cascades
        # into every downstream sign.
        # Audit §2.6: τ = ρC_D|u|u is nonlinear — the annual stress is the
        # time-mean of monthly stress, not the stress of the annual-mean wind
        # (|mean(u)|² ≤ mean(|u|²), so seasonal wind reversals are under-stressed
        # by the annual-mean field).  Compute monthly stress, then aggregate.
        _wind_monthly_mirror = _to_physical_wind(wind_monthly, east)
        tau = np.mean(
            [
                compute_wind_stress(_wind_monthly_mirror[m], c_d=config.ocean_drag_coefficient)
                for m in range(12)
            ],
            axis=0,
        )
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
                # E4 (2026-09-16): sub-grid WBC jet — restore the analytic
                # jet speed ψ_max/(R/β) in the western-intensification core,
                # which the ~51 km graph Laplacian smears out (observed WBC
                # 100–250 cm/s vs resolved ~1 cm/s).  Feeds the SST advection
                # (longitudinal anomaly structure) and the stored currents.
                vel = apply_subgrid_wbc_boost(psi, vel, beta[b_cells], bottom_friction_s=R)
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
                # CLIM-01 (2026-09-18): the SST advection shifts the ocean's
                # annual-mean SST; shift the monthly series by the same
                # increment so the monthly evaporation / SST-gate consumers in
                # Stage 3 see the same level (⟨t_monthly⟩ ≡ t_mean_C at every
                # synced stage; the terminal aggregation then re-derives the
                # annual field from the monthly one — slice 6).
                _dt_sst = sst_corrected - t_mean_C
                t_mean_C = sst_corrected  # feeds into stage 3 (BFS evaporation) + stage 4 (Köppen)
                t_monthly_C = t_monthly_C + _dt_sst[:, None]
                # Write per-cell ocean fields
                for li, gi in enumerate(b_cells):
                    c = mesh.cells[gi]
                    c.ocean_current_east_m_s = float(np.dot(vel[li], east[gi]))
                    c.ocean_current_north_m_s = float(np.dot(vel[li], north[gi]))
                    c.sst_anomaly_c = float(sst_anom[gi])

            # ── 3A.3: upwelling → SST cooling ──
            if config.ocean_upwelling_enabled:
                # 月度为来源 (audit §2.6): compute_upwelling_index applies a ReLU
                # (max(0, equatorward wind)) — nonlinear — so the annual index is the
                # time-mean of monthly indices, not the ReLU of the annual wind (which
                # kills the seasonal equatorward signal in reversing-wind regions).
                _upw = np.mean(
                    [
                        compute_upwelling_index(
                            _wind_monthly_mirror[m],
                            mesh.cells,
                            nodes_xyz,
                            east,
                            north,
                            lat_rad,
                        )
                        for m in range(12)
                    ],
                    axis=0,
                )
                _dt_upw = apply_upwelling_sst_correction(_upw, t_mean_C) - t_mean_C
                t_mean_C = t_mean_C + _dt_upw
                t_monthly_C = t_monthly_C + _dt_upw[:, None]  # CLIM-01: keep ⟨t_monthly⟩ ≡ t_mean_C
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
        # 月度为来源 (audit §2.6): wind_unit = wind/|wind| and |wind| are both
        # nonlinear — the annual direction is the time-mean of the monthly unit
        # directions, and the annual speed is the time-mean of the monthly |wind|.
        _wind_speed_m = np.linalg.norm(_wind_monthly_mirror, axis=2)
        _wind_dir = (_wind_monthly_mirror / np.maximum(_wind_speed_m, 1e-9)[:, :, None]).mean(
            axis=0
        )
        _wind_speed = _wind_speed_m.mean(axis=0)
        _temp_anom = advect_temperature_anomaly(
            _sst_anom,
            _wind_dir,
            _wind_speed,
            is_ocean,
            mesh.cells,
            nodes_xyz,
            radius_m=_radius_m,
            diffusivity=config.ocean_temperature_diffusivity,
        )
        # CLIM-01: land-only increment, applied to both the annual and monthly
        # fields so Stage 3's monthly evaporation / SST-gate see it too.
        _dt_adv = np.where(is_land, _temp_anom, 0.0)
        t_mean_C = t_mean_C + _dt_adv
        t_monthly_C = t_monthly_C + _dt_adv[:, None]

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
        temperature_c=t_mean_C,
        t_monthly_c=t_monthly_C,
        nodes_xyz=nodes_xyz,
        config=config,
        itcz_lat_monthly=itcz_lat_monthly,
        debug=debug,
        edge_table=(_msrc, _mdst),
        ice_increment_c=_t_ice_increment,
    )

    # ── ④ Stationary-wave response (roadmap ④): two-pass fixed point ──
    # Pass-1 precipitation is the latent-heating source: P → column latent
    # heat → mid-level ω → upper-level divergence D → RWS → steady linear
    # barotropic ψ' (map/stationary_wave.py).  ΔSLP_wave = ρ·f·ψ' rides on
    # the *raw* monsoon ΔP field; the existing smoothing → gradient →
    # boundary-layer-wind chain consumes it, giving the wind field its
    # longitudinal structure (subtropical ridge west of monsoon heating —
    # the desert-maintenance mechanism, Rodwell & Hoskins 2001).  Then the
    # moisture budget re-runs on the updated winds.  Under-relaxed between
    # passes (config); the mechanism is a negative feedback (ridge → drying
    # → less heating), residual logged for monitoring.  v1 scope: the ocean
    # chain keeps pass-1 winds (Stommel/SST not re-run) and 4.1-B maritime
    # advection keeps the pre-wave wind field.
    if (
        int(config.stationary_wave_enabled)
        + int(config.stationary_wave_v2_enabled)
        + int(config.wet_trough_enabled)
        > 1
    ):
        raise ValueError(
            "stationary_wave_enabled / stationary_wave_v2_enabled / "
            "wet_trough_enabled are mutually exclusive (one closure per round; "
            "the wet trough and a future ④ v2 gate can compose off the same "
            "two-mode solve if both survive acceptance)"
        )
    if config.convective_pickup_gate_enabled and not config.wet_trough_enabled:
        raise ValueError(
            "convective_pickup_gate_enabled requires wet_trough_enabled: the "
            "gate knots are calibrated on the post-supply-fix W regime "
            "(climate_physics._PICKUP_GATE_KNOTS_* comment — calibration "
            "domain). On the unfixed W field everything collocates at "
            "x≈0.16-0.18 and the ramp strangles the monsoon lands (the "
            "2026-09-17 acceptance failure; round-2 G_only arm reproduced it)."
        )
    if config.stationary_wave_enabled:
        from dreamulator.map.stationary_wave import compute_slp_wave_anomaly

        _lon_deg = np.array([c.lon for c in mesh.cells], dtype=np.float64)
        _areas_km2 = np.array([c.area_km2 for c in mesh.cells], dtype=np.float64)
        # pass-1 逐月风的切向分量 (n, 12)：2D 基本态的地表项（含季风异常
        # 的经度结构——TEJ 型局域东风由此进入热成风修正）。`wind_monthly`
        # 此刻仍是 pass-1 场（下方 wave 消费后才重赋值为 pass-2）。
        _u_e = np.einsum("mck,ck->cm", wind_monthly, _east_w)
        _v_e = np.einsum("mck,ck->cm", wind_monthly, _north_w)
        _wave = compute_slp_wave_anomaly(
            p_monthly_mm=p_monthly,
            t_monthly_c=t_monthly_C,
            elevation_m=elevation_m,
            cell_lat_deg=lat_deg,
            cell_lon_deg=_lon_deg,
            cell_area_km2=_areas_km2,
            wind_east_monthly=_u_e,
            wind_north_monthly=_v_e,
            surface_pressure_hpa=config.surface_pressure_hpa,
            rotation_period_days=config.rotation_period_days,
            radius_km=config.radius_km,
            orbital_period_days=config.orbital_period_days,
            damping_days=config.stationary_wave_damping_days,
        )
        _clip_frac = float((np.abs(_wave.dp_hpa) >= 7.999).mean())
        _dp_wave = _wave.dp_hpa * config.stationary_wave_relaxation
        _console.print(
            f"    [dim]stationary wave (④): ΔSLP {_dp_wave.min():.1f}.."
            f"{_dp_wave.max():.1f} hPa (capped {_clip_frac * 100:.1f}%)[/dim]"
        )
        _dp2 = _smooth_graph(_dp_hpa_raw + _dp_wave, _avg, _n_smooth)
        _grad2 = np.stack(
            [
                _graph_least_squares_gradient(mesh, _dp2[:, m], nodes_xyz) * 100.0 / _radius_m
                for m in range(12)
            ]
        )
        _wind_monsoon2 = monsoon_boundary_layer_wind(
            _grad2, f_coriolis, nodes_xyz, drag_rate_s=_drag
        )
        wind_monthly = np.stack([_wind_bg + _sw_wind[m] + _wind_monsoon2[m] for m in range(12)])
        wind_monthly = np.stack(
            [
                terrain_wind_blocking(wind_monthly[m], elevation_m, config.wind_blocking_height_m)
                for m in range(12)
            ]
        )
        wind = wind_monthly.mean(axis=0)
        # Stored (frontend/validation) winds must reflect the wave-updated
        # annual mean — the wind-R² acceptance metric reads these fields.
        _we2, _wn2 = _dec_wind(wind, _east_w, _north_w)
        for _i, _c in enumerate(mesh.cells):
            _c.wind_east_m_s = float(_we2[_i])
            _c.wind_north_m_s = float(_wn2[_i])

        _p_pass1 = p_monthly
        precipitation_mm, p_monthly = _compute_precipitation_monthly_budget(
            mesh=mesh,
            wind=wind,
            wind_monthly=wind_monthly,
            is_land=is_land,
            is_ocean=is_ocean,
            temperature_c=t_mean_C,
            t_monthly_c=t_monthly_C,
            nodes_xyz=nodes_xyz,
            config=config,
            itcz_lat_monthly=itcz_lat_monthly,
            debug=debug,
            edge_table=(_msrc, _mdst),
            ice_increment_c=_t_ice_increment,
        )
        _resid = float(np.abs(p_monthly - _p_pass1).mean())
        _console.print(f"    [dim]wave two-pass |P₂−P₁| mean {_resid:.1f} mm[/dim]")
        if debug is not None:
            debug["dp_wave_hpa"] = _wave.dp_hpa
            debug["wave_psi"] = _wave.psi
            debug["wave_ubar"] = _wave.ubar
            debug["wave_vbar"] = _wave.vbar
            debug["wave_div_grid"] = _wave.div_grid
            debug["wave_p_resid_mm"] = np.array(_resid)

    # ── ④ v2 two-level Gill response: ω̂ → land subsidence-drying gate ──
    # Pass-1 precipitation is the latent-heating source: P → Q̇ → (zonal-mean
    # basic state) two-mode steady linear solve (map/stationary_wave_two_level.
    # py, Lee-Wang-Mapes 2009) → mid-level w.  Consumption is the R&H
    # subsidence-drying gate — a multiplicative k_rain modulation on LAND
    # (mass-conserving, composed with the storm/SST gates) — NOT the v1
    # ΔSLP→BL-wind path: the wind fields stay pass-1 (no _dp2/gradient/BL
    # rebuild, no 1/f amplification; wind-R² acceptance untouched).  The
    # moisture budget re-runs with the gate only; residual logged.
    elif config.stationary_wave_v2_enabled:
        from dreamulator.map.stationary_wave_two_level import compute_omega_wave_anomaly

        _lon_deg = np.array([c.lon for c in mesh.cells], dtype=np.float64)
        _areas_km2 = np.array([c.area_km2 for c in mesh.cells], dtype=np.float64)
        # pass-1 逐月风的切向分量 (n, 12)：纬向平均基本态的低层项。
        _u_e = np.einsum("mck,ck->cm", wind_monthly, _east_w)
        _v_e = np.einsum("mck,ck->cm", wind_monthly, _north_w)
        _wave2 = compute_omega_wave_anomaly(
            p_monthly_mm=p_monthly,
            t_monthly_c=t_monthly_C,
            elevation_m=elevation_m,
            cell_lat_deg=lat_deg,
            cell_lon_deg=_lon_deg,
            cell_area_km2=_areas_km2,
            wind_east_monthly=_u_e,
            wind_north_monthly=_v_e,
            surface_pressure_hpa=config.surface_pressure_hpa,
            rotation_period_days=config.rotation_period_days,
            radius_km=config.radius_km,
            orbital_period_days=config.orbital_period_days,
        )
        _gate_omega = subsidence_rainout_gate(_wave2.w_mid_m_s, is_land)
        _supp = float((_gate_omega < 0.9)[is_land].mean()) if is_land.any() else 0.0
        _console.print(
            f"    [dim]stationary wave v2 (④): w_mid {_wave2.w_mid_m_s.min():.2e}.."
            f"{_wave2.w_mid_m_s.max():.2e} m/s, gate f<0.9 on {_supp * 100:.1f}% land[/dim]"
        )
        _p_pass1 = p_monthly
        precipitation_mm, p_monthly = _compute_precipitation_monthly_budget(
            mesh=mesh,
            wind=wind,
            wind_monthly=wind_monthly,
            is_land=is_land,
            is_ocean=is_ocean,
            temperature_c=t_mean_C,
            t_monthly_c=t_monthly_C,
            nodes_xyz=nodes_xyz,
            config=config,
            itcz_lat_monthly=itcz_lat_monthly,
            debug=debug,
            edge_table=(_msrc, _mdst),
            ice_increment_c=_t_ice_increment,
            omega_gate_monthly=_gate_omega,
        )
        _resid = float(np.abs(p_monthly - _p_pass1).mean())
        _console.print(f"    [dim]wave v2 two-pass |P₂−P₁| mean {_resid:.1f} mm[/dim]")
        if debug is not None:
            debug["wave2_w_mid"] = _wave2.w_mid_m_s
            debug["omega_gate"] = _gate_omega
            debug["wave2_psi"] = _wave2.psi
            debug["wave2_psi_hat"] = _wave2.psi_hat
            debug["wave2_phi_hat"] = _wave2.phi_hat
            debug["wave2_u_baro"] = _wave2.u_baro
            debug["wave2_u_shear"] = _wave2.u_shear
            debug["wave2_p_resid_mm"] = np.array(_resid)

    # ── Wet monsoon-trough SLP closure (W-supply route round 1, 2026-09-24) ──
    # P → Q = L_v·P (land AND ocean — the prescribed-ΔP intervention's H4:
    # the ocean-side stationary structure is load-bearing for the routing) →
    # two-mode solve → φ̂ → δp_s_wet = c·φ̂ (hydrostatic mapping, all
    # constants — wet_trough_slp_anomaly) rides on the *raw* thermal ΔP;
    # the existing smoothing → gradient → BL-wind chain consumes it, and the
    # moisture budget re-runs on the updated winds.  The wet trough and the
    # precipitation it is derived from are one fixed point — damped Picard,
    # residual logged per pass.  v1 scope (same as ④): the ocean chain and
    # 4.1-B keep the pass-1 winds.  The Rossby placement (low NW of the
    # off-equatorial heating, Gill 1980) is what rotates the Ganges pressure
    # gradient onto the trough axis (the direction fix the wind-chain
    # decomposition attributed to the ΔP structure).  Amplitude expectations
    # from the same intervention: the machinery gain is ~2-3× (D_obs vs
    # D_half arms) — monsoon P may overshoot until the τ(W) governor round
    # recalibrates the pickup gate; routing metrics (W contrast, trough
    # winds) are this round's acceptance, not P amplitude.
    if config.wet_trough_enabled:
        from dreamulator.map.stationary_wave import DP_CAP_HPA
        from dreamulator.map.stationary_wave_two_level import wet_trough_slp_anomaly

        _lon_deg = np.array([c.lon for c in mesh.cells], dtype=np.float64)
        _areas_km2 = np.array([c.area_km2 for c in mesh.cells], dtype=np.float64)
        _u_e = np.einsum("mck,ck->cm", wind_monthly, _east_w)
        _wt_inc = np.zeros((n, 12), dtype=np.float64)  # accumulated wet increment
        _vlo_inc = np.zeros((n, 12, 3), dtype=np.float64)  # relaxed solver-wind state
        # ── Equatorial consumption blend (rounds 1/2 lesson, round-3 refined) ──
        # The boundary-layer closure misbehaves where the Coriolis term drops
        # below the surface drag: at f ≲ k_d the Ekman solution degenerates to
        # v = G/k_d and |v|/|G| = 1/√(k_d²+f²) on the tropical ocean exceeds
        # the mid-latitude land response by >10×, shredding the moisture field
        # (warm-pool runaway, rounds 1/2; the ④ v1 disease).  Inside that
        # degenerate band the wet response is consumed as the solver's own
        # lower-level wind (wave dynamics with bounded momentum damping r₁)
        # instead of the Ekman answer.  The boundary is the BL-degeneracy
        # latitude itself (a validity bound of the momentum balance, not a
        # heuristic radius — round 3's L_R waveguide was 2-4× too wide and
        # starved Guinea's cross-equatorial BL supply):
        #
        #     φ_d = arcsin(k_d,ocean / (2Ω))     Earth 3.9°, nacrea 12.4°
        #
        # world-generic through Ω; cosine taper φ_d → 2φ_d (a numerical
        # smoothness choice).  Ultra-slow rotators (k_d ≥ 2Ω) get φ_d = 90° —
        # the BL closure is degenerate everywhere and the solver wind takes
        # over globally, which is the physically honest limit.
        _omega_p = 2.0 * np.pi / (config.rotation_period_days * 86400.0)
        _phi_d_deg = np.degrees(np.arcsin(np.clip(_DRAG_RATE_S / (2.0 * _omega_p), 0.0, 1.0)))
        _lat_frac = np.abs(lat_deg) / _phi_d_deg
        _w_eq = 0.5 * (1.0 + np.cos(np.pi * np.clip(_lat_frac - 1.0, 0.0, 1.0)))
        # 1 at |lat| ≤ φ_d → 0 at ≥ 2φ_d, (n,)
        # ω-gate state carried out of the loop for the post-pass reporting and
        # debug dump (None when the gate is off — mypy narrows on the check).
        from dreamulator.map.stationary_wave_two_level import TwoLevelSolution

        _wt_omega_last: np.ndarray | None = None
        _wt_sol_last: TwoLevelSolution | None = None
        for _wt_pass in range(max(1, config.wet_trough_iterations)):
            _hweight = None
            if config.wet_trough_heating_weight == "pickup":
                # Deep-convective share of P (a subsaturated drizzling column
                # does not heat the free troposphere) — annual-mean W₀ from
                # the previous budget pass sets the gate (static weight).
                if debug is None or "w_column_final_mean" not in debug:
                    raise ValueError(
                        "wet_trough_heating_weight='pickup' requires the debug "
                        "dict (it reads the pass-1 column water W₀); pass "
                        "debug={} or use the default 'total' mode"
                    )
                _hweight = np.broadcast_to(
                    convective_pickup_gate(debug["w_column_final_mean"], t_mean_C)[:, None],
                    (n, 12),
                )
            elif config.wet_trough_heating_weight != "total":
                raise ValueError(
                    f"unknown wet_trough_heating_weight {config.wet_trough_heating_weight!r} "
                    "(expected 'total' or 'pickup')"
                )
            _dp_wet_new, _v_lower, _wt_sol = wet_trough_slp_anomaly(
                p_monthly_mm=np.maximum(p_monthly, 0.0),
                t_monthly_c=t_monthly_C,
                elevation_m=elevation_m,
                cell_lat_deg=lat_deg,
                cell_lon_deg=_lon_deg,
                cell_area_km2=_areas_km2,
                wind_east_monthly=_u_e,
                surface_pressure_hpa=config.surface_pressure_hpa,
                rotation_period_days=config.rotation_period_days,
                radius_km=config.radius_km,
                heating_weight=_hweight,
            )
            # Amplitude cap (round-4 verdict: the P→Q→ΔP→convergence→P loop has
            # a structural gain > 1 — the uncapped Picard sequence diverged to
            # −54 hPa, ~5× the deepest observed monsoon trough, and the pickup
            # gate cannot stabilise it because saturated columns get f≈1).
            # DP_CAP_HPA is the same guard ④ v1/v2 use: the NCEP stationary-eddy
            # SLP climatology bound, i.e. the validity domain of a *linear*
            # steady response — beyond it the solver's own premise is violated,
            # so clipping is a numerical-stabilisation statement, not a tuning
            # knob.  Clipped share is logged (v1 monitoring precedent).
            _clip_frac = float((np.abs(_dp_wet_new) >= DP_CAP_HPA * 0.999).mean())
            _dp_wet_new = np.clip(_dp_wet_new, -DP_CAP_HPA, DP_CAP_HPA)
            # ── Round 7: ω-gate composed off the SAME two-mode solve ──
            # The wet-trough solver already yields mid-level w for free; feed
            # it to the Rodwell–Hoskins subsidence-drying gate (mass-conserving
            # land k_rain suppression over the monsoon-heating west-side descent
            # tongue).  This is the ④ v2 registered upgrade path — one solve,
            # two consumptions (φ̂→ΔP_wet for routing, w→gate for the desert
            # flank).  Knots unchanged (conservative weak slope); the 2026-09-17
            # no-signal verdict was a forcing-self-reference artifact now broken
            # by the supply fix (see wet_trough_omega_gate_enabled comment).
            _wt_omega_gate = None
            if config.wet_trough_omega_gate_enabled:
                _wt_omega_gate = subsidence_rainout_gate(_wt_sol.w_mid_m_s, is_land)
                _wt_omega_last = _wt_omega_gate
                _wt_sol_last = _wt_sol

            _wt_inc = _wt_inc + config.wet_trough_relaxation * (_dp_wet_new - _wt_inc)
            # Wet increment split by the blend: the BL chain sees only the
            # extratropical share; the waveguide share rides as the solver's
            # lower-level wind (tangent 3D via the local east/north basis),
            # under the same Picard relaxation as the ΔP increment.  The wind
            # needs no cap of its own: the solver's momentum damping r₁ bounds
            # it (round-4 equatorial winds stayed physical while ΔP diverged).
            _vlo_new = (
                _v_lower[:, :, 0][:, :, None] * _east_w[:, None, :]
                + _v_lower[:, :, 1][:, :, None] * _north_w[:, None, :]
            )
            _vlo_inc += config.wet_trough_relaxation * (_vlo_new - _vlo_inc)
            _dp2 = _smooth_graph(_dp_hpa_raw + (1.0 - _w_eq)[:, None] * _wt_inc, _avg, _n_smooth)
            _grad2 = np.stack(
                [
                    _graph_least_squares_gradient(mesh, _dp2[:, m], nodes_xyz) * 100.0 / _radius_m
                    for m in range(12)
                ]
            )
            _wind_monsoon2 = monsoon_boundary_layer_wind(
                _grad2, f_coriolis, nodes_xyz, drag_rate_s=_drag
            )
            wind_monthly = np.stack(
                [
                    _wind_bg
                    + _sw_wind[m]
                    + _wind_monsoon2[m]
                    + (_w_eq[:, None] * _vlo_inc[:, m, :])
                    for m in range(12)
                ]
            )
            wind_monthly = np.stack(
                [
                    terrain_wind_blocking(
                        wind_monthly[m], elevation_m, config.wind_blocking_height_m
                    )
                    for m in range(12)
                ]
            )
            wind = wind_monthly.mean(axis=0)
            # The next solve's zonal basic state follows the updated winds
            # (the baroclinic response is basic-state insensitive per LWM09,
            # but consistency is free).
            _u_e = np.einsum("mck,ck->cm", wind_monthly, _east_w)
            _p_prev = p_monthly
            precipitation_mm, p_monthly = _compute_precipitation_monthly_budget(
                mesh=mesh,
                wind=wind,
                wind_monthly=wind_monthly,
                is_land=is_land,
                is_ocean=is_ocean,
                temperature_c=t_mean_C,
                t_monthly_c=t_monthly_C,
                nodes_xyz=nodes_xyz,
                config=config,
                itcz_lat_monthly=itcz_lat_monthly,
                debug=debug,
                edge_table=(_msrc, _mdst),
                ice_increment_c=_t_ice_increment,
                omega_gate_monthly=_wt_omega_gate,
            )
            _resid = float(np.abs(p_monthly - _p_prev).mean())
            _console.print(
                f"    [dim]wet trough pass {_wt_pass + 1}: "
                f"ΔP_wet {_wt_inc.min():.1f}..{_wt_inc.max():.1f} hPa "
                f"(capped {_clip_frac * 100:.2f}%), "
                f"|P_next−P_prev| mean {_resid:.1f} mm[/dim]"
            )
        # The stored ΔP and winds must reflect the wet-updated fields (the
        # writebacks below read _dp_hpa; the annual wind write was pass-1).
        # Same blend as the consumption above: inside the waveguide the wet
        # share is delivered by the solver wind, not by the ΔP field — the
        # stored/exported ΔP must not claim a pressure structure the wind
        # chain never saw (front-end/validation read this field).
        _dp_hpa = _smooth_graph(_dp_hpa_raw + (1.0 - _w_eq)[:, None] * _wt_inc, _avg, _n_smooth)
        _we2, _wn2 = _dec_wind(wind, _east_w, _north_w)
        for _i, _c in enumerate(mesh.cells):
            _c.wind_east_m_s = float(_we2[_i])
            _c.wind_north_m_s = float(_wn2[_i])
        if _wt_omega_last is not None:
            _supp = float((_wt_omega_last < 0.99)[is_land].mean()) if is_land.any() else 0.0
            _console.print(
                f"    [dim]wet-trough ω gate: f<0.99 on {_supp * 100:.1f}% land, "
                f"min {_wt_omega_last.min():.2f}[/dim]"
            )
            if debug is not None:
                debug["wt_omega_gate"] = _wt_omega_last
                assert _wt_sol_last is not None  # set together with the gate
                debug["wt_w_mid"] = _wt_sol_last.w_mid_m_s.copy()
        if debug is not None:
            debug["wet_trough_dp_hpa"] = _wt_inc.copy()

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

    # ── Stage 3.5: 4.2-① aridity-gated subsidence-warming release ──
    # Stage 1 archived the Held-Hou homogenisation increment on
    # _dt_subsidence; physically the warming belongs to the dry descending
    # branch — over humid subtropical margins it is offset by moist convection
    # and evaporative cooling.  Now that precipitation exists, release the
    # *warming* increment over humid lowland (both the Köppen ratio and the
    # UNEP P/PET_Hamon index must say humid; highlands ≥ 1.5 km always keep —
    # see subsidence_aridity_gate).  The negative (equatorial ascent-branch)
    # part of the homogenisation is moist-convective, not subsidence, and
    # stays.  A uniform shift preserves the seasonal amplitude and the
    # warm/cold-half month ordering, so the Köppen prep arrays above stay
    # valid.  Single-pass approximation: Stages 2-3 consumed the pre-release
    # temperature — the residual inconsistency the T↔P fixed point
    # (proposals/climate-steady-coupling.md) would remove.
    if _dt_subsidence.any():
        # PET on the *reference-year* basis (365.25/12 days per month) so that
        # AI = P/PET compares accumulations over the same window (M2-A0④):
        # p_annual is a rate per 365.25-day reference year; Hamon with the
        # orbital month would accumulate PET over the local year instead
        # (identical for Earth, ×3.65 too wet on nacrea's 100-day year).
        _pet_annual = potential_evapotranspiration_hamon(t_monthly_C, _DAYS_PER_REFERENCE_MONTH)
        _dt_undo = subsidence_aridity_gate(
            _dt_subsidence, p_annual, t_mean_C, p_warm_mm, p_cold_mm, _pet_annual, elevation_m
        )
        # Slice 6: the release acts on the monthly series only — the annual
        # field, t_cold/t_hot and the seasonal-lake freeze clamp are all
        # re-derived from it at the terminal aggregation, so no manual
        # bookkeeping is needed here.
        t_monthly_C -= _dt_undo[:, None]
        _n_released = int((_dt_undo > 0.01).sum())
        if _n_released:
            _console.print(
                f"  [dim]subsidence aridity gate: released {_n_released} humid "
                f"cells (max -{_dt_undo.max():.1f} C)[/dim]"
            )

    # ── Single temperature authority (slice 6, astra rethinking §2.2 target
    # architecture): the annual field is *derived* — the aggregation of the
    # monthly series — instead of prescribing the monthly mean the way the
    # retired B0c terminal re-centring did.  Downstream of the handoff, the
    # corrections either keep the two fields level-aligned (Stage 2.5 ocean,
    # Stage 3.5 subsidence release — CLIM-01) or act on the monthly series
    # alone (4.1-B directional maritime relaxation, the seasonal-lake freeze
    # clamp); the monthly-only physics now flows INTO the annual field rather
    # than being erased from the monthly one by a compensating shift.  The
    # lake clamp is applied *before* aggregating, so ⟨t_monthly⟩ ≡
    # temperature_C holds exactly for the exported pair — including lake
    # cells, where the old re-centre-then-clamp order broke it.  (The wind
    # export already works this way: identity by construction, monthly
    # primary.)
    if _seasonal_lake.any():
        t_monthly_C[_seasonal_lake] = np.maximum(t_monthly_C[_seasonal_lake], 0.0)
    t_mean_C = t_monthly_C.mean(axis=1)
    t_cold_C = t_monthly_C.min(axis=1)
    t_hot_C = t_monthly_C.max(axis=1)

    # Store the monthly climate arrays for the export stage (Phase 4 monthly
    # display).  These are *not* serialized to the mesh file — the full N×12
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
        # wind_monthly is physical (root unification) — store as decomposed;
        # the former east flip is gone.
        _we_m, _wn_m = _dec_wind(wind_monthly[_m], _east_w, _north_w)
        _we_monthly[:, _m] = _we_m
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
        # B0d (Kottek 2006): the b/c third letter counts months ≥ 10 °C —
        # meaningful now that the B0c contract makes t_monthly lapse-consistent.
        t_months_ge10=(t_monthly_C >= 10.0).sum(axis=1),
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
        # Annual-mean pressure anomaly (canonical ΔP's 12-month mean — M2-A0③):
        # the stationary land–sea contrast, so the frontend's annual pressure
        # layer works for engine-built worlds too (slp_annual_hpa is obs-only).
        mesh.cells[i].pressure_anomaly_annual_hpa = float(_dp_hpa[i].mean())
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


def _smooth_graph(
    field: np.ndarray,
    avg: sparse.csr_matrix,
    n_passes: int,
) -> np.ndarray:
    """Jacobi (neighbour-averaging) smoothing on the CVT graph.

    Each pass is a lazy random-walk step (σ = √(passes/2)·cell_spacing); the
    field is smoothed over the synoptic (Rossby-radius, ~500 km) scale before
    differentiation, removing the cell-level land-ocean mosaic / topographic
    noise that would otherwise dominate the gradient.  Used by the geostrophic
    wind (θ) and the monsoon ΔP — both fields must be scale-separated before
    ``_graph_least_squares_gradient``.

    Args:
        field: Scalar field(s), shape (N,) or (N, M).
        avg: Neighbour-averaging sparse matrix (row i = mean over i's neighbours).
        n_passes: Number of Jacobi smoothing passes.

    Returns:
        Smoothed field, same shape as input.
    """
    out = field
    for _ in range(n_passes):
        out = 0.5 * out + 0.5 * avg.dot(out)
    return out


def _graph_least_squares_gradient(
    mesh: CVTMesh,
    scalar: np.ndarray,
    nodes_xyz: np.ndarray,
) -> np.ndarray:
    """Per-cell least-squares gradient of a scalar field, in radians on the unit sphere.

    Solves the local normal equations

        (Σ_j d_j d_jᵀ) g = Σ_j Δf_j d_j

    over each cell's neighbours, with d_j the tangent vector from the cell to
    neighbour j (length = angular distance, radians).  The result is the true
    gradient per radian of arc, independent of the local mesh spacing — needed
    wherever a physical gradient magnitude matters (the geostrophic wind, the
    monsoon pressure-gradient force).  Convert to per-metre by dividing by the
    planet radius.  Callers that feed this a raw cell-scale field (temperature
    mosaic, topography) must smooth it first with ``_smooth_graph``.

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
    *,
    hadley_extent_deg: float,
    polar_cell_start_deg: float,
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
        config: Pipeline configuration (rotation period).
        itcz_lat_monthly: ITCZ latitude per month (degrees), shape (12,), or
            None for no migration.
        hadley_extent_deg: Resolved Hadley half-width (P3: config pin or the
            derived Held-Hou value).
        polar_cell_start_deg: Resolved polar-cell start (anti-overlap clamped).

    Returns:
        Annual-mean cell-circulation wind vectors (m/s), shape (N, 3).
    """
    if itcz_lat_monthly is None:
        itcz_lat_monthly = np.zeros(12)
    winds = [
        hadley_cell_wind(
            lat_rad,
            nodes_xyz,
            hadley_extent_deg=hadley_extent_deg,
            polar_cell_start_deg=polar_cell_start_deg,
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


# E4 (2026-09-16): ocean heat transport as a column diffusion D_OHT.  Calibrated
# on Earth: the EBM ocean column with D = 0.37 reproduces the observed
# open-ocean anchor contrast (28 °C equator → −2 °C at 60°, i.e. 30 K); the
# implied peak column transport is ~2.9 PW.  The column lumps two components
# with different rotation dependence, weighted by the Trenberth & Caron 2001
# partition (peak OHT 1.7-2.2 PW of the ~2.9 PW column → ocean share ~0.65):
# the ocean share is wind-driven (gyres + Ekman, NOT Ω-scaled to first order —
# slow rotators lose the westerly-driven subpolar gyres while gaining Ekman
# drift, roughly cancelling), the atmospheric share scales Ω^−0.3 (Kaspi &
# Showman 2015, the same law as the annual EBM).  Earth (P = 1) is unchanged.
_OHT_COLUMN_WM2K: float = 0.37
_OHT_OCEAN_SHARE: float = 0.65


def _ocean_surface_temperature(
    lat_rad: np.ndarray,
    t_surf_c: float,
    config: TerrainPipelineConfig | None = None,
    solar_const: float = SOLAR_CONSTANT,
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

    E4 world-departure: the anchor shape is Earth's *observed* SST — it
    already contains Earth's OHT, so applying it verbatim to another world is
    a hidden Earth calibration.  When ``config`` is given, a process-based
    departure is added:

        T_world = anchor(lat) + [EBM_OHT(world; D=0.37·P^0.3)
                                 − EBM_OHT(earth_ref; D=0.37)]

    the diffusive-OHT EBM difference between the world's own forcing
    (obliquity/flux/orbit) and the Earth reference.  Earth's forcing makes
    the bracket exactly zero (same parameters, same solve); both solves are
    anchored to the same ``t_surf_c``, so the departure carries no global-mean
    shift (the anchor's ``shift`` mechanism stays the sole level control).
    Slow rotators get stronger column diffusion (bigger cells smear anomalies
    faster — the same P^0.3 law as the annual EBM) and weak-obliquity worlds
    get their own radiative shape (e.g. nacrea's 9° tilt flattens the
    mid-latitude ocean while depleting the polar annual insolation).

    Sea ice: the surface of an ice-covered ocean is NOT open water at the
    freezing point.  Sea ice insulates the ocean from the atmosphere
    (Semtner 1976 zero-layer thermodynamics); its surface equilibrates
    with the overlying air and sits far below 0 °C (~−16 °C annual mean
    at the central Arctic).  A −1.8 °C ice surface would evaporate
    ~500 mm/yr through the energy-limited formula and rain it out over
    the poles — the observed ice-zone evaporation is O(100 mm/yr).  The
    ice surface temperature is therefore an observed-anchor profile
    (NCEP zonal-mean surface temperature over the sea-ice zones), shifted
    1:1 with the planet's climate like the open-ocean branch.  Ice edges
    are hemisphere-asymmetric, matching the annual-mean sea-ice extent
    (NSIDC 1981–2010: Arctic ~11.7 Mkm² ≈ 72°N edge, Antarctic ~11 Mkm²
    ≈ 63°S edge).

    Args:
        lat_rad: Latitude in radians.
        t_surf_c: Global-mean surface temperature (°C), i.e. equilibrium
            temperature + greenhouse warming.
        config: Optional pipeline config — enables the E4 process-based
            world-departure.  ``None`` (or an Earth-forcing config) gives the
            pure anchor.
        solar_const: S₀ at the planet's distance (W/m²); only read when
            ``config`` is given.

    Returns:
        SST / ice-surface temperature estimate (°C), shape matches inputs.
    """
    lat_deg = np.degrees(lat_rad)
    abs_lat_deg = np.abs(lat_deg)
    shift = t_surf_c - float(
        surface_temperature(equilibrium_temperature(1.0, 1.0, 0.306), 33.0) - 273.15
    )
    # Open-ocean SST: 30 °C range from equator (28 °C) to ~60° lat (-2 °C),
    # shifted by the planet's surface temperature relative to Earth's.
    # NOTE: sin() takes the latitude in RADIANS (the profile's native form).
    sst_open = 28.0 + shift - 30.0 * np.sin(np.abs(lat_rad)) ** 2

    # Sea-ice edges (annual mean, hemisphere-asymmetric): ~72°N / ~63°S.
    edge_deg = np.where(lat_deg >= 0.0, 72.0, 63.0)
    ice_weight = _sigmoid(abs_lat_deg, center=np.abs(edge_deg), width=6.0)

    # Ice surface temperature: piecewise-linear anchors from NCEP zonal-mean
    # surface temperature over the ice zones, edge → pole (both hemispheres;
    # south of ~72°S is the Antarctic landmass, so the SH profile flattens).
    t_ice_nh = np.interp(abs_lat_deg, [72.0, 80.0, 90.0], [-6.0, -12.0, -17.0])
    t_ice_sh = np.interp(abs_lat_deg, [63.0, 70.0, 90.0], [-4.0, -13.0, -13.0])
    t_ice = np.where(lat_deg >= 0.0, t_ice_nh, t_ice_sh) + shift

    sst = sst_open * (1.0 - ice_weight) + t_ice * ice_weight

    # ── E4: process-based world-departure (diffusive OHT; see docstring) ──
    if config is not None:
        olr_b = config.ebm_olr_b_wm2k
        # Column D_OHT: ocean share (wind-driven, constant) + atmospheric share
        # (Ω^−0.3) — see the module constants above.
        d_oht = _OHT_COLUMN_WM2K * (
            _OHT_OCEAN_SHARE + (1.0 - _OHT_OCEAN_SHARE) * config.rotation_period_days**0.3
        )
        t_proc = solve_1d_ebm_temperature(
            lat_rad,
            t_surf_c,
            albedo=config.albedo,
            obliquity_deg=config.axial_tilt_deg,
            solar_constant=solar_const,
            orbital_period_days=config.orbital_period_days,
            eccentricity=config.eccentricity,
            perihelion_day=config.perihelion_day,
            olr_b_wm2k=olr_b,
            diffusion_wm2k=d_oht,
        )
        t_ref = solve_1d_ebm_temperature(
            lat_rad,
            t_surf_c,
            albedo=0.306,
            obliquity_deg=23.44,
            solar_constant=SOLAR_CONSTANT,
            olr_b_wm2k=olr_b,
            diffusion_wm2k=_OHT_COLUMN_WM2K,
        )
        sst = sst + (t_proc - t_ref)

    return np.asarray(np.clip(sst, -60.0, 30.0))


def _sigmoid(x: np.ndarray, center: float | np.ndarray, width: float) -> np.ndarray:
    """Smooth sigmoid from 0 (x ≪ center) to 1 (x ≫ center).

    Args:
        x: Input values.
        center: Transition center (scalar, or an array broadcastable
            against ``x`` for per-element centers).
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

    **Convention**: ``wind`` must be the *physical* surface wind (east = the
    ``east_north_basis`` convention, matching the frontend's ``wind_east_m_s``).
    Since the tech-debt-24 root unification (2026-09-13) ``hadley_cell_wind``
    composes on that basis directly, so callers pass its output as-is.

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


def _apply_cold_trap(
    w: np.ndarray,
    w_sat: np.ndarray,
    k_rain_field: np.ndarray,
    neg: np.ndarray,
    src: np.ndarray,
    dst: np.ndarray,
    c_in: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Cold-trap saturation cap with upwind routing (CLIM-02 slice 2).

    A cold air column cannot hold more water than its Clausius–Clapeyron
    ``W_sat(T)``, so the reported column is capped — but the capped rainout
    ``k·(W − W_sat)`` is no longer destroyed (the former silent mass
    deletion).  Physically the excess condensed while the air was still warm:
    it rains out *upwind* of the saturated column (the Antarctic coast, not
    the plateau — astra rethinking §2.1/§5.2), so the excess rate is routed
    back along the cell's inflow edges proportionally to the actual arriving
    flux.  With the routed share included as precipitation,
    ΣA·(rainout + routed) = ΣA·k·W_unconstrained, so the budget's exact
    global conservation survives the cap.

    Args:
        w: Solved (unconstrained) column water, mm.
        w_sat: Saturation column water, mm.
        k_rain_field: Rainout rate field, 1/yr.
        neg: Boolean mask of inflow edges (directed src→dst with c<0: air
            flows dst→src, so *dst* is the upwind source).
        src: Directed-edge source-cell indices.
        dst: Directed-edge destination-cell indices.
        c_in: Attenuated advection coefficients (the actual arriving flux is
            |c_in|·W[dst]).

    Returns:
        (capped W, P) with P = k·W_capped + routed excess, both shape (N,).
    """
    w = np.maximum(w, 0.0)
    excess_rate = k_rain_field * np.maximum(w - w_sat, 0.0)
    p_routed = np.zeros_like(w)
    if excess_rate.any():
        neg_idx = np.flatnonzero(neg)
        inflow_e = (-c_in[neg_idx]) * w[dst[neg_idx]]  # arriving flux per edge
        inflow_tot = np.zeros_like(w)
        np.add.at(inflow_tot, src[neg_idx], inflow_e)
        has_inflow = inflow_tot > 1e-12
        tot_at_src = np.where(has_inflow, inflow_tot, 1.0)
        over_src = excess_rate[src[neg_idx]] > 0.0
        share = np.where(
            over_src & has_inflow[src[neg_idx]],
            excess_rate[src[neg_idx]] * inflow_e / tot_at_src[src[neg_idx]],
            0.0,
        )
        np.add.at(p_routed, dst[neg_idx], share)
        # Overshoot from local sources with no inflow: the cell keeps its own rain.
        local_only = (excess_rate > 0.0) & ~has_inflow
        p_routed[local_only] += excess_rate[local_only]
    w = np.minimum(w, w_sat)
    return w, w * k_rain_field + p_routed


# timescale τ in the moisture budget P = W/τ, a physical constant — not a free
# calibration knob — so it is shared by every world (only wind speed and
# evaporation differ, and the advective e-folding length L = u·τ adapts
# automatically with Ω).
_MOISTURE_RESIDENCE_DAYS: float = 9.0

# Reference-year month length (days).  The moisture budget expresses every
# water flux as a *rate per 365.25-day reference year* (a unit convention, not
# the world's physical year length — see climate-pipeline.md「时间基准约定」).
# PET at the subsidence aridity gate must share that basis: feeding Hamon the
# orbital month (orbital_period/12) made PET an *orbital-year accumulation*,
# so AI = P/PET mixed a 365.25-day numerator with an orbital-year denominator —
# on nacrea (100 d yr) AI read ×3.65 too wet (M2-A0④, 2026-09-18).
_DAYS_PER_REFERENCE_MONTH: float = 365.25 / 12.0

# Land evapotranspiration as a fraction of the ocean evaporation *rate* at the
# same temperature.  Earth's land surface returns ~490 mm/yr against the ocean's
# ~1143 mm/yr (Trenberth et al. 2009 global water budget), i.e. ~43% — but land
# is colder than the ocean on average, so the reference is the shared 15 °C
# evaporation rate and this factor absorbs the soil/vegetation reduction of
# evapotranspiration relative to open water.  Calibrated so the global
# land-mean evapotranspiration lands near the observed ~490 mm/yr.  A single
# physical constant, shared by every world (only temperature differs).
_LAND_EVAPOTRANSPIRATION_FRACTION: float = 0.55

# Monsoon pressure-anomaly smoothing scale (km).  The smoothing exists to kill
# the ~51 km cell-scale land–ocean mosaic noise in the ΔP field before
# differentiation (sea-breeze-scale artifacts) — not to adjust the anomaly to
# any dynamical scale.  The continental thermal lows the monsoon wind responds
# to are 1000–2500 km wide with ~500–1000 km inflow channels; the 2026-09-22
# scale sweep showed σ = 500 km (the earlier Rossby-radius rationale — a
# *free*-adjustment scale, misapplied to a *maintained* forcing) destroyed
# 65–85 % of the monsoon-scale gradient, while σ = 150–200 km already
# suppresses the mosaic noise to ~1/17 of the signal.  175 km is the sweep's
# sweet spot.
_MONSOON_PRESSURE_SMOOTHING_KM: float = 175.0

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

        ∇·(W u) + W/τ = E ,   P = W/τ + P_oro

    is discretised with a first-order upwind finite-volume scheme on the CVT
    graph and solved for the column-water field W (mm).  The upwind flux across
    each edge carries the *upwind* cell's W, so the resulting linear system is a
    diagonally-dominant M-matrix (the rainout W/τ provides strict dominance).
    Air crossing an *uphill* edge condenses the φ = 1 − exp(−Δz/H_cc) share of
    its moisture flux (``cc_lift_drying_scale``): the inflow coefficient is
    attenuated to (1−φ)·c and the condensed amount rains out at the windward
    cell as ``P_oro`` — orographic rain and the lee rain shadow from one
    conservative mechanism (CLIM-02 slice 1).

    Because the advection flux terms cancel globally up to the condensed share
    (Σ ∇·(Wu) = −Σ P_oro), the total precipitation — rainout plus orographic
    condensation — equals the total evaporation *by construction*; global water
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

    # ── CLIM-02 slice 1: orographic uplift condensation — a flux sink inside
    # the budget (astra rethinking §5.2/§7: 地形加雨→凝结汇；雨影→输送耗水).
    # Air crossing an edge uphill cools Γ·Δz; Clausius–Clapeyron drops the
    # saturation mixing ratio by exp(−Δz/H_cc) (``cc_lift_drying_scale``).
    # The inflow coefficient is attenuated to (1−φ)·c and the condensed
    # φ-share rains out at the windward (uphill) cell — one conservative
    # mechanism replacing the former post-budget orographic add-on
    # (fabricated water) *and* the multiplicative föhn shadow (deleted
    # water).  The advection no longer telescopes exactly; the residual is
    # Σ P_oro by construction, so ΣA·(k·W + P_oro) = ΣA·E still holds.
    _elev = np.array([cell.elevation for cell in mesh.cells], dtype=np.float64)
    # The air column rides the *surface*: sea level over the ocean, terrain
    # over land.  Using the raw elevation would make every ocean→land edge a
    # 3 km "climb" out of the bathymetry and dump the onshore flux on the
    # first coastal cell (Earth land-P collapse, found in the slice-1 A/B).
    _h_eff = np.maximum(_elev, 0.0)
    _h_cc = cc_lift_drying_scale(temperature_c, moist_lapse_rate(temperature_c))
    # Lifting-condensation-level offset: unsaturated air condenses nothing
    # below the LCL.  Monthly-mean RH ~75% puts z_LCL ≈ 125·(T−T_d) ≈ 800 m
    # (standard approximation, e.g. Bolton 1980 / Smith 1979's linear mountain
    # model starts condensation at the LCL).  Without it every 100-300 m
    # coastal or plateau-edge step taps the flux and the interiors starve
    # (Earth BWh +6500 in the slice-1 A/B) — real orographic rain needs a
    # real barrier, not mesh-scale steps.
    _z_lcl_m = 800.0
    _uphill_inflow = neg & (_h_eff[src] > _h_eff[dst])  # air climbs dst → src
    _phi = np.zeros_like(c)
    _lift = (_h_eff[src] - _h_eff[dst])[_uphill_inflow]
    _phi[_uphill_inflow] = 1.0 - np.exp(
        -np.maximum(_lift - _z_lcl_m, 0.0) / _h_cc[dst][_uphill_inflow]
    )
    _c_in = c * (1.0 - _phi)  # attenuated inflow coefficients (pos edges: φ=0)

    def _oro_from_w(w_field: np.ndarray) -> np.ndarray:
        """Windward orographic condensation, from the solved column water."""
        p_oro = np.zeros(n, dtype=np.float64)
        if _uphill_inflow.any():
            np.add.at(
                p_oro,
                src[_uphill_inflow],
                _phi[_uphill_inflow] * (-c[_uphill_inflow]) * w_field[dst[_uphill_inflow]],
            )
        return p_oro

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
        kappa = config.moisture_diffusivity_m2s * (1.0 + diffusivity_enhancement)
    else:
        kappa = np.full(n, config.moisture_diffusivity_m2s)
    kappa_edge = 0.5 * (kappa[src] + kappa[dst])  # edge-averaged (symmetric)
    _diff_edge = kappa_edge * s_per_year / area_m2[src]  # 1/yr, per directed edge
    diag = k_rain_field.copy()
    np.add.at(diag, src[pos], c[pos])
    np.add.at(diag, src, _diff_edge)  # diffusion: +κ_edge/A_src per neighbour
    row = np.concatenate([np.arange(n), src[neg], src])
    col = np.concatenate([np.arange(n), dst[neg], dst])
    val = np.concatenate([diag, _c_in[neg], -_diff_edge])
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
            p = w * k_rain_field + _oro_from_w(w)  # orographic rain feeds land ET
            _e_new = _e_pot_land * p / (_e_pot_land + p + 1e-9)
            _delta = float(np.max(np.abs(_e_new - _e_land)))
            _e_land = _LAND_RECYCLING_RELAX * _e_new + (1.0 - _LAND_RECYCLING_RELAX) * _e_land
            e = np.where(is_land, _e_land, e_ocean)
            if _delta < _LAND_RECYCLING_TOL_MM:
                break

    w = lu.solve(e)
    p_oro = _oro_from_w(w)  # from the solved (pre-trap) column water

    # Cold trap: saturation cap + upwind routing of the excess rainout
    # (CLIM-02 slice 2 — the excess rains where the air was still warm).
    w_sat = column_water_saturation(temperature_c)
    w, p = _apply_cold_trap(w, w_sat, k_rain_field, neg, src, dst, _c_in)
    # Orographic condensation comes from the *transiting* flux, not the local
    # column, so it bypasses the cold-trap cap.
    return w, p + p_oro


# Reference background precipitation (mm/yr) used to normalise k_rain
# modulation amplitudes (coastal asymmetry, sub-planet convection) — an
# observation-fit class constant (discipline #9), shared so the two gates
# express their strengths on the same scale.
_K_MOD_P_REF_MM: float = 1000.0


def _sub_planet_rainout_factor(
    lat_rad: np.ndarray,
    lon_rad: np.ndarray,
    config: TerrainPipelineConfig,
) -> np.ndarray:
    """Sub-planet convective rainout enhancement as a k_rain modulation
    (CLIM-02 slice 4, astra §2.1/§7).

    On a tidally locked body the host hangs fixed overhead: its thermal +
    reflected illumination steadily heats the sub-planet point and anchors
    convection there (the sub-stellar convective anchor, e.g. Pierrehumbert
    2010 for stellar-locked planets).  A Gaussian rainout-efficiency
    enhancement centred on the sub-planet point expresses this inside the
    budget — conserving (any k field keeps ΣA·P = ΣA·E), unlike the former
    additive post-budget rain boost (fabricated water).  Gated by
    ``sub_planet_warming_c`` (0 disables; Earth = 0).

    Epistemic class (discipline #9): the σ = 15° Gaussian and the amplitude
    scale ``warming_c × 200 mm/yr/°C`` (converted to a multiplicative factor
    over ``_K_MOD_P_REF_MM``) are author-set heuristics awaiting a literature
    anchor for the sub-planet convective anchor strength — registered to the
    stage-D W-field work, where why the budget alone does not already peak at
    the sub-point (transit-ocean SST structure) is the root question.

    Returns:
        Factor ≥ 1.0, shape (N,).
    """
    if config.sub_planet_warming_c <= 0.0:
        return np.ones_like(lat_rad, dtype=np.float64)
    sub_lat = np.radians(config.sub_planet_latitude_deg)
    sub_lon = np.radians(config.sub_planet_longitude_deg)
    cos_ang = np.sin(lat_rad) * np.sin(sub_lat) + np.cos(lat_rad) * np.cos(sub_lat) * np.cos(
        lon_rad - sub_lon
    )
    ang_dist_deg = np.degrees(np.arccos(np.clip(cos_ang, -1.0, 1.0)))
    amplitude_mm = config.sub_planet_warming_c * 200.0  # mm/yr per °C of warming
    gaussian = np.asarray(np.exp(-0.5 * (ang_dist_deg / 15.0) ** 2), dtype=np.float64)
    return 1.0 + (amplitude_mm / _K_MOD_P_REF_MM) * gaussian


def _coastal_rainout_factor(
    mesh: CVTMesh,
    n: int,
    is_land: np.ndarray,
    is_ocean: np.ndarray,
    wind: np.ndarray,
    temperature_c: np.ndarray,
    nodes_xyz: np.ndarray,
) -> np.ndarray:
    """Coastal rainout-efficiency modulation (CLIM-02 slice 3, astra §2.1/§7).

    Onshore winds carry ocean moisture → coastal convergence raises the local
    rainout efficiency; offshore (land-sourced) winds suppress it.  Applied as
    a multiplicative ``k_rain`` field inside the budget — mass-conserving by
    construction (same family as the storm-track / SST / omega gates), unlike
    the former post-budget multiplication of the final precipitation (which
    non-conservatively scaled everything, including orographic condensation
    and cold-trap routed rain that have nothing to do with coastal
    convergence).  Epistemic class of the constants (discipline #9):
    observation-fit — eps windward/leeward and the [0.5, 1.5] clip are
    calibrated magnitudes; the flux form rho·|U|·q_sat is physical.

    Returns:
        Factor in [0.5, 1.5], shape (n,); 1.0 away from coastal land.
    """
    _coastal, _west_coast = _detect_coastal_cells(mesh.cells, n, is_land, is_ocean)
    if not _coastal.any():
        return np.ones(n, dtype=np.float64)

    from dreamulator.map.ocean_circulation import east_north_basis as _enb

    _east, _ = _enb(nodes_xyz)
    _uzonal = np.einsum("ij,ij->i", wind, _east)  # physical zonal component

    _rho_air = 1.2  # kg/m³
    _s_per_year = 365.25 * 86400.0
    _p_bg = _K_MOD_P_REF_MM  # mm/yr reference background precipitation
    _eps_windward = 1.3e-4  # coastal precipitation efficiency (windward)
    _eps_leeward = 0.8e-4  # coastal precipitation efficiency (leeward)

    factor = np.ones(n, dtype=np.float64)
    for i in np.flatnonzero(_coastal):
        u_abs = abs(_uzonal[i])
        t_k = max(temperature_c[i] + 273.15, 230.0)
        e_sat = 611.2 * np.exp(17.67 * (t_k - 273.15) / (t_k - 29.65))  # Pa
        q_sat = 0.622 * e_sat / 101325.0  # kg/kg
        moisture_flux = _rho_air * u_abs * q_sat  # kg/m²/s
        delta_p = moisture_flux * _s_per_year  # mm/yr equivalent

        is_westerly = _uzonal[i] > 0
        windward = (is_westerly and _west_coast[i]) or (not is_westerly and not _west_coast[i])
        eps = _eps_windward if windward else _eps_leeward
        f_i = 1.0 + eps * delta_p / _p_bg if windward else (1.0 - eps * delta_p / _p_bg)
        factor[i] = np.clip(f_i, 0.5, 1.5)
    return factor


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
) -> tuple[float, float, float]:
    """Centre, half-width (degrees) and equator-pole contrast of the baroclinic band.

    Transient eddies grow where the meridional temperature gradient is
    steepest (Eady instability follows ∇T), so the band is derived from the
    zonal-mean temperature profile rather than from circulation-cell
    boundaries.  Cell boundaries degenerate for single-cell slow rotators —
    yet GCMs of slow rotators show weakened-but-nonzero eddy activity, with
    the baroclinic zone at the mid-to-high-latitude gradient maximum of the
    broad temperature profile (Held–Hou quartic: gradient ∝ sin³φ·cosφ,
    peak near 50–60°).

    The third return value is the profile's own equator-to-pole contrast
    (first minus last zonal bin) — the self-field baroclinicity measure the
    storm amplitude normalises against Earth's 45 °C, replacing the former
    config/auto ``lat_gradient`` duality.

    Args:
        temperature_c: Annual-mean temperature field (°C), shape (N,).  Callers
            on ice-feedback worlds pass the ice-free field (E2).
        lat_deg: Latitude in degrees, shape (N,).
        band_deg: Latitude bin width for the zonal mean.
        min_lat_deg: Ignore gradients equatorward of this (ITCZ region).

    Returns:
        (centre_latitude, gaussian_half_width, delta_ep_c); falls back to the
        classic (45°, 15°, 45 °C) when the profile is too flat to locate a
        peak.
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
        return 45.0, 15.0, 45.0  # incomplete latitudinal coverage — classic fallback
    t_zonal = sums / counts
    delta_ep_c = float(t_zonal[0] - t_zonal[-1])

    grad = np.abs(np.gradient(t_zonal, band_deg))
    # Smooth bin noise (twice-over 3-point kernel ≈ Gaussian σ≈1 bin).
    kernel = np.array([0.25, 0.5, 0.25])
    for _ in range(2):
        grad = np.convolve(grad, kernel, mode="same")

    search = centers >= min_lat_deg
    if not search.any() or grad[search].max() < 0.05:
        return 45.0, 15.0, 45.0  # flat profile (no baroclinicity) — fallback
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
    return centre, width, delta_ep_c


def _to_physical_wind(wind: np.ndarray, east: np.ndarray) -> np.ndarray:
    """Reflect a wind field across the local east axis (flip its east component).

    The map is an involution between the physical convention and the legacy
    mirrored one (``east = north × r̂`` = physical west).  Since the tech-debt-24
    root unification (2026-09-13) the engine's wind fields compose physical at
    the source; the sole remaining use is to feed the *mirror-calibrated*
    ocean chain (Stommel stress/curl, upwelling index, ocean→land anomaly
    advection) in Stage 2.5 — those internals are verified on mirror input
    and must not be re-derived (historical lesson: root-flipping a calibrated
    chain cascades into every downstream sign).  ``w' = w − 2(w·ê)ê``.

    Args:
        wind: Wind vectors, shape (N, 3) or (M, N, 3).
        east: Physical local east unit vectors (``east_north_basis``), (N, 3).

    Returns:
        East-reflected wind, same shape as *wind*.
    """
    we = np.einsum("...ij,ij->...i", wind, east)
    return np.asarray(wind - 2.0 * we[..., None] * east)


def _compute_precipitation_monthly_budget(
    mesh: CVTMesh,
    wind: np.ndarray,
    wind_monthly: np.ndarray,
    is_land: np.ndarray,
    is_ocean: np.ndarray,
    temperature_c: np.ndarray,
    t_monthly_c: np.ndarray,
    nodes_xyz: np.ndarray,
    config: TerrainPipelineConfig,
    itcz_lat_monthly: np.ndarray | None = None,
    debug: dict[str, np.ndarray] | None = None,
    edge_table: tuple[np.ndarray, np.ndarray] | None = None,
    ice_increment_c: np.ndarray | None = None,
    omega_gate_monthly: np.ndarray | None = None,
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
    gone (tech debt 23).  k_rain carries three composed modulations, all
    mass-conserving: the storm-track enhancement (Step 3.5), the §5-α SST
    convection gate ``f(ΔSST)`` (cold-anomaly ocean water exports its moisture
    to the warm pool instead of raining locally — ``sst_convection_gate``) and
    the ④ v2 subsidence-drying gate ``f(w_mid)`` on land (``omega_gate_monthly``,
    stationary-wave subsidence lobes export their moisture to the ascent
    regions — ``subsidence_rainout_gate``).

    On top of each month's budget precipitation: the mechanisms that do not
    vary by month in this model — sub-planet convective enhancement (steady
    on a locked body) — and finally the annual cap applied to the monthly
    values proportionally.  The orographic uplift condensation, the cold-trap
    upwind routing and the west/east-coast rainout asymmetry all live INSIDE
    the budget solve itself (CLIM-02 slices 1-3), so every solve conserves
    ΣA·P = ΣA·E exactly before the remaining post-processing.

    Args:
        mesh: CVT mesh.
        wind: Annual background wind field, shape (N, 3).
        wind_monthly: Monthly winds (background + monsoon anomaly), shape
            (12, N, 3).
        is_land: Boolean land mask, shape (N,).
        is_ocean: Boolean ocean mask, shape (N,).
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
        ice_increment_c: Optional annual ice-albedo feedback increment (°C,
            shape (N,)) archived by Stage 1.  The baroclinic band reads the
            ice-free field ``temperature_c − increment`` on land (E2: the
            feedback is a response, not a forcing — the storm band must not
            chase the ice edge).  ``None`` or all-zero → use the field as-is.
        omega_gate_monthly: Optional land subsidence-drying gate factor,
            shape (N, 12), in [0.2, 1] — the ④ v2 consumption
            (``subsidence_rainout_gate`` on the stationary-wave mid-level w).
            Composed multiplicatively with the storm/SST k_rain modulations;
            ``None`` (default) disables the composition.

    Returns:
        (p_annual_mm shape (N,), p_monthly_mm shape (N, 12)).
    """
    n = mesh.num_cells
    lat_rad = np.radians(np.array([c.lat for c in mesh.cells], dtype=np.float64))
    lon_rad = np.radians(np.array([c.lon for c in mesh.cells], dtype=np.float64))
    lat_deg = np.degrees(lat_rad)

    # ── Wind convention (tech debt 24 root unification, 2026-09-13) ────────
    # `wind` / `wind_monthly` arrive in the *physical* convention
    # (`hadley_cell_wind` and the monsoon module compose on the true east
    # basis = direction of increasing longitude, verified against NCEP).
    # The moisture budget, orographic rain and the coast-asymmetry step
    # consume them directly — the former entry flip (2026-09-12 mirror-bug
    # fix) is retired.  The only remaining mirror-convention consumers are
    # the calibrated ocean chain (Stommel / upwelling / anomaly advection),
    # fed `wind_mirror` at their own entry in Stage 2.5.

    # Directed edge table built once, shared by the 12 budget solves and the
    # orographic step.
    if edge_table is not None:
        src, dst = edge_table
    else:
        from dreamulator.map.ocean_circulation import _build_directed_edge_table

        src, dst = _build_directed_edge_table(mesh.cells)

    # Step 3.5: Mid-latitude storm tracks (baroclinic eddies) — a spatial
    # modulation of the rainout rate k_rain, NOT an additive precipitation
    # source (Held & Soden 2006).  The band is derived from the zonal-mean
    # temperature gradient (``_baroclinic_band``, E2: evaluated on the
    # ice-free field); the amplitude scales with the baroclinicity — the
    # model's own zonal equator-to-pole contrast (self-field criterion: no
    # config/auto_lat_gradient duality, Earth emerges as the 45 °C reference)
    # — times the Ω^0.3 eddy scaling and the available moisture.  Annual
    # fields — the band's seasonal excursion is a second-order effect here.
    if ice_increment_c is not None:
        _t_band_input = np.where(is_land, temperature_c - ice_increment_c, temperature_c)
    else:
        _t_band_input = temperature_c
    _storm_center, _storm_width, _storm_delta_ep_c = _baroclinic_band(_t_band_input, lat_deg)
    _storm_amp = (
        config.storm_track_amplitude_mm
        * (_storm_delta_ep_c / 45.0)
        * (1.0 / config.rotation_period_days) ** 0.3
        * (config.evaporation_base_mm / 1000.0)
    )
    _storm_enhance = (_storm_amp / config.evaporation_base_mm) * np.exp(
        -0.5 * ((np.abs(lat_deg) - _storm_center) / _storm_width) ** 2
    )
    # The same baroclinic eddies also transport moisture poleward (transient-
    # eddy mixing): eddy-diffusivity enhancement ∝ rainout enhancement.
    _eddy_enhance = config.storm_track_kappa_enhancement * _storm_enhance

    # ── §5-α SST convection gate (WTG): k_rain × f(ΔSST) ──────────────────
    # Cold-anomaly ocean water (upwelling / eastern boundary currents — Somali,
    # Canary, Peru cores) is stabilised from below → rainout efficiency
    # collapses and the moisture exports to the warm pool (mass-conserving:
    # composed with the storm modulation as a common k_rain factor, ΣP = ΣE
    # holds for any gate field).  Warm anomalies give f = 1 exactly — warm
    # pools / WBC supply corridors (Bay of Bengal, SCS, Kuroshio, Gulf Stream)
    # are structurally untouched.  Knots = GPCP ocean-cell calibration
    # (``sst_convection_gate`` docstring).  v1 ocean-only.
    if config.sst_convection_gate_enabled:
        _gate_annual = sst_convection_gate(temperature_c, lat_deg, is_ocean)
        _gate_monthly = sst_convection_gate(t_monthly_c, lat_deg, is_ocean)
        _rain_ann = (1.0 + _storm_enhance) * _gate_annual - 1.0
        if debug is not None:
            debug["sst_gate"] = _gate_annual.copy()
    else:
        _gate_monthly = None
        _rain_ann = _storm_enhance
    # ④ v2 subsidence-drying gate: multiplicative composition with the storm /
    # SST gates (the annual budget uses the monthly gate factors' arithmetic
    # mean — the annual solve only sets the land-ET fixed point, which must not
    # be distorted by the monthly weighting).
    if omega_gate_monthly is not None:
        _rain_ann = (1.0 + _rain_ann) * omega_gate_monthly.mean(axis=1) - 1.0
    # ── CLIM-02 slice 3: coastal asymmetry as a k_rain modulation ── the
    # same physical factor the former post-budget step applied, but inside
    # the budget so ΣA·P = ΣA·E survives it (see _coastal_rainout_factor).
    _coastal_k = _coastal_rainout_factor(mesh, n, is_land, is_ocean, wind, temperature_c, nodes_xyz)
    _rain_ann = (1.0 + _rain_ann) * _coastal_k - 1.0
    # ── CLIM-02 slice 4: sub-planet convective anchor as a k_rain modulation ──
    # nacrea-only (sub_planet_warming_c > 0); conserving, replacing the former
    # additive post-budget rain boost.
    _sub_k = _sub_planet_rainout_factor(lat_rad, lon_rad, config)
    _rain_ann = (1.0 + _rain_ann) * _sub_k - 1.0

    _k_base = 365.25 / _MOISTURE_RESIDENCE_DAYS  # base rainout rate, 1/yr

    # Annual solve first: the Budyko recycling curve E = E_pot·P/(E_pot+P) is
    # an annual water-balance relation, and its fixed point converges against
    # the annual P.  Re-applying it inside each monthly solve would depress
    # land evapotranspiration by Jensen's inequality (concave in P), starving
    # the land recycling loop.  Converge it once here and hand the annual
    # water limitation to the monthly solves.
    w0_ann, p_ann = _solve_moisture_budget(
        mesh,
        wind,
        is_ocean,
        temperature_c,
        nodes_xyz,
        config,
        rainout_enhancement=_rain_ann,
        diffusivity_enhancement=_eddy_enhance,
        edge_table=(src, dst),
    )
    if debug is not None:
        # Ungated pass-1 column water — the §5-β calibration input (the wave-
        # gate mode reads this to bin observed precipitation by x = W/W_sat).
        debug["w_column_annual"] = w0_ann.copy()
    # ── §5-β convective pickup gate (iterate-once, keeps every solve linear).
    # The observed rainout efficiency τ = W/P varies by 15-20× between deep
    # deserts (~150 d) and convective regions (7-10 d); the engine's base
    # k_rain is a uniform 1/9 d, which rains the desert column out every nine
    # days and leaks transit-ocean moisture en route.  The gate restores the
    # criticality: precipitation is a critical phenomenon of column water
    # (Neelin, Peters & Hales 2009), so k_rain is suppressed below the
    # convective criticality x = W/W_sat.  The re-solve re-converges the Budyko
    # fixed point against the gated P (correct annual water balance), and the
    # withheld moisture is mass-conservingly exported toward regions above
    # criticality — including the monsoon lands the transit oceans feed.
    if config.convective_pickup_gate_enabled:
        _pickup_ann = convective_pickup_gate(w0_ann, temperature_c)
        w1_ann, p_ann = _solve_moisture_budget(
            mesh,
            wind,
            is_ocean,
            temperature_c,
            nodes_xyz,
            config,
            rainout_enhancement=(1.0 + _rain_ann) * _pickup_ann - 1.0,
            diffusivity_enhancement=_eddy_enhance,
            edge_table=(src, dst),
        )
        # Iterate-twice: the gate relaxes at the re-balanced column.  A single
        # pass pins the gate to the ungated W₀ and structurally blocks the
        # self-release (the first acceptance run: the Ganges fell to 0.35×
        # because its starved W₀ held the gate shut while the withheld
        # transit moisture could never re-open it).  Recomputing at W₁ lets
        # forced columns climb to their criticality — the Picard step toward
        # the k(W) fixed point, matching the daily-timescale convective
        # adjustment behind a monthly-mean closure.
        _pickup_ann = convective_pickup_gate(w1_ann, temperature_c)
        _, p_ann = _solve_moisture_budget(
            mesh,
            wind,
            is_ocean,
            temperature_c,
            nodes_xyz,
            config,
            rainout_enhancement=(1.0 + _rain_ann) * _pickup_ann - 1.0,
            diffusivity_enhancement=_eddy_enhance,
            edge_table=(src, dst),
        )
        if debug is not None:
            debug["pickup_gate_annual"] = _pickup_ann.copy()
    # Converged land ET re-extracted from the annual P (the fixed point ended
    # within 1 mm/yr of this relation).
    _e_pot_ann = evaporation_rate(temperature_c, is_land, config.evaporation_base_mm)
    _e_land_ann = _e_pot_ann * p_ann / (_e_pot_ann + p_ann + 1e-9)
    if debug is not None:
        debug["land_epot"] = _e_pot_ann.copy()
        debug["land_et"] = _e_land_ann.copy()

    # CLIM-02 (2026-09-18): per-stage area-weighted water ledger — quantify how
    # much each post-budget mechanism adds/removes, exposing the ΣP = ΣE
    # residual that the budget core guarantees (including the orographic
    # condensation, in-solver since slice 1) but the sub-planet / sentinel
    # post-processing breaks.  Area-weighted (Σ P·A in mm·km²/yr) so a huge
    # wet ocean cell counts proportionally.
    _area_km2 = np.array([c.area_km2 for c in mesh.cells], dtype=np.float64)

    def _monthly_pass(
        e_land_rate: np.ndarray | None,
    ) -> tuple[np.ndarray, float, np.ndarray, np.ndarray, np.ndarray]:
        """Run the 12 monthly budget solves.

        Args:
            e_land_rate: (n, 12) land evapotranspiration in mm/yr per month
                (the solver's rate basis); ``None`` → the memoryless Budyko
                estimate from that month's temperature + the annual P.

        Returns:
            (p_monthly mm/month, ledger core ΣP·A, storm debug, W debug,
            pickup-gate debug).
        """
        p_out = np.zeros((n, 12), dtype=np.float64)
        dbg_storm = np.zeros(n)
        dbg_pickup = np.ones(n)
        dbg_w = np.zeros(n)
        ledger = 0.0
        for m in range(12):
            t_m = t_monthly_c[:, m]
            if e_land_rate is None:
                # Monthly land ET: energy limitation from that month's
                # temperature, water limitation from the annual precipitation
                # (soil moisture integrates the annual water input, not a
                # single month's) — the bucket pass below replaces this.
                _e_pot_m = evaporation_rate(t_m, is_land, config.evaporation_base_mm)
                _e_land_m = _e_pot_m * p_ann / (_e_pot_m + p_ann + 1e-9)
            else:
                _e_land_m = e_land_rate[:, m]
            if _gate_monthly is not None:
                _rain_m = (1.0 + _storm_enhance) * _gate_monthly[:, m] - 1.0
            else:
                _rain_m = _storm_enhance
            if omega_gate_monthly is not None:
                _rain_m = (1.0 + _rain_m) * omega_gate_monthly[:, m] - 1.0
            _rain_m = (1.0 + _rain_m) * _coastal_k - 1.0  # CLIM-02 slice 3
            _rain_m = (1.0 + _rain_m) * _sub_k - 1.0  # CLIM-02 slice 4
            w_m, p_m = _solve_moisture_budget(
                mesh,
                wind_monthly[m],
                is_ocean,
                t_m,
                nodes_xyz,
                config,
                rainout_enhancement=_rain_m,
                diffusivity_enhancement=_eddy_enhance,
                edge_table=(src, dst),
                land_evapotranspiration=_e_land_m,
            )
            # §5-β monthly iterate-twice: this month's pass-1 column water sets
            # the gate (monthly responsiveness — the July Sahel column is
            # convectively viable while the annual mean is not), the month is
            # re-solved, and the gate is recomputed at the re-balanced column
            # (self-release — see the annual block).  The orographic step below
            # consumes the re-solved w_m automatically.
            if config.convective_pickup_gate_enabled:
                _pickup_m = convective_pickup_gate(w_m, t_m)
                w_m, p_m = _solve_moisture_budget(
                    mesh,
                    wind_monthly[m],
                    is_ocean,
                    t_m,
                    nodes_xyz,
                    config,
                    rainout_enhancement=(1.0 + _rain_m) * _pickup_m - 1.0,
                    diffusivity_enhancement=_eddy_enhance,
                    edge_table=(src, dst),
                    land_evapotranspiration=_e_land_m,
                )
                _pickup_m = convective_pickup_gate(w_m, t_m)
                w_m, p_m = _solve_moisture_budget(
                    mesh,
                    wind_monthly[m],
                    is_ocean,
                    t_m,
                    nodes_xyz,
                    config,
                    rainout_enhancement=(1.0 + _rain_m) * _pickup_m - 1.0,
                    diffusivity_enhancement=_eddy_enhance,
                    edge_table=(src, dst),
                    land_evapotranspiration=_e_land_m,
                )
                dbg_pickup *= _pickup_m

            # p_m already includes the orographic condensation (in-solver flux
            # sink, CLIM-02 slice 1) — the former post-budget add-on is gone.
            p_out[:, m] = p_m / 12.0
            ledger += float((p_m * _area_km2).sum() / 12.0)
            dbg_storm += (w_m * _k_base * _storm_enhance) / 12.0
            dbg_w += w_m / 12.0
        return p_out, ledger, dbg_storm, dbg_w, dbg_pickup

    # Pass 1: memoryless Budyko land ET (also the bucket's P forcing source).
    p_monthly, _ledger_core, _dbg_storm, _dbg_w_final, _dbg_pickup = _monthly_pass(None)

    # ── Soil-water bucket (CLIM-02, astra §2.3): cross-month store replaces
    # the memoryless monthly Budyko estimate.  Pass-1 precipitation forces the
    # bucket to its periodic steady state; the resulting ET re-drives the 12
    # monthly solves (pass 2).  A truncated two-pass fixed point — the ΔE
    # residual between the bucket runs is reported, not iterated away (the
    # full T↔P coupling belongs to steady-coupling, not here).
    if config.soil_bucket_enabled and is_land.any():
        _e_pot_mo = np.stack(
            [
                evaporation_rate(t_monthly_c[:, m], is_land, config.evaporation_base_mm) / 12.0
                for m in range(12)
            ],
            axis=1,
        )
        _e_bud, _r_bud, _cycles, _ds = soil_bucket_monthly(
            p_monthly, _e_pot_mo, config.soil_water_capacity_mm
        )
        p_monthly, _ledger_core, _dbg_storm, _dbg_w_final, _dbg_pickup = _monthly_pass(
            _e_bud * 12.0
        )
        # Truncated-iteration diagnostic: re-run the bucket on pass-2 P.
        _e_bud2, _r_bud2, _c2, _ds2 = soil_bucket_monthly(
            p_monthly, _e_pot_mo, config.soil_water_capacity_mm
        )
        _dE_land = float(np.abs(_e_bud2 - _e_bud)[is_land].max()) * 12.0
        _e_budyko_mo = (
            _e_pot_mo * 12.0 * p_ann[:, None] / (_e_pot_mo * 12.0 + p_ann[:, None] + 1e-9)
        )
        # Bucket output is mm/month → sum over months = mm/yr; the Budyko
        # comparison is an annual *rate* per month → mean over months.
        _et_bucket = float(_e_bud[is_land].sum(axis=1).mean())
        _et_budyko = float(_e_budyko_mo[is_land].mean(axis=1).mean())
        _console.print(
            f"  [dim]soil bucket: C={config.soil_water_capacity_mm:.0f} mm, "
            f"steady in {_cycles} cycle(s) (residual {_ds:.3f} mm); land-mean ET "
            f"{_et_bucket:.0f} mm/yr (Budyko {_et_budyko:.0f}); truncated pass-2 "
            f"ΔE max {_dE_land:.1f} mm/yr[/dim]"
        )
        if debug is not None:
            debug["soil_et_monthly"] = (_e_bud2 * 12.0).copy()
            debug["soil_runoff_monthly"] = (_r_bud2 * 12.0).copy()

    if debug is not None:
        debug["moisture_budget"] = p_monthly.sum(axis=1).copy()
        debug["storm"] = _dbg_storm
        debug["w_column_final_mean"] = _dbg_w_final.copy()
        if config.convective_pickup_gate_enabled:
            debug["pickup_gate_monthly_mean"] = _dbg_pickup.copy()

    # CLIM-02 water ledger: area-weighted annual Σ P·A (mm·km²/yr) snapshots at
    # each post-budget stage, so the build log exposes how much the orographic /
    # coastal / föhn / sub-planet / cap corrections add or remove relative to
    # the mass-conserving core (ΣP = ΣE there).  The residual is the net
    # non-conservation of the final precipitation field.
    def _pa() -> float:
        return float((p_monthly.sum(axis=1) * _area_km2).sum())

    _ledger_stages: list[tuple[str, float]] = [("core (budget+oro+coastal)", _ledger_core)]

    # Step 6.6 (coastal asymmetry) migrated into the budget in CLIM-02 slice 3:
    # the same physical factor now modulates k_rain inside every solve (see
    # _coastal_rainout_factor) instead of multiplying the final precipitation
    # — conserving, and it no longer spuriously scales orographic condensation
    # or cold-trap routed rain.

    # Step 6.7 (Föhn rain shadow) was removed in CLIM-02 slice 1: the leeward
    # drying now emerges inside the budget — the orographic condensation
    # attenuates the moisture flux crossing the barrier, so the air arriving
    # leeward is already depleted (same Clausius–Clapeyron physics the shadow
    # factor applied, but conservative: the dried share rains out windward).

    # Step 8 (sub-planet additive rain boost) migrated into the budget in
    # CLIM-02 slice 4: the sub-planet convective anchor now modulates k_rain
    # inside every solve (see _sub_planet_rainout_factor) — conserving, and
    # the enhancement scales with the local column water instead of adding a
    # fixed amount over whatever the budget produced.

    # Convergence sentinel (CLIM-02 slice 5): per-cell annual cap
    # α·k_rain·W_sat(T) — world-independent and temperature-adaptive, replacing
    # the fixed 11000 mm/yr Earth-station clip.  Applied to the monthly values
    # proportionally so the seasonal shape is preserved where it engages.
    # Numerical stabilisation (discipline #9), not physics: it clips the
    # slice-1 per-edge orographic over-concentration on steep terrain — and
    # warns loudly instead of deleting water silently.
    p_annual = p_monthly.sum(axis=1)
    if debug is not None:
        debug["pre_cap"] = p_annual.copy()
    _sentinel = _convergence_sentinel(temperature_c, _k_base * (1.0 + _rain_ann))
    _over = p_annual > _sentinel
    if _over.any():
        logger.warning(
            "convergence sentinel clipped %d cells (%.3f%%): max P %.0f mm/yr "
            "(sentinel range %.0f–%.0f) — slice-1 per-edge orographic "
            "over-concentration; revisit with the stage-D supply route",
            int(_over.sum()),
            float(_over.mean()) * 100.0,
            float(p_annual[_over].max()),
            float(_sentinel[_over].min()),
            float(_sentinel[_over].max()),
        )
    scale = np.where(_over, _sentinel / np.maximum(p_annual, 1e-9), 1.0)
    p_monthly *= scale[:, None]
    p_annual = p_monthly.sum(axis=1)
    _ledger_stages.append(("sentinel", _pa()))
    if debug is not None:
        debug["final"] = p_annual.copy()

    # CLIM-02 ledger report: each stage's area-weighted ΣP·A and its delta from
    # the mass-conserving core, ending at the net non-conservation residual.
    _core = _ledger_stages[0][1]
    _parts = [f"{_core / 1e9:.3f}"]
    _prev = _core
    for _name, _val in _ledger_stages[1:]:
        _parts.append(f"{_name} {(_val - _prev) / 1e9:+.3f}")
        _prev = _val
    _resid = _prev - _core
    _console.print(
        f"  [dim]water ledger ΣP·A (10⁹ mm·km²/yr): "
        f"{' → '.join(_parts)}; residual {_resid / 1e9:+.3f} "
        f"({_resid / max(_core, 1e-9) * 100:+.2f}% of core)[/dim]"
    )

    return p_annual, p_monthly
