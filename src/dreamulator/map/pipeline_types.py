"""Terrain pipeline configuration and spherical coordinate utilities.

Shared types used across all terrain pipeline modules (cvt_mesh, plate_generator,
boundary_detector, terrain_synthesizer, export, terrain_pipeline).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
import yaml

if TYPE_CHECKING:
    from pathlib import Path

    from .geography import GeographySpec


# ---------------------------------------------------------------------------
# Terrain Pipeline Configuration
# ---------------------------------------------------------------------------


@dataclass
class TerrainPipelineConfig:
    """Complete configuration for the CVT terrain generation pipeline.

    All physical quantities use SI-derived units with explicit suffixes.
    """

    # Identity
    seed: int = 42

    # Planetary physical parameters
    radius_km: float = 6371.0
    gravity_m_s2: float = 9.81
    rotation_period_days: float = 1.0
    albedo: float = 0.306  # Bond albedo (Earth ≈ 0.306)
    orbital_period_days: float = 365.25
    surface_pressure_hpa: float = 1013.25

    # CVT mesh generation
    num_nodes: int = 100_000
    jitter_sigma: float = 0.3
    lloyd_iterations: int = 8

    # Tectonic plates
    num_plates: int = 20
    plate_speed_range_cm_yr: tuple[float, float] = (1.0, 10.0)
    # ---- Tidal heating → plate speed coupling (see tidal_plate_speed.md) ----
    # When enabled, the fastest-plate speed and ocean half-spreading rate are
    # *derived* from tidal heating instead of the authored plate_speed_max /
    # spreading_rate values.  Requires a satellite body whose orbit (e, a) and
    # parent mass resolve from stellar.yaml (see physical_inputs.resolve_tidal_heating).
    tidal_plate_speed_enabled: bool = False
    # Power-law exponent v ∝ q^β.  Literature range [0.5, 1.5]; 1.0 = linear
    # (matches most thermal-evolution models; reproduces ~15 cm/yr for nacrea).
    tidal_plate_speed_beta: float = 1.0
    # Earth reference anchors: mean plate speed (cm/yr) and total surface heat
    # flux (W/m²).  0.09 = 47 TW over Earth's area (44–47 TW total heat flow).
    tidal_plate_speed_v_ref_cm_yr: float = 5.0
    tidal_plate_speed_q_ref_w_m2: float = 0.09
    # Tidal dissipation factor k₂/Q (physical_params.md: k₂=0.3, Q=100).
    tidal_k2_over_q: float = 0.003
    # Ocean half-spreading rate as a fraction of the fastest plate speed
    # (Earth ~0.4; nacrea authored 6/15 = 0.4).
    tidal_spreading_ratio: float = 0.4
    # Algorithm for initial plate partition:
    #   "cortial2019" — Poisson-disc + spherical Voronoi BFS (Cortial et al. 2019 §3)
    plate_algorithm: str = "cortial2019"
    # Fraction of boundary cells to randomly flip (0 = straight Voronoi
    # edges, 0.05–0.15 = natural organic boundaries).
    # Follows Cortial et al. (2019) "noise-warped geodetic distance".
    boundary_noise: float = 0.10
    # Voronoi boundary warp amplitude (Cortial et al. 2019 §3 "geodetic
    # distance + noise warp").  0 = straight geodesic Voronoi edges;
    # ~0.5–0.8 = irregular, jagged plate boundaries (realistic arcs/segments
    # instead of long straight lines).  Applied to the FINAL partition (after
    # tectonics) via a noise-weighted multi-source Dijkstra.
    boundary_warp: float = 0.0
    # Trench arc curvature — Frank (1968) small-circle mechanism: a subducting
    # slab indents the surface as a rigid spherical cap, so the trench traces a
    # SMALL CIRCLE (island-arc curvature; radius ↔ slab dip ↔ convergence rate,
    # Tovish 1978).  Voronoi bisectors can never produce this, so convergent
    # oceanic boundaries are relaxed toward the arc after each tectonic
    # resample; the arc DEVELOPS over the evolution from the current kinematic
    # state (not authored).  0 = off; 1 = full dip-dependent sagitta
    # (0.10–0.30 × chord, bulging oceanward).
    trench_arc: float = 1.0
    # Per-plate continental fraction range.  Each plate is assigned a random
    # continental cell ratio uniformly in [min, max].  Earth ≈ 0.29 land
    # (emergent), but the crust-type continental fraction should be higher
    # since some continental crust is submerged (continental shelves).
    #   0.1–0.5 → mostly ocean world (e.g. island chains)
    #   0.3–0.7 → Earth-like (balanced)
    #   0.6–0.9 → supercontinent / Pangaea-like
    continental_fraction_min: float = 0.28
    continental_fraction_max: float = 0.36
    # Latitude bias for crust-type assignment (0–1).  Higher values
    # concentrate continental crust near the equator.  Qualitatively,
    # faster-rotating planets have stronger Coriolis-driven latitude
    # banding → set higher (e.g. 0.8–0.9).  Tidally-locked or slowly
    # rotating bodies have weak latitude preference → set lower (0.3–0.5).
    lat_bias: float = 0.7

    # Sea level auto-calibration ("倒水")
    # True  = determine sea level from target land fraction (binary search on
    #         elevation × area distribution).  The elevation datum is shifted
    #         so the water surface becomes exactly 0 m, and the implied water
    #         budget is reported.
    # False = keep fixed bimodal base (continental_elevation_m /
    #         oceanic_elevation_m), sea level at 0 (current behavior).
    sea_level_auto: bool = True
    # Target emergent land fraction [0, 1] when sea_level_auto is True.
    # Earth ≈ 0.29 (29% of surface is dry land).
    #   < 0.1 → water world (only highlands emerge)
    #   0.25–0.35 → Earth-like balance
    #   > 0.5 → dry world (small seas, mostly land)
    target_land_fraction: float = 0.29
    # Sea level offset relative to the calibrated datum (metres). 0 = water
    # surface at exactly 0 m (default). −120 = glacial lowstand: cells in
    # (−120, 0] emerge as land.  Experimental knob for ice-age / critical-
    # strait scenarios; terrain post-processing and the climate land mask read
    # it, but frontend colour scales still assume a 0 m surface.
    sea_level_offset_m: float = 0.0

    # ---- Authored geography (continent anchoring, map/geography.py) ----
    # GeographySpec loaded from geography.yaml by the engine. None = pure
    # procedural (per-plate crust fractions). When present, crust is assigned
    # from a per-cell land-bias field via global threshold instead.
    geography: GeographySpec | None = None
    # Blend weight of the authored land-bias field vs fBm texture when
    # geography is present: score = w*field + (1-w)*fbm.
    # 1.0 = hard anchors (sharp), 0.0 = pure noise (anchors ignored).
    anchor_weight: float = 0.6
    # Low-frequency stochastic modulation of divergent-ridge and island-arc
    # uplift (0 = deterministic).  Multiplier range [1−v, 1+v]: some ridge/arc
    # segments emerge as main islands, neighbours stay submerged or become
    # satellite islets — hierarchical archipelagos instead of uniform chains.
    boundary_uplift_noise: float = 0.6
    # Multi-scale long-wavelength relief amplitude for continental interiors
    # (metres).  Analog of dynamic topography (mantle-driven ±500 m on Earth)
    # plus craton-scale swells; without it plate-interior continents are
    # unrealistically flat tablelands (nacrea 2026-08 feedback).
    continental_undulation_m: float = 600.0
    # Per-plate continental-crust floor (fraction of the plate's cells).
    # The global top-N crust threshold can leave whole plates (and their
    # neighbours) with near-zero continental crust — Earth has ~40% mostly-
    # oceanic plates, not 64%.  Plates whose mean authored bias < −0.3
    # (decisively authored ocean, e.g. the southern-ocean ring) are exempt;
    # the global land fraction is re-absorbed by sea-level calibration.
    crust_plate_floor: float = 0.10

    # ---- Tectonic time evolution (Cortial et al. 2019 §4–5) ----
    # Algorithm for time evolution.  "" = no evolution (static).
    #   "cortial2019" — velocity-field tectonic effects (subduction,
    #       collision, ridge, erosion, rifting) on fixed Voronoi boundaries.
    tectonic_algorithm: str = "cortial2019"
    # Number of time steps to simulate.  Cortial 2019 default: 125–250.
    tectonic_steps: int = 0
    # Time step duration in My.  0 = auto-scale from cell resolution
    # (Cortial 2019: δt = 2 My at 500K points; Dreamulator scales
    # automatically so the fastest plate moves ~3 cells/step).
    tectonic_dt_my: float = 0.0
    # ---- Plate rifting (Cortial 2019 §4.4) ----
    # Base Poisson rate λ₀ for plate rifting (Cortial 2019 §4.4).
    # P = λ·e^{-λ} where λ = λ₀ · A/A₀ (A₀ = world mean plate area).
    # 0 = disable rifting.  Per-step base probability × (A/A₀).
    #  With 3× cap boost + 10-step Voronoi interval, produces:
    #    0.01 → 30-40 plates at 100 steps, ~60 at 200 steps
    rift_base_rate: float = 0.01
    # Number of sub-plates created per rifting event (2-4 in the paper).
    rift_min_pieces: int = 2
    rift_max_pieces: int = 3

    # Terrain synthesis
    # Algorithm selector:
    #   "cortial2019_gaussian" — symmetric Gaussian boundary effects
    #   "cortial2019_asymmetric" — asymmetric profiles + hotspots + landforms
    terrain_algorithm: str = "cortial2019_asymmetric"
    continental_elevation_m: float = 850.0
    oceanic_elevation_m: float = -3800.0
    boundary_influence_km: float = 500.0
    # Dual-component boundary profile: narrow ridge (sharp crest) + wide shoulder
    # (plateau flanks).  Ridge sigma ~80 km gives recognisable linear ranges;
    # shoulder sigma defaults to boundary_influence_km for backward compatibility.
    # Set ridge_sigma_km = boundary_influence_km for the old single-Gaussian.
    boundary_ridge_sigma_km: float = 80.0  # narrow crest half-width (km)
    boundary_shoulder_strength: float = 0.3  # shoulder amplitude relative to ridge
    convergent_uplift_m: float = 4000.0
    divergent_depth_m: float = 2000.0
    # Per-plate random base elevation offset (creates inter-plate variation)
    plate_elevation_spread_m: float = 1500.0
    # Asymmetric mountain profile: 0=symmetric, 0.4=moderate, 1.0=extreme
    mountain_asymmetry: float = 0.4
    # Number of hotspot volcanic chains (0 = disabled)
    hotspot_count: int = 3
    # Continental shelf: width in km from coastline into ocean.
    # Earth average: 80 km; passive margins: 100–200 km.
    shelf_width_km: float = 150.0
    # Coastal plain: width in km from coastline inland for gentle
    # elevation ramp-down.  Earth average: 50–100 km.
    coastal_plain_width_km: float = 80.0
    # Maximum elevation (m) for coastal plain smoothing.  Cells above this
    # are treated as coastal mountains (e.g. Andes, Big Sur) and left
    # largely untouched.  The smoothing effect fades linearly from full
    # strength at sea level to zero at this elevation.
    coastal_plain_max_elevation_m: float = 500.0
    # Island arc height at O-O convergent boundaries (m).
    island_arc_height_m: float = 1500.0
    # Interior landforms: paleo-orogeny belts, rift valleys, cratonic basins.
    # 0 = disabled.  Base number of orogenic belts per continental plate.
    # Scales with plate interior area: larger plates get more belts
    # (1 additional belt per ~300 interior cells beyond the first).
    interior_orogeny_count: int = 2
    # Probability (0–1) that a segment along an orogenic belt becomes a
    # sunken intermontane basin (pull-apart / fault-block depression)
    # instead of an elevated ridge.
    interior_basin_chance: float = 0.25
    # Maximum subsidence depth (m) for intermontane basins.  Reference:
    # Turpan Depression −154 m, Fergana Valley ~400 m above sea level,
    # Basin and Range grabens 500–2000 m below surrounding ranges.
    interior_basin_depth_max_m: float = 600.0
    # Along-strike height variation strength (0 = uniform ridge, 1 = full
    # range).  Controls how much the orogenic belt amplitude varies along
    # its length via 1D noise modulation.
    interior_height_variation: float = 0.7
    # Interior lowlands: lower the deep continental interior (far from active
    # convergent boundaries) toward cratonic lowland elevation, so continents
    # read as "low plains + orogenic belts" instead of a uniform high plateau.
    # The bimodal continental base (850 m) has no interior-lowering stage, so
    # without this ~half of emergent land sits above 1000 m (Earth median land
    # ≈ 350–500 m).  Lowering is a smoothstep ramp from 0 at the convergent
    # (mountain-building) margin to full depth at *distance_scale_km* beyond
    # it, soft-clamped above *floor_m* (smooth maximum) so the calibrated
    # coastline is never crossed and the lowlands don't pile up at one value.
    interior_lowland_enabled: bool = True
    # Maximum lowering of the deep interior (m).  Applied only to continental
    # cells far from convergent boundaries (orogenic belts keep their relief).
    interior_lowland_depth_m: float = 600.0
    # Distance (km) from the nearest convergent boundary over which the
    # lowering ramps from 0 to full depth (smoothstep).
    interior_lowland_distance_scale_km: float = 1500.0
    # Minimum post-lowering elevation above the calibrated sea surface (m) —
    # the floor that keeps coastlines unchanged.  Orogenic/paleo-orogeny belts
    # added downstream can still rise above or carve below it.
    interior_lowland_floor_m: float = 50.0

    # Noise
    noise_scale: float = 2.0
    noise_octaves: int = 6
    noise_persistence: float = 0.5
    noise_lacunarity: float = 2.0
    # Anisotropic noise: stretch fBm along boundary strike direction.
    # 0 = isotropic; 0.3 = subtle ridges; 1.0 = strong linear features.
    noise_anisotropy: float = 0.3
    noise_amplitude_land_m: float = 900.0
    noise_amplitude_ocean_m: float = 450.0
    # Low-frequency regional noise (large-scale variation within plates)
    regional_noise_scale: float = 0.5  # much lower than detail noise_scale
    # Regional noise amplitudes should be ~1.5–2× the detail noise so
    # broad intra-plate swells are visible even on high-elevation plates
    # (plate_elevation_spread_m can push base elevation to 2000m+).
    regional_noise_amplitude_land_m: float = 1800.0
    regional_noise_amplitude_ocean_m: float = 1200.0

    # Climate simulation (Phase 3A: Energy Balance Model + wind + precipitation)
    # Stellar / orbital inputs for EBM
    stellar_luminosity_sol: float = 1.0  # L_sun (1.0 = Sun)
    stellar_temperature_k: float = 5772.0  # host star T_eff (K) for spectral ice albedo
    orbital_distance_au: float = 1.0  # AU
    axial_tilt_deg: float = 23.44  # obliquity
    # Atmosphere
    atmosphere_factor: float = 1.0  # greenhouse multiplier (1.0 = Earth, 0 = none)
    greenhouse_warming_K: float = 33.0  # additional greenhouse warming (K)
    lapse_rate_c_km: float = 6.5  # moist adiabatic lapse rate (°C/km)
    variable_lapse_rate: bool = False  # True = T-dependent Γ (tropical highlands warmer)
    lat_gradient_c: float = 40.0  # equator-to-pole temperature difference (°C)
    # Circulation cell boundaries (3A.3a).  Earth: Hadley 0–30°, Ferrel 30–60°,
    # Polar 60–90°.  Slow rotators (weak Coriolis) get an expanded Hadley cell
    # (~Ω^-1/2 scaling) and stronger meridional heat transport → smaller
    # lat_gradient_c.  Keep hadley_extent_deg < polar_cell_start_deg.
    hadley_extent_deg: float = 30.0  # Hadley cell poleward boundary (°)
    polar_cell_start_deg: float = 60.0  # Polar cell equatorward boundary (°)
    # 3A.3a: slow-rotation meridional transport
    auto_lat_gradient: bool = False  # True = compute lat_gradient_c from Ω (Kaspi 2015)
    # Earth reference equator-to-pole ΔT used by the Ω-scaled gradient
    # (lat_gradient_from_omega).  A calibration value (~45–50 °C for Earth),
    # not a derived constant — lower it to flatten the gradient (warm poles).
    lat_gradient_earth_c: float = 45.0
    diffusive_heat_transport: bool = False  # True = graph Laplacian heat diffusion
    # 1D Energy Balance Model (North 1975 / climlab.EBM): replaces the sin² +
    # graph-diffusion temperature profile with the steady-state solution of
    #   0 = D d/dx[(1−x²) dT/dx] + Q(x)(1−α) − (A + B·T),   x = sin(φ)
    # solved spectrally in Legendre polynomials.  Q(x) is the annual-mean
    # insolation (obliquity/orbit-dependent), D the meridional diffusion
    # (rotation-scaled by the caller), (A + B·T) the linear OLR (Budyko 1969).
    # A is calibrated internally so the global-mean temperature matches the
    # equilibrium + greenhouse chain — it is not a free knob.
    ebm_1d: bool = False  # True = solve the 1D EBM (else legacy sin² + diffusion)
    ebm_olr_b_wm2k: float = 2.0  # linear OLR coefficient B (W/m²/K)
    ebm_diffusion_wm2k: float = 0.35  # meridional diffusion D (W/m²/K), Earth ΔT ≈ 41 °C
    # Land-only meridional transport (the atmospheric fraction).  The ocean
    # carries ~30–40% of Earth's poleward heat transport, so land — with no
    # ocean currents — sees only the atmospheric ~60%: D_land ≈ 0.6·D_total.
    # A smaller D makes land follow the local insolation more closely: warmer
    # subtropics (BWh stays hot, fixing BWh→BWk) and colder poles — the
    # annual-mean continentality contrast that the 1D EBM's zonal mean washes out.
    ebm_diffusion_land_wm2k: float = 0.2
    # 3A.3: ice-albedo feedback
    ice_albedo_feedback: bool = False  # True = ice/snow → higher albedo → cooler
    ice_albedo_max_cooling_c: float = 8.0  # max additional cooling from full ice cover (°C)
    ice_albedo_threshold_c: float = -5.0  # T below which ice albedo activates
    # Wind
    wind_blocking_height_m: float = 3000.0  # mountains above this block wind
    # Precipitation
    evaporation_base_mm: float = 1000.0  # annual evaporation at 15 °C ocean (energy-limited)
    itcz_lag_days: int = 30  # ITCZ lag behind subsolar point (thermal inertia)
    # Mid-latitude storm-track amplitude (baroclinic cyclones), mm/yr at Earth
    # calibration (∇T=45°C, Ω=1, evap=1000).  The actual amplitude scales with
    # ∇T × Ω^0.3 × evap (see _compute_precipitation_bfs).  Set to 0 to disable
    # storm tracks (e.g. slow rotators in the single-Hadley-cell regime, where
    # baroclinic eddies do not form).
    storm_track_amplitude_mm: float = 900.0
    # Sub-planet hemisphere warming (for satellites tidally locked to a gas giant)
    sub_planet_warming_c: float = 0.0  # °C warming on the sub-planet side (e.g. 1.0 for nacrea)
    sub_planet_longitude_deg: float = 0.0  # longitude of the sub-planet point
    sub_planet_latitude_deg: float = 0.0  # latitude of the sub-planet point (0=equator)
    # Seasonality (3A.2): seasonal energy-balance model (North & Coakley 1979).
    # T_amp = ΔQ_ω(1−α) / sqrt(B_eff² + (ωC)²), with B_eff = B_rad + 6D — the
    # explicit meridional heat transport for the dominant quadrupole seasonal
    # mode, reusing ebm_olr_b_wm2k (B_rad) and ebm_diffusion_wm2k (D) — no
    # separate damping knob.  See engine/climate_seasonality.py + energy_balance.md §5.
    seasonal_land_heat_capacity: float = 2.0e7  # land+atmosphere (J/m²/K)
    seasonal_ocean_heat_capacity: float = 2.0e8  # ocean mixed layer 50 m (J/m²/K)
    seasonal_coastal_scale_km: float = 500.0  # maritime-moderation e-folding length
    # Seasonal ice-albedo feedback: a cell whose summer never melts keeps the
    # snow/ice albedo and reflects the summer insolation, shrinking its seasonal
    # amplitude — distinguishes the ice cap (EF, frozen) from the subarctic
    # (Dfc, melts each summer).
    seasonal_ice_albedo: bool = True
    ice_albedo_surface: float = 0.7  # snow/ice albedo
    seasonal_ice_threshold_c: float = 0.0  # summer T below which a cell stays frozen
    eccentricity: float = 0.0  # heliocentric orbit eccentricity (resolved from stellar.yaml)
    perihelion_day: float = 0.0  # day of perihelion passage (season phase reference)

    # Ocean
    ocean_currents_enabled: bool = True  # compute wind-driven surface currents (3A.3)
    ocean_drag_coefficient: float = 1.2e-3  # surface drag C_D
    ocean_mixed_layer_depth_m: float = 50.0  # H_ml (m)
    ocean_bottom_friction_s: float = 1e-6  # Stommel R (s⁻¹), tune for WBC ratio
    ocean_sst_advection_days: float = 70.0  # τ: surface SST adjustment time (days)
    ocean_temperature_diffusivity: float = 5.0  # D₀: wind-biased graph diffusion
    ocean_coastal_influence_km: float = 500.0
    ocean_upwelling_enabled: bool = True

    # Export
    export_width: int = 4096
    export_height: int = 2048

    # Isostasy — physical elevation limits (see isostasy_elevation_limits.md)
    isostasy_enabled: bool = False  # clip elevations beyond continental / oceanic limits
    isostasy_max_continental_elevation_m: float = 9000.0  # Earth ~8848; lower for higher-g planets
    isostasy_max_ocean_depth_m: float = 11500.0  # Earth ~11034; can be deeper for higher-g planets

    # Ocean floor age-depth subsidence (plate-cooling model).
    # Replaces the uniform oceanic base elevation with a depth gradient: ocean
    # floor deepens with distance from mid-ocean ridges (divergent boundaries)
    # following depth = ridge_depth + coeff · sqrt(age).
    # age ≈ distance_to_ridge_km / (spreading_rate_cm_yr × 10).  (×10 = cm/yr → km/Myr)
    ocean_age_depth_enabled: bool = False
    ocean_spreading_rate_cm_yr: float = 5.0  # half-rate, Earth: 1–5 cm/yr
    ocean_ridge_depth_m: float = 2500.0  # depth at mid-ocean ridge (age=0)
    ocean_subsidence_coeff: float = 350.0  # sqrt(age) multiplier, Earth ≈ 350
    ocean_max_age_myr: float = 100.0  # steady-state age (lithosphere equilibrates)
    ocean_max_age_depth_m: float = 5500.0  # max depth from cooling alone (no trench)

    # Fluvial erosion / sediment routing was removed (2026-08-26): at the 200k
    # (51 km) geological-engine scale real river valleys (5–50 km wide) are all
    # sub-grid, so fluvial erosion there produced one-cell-wide artificial
    # gullies; river carving belongs to the final Gaea local-refinement step
    # (metre scale).  The river NETWORK (flow routing + river vector layer) is
    # kept — see hydrology.py / river_generator.py.

    @classmethod
    def from_yaml(cls, path: Path) -> TerrainPipelineConfig:
        """Load configuration from a YAML file."""
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TerrainPipelineConfig:
        """Create config from a dictionary (e.g. parsed YAML).

        Supports nested ``planet:``, ``terrain:``, ``plates:``, ``noise:``,
        ``climate:``, ``export:`` sections or flat keys.
        """
        flat: dict[str, Any] = {}

        # Flatten nested sections
        secs = (
            "planet",
            "terrain",
            "plates",
            "noise",
            "climate",
            "export",
            "isostasy",
            "ocean",
            "tidal",
        )
        for section in secs:
            if section in data and isinstance(data[section], dict):
                for k, v in data[section].items():
                    # Prefix section keys to match dataclass field names
                    if section in ("isostasy", "ocean", "tidal"):
                        flat[f"{section}_{k}"] = v
                    else:
                        flat[k] = v

        # Top-level keys override sections
        for k, v in data.items():
            if k not in secs:
                flat[k] = v

        # Map common aliases
        alias_map = {
            "num_cells": "num_nodes",
            "voronoi_num_cells": "num_nodes",
            "plate_speed_min_cm_yr": "_plate_speed_min",
            "plate_speed_max_cm_yr": "_plate_speed_max",
        }
        for old, new in alias_map.items():
            if old in flat:
                flat[new] = flat.pop(old)

        # Reconstruct speed range tuple
        smin = flat.pop("_plate_speed_min", None)
        smax = flat.pop("_plate_speed_max", None)
        if smin is not None and smax is not None:
            flat["plate_speed_range_cm_yr"] = (smin, smax)

        # Filter to known fields
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in flat.items() if k in known}

        return cls(**filtered)

    @classmethod
    def from_planet_config(cls, planet_data: dict[str, Any]) -> TerrainPipelineConfig:
        """Create config from a dreamulator Planet model dict.

        Extracts relevant fields from ``planets.yaml`` planet entries.
        """
        cfg = cls()
        if "radius_km" in planet_data:
            cfg.radius_km = planet_data["radius_km"]
        if "gravity_m_s2" in planet_data:
            cfg.gravity_m_s2 = planet_data["gravity_m_s2"]
        if "rotation_period_days" in planet_data:
            cfg.rotation_period_days = planet_data["rotation_period_days"]
        if "seed" in planet_data:
            cfg.seed = planet_data["seed"]
        # terrain sub-section
        terrain = planet_data.get("terrain", {})
        if isinstance(terrain, dict):
            for k, v in terrain.items():
                if hasattr(cfg, k):
                    setattr(cfg, k, v)
        return cfg


# ---------------------------------------------------------------------------
# Spherical Coordinate Utilities
# ---------------------------------------------------------------------------


def lonlat_to_xyz(
    lon_deg: np.ndarray | float,
    lat_deg: np.ndarray | float,
    radius: float = 1.0,
) -> tuple[np.ndarray | float, np.ndarray | float, np.ndarray | float]:
    """Convert geographic coordinates (degrees) to 3D Cartesian on sphere.

    Convention: y-axis points north (up).

    Args:
        lon_deg: Longitude in degrees [-180, 180].
        lat_deg: Latitude in degrees [-90, 90].
        radius: Sphere radius.

    Returns:
        Tuple of (x, y, z).
    """
    lon = np.radians(lon_deg)
    lat = np.radians(lat_deg)
    cos_lat = np.cos(lat)
    x = radius * cos_lat * np.cos(lon)
    y = radius * np.sin(lat)
    z = radius * cos_lat * np.sin(lon)
    return x, y, z


def xyz_to_lonlat(
    x: np.ndarray | float,
    y: np.ndarray | float,
    z: np.ndarray | float,
) -> tuple[np.ndarray | float, np.ndarray | float]:
    """Convert 3D Cartesian to geographic coordinates (degrees).

    Returns:
        Tuple of (lon_deg, lat_deg).
    """
    r = np.sqrt(x * x + y * y + z * z)
    lat = np.degrees(np.arcsin(np.clip(y / np.maximum(r, 1e-12), -1, 1)))
    lon = np.degrees(np.arctan2(z, x))
    return lon, lat


def angular_distance_xyz(
    xyz1: np.ndarray,
    xyz2: np.ndarray,
) -> np.ndarray:
    """Angular distance (radians) between unit vectors.

    Args:
        xyz1: Shape (..., 3).
        xyz2: Shape (..., 3).

    Returns:
        Angular distance in radians.
    """
    dot = np.clip(np.sum(xyz1 * xyz2, axis=-1), -1, 1)
    return np.asarray(np.arccos(dot))


def smooth_step(
    x: np.ndarray,
    edge0: float = 0.0,
    edge1: float = 1.0,
) -> np.ndarray:
    """Hermite smoothstep: 0 below edge0, 1 above edge1, smooth between."""
    t = np.clip((x - edge0) / (edge1 - edge0), 0, 1)
    return t * t * (3 - 2 * t)


def make_equirect_grid(
    width: int,
    height: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Create latitude/longitude grids for equirectangular projection.

    Returns:
        (lat_grid, lon_grid) each shape (height, width), in radians.
        lat: +π/2 (north) at row 0 → -π/2 (south) at row H-1.
        lon: -π at col 0 → +π at col W-1.
    """
    lon_1d = np.linspace(-np.pi, np.pi, width, endpoint=False)
    lat_1d = np.linspace(np.pi / 2, -np.pi / 2, height)
    lon_grid, lat_grid = np.meshgrid(lon_1d, lat_1d)
    return lat_grid, lon_grid
