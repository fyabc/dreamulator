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

    # Terrain synthesis
    continental_elevation_m: float = 850.0
    oceanic_elevation_m: float = -3800.0
    boundary_influence_km: float = 500.0
    convergent_uplift_m: float = 4000.0
    divergent_depth_m: float = 2000.0

    # Noise
    noise_scale: float = 2.0
    noise_octaves: int = 6
    noise_persistence: float = 0.5
    noise_lacunarity: float = 2.0
    noise_amplitude_land_m: float = 600.0
    noise_amplitude_ocean_m: float = 300.0

    # Sea level
    sea_level_m: float = 0.0

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
