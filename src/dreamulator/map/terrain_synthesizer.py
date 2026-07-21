"""Terrain synthesis on the spherical CVT mesh.

Pipeline:
    1. Bimodal base elevation (continental ~850m, oceanic ~-3800m)
    2. Tectonic boundary effects (Gaussian falloff from boundaries)
    3. Multi-octave 3D Simplex fBm noise
    4. Sea level classification

All operations work directly on CVT cell (x, y, z) coordinates, ensuring
seamless global coverage with no projection artifacts.

See ``docs/usage/terrain-pipeline.md`` §5 for algorithm details.
"""

from __future__ import annotations

import logging

import numpy as np

from .models import CVTMesh, TectonicPlate
from .pipeline_types import TerrainPipelineConfig

logger = logging.getLogger(__name__)

# Check for opensimplex
try:
    import opensimplex

    _HAS_OPENSIMPLEX = True
except ImportError:
    _HAS_OPENSIMPLEX = False


# ---------------------------------------------------------------------------
# fBm noise on CVT cells
# ---------------------------------------------------------------------------


def _compute_noise_elementwise_xyz(
    x: np.ndarray,
    y: np.ndarray,
    z: np.ndarray,
    frequency: float,
    seed: int,
) -> np.ndarray:
    """Compute 3D Simplex noise at scattered points on the sphere.

    Args:
        x, y, z: (n,) coordinates on unit sphere.
        frequency: Noise frequency multiplier.
        seed: Noise seed.

    Returns:
        (n,) noise values approximately in [-1, 1].
    """
    if not _HAS_OPENSIMPLEX:
        return _fallback_noise_xyz(x, y, z, frequency, seed)

    opensimplex.seed(seed)
    fx = (x * frequency).ravel()
    fy = (y * frequency).ravel()
    fz = (z * frequency).ravel()

    n = len(fx)
    result = np.empty(n, dtype=np.float64)

    # Process in chunks for memory efficiency
    chunk_size = 50_000
    for start in range(0, n, chunk_size):
        end = min(start + chunk_size, n)
        for j in range(start, end):
            result[j] = opensimplex.noise3(float(fx[j]), float(fy[j]), float(fz[j]))

    return result


def _fallback_noise_xyz(
    x: np.ndarray,
    y: np.ndarray,
    z: np.ndarray,
    frequency: float,
    seed: int,
) -> np.ndarray:
    """Fallback pseudo-noise using random hash when opensimplex unavailable."""
    rng = np.random.default_rng(seed)
    # Use a simple hash-based approach
    n = len(x)
    # Quantize coordinates to grid and hash
    ix = np.floor(x * frequency * 100).astype(np.int64)
    iy = np.floor(y * frequency * 100).astype(np.int64)
    iz = np.floor(z * frequency * 100).astype(np.int64)
    # Hash to pseudo-random values
    h = (ix * 73856093) ^ (iy * 19349663) ^ (iz * 83492791) ^ seed
    h = (h * h) >> 8
    return ((h & 0xFFFF).astype(np.float64) / 32768.0 - 1.0)


def generate_fbm_on_cells(
    mesh: CVTMesh,
    config: TerrainPipelineConfig,
) -> np.ndarray:
    """Generate multi-octave fBm noise sampled at CVT cell positions.

    Each octave is sampled directly at the cell xyz positions, so no
    upsampling or interpolation is needed (unlike the grid-based approach
    in ``generate_planet_heightmap.py``).

    Args:
        mesh: The CVT mesh.
        config: Pipeline configuration.

    Returns:
        (n,) noise values approximately in [-1, 1].
    """
    n = mesh.num_cells
    x = np.array([c.x for c in mesh.cells])
    y = np.array([c.y for c in mesh.cells])
    z = np.array([c.z for c in mesh.cells])

    result = np.zeros(n, dtype=np.float64)
    amplitude = 1.0
    frequency = config.noise_scale

    for i in range(config.noise_octaves):
        noise = _compute_noise_elementwise_xyz(
            x, y, z, frequency, config.seed + i * 1000
        )
        result += amplitude * noise
        amplitude *= config.noise_persistence
        frequency *= config.noise_lacunarity

        if (i + 1) % 2 == 0:
            logger.debug("  fBm octave %d/%d complete", i + 1, config.noise_octaves)

    # Normalize to [-1, 1]
    max_val = np.max(np.abs(result))
    if max_val > 0:
        result /= max_val

    return result


# ---------------------------------------------------------------------------
# Boundary effects
# ---------------------------------------------------------------------------


def apply_boundary_effects(
    mesh: CVTMesh,
    config: TerrainPipelineConfig,
) -> np.ndarray:
    """Apply tectonic boundary elevation effects.

    Gaussian falloff from boundary:
        ΔH = A · exp(-d² / 2σ²) · rate_factor

    where:
        A = convergent_uplift_m or divergent_depth_m
        d = distance_to_boundary_km
        σ = boundary_influence_km
        rate_factor = min(|convergence_rate| / reference_rate, 1.0)

    Args:
        mesh: The CVT mesh (modified in-place).
        config: Pipeline configuration.

    Returns:
        (n,) array of boundary elevation adjustments (metres).
    """
    n = mesh.num_cells
    delta_h = np.zeros(n, dtype=np.float64)
    sigma = config.boundary_influence_km
    sigma_sq_2 = 2 * sigma * sigma

    # Reference convergence rate for normalization (10 cm/yr is very fast)
    ref_rate = 10.0  # cm/yr

    for i, cell in enumerate(mesh.cells):
        if cell.boundary_type is None:
            continue
        if cell.distance_to_boundary_km > 3 * sigma:
            continue  # Beyond 3σ, effect is negligible

        # Gaussian distance falloff
        d = cell.distance_to_boundary_km
        falloff = np.exp(-(d * d) / sigma_sq_2)

        # Rate factor (how fast the plates are converging/diverging)
        rate = abs(cell.convergence_rate_cm_yr)
        rate_factor = min(rate / ref_rate, 1.0)

        if cell.boundary_type == "convergent":
            delta_h[i] = config.convergent_uplift_m * falloff * rate_factor
        elif cell.boundary_type == "divergent":
            delta_h[i] = config.divergent_depth_m * falloff * rate_factor
        # Transform boundaries: no systematic elevation change

    return delta_h


# ---------------------------------------------------------------------------
# Sea/land classification
# ---------------------------------------------------------------------------


def classify_sea_land(
    mesh: CVTMesh,
    sea_level_m: float,
) -> None:
    """Update crust_type based on final elevation vs sea level.

    Cells above sea level with oceanic crust become ``transitional``
    (islands, seamounts).  Cells below sea level with continental crust
    become ``transitional`` (continental shelf, submarine canyons).

    Modifies cells in-place.
    """
    for cell in mesh.cells:
        above_sea = cell.elevation > sea_level_m
        if above_sea and cell.crust_type == "oceanic":
            cell.crust_type = "transitional"
        elif not above_sea and cell.crust_type == "continental":
            cell.crust_type = "transitional"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def synthesize_terrain(
    mesh: CVTMesh,
    plates: list[TectonicPlate],
    config: TerrainPipelineConfig,
) -> None:
    """Synthesize terrain elevation on the CVT mesh.

    This is the main entry point for Stage 4 of the terrain pipeline.

    Pipeline:
        1. Bimodal base elevation
        1b. Per-plate random offset (inter-plate variation)
        2. Tectonic boundary effects (Gaussian)
        3a. Low-frequency regional noise (intra-plate variation)
        3b. High-frequency detail noise
        4. Sea/land classification

    Args:
        mesh: The CVT mesh (modified in-place).
        plates: List of tectonic plates.
        config: Pipeline configuration.
    """
    logger.info("Synthesizing terrain elevation")
    n = mesh.num_cells

    # 1. Bimodal base elevation
    logger.info("  Step 1/5: Bimodal base elevation")
    base = np.full(n, config.oceanic_elevation_m, dtype=np.float64)
    for i, cell in enumerate(mesh.cells):
        if cell.crust_type == "continental":
            base[i] = config.continental_elevation_m

    # 1b. Per-plate random elevation offset
    # Each plate gets a random offset to create large-scale variation.
    # Continental plates shift up/down, oceanic plates shift up/down independently.
    logger.info("  Step 2/5: Per-plate elevation offset (spread=%.0fm)", config.plate_elevation_spread_m)
    rng = np.random.default_rng(config.seed + 100)
    plate_offsets: dict[str, float] = {}
    for plate in plates:
        # Random offset uniformly distributed in [-spread, +spread]
        plate_offsets[plate.id] = rng.uniform(
            -config.plate_elevation_spread_m,
            config.plate_elevation_spread_m,
        )

    # Apply offsets to base elevation
    for i, cell in enumerate(mesh.cells):
        if cell.plate_id and cell.plate_id in plate_offsets:
            base[i] += plate_offsets[cell.plate_id]

    # 2. Tectonic boundary effects
    logger.info("  Step 3/5: Tectonic boundary effects")
    boundary_delta = apply_boundary_effects(mesh, config)

    # 3a. Low-frequency regional noise (creates broad elevation trends within plates)
    logger.info("  Step 4/5: Regional noise (scale=%.1f) + detail noise (%d octaves)",
                config.regional_noise_scale, config.noise_octaves)

    # Regional noise: very low frequency, high amplitude
    regional_config = TerrainPipelineConfig(
        seed=config.seed + 200,
        noise_scale=config.regional_noise_scale,
        noise_octaves=3,  # fewer octaves for regional component
        noise_persistence=0.6,
        noise_lacunarity=2.0,
    )
    regional_fbm = generate_fbm_on_cells(mesh, regional_config)

    regional_amplitude = np.where(
        base >= config.sea_level_m,
        config.regional_noise_amplitude_land_m,
        config.regional_noise_amplitude_ocean_m,
    )
    regional_contribution = regional_fbm * regional_amplitude

    # 3b. High-frequency detail noise (existing)
    fbm = generate_fbm_on_cells(mesh, config)

    # Amplitude-modulated by terrain type
    noise_amplitude = np.where(
        base >= config.sea_level_m,
        config.noise_amplitude_land_m,
        config.noise_amplitude_ocean_m,
    )

    # Distance-to-boundary modulation: more mountainous near boundaries
    sigma = config.boundary_influence_km
    interior_factor = np.ones(n, dtype=np.float64)
    for i, cell in enumerate(mesh.cells):
        if cell.distance_to_boundary_km < 3 * sigma:
            d = cell.distance_to_boundary_km
            proximity = np.exp(-(d * d) / (2 * sigma * sigma))
            interior_factor[i] = 1.0 + 0.5 * proximity

    detail_contribution = fbm * noise_amplitude * interior_factor

    # 4. Combine all components
    logger.info("  Step 5/5: Combining elevation components")
    elevation = base + boundary_delta + regional_contribution + detail_contribution

    # Write back to cells
    for i, cell in enumerate(mesh.cells):
        cell.elevation = float(elevation[i])

    # Classify sea/land
    classify_sea_land(mesh, config.sea_level_m)

    # Summary statistics
    above = np.sum(elevation > config.sea_level_m)
    below = n - above
    logger.info(
        "Terrain synthesis complete: elev range [%.0f, %.0f] m, "
        "%.1f%% land, %.1f%% ocean",
        np.min(elevation),
        np.max(elevation),
        100 * above / n,
        100 * below / n,
    )
