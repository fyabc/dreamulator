#!/usr/bin/env python3
"""
Procedural planet heightmap generator with spherical coordinate computation.

Generates a base heightmap for Gaea import or direct visualization.
All terrain synthesis operates on the sphere; equirectangular projection
and cube-map faces are computed only at the export stage.

Architecture:
    1. Continent field: elliptical Gaussian features on sphere
    2. Base elevation: continent field → elevation via power-law transfer
    3. Tidal deformation: permanent crustal bulge (tidally-locked moons)
    4. Tectonic plates: Spherical Voronoi tessellation
    5. Boundary effects: convergent/divergent/transform elevation
    6. Hotspots: Gaussian volcanic uplift
    7. User features: Gaussian plateaus, rifts, etc.
    8. Noise detail: multi-octave 3D Simplex fBm on sphere

Usage:
    python generate_planet_heightmap.py --config path/to/heightmap_config.yaml --output output/
    python generate_planet_heightmap.py --config cfg.yaml --output out/ --resolution 4096 2048
    python generate_planet_heightmap.py --config cfg.yaml --output out/ --cubemap --preview
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

import numpy as np
import yaml
from PIL import Image

try:
    from scipy.spatial import SphericalVoronoi
except ImportError:
    print("ERROR: scipy required. Install: pip install scipy", file=sys.stderr)
    sys.exit(1)

try:
    import opensimplex

    _HAS_OPENSIMPLEX = True
except ImportError:
    _HAS_OPENSIMPLEX = False

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.colors as mcolors

    _HAS_MATPLOTLIB = True
except ImportError:
    _HAS_MATPLOTLIB = False


# ═══════════════════════════════════════════════════════════════════════════════
# Spherical Math Utilities
# ═══════════════════════════════════════════════════════════════════════════════


def lat_lon_to_xyz(
    lat: np.ndarray, lon: np.ndarray, radius: float = 1.0
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Convert geographic coordinates to 3D Cartesian (unit sphere).

    Args:
        lat: Latitude in radians (-π/2 to π/2).
        lon: Longitude in radians (-π to π).
        radius: Sphere radius.

    Returns:
        Tuple of (x, y, z) arrays.  y = up (north pole).
    """
    cos_lat = np.cos(lat)
    x = radius * cos_lat * np.cos(lon)
    y = radius * np.sin(lat)
    z = radius * cos_lat * np.sin(lon)
    return x, y, z


def xyz_to_lat_lon(
    x: np.ndarray, y: np.ndarray, z: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Convert 3D Cartesian to geographic coordinates.

    Returns:
        Tuple of (lat, lon) in radians.
    """
    r = np.sqrt(x * x + y * y + z * z)
    lat = np.arcsin(np.clip(y / np.maximum(r, 1e-12), -1, 1))
    lon = np.arctan2(z, x)
    return lat, lon


def angular_distance(
    lat1: np.ndarray,
    lon1: np.ndarray,
    lat2: float,
    lon2: float,
) -> np.ndarray:
    """Great-circle angular distance (radians) via Haversine."""
    dlat = lat1 - lat2
    dlon = lon1 - lon2
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def angular_distance_xyz(xyz1: np.ndarray, xyz2: np.ndarray) -> np.ndarray:
    """Angular distance between unit vectors.  xyz shape (..., 3)."""
    dot = np.clip(np.sum(xyz1 * xyz2, axis=-1), -1, 1)
    return np.arccos(dot)


def smooth_step(x: np.ndarray, edge0: float = 0.0, edge1: float = 1.0) -> np.ndarray:
    """Hermite smoothstep: 0 below edge0, 1 above edge1, smooth between."""
    t = np.clip((x - edge0) / (edge1 - edge0), 0, 1)
    return t * t * (3 - 2 * t)


def make_equirect_grid(
    width: int, height: int
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


# ═══════════════════════════════════════════════════════════════════════════════
# Configuration Dataclasses
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class ContinentFeature:
    """Elliptical Gaussian terrain feature on the sphere."""

    name: str
    lat_deg: float  # center latitude (degrees)
    lon_deg: float  # center longitude (degrees)
    semi_lon_deg: float  # E-W semi-axis (degrees of longitude)
    semi_lat_deg: float  # N-S semi-axis (degrees of latitude)
    amplitude_m: float  # peak elevation contribution (meters; negative = depression)
    rotation_deg: float = 0.0  # rotation of ellipse axes (degrees)
    falloff_power: float = 2.5  # sharpness of edge (higher = sharper)


@dataclass
class HotspotFeature:
    """Mantle plume hotspot."""

    name: str
    lat_deg: float
    lon_deg: float
    radius_km: float  # influence radius
    amplitude_m: float  # peak uplift
    has_caldera: bool = False  # central depression
    caldera_radius_km: float = 0.0
    caldera_depth_m: float = 0.0


@dataclass
class PlateSeed:
    """Pre-defined tectonic plate seed point."""

    name: str
    lat_deg: float
    lon_deg: float
    plate_type: str  # "continental" | "oceanic"
    velocity_cm_yr: float = 5.0
    direction_deg: float = 0.0  # compass bearing of motion


@dataclass
class PlanetConfig:
    """Full planet configuration for heightmap generation."""

    # Identity
    name: str = "Planet"
    seed: int = 42

    # Physical
    radius_km: float = 6371.0
    gravity_m_s2: float = 9.81
    rotation_period_days: float = 1.0

    # Elevation
    elevation_min_m: float = -11000.0
    elevation_max_m: float = 9000.0
    sea_level_m: float = 0.0

    # Continent field
    continent_elev_m: float = 3000.0  # characteristic continent height
    ocean_depth_m: float = 5000.0  # characteristic ocean depth
    continent_elev_power: float = 0.7  # power-law exponent for continent profile
    shelf_fraction: float = 0.15  # continental shelf width as fraction of coast zone
    coast_threshold_fraction: float = 0.10  # coast threshold = continent_elev_m × this

    # Tidal deformation (for tidally-locked bodies)
    tidal_bulge_amplitude_m: float = 0.0
    tidal_bulge_lon_deg: float = 0.0  # sub-primary longitude

    # Tectonic plates
    num_plates: int = 20
    plate_seeds: list = field(default_factory=list)
    boundary_influence_km: float = 500.0
    convergent_elev_m: float = 4000.0
    divergent_elev_m: float = -2000.0

    # Noise
    noise_scale: float = 2.0
    noise_octaves: int = 6
    noise_persistence: float = 0.5
    noise_lacunarity: float = 2.0
    continent_noise_amp_m: float = 600.0
    ocean_noise_amp_m: float = 300.0

    # Output
    width: int = 2048
    height: int = 1024

    # Features
    continent_features: list = field(default_factory=list)
    hotspots: list = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════════
# Noise Utilities
# ═══════════════════════════════════════════════════════════════════════════════


def generate_fbm_3d(
    lat_grid: np.ndarray,
    lon_grid: np.ndarray,
    seed: int,
    noise_scale: float = 2.0,
    octaves: int = 6,
    persistence: float = 0.5,
    lacunarity: float = 2.0,
) -> np.ndarray:
    """Multi-octave 3D Simplex noise on the sphere.

    Each octave is generated at a resolution appropriate for its frequency,
    then upsampled to the full grid.  This avoids computing millions of
    noise evaluations for low-frequency octaves.

    Args:
        lat_grid: 2D array of latitudes (radians).
        lon_grid: 2D array of longitudes (radians).
        seed: Random seed.
        noise_scale: Base spatial frequency on the unit sphere.
        octaves: Number of noise octaves.
        persistence: Amplitude decay per octave.
        lacunarity: Frequency growth per octave.

    Returns:
        2D array of noise values, shape = lat_grid.shape, range ≈ [-1, 1].
    """
    if not _HAS_OPENSIMPLEX:
        print("WARNING: opensimplex not available, using fallback noise", file=sys.stderr)
        return _fallback_fbm(lat_grid, lon_grid, seed, noise_scale, octaves,
                             persistence, lacunarity)

    h, w = lat_grid.shape
    result = np.zeros((h, w), dtype=np.float64)
    amplitude = 1.0
    frequency = noise_scale

    for i in range(octaves):
        # Resolution appropriate for this octave's frequency.
        # Cap at 512×256 to keep element-wise noise loop manageable;
        # higher octaves are upsampled via cubic interpolation.
        res_factor = max(4, int(frequency * 40))
        octave_w = min(w, max(64, min(512, res_factor * 4)))
        octave_h = min(h, max(32, min(256, res_factor * 2)))

        # Generate grid at octave resolution
        o_lon = np.linspace(-np.pi, np.pi, octave_w, endpoint=False)
        o_lat = np.linspace(np.pi / 2, -np.pi / 2, octave_h)
        o_lon_g, o_lat_g = np.meshgrid(o_lon, o_lat)

        # 3D Cartesian on unit sphere
        cos_lat = np.cos(o_lat_g)
        ox = cos_lat * np.cos(o_lon_g)
        oy = np.sin(o_lat_g)
        oz = cos_lat * np.sin(o_lon_g)

        # Sample 3D Simplex noise element-wise
        # (noise3array creates a meshgrid output, not element-wise, so we
        # must iterate point-by-point via _compute_noise_elementwise)
        noise = _compute_noise_elementwise(ox, oy, oz, frequency, seed + i * 1000)

        # Upsample to full resolution
        if noise.shape != (h, w):
            from scipy.ndimage import zoom as ndzoom

            zoom_h = h / noise.shape[0]
            zoom_w = w / noise.shape[1]
            noise = ndzoom(noise, (zoom_h, zoom_w), order=3)
            # Trim or pad if zoom produces slightly wrong size
            noise = noise[:h, :w]

        result += amplitude * noise
        amplitude *= persistence
        frequency *= lacunarity

    # Normalize to [-1, 1]
    max_val = np.max(np.abs(result))
    if max_val > 0:
        result /= max_val

    return result


def _compute_noise_elementwise(
    x: np.ndarray,
    y: np.ndarray,
    z: np.ndarray,
    frequency: float,
    seed: int,
) -> np.ndarray:
    """Compute opensimplex noise element-wise (vectorized via list comprehension)."""
    opensimplex.seed(seed)
    flat_x = (x * frequency).ravel()
    flat_y = (y * frequency).ravel()
    flat_z = (z * frequency).ravel()

    # Process in chunks for memory efficiency
    chunk_size = 50000
    n = len(flat_x)
    result = np.empty(n, dtype=np.float64)

    for start in range(0, n, chunk_size):
        end = min(start + chunk_size, n)
        for j in range(start, end):
            result[j] = opensimplex.noise3(flat_x[j], flat_y[j], flat_z[j])

    return result.reshape(x.shape)


def _fallback_fbm(
    lat_grid, lon_grid, seed, noise_scale, octaves, persistence, lacunarity
):
    """Simple value-noise fallback when opensimplex is unavailable."""
    rng = np.random.default_rng(seed)
    h, w = lat_grid.shape
    result = np.zeros((h, w))
    amplitude = 1.0
    frequency = noise_scale

    for _ in range(octaves):
        noise = rng.standard_normal((h, w))
        from scipy.ndimage import gaussian_filter

        sigma = max(1, w / (frequency * 10))
        noise = gaussian_filter(noise, sigma=sigma)
        result += amplitude * noise
        amplitude *= persistence
        frequency *= lacunarity

    max_val = np.max(np.abs(result))
    if max_val > 0:
        result /= max_val
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Spherical Heightmap Generator
# ═══════════════════════════════════════════════════════════════════════════════


class SphericalHeightmapGenerator:
    """Generates planet heightmaps on the sphere."""

    def __init__(self, config: PlanetConfig):
        self.config = config
        self.rng = np.random.default_rng(config.seed)

        # Precompute grid
        self.lat_grid, self.lon_grid = make_equirect_grid(config.width, config.height)
        self.x_grid, self.y_grid, self.z_grid = lat_lon_to_xyz(
            self.lat_grid, self.lon_grid
        )
        self.xyz_grid = np.stack([self.x_grid, self.y_grid, self.z_grid], axis=-1)

    # ── Continent Field ──────────────────────────────────────────────────────

    def _compute_continent_field(self) -> np.ndarray:
        """Sum of elliptical Gaussian features on the sphere."""
        field_val = np.zeros_like(self.lat_grid)

        for feat in self.config.continent_features:
            field_val += self._elliptical_gaussian(
                feat_lat_deg=feat.lat_deg,
                feat_lon_deg=feat.lon_deg,
                semi_lon_deg=feat.semi_lon_deg,
                semi_lat_deg=feat.semi_lat_deg,
                amplitude=feat.amplitude_m,
                rotation_deg=feat.rotation_deg,
                falloff_power=feat.falloff_power,
            )

        return field_val

    def _elliptical_gaussian(
        self,
        feat_lat_deg: float,
        feat_lon_deg: float,
        semi_lon_deg: float,
        semi_lat_deg: float,
        amplitude: float,
        rotation_deg: float = 0.0,
        falloff_power: float = 2.5,
    ) -> np.ndarray:
        """Elliptical Gaussian feature on the sphere.

        Uses angular distance with separate E-W and N-S scales,
        and a power-law falloff for sharper edges than a pure Gaussian.
        """
        lat0 = np.radians(feat_lat_deg)
        lon0 = np.radians(feat_lon_deg)
        semi_lon = np.radians(semi_lon_deg)
        semi_lat = np.radians(semi_lat_deg)
        rot = np.radians(rotation_deg)

        # Angular offsets from center
        dlon = self.lon_grid - lon0
        # Wrap longitude difference to [-π, π]
        dlon = (dlon + np.pi) % (2 * np.pi) - np.pi
        dlat = self.lat_grid - lat0

        # Apply rotation
        if abs(rot) > 1e-6:
            cos_r = np.cos(rot)
            sin_r = np.sin(rot)
            # Weight by cos(lat) for correct angular metric
            dlon_weighted = dlon * np.cos(self.lat_grid)
            dlat_rot = cos_r * dlat + sin_r * dlon_weighted
            dlon_rot = -sin_r * dlat + cos_r * dlon_weighted
            # Un-weight longitude
            dlon_rot = dlon_rot / np.maximum(np.cos(self.lat_grid), 0.01)
            dlat = dlat_rot
            dlon = dlon_rot

        # Normalized elliptical distance
        r = np.sqrt((dlon / semi_lon) ** 2 + (dlat / semi_lat) ** 2)

        # Power-law falloff (sharper than Gaussian)
        return amplitude * np.exp(-(r ** falloff_power))

    # ── Base Elevation ───────────────────────────────────────────────────────

    def _compute_base_elevation(self, continent_field: np.ndarray) -> np.ndarray:
        """Convert continent field to elevation via power-law transfer.

        Positive field values → continent (with power-law profile, flat
        interior, steep coast).  Negative values → ocean floor.
        A small threshold prevents Gaussian tails from creating spurious land.
        """
        c = self.config
        elev = np.zeros_like(continent_field)

        # Threshold: continent field must exceed this to be land
        # Prevents Gaussian tails from creating unrealistically large continents
        coast_threshold = c.continent_elev_m * c.coast_threshold_fraction

        # Continent (field > threshold)
        pos_mask = continent_field > coast_threshold
        pos_field = continent_field[pos_mask]
        # Normalize: threshold → 0, max → 1
        pos_norm = (pos_field - coast_threshold) / max(c.continent_elev_m - coast_threshold, 1)
        pos_norm = np.clip(pos_norm, 0, 1)
        # Power-law: more lowlands, fewer mountains
        elev[pos_mask] = (
            c.sea_level_m + c.continent_elev_m * np.power(pos_norm, c.continent_elev_power)
        )

        # Shallow coast / continental shelf (0 < field < threshold)
        shelf_mask = (continent_field > 0) & (~pos_mask)
        shelf_field = continent_field[shelf_mask]
        shelf_norm = shelf_field / max(coast_threshold, 1)
        elev[shelf_mask] = c.sea_level_m + 50 * shelf_norm  # very shallow

        # Ocean (field <= 0)
        neg_mask = continent_field <= 0
        neg_field = np.clip(-continent_field[neg_mask], 0, None)
        neg_norm = neg_field / max(c.ocean_depth_m, 1)
        neg_norm = np.clip(neg_norm, 0, 1)
        elev[neg_mask] = c.sea_level_m - c.ocean_depth_m * neg_norm

        return elev

    # ── Tidal Deformation ────────────────────────────────────────────────────

    def _compute_tidal_deformation(self) -> np.ndarray:
        """Permanent crustal tidal bulge for tidally-locked bodies.

        Uses the P₂ Legendre polynomial: (3cos²θ - 1)/2
        which creates bulges at both sub-primary and anti-primary points,
        and depressions at 90° from the tidal axis.
        """
        amp = self.config.tidal_bulge_amplitude_m
        if abs(amp) < 1:
            return np.zeros_like(self.lat_grid)

        lon0 = np.radians(self.config.tidal_bulge_lon_deg)
        # Angle from tidal axis (sub-primary point at equator)
        dist = angular_distance(self.lat_grid, self.lon_grid, 0, lon0)
        cos_d = np.cos(dist)
        # P₂ Legendre: (3cos²θ - 1)/2 → peaks at 0° and 180°, trough at 90°
        bulge = amp * (3 * cos_d**2 - 1) / 2
        return bulge

    # ── Tectonic Plates ──────────────────────────────────────────────────────

    def _generate_plates(self) -> tuple[SphericalVoronoi, np.ndarray, dict]:
        """Generate tectonic plates via Spherical Voronoi.

        Returns:
            (sv, plate_map, plate_info) where:
            - sv: SphericalVoronoi object
            - plate_map: 2D array of plate indices, shape = grid
            - plate_info: dict with plate metadata
        """
        n_plates = self.config.num_plates
        seeds = self.config.plate_seeds

        # Generate plate seed points
        if len(seeds) >= n_plates:
            points = np.array(
                [
                    lat_lon_to_xyz(np.radians(s.lat_deg), np.radians(s.lon_deg))
                    for s in seeds[:n_plates]
                ]
            )
            points = np.array(list(zip(*points))).T  # (N, 3)
        else:
            # Place pre-defined seeds, fill rest with random
            points_list = []
            for s in seeds:
                x, y, z = lat_lon_to_xyz(np.radians(s.lat_deg), np.radians(s.lon_deg))
                points_list.append(
                    [float(x) if isinstance(x, np.ndarray) else x,
                     float(y) if isinstance(y, np.ndarray) else y,
                     float(z) if isinstance(z, np.ndarray) else z]
                )
            # Fill remaining with random points on sphere
            n_remaining = n_plates - len(points_list)
            for _ in range(n_remaining):
                vec = self.rng.standard_normal(3)
                vec /= np.linalg.norm(vec)
                points_list.append(vec.tolist())
            points = np.array(points_list)

        # Compute Spherical Voronoi
        sv = SphericalVoronoi(points, radius=1.0, center=np.zeros(3))
        sv.sort_vertices_of_regions()

        # Assign each grid point to nearest plate seed
        # Efficient: use dot product (higher = closer on unit sphere)
        # grid_xyz: (H, W, 3), points: (N, 3)
        grid_flat = self.xyz_grid.reshape(-1, 3)
        dots = grid_flat @ points.T  # (H*W, N)
        nearest = np.argmax(dots, axis=1)
        plate_map = nearest.reshape(self.lat_grid.shape)

        # Build plate info
        plate_info = {}
        plate_types = {}
        for i, s in enumerate(seeds[:n_plates]):
            plate_types[i] = s.plate_type
            plate_info[i] = {
                "name": s.name,
                "type": s.plate_type,
                "velocity_cm_yr": s.velocity_cm_yr,
                "direction_deg": s.direction_deg,
                "seed_lat_deg": s.lat_deg,
                "seed_lon_deg": s.lon_deg,
            }
        for i in range(len(seeds), n_plates):
            plate_types[i] = "oceanic"
            lat_r, lon_r = xyz_to_lat_lon(points[i, 0], points[i, 1], points[i, 2])
            plate_info[i] = {
                "name": f"plate_{i}",
                "type": "oceanic",
                "velocity_cm_yr": float(self.rng.uniform(3, 10)),
                "direction_deg": float(self.rng.uniform(0, 360)),
                "seed_lat_deg": float(np.degrees(lat_r)),
                "seed_lon_deg": float(np.degrees(lon_r)),
            }

        # Compute Euler poles for each plate
        for i in range(n_plates):
            info = plate_info[i]
            direction = np.radians(info["direction_deg"])
            speed = info["velocity_cm_yr"]
            # Angular velocity = speed / radius
            omega = speed * 0.01 / (self.config.radius_km * 1000)  # rad/year
            # Euler pole perpendicular to motion direction at plate center
            lat_c = np.radians(info["seed_lat_deg"])
            lon_c = np.radians(info["seed_lon_deg"])
            # Simple model: Euler pole at plate center rotated 90° from motion
            euler_lat = lat_c + np.pi / 2 * np.cos(direction)
            euler_lon = lon_c + np.pi / 2 * np.sin(direction) / max(np.cos(lat_c), 0.1)
            euler_lat = np.clip(euler_lat, -np.pi / 2, np.pi / 2)
            euler_xyz = lat_lon_to_xyz(euler_lat, euler_lon)
            euler_vec = np.array(
                [float(euler_xyz[0]) if isinstance(euler_xyz[0], np.ndarray) else euler_xyz[0],
                 float(euler_xyz[1]) if isinstance(euler_xyz[1], np.ndarray) else euler_xyz[1],
                 float(euler_xyz[2]) if isinstance(euler_xyz[2], np.ndarray) else euler_xyz[2]]
            )
            euler_vec /= np.linalg.norm(euler_vec)
            info["euler_pole"] = euler_vec.tolist()
            info["omega_rad_yr"] = omega

        return sv, plate_map, plate_info

    # ── Boundary Effects ─────────────────────────────────────────────────────

    def _compute_boundary_effects(
        self,
        sv: SphericalVoronoi,
        plate_map: np.ndarray,
        plate_info: dict,
    ) -> tuple[np.ndarray, list]:
        """Compute elevation adjustments near plate boundaries.

        Extracts boundaries from SphericalVoronoi regions (shared edges
        between adjacent cells) and applies Gaussian elevation effects.

        Returns:
            (boundary_elev, boundary_list) where boundary_list contains
            metadata about each boundary segment.
        """
        influence_rad = self.config.boundary_influence_km / self.config.radius_km

        # Build edge → cell mapping from Voronoi regions
        # Each region[i] is a list of vertex indices forming cell i's polygon
        edge_to_cells: dict[tuple[int, int], list[int]] = {}
        for cell_idx, region in enumerate(sv.regions):
            if not region or region[0] == -1:
                continue
            n = len(region)
            for j in range(n):
                v1 = region[j]
                v2 = region[(j + 1) % n]
                edge_key = (min(v1, v2), max(v1, v2))
                if edge_key not in edge_to_cells:
                    edge_to_cells[edge_key] = []
                edge_to_cells[edge_key].append(cell_idx)

        # Find boundary edges (shared by exactly 2 cells)
        boundary_points = []  # (xyz, plate_a, plate_b, btype, conv_rate)
        boundaries_meta = []
        seen_pairs: set[tuple[int, int]] = set()

        for (v1, v2), cells in edge_to_cells.items():
            if len(cells) != 2:
                continue
            p1_idx, p2_idx = cells[0], cells[1]
            pair_key = (min(p1_idx, p2_idx), max(p1_idx, p2_idx))

            # Get the two edge vertex positions
            vert1 = sv.vertices[v1]
            vert2 = sv.vertices[v2]
            mid_vert = (vert1 + vert2) / 2
            mid_vert /= np.linalg.norm(mid_vert)

            # Classify boundary (once per plate pair for metadata)
            if pair_key not in seen_pairs:
                seen_pairs.add(pair_key)
                info_a = plate_info.get(p1_idx, {})
                info_b = plate_info.get(p2_idx, {})
                conv_rate = self._compute_convergence_rate(mid_vert, info_a, info_b)

                if conv_rate > 0.01:
                    btype = "convergent"
                elif conv_rate < -0.01:
                    btype = "divergent"
                else:
                    btype = "transform"

                boundaries_meta.append({
                    "plate_a": p1_idx,
                    "plate_b": p2_idx,
                    "type": btype,
                    "convergence_rate": float(conv_rate),
                    "midpoint_lat": float(np.degrees(np.arcsin(np.clip(mid_vert[1], -1, 1)))),
                    "midpoint_lon": float(np.degrees(np.arctan2(mid_vert[2], mid_vert[0]))),
                })
            else:
                # Reuse the already-computed type for this plate pair
                btype = next(
                    (b["type"] for b in boundaries_meta
                     if (b["plate_a"] == pair_key[0] and b["plate_b"] == pair_key[1])
                     or (b["plate_a"] == pair_key[1] and b["plate_b"] == pair_key[0])),
                    "transform",
                )
                info_a = plate_info.get(p1_idx, {})
                info_b = plate_info.get(p2_idx, {})
                conv_rate = abs(self._compute_convergence_rate(mid_vert, info_a, info_b))

            # Add both edge vertices as boundary sample points
            for v in [vert1, vert2, mid_vert]:
                boundary_points.append((v, p1_idx, p2_idx, btype, abs(conv_rate) if isinstance(conv_rate, float) else 1.0))

        if not boundary_points:
            return np.zeros_like(self.lat_grid), boundaries_meta

        # Compute boundary effects at medium resolution, then upsample
        med_w, med_h = min(512, self.config.width), min(256, self.config.height)
        med_lat, med_lon = make_equirect_grid(med_w, med_h)
        med_x, med_y, med_z = lat_lon_to_xyz(med_lat, med_lon)
        med_xyz = np.stack([med_x, med_y, med_z], axis=-1).reshape(-1, 3)

        boundary_elev_med = np.zeros(med_h * med_w)

        # Process boundary points
        bp_xyz = np.array([bp[0] for bp in boundary_points])
        bp_types = [bp[3] for bp in boundary_points]
        bp_rates = np.array([bp[4] for bp in boundary_points])

        # Compute distances from all grid points to all boundary points
        # Process in chunks for memory
        chunk_size = 10000
        for start in range(0, len(med_xyz), chunk_size):
            end = min(start + chunk_size, len(med_xyz))
            chunk = med_xyz[start:end]  # (chunk, 3)

            # Distance to all boundary points
            dots = chunk @ bp_xyz.T  # (chunk, n_bp)
            dists = np.arccos(np.clip(dots, -1, 1))  # angular distance

            # Apply influence for each boundary type
            for bi in range(len(bp_xyz)):
                d = dists[:, bi]
                within = d < influence_rad
                if not np.any(within):
                    continue

                falloff = np.exp(-(d[within] / (influence_rad * 0.4)) ** 2)
                rate_factor = min(bp_rates[bi] / 5.0, 2.0)  # normalize rate

                if bp_types[bi] == "convergent":
                    boundary_elev_med[start + np.where(within)[0]] += (
                        self.config.convergent_elev_m * falloff * rate_factor
                    )
                elif bp_types[bi] == "divergent":
                    boundary_elev_med[start + np.where(within)[0]] += (
                        self.config.divergent_elev_m * falloff * rate_factor
                    )
                # Transform: no elevation change

        # Upsample to full resolution
        boundary_elev = boundary_elev_med.reshape(med_h, med_w)
        if (med_h, med_w) != (self.config.height, self.config.width):
            from scipy.ndimage import zoom as ndzoom

            zoom_h = self.config.height / med_h
            zoom_w = self.config.width / med_w
            boundary_elev = ndzoom(boundary_elev, (zoom_h, zoom_w), order=1)
            boundary_elev = boundary_elev[: self.config.height, : self.config.width]

        return boundary_elev, boundaries_meta

    def _compute_convergence_rate(
        self, point_xyz: np.ndarray, info_a: dict, info_b: dict
    ) -> float:
        """Compute convergence rate at a point between two plates.

        Positive = convergent, negative = divergent.
        """
        va = self._plate_velocity_at(point_xyz, info_a)
        vb = self._plate_velocity_at(point_xyz, info_b)
        relative = va - vb  # velocity of A relative to B

        # Approximate boundary normal (from A center to B center)
        lat_a = np.radians(info_a.get("seed_lat_deg", 0))
        lon_a = np.radians(info_a.get("seed_lon_deg", 0))
        lat_b = np.radians(info_b.get("seed_lat_deg", 0))
        lon_b = np.radians(info_b.get("seed_lon_deg", 0))
        ca = np.array(lat_lon_to_xyz(lat_a, lon_a))
        cb = np.array(lat_lon_to_xyz(lat_b, lon_b))
        ca = np.array([float(c) if isinstance(c, np.ndarray) else c for c in ca])
        cb = np.array([float(c) if isinstance(c, np.ndarray) else c for c in cb])
        normal = cb - ca
        norm_len = np.linalg.norm(normal)
        if norm_len < 1e-10:
            return 0.0
        normal /= norm_len

        # Convergence = component of relative velocity along boundary normal
        return float(np.dot(relative, normal))

    def _plate_velocity_at(
        self, point_xyz: np.ndarray, plate_info: dict
    ) -> np.ndarray:
        """Compute plate velocity vector at a point on the unit sphere.

        Uses rigid-body rotation: v = ω × r.
        """
        if "euler_pole" not in plate_info:
            return np.zeros(3)

        euler = np.array(plate_info["euler_pole"])
        omega = plate_info.get("omega_rad_yr", 0)
        omega_vec = euler * omega

        # v = omega_vec × point_xyz  (on unit sphere)
        p = point_xyz
        if p.ndim > 1:
            p = p.ravel()[:3]
        v = np.cross(omega_vec, p)

        # Convert to cm/yr for meaningful magnitudes
        # (omega is in rad/yr, sphere radius is unit)
        return v * self.config.radius_km * 1e5  # km → cm

    # ── Hotspots ─────────────────────────────────────────────────────────────

    def _compute_hotspot_effects(self) -> np.ndarray:
        """Gaussian uplift (and optional caldera depression) for hotspots."""
        result = np.zeros_like(self.lat_grid)

        for hs in self.config.hotspots:
            lat0 = np.radians(hs.lat_deg)
            lon0 = np.radians(hs.lon_deg)
            sigma = hs.radius_km / self.config.radius_km

            dist = angular_distance(self.lat_grid, self.lon_grid, lat0, lon0)
            uplift = hs.amplitude_m * np.exp(-(dist / sigma) ** 2)

            if hs.has_caldera and hs.caldera_radius_km > 0:
                cal_sigma = hs.caldera_radius_km / self.config.radius_km
                caldera = hs.caldera_depth_m * np.exp(-(dist / cal_sigma) ** 2)
                uplift -= caldera

            result += uplift

        return result

    # ── Noise Detail ─────────────────────────────────────────────────────────

    def _compute_noise_detail(self, continent_field: np.ndarray) -> np.ndarray:
        """Multi-octave 3D noise, amplitude-modulated by terrain type."""
        c = self.config

        print("  Generating 3D fBm noise...", end="", flush=True)
        t0 = time.time()
        noise = generate_fbm_3d(
            self.lat_grid,
            self.lon_grid,
            seed=c.seed,
            noise_scale=c.noise_scale,
            octaves=c.noise_octaves,
            persistence=c.noise_persistence,
            lacunarity=c.noise_lacunarity,
        )
        print(f" ({time.time() - t0:.1f}s)")

        # Amplitude modulation: continents get continent_noise_amp,
        # oceans get ocean_noise_amp, smooth transition at coast
        coast_mask = smooth_step(continent_field, -200, 200)  # 0=ocean, 1=land
        noise_amp = (
            c.ocean_noise_amp_m * (1 - coast_mask)
            + c.continent_noise_amp_m * coast_mask
        )

        return noise * noise_amp

    # ── Main Generation Pipeline ─────────────────────────────────────────────

    def generate(self) -> GenerationResult:
        """Run the full heightmap generation pipeline.

        Returns:
            GenerationResult with elevation grid, metadata, and config.
        """
        t_start = time.time()
        print(f"Generating heightmap for {self.config.name}...")
        print(f"  Resolution: {self.config.width}×{self.config.height}")
        print(f"  Seed: {self.config.seed}")

        # 1. Continent field
        print("  [1/7] Computing continent field...", end="", flush=True)
        t0 = time.time()
        continent_field = self._compute_continent_field()
        print(f" ({time.time() - t0:.2f}s)")

        # 2. Base elevation
        print("  [2/7] Computing base elevation...", end="", flush=True)
        t0 = time.time()
        base_elev = self._compute_base_elevation(continent_field)
        print(f" ({time.time() - t0:.2f}s)")

        # 3. Tidal deformation
        print("  [3/7] Computing tidal deformation...", end="", flush=True)
        t0 = time.time()
        tidal = self._compute_tidal_deformation()
        print(f" ({time.time() - t0:.2f}s)")

        # 4. Tectonic plates
        print("  [4/7] Generating tectonic plates...", end="", flush=True)
        t0 = time.time()
        sv, plate_map, plate_info = self._generate_plates()
        print(f" ({time.time() - t0:.2f}s)")

        # 5. Boundary effects
        print("  [5/7] Computing boundary effects...", end="", flush=True)
        t0 = time.time()
        boundary_elev, boundaries_meta = self._compute_boundary_effects(
            sv, plate_map, plate_info
        )
        print(f" ({time.time() - t0:.2f}s)")

        # 6. Hotspot effects
        print("  [6/7] Computing hotspot effects...", end="", flush=True)
        t0 = time.time()
        hotspot_elev = self._compute_hotspot_effects()
        print(f" ({time.time() - t0:.2f}s)")

        # 7. Noise detail
        print("  [7/7] Adding noise detail...")
        noise_elev = self._compute_noise_detail(continent_field)

        # Combine all contributions
        print("  Combining layers...", end="", flush=True)
        elevation = base_elev + tidal + boundary_elev + hotspot_elev + noise_elev

        # Clamp to configured range
        elevation = np.clip(elevation, self.config.elevation_min_m, self.config.elevation_max_m)
        print(" done.")

        # Compute statistics
        land_mask = elevation > self.config.sea_level_m
        land_frac = np.mean(land_mask)
        print(f"\n  Statistics:")
        print(f"    Elevation range: {elevation.min():.0f}m to {elevation.max():.0f}m")
        print(f"    Mean elevation: {elevation.mean():.0f}m")
        print(f"    Land fraction: {land_frac:.1%}")
        print(f"    Ocean fraction: {1 - land_frac:.1%}")

        elapsed = time.time() - t_start
        print(f"\n  Generation complete in {elapsed:.1f}s")

        # Build metadata
        hotspots_meta = [
            {
                "name": hs.name,
                "lat_deg": hs.lat_deg,
                "lon_deg": hs.lon_deg,
                "radius_km": hs.radius_km,
                "amplitude_m": hs.amplitude_m,
                "has_caldera": hs.has_caldera,
            }
            for hs in self.config.hotspots
        ]

        features_meta = [
            {
                "name": f.name,
                "type": "continent" if f.amplitude_m > 0 else "rift/depression",
                "lat_deg": f.lat_deg,
                "lon_deg": f.lon_deg,
                "semi_lon_deg": f.semi_lon_deg,
                "semi_lat_deg": f.semi_lat_deg,
                "amplitude_m": f.amplitude_m,
            }
            for f in self.config.continent_features
        ]

        return GenerationResult(
            elevation=elevation,
            continent_field=continent_field,
            plate_map=plate_map,
            plate_info=plate_info,
            boundaries=boundaries_meta,
            hotspots=hotspots_meta,
            features=features_meta,
            config=self.config,
        )

    # ── Cube Map Export ──────────────────────────────────────────────────────

    def generate_cubemap_faces(
        self, face_resolution: int = 2048
    ) -> dict[str, np.ndarray]:
        """Generate heightmap for each cube map face.

        Each face is a square grid mapped to the sphere, ensuring perfect
        seam continuity between faces (no interpolation artifacts).

        Args:
            face_resolution: Pixels per face edge.

        Returns:
            Dict of face_name → 2D elevation array.
        """
        faces = {}
        face_names = ["+X", "-X", "+Y", "-Y", "+Z", "-Z"]

        for fname in face_names:
            u = np.linspace(-1, 1, face_resolution, endpoint=False)
            v = np.linspace(-1, 1, face_resolution, endpoint=False)
            u_grid, v_grid = np.meshgrid(u, v)

            # Map (u, v) on cube face to 3D direction
            if fname == "+X":
                fx, fy, fz = np.ones_like(u_grid), v_grid, -u_grid
            elif fname == "-X":
                fx, fy, fz = -np.ones_like(u_grid), v_grid, u_grid
            elif fname == "+Y":
                fx, fy, fz = u_grid, np.ones_like(u_grid), -v_grid
            elif fname == "-Y":
                fx, fy, fz = u_grid, -np.ones_like(u_grid), v_grid
            elif fname == "+Z":
                fx, fy, fz = u_grid, v_grid, np.ones_like(u_grid)
            else:  # -Z
                fx, fy, fz = -u_grid, v_grid, -np.ones_like(u_grid)

            # Normalize to unit sphere
            r = np.sqrt(fx**2 + fy**2 + fz**2)
            fx /= r
            fy /= r
            fz /= r

            # Convert to lat/lon
            face_lat = np.arcsin(np.clip(fy, -1, 1))
            face_lon = np.arctan2(fz, fx)

            # Recompute all layers for this face's grid
            face_elev = self._evaluate_at(face_lat, face_lon)
            faces[fname] = face_elev

        return faces

    def _evaluate_at(self, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
        """Evaluate the full heightmap at arbitrary lat/lon points.

        Re-runs the generation pipeline for the given coordinates.
        Used for cube map face generation.
        """
        c = self.config

        # Store and swap grid
        orig_lat, orig_lon = self.lat_grid, self.lon_grid
        orig_xyz = self.xyz_grid
        self.lat_grid, self.lon_grid = lat, lon
        x, y, z = lat_lon_to_xyz(lat, lon)
        self.xyz_grid = np.stack([x, y, z], axis=-1)

        try:
            cf = self._compute_continent_field()
            base = self._compute_base_elevation(cf)
            tidal = self._compute_tidal_deformation()
            hotspots = self._compute_hotspot_effects()
            noise = self._compute_noise_detail(cf)
            # Skip boundary effects for cube faces (expensive, minor contribution)
            elev = base + tidal + hotspots + noise
            elev = np.clip(elev, c.elevation_min_m, c.elevation_max_m)
        finally:
            self.lat_grid, self.lon_grid = orig_lat, orig_lon
            self.xyz_grid = orig_xyz

        return elev


# ═══════════════════════════════════════════════════════════════════════════════
# Generation Result
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class GenerationResult:
    """Result of heightmap generation."""

    elevation: np.ndarray  # (H, W) float64, meters
    continent_field: np.ndarray  # (H, W) float64
    plate_map: np.ndarray  # (H, W) int, plate indices
    plate_info: dict
    boundaries: list
    hotspots: list
    features: list
    config: PlanetConfig

    def export_elevation_png(self, path: Path) -> None:
        """Export elevation as 16-bit PNG.

        Normalizes the actual elevation range to full [0, 65535] uint16,
        matching the dreamulator elevation_codec convention.
        The physical elevation range is stored in metadata.json.
        """
        elev = self.elevation
        actual_min = float(elev.min())
        actual_max = float(elev.max())
        # Normalize actual range to full 16-bit
        normalized = (elev - actual_min) / max(actual_max - actual_min, 1)
        normalized = np.clip(normalized, 0, 1)
        data_16 = (normalized * 65535).astype(np.uint16)
        img = Image.fromarray(data_16)
        img.save(str(path))
        # Store the actual range for downstream use
        self._png_elevation_range = (actual_min, actual_max)
        print(f"  Saved elevation PNG: {path} (range: {actual_min:.0f}m to {actual_max:.0f}m)")

    def export_metadata_json(self, path: Path) -> None:
        """Export plate, boundary, hotspot metadata as JSON."""
        c = self.config
        # Use actual elevation range if PNG was exported
        png_range = getattr(self, '_png_elevation_range', None)
        actual_range = list(png_range) if png_range else [c.elevation_min_m, c.elevation_max_m]
        actual_min, actual_max = actual_range
        sea_level_norm = (c.sea_level_m - actual_min) / max(actual_max - actual_min, 1)

        meta = {
            "generator": "generate_planet_heightmap.py",
            "planet_name": c.name,
            "seed": c.seed,
            "resolution": [c.width, c.height],
            "radius_km": c.radius_km,
            "gravity_m_s2": c.gravity_m_s2,
            "elevation_range_m": actual_range,
            "sea_level_m": c.sea_level_m,
            "sea_level_normalized": round(sea_level_norm, 4),
            "land_fraction": float(np.mean(self.elevation > c.sea_level_m)),
            "plates": self.plate_info,
            "boundaries": self.boundaries,
            "hotspots": self.hotspots,
            "continent_features": self.features,
            "gaea_import_notes": {
                "sea_level_normalized": round(sea_level_norm, 4),
                "sea_level_pixel_value_16bit": int(sea_level_norm * 65535),
                "do_not_use_seamless": True,
                "recommended_workflow": "File → Math(noise mix) → Erosion2 → Rivers → Sea → Export",
            },
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False, default=str)
        print(f"  Saved metadata: {path}")

    def export_cubemap_pngs(self, output_dir: Path, generator: SphericalHeightmapGenerator,
                           face_resolution: int = 2048) -> None:
        """Generate and export cube map faces for Gaea."""
        c = self.config
        faces = generator.generate_cubemap_faces(face_resolution)
        cubemap_dir = output_dir / "cubemap"
        cubemap_dir.mkdir(parents=True, exist_ok=True)

        elev_range = c.elevation_max_m - c.elevation_min_m
        for fname, face_elev in faces.items():
            normalized = (face_elev - c.elevation_min_m) / elev_range
            normalized = np.clip(normalized, 0, 1)
            data_16 = (normalized * 65535).astype(np.uint16)
            img = Image.fromarray(data_16)
            safe_name = fname.replace("+", "pos").replace("-", "neg")
            img.save(str(cubemap_dir / f"face_{safe_name}.png"))
            print(f"  Saved cube face {fname}: {cubemap_dir / f'face_{safe_name}.png'}")

    def export_preview(self, path: Path) -> None:
        """Generate color preview visualization."""
        if not _HAS_MATPLOTLIB:
            print("  WARNING: matplotlib not available, skipping preview")
            return

        c = self.config
        fig, axes = plt.subplots(2, 2, figsize=(20, 12))
        fig.suptitle(
            f"{c.name} — Seed {c.seed} — {c.width}×{c.height}",
            fontsize=14,
            fontweight="bold",
        )

        # 1. Elevation (hypsometric tint)
        ax = axes[0, 0]
        elev = self.elevation
        # Custom colormap: deep blue → light blue → green → yellow → brown → white
        colors_list = [
            "#0a1a3a",   # deep ocean (0.0)
            "#1a4a8a",   # mid ocean
            "#3a8aba",   # shallow ocean
            "#2a6a2a",   # coast/lowland
            "#5a8a2a",   # hills
            "#8a7a4a",   # mountains
            "#ffffff",   # peaks/snow (1.0)
        ]
        sea_norm = (c.sea_level_m - c.elevation_min_m) / (c.elevation_max_m - c.elevation_min_m)
        elev_norm = (elev - c.elevation_min_m) / (c.elevation_max_m - c.elevation_min_m)
        cmap = mcolors.LinearSegmentedColormap.from_list("hypsometric", colors_list)
        im = ax.imshow(elev_norm, cmap=cmap, aspect="auto", vmin=0, vmax=1)
        ax.set_title("Elevation (hypsometric)")
        ax.set_xlabel("Longitude")
        ax.set_ylabel("Latitude")
        plt.colorbar(im, ax=ax, label="Normalized elevation")

        # 2. Plate map
        ax = axes[0, 1]
        n_plates = len(self.plate_info)
        plate_colors = plt.cm.Set3(np.linspace(0, 1, max(n_plates, 12)))
        plate_img = plate_colors[self.plate_map % len(plate_colors)]
        ax.imshow(plate_img, aspect="auto")
        ax.set_title(f"Tectonic Plates ({n_plates} plates)")
        ax.set_xlabel("Longitude")
        ax.set_ylabel("Latitude")

        # 3. Continent field
        ax = axes[1, 0]
        cf_norm = np.clip(self.continent_field / 3000, -1, 1)
        im = ax.imshow(cf_norm, cmap="RdBu_r", aspect="auto", vmin=-1, vmax=1)
        ax.set_title("Continent Field (red=land, blue=ocean)")
        ax.set_xlabel("Longitude")
        ax.set_ylabel("Latitude")
        plt.colorbar(im, ax=ax, label="Continent field value")

        # 4. Land/ocean + features overlay
        ax = axes[1, 1]
        land_ocean = np.where(elev > c.sea_level_m, 1, 0)
        ax.imshow(land_ocean, cmap="Blues_r", aspect="auto", vmin=0, vmax=1)
        # Plot hotspots
        for hs in self.config.hotspots:
            px = (hs.lon_deg + 180) / 360 * c.width
            py = (90 - hs.lat_deg) / 180 * c.height
            ax.plot(px, py, "r^", markersize=8, label=hs.name)
        ax.set_title("Land/Ocean + Hotspots (▲)")
        ax.set_xlabel("Longitude")
        ax.set_ylabel("Latitude")

        plt.tight_layout()
        plt.savefig(str(path), dpi=150, bbox_inches="tight")
        plt.close(fig)
        print(f"  Saved preview: {path}")


# ═══════════════════════════════════════════════════════════════════════════════
# YAML Configuration Loader
# ═══════════════════════════════════════════════════════════════════════════════


def load_planet_config(path: Path) -> PlanetConfig:
    """Load planet configuration from a YAML file.

    The YAML format supports comments and is human-editable.
    See data/worlds/gaia-m/layers/geological/input/heightmap_config.yaml
    for a fully documented example.

    Args:
        path: Path to the YAML configuration file.

    Returns:
        PlanetConfig populated from the YAML data.

    Raises:
        FileNotFoundError: If the config file doesn't exist.
        ValueError: If required fields are missing or invalid.
    """
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise ValueError(f"Config file must be a YAML mapping, got {type(data).__name__}")

    # ── Planet basics ────────────────────────────────────────────────────
    planet = data.get("planet", {})
    elevation = data.get("elevation", {})
    profile = data.get("continent_profile", {})
    tidal = data.get("tidal", {})
    plates = data.get("plates", {})
    noise = data.get("noise", {})
    output = data.get("output", {})

    # ── Continent features ───────────────────────────────────────────────
    continent_features = []
    for feat in data.get("continent_features", []):
        continent_features.append(ContinentFeature(
            name=feat["name"],
            lat_deg=feat["lat_deg"],
            lon_deg=feat["lon_deg"],
            semi_lon_deg=feat["semi_lon_deg"],
            semi_lat_deg=feat["semi_lat_deg"],
            amplitude_m=feat["amplitude_m"],
            rotation_deg=feat.get("rotation_deg", 0.0),
            falloff_power=feat.get("falloff_power", 2.5),
        ))

    # ── Hotspots ─────────────────────────────────────────────────────────
    hotspots = []
    for hs in data.get("hotspots", []):
        hotspots.append(HotspotFeature(
            name=hs["name"],
            lat_deg=hs["lat_deg"],
            lon_deg=hs["lon_deg"],
            radius_km=hs["radius_km"],
            amplitude_m=hs["amplitude_m"],
            has_caldera=hs.get("has_caldera", False),
            caldera_radius_km=hs.get("caldera_radius_km", 0.0),
            caldera_depth_m=hs.get("caldera_depth_m", 0.0),
        ))

    # ── Plate seeds ──────────────────────────────────────────────────────
    plate_seeds = []
    for ps in plates.get("seeds", []):
        plate_seeds.append(PlateSeed(
            name=ps["name"],
            lat_deg=ps["lat_deg"],
            lon_deg=ps["lon_deg"],
            plate_type=ps.get("type", "oceanic"),
            velocity_cm_yr=ps.get("velocity_cm_yr", 5.0),
            direction_deg=ps.get("direction_deg", 0.0),
        ))

    # ── Coast threshold ──────────────────────────────────────────────────
    coast_frac = profile.get("coast_threshold_fraction", 0.10)

    return PlanetConfig(
        # Planet
        name=planet.get("name", "Planet"),
        seed=planet.get("seed", 42),
        radius_km=planet.get("radius_km", 6371.0),
        gravity_m_s2=planet.get("gravity_m_s2", 9.81),
        rotation_period_days=planet.get("rotation_period_days", 1.0),
        # Elevation
        elevation_min_m=elevation.get("min_m", -11000.0),
        elevation_max_m=elevation.get("max_m", 9000.0),
        sea_level_m=elevation.get("sea_level_m", 0.0),
        # Continent profile
        continent_elev_m=profile.get("continent_elev_m", 3500.0),
        ocean_depth_m=profile.get("ocean_depth_m", 5500.0),
        continent_elev_power=profile.get("continent_elev_power", 0.7),
        shelf_fraction=profile.get("shelf_fraction", 0.12),
        coast_threshold_fraction=coast_frac,
        # Tidal
        tidal_bulge_amplitude_m=tidal.get("bulge_amplitude_m", 0.0),
        tidal_bulge_lon_deg=tidal.get("bulge_lon_deg", 0.0),
        # Plates
        num_plates=plates.get("num_plates", 20),
        plate_seeds=plate_seeds,
        boundary_influence_km=plates.get("boundary_influence_km", 300.0),
        convergent_elev_m=plates.get("convergent_elev_m", 1500.0),
        divergent_elev_m=plates.get("divergent_elev_m", -1200.0),
        # Noise
        noise_scale=noise.get("scale", 2.0),
        noise_octaves=noise.get("octaves", 6),
        noise_persistence=noise.get("persistence", 0.5),
        noise_lacunarity=noise.get("lacunarity", 2.0),
        continent_noise_amp_m=noise.get("continent_noise_amp_m", 500.0),
        ocean_noise_amp_m=noise.get("ocean_noise_amp_m", 250.0),
        # Output
        width=output.get("width", 2048),
        height=output.get("height", 1024),
        # Features
        continent_features=continent_features,
        hotspots=hotspots,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(
        description="Generate a procedural planet heightmap on the sphere.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate from YAML config (recommended)
  python generate_planet_heightmap.py \\
    --config data/worlds/gaia-m/layers/geological/input/heightmap_config.yaml \\
    --output output/gaiam/ --preview

  # Override resolution from CLI
  python generate_planet_heightmap.py --config cfg.yaml --output out/ \\
    --resolution 4096 2048

  # Include cube map faces for Gaea
  python generate_planet_heightmap.py --config cfg.yaml --output out/ \\
    --cubemap --cubemap-res 2048
        """,
    )
    parser.add_argument(
        "--config", type=Path, required=True,
        help="Path to planet YAML configuration file",
    )
    parser.add_argument(
        "--output", type=Path, default=Path("output/heightmap"),
        help="Output directory (default: output/heightmap)",
    )
    parser.add_argument(
        "--resolution", nargs=2, type=int, default=None,
        metavar=("WIDTH", "HEIGHT"),
        help="Override output resolution (default: from config file)",
    )
    parser.add_argument(
        "--seed", type=int, default=None,
        help="Override random seed (default: from config file)",
    )
    parser.add_argument("--cubemap", action="store_true", help="Generate cube map faces")
    parser.add_argument(
        "--cubemap-res", type=int, default=2048,
        help="Cube map face resolution (default: 2048)",
    )
    parser.add_argument("--preview", action="store_true", help="Generate color preview PNG")

    args = parser.parse_args()

    # Load config from YAML
    config = load_planet_config(args.config)

    # Apply CLI overrides
    if args.seed is not None:
        config.seed = args.seed
    if args.resolution is not None:
        config.width = args.resolution[0]
        config.height = args.resolution[1]

    # Create output directory
    args.output.mkdir(parents=True, exist_ok=True)

    # Generate
    generator = SphericalHeightmapGenerator(config)
    result = generator.generate()

    # Export
    print("\nExporting...")
    result.export_elevation_png(args.output / "elevation.png")
    result.export_metadata_json(args.output / "metadata.json")

    if args.cubemap:
        result.export_cubemap_pngs(args.output, generator, args.cubemap_res)

    if args.preview:
        result.export_preview(args.output / "preview.png")

    print("\nDone!")


if __name__ == "__main__":
    main()
