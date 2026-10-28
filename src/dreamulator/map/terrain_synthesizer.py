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
from typing import TYPE_CHECKING

import numpy as np

from .distance import geodesic_bfs, geodesic_bfs_with_source
from .geography import build_elevation_pins, build_land_bias_field, feature_noise_seed
from .pipeline_types import TerrainPipelineConfig

if TYPE_CHECKING:
    from .geography import GeographyFeature
    from .models import CVTMesh, TectonicPlate
    from .orogen_contract import OrogenContract

logger = logging.getLogger(__name__)

# Subduction-trench relief below the abyssal floor.  Earth's trenches reach
# ~−11 km (Mariana) while the abyssal plain sits near −4 km, so a ~7 km relief
# on the subducting side reproduces trench depths.  Applied only to oceanic
# crust on the oceanward side of convergent boundaries.  Gaussian (legacy) profile
# path only; the asymmetric path uses the flexure of the subducting plate.
_TRENCH_RELIEF_M = 7000.0

# Earth-envelope floors for deep-ocean cells (2026-09-30, nacrea #95271:
# a −10.5 km continental-crust cell directly on the coast).  Calibrated on the
# real-Earth CVT mesh (ETOPO1 @ ~51 km cells): continental-crust seafloor is
# never deeper than −5.3 km (observed min −5312 m; isostasy keeps ~35-km
# continental crust floating — abyssal depths belong to oceanic lithosphere),
# and coast-adjacent ocean cells (first ring) never deeper than −6.0 km
# (observed min −5979 m — Cayman/Hellenic-type trench-adjacent coasts; trench
# axes sit ≥1 cell offshore).  Closure class: observation-fitted, calibration
# domain = Earth's tectonic regime.
_CONTINENTAL_CRUST_FLOOR_M = -5300.0
_COAST_RING_FLOOR_M = -6000.0

# Continental slope seaward of the shelf break: mean gradient about 4° (the
# commonly quoted average of Earth's continental slopes, e.g. Brothers et al.
# 2018).  Closure class: observation-fitted, calibration domain = Earth's
# margins.
_CONTINENTAL_SLOPE_M_PER_KM = 1000.0 * float(np.tan(np.radians(4.0)))

# Drowned continental margin by margin type: the thinned continental crust that
# the two-class crust partition (continental crust ≈ land) leaves out.  Global
# mean shelf widths from the GSFM seafloor map: passive margins 88 km, active
# margins 31 km (Harris et al. 2014, Marine Geology 352).  A coast is active
# when a convergent or transform plate boundary lies within the boundary
# influence width.  Closure class: observation-fitted, calibration domain =
# Earth's margins (to be replaced by margin age once the history contract
# provides it).
_PASSIVE_MARGIN_SHELF_KM = 88.0
_ACTIVE_MARGIN_SHELF_KM = 31.0

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
    n = len(mesh.cells)

    # ---- Multi-source geodesic BFS to divergent and convergent boundaries ----
    # Restricted to oceanic crust (ocean-floor age only).
    seeds_div: list[int] = []
    seeds_conv: list[int] = []
    for i, cell in enumerate(mesh.cells):
        if cell.crust_type != "oceanic":
            continue
        if cell.boundary_type == "divergent":
            seeds_div.append(i)
        elif cell.boundary_type == "convergent":
            seeds_conv.append(i)

    def oceanic(cid: int) -> bool:
        return mesh.cells[cid].crust_type == "oceanic"

    d_div = np.full(n, -1.0)
    d_conv = np.full(n, -1.0)
    for cid, d in geodesic_bfs(mesh, seeds_div, config.radius_km, can_expand=oceanic).items():
        d_div[cid] = d
    for cid, d in geodesic_bfs(mesh, seeds_conv, config.radius_km, can_expand=oceanic).items():
        d_conv[cid] = d

    # ---- Interplate ocean cells only ----
    # Cells that can reach both a divergent AND a convergent boundary
    # are "conveyor-belt" ocean floor with a meaningful age.
    # Cells that can only reach one type (e.g. a plate with no convergent
    # boundary) fall through to NaN and keep the uniform base.
    valid = (d_div >= 0) & (d_conv >= 0)
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
    # unreached cells carry −1 distances; they are masked out below, keep their age finite
    age_myr = config.ocean_max_age_myr * np.clip(fraction, 0.0, 1.0)

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


#: Overlay kernel above this level is the overlay's footprint (the calibration mask
#: convention, ≈ 86% of the nominal radius).
_MICROCONTINENT_OVERLAY_THRESHOLD = 0.05
#: Upper bound of a positive overlay's outline roughness (its ``noise_amplitude``): the
#: footprint radius is scaled by 1 ± roughness with a patch-scale fBm, so the fragment
#: edge — the continental/oceanic step, hence the shelf break and the outer coasts — is
#: irregular instead of the nominal ellipse.  Kept below 1 so the scale stays positive
#: (an unbounded amplitude makes far-field noise outliers claim one-cell dots).
_OVERLAY_EDGE_WARP_MAX = 0.9
#: Base wavenumbers (per unit sphere, ×1/radius in radians) of the patch-scale fBm for the
#: fragment outline and for the island cut: outline bumps of about a quarter radius and
#: islands of about a third (several cells on the 54 km grid; an eighth gave one-cell
#: dots).  The world-scale feature fBm (wavelength ~25°) is nearly constant across a
#: 5–10° patch and gave an ellipse with one blob island.  Numerical convention.
_OVERLAY_EDGE_WAVENUMBER = 4.0
_OVERLAY_ISLAND_WAVENUMBER = 3.0
#: Octaves of the island-cut fBm: one octave gives rounded island bodies; more add small
#: islets and inlets that read as speckle on the 54 km grid.  Numerical convention.
_OVERLAY_ISLAND_OCTAVES = 1


def _patch_noise(
    mesh: CVTMesh, f: GeographyFeature, seed: int, wavenumber: float, octaves: int = 4
) -> np.ndarray:
    """fBm in [-1, 1] whose base wavelength scales with the overlay's radius."""
    from .noise_kernels import fbm_on_points

    xyz = mesh.cell_xyz / np.linalg.norm(mesh.cell_xyz, axis=1, keepdims=True)
    base = wavenumber / np.radians(f.size_deg)
    return np.asarray(
        fbm_on_points(xyz[:, 0], xyz[:, 1], xyz[:, 2], seed, octaves=octaves, base_freq=base),
        dtype=np.float64,
    )


def _overlay_claims(
    mesh: CVTMesh, config: TerrainPipelineConfig
) -> list[tuple[GeographyFeature, np.ndarray]]:
    """Crustal-fragment footprint of every positive overlay: ``[(feature, mask)]``.

    A positive overlay is a continental crust fragment (author ruling 2026-10-21).  Its
    footprint is the overlay kernel above ``_MICROCONTINENT_OVERLAY_THRESHOLD`` with the
    radius roughened by the feature's ``noise_amplitude`` (outline roughness, capped at
    ``_OVERLAY_EDGE_WARP_MAX``) through a patch-scale fBm, not the smooth ellipse.
    """
    from .geography import _feature_kernel

    spec = config.geography
    if spec is None or not spec.overlays:
        return []
    xyz = mesh.cell_xyz / np.linalg.norm(mesh.cell_xyz, axis=1, keepdims=True)
    out = []
    for k, f in enumerate(spec.overlays):
        if f.strength <= 0.0:
            continue
        seed = feature_noise_seed(int(config.seed)) + 7919 * k
        noise = _patch_noise(mesh, f, seed, _OVERLAY_EDGE_WAVENUMBER)
        roughness = float(np.clip(f.noise_amplitude, 0.0, _OVERLAY_EDGE_WARP_MAX))
        warped = f.model_copy(update={"noise_amplitude": roughness})
        kern = _feature_kernel(xyz[:, 0], xyz[:, 1], xyz[:, 2], warped, noise)
        out.append((f, kern > _MICROCONTINENT_OVERLAY_THRESHOLD))
    return out


def _restamp_overlay_microcontinents(mesh: CVTMesh, config: TerrainPipelineConfig) -> int:
    """Terrain-stage crust restamp for positive geography overlays (crust fragments).

    Overlays are invisible to the plate stage, so a positive overlay over oceanic crust
    would drown under the ocean age–depth floor.  A positive overlay claims continental
    crust — a Zealandia-style crustal fragment — over its roughened footprint
    (``_overlay_claims``), restamped before the bimodal base: those cells keep the
    continental base, skip age–depth and receive the procedural texture; the islands
    inside are cut on the final surface (``_apply_overlay_archipelago_texture``).

    Negative overlays do NOT restamp: a carved sea over continental crust is an
    epicontinental sea (continental crust under water).  Where overlays and authored
    features disagree, overlays win (the restamp runs after ``_relabel_leaked_crust``).
    Epistemic class: approximate derivation (real fragments are rifted, thinned crust).
    """
    n = 0
    for _f, claim in _overlay_claims(mesh, config):
        for i in np.flatnonzero(claim):
            if mesh.cells[i].crust_type != "continental":
                mesh.cells[i].crust_type = "continental"
                n += 1
    if n:
        logger.info("  Overlay microcontinents: %d cells restamped continental", n)
    return n


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


def apply_elevation_pin_values(
    elevation: np.ndarray,
    pins: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray],
    *,
    crosses_sea_level: bool,
) -> np.ndarray:
    """Apply one authored pin pass to a surface in the calibrated sea datum."""
    weight, target, strength, exponent = pins
    crosses = crosses_sea_level
    # Decisive core, soft edge: the kernel rarely hits exactly 1 on a discrete
    # mesh, so saturate the blend factor at w ≥ 0.5 — the author's target is
    # authoritative at the feature core while the rim still fades smoothly.
    factor = strength * np.asarray(np.clip(2.0 * weight, 0.0, 1.0))
    if not crosses:
        # Side of the calibrated datum (0 m), the frame the targets are
        # written in; a sea_level_offset_m experiment then moves the water
        # against the pinned floor as before.
        same_side = (target > 0.0) == (elevation > 0.0)
        factor = np.where(same_side, factor, 0.0)
    # Deviation exponentiation: cells further from target get proportionally
    # stronger pull (exponent > 1 = 削峰强力, 平原温和; exponent = 1 = 线性).
    # Normalised to a reference scale so exponent=1.0 is byte-identical
    # to the linear formula.
    deviation = target - elevation
    ref = 1000.0  # metres — at this deviation the pull equals linear
    normalised = deviation / ref
    mag = np.power(np.abs(normalised), exponent)
    # 削峰 (exponent > 1) is meant to *depress* cells above the target.  Applied
    # symmetrically it also over-raises cells far below the target — a deep ocean
    # trench on the feature's soft edge gets pulled up into a mountain (§3.9).
    # Keep the downward (above-target) amplification, but make the upward
    # (below-target) pull linear so the ocean floor stays in the ocean.
    mag = np.where((exponent > 1.0) & (normalised >= 0.0), np.abs(normalised), mag)
    # The exponent < 1 branch amplifies small deviations (|n|^e > |n|), so
    # factor·|n|^e can exceed the deviation itself and overshoot the target.
    # Cap the applied pull at the full deviation: the pin may reach its
    # target but never pass it, so a same-side pin cannot cross the surface.
    applied = np.minimum(factor * mag, np.abs(normalised))
    return np.asarray(elevation + np.sign(normalised) * applied * ref)


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

    Two passes.  Pins with ``pin_crosses_sea_level = False`` (the default:
    mean-elevation pins) only act on cells on their own side of the
    calibrated datum — a positive target on land, a negative one on ocean — so
    they adjust heights without moving the coastline; a convex pull toward a
    target on the same side cannot cross it.  Pins marked as crossing (land
    bridges, cut straits) then act everywhere.

    No-op (returns *elevation* unchanged) when no feature declares a target.
    """
    spec = config.geography
    if spec is None:
        return elevation
    n_pinned = 0
    for crosses in (False, True):
        pins = build_elevation_pins(mesh, spec, crosses_sea_level=crosses)
        if pins is None:
            continue
        weight, target, strength, exponent = pins
        elevation = apply_elevation_pin_values(elevation, pins, crosses_sea_level=crosses)
        factor = strength * np.asarray(np.clip(2.0 * weight, 0.0, 1.0))
        if not crosses:
            factor = np.where((target > 0.0) == (elevation > 0.0), factor, 0.0)
        n_pinned += int(np.count_nonzero(factor > 0.0))
    logger.info("  Geography pins: %d cells pulled toward authored targets", n_pinned)
    return elevation


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
    orogen_contract: OrogenContract | None = None,
    source_fields: dict[str, np.ndarray] | None = None,
) -> None:
    """Synthesize terrain elevation (dispatches to configured algorithm).

    Args:
        mesh: The CVT mesh (modified in-place).
        plates: List of tectonic plates.
        config: Pipeline configuration.
        orogen_contract: History contract, orogen part (built here when not given).

    Raises:
        ValueError: Unknown terrain algorithm.
    """
    algo = config.terrain_algorithm
    if source_fields is not None:
        if algo != "cortial2019_asymmetric":
            raise ValueError("terrain source capture requires the asymmetric source pipeline")
        source_fields.clear()
    if algo not in _TERRAIN_ALGORITHMS:
        raise ValueError(
            f"Unknown terrain algorithm '{algo}'. Available: {sorted(_TERRAIN_ALGORITHMS.keys())}"
        )
    # Authored land-bias field (pure function of (mesh, spec[, raster]),
    # identical to the one used for crust anchoring) so convergent uplift can
    # be damped inside authored ocean basins / rift seas.
    spec = config.geography
    geography_bias = (
        build_land_bias_field(
            mesh, spec, raster_bias=raster_bias, noise_seed=feature_noise_seed(int(config.seed))
        )
        if spec is not None and (spec.features or spec.overlays or raster_bias is not None)
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
        if orogen_contract is None:
            from .orogen_contract import build_orogen_contract

            orogen_contract = build_orogen_contract(
                mesh,
                plates,
                config.radius_km,
                config.collision_overrides,
                subduction_polarities=getattr(config, "subduction_polarities", []),
            )
        _synthesize_asymmetric(
            mesh,
            plates,
            config,
            geography_bias=geography_bias,
            uplift_mod=uplift_mod,
            orogen_contract=orogen_contract,
            source_fields=source_fields,
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
    _restamp_overlay_microcontinents(mesh, config)
    base = np.full(n, config.oceanic_elevation_m, dtype=np.float64)
    for i, cell in enumerate(mesh.cells):
        if cell.crust_type == "continental":
            base[i] = config.continental_elevation_m
    _apply_base_override(base, geography_bias, config)

    # 1c. Ocean floor age-depth subsidence (replaces uniform oceanic base)
    if config.ocean_age_depth_enabled:
        logger.info(
            "  Step 1c/5: Ocean age-depth (ridge=%.0fm, max=%.0fm)",
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
        elevation = _apply_sea_level_calibration(
            mesh, elevation, config, overlay_mask=_overlay_calibration_mask(mesh, config)
        )
        for i, cell in enumerate(mesh.cells):
            cell.elevation = float(elevation[i])

    # Post-processing (shared with asymmetric: shelf/plain must run last)
    sea_level = config.sea_level_offset_m
    elevation, clamped = _apply_interior_lowlands(mesh, elevation, config)
    elevation = _apply_deposition_fill(mesh, elevation, config, clamped)
    elevation = _apply_island_arcs(
        mesh, elevation, config, geography_bias=geography_bias, uplift_mod=uplift_mod
    )
    elevation = _apply_continental_shelf(mesh, elevation, config, rng)
    elevation = _apply_coastal_plain(mesh, elevation, config, rng)
    elevation = _clamp_deep_ocean_floors(mesh, elevation, config)
    elevation = _apply_overlay_archipelago_texture(mesh, config, elevation)

    # Author elevation pins: the author's final word on elevation, applied
    # after every procedural stage so shelf/arcs cannot overwrite a pinned
    # strait depth or isthmus height.
    elevation = _apply_geography_pins(mesh, elevation, config)

    # Isostasy: compress only the tail that exceeds physical limits.
    # Unlike global scaling (which compresses the entire distribution),
    # this leaves the bulk of cells untouched and only pulls back extremes.
    # Excess above/below the limit is folded back with exponential decay,
    # so peaks stay higher than foothills while the tail approaches the
    # limit asymptotically — it is NOT a hard clip, so the very highest
    # peaks can still sit a little above ``land_limit`` (and the deepest
    # trenches a little below ``-ocean_limit``) after compression.
    # Limits: h_max ∝ 1/g  (see isostasy_elevation_limits.md).
    if config.isostasy_enabled:
        land_limit = config.isostasy_max_continental_elevation_m
        ocean_limit = config.isostasy_max_ocean_depth_m

        # Land: compress cells above limit
        over = elevation > land_limit
        if np.any(over):
            excess = elevation[over] - land_limit
            elevation[over] = land_limit + excess * np.exp(-7.5 * excess / land_limit)

        # Ocean: compress cells below (deeper than) limit
        over_deep = elevation < -ocean_limit
        if np.any(over_deep):
            excess = -ocean_limit - elevation[over_deep]  # positive excess depth
            elevation[over_deep] = -ocean_limit - excess * np.exp(-7.5 * excess / ocean_limit)

    _smooth_land_discontinuities(mesh, elevation, iterations=3, blend=0.3)

    # Write post-processed elevation back to cells
    for i, cell in enumerate(mesh.cells):
        cell.elevation = float(elevation[i])

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
    orogen_contract: OrogenContract,
    source_fields: dict[str, np.ndarray] | None = None,
) -> None:
    """Cortial 2019 — asymmetric mountain profiles + hotspots + landforms.

    Continental convergent relief comes from the history contract
    (``orogen_profile.orogen_relief``, orogen_topography.md §2–4); the boundary profiles
    keep only ocean–ocean arcs, rifts and transforms; trenches are the flexure of the
    subducting plate (``trench_flexure.trench_relief``, §3.4).
    """
    logger.info("Synthesizing terrain (asymmetric)")
    n = mesh.num_cells
    rng = np.random.default_rng(config.seed + 100)

    from .terrain_source_export import capture_source_field

    if source_fields is not None:
        capture_source_field(
            source_fields,
            "xyz",
            mesh.cell_xyz / np.linalg.norm(mesh.cell_xyz, axis=1, keepdims=True),
        )
        capture_source_field(
            source_fields, "plate_id", np.array([c.plate_id or "" for c in mesh.cells])
        )
        capture_source_field(
            source_fields, "cell_area_km2", np.array([c.area_km2 for c in mesh.cells])
        )

    # 1. Bimodal base + per-plate offsets (same as gaussian)
    _restamp_overlay_microcontinents(mesh, config)
    base = np.full(n, config.oceanic_elevation_m, dtype=np.float64)
    for i, cell in enumerate(mesh.cells):
        if cell.crust_type == "continental":
            base[i] = config.continental_elevation_m
    _apply_base_override(base, geography_bias, config)

    age_valid = np.zeros(n, dtype=bool)
    if config.ocean_age_depth_enabled:
        age_depth = _compute_ocean_age_depth(mesh, config)
        ocean_mask = np.array([c.crust_type == "oceanic" for c in mesh.cells])
        age_valid = ocean_mask & np.isfinite(age_depth)
        base[age_valid] = age_depth[age_valid]

    logger.info("  Step 1/6: Base elevation + plate offsets")
    _relabel_leaked_crust(mesh, geography_bias)
    if orogen_contract.polarity_stage != "terrain-crust":
        from .orogen_contract import resolve_contract_polarities

        resolve_contract_polarities(
            mesh, plates, orogen_contract, config.radius_km, stage="terrain-crust"
        )
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
            elif not age_valid[i]:  # seafloor of known age: depth is set by the age
                base[i] += off
    # dynamic topography of the mantle flow, degree-2 about the poloidal axis
    # (knowledge/geology/terrain_synthesis.md §4.3.1)
    from .dynamic_topography import dynamic_topography
    from .plate_generator import coherent_poloidal_axis

    base += dynamic_topography(mesh, coherent_poloidal_axis(config))

    # 2. Asymmetric boundary effects
    logger.info(
        "  Step 2/6: Asymmetric boundary profiles (asymmetry=%.2f)", config.mountain_asymmetry
    )
    from .trench_flexure import trench_relief

    trench, _axis_offset, subducting = trench_relief(
        mesh, plates, orogen_contract, config.radius_km, config.gravity_m_s2
    )
    from .trench_flexure import forearc

    forearc_surface, forearc_km = forearc(mesh, orogen_contract, base + trench, config.radius_km)
    boundary_delta, transform_boost = _asymmetric_boundary_effects(
        mesh,
        config,
        geography_bias=geography_bias,
        uplift_mod=uplift_mod,
        plate_offsets=plate_offsets,
        cont_frac=_neighbor_continental_fraction(mesh),
        continental_orogens_from_contract=True,
        subducting=subducting,
    )
    from .orogen_profile import orogen_relief

    contributions: dict[str, np.ndarray] | None = {} if source_fields is not None else None
    orogen, orogen_cap = orogen_relief(
        mesh,
        orogen_contract,
        config.radius_km,
        config.gravity_m_s2,
        config.continental_elevation_m,
        forearc_km=forearc_km,
        segment_contributions=contributions,
    )
    if contributions is not None:
        for sid, layer in contributions.items():
            capture_source_field(source_fields, "orogen.segment." + sid, layer)
    capture_source_field(source_fields, "active_orogen_m", orogen)
    capture_source_field(source_fields, "base_m", base)
    capture_source_field(source_fields, "boundary_m", boundary_delta)
    capture_source_field(source_fields, "trench_m", trench)
    capture_source_field(source_fields, "trench_axis_offset_m", _axis_offset)
    capture_source_field(source_fields, "subducting_mask", subducting)
    capture_source_field(source_fields, "forearc_surface_m", forearc_surface)
    if source_fields is not None:
        capture_source_field(
            source_fields,
            "land_crust_mask",
            np.array([c.crust_type != "oceanic" for c in mesh.cells]),
        )
    # old orogens along the history's paleo-sutures (terrain_synthesis.md §4.3): crest
    # decays from the world's typical collision crest (median over its collision segments)
    # towards the residual
    from .orogen_profile import collision_cap_m, collision_crests_m
    from .paleo_orogens import paleo_orogen_relief

    crests = collision_crests_m(
        orogen_contract, config.gravity_m_s2, config.continental_elevation_m
    )
    active_crest = (
        float(np.median(crests))
        if crests
        else collision_cap_m(config.gravity_m_s2) - config.continental_elevation_m
    )
    paleo = paleo_orogen_relief(mesh, config.paleo_sutures, active_crest, config.radius_km)
    capture_source_field(source_fields, "paleo_orogen_m", paleo)
    logger.info(
        "  Old orogens: %d sutures, active crest %.0f m, %d cells",
        len(config.paleo_sutures),
        active_crest,
        int((paleo > 0).sum()),
    )
    for k in np.flatnonzero((paleo > orogen) & (paleo > 0.0)).tolist():
        if not mesh.cells[k].landform:
            mesh.cells[k].landform = "orogeny"
    orogen = np.maximum(orogen, paleo)
    capture_source_field(source_fields, "combined_orogen_m", orogen)

    # 3. Sub-grid island catalogue: hotspot and arc volcanoes enter as cell means of their
    # volume; the intrusive arc magma thickens the arc crust (island-catalog.md §3.2)
    from .island_catalog import (
        arc_platform,
        build_island_catalog,
        remember_synthesis_catalog,
        volcano_cell_mean,
    )

    logger.info("  Step 3/6: Island catalogue (hotspot chains, island arcs)")
    catalog = build_island_catalog(mesh, plates, config, orogen_contract=orogen_contract)
    remember_synthesis_catalog(catalog)
    volcano_delta = volcano_cell_mean(mesh, catalog, config.radius_km)
    arc_delta = arc_platform(mesh, plates, config, orogen_contract=orogen_contract)
    hotspot_delta = volcano_delta + arc_delta
    capture_source_field(source_fields, "volcano_cell_mean_m", volcano_delta)
    capture_source_field(source_fields, "arc_platform_m", arc_delta)

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
    strike = _compute_boundary_strike(mesh, config) if config.noise_anisotropy > 0 else None
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
        + orogen
        + trench
        + hotspot_delta
        + regional_fbm * regional_amp
        + fbm * noise_amp * interior_factor * transform_boost
    )
    capture_source_field(source_fields, "combined_elevation_m", elevation)

    for i, cell in enumerate(mesh.cells):
        cell.elevation = float(elevation[i])

    # Sea level auto-calibration ("倒水"): a uniform shift, which the forearc surface
    # (computed on the pre-calibration datum) follows
    datum_shift = 0.0
    if config.sea_level_auto:
        _before = float(elevation[0])
        elevation = _apply_sea_level_calibration(
            mesh, elevation, config, overlay_mask=_overlay_calibration_mask(mesh, config)
        )
        datum_shift = float(elevation[0]) - _before
        for i, cell in enumerate(mesh.cells):
            cell.elevation = float(elevation[i])

    capture_source_field(source_fields, "after_initial_sea_level_m", elevation)

    # Post-processing (order matters: arcs/orogeny add elevation,
    # shelf/plain must run last to not be overwritten)
    sea_level = config.sea_level_offset_m
    # the collapse limit bounds the final mean surface of orogen cells (texture noise
    # must not lift a plateau above its cap; orogen_topography.md §3)
    from .orogen_profile import apply_orogen_cap

    capture_source_field(source_fields, "orogen_cap_m", orogen_cap)
    elevation = apply_orogen_cap(elevation, orogen_cap, sea_level)
    capture_source_field(source_fields, "after_orogen_cap_m", elevation)
    elevation, clamped = _apply_interior_lowlands(mesh, elevation, config)
    capture_source_field(source_fields, "after_interior_lowlands_m", elevation)
    capture_source_field(source_fields, "interior_lowland_clamped_mask", clamped)
    elevation = _apply_deposition_fill(mesh, elevation, config, clamped)
    capture_source_field(source_fields, "after_deposition_fill_m", elevation)
    if not config.island_catalog_enabled:
        elevation = _apply_island_arcs(
            mesh,
            elevation,
            config,
            geography_bias=geography_bias,
            uplift_mod=uplift_mod,
            subducting=subducting,
        )
    shelf_sources = {"source_fields": source_fields} if source_fields is not None else {}
    elevation = _apply_continental_shelf(
        mesh, elevation, config, rng, active_flexure=subducting, **shelf_sources
    )
    capture_source_field(source_fields, "before_coastal_plain_m", elevation)
    elevation = _apply_coastal_plain(mesh, elevation, config, rng, source_fields=source_fields)
    capture_source_field(source_fields, "after_coastal_plain_m", elevation)
    # forearc wedge of ocean–continent margins bounds the surface between trench and coast
    # (orogen_topography.md §6); after the shelf, so the wedge rather than a passive-margin
    # shelf sets it.  The land it drowns is made up by the final sea-level trim below.
    elevation = np.minimum(elevation, forearc_surface + datum_shift + sea_level)
    if source_fields is not None:
        capture_source_field(
            source_fields, "final_forearc_surface_m", forearc_surface + datum_shift + sea_level
        )
    capture_source_field(source_fields, "after_forearc_m", elevation)
    elevation = _clamp_deep_ocean_floors(mesh, elevation, config)
    capture_source_field(source_fields, "after_deep_ocean_clamp_m", elevation)

    # Final sea-level trim (technical debt 47): the forearc and the other post-processing
    # changed the land area after the solve above.  Solving again on the final surface,
    # whose submerged continental crust is now shelf, meets the author's land fraction
    # with a sea-level change of tens of metres; the shelf is not rebuilt (it would follow
    # the new sea level and the solve would chase it down the pre-shelf slopes).
    if config.sea_level_auto:
        elevation = _apply_sea_level_calibration(
            mesh,
            elevation,
            config,
            overlay_mask=_overlay_calibration_mask(mesh, config),
            label="Final sea-level trim",
        )
    capture_source_field(source_fields, "after_final_sea_level_m", elevation)
    # islands of positive overlays, cut from the actual sea surface
    elevation = _apply_overlay_archipelago_texture(mesh, config, elevation)
    capture_source_field(source_fields, "after_overlay_archipelago_m", elevation)

    # Author elevation pins (final word; see _apply_geography_pins)
    elevation = _apply_geography_pins(mesh, elevation, config)
    capture_source_field(source_fields, "final_elevation_m", elevation)

    # Cell-mean semantics (orogen_topography.md §1): no asymptotic compression — the
    # land limit is a peak height (orogen means are capped by the profile) and the ocean
    # limit a trench-axis depth (trench means come from the flexure profile).

    # Write post-processed elevation back to cells
    for i, cell in enumerate(mesh.cells):
        cell.elevation = float(elevation[i])

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

    Coastline cells (land with an ocean neighbour) are *not* smoothed: they
    carry the coastal-plain transition laid down by *_apply_coastal_plain*
    (§3.9).  Blending them toward their (mountainous) inland neighbours would
    lift the low coastal strip straight back to the inland relief — the
    "Andes drop straight into the sea" artefact.  They still serve as
    neighbours for inland cells, so the interior relaxes toward the coast
    without the coast being lifted.
    """
    n = len(mesh.cells)
    # Precompute per-cell neighbour land-mean for vectorised smoothing
    nbr_sum = np.empty(n, dtype=np.float64)
    nbr_count = np.empty(n, dtype=np.int32)
    land_mask = elevation > 0

    # Coastline cells: land with at least one ocean (non-land) neighbour.
    coastline_mask = np.zeros(n, dtype=bool)
    for i, cell in enumerate(mesh.cells):
        if not land_mask[i]:
            continue
        for nid in cell.neighbors:
            if 0 <= nid < n and not land_mask[nid]:
                coastline_mask[i] = True
                break
    update_mask = land_mask & ~coastline_mask

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

        valid = (nbr_count > 0) & update_mask
        nbr_mean = np.divide(nbr_sum, nbr_count, out=np.full_like(nbr_sum, elevation), where=valid)
        # Blend:  (1 - blend) * self  +  blend * neighbours
        elevation[valid] = (1.0 - blend) * elevation[valid] + blend * nbr_mean[valid]


def _divergent_side_sign(mesh: CVTMesh) -> np.ndarray:
    """Signed side (±1) of each cell relative to its nearest divergent boundary.

    A boundary separates two plates; a cell is +1 on the canonically-smaller
    plate's side and -1 on the larger plate's side (matching boundary_detector's
    ``pa < pb`` ordering).  This is the geometric ingredient for half-graben
    asymmetry: footwall (uplifted) vs hanging-wall (down-dropped) side.  0 =
    cell not near a divergent boundary.
    """
    from collections import deque

    n = mesh.num_cells
    side = np.zeros(n, dtype=np.float64)
    boundary_side: dict[int, float] = {}
    source: dict[int, int] = {}
    q: deque[int] = deque()

    for i, cell in enumerate(mesh.cells):
        if cell.boundary_type != "divergent" or cell.plate_id is None:
            continue
        other: str | None = None
        for nid in cell.neighbors:
            npid = mesh.cells[nid].plate_id
            if npid is not None and npid != cell.plate_id:
                other = npid
                break
        if other is None:
            continue
        boundary_side[i] = 1.0 if cell.plate_id < other else -1.0
        source[i] = i
        q.append(i)

    # BFS: each cell inherits the side of its nearest divergent boundary cell.
    while q:
        cid = q.popleft()
        src = source[cid]
        for nid in mesh.cells[cid].neighbors:
            if nid in source:
                continue
            source[nid] = src
            q.append(nid)

    for cid, src in source.items():
        side[cid] = boundary_side[src]
    return side


def _asymmetric_boundary_effects(
    mesh: CVTMesh,
    config: TerrainPipelineConfig,
    *,
    geography_bias: np.ndarray | None = None,
    uplift_mod: np.ndarray | None = None,
    plate_offsets: dict[str, float] | None = None,
    cont_frac: np.ndarray | None = None,
    continental_orogens_from_contract: bool = False,
    subducting: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Boundary-type-specific elevation profiles.

    With ``continental_orogens_from_contract`` the convergent uplift of continental
    cells (collision and the overriding side of Andean margins) and the intermontane
    basins are left to ``orogen_profile`` (history contract) and the trenches to
    ``trench_flexure``; ocean–ocean arcs stay here, kept off the ``subducting`` side
    (arcs stand on the overriding plate).

    Convergent (C-C / C-O / O-O)
        Asymmetric mountain range on the overriding plate: steep front
        (σ ≈ 200 km) facing the trench, gentle back-slope (σ ≈ 700 km).
        Oceanic trench at 100–150 km from the peak on the subducting side.

    Divergent (continental rift / rifted margin / mid-ocean ridge)
        Continental: deep central rift valley with flanking rift shoulders
        (East African Rift, Baikal), segmented along strike.
        Transitional: rifted margin — thinned crust, shallow half-graben,
        no high shoulders.
        Oceanic: mid-ocean ridge whose morphology follows the FULL spreading
        rate — fast (>9 cm/yr) = smooth axial high (no graben), slow (<5 cm/yr)
        = median valley + rift mountains (Frisch et al. 2011).

    Transform
        Pure strike-slip (v_t/v_total > ~0.9): no systematic elevation
        change — a narrow band of enhanced roughness (±50 % noise boost
        within ~200 km) creates linear valleys and shutter ridges (San
        Andreas, North Anatolian).  Oblique transtension (v_t/v_total
        ~0.7–0.9, v_n < 0) opens a shallow pull-apart basin (Dead Sea,
        Salton Trough) whose depth scales with obliquity (§3.7).

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

    # Along-strike segmentation (width, decoupled from height): a higher-frequency
    # fBm (~base_freq 24 → ~270 km) quantized to discrete steps, so the convergent
    # belt width varies piecewise-constantly along strike (salient/recess) instead
    # of a smooth global field.  Separate from `arc_u` (which still drives height),
    # so width and height are decoupled.  (The divergent rift is NOT modulated here:
    # the "rift sea" is a transitional-crust band assigned in geography, not terrain
    # synthesis — see §4.)
    width_noise = fbm_on_points(
        px,
        py,
        pz,
        int(config.seed) + 7170,
        octaves=2,
        lacunarity=2.0,
        persistence=0.5,
        base_freq=24.0,
    )
    width_u = np.round(0.5 * (width_noise + 1.0) * 2.0) / 2.0  # quantized [0,1], 3 steps: {0,.5,1}

    # Intermontane-basin trigger: a lower-frequency fBm (~base_freq 12 → ~550 km)
    # marks which along-strike segments of a wide (super-critical) orogen collapse
    # into a basin (§3.8), so basins are discrete segments, not a uniform ribbon.
    basin_noise = fbm_on_points(
        px,
        py,
        pz,
        int(config.seed) + 8190,
        octaves=2,
        lacunarity=2.0,
        persistence=0.5,
        base_freq=12.0,
    )
    basin_u = 0.5 * (basin_noise + 1.0)  # [0, 1]

    # Half-graben polarity: ±1 field (~base_freq 16 → ~400 km wavelength) that
    # flips the footwall/hanging-wall side along strike, segmenting the rift into
    # dip domains (Scholz 1998) instead of a uniform one-sided scarp.
    polarity_noise = fbm_on_points(
        px,
        py,
        pz,
        int(config.seed) + 6160,
        octaves=2,
        lacunarity=2.0,
        persistence=0.5,
        base_freq=16.0,
    )
    polarity = np.where(polarity_noise > 0.0, 1.0, -1.0)
    side = _divergent_side_sign(mesh)

    # Rift along-axis phase field (§3.6): smooth u ∈ [0, 1], ~800 km wavelength.
    # Low-u segments are incipient rift tips (narrow, emergent grabens), high-u
    # segments mature drowned seas — the systematic along-strike stretching
    # gradient of propagating rifts (Vink 1982; Red Sea 180–350 km vs the
    # Afar/Manda Hararo tip ~50 km).
    rift_u_noise = fbm_on_points(
        px,
        py,
        pz,
        int(config.seed) + 9210,
        octaves=2,
        lacunarity=2.0,
        persistence=0.5,
        base_freq=8.0,
    )
    rift_u = 0.5 * (rift_u_noise + 1.0)  # [0, 1]

    # Lateral meander fields (±1, ~650 km): relief centres wander off the
    # kinematic boundary — rift axes localise on inherited weakness fabric
    # (Danakil en-echelon step-overs), orogenic belts deflect in
    # salients/recesses (Pennsylvania salient ~100 km).  Zero config amplitude
    # restores the old boundary-hugging behaviour.
    meander_div = (
        fbm_on_points(
            px,
            py,
            pz,
            int(config.seed) + 9310,
            octaves=2,
            lacunarity=2.0,
            persistence=0.5,
            base_freq=10.0,
        )
        if config.rift_meander_km > 0
        else None
    )
    meander_conv = (
        fbm_on_points(
            px,
            py,
            pz,
            int(config.seed) + 9410,
            octaves=2,
            lacunarity=2.0,
            persistence=0.5,
            base_freq=10.0,
        )
        if config.orogen_meander_km > 0
        else None
    )

    # Horst-graben fault-block noise: high-frequency anisotropic fBm aligned to
    # boundary strike, so blocks are elongated along the rift axis (not isotropic
    # blobs).  Only used in the continental rift branch, confined to the graben.
    fault_strike = _compute_boundary_strike(mesh, config) if config.noise_anisotropy > 0 else None
    fault_cfg = TerrainPipelineConfig(
        seed=config.seed + 700,
        noise_scale=config.noise_scale * 4.0,
        noise_octaves=config.noise_octaves,
        noise_persistence=config.noise_persistence,
        noise_lacunarity=config.noise_lacunarity,
        noise_anisotropy=config.noise_anisotropy,
    )
    fault_noise = (
        _anisotropic_fbm(mesh, fault_cfg, fault_strike)
        if fault_strike is not None
        else generate_fbm_on_cells(mesh, fault_cfg)
    )

    # Influence mask bound: the meander can shift relief centres off the
    # boundary, so widen the band by the largest configured wander.
    meander_max = max(config.rift_meander_km, config.orogen_meander_km)
    band_max = 1.2 * shoulder_sigma + meander_max

    # cell-mean mode with the age–depth seafloor: no separate ridge bump
    age_depth_ridges = continental_orogens_from_contract and config.ocean_age_depth_enabled
    for i, cell in enumerate(mesh.cells):
        if cell.boundary_type is None:
            continue
        d = cell.distance_to_boundary_km
        if d is None or d > band_max:
            continue

        rate = abs(cell.convergence_rate_cm_yr)
        rate_factor = (rate / ref_rate) ** 0.5  # sub-linear power law
        crust = getattr(cell, "crust_type", "")

        if cell.boundary_type == "convergent":
            # ---- Convergent: asymmetric mountain + trench ----------------
            # Belt width grows with the cumulative convergence S accumulated
            # during tectonic evolution (critical taper, Davis et al. 1983 —
            # proposal §3.6): a boundary that converged longer/faster gets a
            # wider orogen.  Continental collision widens ~2× faster than
            # subduction because buoyant continental lithosphere underthrusts
            # broadly instead of being floored by a dense slab.
            s_km = cell.cumulative_convergence_km
            k_type = (
                config.orogen_width_collision_rate
                if crust == "continental"
                else config.orogen_width_subduction_rate
            )
            sigma_conv = min(
                config.orogen_width_max_km,
                config.orogen_width_base_km + k_type * s_km,
            )
            # Along-arc segmentation: belt width varies 0.7–1.3× and the
            # amplitude factor spans [-0.25, 1.35] — high segments become
            # main islands/mountain knots, low ones islets or shelf, negative
            # ones subside into graben seas between arc segments.
            u = arc_u[i]
            seg_mod = 1.6 * u - 0.25
            # Width decoupled from height: quantized segment-based `width_u`
            # (not the smooth `u` that drives `seg_mod` height).
            sigma_front = (
                sigma_conv * (1.0 - asym * 0.5) * (0.7 + 0.6 * width_u[i])  # steep side
            )

            # Lateral deflection (salient/recess): the whole orogen
            # cross-section — mountain, intermontane basin, trench — shifts
            # off the kinematic boundary by δ_conv(x).
            d_o = d - config.orogen_meander_km * meander_conv[i] if meander_conv is not None else d

            # Mountain peak offset toward overriding plate (50–150 km)
            peak_offset = asym * sigma_conv * 0.25
            dist_from_peak = abs(d_o - peak_offset)
            mountain = float(
                _dual_boundary_falloff(
                    np.array([dist_from_peak]), ridge_sigma, sigma_front, shoulder_strength
                )[0]
            )

            # Crust-type-dependent amplitude.  A continental cell is C-C
            # collision (or the overriding side of an O-C subduction).  An
            # oceanic cell is only an O-O island arc when its neighbourhood is
            # all-oceanic; an oceanic cell with continental neighbours sits on
            # the subducting side of an O-C subduction and must NOT get the
            # island-arc uplift — the trench (below) is its only relief.
            if crust == "continental" and continental_orogens_from_contract:
                amp = 0.0  # cell-mean orogen from the history contract (orogen_profile)
            elif crust == "continental":
                amp = config.convergent_uplift_m * 1.3  # C-C collision
            elif cont_frac is not None and cont_frac[i] >= 0.15:
                amp = 0.0  # O-C subducting side → trench only
            elif subducting is not None and subducting[i]:
                amp = 0.0  # down-going plate of an O-O margin → trench only
            elif continental_orogens_from_contract and config.island_catalog_enabled:
                amp = 0.0  # arc crust and volcanoes from the island catalogue
            else:
                amp = config.convergent_uplift_m * 0.6  # O-O island arc

            delta_h[i] = amp * mountain * rate_factor * seg_mod * damp[i]

            # Intermontane basin (断陷): on wide (super-critical) continental
            # orogens, orogenic collapse forms a depression behind the range
            # (§3.8, Davis 1983 — Andes Altiplano, Tibet Qaidam).  Gated by belt
            # width + along-strike chance; depth scales with belt width.
            if (
                crust == "continental"
                and not continental_orogens_from_contract
                and sigma_conv > config.intermontane_basin_wide_km
            ):
                basin_strength = float(np.clip((basin_u[i] - 0.5) * 2.0, 0.0, 1.0))
                if basin_strength > 0.0:
                    basin_center = sigma_conv * 0.4  # behind the peak, overriding side
                    basin_sigma = sigma_conv * 0.25
                    basin_depth = (
                        config.intermontane_basin_depth_m
                        * (sigma_conv / config.orogen_width_max_km)
                        * basin_strength
                    )
                    delta_h[i] -= basin_depth * np.exp(
                        -((d_o - basin_center) ** 2) / (2 * basin_sigma * basin_sigma)
                    )

            # Oceanic trench on the subducting side (100–200 km from peak).
            # Only oceanic crust subducts and forms a trench; continental
            # collision has no trench.  Deepened to ~6 km relief so trenches
            # reach abyssal-trench depths (~−10 km; Mariana ≈ −11 km).
            trench_dist_km = sigma_conv * 0.35  # ~140 km
            if (
                d_o > trench_dist_km
                and crust == "oceanic"
                and not continental_orogens_from_contract
            ):
                dist_from_trench = abs(d_o - trench_dist_km - peak_offset)
                trench_sigma = sigma_conv * 0.25  # narrow, sharp trench
                trench = -_TRENCH_RELIEF_M * np.exp(
                    -(dist_from_trench * dist_from_trench) / (2 * trench_sigma * trench_sigma)
                )
                delta_h[i] += trench * rate_factor

        elif cell.boundary_type == "divergent":
            # ---- Divergent: crust-aware + spreading-rate-dependent ---------
            sigma_div = config.divergent_width_km  # per-type width (km)
            # Top-N crust leakage on an oceanic boundary (neighbourhood mostly
            # oceanic) follows the oceanic ridge profile, not the +1400 m
            # continental-rift one; −0.6×off decouples ridge depth from the
            # plate offset so crests stay near −2500 m (Earth-like).
            leaked = crust == "continental" and cont_frac is not None and cont_frac[i] < 0.5
            off_i = plate_offsets.get(cell.plate_id or "", 0.0) if plate_offsets else 0.0

            if (crust == "oceanic" or leaked) and age_depth_ridges:
                # The plate-cooling age–depth curve already is the ridge (age 0 at the
                # axis); axial highs and median valleys are 10–30 km features, sub-grid
                # on the cell-mean map.
                delta_h[i] = 0.0
            elif crust == "oceanic" or leaked:
                # Mid-ocean ridge, morphology by the local FULL spreading rate
                # (the opening rate of this boundary cell's plate pair).
                # Earth: ridge crest ~1300 m above the abyss, ~-2500 m below sea
                # level.  0.35× keeps crests submerged even on high-offset
                # oceanic plates after sea-level calibration (2026-08 feedback).
                full_rate = max(-cell.convergence_rate_cm_yr, 0.0)
                ridge_amp = config.divergent_depth_m * 0.35
                if full_rate >= 9.0:
                    # Fast: single smooth axial high (peak at axis, no graben).
                    ridge = ridge_amp * np.exp(-(d * d) / (2 * (sigma_div * 0.3) ** 2))
                    rift = 0.0
                elif full_rate <= 5.0:
                    # Slow: central median valley + flanking rift mountains.
                    ridge = ridge_amp * np.exp(
                        -(abs(d - sigma_div * 0.2) ** 2) / (2 * (sigma_div * 0.45) ** 2)
                    )
                    rift = (
                        -config.divergent_depth_m
                        * 0.25
                        * np.exp(-(d * d) / (2 * (sigma_div * 0.2) ** 2))
                    )
                else:
                    # Intermediate: shallow graben + low axial high.
                    ridge = ridge_amp * 0.7 * np.exp(-(d * d) / (2 * (sigma_div * 0.3) ** 2))
                    rift = (
                        -config.divergent_depth_m
                        * 0.1
                        * np.exp(-(d * d) / (2 * (sigma_div * 0.2) ** 2))
                    )
                delta_h[i] = (rift + ridge) * rate_factor * mod[i] - 0.6 * off_i
            elif crust == "transitional":
                # Rifted margin / continent-ocean transition: thinned crust, no
                # high rift shoulders — shallow half-graben relief only.
                rift = (
                    -config.divergent_depth_m
                    * 0.2
                    * np.exp(-(d * d) / (2 * (sigma_div * 0.3) ** 2))
                )
                delta_h[i] = rift * rate_factor * mod[i]
            else:
                # Continental rift: deep central graben + flanking rift
                # shoulders (East African Rift, Baikal, Red Sea).  The graben
                # must drop below sea level to form a rift sea, so the shoulder
                # Gaussian is pushed OUT (centre 0.6σ) and narrowed (0.3σ) — a
                # wide shoulder at 0.35σ overlaps the valley floor (74% of its
                # peak at d=0) and fills it back up, killing the rift sea.
                seg_mod = 0.7 + 0.6 * arc_u[i]  # [0.7, 1.3] shoulder-height modulation
                # Rate gate: only fast continental rifts (Red Sea stage) drop
                # below sea level; slow rifts (East African Rift / Baikal) stay
                # as a shallow graben above sea level.  `rate` = |v_n| (full
                # divergence rate, cm/yr) at the boundary.
                rift_depth_factor = 0.8 if rate >= config.continental_rift_sea_rate_cm_yr else 0.3
                # Along-axis phase (Vink 1982): tips are narrow and stay
                # emergent (East-Africa stage), mature segments wide and
                # drowned (Red Sea stage) — one boundary hosts the phase
                # mosaic instead of a uniform ribbon.
                u_r = rift_u[i]
                m_axis = config.rift_axis_modulation
                rift_depth_factor *= 0.55 + 0.45 * u_r
                # Half-graben: the shoulder sits on ONE side (polarity), so the
                # rift is asymmetric instead of two symmetric shoulders.  The
                # valley axis itself wanders laterally off the kinematic
                # boundary (en-echelon inherited fabric): ds_side = signed
                # distance from the *wandered* axis.
                ds_side = d * side[i]
                if meander_div is not None:
                    ds_side -= config.rift_meander_km * meander_div[i]
                ds = ds_side * polarity[i]
                # Rift-valley width grows with cumulative divergence E
                # (distributed extension, East African Rift 50–200 km — §3.6):
                # a boundary that rifted longer/faster gets a wider graben, so the
                # rift sea is wider and varies along strike instead of a uniform
                # 1-cell slit.
                valley_sigma = min(
                    config.rift_valley_max_km,
                    config.rift_valley_base_km
                    + config.rift_valley_rate * cell.cumulative_divergence_km,
                ) * (1.0 - m_axis + 2.0 * m_axis * u_r)
                rift = (
                    -config.divergent_depth_m
                    * rift_depth_factor
                    * np.exp(-(ds_side * ds_side) / (2 * valley_sigma * valley_sigma))
                )
                ridge = (
                    config.divergent_depth_m
                    * 0.7
                    * seg_mod
                    * np.exp(-((ds - sigma_div * 0.6) ** 2) / (2 * (sigma_div * 0.3) ** 2))
                )
                # Horst-graben: high-freq fault blocks confined to the graben
                # (|ds_side| < σ_div), ±fault_amp relief so the rift floor is
                # broken into along-strike horsts/grabens instead of a smooth
                # valley.
                fault_amp = config.rift_fault_block_amp_m  # m (§3.8)
                fault = (
                    fault_amp
                    * fault_noise[i]
                    * np.exp(-(ds_side * ds_side) / (2 * (sigma_div * 0.4) ** 2))
                )
                # uplift_mod (mod) only modulates the shoulder (ridge), not the
                # valley (rift) — otherwise the arc noise halves the graben depth
                # and kills the rift sea (was ~-26 m).
                delta_h[i] = (rift + ridge * mod[i]) * rate_factor + fault

    # ---- Transform: leaky-transform basins + roughness boost ----
    # Pure strike-slip (v_t/v_total > threshold) is roughness-only — San
    # Andreas / North Anatolian linear valleys, shutter ridges, sag ponds.
    # Oblique transforms with an extensional component (v_t/v_total below the
    # threshold AND v_n < 0) open a shallow pull-apart basin (Dead Sea −430 m,
    # Salton Trough) whose depth scales with the obliquity (§3.7).
    transform_cells: list[int] = []
    leaky_cells: dict[int, float] = {}  # cid → obliquity strength [0, 1]
    for i, cell in enumerate(mesh.cells):
        if cell.boundary_type == "transform":
            transform_cells.append(i)
            mesh.cells[i].landform = (
                "transform" if not mesh.cells[i].landform else mesh.cells[i].landform
            )
            tf = cell.tangential_fraction
            if 0.0 < tf < config.transform_leaky_threshold and cell.convergence_rate_cm_yr < 0.0:
                # Obliquity strength: 1.0 at v_t/v_total=0.7 (strongest oblique),
                # 0.0 at the threshold (pure strike-slip).  Only transtension
                # (v_n < 0) opens a basin; transpression would uplift instead.
                strength = (config.transform_leaky_threshold - tf) / (
                    config.transform_leaky_threshold - 0.7
                )
                leaky_cells[i] = float(np.clip(strength, 0.0, 1.0))

    # Pull-apart basin subsidence: the leaky trace is a continuous along-strike
    # floor, its non-leaky flanks are the basin shoulders (half depth).
    if leaky_cells:
        for cid, strength in leaky_cells.items():
            depth = config.transform_leaky_basin_depth_m * strength
            delta_h[cid] -= depth
            for nid in mesh.cells[cid].neighbors:
                if nid not in leaky_cells:
                    delta_h[nid] -= depth * 0.5

    # Roughness boost in a narrow band around transform boundary cells
    # (σ × 0.4 ≈ 200 km): 1.5 at the fault trace, decaying to 1.0 outward.
    transform_boost = np.ones(n, dtype=np.float64)
    if transform_cells:
        sigma_trans = config.transform_width_km  # per-type width (km)
        tdist = geodesic_bfs(mesh, transform_cells, config.radius_km, max_dist_km=1.2 * sigma_trans)
        for cid, d_t in tdist.items():
            transform_boost[cid] = 1.0 + 0.5 * np.exp(
                -(d_t * d_t) / (2 * sigma_trans * sigma_trans)
            )

    return delta_h, transform_boost


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
    config: TerrainPipelineConfig,
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

    # Propagate strike to cells within the boundary influence radius, each
    # cell inheriting the strike of its nearest boundary cell.
    sigma = 500.0  # km — same as boundary_influence default
    propagated = geodesic_bfs_with_source(
        mesh, list(strike.keys()), config.radius_km, max_dist_km=sigma
    )
    for nid, (src, _d) in propagated.items():
        if nid not in strike:
            strike[nid] = strike[src]

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
    #    adjacency graph via bincount accumulation (previously a per-cell
    #    Python loop calling np.var on tiny lists).
    offsets = np.fromiter((len(cell.neighbors) for cell in mesh.cells), dtype=np.int64, count=n)
    rows = np.repeat(np.arange(n), offsets)
    cols = np.fromiter(
        (nb for cell in mesh.cells for nb in cell.neighbors),
        dtype=np.int64,
        count=int(offsets.sum()),
    )
    counts = 1.0 + np.bincount(rows, minlength=n)
    sums = elevations + np.bincount(rows, weights=elevations[cols], minlength=n)
    sq_sums = elevations**2 + np.bincount(rows, weights=elevations[cols] ** 2, minlength=n)
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
# Overlay archipelago texture
# =========================================================================


#: Shoreline depth (m) of the channels between the islands of an overlay fragment: the
#: middle of the 1–5 m shoreline range the continental shelf uses.
_FRAGMENT_SHORE_DEPTH_M = 3.0
#: Deepest basin (m) between the blocks of an overlay fragment beyond the shelf: rifted
#: continental fragments carry inter-block basins and troughs of roughly 0.5–1.5 km
#: (Zealandia's plateaus and troughs); observation-scale value.
_FRAGMENT_BASIN_DEPTH_M = 1000.0


def _apply_overlay_archipelago_texture(
    mesh: CVTMesh, config: TerrainPipelineConfig, elevation: np.ndarray
) -> np.ndarray:
    """Cut the islands of positive overlays on the final surface — ``strength`` = land fraction.

    Within each positive overlay's fragment footprint (``_overlay_claims``) the cells whose
    patch-scale fBm (islands of about a third of the radius) falls in the bottom
    ``1 − strength`` fraction become channels.  The channels between the islands of a
    crustal fragment start as shelf seas: from the shoreline depth at the islands they deepen
    with the distance from the nearest island to the shelf-break depth at a passive-margin
    shelf width (88 km), then, over a second shelf width, into the thinned-crust basins
    between the fragment's blocks (``_FRAGMENT_BASIN_DEPTH_M``).  Cell means are taken at the
    cell centre (half a spacing off the coast); the depth of the patch fBm below the cut
    level stretches the distance by a factor 0.5–1.5, so channel axes run deeper than their
    banks and the isobaths do not just trace the island outlines.  The shallow shelf left on
    the oceanic crust just outside the fragment (laid around the uncut plateau) takes the same
    profile, so it does not surface as a ring of land around the outline.  Cells already
    deeper keep their depth.  Runs on the final surface, after the sea-level trim and
    before the author pins, so the cut is measured from the actual sea surface and no later
    stage can lift the channels back; ``strength`` ≥ 1 is a solid fragment.  Negative
    overlays carve seas through the base-override gate instead.
    """
    claims = _overlay_claims(mesh, config)
    if not claims:
        return elevation
    sea_level = config.sea_level_offset_m
    out = np.asarray(elevation, dtype=np.float64).copy()
    n = len(mesh.cells)
    xyz = mesh.cell_xyz / np.linalg.norm(mesh.cell_xyz, axis=1, keepdims=True)
    rows = np.repeat(np.arange(n), [len(c.neighbors) for c in mesh.cells])
    cols = np.array([j for c in mesh.cells for j in c.neighbors], dtype=np.int64)
    w = (
        np.arccos(np.clip(np.einsum("ij,ij->i", xyz[rows], xyz[cols]), -1.0, 1.0))
        * config.radius_km
    )
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import dijkstra

    graph = csr_matrix((w, (rows, cols)), shape=(n, n))
    half_dx = 0.5 * float(np.sqrt(4.0 * np.pi * config.radius_km**2 / n))
    oceanic = np.array([c.crust_type == "oceanic" for c in mesh.cells])
    for k, (f, claim) in enumerate(claims):
        land_fraction = float(np.clip(f.strength, 0.0, 1.0))
        if land_fraction >= 1.0 or not claim.any():
            continue
        seed = feature_noise_seed(int(config.seed)) + 104729 + 7919 * k
        noisy = _patch_noise(mesh, f, seed, _OVERLAY_ISLAND_WAVENUMBER, _OVERLAY_ISLAND_OCTAVES)
        thr = float(np.quantile(noisy[claim], 1.0 - land_fraction))
        sea = claim & (noisy < thr)
        # The shelf around the uncut plateau extends a shelf width onto the oceanic crust
        # outside the fragment; with the plateau cut into islands its shallowest part (the
        # sea-level trim exposes it) would be a ring of land around the outline.  Those cells
        # join the channels: oceanic crust within a shelf width outside, shallower than the
        # shelf break.
        d_out = dijkstra(
            graph, indices=np.flatnonzero(claim), min_only=True, limit=_PASSIVE_MARGIN_SHELF_KM
        )
        ring = (
            ~claim & oceanic & np.isfinite(d_out) & (out > sea_level - config.shelf_break_depth_m)
        )
        sea = sea | ring
        islands = claim & ~sea & (out > sea_level)
        zone = claim | ring
        nodes = np.flatnonzero(zone)
        if islands.any():
            d = dijkstra(
                graph[nodes][:, nodes],
                indices=np.searchsorted(nodes, np.flatnonzero(islands)),
                min_only=True,
            )
            dist = np.full(n, np.inf)
            dist[nodes] = d
        else:
            dist = np.full(n, np.inf)
        idx = np.flatnonzero(sea)
        lo = float(noisy[claim].min())
        below = np.clip((thr - noisy[idx]) / max(thr - lo, 1e-12), 0.0, 1.0)  # 1 = deepest
        x = np.maximum(dist[idx] - half_dx, 0.0) / _PASSIVE_MARGIN_SHELF_KM
        x = x * (0.5 + 1.0 * below)
        shelf = config.shelf_break_depth_m
        depth = _FRAGMENT_SHORE_DEPTH_M + (shelf - _FRAGMENT_SHORE_DEPTH_M) * np.clip(x, 0.0, 1.0)
        t = np.clip(x - 1.0, 0.0, 1.0)  # beyond one shelf width: thinned-crust basin
        depth = depth + (max(_FRAGMENT_BASIN_DEPTH_M, shelf) - shelf) * t * t * (3.0 - 2.0 * t)
        out[idx] = np.minimum(out[idx], sea_level - depth)
    return out


# =========================================================================
# Sea level calibration ("倒水") — volume-driven binary search
# =========================================================================


def _overlay_calibration_mask(mesh: CVTMesh, config: TerrainPipelineConfig) -> np.ndarray | None:
    """Cells covered by terrain-only overlays (None when there are none).

    The water-budget calibration solves the global sea level blind to these
    cells, so an overlay's added/carved land stays a local deviation instead
    of dragging every coastline (2026-09-30).
    """
    spec = config.geography
    if spec is None or not spec.overlays:
        return None
    return spec.overlay_cell_mask(
        np.array([c.x for c in mesh.cells], dtype=np.float64),
        np.array([c.y for c in mesh.cells], dtype=np.float64),
        np.array([c.z for c in mesh.cells], dtype=np.float64),
    )


def _apply_sea_level_calibration(
    mesh: CVTMesh,
    elevation: np.ndarray,
    config: TerrainPipelineConfig,
    overlay_mask: np.ndarray | None = None,
    label: str = "Water calibration",
) -> np.ndarray:
    """Calibrate sea level to match the target land fraction.

    Sorts (elevation, area) pairs once, builds a cumulative area prefix sum from
    highest to lowest and solves for the sea level on that curve, linearly
    interpolated between consecutive cell elevations (continuous in the inputs).

    Complexity: O(n log n)  (one sort + prefix sum + one search).

    ``overlay_mask`` (2026-09-30): cells covered by terrain-only geography
    overlays are excluded from the budget solve — the sea level is set by the
    plate-stage world and the overlay's added/carved land becomes a *local*
    deviation (total land fraction may drift from target by the overlay's net
    contribution, which is the point).  Falls back to the global solve when
    overlays cover more than 40% of the surface.
    """
    n = mesh.num_cells
    areas = np.array([c.area_km2 for c in mesh.cells], dtype=np.float64)

    if overlay_mask is not None and overlay_mask.mean() <= 0.40:
        keep = ~overlay_mask
        calibration_elev = elevation[keep]
        calibration_areas = areas[keep]
        cal_note = f" overlay-blind({int(overlay_mask.sum())} cells)"
    else:
        calibration_elev = elevation
        calibration_areas = areas
        cal_note = ""

    total_area = np.sum(areas)
    target_land_area = config.target_land_fraction * np.sum(calibration_areas)

    # Sort by elevation descending, with area alongside.
    order = np.argsort(calibration_elev, kind="stable")[::-1]  # highest → lowest
    elev_sorted = calibration_elev[order]
    area_sorted = calibration_areas[order]

    # Land area above h, interpolated linearly between consecutive cell elevations so the
    # solution moves continuously with the elevations: a step function puts the sea level
    # in the middle of whatever gap the target falls into, and one coastal cell changing
    # order (last-bit float noise) would shift the whole map by the gap width.
    cum_land = np.cumsum(area_sorted)
    k = int(np.searchsorted(cum_land, target_land_area))
    if k <= 0:
        sea_level = float(elev_sorted[0])
    elif k >= len(elev_sorted):
        sea_level = float(elev_sorted[-1])
    else:
        c0, c1 = float(cum_land[k - 1]), float(cum_land[k])
        e0, e1 = float(elev_sorted[k - 1]), float(elev_sorted[k])
        t = (target_land_area - c0) / max(c1 - c0, 1e-12)
        sea_level = e0 + t * (e1 - e0)

    # Compute implied water budget
    depths = np.maximum(0.0, sea_level - elevation)  # m
    water_km3 = np.sum(depths / 1000.0 * areas)
    surface_km2 = total_area
    implied_budget_km = water_km3 / surface_km2

    land_area_final = float(np.sum(areas[elevation > sea_level]))
    land_pct = 100.0 * land_area_final / surface_km2
    cell_pct = 100.0 * np.sum(elevation > sea_level) / n

    logger.info(
        "  %s: target %.1f%% land → sea level %.0f m → "
        "%.1f%% land by area (%.1f%% by cells), "
        "implied water budget %.2f km (%.1f million km^3)%s",
        label,
        config.target_land_fraction * 100,
        sea_level,
        land_pct,
        cell_pct,
        implied_budget_km,
        water_km3 / 1e6,
        cal_note,
    )

    return elevation - sea_level


def _apply_interior_lowlands(
    mesh: CVTMesh,
    elevation: np.ndarray,
    config: TerrainPipelineConfig,
) -> tuple[np.ndarray, np.ndarray]:
    """Lower deep continental interiors toward cratonic lowland elevation.

    The bimodal continental base (``continental_elevation_m``) plus convergent
    boundary uplift leaves plate interiors as a uniform high plateau — without
    this stage roughly half of emergent land sits above 1000 m, whereas Earth's
    median land elevation is ≈ 350–500 m (Cogley 1984; ETOPO1).  Real continents
    are low cratons ringed by orogenic belts: mountain-building is concentrated
    at active convergent margins, and the deep interior subsides back toward sea
    level.

    Lowering is a smoothstep ramp from 0 at the nearest convergent (orogenic)
    boundary to full ``interior_lowland_depth_m`` at
    ``interior_lowland_distance_scale_km`` beyond it, soft-clamped above
    ``interior_lowland_floor_m`` (smooth maximum) so the calibrated coastline
    (and target land fraction) is never crossed.  Runs before the island-arc /
    interior-landform stages so paleo-orogeny belts are carved
    on top of the lowlands.

    References:
      * Cogley, J.G. (1984). "Continental margins and the extent and number of
        the continents." *Reviews of Geophysics*, 22(2), 101–122. — cratonic
        interiors are systematically lower than active margins.
      * ETOPO1 Global Relief Model — Earth median land elevation ≈ 350–500 m.

    Modifies *elevation* in-place.

    Returns ``(elevation, clamped)`` — the latter marks cells soft-clamped to the
    floor (the interior overshoot), which the downstream deposition fill targets.
    """
    n = mesh.num_cells
    empty = np.zeros(n, dtype=bool)
    if not config.interior_lowland_enabled:
        return elevation, empty
    depth = config.interior_lowland_depth_m
    if depth <= 0:
        return elevation, empty
    scale = config.interior_lowland_distance_scale_km
    floor = config.interior_lowland_floor_m
    sea_level = config.sea_level_offset_m  # 0 after calibration

    # Convergent boundary cells are the orogenic source.  Seed the BFS from the
    # exact plate-edge cells (distance 0) so the ramp origin is the trench /
    # collision zone, not the propagated type halo (~1.2× boundary_influence_km).
    sources: list[int] = []
    for i, cell in enumerate(mesh.cells):
        d = cell.distance_to_boundary_km
        if cell.boundary_type == "convergent" and d is not None and d <= 1.0:
            sources.append(i)
    if not sources:
        logger.info("  Interior lowlands: no convergent boundaries, skipping")
        return elevation, empty

    # Multi-source geodesic BFS → distance to the nearest convergent boundary.
    dist = geodesic_bfs(mesh, sources, config.radius_km)
    dist_km = np.full(n, -1.0)  # unreachable → negative → ramp 0
    for cid, d in dist.items():
        dist_km[cid] = d

    # Smoothstep ramp 0 → 1 over [0, scale].
    t = np.clip(dist_km / scale, 0.0, 1.0)
    ramp = t * t * (3.0 - 2.0 * t)

    # Lower continental land cells only.  The floor is a SOFT clamp (smooth
    # maximum via logsumexp) at the calibrated sea level + floor_m: cells
    # approaching it taper off instead of hard-clamping, so lowlands keep
    # intra-cell relief and the histogram doesn't spike — while never crossing
    # the sea level (coastline unchanged).
    n_lowered = 0
    clamped = np.zeros(n, dtype=bool)
    min_h = sea_level + floor
    # Fixed transition width (metres), independent of floor_m: cells that would
    # fall below the floor spread smoothly over ~this band instead of piling at
    # a single value.
    soft_k = 1.0 / 50.0
    for i, cell in enumerate(mesh.cells):
        if elevation[i] <= sea_level:
            continue
        if getattr(cell, "crust_type", "") != "continental":
            continue
        r = ramp[i]
        if r <= 0.0:
            continue
        new_h = elevation[i] - depth * r
        if new_h < min_h:
            # Smooth maximum: approaches min_h without a hard cliff.
            new_h = float(np.logaddexp(soft_k * new_h, soft_k * min_h) / soft_k)
            clamped[i] = True
        if new_h < elevation[i]:
            elevation[i] = new_h
            n_lowered += 1

    if n_lowered:
        logger.info(
            "  Interior lowlands: lowered %d cells (depth=%.0f m, scale=%.0f km, floor=%.0f m)",
            n_lowered,
            depth,
            scale,
            floor,
        )
    return elevation, clamped


def _apply_deposition_fill(
    mesh: CVTMesh,
    elevation: np.ndarray,
    config: TerrainPipelineConfig,
    clamped: np.ndarray,
) -> np.ndarray:
    """Fill interior basins with sediment to their spill level (deposition).

    Runs *after* the interior lowlands (whose soft floor has already clamped
    below-sea-level cells back to ~0 m, fixing the coastline).  Deposit sediment
    to raise the **clamped** cells (the interior overshoot) to their **spill
    level**, the lowest outlet to the global ocean, so they drain again (Landlab
    SinkFiller; Tucker et al. 2001).  This adjusts *inland* elevation without
    touching the calibrated coastline, and — crucially — does **not** fill
    natural seas/straits (which were never clamped).  A fraction of basins are
    left partially unfilled as **lakes** at ``spill − lake_depth_m``, marked
    ``is_lake``.

    References:
      * Tucker, G.E., Lancaster, S.T., Gasparini, N.M., Bras, R.L., & Rybarczyk,
        S.M. (2001). "An object-oriented framework for distributed hydrologic
        and geomorphic modeling using triangulated irregular networks."
        *Computers & Geosciences*, 27(8), 959–973.
      * Barnes, R., Lehman, C., & Mulla, D. (2014). "Priority-flood."
        *Computers & Geosciences*, 62, 117–127.

    Modifies *elevation* in-place.
    """
    from collections import deque

    from .hydrology import priority_flood_fill

    if not config.deposition_enabled:
        return elevation
    sea_level = config.sea_level_offset_m
    n = mesh.num_cells
    neighbors = [c.neighbors for c in mesh.cells]

    # Spill level per cell (priority-flood from the ocean).
    filled, _ = priority_flood_fill(elevation, elevation >= sea_level, neighbors)

    # Only the interior-lowlands overshoot (clamped cells) below their spill
    # level is filled — natural seas/straits are never clamped, so are untouched.
    depressed = clamped & (filled > elevation)
    if not bool(np.any(depressed)):
        return elevation

    rng = np.random.default_rng(config.seed + 900)
    lake_depth = config.lake_depth_m
    visited = np.zeros(n, dtype=bool)
    n_filled = 0
    n_lake = 0
    # One uniform per cell, addressed by the basin's lowest cell id: the draw a
    # basin gets must not depend on how many basins (or small pits) were met
    # before it, which shifts with float noise in the depression test.
    basin_u = rng.random(n)
    for s in range(n):
        if not depressed[s] or visited[s]:
            continue
        basin: list[int] = []
        bq: deque[int] = deque([s])
        visited[s] = True
        while bq:
            i = bq.popleft()
            basin.append(i)
            for j in neighbors[i]:
                if depressed[j] and not visited[j]:
                    visited[j] = True
                    bq.append(j)

        if len(basin) >= 20 and basin_u[min(basin)] < config.lake_fraction:
            # Leave a lake: fill to spill − lake_depth (never below the floor).
            # Only large basins become lakes; tiny noise pits are always filled.
            for i in basin:
                target = filled[i] - lake_depth
                if target > elevation[i]:
                    elevation[i] = target
                mesh.cells[i].is_lake = True
            n_lake += len(basin)
        else:
            for i in basin:
                elevation[i] = filled[i]
            n_filled += len(basin)

    if n_filled or n_lake:
        logger.info(
            "  Deposition fill: %d cells to spill level, %d cells left as lakes "
            "(frac=%.0f%% of %d basins)",
            n_filled,
            n_lake,
            config.lake_fraction * 100,
            int(np.sum(visited)),
        )
    return elevation


# =========================================================================
# Shared post-processing: continental shelf + island arcs
# =========================================================================


def _clamp_deep_ocean_floors(
    mesh: CVTMesh,
    elevation: np.ndarray,
    config: TerrainPipelineConfig,
) -> np.ndarray:
    """Clamp physically impossible deep-ocean floors to the Earth envelope.

    Two independent floors (constants documented at the top of this module):

    1. Continental-crust ocean cells: floor −5.3 km.  Trench relief carved
       into cells the crust relabelling later marks continental produces
       −10 km continental seafloor, which isostasy forbids.
    2. Coast-adjacent ocean ring (ocean cells with ≥1 land neighbour):
       floor −6.0 km.  Real trench axes sit at least one cell offshore;
       the coast-adjacent fringe bottoms out near −6 km (Cayman, Hellenic).

    Both floors only raise cells that are ≥5 km below sea level, so no cell
    can cross the sea surface: the downstream land mask and the calibrated
    sea level are unchanged — the coastline is bit-stable.
    """
    sea_level = config.sea_level_offset_m
    n = len(mesh.cells)
    ocean = elevation <= sea_level

    elevation = elevation.copy()

    # Floor 1: continental-crust seafloor
    crust = np.array([c.crust_type or "" for c in mesh.cells], dtype=object)
    cont = ocean & (crust == "continental")
    elevation[cont] = np.maximum(elevation[cont], _CONTINENTAL_CRUST_FLOOR_M)

    # Floor 2: coast-adjacent ring
    land = elevation > sea_level
    for i, cell in enumerate(mesh.cells):
        if not ocean[i]:
            continue
        for nid in cell.neighbors:
            if 0 <= nid < n and land[nid]:
                elevation[i] = max(elevation[i], _COAST_RING_FLOOR_M)
                break

    return elevation


def _apply_continental_shelf(
    mesh: CVTMesh,
    elevation: np.ndarray,
    config: TerrainPipelineConfig,
    rng: np.random.Generator,
    *,
    active_flexure: np.ndarray | None = None,
    source_fields: dict[str, np.ndarray] | None = None,
) -> np.ndarray:
    """Continental shelf and slope (see ``_shelf_profile`` for the physics).

    Modifies *elevation* in-place. With an explicit active-flexure footprint,
    the down-going plate keeps its incoming seafloor and flexural topography;
    the shelf and continental slope describe the other margin substrate.
    The asymmetric pipeline supplies the footprint from ``trench_relief``.
    Active trench sediment infill requires its own sediment budget. Callers
    without this source footprint use the coastal shelf approximation.
    """
    from .terrain_source_export import capture_source_field

    capture_source_field(source_fields, "before_shelf_m", elevation)
    if source_fields is not None:
        capture_source_field(
            source_fields,
            "shelf_continental_crust_mask",
            np.array([cell.crust_type == "continental" for cell in mesh.cells]),
        )
    if config.shelf_width_km <= 0:
        capture_source_field(source_fields, "after_shelf_m", elevation)
        return elevation
    if active_flexure is not None:
        active_flexure = np.asarray(active_flexure, dtype=bool)
        if active_flexure.shape != elevation.shape:
            raise ValueError("active flexure must have one value per elevation cell")
    # Draws kept identical in kind and order (one scalar, one per-cell array)
    # so the downstream stages see the same RNG state.
    shore_level = rng.uniform(-5.0, -1.0)  # shoreline depth below sea level (m)
    shelf_noise = rng.uniform(-0.05, 0.05, size=len(mesh.cells))  # per-cell ±5%, by cell id
    capture_source_field(source_fields, "shelf_noise_fraction", shelf_noise)
    capture_source_field(
        source_fields, "shelf_shore_depth_m", np.full(len(elevation), -shore_level)
    )
    touched, z_new = _shelf_profile(
        mesh, elevation, config, -shore_level, shelf_noise, source_fields=source_fields
    )
    if active_flexure is not None:
        eligible = ~active_flexure[touched]
        touched, z_new = touched[eligible], z_new[eligible]
    elevation[touched] = z_new
    capture_source_field(source_fields, "after_shelf_m", elevation)
    return elevation


def _shelf_profile(
    mesh: CVTMesh,
    elevation: np.ndarray,
    config: TerrainPipelineConfig,
    shore_depth: float,
    shelf_noise: np.ndarray,
    *,
    source_fields: dict[str, np.ndarray] | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Continental shelf on submerged continental crust, continental slope beyond it.

    A continental shelf is continental crust below sea level: buoyant crust
    that the sea has drowned, planed by waves and filled by sediment down to
    the shelf break.  Its seaward edge is the continent–ocean boundary (COB),
    where the continental slope drops to the oceanic floor.  So the shelf
    width of each stretch of coast is the distance from the coastline to the
    COB of the submerged continental crust connected to it — wide where the
    crust partition left a drowned continental margin (rift seas, inland
    seas).  The crust partition has no thinned-margin class (continental crust
    ≈ land), so every coast also gets the drowned margin of its type — the
    global mean shelf width of passive (88 km) or active (31 km) margins — and
    the shelf reaches the farther of the two.

    Profile, with ``d`` the distance (km) from the coastline itself and ``W``
    the shelf width of the nearest coast:

    * shelf platform, ``0 ≤ d ≤ W``: linear from a near-surface depth at the
      shore to the shelf break ``h_b`` (``shelf_break_depth_m``);
    * continental slope, ``d > W``: deepening at ``tan 4°`` from the shelf
      break (from the shore where ``W = 0``) until it meets the original
      seafloor, which is kept where it is shallower.

    The coastline is the land–ocean Voronoi edge: a coast-adjacent ocean cell
    sits half a centre spacing from it, and distances grow through the ocean
    by geodesic Dijkstra.  Each cell takes the profile averaged over its own
    footprint (a disc of the cell's area projected onto the coast normal), so
    the depth follows the coastline and crust geometry instead of the cell
    index.  Only ocean cells change, and every new value stays below sea
    level.

    The shelf break sits at about the long-term lowstand (Earth: mean break
    132 m, Shepard 1963; Last Glacial Maximum sea level −134 m, Lambeck et al.
    2014), so ``shelf_break_depth_m`` is a world input derived from that
    world's sea-level history.

    Returns ``(touched, z_new)``: the changed cell ids and their elevations.
    """
    import heapq

    sea_level = config.sea_level_offset_m
    n = len(mesh.cells)
    ocean = elevation <= sea_level
    xyz = mesh.cell_xyz
    area = np.array([c.area_km2 for c in mesh.cells])
    footprint_r = np.sqrt(area / np.pi)

    def arc_km(i: int, j: int) -> float:
        return float(config.radius_km * np.arccos(np.clip(xyz[i] @ xyz[j], -1.0, 1.0)))

    # 1. Coast-adjacent ocean cells start at half the spacing to their nearest
    #    land neighbour (the shared Voronoi edge bisects the two centres); that
    #    land cell is the coast source the cell's shelf width is read from.
    dist = np.full(n, np.inf)
    source = np.full(n, -1, dtype=np.int64)
    for oc in np.nonzero(ocean)[0]:
        for nid in mesh.cells[oc].neighbors:
            if not ocean[nid]:
                h = 0.5 * arc_km(int(oc), nid)
                if h < dist[oc]:
                    dist[oc] = h
                    source[oc] = nid
    seeds = np.nonzero(np.isfinite(dist))[0]
    if seeds.size == 0:
        from .terrain_source_export import capture_source_field

        capture_source_field(source_fields, "shelf_coast_cell_id", source)
        capture_source_field(source_fields, "shelf_coast_width_m", np.zeros(n))
        capture_source_field(source_fields, "shelf_coast_drowned_width_m", np.zeros(n))
        capture_source_field(source_fields, "shelf_coast_type_width_m", np.zeros(n))
        capture_source_field(source_fields, "shelf_coast_type_active_mask", np.zeros(n, dtype=bool))
        capture_source_field(source_fields, "shelf_distance_m", dist * 1000)
        logger.info("  Continental shelf: no coastline cells detected")
        return np.zeros(0, dtype=np.int64), np.zeros(0)

    # 2. Submerged continental crust connected to the coast (the drowned margin).
    crust = np.array([c.crust_type or "" for c in mesh.cells], dtype=object)
    drowned = ocean & (crust == "continental")
    margin = np.zeros(n, dtype=bool)
    stack = [int(i) for i in seeds if drowned[i]]
    margin[stack] = True
    while stack:
        i = stack.pop()
        for nid in mesh.cells[i].neighbors:
            if drowned[nid] and not margin[nid]:
                margin[nid] = True
                stack.append(nid)

    # 3. Geodesic Dijkstra through the ocean, carrying the coast source.
    heap = [(float(dist[i]), int(i)) for i in seeds]
    heapq.heapify(heap)
    while heap:
        d, i = heapq.heappop(heap)
        if d > dist[i]:
            continue
        for nid in mesh.cells[i].neighbors:
            if ocean[nid]:
                nd = d + arc_km(i, nid)
                if nd < dist[nid]:
                    dist[nid] = nd
                    source[nid] = source[i]
                    heapq.heappush(heap, (nd, nid))

    # 4. Shelf width per coast source: out to the seaward edge of the farthest
    #    drowned-continental-crust cell it is nearest to (the COB), and at least
    #    the drowned margin of the coast's type.
    width = np.zeros(n)
    for j in np.nonzero(margin)[0]:
        width[source[j]] = max(width[source[j]], dist[j] + footprint_r[j])
    drowned_width = width.copy() if source_fields is not None else None
    active = np.array(
        [
            c.distance_to_boundary_km is not None
            and c.distance_to_boundary_km <= config.boundary_influence_km
            and (c.convergence_rate_cm_yr > 0.0 or c.tangential_fraction > 0.5)
            for c in mesh.cells
        ]
    )
    belt = np.where(active, _ACTIVE_MARGIN_SHELF_KM, _PASSIVE_MARGIN_SHELF_KM)
    coast = np.unique(source[seeds])
    width[coast] = np.maximum(width[coast], belt[coast])

    if source_fields is not None:
        from .terrain_source_export import capture_source_field

        coastal_source = source.copy()
        coastal_source[coast] = coast
        width_field = np.zeros(n)
        reachable = coastal_source >= 0
        width_field[reachable] = width[coastal_source[reachable]] * 1000
        capture_source_field(source_fields, "shelf_coast_cell_id", coastal_source)
        capture_source_field(source_fields, "shelf_coast_width_m", width_field)
        assert drowned_width is not None
        drowned_field = np.zeros(n)
        type_field = np.zeros(n)
        active_field = np.zeros(n, dtype=bool)
        drowned_field[reachable] = drowned_width[coastal_source[reachable]] * 1000
        type_field[reachable] = belt[coastal_source[reachable]] * 1000
        active_field[reachable] = active[coastal_source[reachable]]
        capture_source_field(source_fields, "shelf_coast_drowned_width_m", drowned_field)
        capture_source_field(source_fields, "shelf_coast_type_width_m", type_field)
        capture_source_field(source_fields, "shelf_coast_type_active_mask", active_field)
        capture_source_field(source_fields, "shelf_distance_m", dist * 1000)

    shelf_break = config.shelf_break_depth_m
    deepest = float(-(elevation[ocean].min() - sea_level))
    reach = float(width.max()) + max(0.0, deepest - shore_depth) / _CONTINENTAL_SLOPE_M_PER_KM
    touched = np.nonzero(np.isfinite(dist) & (dist <= reach))[0]
    w_cell = width[source[touched]][:, None]

    # Footprint average: a disc of radius r projected onto the coast normal has
    # density ∝ sqrt(1 − u²) — Gauss–Chebyshev (second kind) nodes are exact.
    k = np.arange(1, 8)
    nodes = np.cos(k * np.pi / 8.0)
    weights = np.sin(k * np.pi / 8.0) ** 2
    weights /= weights.sum()
    d_s = np.maximum(dist[touched, None] + footprint_r[touched, None] * nodes[None, :], 0.0)
    has_shelf = w_cell > 0.0
    platform = shore_depth + (shelf_break - shore_depth) * np.minimum(
        d_s / np.where(has_shelf, w_cell, 1.0), 1.0
    )
    edge_depth = np.where(has_shelf, shelf_break, shore_depth)
    slope = edge_depth + np.maximum(d_s - w_cell, 0.0) * _CONTINENTAL_SLOPE_M_PER_KM
    profile = np.where(has_shelf & (d_s <= w_cell), platform, slope)
    depth = (profile * weights[None, :]).sum(axis=1)

    z_new = sea_level - depth * (1.0 + shelf_noise[touched])
    on_shelf = dist[touched] <= width[source[touched]]
    # The slope only deepens: the original seafloor wins where it is shallower
    # (seamounts, ridges, shallow-sea features).  The shelf itself overwrites.
    z_new = np.where(on_shelf, z_new, np.maximum(z_new, elevation[touched]))

    coast_sources = np.unique(source[seeds])
    logger.info(
        "  Continental shelf: %d shelf + %d slope cells; %d of %d coast cells with a shelf "
        "(median width %.0f km), break=%.0f m",
        int(on_shelf.sum()),
        int((~on_shelf).sum()),
        int((width[coast_sources] > 0).sum()),
        coast_sources.size,
        float(np.median(width[coast_sources][width[coast_sources] > 0]))
        if (width[coast_sources] > 0).any()
        else 0.0,
        shelf_break,
    )
    return touched, z_new


def _apply_coastal_plain(
    mesh: CVTMesh,
    elevation: np.ndarray,
    config: TerrainPipelineConfig,
    rng: np.random.Generator,
    *,
    source_fields: dict[str, np.ndarray] | None = None,
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
    a smooth land→coast→shelf→deep ocean transition.  Oceanic cells
    raised above sea level at the continental margin (the subducting
    side of an O-C subduction, physically a trench) are smoothed too,
    so the subducting plate does not turn into a coastal mountain range.

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

    # Minimum coastal strip: at least ~3 cells wide for steep tectonic coasts,
    # so the main-arc relief (4000–6000 m) sits 2–3 cells inland rather than
    # dropping straight into the sea (Andes: main arc 100–200 km from the
    # trench, coastal range/plain in the first ~50 km).
    cell_km = np.sqrt(4.0 * np.pi * config.radius_km**2 / n)
    min_strip_km = min(150.0, max(cell_km * 3.0, plain_width * 0.2))
    max_bfs_width = max(plain_width, min_strip_km)

    # 1. Identify coastline cells: any land cell (elevation above sea level)
    #    with an ocean neighbour.  Applied uniformly to every crust type — an
    #    oceanic cell raised above sea level at a subduction margin is an O-C
    #    artifact and is smoothed exactly like a continental coastal mountain.
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

    # 2. Geodesic BFS inland from coastline.
    inland_dist = geodesic_bfs(
        mesh,
        coastline,
        config.radius_km,
        max_dist_km=max_bfs_width,
        can_expand=lambda nid: elevation[nid] > sea_level,
    )

    # 3. Variable-width coastal plain with elevation-dependent blend target.
    #    Low-lying cells blend toward ~30 m (classic coastal plain).
    #    High-elevation cells (coastal mountains) blend toward ~40% of their
    #    original elevation — creating a narrow but not-flat transition
    #    (cf. Chilean Cordillera de la Costa, ~2000–3000 m at the coast).
    max_plain_elev = config.coastal_plain_max_elevation_m  # 500 m default
    # Coastal strip target for steep tectonic coasts: ~15% of the inland
    # relief ≈ 500–900 m — the coastal range/plain (Chilean Cordillera de la
    # Costa ~500–1500 m), not the 4000–6000 m main arc.
    mountain_coast_ratio = 0.15
    # Lowland targets addressed by cell id (see the shelf note above).
    lowland_targets = sea_level + rng.uniform(10.0, 50.0, size=len(mesh.cells))
    source_blend = np.ones(n) if source_fields is not None else None
    if source_fields is not None:
        from .terrain_source_export import capture_source_field

        capture_source_field(source_fields, "coastal_lowland_target_m", lowland_targets)

    for cid, d_km in inland_dist.items():
        if elevation[cid] <= sea_level:
            continue

        elev_above_sea = elevation[cid] - sea_level

        # Elevation factor: 1.0 at sea level → 0.0 at max_plain_elev+
        elev_factor = max(0.0, 1.0 - elev_above_sea / max_plain_elev)

        # Coast elevation target: ~30 m above sea for lowlands, 40% of
        # original for mountains
        lowland_target = lowland_targets[cid]
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
        if source_blend is not None:
            source_blend[cid] = blend
        elevation[cid] = max(
            lowland_target,
            elevation[cid] * blend + coast_target * (1.0 - blend),
        )

    if source_blend is not None:
        capture_source_field(source_fields, "coastal_plain_blend_fraction", source_blend)

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
    subducting: np.ndarray | None = None,
) -> np.ndarray:
    """Island arc uplift at O-O convergent boundaries.

    At oceanic-oceanic subduction zones, a volcanic arc forms on the
    overriding plate, ~100–300 km from the trench.  This creates chains
    of islands like Japan, the Aleutians, and the Marianas.  With ``subducting``
    (the down-going side from ``trench_flexure``) those cells get no arc.

    Modifies *elevation* in-place.

    References:
      Stern, R.J. (2002). "Subduction zones." *Reviews of Geophysics*, 40(4).
      — island arc formation at O-O convergent margins, arc-trench gap.
    """
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

    # Geodesic BFS from arc boundary cells: arc is ~1-2 cells wide on the
    # overriding side (arc-trench gap + arc width).
    arc_width_km = 200.0
    arc_affected = geodesic_bfs(mesh, arc_cells, config.radius_km, max_dist_km=arc_width_km)

    # Gaussian arc uplift: peak at ~150 km from trench
    sigma = arc_width_km * 0.4
    peak_dist = arc_width_km * 0.35
    arc_count = 0

    damp = _anchor_uplift_damping(geography_bias, len(elevation))
    mod = uplift_mod if uplift_mod is not None else np.ones(len(elevation), dtype=np.float64)
    for cid, d_km in arc_affected.items():
        weight = np.exp(-((d_km - peak_dist) ** 2) / (2 * sigma * sigma))
        dz = arc_height * weight * damp[cid] * mod[cid]
        # Only uplift cells that are oceanic (don't push continental crust)
        if subducting is not None and subducting[cid]:
            continue
        if getattr(mesh.cells[cid], "crust_type", "") != "continental":
            elevation[cid] += dz
            arc_count += 1
    logger.info(
        "  Island arcs: %d boundary cells → %d arc cells (height=%.0f m)",
        len(arc_cells),
        arc_count,
        arc_height,
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
