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

See ``docs/design/terrain-pipeline.md`` §5 for detailed algorithm reference.
"""

from __future__ import annotations

import logging
import zlib
from typing import TYPE_CHECKING

import numpy as np

from .geography import build_elevation_pins, build_land_bias_field
from .pipeline_types import TerrainPipelineConfig

if TYPE_CHECKING:
    from .models import CVTMesh, TectonicPlate

logger = logging.getLogger(__name__)

# Subduction-trench relief below the abyssal floor.  Earth's trenches reach
# ~−11 km (Mariana) while the abyssal plain sits near −4 km, so a ~7 km relief
# on the subducting side reproduces trench depths.  Applied only to oceanic
# crust on the oceanward side of convergent boundaries.
_TRENCH_RELIEF_M = 7000.0

# Authored-geography uplift suppression (roadmap #9): cells inside authored
# ocean basins / rift seas (strong negative land-bias) must not be lifted out
# of the water by a convergent boundary that happens to cross them.  Damping
# is continuous at the threshold (1.0 at bias = −0.5, i.e. normal orogeny is
# untouched) and floors at 0.1 for bias ≤ −1.
_ANCHOR_SUPPRESS_BIAS_THRESHOLD = -0.5
_ANCHOR_SUPPRESS_FLOOR = 0.1


# Plate-interior continental cells receive only this fraction of the uniform
# per-plate offset; the rest is replaced by multi-scale undulation so cratons
# stay low while plates still differ (Earth: cratons 0–800 m, not +2 km shelves).
_PLATE_OFFSET_LAND_FRACTION = 0.4


# ---------------------------------------------------------------------------
# Ocean floor age-depth subsidence (plate-cooling model)
# ---------------------------------------------------------------------------


def _compute_ocean_age_depth(
    mesh: CVTMesh,
    config: TerrainPipelineConfig,
) -> np.ndarray:
    """Depth (negative m) of each oceanic cell from plate-cooling subsidence.

    Ocean floor age is estimated as the normalised position between divergent
    (spreading ridge, age=0) and convergent (trench, age=max) boundaries.
    Cells mid-way between a ridge and a trench get intermediate ages.

        age = max_age · d_div / (d_div + d_conv)

    where d_div and d_conv are distances to the nearest divergent / convergent
    boundary respectively.  Depth then follows the half-space cooling law:

        depth = ridge_depth + subsidence_coeff · sqrt(age)

    capped at ``ocean_max_age_depth_m``.
    """
    from collections import deque

    n = len(mesh.cells)

    # ---- Multi-source BFS to divergent and convergent boundaries ----
    hops_div = np.full(n, -1, dtype=np.int32)
    hops_conv = np.full(n, -1, dtype=np.int32)
    q_div: deque[int] = deque()
    q_conv: deque[int] = deque()

    for i, cell in enumerate(mesh.cells):
        if cell.crust_type != "oceanic":
            continue
        bt = cell.boundary_type
        if bt == "divergent":
            hops_div[i] = 0
            q_div.append(i)
        elif bt == "convergent":
            hops_conv[i] = 0
            q_conv.append(i)

    # BFS from divergent boundaries
    while q_div:
        cur = q_div.popleft()
        for nid in mesh.cells[cur].neighbors:
            if not (0 <= nid < n):
                continue
            if mesh.cells[nid].crust_type != "oceanic":
                continue
            if hops_div[nid] == -1:
                hops_div[nid] = hops_div[cur] + 1
                q_div.append(nid)

    # BFS from convergent boundaries
    while q_conv:
        cur = q_conv.popleft()
        for nid in mesh.cells[cur].neighbors:
            if not (0 <= nid < n):
                continue
            if mesh.cells[nid].crust_type != "oceanic":
                continue
            if hops_conv[nid] == -1:
                hops_conv[nid] = hops_conv[cur] + 1
                q_conv.append(nid)

    # ---- Hops → distance (km) ----
    avg_spacing_km = (4.0 * config.radius_km) / np.sqrt(n) if n > 0 else 100.0
    d_div = hops_div.astype(np.float64) * avg_spacing_km
    d_conv = hops_conv.astype(np.float64) * avg_spacing_km

    # ---- Interplate ocean cells only ----
    # Cells that can reach both a divergent AND a convergent boundary
    # are "conveyor-belt" ocean floor with a meaningful age.
    # Cells that can only reach one type (e.g. a plate with no convergent
    # boundary) fall through to NaN and keep the uniform base.
    valid = (hops_div >= 0) & (hops_conv >= 0)
    both_zero = (d_div == 0.0) & (d_conv == 0.0)  # cell IS both types — skip
    valid = valid & ~both_zero

    # ---- Age interpolation ----
    # age = max_age · d_div / (d_div + d_conv)
    # At divergent (d_div=0): age=0 → shallow ridge
    # At convergent (d_conv=0): age=max → deep trench-adjacent floor
    fraction = np.divide(
        d_div,
        d_div + d_conv,
        out=np.full_like(d_div, 0.5),
        where=(d_div + d_conv) > 0,
    )
    age_myr = config.ocean_max_age_myr * fraction

    # ---- Age → depth ----
    depth_m = config.ocean_ridge_depth_m + config.ocean_subsidence_coeff * np.sqrt(age_myr)
    depth_m = np.minimum(depth_m, config.ocean_max_age_depth_m)

    result = np.full(n, np.nan, dtype=np.float64)
    result[valid] = -depth_m[valid]
    return result


def _relabel_leaked_crust(mesh: CVTMesh, geography_bias: np.ndarray | None = None) -> None:
    """Relabel isolated top-N crust-leakage cells to oceanic.

    The global top-N crust threshold sprinkles a few continental cells into
    oceanic regions (fBm blobs).  On Earth, oceanic islands are arc /
    hotspot / shelf features, not random sprinkles; islands here should
    likewise emerge only where island-arc / hotspot uplift or an author pin
    raises the seafloor.  Cells with a mostly-oceanic neighbourhood
    (cont_frac < 0.5, i.e. clusters smaller than ~4 cells) are relabelled
    oceanic before the base stage; boundary uplifts and pins can still lift
    them into hierarchical archipelagos afterwards.

    Only authored-ocean cells (bias < −0.3) are relabelled: isolated
    continental cells elsewhere may be the per-plate crust floor
    (``crust_plate_floor``), which must survive.
    """
    cont_frac = _neighbor_continental_fraction(mesh)
    n_relabeled = 0
    for i, c in enumerate(mesh.cells):
        if c.crust_type != "continental" or cont_frac[i] >= 0.5:
            continue
        if geography_bias is not None and geography_bias[i] >= -0.3:
            continue  # crust-floor cell in an unauthored region — keep
        c.crust_type = "oceanic"
        n_relabeled += 1
    if n_relabeled:
        logger.info("  Crust leakage cleanup: %d isolated cells relabelled oceanic", n_relabeled)


def _neighbor_continental_fraction(mesh: CVTMesh) -> np.ndarray:
    """Per-cell fraction of continental crust among self + neighbours.

    Used to distinguish true continental rifts (East-Africa style, embedded
    in continental crust) from top-N crust *leakage* cells sitting on an
    oceanic divergent boundary — the latter must follow the oceanic ridge
    profile, not the +1400 m continental-rift one.
    """
    isc = np.array([c.crust_type == "continental" for c in mesh.cells], dtype=np.float64)
    out = np.empty(len(isc), dtype=np.float64)
    for i, c in enumerate(mesh.cells):
        nb = c.neighbors
        out[i] = (isc[i] + float(isc[np.asarray(nb, dtype=np.int64)].sum())) / (1 + len(nb))
    return out


def _continental_undulation(mesh: CVTMesh, config: TerrainPipelineConfig) -> np.ndarray:
    """Multi-scale long-wavelength relief for continental interiors.

    Analog of dynamic topography (mantle convection ±500 m on Earth; Flament
    et al. 2013) plus craton-scale swells and shields.  Without it,
    plate-interior continents are unrealistically flat tablelands.
    """
    und_cfg = TerrainPipelineConfig(
        seed=config.seed + 600,
        noise_scale=config.regional_noise_scale,
        noise_octaves=3,
        noise_persistence=0.55,
        noise_lacunarity=2.2,
    )
    return generate_fbm_on_cells(mesh, und_cfg) * config.continental_undulation_m


def _apply_base_override(
    base: np.ndarray,
    geography_bias: np.ndarray | None,
    config: TerrainPipelineConfig,
) -> None:
    """Where the authored bias is decisive (|bias| > 0.5), the bimodal base
    follows the author, not the crust label.

    The top-N crust threshold always leaks a few continental cells into
    authored seas (and oceanic holes into authored continents); without this
    override those cells receive the +850 m continental base plus plate
    offsets and rise thousands of metres inside an authored rift sea
    (roadmap #9).  Anchoring thus reaches elevation, not just crust type.
    """
    if geography_bias is None:
        return
    oceanic = geography_bias < _ANCHOR_SUPPRESS_BIAS_THRESHOLD
    continental = geography_bias > -_ANCHOR_SUPPRESS_BIAS_THRESHOLD
    base[oceanic] = config.oceanic_elevation_m
    base[continental] = config.continental_elevation_m


def _anchor_uplift_damping(geography_bias: np.ndarray | None, n: int) -> np.ndarray:
    """Per-cell multiplier for positive convergent uplift (1.0 = unauthored)."""
    if geography_bias is None:
        return np.ones(n, dtype=np.float64)
    damp = np.clip(2.0 * geography_bias + 2.0, _ANCHOR_SUPPRESS_FLOOR, 1.0)
    return np.asarray(np.where(geography_bias < _ANCHOR_SUPPRESS_BIAS_THRESHOLD, damp, 1.0))


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
    """Compute 3D noise at scattered points on the sphere.

    Stage 1.1: Numba-JIT Perlin kernel (``noise_kernels``) replaces the
    former per-cell scalar ``opensimplex.noise3`` calls (~44 µs → ~0.1 µs).

    Args:
        x, y, z: (n,) coordinates on unit sphere.
        frequency: Noise frequency multiplier.
        seed: Noise seed.

    Returns:
        (n,) noise values approximately in [-1, 1].
    """
    from .noise_kernels import noise_on_points

    return noise_on_points(
        (x * frequency).ravel(),
        (y * frequency).ravel(),
        (z * frequency).ravel(),
        seed,
    )


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
    xyz = mesh.cell_xyz
    x, y, z = xyz[:, 0], xyz[:, 1], xyz[:, 2]

    result = np.zeros(n, dtype=np.float64)
    amplitude = 1.0
    frequency = config.noise_scale

    for i in range(config.noise_octaves):
        noise = _compute_noise_elementwise_xyz(x, y, z, frequency, config.seed + i * 1000)
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


def _dual_boundary_falloff(
    d_km: np.ndarray,
    ridge_sigma_km: float = 80.0,
    shoulder_sigma_km: float = 400.0,
    shoulder_strength: float = 0.3,
) -> np.ndarray:
    """Dual-component boundary distance falloff.

    Combines a narrow Gaussian (sharp ridge crest) with a wider Gaussian
    (plateau shoulder) so mountain *ranges* are visible as linear features
    rather than broad uplifts::

        falloff = (exp(-d²/2σᵣ²) + α·exp(-d²/2σₛ²)) / (1 + α)

    At d=0: 1.0.  At d=σᵣ: dominated by shoulder.  At d≫σₛ: → 0.
    """
    ridge = np.exp(-(d_km * d_km) / (2.0 * ridge_sigma_km * ridge_sigma_km))
    shoulder = np.exp(-(d_km * d_km) / (2.0 * shoulder_sigma_km * shoulder_sigma_km))
    return (ridge + shoulder_strength * shoulder) / (1.0 + shoulder_strength)  # type: ignore[no-any-return]


def apply_boundary_effects(
    mesh: CVTMesh,
    config: TerrainPipelineConfig,
    *,
    geography_bias: np.ndarray | None = None,
    uplift_mod: np.ndarray | None = None,
    plate_offsets: dict[str, float] | None = None,
    cont_frac: np.ndarray | None = None,
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
    shoulder_sigma = config.boundary_influence_km
    ridge_sigma = config.boundary_ridge_sigma_km
    shoulder_strength = config.boundary_shoulder_strength

    # Reference convergence rate for normalization (10 cm/yr is very fast)
    ref_rate = 5.0  # cm/yr — median plate speed
    damp = _anchor_uplift_damping(geography_bias, n)
    mod = uplift_mod if uplift_mod is not None else np.ones(n, dtype=np.float64)

    # ---- Build per-cell boundary arrays in a single pass ----
    btype = np.array([c.boundary_type or "" for c in mesh.cells], dtype=object)
    dist = np.array(
        [
            c.distance_to_boundary_km if c.distance_to_boundary_km is not None else 1e9
            for c in mesh.cells
        ],
        dtype=np.float64,
    )
    rate_arr = np.array([abs(c.convergence_rate_cm_yr) for c in mesh.cells], dtype=np.float64)

    # Mask: boundary cells within influence radius
    mask = (btype != "") & (btype != "none") & (dist < 1.2 * shoulder_sigma)
    if not np.any(mask):
        return delta_h

    # Vectorised falloff for all boundary cells at once
    falloff = np.zeros(n, dtype=np.float64)
    falloff[mask] = _dual_boundary_falloff(
        dist[mask], ridge_sigma, shoulder_sigma, shoulder_strength
    )

    # Rate factor
    rate_factor = (rate_arr[mask] / ref_rate) ** 0.5

    is_conv = btype[mask] == "convergent"
    is_div = btype[mask] == "divergent"

    # Convergent: uplift
    conv_idx = np.where(mask)[0][is_conv]
    if len(conv_idx) > 0:
        delta_h[conv_idx] = (
            config.convergent_uplift_m * falloff[conv_idx] * rate_factor[is_conv] * damp[conv_idx]
        )

    # Divergent: subsidence
    div_idx = np.where(mask)[0][is_div]
    if len(div_idx) > 0:
        # 0.35×: Earth ridge crests sit ~1300 m above the abyss but
        # ~2500 m BELOW sea level.  Plate offsets are assembled from the
        # per-plate dict; cells without a plate use offset 0.
        div_offsets = np.array(
            [
                plate_offsets.get(mesh.cells[_j].plate_id or "", 0.0) if plate_offsets else 0.0
                for _j in div_idx
            ],
            dtype=np.float64,
        )
        delta_h[div_idx] = (
            0.35 * config.divergent_depth_m * falloff[div_idx] * rate_factor[is_div] * mod[div_idx]
            - 0.6 * div_offsets
        )
        # Transform boundaries: no systematic elevation change

    return delta_h


# ---------------------------------------------------------------------------
# Sea/land classification
# ---------------------------------------------------------------------------


def classify_sea_land(
    mesh: CVTMesh,
    sea_level_m: float,
    *,
    buffer_m: float = 50.0,
) -> None:
    """Update crust_type based on final elevation vs sea level.

    Cells within ±*buffer_m* of sea level are marked ``transitional``
    regardless of original crust type — this prevents near-sea-level
    shelf cells from appearing as deep ocean.

    Cells far above sea level with oceanic crust become ``transitional``
    (islands, seamounts).  Submerged continental crust is left as
    ``continental`` (the geological definition of continental shelves).

    Modifies cells in-place.
    """
    for cell in mesh.cells:
        near_sea = abs(cell.elevation - sea_level_m) <= buffer_m
        if near_sea or cell.elevation > sea_level_m and cell.crust_type == "oceanic":
            cell.crust_type = "transitional"


def _apply_geography_pins(
    mesh: CVTMesh,
    elevation: np.ndarray,
    config: TerrainPipelineConfig,
) -> np.ndarray:
    """Pull elevation toward authored ``elevation_target_m`` values.

    Applied after sea-level calibration and all post-processing (shelf, arcs,
    plains) so procedural stages cannot overwrite a pinned strait depth or
    isthmus height — the author's intent is the final arbiter.  Targets are
    relative to the *calibrated* (interglacial) sea surface at 0 m, i.e. they
    pin the seabed/land in absolute terms; ``sea_level_offset_m`` then moves
    the water against the pinned floor — a −80 m strait pin emerges (and the
    strait closes) under a −120 m glacial offset.  The blend ``s·w ∈ [0,1]``
    is a convex combination (no overshoot), with the feature kernel providing
    the spatial soft edge and ``pin_strength`` the trust.

    No-op (returns *elevation* unchanged) when no feature declares a target.
    """
    spec = config.geography
    if spec is None:
        return elevation
    pins = build_elevation_pins(mesh, spec)
    if pins is None:
        return elevation
    weight, target, strength, exponent = pins
    # Decisive core, soft edge: the kernel rarely hits exactly 1 on a discrete
    # mesh, so saturate the blend factor at w ≥ 0.5 — the author's target is
    # authoritative at the feature core while the rim still fades smoothly.
    factor = strength * np.asarray(np.clip(2.0 * weight, 0.0, 1.0))
    # Deviation exponentiation: cells further from target get proportionally
    # stronger pull (exponent > 1 = 削峰强力, 平原温和; exponent = 1 = 线性).
    # Normalised to a reference scale so exponent=1.0 is byte-identical
    # to the linear formula.
    deviation = target - elevation
    ref = 1000.0  # metres — at this deviation the pull equals linear
    normalised = deviation / ref
    exaggerated = np.sign(normalised) * np.power(np.abs(normalised), exponent)
    pull = exaggerated * ref
    pulled = elevation + factor * pull
    n_pinned = int(np.count_nonzero(weight > 0.0))
    logger.info("  Geography pins: %d cells pulled toward authored targets", n_pinned)
    return np.asarray(pulled)


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
    *,
    raster_bias: np.ndarray | None = None,
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
            f"Unknown terrain algorithm '{algo}'. Available: {sorted(_TERRAIN_ALGORITHMS.keys())}"
        )
    # Authored land-bias field (pure function of (mesh, spec[, raster]),
    # identical to the one used for crust anchoring) so convergent uplift can
    # be damped inside authored ocean basins / rift seas.
    spec = config.geography
    geography_bias = (
        build_land_bias_field(mesh, spec, raster_bias=raster_bias)
        if spec is not None and (spec.features or raster_bias is not None)
        else None
    )
    # Low-frequency stochastic modulation for divergent-ridge / island-arc
    # uplift (hierarchical islands instead of uniform chains).
    uplift_mod: np.ndarray | None = None
    if config.boundary_uplift_noise > 0:
        mod_cfg = TerrainPipelineConfig(
            seed=config.seed + 400,
            noise_scale=config.regional_noise_scale,
            noise_octaves=2,
            noise_persistence=0.55,
            noise_lacunarity=2.0,
        )
        uplift_mod = 1.0 + config.boundary_uplift_noise * generate_fbm_on_cells(mesh, mod_cfg)
    if algo == "cortial2019_gaussian":
        _synthesize_gaussian(
            mesh, plates, config, geography_bias=geography_bias, uplift_mod=uplift_mod
        )
    elif algo == "cortial2019_asymmetric":
        _synthesize_asymmetric(
            mesh, plates, config, geography_bias=geography_bias, uplift_mod=uplift_mod
        )


# =========================================================================
# Algorithm: cortial2019_gaussian (original)
# =========================================================================


def _synthesize_gaussian(
    mesh: CVTMesh,
    plates: list[TectonicPlate],
    config: TerrainPipelineConfig,
    *,
    geography_bias: np.ndarray | None = None,
    uplift_mod: np.ndarray | None = None,
) -> None:
    """Cortial 2019 §4 — symmetric Gaussian boundary mountain profiles."""
    logger.info("Synthesizing terrain elevation")
    n = mesh.num_cells
    rng = np.random.default_rng(config.seed + 100)

    # 1. Bimodal base elevation
    logger.info("  Step 1/5: Bimodal base elevation")
    _relabel_leaked_crust(mesh, geography_bias)
    base = np.full(n, config.oceanic_elevation_m, dtype=np.float64)
    for i, cell in enumerate(mesh.cells):
        if cell.crust_type == "continental":
            base[i] = config.continental_elevation_m
    _apply_base_override(base, geography_bias, config)

    # 1c. Ocean floor age-depth subsidence (replaces uniform oceanic base)
    if config.ocean_age_depth_enabled:
        logger.info(
            "  Step 1c/5: Ocean age-depth (rate=%.1f cm/yr, ridge=%.0fm, max=%.0fm)",
            config.ocean_spreading_rate_cm_yr,
            config.ocean_ridge_depth_m,
            config.ocean_max_age_depth_m,
        )
        age_depth = _compute_ocean_age_depth(mesh, config)
        ocean_mask = np.array([c.crust_type == "oceanic" for c in mesh.cells])
        valid = ocean_mask & np.isfinite(age_depth)
        base[valid] = age_depth[valid]

    # 1b. Per-plate random elevation offset
    # Oceanic plates shift fully; continental interiors keep only a fraction
    # of the uniform offset plus multi-scale undulation (cratons stay low).
    logger.info(
        "  Step 2/5: Per-plate elevation offset (spread=%.0fm)", config.plate_elevation_spread_m
    )
    rng = np.random.default_rng(config.seed + 100)
    plate_offsets: dict[str, float] = {}
    for plate in plates:
        # Random offset uniformly distributed in [-spread, +spread]
        plate_offsets[plate.id] = rng.uniform(
            -config.plate_elevation_spread_m,
            config.plate_elevation_spread_m,
        )

    und = _continental_undulation(mesh, config)
    # Apply offsets to base elevation
    for i, cell in enumerate(mesh.cells):
        if cell.plate_id and cell.plate_id in plate_offsets:
            off = plate_offsets[cell.plate_id]
            if cell.crust_type == "continental":
                base[i] += _PLATE_OFFSET_LAND_FRACTION * off + und[i]
            else:
                base[i] += off

    # 2. Tectonic boundary effects
    logger.info("  Step 3/5: Tectonic boundary effects")
    boundary_delta = apply_boundary_effects(
        mesh,
        config,
        geography_bias=geography_bias,
        uplift_mod=uplift_mod,
        plate_offsets=plate_offsets,
        cont_frac=_neighbor_continental_fraction(mesh),
    )

    # 3a. Low-frequency regional noise (creates broad elevation trends within plates)
    logger.info(
        "  Step 4/5: Regional noise (scale=%.1f) + detail noise (%d octaves)",
        config.regional_noise_scale,
        config.noise_octaves,
    )

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
        base >= 0.0,
        config.regional_noise_amplitude_land_m,
        config.regional_noise_amplitude_ocean_m,
    )
    regional_contribution = regional_fbm * regional_amplitude

    # 3b. High-frequency detail noise (existing)
    fbm = generate_fbm_on_cells(mesh, config)

    # Amplitude-modulated by terrain type
    noise_amplitude = np.where(
        base >= 0.0,
        config.noise_amplitude_land_m,
        config.noise_amplitude_ocean_m,
    )

    # Distance-to-boundary modulation: more mountainous near boundaries,
    # with a 1.2× base noise floor in plate interiors.
    shoulder_sigma = config.boundary_influence_km
    interior_factor = np.full(n, 1.2, dtype=np.float64)
    for i, cell in enumerate(mesh.cells):
        d = cell.distance_to_boundary_km
        if d is not None and d < 1.2 * shoulder_sigma:
            proximity = float(
                _dual_boundary_falloff(
                    np.array([d]),
                    config.boundary_ridge_sigma_km,
                    shoulder_sigma,
                    config.boundary_shoulder_strength,
                )[0]
            )
            interior_factor[i] = 1.2 + 0.3 * proximity

    detail_contribution = fbm * noise_amplitude * interior_factor

    # 4. Combine all components
    logger.info("  Step 5/5: Combining elevation components")
    elevation = base + boundary_delta + regional_contribution + detail_contribution

    # Write back to cells
    for i, cell in enumerate(mesh.cells):
        cell.elevation = float(elevation[i])

    # Sea level auto-calibration ("倒水")
    if config.sea_level_auto:
        elevation = _apply_sea_level_calibration(mesh, elevation, config)
        for i, cell in enumerate(mesh.cells):
            cell.elevation = float(elevation[i])

    # Post-processing (shared with asymmetric: shelf/plain must run last)
    sea_level = config.sea_level_offset_m
    elevation = _apply_island_arcs(
        mesh, elevation, config, geography_bias=geography_bias, uplift_mod=uplift_mod
    )
    elevation = _apply_continental_shelf(mesh, elevation, config, rng)
    elevation = _apply_coastal_plain(mesh, elevation, config, rng)

    # Author elevation pins: the author's final word on elevation, applied
    # after every procedural stage so shelf/arcs cannot overwrite a pinned
    # strait depth or isthmus height.
    elevation = _apply_geography_pins(mesh, elevation, config)

    # Isostasy: compress only the tail that exceeds physical limits.
    # Unlike global scaling (which compresses the entire distribution),
    # this leaves the bulk of cells untouched and only pulls back extremes.
    # Excess above/below the limit is folded back with exponential decay,
    # so peaks stay higher than foothills but no cell exceeds the limit.
    # Limits: h_max ∝ 1/g  (see isostasy_elevation_limits.md).
    if config.isostasy_enabled:
        land_limit = config.isostasy_max_continental_elevation_m
        ocean_limit = config.isostasy_max_ocean_depth_m

        # Land: compress cells above limit
        over = elevation > land_limit
        if np.any(over):
            excess = elevation[over] - land_limit
            elevation[over] = land_limit + excess * np.exp(-5.0 * excess / land_limit)

        # Ocean: compress cells below (deeper than) limit
        over_deep = elevation < -ocean_limit
        if np.any(over_deep):
            excess = -ocean_limit - elevation[over_deep]  # positive excess depth
            elevation[over_deep] = -ocean_limit - excess * np.exp(-5.0 * excess / ocean_limit)

    _smooth_land_discontinuities(mesh, elevation, iterations=3, blend=0.3)

    # Write post-processed elevation back to cells
    for i, cell in enumerate(mesh.cells):
        cell.elevation = float(elevation[i])

    # Classify sea/land
    classify_sea_land(mesh, sea_level)

    _log_synthesis_stats(elevation, sea_level, n)
    _compute_quality_metrics(mesh, sea_level)


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
    *,
    geography_bias: np.ndarray | None = None,
    uplift_mod: np.ndarray | None = None,
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
    _apply_base_override(base, geography_bias, config)

    if config.ocean_age_depth_enabled:
        age_depth = _compute_ocean_age_depth(mesh, config)
        ocean_mask = np.array([c.crust_type == "oceanic" for c in mesh.cells])
        valid = ocean_mask & np.isfinite(age_depth)
        base[valid] = age_depth[valid]

    logger.info("  Step 1/6: Base elevation + plate offsets")
    _relabel_leaked_crust(mesh, geography_bias)
    plate_offsets: dict[str, float] = {}
    for plate in plates:
        plate_offsets[plate.id] = rng.uniform(
            -config.plate_elevation_spread_m,
            config.plate_elevation_spread_m,
        )
    und = _continental_undulation(mesh, config)
    for i, cell in enumerate(mesh.cells):
        if cell.plate_id and cell.plate_id in plate_offsets:
            off = plate_offsets[cell.plate_id]
            if cell.crust_type == "continental":
                base[i] += _PLATE_OFFSET_LAND_FRACTION * off + und[i]
            else:
                base[i] += off

    # 2. Asymmetric boundary effects
    logger.info(
        "  Step 2/6: Asymmetric boundary profiles (asymmetry=%.2f)", config.mountain_asymmetry
    )
    boundary_delta, transform_boost = _asymmetric_boundary_effects(
        mesh,
        config,
        geography_bias=geography_bias,
        uplift_mod=uplift_mod,
        plate_offsets=plate_offsets,
        cont_frac=_neighbor_continental_fraction(mesh),
    )

    # 3. Hotspot volcanic chains
    hotspot_delta = np.zeros(n, dtype=np.float64)
    if config.hotspot_count > 0:
        logger.info("  Step 3/6: Hotspot chains (%d hotspots)", config.hotspot_count)
        hotspot_delta = _generate_hotspots(mesh, plates, config, rng)

    # 4–5. Regional + detail noise (reuse)
    logger.info("  Step 4/6: Regional noise (scale=%.1f)", config.regional_noise_scale)
    regional_cfg = TerrainPipelineConfig(
        seed=config.seed + 200,
        noise_scale=config.regional_noise_scale,
        noise_octaves=3,
        noise_persistence=0.6,
        noise_lacunarity=2.0,
    )
    regional_fbm = generate_fbm_on_cells(mesh, regional_cfg)
    regional_amp = np.where(
        base >= 0.0,
        config.regional_noise_amplitude_land_m,
        config.regional_noise_amplitude_ocean_m,
    )

    logger.info(
        "  Step 5/6: Detail noise (%d octaves, anisotropy=%.2f)",
        config.noise_octaves,
        config.noise_anisotropy,
    )
    strike = _compute_boundary_strike(mesh) if config.noise_anisotropy > 0 else None
    fbm = _anisotropic_fbm(mesh, config, strike) if strike else generate_fbm_on_cells(mesh, config)
    noise_amp = np.where(
        base >= 0.0,
        config.noise_amplitude_land_m,
        config.noise_amplitude_ocean_m,
    )

    # Boundary-proximity factor.
    # Near boundaries: up to 1.5× noise (rugged mountains).
    # Plate interiors: 1.2× base noise (enough texture on high plateaus).
    shoulder_sigma = config.boundary_influence_km
    interior_factor = np.full(n, 1.2, dtype=np.float64)
    for i, cell in enumerate(mesh.cells):
        d = cell.distance_to_boundary_km
        if d is not None and d < 1.2 * shoulder_sigma:
            interior_factor[i] = 1.2 + 0.3 * float(
                _dual_boundary_falloff(
                    np.array([d]),
                    config.boundary_ridge_sigma_km,
                    shoulder_sigma,
                    config.boundary_shoulder_strength,
                )[0]
            )

    # 6. Combine
    logger.info("  Step 6/6: Combining components")
    elevation = (
        base
        + boundary_delta
        + hotspot_delta
        + regional_fbm * regional_amp
        + fbm * noise_amp * interior_factor * transform_boost
    )

    for i, cell in enumerate(mesh.cells):
        cell.elevation = float(elevation[i])

    # Sea level auto-calibration ("倒水")
    if config.sea_level_auto:
        elevation = _apply_sea_level_calibration(mesh, elevation, config)
        for i, cell in enumerate(mesh.cells):
            cell.elevation = float(elevation[i])

    # Post-processing (order matters: arcs/orogeny add elevation,
    # shelf/plain must run last to not be overwritten)
    sea_level = config.sea_level_offset_m
    elevation = _apply_island_arcs(
        mesh, elevation, config, geography_bias=geography_bias, uplift_mod=uplift_mod
    )
    elevation = _apply_interior_landforms(mesh, elevation, config, rng)
    elevation = _apply_continental_shelf(mesh, elevation, config, rng)
    elevation = _apply_coastal_plain(mesh, elevation, config, rng)

    # Author elevation pins (final word; see _apply_geography_pins)
    elevation = _apply_geography_pins(mesh, elevation, config)

    # Isostasy: compress only the tail that exceeds physical limits.
    if config.isostasy_enabled:
        land_limit = config.isostasy_max_continental_elevation_m
        ocean_limit = config.isostasy_max_ocean_depth_m
        over = elevation > land_limit
        if np.any(over):
            excess = elevation[over] - land_limit
            elevation[over] = land_limit + excess * np.exp(-5.0 * excess / land_limit)
        over_deep = elevation < -ocean_limit
        if np.any(over_deep):
            excess = -ocean_limit - elevation[over_deep]
            elevation[over_deep] = -ocean_limit - excess * np.exp(-5.0 * excess / ocean_limit)

    # Graph Laplacian smoothing: reduce cliff-like discontinuities
    # between neighbouring land cells caused by isostasy selectively
    # compressing peaks but leaving mid-elevation cells untouched.
    # 3 iterations of 30% blend → sharp steps relaxed ~66%.
    _smooth_land_discontinuities(mesh, elevation, iterations=3, blend=0.3)

    # Write post-processed elevation back to cells
    for i, cell in enumerate(mesh.cells):
        cell.elevation = float(elevation[i])

    classify_sea_land(mesh, sea_level)
    _log_synthesis_stats(elevation, sea_level, n)
    _compute_quality_metrics(mesh, sea_level)


def _smooth_land_discontinuities(
    mesh: CVTMesh,
    elevation: np.ndarray,
    *,
    iterations: int = 3,
    blend: float = 0.3,
) -> None:
    """Graph Laplacian smoothing on land cells (modifies elevation in-place).

    Each iteration blends every land cell toward the mean of its land
    neighbours, relaxing cliff-like steps without flattening legitimate
    mountain shapes.
    """
    n = len(mesh.cells)
    # Precompute per-cell neighbour land-mean for vectorised smoothing
    nbr_sum = np.empty(n, dtype=np.float64)
    nbr_count = np.empty(n, dtype=np.int32)
    land_mask = elevation > 0

    for _ in range(iterations):
        nbr_sum.fill(0.0)
        nbr_count.fill(0)
        for i, cell in enumerate(mesh.cells):
            if not land_mask[i]:
                continue
            for nid in cell.neighbors:
                if 0 <= nid < n and land_mask[nid]:
                    nbr_sum[i] += elevation[nid]
                    nbr_count[i] += 1

        valid = nbr_count > 0
        nbr_mean = np.divide(nbr_sum, nbr_count, out=np.full_like(nbr_sum, elevation), where=valid)
        # Blend:  (1 - blend) * self  +  blend * neighbours
        elevation[valid] = (1.0 - blend) * elevation[valid] + blend * nbr_mean[valid]


def _asymmetric_boundary_effects(
    mesh: CVTMesh,
    config: TerrainPipelineConfig,
    *,
    geography_bias: np.ndarray | None = None,
    uplift_mod: np.ndarray | None = None,
    plate_offsets: dict[str, float] | None = None,
    cont_frac: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Boundary-type-specific elevation profiles.

    Convergent (C-C / C-O / O-O)
        Asymmetric mountain range on the overriding plate: steep front
        (σ ≈ 200 km) facing the trench, gentle back-slope (σ ≈ 700 km).
        Oceanic trench at 100–150 km from the peak on the subducting side.

    Divergent (continental rift / mid-ocean ridge)
        Continental: deep central rift valley with flanking highlands
        (e.g. East African Rift).  Oceanic: broad submarine ridge rising
        ~1300 m above the abyssal plain (peak ≈ −2500 m), occasionally
        breaking the surface (Iceland-type).

    Transform
        No systematic elevation change.  Instead, a narrow band of
        enhanced roughness (±50 % noise boost within ~200 km) creates
        linear valleys and shutter ridges characteristic of strike-slip
        fault zones (e.g. San Andreas, North Anatolian).

    References
    ----------
    * Cortial et al. (2019) §4.1 — subduction uplift with velocity-dependent
      amplitude and squared-elevation feedback.
    * Willett (1999) — windward/leeward asymmetry from orographic precipitation.
    * Wilson (1963) — hotspot volcanic chains from plate motion over fixed plume.
    * Frisch, W., Meschede, M., & Blakey, R. (2011). *Plate Tectonics*.
      Springer. — mid-ocean ridge morphology, transform fault features.
    """
    n = mesh.num_cells
    delta_h = np.zeros(n, dtype=np.float64)
    asym = config.mountain_asymmetry  # [0, 1]
    shoulder_sigma = config.boundary_influence_km
    ridge_sigma = config.boundary_ridge_sigma_km
    shoulder_strength = config.boundary_shoulder_strength
    damp = _anchor_uplift_damping(geography_bias, n)
    mod = uplift_mod if uplift_mod is not None else np.ones(n, dtype=np.float64)

    # Reference convergence rate for normalisation.
    # Earth: fast plates (Pacific) ~10 cm/yr, slow (Africa) ~1 cm/yr,
    # median ~5 cm/yr.  Using the median as reference, then taking the
    # square root, gives a sub-linear saturating curve:
    #   1 cm/yr → 0.45   5 cm/yr → 1.0   10 cm/yr → 1.41   14 cm/yr → 1.67
    # This matches the geological observation that mountain height grows
    # with convergence rate but with diminishing returns (no hard cap).
    ref_rate = 5.0  # cm/yr — median plate speed

    # Along-arc heterogeneity (Japan-type arcs: main island + islets +
    # graben seas).  A medium-wavelength fBm (~800 km) modulates uplift
    # amplitude AND belt width, so convergent belts segment instead of
    # running as uniform ribbons.
    from .noise_kernels import fbm_on_points

    px = mesh.cell_xyz[:, 0]
    py = mesh.cell_xyz[:, 1]
    pz = mesh.cell_xyz[:, 2]
    arc_noise = fbm_on_points(
        px,
        py,
        pz,
        int(config.seed) + 5150,
        octaves=2,
        lacunarity=2.0,
        persistence=0.5,
        base_freq=8.0,
    )
    arc_u = 0.5 * (arc_noise + 1.0)  # [0, 1]

    for i, cell in enumerate(mesh.cells):
        if cell.boundary_type is None:
            continue
        d = cell.distance_to_boundary_km
        if d is None or d > 1.2 * shoulder_sigma:
            continue

        rate = abs(cell.convergence_rate_cm_yr)
        rate_factor = (rate / ref_rate) ** 0.5  # sub-linear power law
        crust = getattr(cell, "crust_type", "")

        if cell.boundary_type == "convergent":
            # ---- Convergent: asymmetric mountain + trench ----------------
            # Narrower sigma for convergent belts (more focused deformation)
            sigma_conv = shoulder_sigma * 0.8  # 400 km
            # Along-arc segmentation: belt width varies 0.7–1.3× and the
            # amplitude factor spans [-0.25, 1.35] — high segments become
            # main islands/mountain knots, low ones islets or shelf, negative
            # ones subside into graben seas between arc segments.
            u = arc_u[i]
            seg_mod = 1.6 * u - 0.25
            sigma_front = (
                sigma_conv * (1.0 - asym * 0.5) * (0.7 + 0.6 * u)  # steep side
            )

            # Mountain peak offset toward overriding plate (50–150 km)
            peak_offset = asym * sigma_conv * 0.25
            dist_from_peak = abs(d - peak_offset)
            mountain = float(
                _dual_boundary_falloff(
                    np.array([dist_from_peak]), ridge_sigma, sigma_front, shoulder_strength
                )[0]
            )

            # Crust-type-dependent amplitude
            if crust == "continental":
                amp = config.convergent_uplift_m * 1.3  # C-C collision
            else:
                amp = config.convergent_uplift_m * 0.6  # O-O island arc

            delta_h[i] = amp * mountain * rate_factor * seg_mod * damp[i]

            # Oceanic trench on the subducting side (100–200 km from peak).
            # Only oceanic crust subducts and forms a trench; continental
            # collision has no trench.  Deepened to ~6 km relief so trenches
            # reach abyssal-trench depths (~−10 km; Mariana ≈ −11 km).
            trench_dist_km = sigma_conv * 0.35  # ~140 km
            if d > trench_dist_km and crust == "oceanic":
                dist_from_trench = abs(d - trench_dist_km - peak_offset)
                trench_sigma = sigma_conv * 0.25  # narrow, sharp trench
                trench = -_TRENCH_RELIEF_M * np.exp(
                    -(dist_from_trench * dist_from_trench) / (2 * trench_sigma * trench_sigma)
                )
                delta_h[i] += trench * rate_factor

        elif cell.boundary_type == "divergent":
            # ---- Divergent: rift + ridge, crust-aware ---------------------
            sigma_div = shoulder_sigma * 0.6  # 300 km — narrower rift zone
            # Top-N crust leakage on an oceanic boundary (neighbourhood mostly
            # oceanic) follows the oceanic ridge profile, not the +1400 m
            # continental-rift one; −0.6×off decouples ridge depth from the
            # plate offset so crests stay near −2500 m (Earth-like).
            leaked = crust == "continental" and cont_frac is not None and cont_frac[i] < 0.5
            off_i = plate_offsets.get(cell.plate_id or "", 0.0) if plate_offsets else 0.0

            if crust == "oceanic" or leaked:
                # Mid-ocean ridge: broad submarine rise, shallow central graben.
                # Earth: ridge crest ~1300 m above the abyss, ~-2500 m below sea
                # level.  0.35× keeps crests submerged even on high-offset
                # oceanic plates after sea-level calibration (2026-08 feedback).
                ridge_amp = config.divergent_depth_m * 0.35
                ridge = ridge_amp * np.exp(
                    -(abs(d - sigma_div * 0.2) ** 2) / (2 * (sigma_div * 0.45) ** 2)
                )
                # Shallow central rift (only ~300 m deeper than the ridge flanks)
                rift = (
                    -config.divergent_depth_m
                    * 0.15
                    * np.exp(-(d * d) / (2 * (sigma_div * 0.2) ** 2))
                )
                delta_h[i] = (rift + ridge) * rate_factor * mod[i] - 0.6 * off_i
            else:
                # Continental rift: deep central valley + flanking highlands
                # (East African Rift, Baikal).  The rift floor can drop below
                # sea level (Dead Sea, Danakil Depression).
                rift = (
                    -config.divergent_depth_m
                    * 0.5
                    * np.exp(-(d * d) / (2 * (sigma_div * 0.25) ** 2))
                )
                ridge = (
                    config.divergent_depth_m
                    * 0.7
                    * np.exp(-(abs(d - sigma_div * 0.35) ** 2) / (2 * (sigma_div * 0.45) ** 2))
                )
                delta_h[i] = (rift + ridge) * rate_factor * mod[i]

    # ---- Transform: roughness-only (no systematic elevation change) ----
    # Collect transform boundary cells for a narrow roughness boost.
    # Strike-slip fault zones (San Andreas, North Anatolian) feature
    # linear valleys, shutter ridges, and sag ponds — local roughness
    # ~1.5× within ~200 km of the fault trace.
    transform_cells: list[int] = []
    for i, cell in enumerate(mesh.cells):
        if cell.boundary_type == "transform":
            transform_cells.append(i)
            mesh.cells[i].landform = (
                "transform" if not mesh.cells[i].landform else mesh.cells[i].landform
            )

    # BFS from transform boundary cells (narrow band: σ × 0.4 ≈ 200 km)
    transform_boost = np.ones(n, dtype=np.float64)
    if transform_cells:
        sigma_trans = shoulder_sigma * 0.4  # 200 km — transform faults are linear, narrow
        from collections import deque

        tq: deque[int] = deque()
        tdist: dict[int, float] = {}
        for cid in transform_cells:
            tdist[cid] = 0.0
            tq.append(cid)

        cell_km = np.sqrt(4.0 * np.pi * config.radius_km**2 / n)
        while tq:
            cid = tq.popleft()
            d_t = tdist[cid]
            if d_t >= 1.2 * sigma_trans:
                continue
            # Boost factor: 1.5 at the fault trace, decaying to 1.0 at 200 km
            transform_boost[cid] = 1.0 + 0.5 * np.exp(
                -(d_t * d_t) / (2 * sigma_trans * sigma_trans)
            )
            for nid in mesh.cells[cid].neighbors:
                if nid not in tdist:
                    tdist[nid] = d_t + cell_km
                    tq.append(nid)

    return delta_h, transform_boost


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

        for _ in range(max_chain_cells):
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
                dir_to_neighbor = np.array(
                    [
                        nc.x - current.x,
                        nc.y - current.y,
                        nc.z - current.z,
                    ]
                )
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
        num_hotspots,
        int(np.sum(hotspot_field > 0)),
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
    xyz = mesh.cell_xyz
    x, y, z = xyz[:, 0], xyz[:, 1], xyz[:, 2]

    anisotropy = config.noise_anisotropy

    # Vectorized strike frame (Stage 1.1): boundary_strike dict → (n, 3) array
    # once, outside the octave loop (formerly re-looked-up per cell per octave).
    strike_arr: np.ndarray | None = None
    if anisotropy > 0.0 and boundary_strike is not None:
        strike_arr = np.zeros((n, 3), dtype=np.float64)
        for i, s in boundary_strike.items():
            strike_arr[i] = s

    result = np.zeros(n, dtype=np.float64)
    amplitude = 1.0
    frequency = config.noise_scale

    for octave in range(config.noise_octaves):
        if strike_arr is not None:
            # Stretch coordinates along local strike direction (vectorized)
            sx = strike_arr[:, 0]
            sy = strike_arr[:, 1]
            sz = strike_arr[:, 2]
            has_strike = np.any(strike_arr != 0.0, axis=1)

            along = x * sx + y * sy + z * sz
            px = x - along * sx
            py = y - along * sy
            pz = z - along * sz
            across = np.sqrt(px * px + py * py + pz * pz)

            # Tangential compress / perpendicular expand
            fa = along / (1.0 + anisotropy)
            fb = across * (1.0 + anisotropy)
            fx = np.where(has_strike, fa * sx + fb * px, x)
            fy = np.where(has_strike, fa * sy + fb * py, y)
            fz = np.where(has_strike, fa * sz + fb * pz, z)

            noise = _compute_noise_elementwise_xyz(
                fx,
                fy,
                fz,
                frequency,
                config.seed + octave * 1000,
            )
        else:
            noise = _compute_noise_elementwise_xyz(
                x,
                y,
                z,
                frequency,
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

    # 2. RMS roughness (local cell-to-cell variance), vectorized over the
    #    adjacency graph via np.add.at accumulation (previously a per-cell
    #    Python loop calling np.var on tiny lists).
    offsets = np.fromiter((len(cell.neighbors) for cell in mesh.cells), dtype=np.int64, count=n)
    rows = np.repeat(np.arange(n), offsets)
    cols = np.fromiter(
        (nb for cell in mesh.cells for nb in cell.neighbors),
        dtype=np.int64,
        count=int(offsets.sum()),
    )
    counts = np.ones(n, dtype=np.float64)
    sums = elevations.copy()
    sq_sums = elevations**2
    np.add.at(counts, rows, 1.0)
    np.add.at(sums, rows, elevations[cols])
    np.add.at(sq_sums, rows, elevations[cols] ** 2)
    means = sums / counts
    variances = np.maximum(sq_sums / counts - means**2, 0.0)
    rms_roughness = float(np.sqrt(variances).mean()) if n else 0.0

    # 3. Peak statistics
    high_peaks = int(np.sum(elevations > 3000))
    very_high = int(np.sum(elevations > 5000))
    trenches = int(np.sum(elevations < -5000))

    # 4. Peak-to-valley ratio
    p2v = (np.max(elevations) - sea_level_m) / max(1.0, sea_level_m - np.min(elevations))

    logger.info(
        "  Quality metrics: bimodality=%.0f m (land %.0f / ocean %.0f), "
        "roughness=%.0f m RMS, "
        "peaks >3km=%d, >5km=%d, trenches <-5km=%d, P/V ratio=%.2f",
        bimodality,
        land_peak,
        ocean_peak,
        rms_roughness,
        high_peaks,
        very_high,
        trenches,
        p2v,
    )


# =========================================================================
# Sea level calibration ("倒水") — volume-driven binary search
# =========================================================================


def _apply_sea_level_calibration(
    mesh: CVTMesh,
    elevation: np.ndarray,
    config: TerrainPipelineConfig,
) -> np.ndarray:
    """Calibrate sea level to match the target land fraction.

    Sorts (elevation, area) pairs once, builds a cumulative area prefix sum
    from highest to lowest, then binary-searches the sorted array in O(log n)
    per iteration instead of scanning all n cells every time.

    Complexity: O(n log n)  (one sort + prefix sum, then 60 × O(log n) lookups).
    """
    n = mesh.num_cells
    areas = np.array([c.area_km2 for c in mesh.cells], dtype=np.float64)
    total_area = np.sum(areas)
    target_land_area = config.target_land_fraction * total_area

    # Sort by elevation descending, with area alongside.
    order = np.argsort(elevation)[::-1]  # highest → lowest
    elev_sorted = elevation[order]
    area_sorted = areas[order]

    # Cumulative land area: cum[i] = sum of areas for cells >= elev_sorted[i].
    cum_land = np.cumsum(area_sorted)

    # Helper: land area for a given sea-level h (cells above h).
    def _land_area(h: float) -> float:
        # elev_sorted is descending; find first cell <= h.
        idx = int(np.searchsorted(-elev_sorted, -h))  # searchsorted on negated values
        if idx == 0:
            return 0.0
        return float(cum_land[idx - 1])

    # Binary search for sea level h in [min(elev), max(elev)]
    lo = float(elev_sorted[-1])  # min elevation
    hi = float(elev_sorted[0])  # max elevation

    for _ in range(60):
        mid = (lo + hi) * 0.5
        if _land_area(mid) > target_land_area:
            lo = mid  # need higher sea level → less land
        else:
            hi = mid  # need lower sea level → more land

    sea_level = (lo + hi) * 0.5

    # Compute implied water budget
    depths = np.maximum(0.0, sea_level - elevation)  # m
    water_km3 = np.sum(depths / 1000.0 * areas)
    surface_km2 = total_area
    implied_budget_km = water_km3 / surface_km2

    land_area_final = _land_area(sea_level)
    land_pct = 100.0 * land_area_final / surface_km2
    cell_pct = 100.0 * np.sum(elevation > sea_level) / n

    logger.warning(
        "  Water calibration: target %.1f%% land → sea level %.0f m → "
        "%.1f%% land by area (%.1f%% by cells), "
        "implied water budget %.2f km (%.1f million km^3)",
        config.target_land_fraction * 100,
        sea_level,
        land_pct,
        cell_pct,
        implied_budget_km,
        water_km3 / 1e6,
    )

    return elevation - sea_level


# =========================================================================
# Shared post-processing: continental shelf + island arcs
# =========================================================================


def _apply_continental_shelf(
    mesh: CVTMesh,
    elevation: np.ndarray,
    config: TerrainPipelineConfig,
    rng: np.random.Generator,
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
    if shelf_width <= 0:
        return elevation
    sea_level = config.sea_level_offset_m

    # 1. Identify coastline cells (land with at least one ocean neighbour)
    coastline: set[int] = set()
    for i, cell in enumerate(mesh.cells):
        if elevation[i] <= sea_level:
            continue
        for nid in cell.neighbors:
            if elevation[nid] <= sea_level:
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
            if nid not in shelf_dist and elevation[nid] <= sea_level:
                shelf_dist[nid] = d + cell_km
                q.append(nid)

    # 3. Two-stage shelf profile: shallow platform → shelf break → deep ocean
    shelf_edge_depth = sea_level + rng.uniform(-5.0, -1.0)  # near-surface
    shelf_break_depth = sea_level - 200.0  # typical shelf-break depth (m)
    drop_fold = 30.0  # e-folding for the drop beyond the shelf break (km)
    shelf_cells = 0

    for cid, d_km in shelf_dist.items():
        if d_km <= 0:
            continue
        orig_z = elevation[cid]
        if d_km <= shelf_width:
            # Shelf platform: linear ramp from coast to shelf break
            t_ramp = d_km / shelf_width
            z_shelf = shelf_edge_depth + t_ramp * (shelf_break_depth - shelf_edge_depth)
        else:
            # Below shelf break: exponential drop to original ocean depth
            d_below = d_km - shelf_width
            t_drop = 1.0 - np.exp(-d_below / drop_fold)
            z_shelf = shelf_break_depth * (1.0 - t_drop) + orig_z * t_drop
        # Random ±5% variation
        noise = 1.0 + rng.uniform(-0.05, 0.05)
        elevation[cid] = z_shelf * noise
        shelf_cells += 1

    logger.info(
        "  Continental shelf: %d cells, width=%.0f km",
        shelf_cells,
        shelf_width,
    )
    return elevation


def _apply_coastal_plain(
    mesh: CVTMesh,
    elevation: np.ndarray,
    config: TerrainPipelineConfig,
    rng: np.random.Generator,
) -> np.ndarray:
    """Gentle coastal plain on the land side of coastlines.

    Low-lying land gets the full *coastal_plain_width_km* smoothing.
    High-elevation coastal mountains (e.g. Andes) get a narrower but
    non-zero transition strip — at minimum 1 cell wide — so that no
    cell sits at 5000m+ directly on the shoreline.

    The effective width shrinks with elevation above sea level, from
    *coastal_plain_width_km* at 0 m to ~1.0 cell at
    *coastal_plain_max_elevation_m* and above.  This follows Inman &
    Nordstrom's (1971) distinction between gentle coastal plains and
    steep tectonic coasts, while ensuring even the steepest coasts
    have at least a minimal lowland transition.

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
    if plain_width <= 0:
        return elevation

    sea_level = config.sea_level_offset_m

    # 1. Identify coastline cells (land with at least one ocean neighbour)
    coastline: set[int] = set()
    for i, cell in enumerate(mesh.cells):
        if elevation[i] <= sea_level:
            continue
        for nid in cell.neighbors:
            if elevation[nid] <= sea_level:
                coastline.add(i)
                break

    if not coastline:
        return elevation

    # 2. BFS inland from coastline.
    #    Extend BFS range to cover the minimum coastal strip even for
    #    high-elevation mountains (at least 1 cell inland).
    from collections import deque

    cell_km = np.sqrt(4.0 * np.pi * config.radius_km**2 / n)
    # Minimum coastal strip: at least 1 cell wide, up to 150 km absolute cap
    min_strip_km = min(150.0, max(cell_km * 1.2, plain_width * 0.2))
    max_bfs_width = max(plain_width, min_strip_km)

    inland_dist: dict[int, float] = {}
    q: deque[int] = deque()
    for cid in coastline:
        inland_dist[cid] = 0.0
        q.append(cid)

    while q:
        cid = q.popleft()
        d = inland_dist[cid]
        if d >= max_bfs_width:
            continue
        for nid in mesh.cells[cid].neighbors:
            if nid not in inland_dist and elevation[nid] > sea_level:
                inland_dist[nid] = d + cell_km
                q.append(nid)

    # 3. Variable-width coastal plain with elevation-dependent blend target.
    #    Low-lying cells blend toward ~30 m (classic coastal plain).
    #    High-elevation cells (coastal mountains) blend toward ~40% of their
    #    original elevation — creating a narrow but not-flat transition
    #    (cf. Chilean Cordillera de la Costa, ~2000–3000 m at the coast).
    max_plain_elev = config.coastal_plain_max_elevation_m  # 500 m default
    mountain_coast_ratio = 0.40  # mountain cells retain ~40% of elev at the coast

    for cid, d_km in inland_dist.items():
        if elevation[cid] <= sea_level:
            continue

        elev_above_sea = elevation[cid] - sea_level

        # Elevation factor: 1.0 at sea level → 0.0 at max_plain_elev+
        elev_factor = max(0.0, 1.0 - elev_above_sea / max_plain_elev)

        # Coast elevation target: ~30 m above sea for lowlands, 40% of
        # original for mountains
        lowland_target = sea_level + rng.uniform(10.0, 50.0)
        mountain_target = elevation[cid] * mountain_coast_ratio
        coast_target = lowland_target * elev_factor + mountain_target * (1.0 - elev_factor)

        # Effective width: shrinks from plain_width (sea level) to min_strip_km
        # (~1 cell) for cells at max_plain_elev and above.
        width_factor = max(0.0, 1.0 - elev_above_sea / max_plain_elev)
        effective_width = min_strip_km + (plain_width - min_strip_km) * width_factor

        if d_km >= effective_width:
            continue

        t = d_km / max(effective_width, 1.0)  # 0 at coast → 1 at effective limit
        blend = t * t * (3.0 - 2.0 * t)  # smoothstep
        elevation[cid] = max(
            lowland_target,
            elevation[cid] * blend + coast_target * (1.0 - blend),
        )

    logger.info(
        "  Coastal plain: %d land cells, width=%.0f km (min strip %.0f km / %.1f cells)",
        len(inland_dist),
        plain_width,
        min_strip_km,
        min_strip_km / max(cell_km, 1.0),
    )
    return elevation


def _apply_island_arcs(
    mesh: CVTMesh,
    elevation: np.ndarray,
    config: TerrainPipelineConfig,
    *,
    geography_bias: np.ndarray | None = None,
    uplift_mod: np.ndarray | None = None,
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

    damp = _anchor_uplift_damping(geography_bias, len(elevation))
    mod = uplift_mod if uplift_mod is not None else np.ones(len(elevation), dtype=np.float64)
    sea_level = config.sea_level_offset_m
    for cid, d_km in arc_affected.items():
        weight = np.exp(-((d_km - peak_dist) ** 2) / (2 * sigma * sigma))
        dz = arc_height * weight * damp[cid] * mod[cid]
        # Only uplift cells that are oceanic (don't push continental crust)
        if getattr(mesh.cells[cid], "crust_type", "") != "continental":
            elevation[cid] += dz
            arc_count += 1
        # If this lifts above sea level, mark as transitional (island)
        if elevation[cid] > sea_level:
            mesh.cells[cid].crust_type = "transitional"

    logger.info(
        "  Island arcs: %d boundary cells → %d arc cells (height=%.0f m)",
        len(arc_cells),
        arc_count,
        arc_height,
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
    """Paleo-orogeny belts, rift valleys, and intermontane basins.

    Plate interiors far from active boundaries can appear too flat.
    On Earth, ancient collision zones (Urals, Appalachians) and failed
    rift arms persist as linear features long after the plate boundary
    has migrated away.

    For each continental plate, this places 1–3 belts at random orientation
    across the interior.  Each belt meanders along a two-frequency path and
    varies in **both height and width** along strike (0.55–1.45×, correlated
    with amplitude — collision knots broad and high, transfer segments
    narrow) via 1D simplex noise — producing natural peaks, passes, and
    sunken intermontane basins (pull-apart / fault-block depressions like
    the Turpan Depression at −154 m or the Fergana Valley).  Rift valleys
    get the same meander + width variation (straight stripes read as fake).

    References
    ----------
    * Şengör, A.M.C. (1990). "Plate tectonics and orogenic research
      after 25 years: A Tethyan perspective." *Earth-Science Reviews*,
      27(1–2), 1–201.
    * Burke, K. & Dewey, J.F. (1973). "Plume-generated triple
      junctions: Key indicators in applying plate tectonics to old
      rocks." *Journal of Geology*, 81(4), 406–433.
    * Kröner, A. (1981). "Precambrian plate tectonics." Elsevier.
      — ancient orogenic belts as linear weak zones reactivated over
      multiple orogenic cycles.
    * Allen, M.B., Şengör, A.M.C., & Natal'in, B.A. (1995). "Junggar,
      Turpan and Alakol basins as Late Permian to Early Triassic
      extensional structures in a sinistral shear zone." *Journal of
      the Geological Society*, 152, 327–338. — pull-apart intermontane
      basin formation in the Tianshan range.

    Modifies *elevation* in-place.
    """
    num_orogenies = config.interior_orogeny_count
    if num_orogenies <= 0:
        return elevation

    try:
        import opensimplex

        _has_noise = True
    except ImportError:
        _has_noise = False

    # Group cells by plate and identify interiors
    plate_cells: dict[str, list[int]] = {}
    for i, cell in enumerate(mesh.cells):
        pid = cell.plate_id or ""
        if pid:
            plate_cells.setdefault(pid, []).append(i)

    total_orogeny = 0
    total_basin = 0
    total_rift = 0

    xyz_all = mesh.cell_xyz
    radius_km = config.radius_km

    for pid, cell_indices in plate_cells.items():
        # Only add orogenies to continental or mixed plates
        n_cont = sum(
            1 for i in cell_indices if getattr(mesh.cells[i], "crust_type", "") == "continental"
        )
        if n_cont < len(cell_indices) * 0.2:
            continue

        # Find interior cells (beyond the boundary influence zone)
        interior_threshold = config.boundary_influence_km * 1.2
        interior = [
            i
            for i in cell_indices
            if (dist_i := mesh.cells[i].distance_to_boundary_km) is not None
            and dist_i > interior_threshold
            and getattr(mesh.cells[i], "crust_type", "") == "continental"
        ]
        ni = len(interior)
        if ni < 10:
            continue
        interior_arr = np.array(interior, dtype=np.int64)

        # ---- Orogenic belts: count scales with interior area ----
        n_belts = config.interior_orogeny_count + max(0, ni // 800 - 1)
        n_belts = min(n_belts, 4)
        belt_seed_base = zlib.crc32(pid.encode("utf-8")) % 10000

        # Pre-extract interior positions (ni, 3)
        interior_xyz = xyz_all[interior_arr]

        for belt_idx in range(n_belts):
            if ni < 3:
                continue
            a_idx = interior[rng.integers(0, ni)]
            b_idx = interior[rng.integers(0, ni)]
            if a_idx == b_idx:
                continue

            a_pos = xyz_all[a_idx]
            b_pos = xyz_all[b_idx]

            # Great-circle arc: normal vector
            gc_normal = np.cross(a_pos, b_pos)
            gc_norm = np.linalg.norm(gc_normal)
            if gc_norm < 1e-12:
                continue
            gc_normal /= gc_norm

            # Angular length of the belt — cap at 30°
            angle_ab_raw = np.arccos(np.clip(np.dot(a_pos, b_pos), -1.0, 1.0))
            angle_ab = min(angle_ab_raw, np.radians(30))

            # Belt parameters
            base_amplitude = rng.uniform(500.0, 1500.0)
            sigma_km = rng.uniform(80.0, 200.0)
            height_var = config.interior_height_variation
            basin_chance = config.interior_basin_chance
            basin_depth_max = config.interior_basin_depth_max_m

            belt_noise_seed = (belt_seed_base * 100 + belt_idx + 1) * 1000

            # ---- Pre-filter: dot product with gc_normal is a cheap proxy
            # for angular distance from the great-circle plane.
            # sin(10°) ≈ 0.174 → only ~5% of cells pass.
            _abs_dot = np.abs(np.dot(interior_xyz, gc_normal))
            _near = _abs_dot < 0.174  # within ~10° of the belt plane
            candidates = np.where(_near)[0]
            if len(candidates) == 0:
                continue
            cand_xyz = interior_xyz[candidates]

            # ---- Vectorised projection onto great-circle plane ----
            _proj = cand_xyz - np.outer(np.dot(cand_xyz, gc_normal), gc_normal)
            _pn = np.linalg.norm(_proj, axis=1)
            _ok = _pn > 1e-12
            _proj[_ok] /= _pn[_ok, np.newaxis]

            # Along-belt position t ∈ [0, 1]
            _cos_ap = np.clip(np.dot(_proj, a_pos), -1.0, 1.0)
            _angle_ap = np.arccos(_cos_ap)
            t_vals = np.clip(_angle_ap / max(angle_ab, 1e-12), 0.0, 1.0)

            belt_count = 0
            basin_count = 0

            for _j, ci in enumerate(candidates):
                if not _ok[_j]:
                    continue
                t = float(t_vals[_j])
                p_proj = _proj[_j]
                i = interior_arr[ci]
                pos = cand_xyz[_j]

                # Along-strike wobble
                if _has_noise:
                    wobble = (
                        opensimplex.noise2(belt_noise_seed + 0.5, t * 2.5) * 0.35
                        + opensimplex.noise2(belt_noise_seed + 1.5, t * 7.0) * 0.12
                    )
                    cos_w = np.cos(wobble)
                    sin_w = np.sin(wobble)
                    p_proj = p_proj * cos_w + np.cross(gc_normal, p_proj) * sin_w

                # Along-strike modulation: height + width
                if _has_noise:
                    import warnings as _w

                    with _w.catch_warnings():
                        _w.filterwarnings("ignore", message="overflow encountered")
                        opensimplex.seed(belt_noise_seed)
                    strike_noise = opensimplex.noise2(t * 8.0, belt_noise_seed * 0.01)
                else:
                    strike_noise = rng.uniform(-1.0, 1.0)

                local_sigma = sigma_km * (0.55 + 0.9 * (strike_noise + 1.0) / 2.0)

                # Angular distance from cell to the (wobbled) belt line
                dot_to_arc = np.clip(np.dot(pos, p_proj), -1.0, 1.0)
                dist_km = np.arccos(dot_to_arc) * radius_km

                if dist_km >= 2.0 * local_sigma:
                    continue

                # Determine segment type and amplitude
                if strike_noise < -(1.0 - basin_chance * 2):
                    basin_depth = basin_depth_max * abs(strike_noise)
                    local_amp = -basin_depth
                    landform_type = "basin"
                    basin_count += 1
                else:
                    amp_mult = 0.3 + height_var * (strike_noise + 1.0) / 2.0
                    local_amp = base_amplitude * amp_mult
                    landform_type = "orogeny"
                    belt_count += 1

                weight = np.exp(-(dist_km * dist_km) / (2 * local_sigma * local_sigma))
                jitter = rng.uniform(-0.10, 0.10)
                elevation[i] += local_amp * weight * (1.0 + jitter)

                if not mesh.cells[i].landform:
                    mesh.cells[i].landform = landform_type

            total_orogeny += belt_count
            total_basin += basin_count

        # ---- Rift valleys (1 per plate, 30% chance) ----
        if rng.random() < 0.3 and ni > 20:
            a_idx = interior[rng.integers(0, ni)]
            b_idx = interior[rng.integers(0, ni)]
            if a_idx != b_idx:
                a_pos = xyz_all[a_idx]
                b_pos = xyz_all[b_idx]
                gc_normal = np.cross(a_pos, b_pos)
                gc_norm = np.linalg.norm(gc_normal)
                if gc_norm > 1e-12:
                    gc_normal /= gc_norm
                    angle_ab = np.arccos(np.clip(np.dot(a_pos, b_pos), -1.0, 1.0))
                    rift_sigma = rng.uniform(40.0, 100.0)
                    rift_depth_base = rng.uniform(300.0, 800.0)
                    rift_noise_seed = (belt_seed_base * 100 + 99) * 1000

                    # Pre-filter (same principle as orogeny belts)
                    _abs_dot = np.abs(np.dot(interior_xyz, gc_normal))
                    _near = _abs_dot < 0.174
                    candidates = np.where(_near)[0]
                    if len(candidates) == 0:
                        continue
                    cand_xyz = interior_xyz[candidates]

                    _proj = cand_xyz - np.outer(np.dot(cand_xyz, gc_normal), gc_normal)
                    _pn = np.linalg.norm(_proj, axis=1)
                    _ok = _pn > 1e-12
                    _proj[_ok] /= _pn[_ok, np.newaxis]

                    _cos_ap = np.clip(np.dot(_proj, a_pos), -1.0, 1.0)
                    _angle_ap = np.arccos(_cos_ap)
                    t_vals = np.clip(_angle_ap / max(angle_ab, 1e-12), 0.0, 1.0)

                    for _j, ci in enumerate(candidates):
                        if not _ok[_j]:
                            continue
                        t = float(t_vals[_j])
                        p_proj = _proj[_j]
                        i = interior_arr[ci]
                        pos = cand_xyz[_j]

                        # Meander
                        if _has_noise:
                            wobble = (
                                opensimplex.noise2(rift_noise_seed + 0.5, t * 2.5) * 0.35
                                + opensimplex.noise2(rift_noise_seed + 1.5, t * 7.0) * 0.12
                            )
                            cos_w = np.cos(wobble)
                            sin_w = np.sin(wobble)
                            p_proj = p_proj * cos_w + np.cross(gc_normal, p_proj) * sin_w

                        # Along-strike modulation
                        if _has_noise:
                            import warnings as _w

                            with _w.catch_warnings():
                                _w.filterwarnings("ignore", message="overflow encountered")
                                opensimplex.seed(rift_noise_seed)
                            strike_noise = opensimplex.noise2(t * 6.0, rift_noise_seed * 0.01)
                        else:
                            strike_noise = rng.uniform(-1.0, 1.0)
                        depth_mult = 0.4 + 0.6 * (strike_noise + 1.0) / 2.0
                        local_depth = rift_depth_base * depth_mult
                        local_rift_sigma = rift_sigma * (0.55 + 0.9 * (strike_noise + 1.0) / 2.0)

                        dot_to_arc = np.clip(np.dot(pos, p_proj), -1.0, 1.0)
                        dist_km = np.arccos(dot_to_arc) * radius_km

                        if dist_km >= 2.0 * local_rift_sigma:
                            continue

                        weight = np.exp(
                            -(dist_km * dist_km) / (2 * local_rift_sigma * local_rift_sigma)
                        )
                        jitter = rng.uniform(-0.10, 0.10)
                        elevation[i] -= local_depth * weight * (1.0 + jitter)
                        if not mesh.cells[i].landform:
                            mesh.cells[i].landform = "rift"
                        total_rift += 1

    if total_orogeny > 0 or total_basin > 0 or total_rift > 0:
        logger.info(
            "  Interior landforms: %d orogeny, %d basin, %d rift cells "
            "(%d belts/plate, basin chance %.0f%%)",
            total_orogeny,
            total_basin,
            total_rift,
            num_orogenies,
            config.interior_basin_chance * 100,
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
        "Terrain synthesis complete: elev range [%.0f, %.0f] m, %.1f%% land, %.1f%% ocean",
        np.min(elevation),
        np.max(elevation),
        100 * above / n,
        100 * (n - above) / n,
    )
