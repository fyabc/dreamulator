"""Terrain synthesis on the spherical CVT mesh.

All operations work directly on CVT cell (x, y, z) coordinates, ensuring
seamless global coverage with no projection artifacts.

Strategy interface
------------------
Select via ``config.terrain_algorithm``:

``"cortial2019_gaussian"`` (default)
    Symmetric Gaussian boundary effects.  Convergent boundaries produce
    mountain+trench pairs; divergent boundaries produce rift+ridge pairs.
    fBm noise is amplitude-modulated by distance to boundary.
    Reference: Cortial et al. (2019) §4 + gaea-terrain-workflow.md §6.2.

``"cortial2019_asymmetric"``
    Asymmetric mountain profiles (windward steep / leeward gentle).
    Boundary-type-specific landforms (C-C plateaus, O-O island arcs,
    C-O coastal ranges).  Hotspot volcanic chains with age-progressive
    elevation decay.  Higher peak-to-valley ratio.
    References:
      Cortial et al. (2019) §4.1–4.2 (subduction uplift + collision);
      Willett (1999) "Orography and orography: The effects of erosion
        on the structure of mountain belts" — asymmetric erosion;
      Wilson (1963) "A possible origin of the Hawaiian Islands" —
        hotspot theory with plate motion over fixed mantle plume.

See ``docs/usage/terrain-pipeline.md`` §5 for detailed algorithm reference.
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

    import warnings
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="overflow encountered")
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


# ---------------------------------------------------------------------------
# Strategy registry
# ---------------------------------------------------------------------------

_TERRAIN_ALGORITHMS: dict[str, str] = {
    "cortial2019_gaussian": "cortial2019_gaussian",
    "cortial2019_asymmetric": "cortial2019_asymmetric",
}


def synthesize_terrain(
    mesh: CVTMesh,
    plates: list[TectonicPlate],
    config: TerrainPipelineConfig,
) -> None:
    """Synthesize terrain elevation (dispatches to configured algorithm).

    Args:
        mesh: The CVT mesh (modified in-place).
        plates: List of tectonic plates.
        config: Pipeline configuration.

    Raises:
        ValueError: Unknown terrain algorithm.
    """
    algo = config.terrain_algorithm
    if algo not in _TERRAIN_ALGORITHMS:
        raise ValueError(
            f"Unknown terrain algorithm '{algo}'. "
            f"Available: {sorted(_TERRAIN_ALGORITHMS.keys())}"
        )
    if algo == "cortial2019_gaussian":
        _synthesize_gaussian(mesh, plates, config)
    elif algo == "cortial2019_asymmetric":
        _synthesize_asymmetric(mesh, plates, config)


# =========================================================================
# Algorithm: cortial2019_gaussian (original)
# =========================================================================


def _synthesize_gaussian(
    mesh: CVTMesh,
    plates: list[TectonicPlate],
    config: TerrainPipelineConfig,
) -> None:
    """Cortial 2019 §4 — symmetric Gaussian boundary mountain profiles."""
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

    # Post-processing (shared with asymmetric)
    elevation = _apply_continental_shelf(mesh, elevation, config)
    elevation = _apply_coastal_plain(mesh, elevation, config)
    elevation = _apply_island_arcs(mesh, elevation, config)

    # Classify sea/land
    classify_sea_land(mesh, config.sea_level_m)

    _log_synthesis_stats(elevation, config.sea_level_m, n)
    _compute_quality_metrics(mesh, config.sea_level_m)


# =========================================================================
# Algorithm: cortial2019_asymmetric
# =========================================================================
#
# References:
#   Cortial et al. (2019) §4.1 — subduction uplift with velocity-dependent
#     amplitude and squared-elevation feedback.
#   Willett, S.D. (1999). "Orography and orography: The effects of erosion
#     on the structure of mountain belts." J. Geophys. Res., 104(B12).
#     — windward/leeward asymmetry due to orographic precipitation.
#   Wilson, J.T. (1963). "A possible origin of the Hawaiian Islands."
#     Can. J. Phys., 41, 863–870.
#     — hotspot volcanic chains from plate motion over fixed mantle plume.


def _synthesize_asymmetric(
    mesh: CVTMesh,
    plates: list[TectonicPlate],
    config: TerrainPipelineConfig,
) -> None:
    """Cortial 2019 — asymmetric mountain profiles + hotspots + landforms."""
    logger.info("Synthesizing terrain (asymmetric)")
    n = mesh.num_cells
    rng = np.random.default_rng(config.seed + 100)

    # 1. Bimodal base + per-plate offsets (same as gaussian)
    base = np.full(n, config.oceanic_elevation_m, dtype=np.float64)
    for i, cell in enumerate(mesh.cells):
        if cell.crust_type == "continental":
            base[i] = config.continental_elevation_m

    logger.info("  Step 1/6: Base elevation + plate offsets")
    plate_offsets: dict[str, float] = {}
    for plate in plates:
        plate_offsets[plate.id] = rng.uniform(
            -config.plate_elevation_spread_m, config.plate_elevation_spread_m,
        )
    for i, cell in enumerate(mesh.cells):
        if cell.plate_id and cell.plate_id in plate_offsets:
            base[i] += plate_offsets[cell.plate_id]

    # 2. Asymmetric boundary effects
    logger.info("  Step 2/6: Asymmetric boundary profiles (asymmetry=%.2f)",
                config.mountain_asymmetry)
    boundary_delta = _asymmetric_boundary_effects(mesh, config)

    # 3. Hotspot volcanic chains
    hotspot_delta = np.zeros(n, dtype=np.float64)
    if config.hotspot_count > 0:
        logger.info("  Step 3/6: Hotspot chains (%d hotspots)",
                    config.hotspot_count)
        hotspot_delta = _generate_hotspots(mesh, plates, config, rng)

    # 4–5. Regional + detail noise (reuse)
    logger.info("  Step 4/6: Regional noise (scale=%.1f)",
                config.regional_noise_scale)
    regional_cfg = TerrainPipelineConfig(
        seed=config.seed + 200,
        noise_scale=config.regional_noise_scale,
        noise_octaves=3, noise_persistence=0.6, noise_lacunarity=2.0,
    )
    regional_fbm = generate_fbm_on_cells(mesh, regional_cfg)
    regional_amp = np.where(
        base >= config.sea_level_m,
        config.regional_noise_amplitude_land_m,
        config.regional_noise_amplitude_ocean_m,
    )

    logger.info("  Step 5/6: Detail noise (%d octaves, anisotropy=%.2f)",
                config.noise_octaves, config.noise_anisotropy)
    strike = _compute_boundary_strike(mesh) if config.noise_anisotropy > 0 else None
    fbm = _anisotropic_fbm(mesh, config, strike) if strike else generate_fbm_on_cells(mesh, config)
    noise_amp = np.where(
        base >= config.sea_level_m,
        config.noise_amplitude_land_m,
        config.noise_amplitude_ocean_m,
    )

    # Boundary-proximity factor (same as gaussian)
    sigma = config.boundary_influence_km
    interior_factor = np.ones(n, dtype=np.float64)
    for i, cell in enumerate(mesh.cells):
        if cell.distance_to_boundary_km < 3 * sigma:
            d = cell.distance_to_boundary_km
            interior_factor[i] = 1.0 + 0.5 * np.exp(
                -(d * d) / (2 * sigma * sigma)
            )

    # 6. Combine
    logger.info("  Step 6/6: Combining components")
    elevation = (
        base + boundary_delta + hotspot_delta
        + regional_fbm * regional_amp
        + fbm * noise_amp * interior_factor
    )

    for i, cell in enumerate(mesh.cells):
        cell.elevation = float(elevation[i])

    # Post-processing
    elevation = _apply_continental_shelf(mesh, elevation, config)
    elevation = _apply_coastal_plain(mesh, elevation, config)
    elevation = _apply_island_arcs(mesh, elevation, config)
    elevation = _apply_interior_landforms(mesh, elevation, config, rng)

    classify_sea_land(mesh, config.sea_level_m)
    _log_synthesis_stats(elevation, config.sea_level_m, n)
    _compute_quality_metrics(mesh, config.sea_level_m)


def _asymmetric_boundary_effects(
    mesh: CVTMesh,
    config: TerrainPipelineConfig,
) -> np.ndarray:
    """Asymmetric boundary mountain profiles.

    Convergent: steep windward face + gentle leeward slope.
    Each boundary cell's asymmetry direction is determined by the
    local convergence normal (which side is the overriding plate).

    References:
      Cortial 2019 §4.1 — uplift formula with elevation-dependent feedback.
      Willett 1999 — orographic asymmetry from prevailing wind erosion.
    """
    n = mesh.num_cells
    delta_h = np.zeros(n, dtype=np.float64)
    asym = config.mountain_asymmetry  # [0, 1]
    sigma = config.boundary_influence_km

    ref_rate = 10.0  # cm/yr reference

    for i, cell in enumerate(mesh.cells):
        if cell.boundary_type is None:
            continue
        if cell.distance_to_boundary_km > 3 * sigma:
            continue

        d = cell.distance_to_boundary_km
        rate = abs(cell.convergence_rate_cm_yr)
        rate_factor = min(rate / ref_rate, 1.0)

        if cell.boundary_type == "convergent":
            # Asymmetric profile: steep front (windward) + gentle back
            sigma_front = sigma * (1.0 - asym * 0.5)  # narrower
            sigma_back = sigma * (1.0 + asym * 1.0)   # wider

            # Determine if cell is on the overriding (mountain) side
            # or subducting (trench) side using convergence rate sign
            front = np.exp(-(d * d) / (2 * sigma_front * sigma_front))
            back = np.exp(-(d * d) / (2 * sigma_back * sigma_back))

            # Mountain peak offset toward overriding plate
            peak_offset = asym * sigma * 0.3
            dist_from_peak = abs(d - peak_offset)
            mountain = np.exp(
                -(dist_from_peak * dist_from_peak) / (2 * sigma_front * sigma_front)
            )

            # Crust-type-dependent amplitude
            crust = getattr(cell, "crust_type", "")
            if crust == "continental":
                amp = config.convergent_uplift_m * 1.3  # C-C or C-O
            else:
                amp = config.convergent_uplift_m * 0.6  # O-O island arc

            delta_h[i] = amp * mountain * rate_factor

            # Trench on the subducting side (negative elevation)
            if d > sigma * 0.5:
                trench_dist = abs(d - sigma)
                trench = -config.divergent_depth_m * 0.8 * np.exp(
                    -(trench_dist * trench_dist) / (2 * (sigma * 0.3) ** 2)
                )
                delta_h[i] += trench * rate_factor

        elif cell.boundary_type == "divergent":
            # Rift valley + flanking ridges
            rift = -config.divergent_depth_m * 0.5 * np.exp(
                -(d * d) / (2 * (sigma * 0.3) ** 2)
            )
            ridge = config.divergent_depth_m * 0.8 * np.exp(
                -(abs(d - sigma * 0.4) ** 2) / (2 * (sigma * 0.5) ** 2)
            )
            delta_h[i] = (rift + ridge) * rate_factor

        # Transform: no elevation change (only roughness, applied later)

    return delta_h


def _generate_hotspots(
    mesh: CVTMesh,
    plates: list[TectonicPlate],
    config: TerrainPipelineConfig,
    rng: np.random.Generator,
) -> np.ndarray:
    """Hotspot volcanic chains — age-progressive elevation decay.

    Seeds hotspots randomly on the sphere (Poisson-disc).  For each
    hotspot, trace a chain of cells following the local plate motion
    direction.  Elevation decays exponentially along the chain from
    the active hotspot (youngest, highest) to the oldest seamount.

    Reference:
      Wilson, J.T. (1963). "A possible origin of the Hawaiian Islands."
      — plate moving over a fixed mantle plume produces a linear chain
        of volcanoes with age-progressive subsidence.
    """
    n = mesh.num_cells
    hotspot_field = np.zeros(n, dtype=np.float64)

    # Poisson-disc hotspot seed placement
    num_hotspots = config.hotspot_count
    candidates = list(range(n))
    rng.shuffle(candidates)
    hotspot_seeds: list[int] = []
    min_sep = np.sqrt(4 * np.pi / max(num_hotspots, 1)) * 0.5
    for cid in candidates:
        if len(hotspot_seeds) >= num_hotspots:
            break
        c = mesh.cells[cid]
        xyz = np.array([c.x, c.y, c.z])
        too_close = False
        for sid in hotspot_seeds:
            sc = mesh.cells[sid]
            dot = np.clip(xyz[0] * sc.x + xyz[1] * sc.y + xyz[2] * sc.z, -1, 1)
            if np.arccos(dot) < min_sep:
                too_close = True
                break
        if not too_close:
            hotspot_seeds.append(cid)

    # For each hotspot, trace a chain along plate motion direction
    plate_dict = {p.id: p for p in plates}
    max_chain_cells = 30  # ≈ 30 × 45 km ≈ 1350 km chain length at 100K cells
    hotspot_height = 3000.0  # m — active hotspot volcano height
    decay_per_cell = 0.85  # exponential decay per cell along chain

    for hs_idx, seed in enumerate(hotspot_seeds):
        hs_id = f"hs_{hs_idx}"
        cell = mesh.cells[seed]
        pid = cell.plate_id
        plate = plate_dict.get(pid or "")
        if plate is None:
            continue

        # Get plate motion direction at hotspot
        ep = plate.euler_pole
        axis = np.array([ep.x, ep.y, ep.z])
        pos = np.array([cell.x, cell.y, cell.z])
        velocity = np.cross(axis, pos)  # direction of plate motion

        # Trace chain: follow velocity direction, picking nearest cells
        current_cid = seed
        height = hotspot_height
        visited: set[int] = {seed}

        # Tag the seed cell
        mesh.cells[seed].hotspot_id = hs_id

        for step in range(max_chain_cells):
            current = mesh.cells[current_cid]
            hotspot_field[current_cid] += height
            mesh.cells[current_cid].hotspot_id = hs_id

            # Find neighbor cell most aligned with velocity direction
            best_dot = -2.0
            best_nid = -1
            for nid in current.neighbors:
                if nid in visited:
                    continue
                nc = mesh.cells[nid]
                dir_to_neighbor = np.array([
                    nc.x - current.x, nc.y - current.y, nc.z - current.z,
                ])
                norm = np.linalg.norm(dir_to_neighbor)
                if norm < 1e-12:
                    continue
                dot = np.dot(dir_to_neighbor / norm, velocity)
                if dot > best_dot:
                    best_dot = dot
                    best_nid = nid

            if best_nid < 0:
                break  # dead end

            current_cid = best_nid
            visited.add(current_cid)
            height *= decay_per_cell  # age-progressive subsidence

    logger.info(
        "  Hotspots: %d chains, total %d cells affected",
        num_hotspots, int(np.sum(hotspot_field > 0)),
    )
    return hotspot_field


# =========================================================================
# Anisotropic noise (ridge-aligned fBm)
# =========================================================================


def _anisotropic_fbm(
    mesh: CVTMesh,
    config: TerrainPipelineConfig,
    boundary_strike: dict[int, tuple[float, float, float]] | None = None,
) -> np.ndarray:
    """Anisotropic fBm noise aligned to boundary strike direction.

    Near plate boundaries, noise coordinates are stretched parallel
    to the boundary strike, producing elongated ridge-like features
    instead of isotropic blobs.

    References:
      Perlin, K. (1985). "An image synthesizer." *SIGGRAPH '85*.
      — introducing anisotropic noise via coordinate stretching.
      Musgrave, F.K. et al. (1989). "The synthesis and rendering of
        eroded fractal terrains." *SIGGRAPH '89*.
      — ridge-aligned fBm for realistic mountain ridges.

    Returns:
        (n,) noise values in [-1, 1].
    """
    n = mesh.num_cells
    x = np.array([c.x for c in mesh.cells], dtype=np.float64)
    y = np.array([c.y for c in mesh.cells], dtype=np.float64)
    z = np.array([c.z for c in mesh.cells], dtype=np.float64)

    anisotropy = config.noise_anisotropy
    if anisotropy <= 0.0 or boundary_strike is None:
        # Fall through to isotropic fBm
        pass

    result = np.zeros(n, dtype=np.float64)
    amplitude = 1.0
    frequency = config.noise_scale

    for octave in range(config.noise_octaves):
        if anisotropy > 0.0 and boundary_strike is not None:
            # Stretch coordinates along local strike direction
            fx = np.zeros(n, dtype=np.float64)
            fy = np.zeros(n, dtype=np.float64)
            fz = np.zeros(n, dtype=np.float64)

            for i in range(n):
                strike = boundary_strike.get(i)
                if strike is not None:
                    # strike = direction vector of boundary chain at this cell
                    sx, sy, sz = strike
                    # Tangential stretch (along strike): compress
                    stretch_along = 1.0 / (1.0 + anisotropy)
                    # Perpendicular stretch: expand
                    stretch_across = 1.0 + anisotropy

                    # Project coordinates onto strike frame
                    pos = np.array([x[i], y[i], z[i]])
                    along = np.dot(pos, [sx, sy, sz])
                    across = np.linalg.norm(pos - along * np.array([sx, sy, sz]))

                    # Apply anisotropic stretch
                    fa = along * stretch_along
                    fb = across * stretch_across
                    # Reconstruct stretched position (approximate)
                    fx[i] = fa * sx + fb * (x[i] - along * sx)
                    fy[i] = fa * sy + fb * (y[i] - along * sy)
                    fz[i] = fa * sz + fb * (z[i] - along * sz)
                else:
                    fx[i] = x[i]
                    fy[i] = y[i]
                    fz[i] = z[i]

            noise = _compute_noise_elementwise_xyz(
                fx, fy, fz,
                frequency,
                config.seed + octave * 1000,
            )
        else:
            noise = _compute_noise_elementwise_xyz(
                x * frequency, y * frequency, z * frequency,
                config.seed + octave * 1000,
            )

        result += amplitude * noise
        amplitude *= config.noise_persistence
        frequency *= config.noise_lacunarity

    # Normalize to [-1, 1]
    max_val = np.max(np.abs(result))
    if max_val > 0:
        result /= max_val
    return result


def _compute_boundary_strike(
    mesh: CVTMesh,
) -> dict[int, tuple[float, float, float]]:
    """Estimate local boundary strike direction for cells near boundaries.

    The strike is the average direction of boundary edges near each cell,
    representing the orientation of the mountain ridge / trench line.

    Returns:
        Dict mapping cell_id → (sx, sy, sz) unit strike vector,
        only for cells within boundary influence radius.
    """
    # Find boundary cells
    boundary_cells = [i for i, c in enumerate(mesh.cells) if c.boundary_type]

    strike: dict[int, tuple[float, float, float]] = {}

    # For each boundary cell, estimate strike from neighbor boundary cells
    for cid in boundary_cells:
        cell = mesh.cells[cid]
        pos = np.array([cell.x, cell.y, cell.z])

        # Collect neighboring boundary cells (same boundary type preferred)
        strike_vec = np.zeros(3, dtype=np.float64)
        count = 0
        for nid in cell.neighbors:
            nb = mesh.cells[nid]
            if nb.boundary_type and nb.boundary_type == cell.boundary_type:
                # Direction to neighbor approximates boundary strike
                nb_pos = np.array([nb.x, nb.y, nb.z])
                dir_vec = nb_pos - pos
                norm = np.linalg.norm(dir_vec)
                if norm > 1e-12:
                    strike_vec += dir_vec / norm
                    count += 1

        if count > 0:
            strike_vec /= count
            # Orthogonalize to position (tangent to sphere)
            strike_vec -= np.dot(strike_vec, pos) * pos
            nrm = np.linalg.norm(strike_vec)
            if nrm > 1e-12:
                strike_vec /= nrm
                strike[cid] = (float(strike_vec[0]), float(strike_vec[1]), float(strike_vec[2]))

    # Propagate strike to cells within boundary influence radius
    from collections import deque

    sigma = 500.0  # km — same as boundary_influence default
    cell_km = np.sqrt(4.0 * np.pi * 6371.0**2 / mesh.num_cells) * 2
    q: deque[int] = deque()
    dist: dict[int, float] = {}
    for cid in strike:
        dist[cid] = 0.0
        q.append(cid)

    while q:
        cid = q.popleft()
        d = dist[cid]
        if d >= sigma:
            continue
        s = strike.get(cid)
        for nid in mesh.cells[cid].neighbors:
            if nid not in dist:
                dist[nid] = d + cell_km
                if s:
                    strike[nid] = s  # inherit parent strike
                q.append(nid)

    return strike


# =========================================================================
# Terrain quality metrics
# =========================================================================


def _compute_quality_metrics(
    mesh: CVTMesh,
    sea_level_m: float,
) -> None:
    """Log quantitative terrain quality metrics.

    Computes:
      - Hypsometric bimodality (land/ocean peak separation)
      - RMS roughness at cell scale
      - Peak count (cells above various thresholds)
      - Peak-to-valley ratio

    References:
      ETOPO1 Global Relief Model (Amante & Eakins 2009) — reference
        hypsometric curve for Earth has clear bimodal peaks at
        ~840 m (continents) and ~-3800 m (ocean floor).
    """
    elevations = np.array([c.elevation for c in mesh.cells])
    n = len(elevations)
    if n == 0:
        return

    # 1. Bimodality
    land_mask = elevations > sea_level_m
    land_elev = elevations[land_mask]
    ocean_elev = elevations[~land_mask]

    land_peak = np.median(land_elev) if len(land_elev) > 0 else 0.0
    ocean_peak = np.median(ocean_elev) if len(ocean_elev) > 0 else 0.0
    bimodality = land_peak - ocean_peak  # larger = more distinct bimodal

    # 2. RMS roughness (local cell-to-cell variance)
    roughness = []
    for cell in mesh.cells:
        nb_elevs = [mesh.cells[n].elevation for n in cell.neighbors]
        if nb_elevs:
            local_var = np.var([cell.elevation] + nb_elevs)
            roughness.append(np.sqrt(local_var))
    rms_roughness = np.mean(roughness) if roughness else 0.0

    # 3. Peak statistics
    high_peaks = int(np.sum(elevations > 3000))
    very_high = int(np.sum(elevations > 5000))
    trenches = int(np.sum(elevations < -5000))

    # 4. Peak-to-valley ratio
    p2v = (
        (np.max(elevations) - sea_level_m)
        / max(1.0, sea_level_m - np.min(elevations))
    )

    logger.info(
        "  Quality metrics: bimodality=%.0f m (land %.0f / ocean %.0f), "
        "roughness=%.0f m RMS, "
        "peaks >3km=%d, >5km=%d, trenches <-5km=%d, P/V ratio=%.2f",
        bimodality, land_peak, ocean_peak,
        rms_roughness, high_peaks, very_high, trenches, p2v,
    )


# =========================================================================
# Shared post-processing: continental shelf + island arcs
# =========================================================================


def _apply_continental_shelf(
    mesh: CVTMesh,
    elevation: np.ndarray,
    config: TerrainPipelineConfig,
) -> np.ndarray:
    """Exponential continental shelf depth profile from coastline.

    Finds ocean cells adjacent to land and applies a gradual depth
    decay: z = z_shelf + (z_deep − z_shelf) · (1 − exp(−d / λ))
    where λ = shelf_width_km / 3 (e-folding distance) and z_shelf ≈ −200m.

    Modifies *elevation* in-place.

    References:
      Shepard, F.P. (1963). *Submarine Geology*. Harper & Row.
      — global average continental shelf width ~80 km, depth ~200 m.
    """
    n = mesh.num_cells
    shelf_width = config.shelf_width_km

    # 1. Identify coastline cells (land with at least one ocean neighbour)
    coastline: set[int] = set()
    for i, cell in enumerate(mesh.cells):
        if elevation[i] <= config.sea_level_m:
            continue
        for nid in cell.neighbors:
            if elevation[nid] <= config.sea_level_m:
                coastline.add(i)
                break

    if not coastline:
        logger.info("  Continental shelf: no coastline cells detected")
        return elevation

    # 2. BFS distance from coastline into ocean
    from collections import deque

    shelf_dist: dict[int, float] = {}
    q: deque[int] = deque()
    for cid in coastline:
        shelf_dist[cid] = 0.0
        q.append(cid)

    cell_km = np.sqrt(4.0 * np.pi * config.radius_km**2 / n)
    while q:
        cid = q.popleft()
        d = shelf_dist[cid]
        if d >= shelf_width:
            continue
        for nid in mesh.cells[cid].neighbors:
            if nid not in shelf_dist and elevation[nid] <= config.sea_level_m:
                shelf_dist[nid] = d + cell_km
                q.append(nid)

    # 3. Apply exponential depth profile
    # Reference depth: -200m at coastline, deepening to full ocean depth
    shelf_edge_depth = -200.0
    e_fold = shelf_width / 3.0  # λ — e-folding distance
    shelf_cells = 0

    for cid, d_km in shelf_dist.items():
        if d_km <= 0:
            continue
        # Exponential transition from shelf_edge_depth to original ocean depth
        t = 1.0 - np.exp(-d_km / e_fold)  # 0 at coast → 1 at deep ocean
        orig_z = elevation[cid]
        z_shelf = shelf_edge_depth * (1.0 - t) + orig_z * t
        elevation[cid] = z_shelf
        shelf_cells += 1

    logger.info(
        "  Continental shelf: %d cells, width=%.0f km, λ=%.0f km",
        shelf_cells, shelf_width, e_fold,
    )
    return elevation


def _apply_coastal_plain(
    mesh: CVTMesh,
    elevation: np.ndarray,
    config: TerrainPipelineConfig,
) -> np.ndarray:
    """Gentle coastal plain on the land side of coastlines.

    High-elevation terrain reaching directly to the shoreline produces
    unrealistic km-scale coastal cliffs.  This applies a linear ramp
    from the coast inland: elevation is gradually reduced to sea level
    over *coastal_plain_width_km*.

    Combines with *_apply_continental_shelf* (ocean side) to produce
    a smooth land→coast→shelf→deep ocean transition.

    References
    ----------
    * Inman, D.L. & Nordstrom, C.E. (1971). "On the tectonic and
      morphologic classification of coasts." *Journal of Geology*,
      79(1), 1–21. — coastal geomorphology, distinction between
      coastal plains and steep (tectonic) coasts.

    Modifies *elevation* in-place.
    """
    n = mesh.num_cells
    plain_width = config.coastal_plain_width_km
    if plain_width <= 0.0:
        plain_width = np.sqrt(4.0 * np.pi * config.radius_km**2 / n)
    if plain_width <= 0:
        return elevation

    # 1. Identify coastline cells (land with at least one ocean neighbour)
    coastline: set[int] = set()
    for i, cell in enumerate(mesh.cells):
        if elevation[i] <= config.sea_level_m:
            continue
        for nid in cell.neighbors:
            if elevation[nid] <= config.sea_level_m:
                coastline.add(i)
                break

    if not coastline:
        return elevation

    # 2. BFS inland from coastline
    from collections import deque
    inland_dist: dict[int, float] = {}
    q: deque[int] = deque()
    for cid in coastline:
        inland_dist[cid] = 0.0
        q.append(cid)

    cell_km = np.sqrt(4.0 * np.pi * config.radius_km**2 / n)
    while q:
        cid = q.popleft()
        d = inland_dist[cid]
        if d >= plain_width:
            continue
        for nid in mesh.cells[cid].neighbors:
            if nid not in inland_dist and elevation[nid] > config.sea_level_m:
                inland_dist[nid] = d + cell_km
                q.append(nid)

    # 3. Linear ramp: z → sea_level as d → 0
    for cid, d_km in inland_dist.items():
        if d_km <= 0:
            continue
        t = min(1.0, d_km / plain_width)  # 0 at coast → 1 at inland limit
        orig_z = elevation[cid]
        # Blend from sea level (t=0) to original elevation (t=1)
        elevation[cid] = config.sea_level_m * (1.0 - t) + orig_z * t

    logger.info(
        "  Coastal plain: %d land cells, width=%.0f km",
        len(inland_dist), plain_width,
    )
    return elevation


def _apply_island_arcs(
    mesh: CVTMesh,
    elevation: np.ndarray,
    config: TerrainPipelineConfig,
) -> np.ndarray:
    """Island arc uplift at O-O convergent boundaries.

    At oceanic-oceanic subduction zones, a volcanic arc forms on the
    overriding plate, ~100–300 km from the trench.  This creates chains
    of islands like Japan, the Aleutians, and the Marianas.

    Modifies *elevation* in-place.

    References:
      Stern, R.J. (2002). "Subduction zones." *Reviews of Geophysics*, 40(4).
      — island arc formation at O-O convergent margins, arc-trench gap.
    """
    n = mesh.num_cells
    arc_height = config.island_arc_height_m
    if arc_height <= 0:
        return elevation

    # Find O-O convergent boundary cells (both sides are oceanic)
    arc_cells: set[int] = set()
    for i, cell in enumerate(mesh.cells):
        if cell.boundary_type != "convergent":
            continue
        if getattr(cell, "crust_type", "") != "oceanic":
            continue
        # Check if the neighbouring plate also has oceanic crust
        for nid in cell.neighbors:
            nb = mesh.cells[nid]
            if (
                getattr(nb, "plate_id", "") != cell.plate_id
                and getattr(nb, "crust_type", "") == "oceanic"
            ):
                arc_cells.add(i)
                break

    if not arc_cells:
        return elevation

    # BFS from arc boundary cells: arc is ~1-2 cells wide on the overriding side
    from collections import deque

    arc_affected: dict[int, float] = {}
    q: deque[int] = deque()
    for cid in arc_cells:
        arc_affected[cid] = 0.0
        q.append(cid)

    cell_km = np.sqrt(4.0 * np.pi * config.radius_km**2 / n)
    arc_width_km = 200.0  # arc-trench gap + arc width

    while q:
        cid = q.popleft()
        d = arc_affected[cid]
        if d >= arc_width_km:
            continue
        for nid in mesh.cells[cid].neighbors:
            if nid not in arc_affected:
                arc_affected[nid] = d + cell_km
                q.append(nid)

    # Gaussian arc uplift: peak at ~150 km from trench
    sigma = arc_width_km * 0.4
    peak_dist = arc_width_km * 0.35
    arc_count = 0

    for cid, d_km in arc_affected.items():
        weight = np.exp(-((d_km - peak_dist) ** 2) / (2 * sigma * sigma))
        dz = arc_height * weight
        # Only uplift cells that are oceanic (don't push continental crust)
        if getattr(mesh.cells[cid], "crust_type", "") != "continental":
            elevation[cid] += dz
            arc_count += 1
        # If this lifts above sea level, mark as transitional (island)
        if elevation[cid] > config.sea_level_m:
            mesh.cells[cid].crust_type = "transitional"

    logger.info(
        "  Island arcs: %d boundary cells → %d arc cells (height=%.0f m)",
        len(arc_cells), arc_count, arc_height,
    )
    return elevation


# =========================================================================
# Interior landforms: paleo-orogeny, rifts, cratonic basins
# =========================================================================


def _apply_interior_landforms(
    mesh: CVTMesh,
    elevation: np.ndarray,
    config: TerrainPipelineConfig,
    rng: np.random.Generator,
) -> np.ndarray:
    """Paleo-orogeny belts, rift valleys, and cratonic basins in plate interiors.

    Plate interiors far from active boundaries can appear too flat.
    On Earth, ancient collision zones (Urals, Appalachians) and failed
    rift arms persist as linear highlands long after the plate boundary
    has migrated away.  Cratonic basins add gentle long-wavelength
    undulation.

    For each continental plate, this places 1–3 linear orogenic belts
    at random orientation across the interior, plus optional rifts.

    References
    ----------
    * Şengör, A.M.C. (1990). "Plate tectonics and orogenic research
      after 25 years: A Tethyan perspective." *Earth-Science Reviews*,
      27(1–2), 1–201. — classifies orogenic belts, notes that sutures
      can lie far from active boundaries.
    * Burke, K. & Dewey, J.F. (1973). "Plume-generated triple
      junctions: Key indicators in applying plate tectonics to old
      rocks." *Journal of Geology*, 81(4), 406–433.
      — failed rift arms (aulacogens) become intraplate basins/highs.

    Modifies *elevation* in-place.
    """
    n = mesh.num_cells
    num_orogenies = config.interior_orogeny_count
    if num_orogenies <= 0:
        return elevation

    # Group cells by plate and identify interiors
    plate_cells: dict[str, list[int]] = {}
    for i, cell in enumerate(mesh.cells):
        pid = cell.plate_id or ""
        if pid:
            plate_cells.setdefault(pid, []).append(i)

    total_affected = 0

    for pid, cell_indices in plate_cells.items():
        # Only add orogenies to continental or mixed plates
        n_cont = sum(
            1 for i in cell_indices
            if getattr(mesh.cells[i], "crust_type", "") == "continental"
        )
        if n_cont < len(cell_indices) * 0.2:
            continue  # too oceanic — skip

        # Find interior cells (far from any boundary)
        interior = [
            i for i in cell_indices
            if mesh.cells[i].distance_to_boundary_km > 800
            and getattr(mesh.cells[i], "crust_type", "") == "continental"
        ]
        if len(interior) < 10:
            continue

        # Place 1–3 orogenic belts per plate
        n_belts = min(num_orogenies, max(1, len(interior) // 30))
        for _ in range(n_belts):
            # Pick two seed cells in the interior to define the belt line
            if len(interior) < 3:
                continue
            a_idx = interior[rng.integers(0, len(interior))]
            b_idx = interior[rng.integers(0, len(interior))]
            if a_idx == b_idx:
                continue

            a_pos = np.array([
                mesh.cells[a_idx].x, mesh.cells[a_idx].y, mesh.cells[a_idx].z,
            ])
            b_pos = np.array([
                mesh.cells[b_idx].x, mesh.cells[b_idx].y, mesh.cells[b_idx].z,
            ])
            # Direction vector of the belt (on sphere → great-circle arc)
            belt_dir = b_pos - a_pos
            belt_len = np.linalg.norm(belt_dir)
            if belt_len < 1e-12:
                continue
            belt_dir /= belt_len

            # Orogeny amplitude: 500–1500 m, varies per belt
            amplitude = rng.uniform(500.0, 1500.0)
            # Width of the belt (Gaussian sigma in km)
            sigma_km = rng.uniform(80.0, 200.0)
            cell_km = np.sqrt(4.0 * np.pi * config.radius_km**2 / n)

            belt_count = 0
            for i in interior:
                cell = mesh.cells[i]
                pos = np.array([cell.x, cell.y, cell.z])
                # Distance from point to the great-circle arc defined by a→b
                # Approximate: distance to the line segment in 3D, projected
                # to angular distance on the sphere
                vec = pos - a_pos
                proj = np.dot(vec, belt_dir)
                proj = max(0.0, min(belt_len, proj))  # clamp to segment
                closest = a_pos + proj * belt_dir
                closest_norm = np.linalg.norm(closest)
                if closest_norm < 1e-12:
                    continue
                closest /= closest_norm  # project back to unit sphere

                # Angular distance from cell to the belt line
                dot = np.clip(np.dot(pos, closest), -1.0, 1.0)
                ang_dist_rad = np.arccos(dot)
                dist_km = ang_dist_rad * config.radius_km

                if dist_km < 3 * sigma_km:
                    # Gaussian profile
                    weight = np.exp(-(dist_km * dist_km) / (2 * sigma_km * sigma_km))
                    # Add noise perturbation along the belt for natural look
                    noise = rng.uniform(-0.15, 0.15)
                    elevation[i] += amplitude * weight * (1.0 + noise)
                    mesh.cells[i].landform = "orogeny"
                    belt_count += 1

            total_affected += belt_count

        # Optional: rift valley (1 per plate, 30% chance)
        if rng.random() < 0.3 and len(interior) > 20:
            a_idx = interior[rng.integers(0, len(interior))]
            b_idx = interior[rng.integers(0, len(interior))]
            if a_idx != b_idx:
                a_pos = np.array([mesh.cells[a_idx].x, mesh.cells[a_idx].y, mesh.cells[a_idx].z])
                b_pos = np.array([mesh.cells[b_idx].x, mesh.cells[b_idx].y, mesh.cells[b_idx].z])
                rift_dir = b_pos - a_pos
                rift_len = np.linalg.norm(rift_dir)
                if rift_len > 1e-12:
                    rift_dir /= rift_len
                    rift_depth = rng.uniform(300.0, 800.0)
                    sigma_km = rng.uniform(40.0, 100.0)
                    for i in interior:
                        pos = np.array([mesh.cells[i].x, mesh.cells[i].y, mesh.cells[i].z])
                        vec = pos - a_pos
                        proj = np.dot(vec, rift_dir)
                        proj = max(0.0, min(rift_len, proj))
                        closest = a_pos + proj * rift_dir
                        norm = np.linalg.norm(closest)
                        if norm < 1e-12:
                            continue
                        closest /= norm
                        dot = np.clip(np.dot(pos, closest), -1.0, 1.0)
                        dist_km = np.arccos(dot) * config.radius_km
                        if dist_km < 3 * sigma_km:
                            weight = np.exp(-(dist_km**2) / (2 * sigma_km**2))
                            elevation[i] -= rift_depth * weight
                            mesh.cells[i].landform = "rift"
                            total_affected += 1

    if total_affected > 0:
        logger.info(
            "  Interior landforms: %d cells (orogenies=%d/plate, rifts 30%% chance)",
            total_affected, num_orogenies,
        )

    return elevation


def _log_synthesis_stats(
    elevation: np.ndarray,
    sea_level_m: float,
    n: int,
) -> None:
    """Consistent summary logging for all terrain algorithms."""
    above = np.sum(elevation > sea_level_m)
    logger.info(
        "Terrain synthesis complete: elev range [%.0f, %.0f] m, "
        "%.1f%% land, %.1f%% ocean",
        np.min(elevation), np.max(elevation),
        100 * above / n, 100 * (n - above) / n,
    )
