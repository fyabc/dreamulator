"""Terrain pipeline configuration and spherical coordinate utilities.

Shared types used across all terrain pipeline modules (cvt_mesh, plate_generator,
boundary_detector, terrain_synthesizer, export, terrain_pipeline).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import yaml


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

    # CVT mesh generation
    num_nodes: int = 100_000
    jitter_sigma: float = 0.3
    lloyd_iterations: int = 8

    # Tectonic plates
    num_plates: int = 20
    plate_speed_range_cm_yr: tuple[float, float] = (1.0, 10.0)
    # Algorithm for initial plate partition:
    #   "cortial2019" — Poisson-disc + spherical Voronoi BFS (Cortial et al. 2019 §3)
    plate_algorithm: str = "cortial2019"
    # Fraction of boundary cells to randomly flip (0 = straight Voronoi
    # edges, 0.05–0.15 = natural organic boundaries).
    # Follows Cortial et al. (2019) "noise-warped geodetic distance".
    boundary_noise: float = 0.10
    # Per-plate continental fraction range.  Each plate is assigned a random
    # continental cell ratio uniformly in [min, max].  Earth ≈ 0.29 land
    # (emergent), but the crust-type continental fraction should be higher
    # since some continental crust is submerged (continental shelves).
    #   0.1–0.5 → mostly ocean world (e.g. island chains)
    #   0.3–0.7 → Earth-like (balanced)
    #   0.6–0.9 → supercontinent / Pangaea-like
    continental_fraction_min: float = 0.25
    continental_fraction_max: float = 0.65

    # ---- Tectonic time evolution (Cortial et al. 2019 §4–5) ----
    # Algorithm for time evolution.  "" = no evolution (static).
    #   "cortial2019" — velocity-field tectonic effects (subduction,
    #       collision, ridge, erosion) on fixed Voronoi boundaries.
    tectonic_algorithm: str = ""
    # Number of time steps to simulate.  Cortial 2019 default: 125–250.
    tectonic_steps: int = 0
    # Time step duration in My.  0 = auto-scale from cell resolution
    # (Cortial 2019: δt = 2 My at 500K points; Dreamulator scales
    # automatically so the fastest plate moves ~3 cells/step).
    tectonic_dt_my: float = 0.0

    # Terrain synthesis
    # Algorithm selector:
    #   "cortial2019_gaussian" — symmetric Gaussian boundary effects
    #   "cortial2019_asymmetric" — asymmetric profiles + hotspots + landforms
    terrain_algorithm: str = "cortial2019_asymmetric"
    continental_elevation_m: float = 850.0
    oceanic_elevation_m: float = -3800.0
    boundary_influence_km: float = 500.0
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

    # Export
    export_width: int = 4096
    export_height: int = 2048

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
        ``export:`` sections or flat keys.
        """
        flat: dict[str, Any] = {}

        # Flatten nested sections
        for section in ("planet", "terrain", "plates", "noise", "export"):
            if section in data and isinstance(data[section], dict):
                flat.update(data[section])

        # Top-level keys override sections
        for k, v in data.items():
            if k not in ("planet", "terrain", "plates", "noise", "export"):
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
    return np.arccos(dot)


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
