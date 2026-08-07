"""Tectonic plate time evolution — Cortial et al. (2019) §4–5.

Implements the full procedural tectonic simulation from
*Cortial, Y., Peytavie, A., Galin, E., & Guérin, E. (2019).
Procedural Tectonic Planets. Computer Graphics Forum, 38(2), 1–11.*
https://doi.org/10.1111/cgf.13614

Algorithm: centroid rotation + re-Voronoi (Cortial 2019 original)
-----------------------------------------------------------------
Each time step:
    1. Rotate plate centroids around their Euler poles (Rodrigues).
    2. Find nearest CVT cells → new seeds.
    3. Re-run spherical Voronoi partition → shifted boundaries.
    4. Apply subduction uplift (§4.1) + collision orogeny (§4.2)
       at convergent cells (those that changed plate).
    5. Apply ridge profile (§4.3) at divergent cells.
    6. Apply erosion / subsidence (§5) globally.

Time-step auto-scaling
----------------------
The time step δt is automatically scaled so that the fastest plate
moves ~3 CVT cells per step, regardless of mesh resolution:
    δt = 3 · √(4πR²/N) / v_max_km_My
At 4K cells δt ≈ 10 My; at 100K cells δt ≈ 2 My.
Set ``tectonic_dt_my`` explicitly to override.

All constants from Cortial et al. 2019 Table 1 (see Appendix D.7).
"""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING, Any

import numpy as np

from .models import CVTMesh, EulerPole, TectonicPlate

if TYPE_CHECKING:
    from collections.abc import Callable

    from .pipeline_types import TerrainPipelineConfig

logger = logging.getLogger(__name__)

# =============================================================================
# Cortial et al. (2019) Table 1 — physical constants
# =============================================================================

# Reference values
_RADIUS_KM = 6370.0
_V0_MM_YR = 100.0  # v₀ — max plate speed (mm/yr)
_Z_C_KM = 10.0  # z_c — max continental elevation (km)
_Z_T_KM = -10.0  # z_t — trench depth (km)
_Z_A_KM = -6.0  # z_a — abyssal plain (km)
_Z_R_KM = -1.0  # z_r — max ridge elevation (km)

# Subduction (§4.1)
_U0_MM_YR = 0.6  # u₀ — reference uplift rate (mm/yr)
_R_S_KM = 1800.0  # r_s — subduction influence radius (km)

# Collision (§4.2)
_R_C_KM = 4200.0  # r_c — collision influence radius (km)
_DELTA_C_PER_KM = 1.3e-5  # Δ_c — collision coefficient (km⁻¹)

# Erosion (§5)
_EPSILON_C_MM_YR = 0.03  # ε_c — continental erosion (mm/yr)
_EPSILON_O_MM_YR = 0.04  # ε_o — oceanic subsidence (mm/yr)
_EPSILON_T_MM_YR = 0.3  # ε_t — trench sedimentation (mm/yr)

# =============================================================================
# Helpers
# =============================================================================


def _smooth_step(x: float) -> float:
    """Hermite smoothstep: [0,1] → [0,1]."""
    t = max(0.0, min(1.0, x))
    return t * t * (3.0 - 2.0 * t)


def _bfs_distance(
    mesh: CVTMesh,
    sources: set[int],
    max_dist_km: float,
    cell_radius_km: float,
) -> dict[int, float]:
    """BFS graph-distance (km) from *sources*, clamped to *max_dist_km*."""
    from collections import deque

    dist: dict[int, float] = {}
    q: deque[int] = deque()
    for cid in sources:
        dist[cid] = 0.0
        q.append(cid)

    step_km = cell_radius_km * 2.0  # approximate cell-to-cell distance
    while q:
        cid = q.popleft()
        d = dist[cid]
        if d >= max_dist_km:
            continue
        for nid in mesh.cells[cid].neighbors:
            if nid not in dist:
                nd = d + step_km
                dist[nid] = nd
                if nd < max_dist_km:
                    q.append(nid)
    return dist


def _plate_velocity_cm_yr(
    plate: TectonicPlate,
    pos: np.ndarray,
    radius_km: float,
) -> np.ndarray:
    """Compute plate surface velocity (cm/yr) at position *pos* (unit vector).

    v = ω × pos · R   (Cortial 2019 eq. for geodetic movement)
    """
    ep = plate.euler_pole
    axis = np.array([ep.x, ep.y, ep.z])
    omega_rad_yr = ep.omega_rad_yr
    # v in cm/yr = ω (rad/yr) × pos · radius_cm
    radius_cm = radius_km * 1e5
    return np.cross(axis, pos) * omega_rad_yr * radius_cm


# =============================================================================
# Per-step elevation effects
# =============================================================================


def _subduction_uplift(
    mesh: CVTMesh,
    cell_plate_map: dict[int, str],
    plates: list[TectonicPlate],
    radius_km: float,
    dt_my: float,
    convergent_set: set[int],
    elev_m: np.ndarray,
) -> float:
    """Cortial 2019 §4.1 — uplift at convergent boundaries.

    uⱼ(p) = u₀ · f(d) · g(v) · (1 + h(z̃)) · δt

    Note: the oceanward trench itself is carved during terrain synthesis
    (``terrain_synthesizer._asymmetric_boundary_effects``), which is the stage
    that sets final elevations.

    Returns total uplift applied (km, summed over all cells).
    """
    if not convergent_set:
        return 0.0

    cell_km = np.sqrt(4.0 * np.pi * radius_km**2 / mesh.num_cells)
    dist = _bfs_distance(mesh, convergent_set, _R_S_KM, cell_km)
    dt_yr = dt_my * 1e6
    u0_km_yr = _U0_MM_YR * 1e-6

    plate_dict = {p.id: p for p in plates}
    total_km = 0.0

    for cid, d_km in dist.items():
        pid = cell_plate_map.get(cid, "")
        plate = plate_dict.get(pid)
        if plate is None:
            continue

        # f(d) — cubic falloff
        f_d = 1.0 - _smooth_step(d_km / _R_S_KM)

        # g(v) — normalised speed
        v_cm_yr = plate.euler_pole.omega_rad_yr * radius_km * 1e5
        g_v = max(0.1, min(1.0, v_cm_yr / 10.0))

        # h(z̃) — squared elevation above sea level
        z_km = elev_m[cid] / 1000.0
        z_above = max(0.0, z_km)
        h_z = (z_above / _Z_C_KM) ** 2 if _Z_C_KM > 0 else 0.0

        dz_km = u0_km_yr * f_d * g_v * (1.0 + h_z) * dt_yr
        # Cap: don't push above z_c (10 km) or below z_t (-10 km)
        cur_m = elev_m[cid]
        elev_m[cid] = max(
            _Z_T_KM * 1000.0,
            min(_Z_C_KM * 1000.0, cur_m + dz_km * 1000.0),
        )
        total_km += dz_km

    return total_km


def _collision_orogeny(
    mesh: CVTMesh,
    cell_plate_map: dict[int, str],
    radius_km: float,
    dt_my: float,
    convergent_set: set[int],
    elev_m: np.ndarray,
    crust_arr: np.ndarray,
) -> float:
    """Cortial 2019 §4.2 — continental collision mountain building.

    Δz(p) = Δ_c · A · (1 − d/r_c)⁴

    Only active where BOTH sides of a convergent boundary are continental.
    """
    if not convergent_set:
        return 0.0

    # Find convergent cells with continental crust on both sides
    collision_cells: list[int] = []
    for cid in convergent_set:
        if crust_arr[cid] != "continental":
            continue
        pid = cell_plate_map.get(cid, "")
        for nid in mesh.cells[cid].neighbors:
            npid = cell_plate_map.get(nid, "")
            if npid and npid != pid and crust_arr[nid] == "continental":
                collision_cells.append(cid)
                break

    if not collision_cells:
        return 0.0

    cell_km = np.sqrt(4.0 * np.pi * radius_km**2 / mesh.num_cells)
    dist = _bfs_distance(mesh, set(collision_cells), _R_C_KM, cell_km)
    total_km = 0.0

    for cid, d_km in dist.items():
        d_norm = d_km / _R_C_KM
        weight = (1.0 - d_norm) ** 4
        area_km2 = cell_km**2
        dz_km = _DELTA_C_PER_KM * area_km2 * weight * dt_my / 2.0
        elev_m[cid] += dz_km * 1000.0
        total_km += dz_km

    return total_km


def _ridge_profile(
    mesh: CVTMesh,
    divergent_set: set[int],
    radius_km: float,
) -> None:
    """Cortial 2019 §4.3 — ridge elevation at divergent boundaries.

    z = α · z̄ + (1−α) · z_Γ  (blend toward ridge template)
    """
    if not divergent_set:
        return

    cell_km = np.sqrt(4.0 * np.pi * radius_km**2 / mesh.num_cells)
    dist = _bfs_distance(mesh, divergent_set, 200.0, cell_km)

    for cid, d_km in dist.items():
        alpha = d_km / max(200.0, d_km + 1.0)
        z_cur_km = getattr(mesh.cells[cid], "elevation", 0.0) / 1000.0
        z_ridge_km = _Z_R_KM + (d_km / 200.0) * (_Z_A_KM - _Z_R_KM)
        z_new_km = alpha * z_cur_km + (1.0 - alpha) * z_ridge_km
        mesh.cells[cid].elevation = z_new_km * 1000.0


def _erosion(
    mesh: CVTMesh,
    dt_my: float,
    elev_m: np.ndarray,
    crust_arr: np.ndarray,
) -> None:
    """Cortial 2019 §5 — erosion / subsidence / sedimentation (vectorized)."""
    dt_yr = dt_my * 1e6

    z_km = elev_m / 1000.0
    continental = crust_arr == "continental"
    dz_km = np.where(
        continental,
        (z_km / _Z_C_KM) * _EPSILON_C_MM_YR * 1e-6 * dt_yr,
        (1.0 - z_km / _Z_T_KM) * _EPSILON_O_MM_YR * 1e-6 * dt_yr,
    )
    elev_m -= dz_km * 1000.0

    # Trench sedimentation (deep cells) — judged on pre-erosion depth
    elev_m[z_km < -5.0] += _EPSILON_T_MM_YR * 1e-6 * dt_yr * 1000.0


# =============================================================================
# Boundary classification per step
# =============================================================================


def _classify_step_boundaries(
    mesh: CVTMesh,
    cell_plate_map: dict[int, str],
    plates: list[TectonicPlate],
    radius_km: float,
) -> tuple[set[int], set[int]]:
    """Find convergent and divergent boundary cells from plate velocities.

    For each boundary cell, compute the relative velocity between its
    plate and each neighbour plate.  If plates are converging (moving
    toward each other) → convergent.  If diverging → divergent.

    Returns:
        (convergent_set, divergent_set) — sets of cell IDs.
    """
    plate_dict = {p.id: p for p in plates}
    convergent: set[int] = set()
    divergent: set[int] = set()

    for cid, pid in cell_plate_map.items():
        cell = mesh.cells[cid]
        pos = np.array([cell.x, cell.y, cell.z])

        # Find neighbour plates
        nb_plates: set[str] = set()
        for nid in cell.neighbors:
            npid = cell_plate_map.get(nid, "")
            if npid and npid != pid:
                nb_plates.add(npid)
        if not nb_plates:
            continue

        plate = plate_dict.get(pid)
        if plate is None:
            continue

        v_own = _plate_velocity_cm_yr(plate, pos, radius_km)

        # Compare with each neighbour's velocity
        for npid in nb_plates:
            nplate = plate_dict.get(npid)
            if nplate is None:
                continue
            v_other = _plate_velocity_cm_yr(nplate, pos, radius_km)
            v_rel = v_own - v_other

            # Project relative velocity onto the boundary normal
            # (approximate: normal = toward neighbour plate centroid)
            normal = np.zeros(3)
            for nid in cell.neighbors:
                if cell_plate_map.get(nid, "") == npid:
                    nc = mesh.cells[nid]
                    normal += np.array([nc.x, nc.y, nc.z]) - pos
            norm = np.linalg.norm(normal)
            if norm < 1e-12:
                continue
            normal /= norm

            vn = np.dot(v_rel, normal)  # cm/yr, positive = convergent

            if vn > 0.5:  # Cortial threshold
                convergent.add(cid)
            elif vn < -0.5:
                divergent.add(cid)

    return convergent, divergent


# =============================================================================
# Main loop
# =============================================================================


# ---------------------------------------------------------------------------
# Strategy registry
# ---------------------------------------------------------------------------
#
# Each tectonic algorithm is a callable (mesh, plates, config) → (plates, cell_map).
# Add new algorithms here and reference them by name in ``tectonic_algorithm``.


_TECTONIC_ALGORITHMS: dict[str, str] = {
    "cortial2019": "cortial2019",
}


def run_tectonic_evolution(
    mesh: CVTMesh,
    plates: list[TectonicPlate],
    config: TerrainPipelineConfig,
    *,
    progress_callback: Callable[[int, int], object] | None = None,
) -> tuple[list[TectonicPlate], dict[int, str]]:
    """Run tectonic time evolution (dispatches to configured algorithm).

    Args:
        mesh: CVT mesh (cells modified in-place — elevation).
        plates: Initial tectonic plates with Euler poles.
        config: Pipeline configuration.
        progress_callback: Optional ``(step: int, total: int) -> None``
            callable for progress reporting.

    Returns:
        (plates, cell_plate_map).
    """
    algo = config.tectonic_algorithm
    # Backward compatibility: auto-select if YAML overrides default to ""
    if not algo and config.tectonic_steps > 0:
        algo = "cortial2019"
    if not algo or config.tectonic_steps <= 0:
        # No evolution — reconstruct cell map from plate data
        cell_map: dict[int, str] = {}
        for p in plates:
            for cid in p.cell_ids:
                cell_map[cid] = p.id
        if config.boundary_warp > 0:
            # Weight by current area so the warp preserves the (possibly
            # skewed) size distribution of the initial partition.
            weights = {p.id: float(max(len(p.cell_ids), 1)) for p in plates}
            cell_map = warp_boundaries(mesh, cell_map, config, plate_weights=weights)
            _rebuild_plate_cells(mesh, cell_map, plates)
        return plates, cell_map

    if algo not in _TECTONIC_ALGORITHMS:
        raise ValueError(
            f"Unknown tectonic algorithm '{algo}'. Available: {sorted(_TECTONIC_ALGORITHMS.keys())}"
        )
    if algo == "cortial2019":
        plates_out, cell_map, plate_weight, arc_state = _evolve_cortial2019(
            mesh,
            plates,
            config,
            progress_callback=progress_callback,
        )
        # Noise-warp the FINAL partition (Cortial 2019 §3) — irregular
        # boundaries instead of straight geodesic arcs.  Pass the persistent
        # size weights so the warp doesn't re-uniformise plate areas.
        if config.boundary_warp > 0:
            cell_map = warp_boundaries(mesh, cell_map, config, plate_weights=plate_weight)
        # The warp re-partitions from centroids (geodesic bisectors) and thus
        # re-straightens the trench arcs developed during evolution — re-apply
        # them on the final map before terrain synthesis.
        cell_map = _trench_arc_relaxation(
            mesh,
            cell_map,
            plates_out,
            config.radius_km,
            config.trench_arc,
            arc_state,
            smooth_rng=np.random.default_rng(config.seed + 909),
        )
        cell_map = _smooth_partition(mesh, cell_map)
        cell_map = _merge_plate_enclaves(mesh, cell_map)
        _rebuild_plate_cells(mesh, cell_map, plates_out)
        return plates_out, cell_map
    raise ValueError(f"Tectonic algorithm '{algo}' not implemented")  # unreachable


def _spawn_oceanic_crust(
    mesh: CVTMesh,
    cell_plate_map: dict[int, str],
    plates: list[TectonicPlate],
    config: TerrainPipelineConfig,
    rng: np.random.Generator,
    *,
    step: int,
    plate_birth_step: dict[str, int] | None = None,
) -> tuple[list[TectonicPlate], dict[int, str]]:
    """At divergent boundaries, occasionally spawn small oceanic plates.

    Does NOT modify mesh topology — reassigns existing cells to new plate IDs.
    New plates get a cooldown (recorded in plate_birth_step) to prevent
    immediate re-absorption.  Triggers roughly every 25-40 steps.
    """
    # Trigger every 12-18 steps (roughly twice per 50-step run)
    if step < 5 or step % rng.integers(12, 19) != 0:
        return plates, cell_plate_map

    # Collect boundary cells (neighbor has a different plate ID)
    boundary: list[int] = []
    for cid in range(mesh.num_cells):
        pid = cell_plate_map.get(cid, "")
        if not pid:
            continue
        for nid in mesh.cells[cid].neighbors:
            npid = cell_plate_map.get(nid, "")
            if npid and npid != pid:
                boundary.append(cid)
                break
    if len(boundary) < 5:
        return plates, cell_plate_map

    # Pick a seed and expand a small cluster (~20-50 cells)
    seed = int(rng.choice(boundary))
    new_cells: list[int] = [seed]
    frontier = [seed]
    visited = {seed}
    for _ in range(5):  # 5 layers of BFS → ~80-120 cells (big enough to survive)
        next_frontier: list[int] = []
        for cid in frontier:
            for nid in mesh.cells[cid].neighbors:
                if nid not in visited and len(new_cells) < 120:
                    visited.add(nid)
                    next_frontier.append(nid)
                    new_cells.append(nid)
        frontier = next_frontier
        if not frontier:
            break

    if len(new_cells) < 10:
        return plates, cell_plate_map  # too small

    # Create new plate — inherit Euler pole from current owner with perturbation
    parent_id = cell_plate_map.get(seed, "")
    parent = next((p for p in plates if p.id == parent_id), None)
    if parent is None:
        return plates, cell_plate_map

    # Fresh Euler pole: small perturbation from parent
    ax = rng.standard_normal(3)
    ax /= np.linalg.norm(ax)
    new_pole = EulerPole(
        x=float(ax[0]),
        y=float(ax[1]),
        z=float(ax[2]),
        omega_rad_yr=parent.euler_pole.omega_rad_yr * rng.uniform(0.7, 1.3),
    )

    new_id = f"oceanic_s{step:04d}"
    new_plate = TectonicPlate(
        id=new_id,
        name=f"新生洋壳 t={step}",
        type="oceanic",
        cell_ids=new_cells,
        euler_pole=new_pole,
    )
    plates.append(new_plate)
    if plate_birth_step is not None:
        plate_birth_step[new_id] = step
    for cid in new_cells:
        cell_plate_map[cid] = new_id

    logger.info(
        "  Spawned oceanic crust: %d cells → plate %s at divergent boundary",
        len(new_cells),
        new_id,
    )
    return plates, cell_plate_map


def _rodrigues_rotate(
    xyz: np.ndarray,
    axis: np.ndarray,
    angle_rad: float,
) -> np.ndarray:
    """Rodrigues rotation of a point on the unit sphere."""
    axis = axis / np.linalg.norm(axis)
    cos_a, sin_a = np.cos(angle_rad), np.sin(angle_rad)
    return np.asarray(
        xyz * cos_a + np.cross(axis, xyz) * sin_a + axis * np.dot(axis, xyz) * (1.0 - cos_a)
    )


def _auto_compute_dt(mesh: CVTMesh, config: TerrainPipelineConfig) -> float:
    """Scale δt so the fastest plate moves ~3 cells per step.

    δt = 3 · cell_size_km / v_max_km_My
    where cell_size_km = √(4πR² / N), v_max = 10 cm/yr = 100 km/My.
    """
    if config.tectonic_dt_my > 0.0:
        return config.tectonic_dt_my  # user override

    cell_km = np.sqrt(4.0 * np.pi * config.radius_km**2 / mesh.num_cells)
    v_max_km_my = 100.0  # 10 cm/yr → 100 km/My
    dt_my = 3.0 * cell_km / v_max_km_my
    return float(max(1.0, dt_my))


def _plate_speeds(
    plate_ids: list[str],
    plate_weight: dict[str, float],
    fallback_areas: list[int] | None = None,
) -> np.ndarray:
    """Per-plate expansion speed for the weighted re-partition.

    Speed = the persistent size weight normalised to mean 1 (only ratios
    matter).  A plate missing a weight — should not happen, the roster is
    reconciled after every rift/cleanup — falls back to its current area.
    """
    w = np.array(
        [
            max(
                plate_weight.get(
                    pid,
                    float(max(fallback_areas[i], 1)) if fallback_areas else 1.0,
                ),
                1.0,
            )
            for i, pid in enumerate(plate_ids)
        ],
        dtype=np.float64,
    )
    mean = float(w.mean())
    return w / mean if mean > 0 else w


def _evolve_cortial2019(
    mesh: CVTMesh,
    plates: list[TectonicPlate],
    config: TerrainPipelineConfig,
    *,
    progress_callback: Callable[[int, int], object] | None = None,
) -> tuple[list[TectonicPlate], dict[int, str], dict[str, float], dict[tuple[str, str], float]]:
    """Cortial et al. (2019) original — centroid rotation + re-Voronoi.

    Each step: rotate plate centroids → Voronoi → boundaries shift → elevation.

    Returns ``(plates, cell_plate_map, plate_weight, arc_state)``.
    ``plate_weight`` maps plate id → persistent size weight (area at birth,
    arbitrary scale): the re-partition uses it as a multiplicatively-weighted
    Voronoi so the skewed size distribution survives the Lloyd-style iteration
    instead of relaxing to near-equal areas (see ``voronoi_partition_warped``).
    ``arc_state`` carries the developed trench-arc sagittae so the final
    boundary warp can re-apply the arcs it re-straightens.
    """
    from .plate_generator import voronoi_partition_warped

    num_steps = config.tectonic_steps
    dt_my = _auto_compute_dt(mesh, config)
    radius_km = config.radius_km
    rng = np.random.default_rng(config.seed)
    logger.info(
        "Tectonic evolution: seed=%d, steps=%d, rift_rate=%.4f",
        config.seed,
        num_steps,
        config.rift_base_rate,
    )

    # Initial cell→plate map
    cell_plate_map: dict[int, str] = {}
    for p in plates:
        for cid in p.cell_ids:
            cell_plate_map[cid] = p.id

    # Persistent per-plate size weights — area at birth.  The re-partition
    # divides space proportionally to these (multiplicatively weighted
    # Voronoi), so the birth-time size skew survives the Lloyd-style
    # centroid→Voronoi iteration instead of relaxing toward equal areas.
    plate_weight: dict[str, float] = {p.id: float(max(len(p.cell_ids), 1)) for p in plates}
    # Developed trench-arc sagitta per (subducting, overriding) pair.
    arc_state: dict[tuple[str, str], float] = {}

    if num_steps <= 0:
        return plates, cell_plate_map, plate_weight, arc_state

    # Stage 1.2: canonical elevation/crust arrays for the whole evolution
    # (written back to cells once at the end) + cKDTree for nearest-cell
    # queries (was O(n) Python dot products per plate per step).
    from scipy.spatial import cKDTree

    _n = mesh.num_cells
    _cell_xyz = np.array([[c.x, c.y, c.z] for c in mesh.cells], dtype=np.float64)
    _tree = cKDTree(_cell_xyz)
    elev_m = np.array([c.elevation for c in mesh.cells], dtype=np.float64)
    crust_arr = np.array([c.crust_type for c in mesh.cells])

    logger.info(
        "Tectonic evolution: %d steps × %.1f My = %.0f My total "
        "(cell ~%.0f km, δt auto-scaled to move ~3 cells/step)",
        num_steps,
        dt_my,
        num_steps * dt_my,
        np.sqrt(4.0 * np.pi * radius_km**2 / mesh.num_cells),
    )

    prev_cell_map = cell_plate_map
    plate_birth_step: dict[str, int] = {p.id: 0 for p in plates}
    cooldown = max(1, num_steps // 20)  # ~5% of total run
    unit_cost = np.ones(mesh.num_cells, dtype=np.float64)
    # Re-partition the Voronoi every resample_every steps (so boundaries track
    # the moving centroids), and once immediately after a rifting event so
    # newborn fragments get a clean partition.  Between resamples cell
    # ownership is stable (Cortial 2019 strategy).
    resample_every = 10
    last_resample_step = -resample_every  # triggers a resample at step 0
    rifted_since_last_resample = False

    for step in range(num_steps):
        # 1. Rotate centroids → find new seeds (Stage 1.2: batched cKDTree
        #    query; was 20 plates × O(n) Python dot products per step)
        rotated_centroids: list[np.ndarray] = []
        for plate in plates:
            ep = plate.euler_pole
            axis = np.array([ep.x, ep.y, ep.z])
            omega = ep.omega_rad_yr
            angle_rad = omega * dt_my * 1e6

            # Current centroid
            cids = plate.cell_ids
            if cids:
                cx = np.mean([mesh.cells[c].x for c in cids])
                cy = np.mean([mesh.cells[c].y for c in cids])
                cz = np.mean([mesh.cells[c].z for c in cids])
                centroid = np.array([cx, cy, cz])
                centroid /= np.linalg.norm(centroid)
            else:
                centroid = np.array([1.0, 0.0, 0.0])  # fallback

            rotated_centroids.append(_rodrigues_rotate(centroid, axis, angle_rad))
        # Distinct seeds — duplicate seeds (two centroids rounding to the
        # same cell) make a plate lose all its cells and get removed by
        # _cleanup_empty (the artificial plate-count collapse).
        new_seeds = _assign_distinct_seeds(_tree, rotated_centroids) if rotated_centroids else []

        # 2. Re-run Voronoi (every N steps, or right after a rift)
        # Protect newborn plates: lock their cells so they survive long enough to grow
        needs_resample = step - last_resample_step >= resample_every or rifted_since_last_resample
        if needs_resample:
            locked: dict[int, str] = {}
            newborn_cooldown = cooldown * 5  # ~25 steps — give oceanic plates time to grow
            newborn_pids = [
                pid
                for pid, birth in plate_birth_step.items()
                if pid.startswith("oceanic") and step - birth < newborn_cooldown
            ]
            if newborn_pids:
                # Stage 1.2: one O(n) coding pass + np.where per newborn plate
                # (was an O(n) full scan PER newborn plate)
                pid_code: dict[str, int] = {}
                cur_codes = np.empty(_n, dtype=np.int64)
                for i in range(_n):
                    pid = cell_plate_map.get(i, "")
                    code = pid_code.get(pid)
                    if code is None:
                        code = pid_code[pid] = len(pid_code)
                    cur_codes[i] = code
                for pid in newborn_pids:
                    code = pid_code.get(pid)
                    if code is not None:
                        for cid in np.where(cur_codes == code)[0].tolist():
                            locked[cid] = pid
            if locked:
                logger.info(
                    "  Voronoi: %d cells locked for %d oceanic newborn(s)",
                    len(locked),
                    len({v for v in locked.values()}),
                )
            # Pass the real plate ids (new_seeds[i] ↔ plates[i]) so rifted
            # plates keep their identity; index-based naming would orphan cells.
            # Weighted by persistent plate size: unit-speed (plain) Voronoi of
            # moving centroids is Lloyd iteration and relaxes sizes toward
            # equal; speeds ∝ birth area pin the skewed distribution.
            new_cell_map = voronoi_partition_warped(
                mesh,
                new_seeds,
                [p.id for p in plates],
                unit_cost,
                plate_speed=_plate_speeds(
                    [p.id for p in plates],
                    plate_weight,
                    [len(p.cell_ids) for p in plates],
                ),
                locked=locked,
            )
            # Frank (1968) trench arcs: the Voronoi bisector above is a
            # geodesic; relax convergent oceanic boundaries toward the
            # small-circle arc implied by the current kinematics so arcs
            # develop over the evolution.
            new_cell_map = _trench_arc_relaxation(
                mesh,
                new_cell_map,
                plates,
                radius_km,
                config.trench_arc,
                arc_state,
                locked=locked,
            )
            last_resample_step = step
            rifted_since_last_resample = False
        else:
            new_cell_map = prev_cell_map

        # 3. Detect changed cells → convergent set (Stage 1.2: vectorized;
        #    identical maps between resamples skip the scan entirely)
        if needs_resample:
            all_pids: dict[str, int] = {}

            def _codes(m: dict[int, str], codes_out: dict[str, int]) -> np.ndarray:
                arr = np.empty(_n, dtype=np.int64)
                for i in range(_n):
                    pid = m.get(i, "")
                    code = codes_out.get(pid)
                    if code is None:
                        code = codes_out[pid] = len(codes_out)
                    arr[i] = code
                return arr

            changed_mask = _codes(prev_cell_map, all_pids) != _codes(new_cell_map, all_pids)
            n_changed = int(changed_mask.sum())
            # Treat all changed cells as convergent for now
            # (proper divergence detection would track which plate lost cells)
            convergent = set(np.where(changed_mask)[0].tolist())
        else:
            n_changed = 0
            convergent = set()

        # 4. Apply elevation effects (array-backed, Stage 1.2)
        _subduction_uplift(
            mesh,
            new_cell_map,
            plates,
            radius_km,
            dt_my,
            convergent,
            elev_m,
        )
        _collision_orogeny(
            mesh,
            new_cell_map,
            radius_km,
            dt_my,
            convergent,
            elev_m,
            crust_arr,
        )
        _erosion(mesh, dt_my, elev_m, crust_arr)

        # 5. Plate rifting + cleanup orphan cells
        n_before = len(plates)
        plates, new_cell_map = _rift_plates(
            mesh,
            new_cell_map,
            plates,
            config,
            rng,
            step=step,
            plate_birth_step=plate_birth_step,
        )
        if len(plates) != n_before:
            rifted_since_last_resample = True
        # Remove plates that ended up with 0 cells (Voronoi consolidation)
        plates, new_cell_map = _cleanup_empty(
            mesh,
            new_cell_map,
            plates,
            step=step,
            plate_birth_step=plate_birth_step,
            cooldown=cooldown,
        )

        # Keep size weights in sync with the plate roster: removed plates
        # drop their weight; newborn fragments get their BIRTH area (the rift
        # partition's weighted Dijkstra already made them unequal-sized).
        alive = {p.id for p in plates}
        for pid in [k for k in plate_weight if k not in alive]:
            del plate_weight[pid]
        for p in plates:
            if p.id not in plate_weight:
                plate_weight[p.id] = float(max(len(p.cell_ids), 1))

        # 6. Update for next step
        prev_cell_map = new_cell_map
        _rebuild_plate_cells(mesh, new_cell_map, plates)

        if progress_callback is not None:
            # A faulty progress callback must never kill the simulation
            with contextlib.suppress(Exception):
                progress_callback(step + 1, num_steps)
        elif step % 10 == 0 or step == num_steps - 1:
            logger.info(
                "  Step %3d/%d: %d cells changed plate",
                step + 1,
                num_steps,
                n_changed,
            )

    # Finalise — write the canonical elevation array back to cells once
    for i, c in enumerate(mesh.cells):
        c.elevation = float(elev_m[i])
    logger.info(
        "Tectonic evolution complete: %d steps, %d plates, %d cells",
        num_steps,
        len(plates),
        mesh.num_cells,
    )
    return plates, prev_cell_map, plate_weight, arc_state


def _rift_plates(
    mesh: CVTMesh,
    cell_plate_map: dict[int, str],
    plates: list[TectonicPlate],
    config: TerrainPipelineConfig,
    rng: np.random.Generator,
    *,
    step: int = 0,
    plate_birth_step: dict[str, int] | None = None,
) -> tuple[list[TectonicPlate], dict[int, str]]:
    """Cortial 2019 §4.4 — probabilistic plate rifting.

    Larger plates are more likely to rift.  Cooldown prevents immediate
    re-rifting of fragments.  Cells are refreshed from the current map
    before partitioning to account for Voronoi boundary shifts.

    Returns updated (plates, cell_plate_map).
    """
    if config.rift_base_rate <= 0 or len(plates) < 2:
        return plates, cell_plate_map

    lambda_0 = config.rift_base_rate
    min_pieces = config.rift_min_pieces
    max_pieces = config.rift_max_pieces

    total_cells = mesh.num_cells
    cooldown = 5  # steps before a new plate can rift again
    # Refresh cell counts from current map (Voronoi may have shifted boundaries)
    for plate in plates:
        plate.cell_ids = [cid for cid, pid in cell_plate_map.items() if pid == plate.id]
    plate_areas = {p.id: len(p.cell_ids) for p in plates}
    avg_cells = total_cells / len(plates)

    for plate in list(plates):  # iterate a copy because we may mutate
        n_cells = plate_areas[plate.id]
        if n_cells < avg_cells * 0.5:
            continue  # too small to rift (half the average size)

        # Cooldown: normal plates must wait; super-plates (>2× avg) skip cooldown.
        # Gondwana broke into 7 fragments over 4 phases in ~140 My — large plates
        # rift repeatedly until they reach a stable size.
        if plate_birth_step is not None:
            birth = plate_birth_step.get(plate.id, -cooldown)
            if step - birth < cooldown and n_cells <= avg_cells * 2:
                continue  # only small/normal plates respect cooldown

        # Super-plate boost: larger plates rift more often.
        # Capped at 3× to prevent runaway fragmentation.
        lam = lambda_0 * n_cells / avg_cells
        if n_cells > avg_cells * 2:
            boost = min(3.0, n_cells / avg_cells - 1.0)
            lam *= boost
        elif n_cells > avg_cells * 1.5:
            lam *= 1.3
        if lam < 0.001:
            continue
        r = rng.random()
        if r >= lam:
            continue

        n_pieces = rng.integers(min_pieces, max_pieces + 1)
        logger.info(
            "  Rifting plate %s (%d cells, λ=%.3f, r=%.4f) → %d pieces",
            plate.name,
            n_cells,
            lam,
            r,
            n_pieces,
        )

        # Pick n_pieces random seed cells from the plate
        seed_ids = list(
            rng.choice(  # type: ignore[call-overload]
                np.asarray(plate.cell_ids), size=min(n_pieces, n_cells), replace=False
            )
        )
        # BFS from each seed to partition the plate's cells
        new_ids = _partition_cells(mesh, plate.cell_ids, seed_ids, rng)
        # Filter out empty partitions (can happen with edge-positioned seeds)
        new_ids = [g for g in new_ids if g]

        if len(new_ids) < 2:
            continue  # not enough non-empty pieces to split

        # Remove old plate, add new sub-plates
        plates.remove(plate)
        if plate_birth_step is not None:
            plate_birth_step.pop(plate.id, None)
        old_id = plate.id
        added = 0
        assigned_total = 0
        for i, new_id in enumerate(new_ids):
            if not new_id:
                continue  # skip empty partitions
            sub_name = f"{plate.name}_{chr(65 + i)}"
            sub_id = f"{old_id}_{chr(97 + i)}"
            # Perturb Euler pole so fragments have distinct motion.
            # Mild rotation (±10-20°) + ω variation (±15%) gives ~2-5 cm/yr
            # relative motion between adjacent fragments — detectable by the
            # boundary classifier (threshold 0.5 cm/yr) without causing the
            # sub-plates to drift so fast that Voronoi reassigns all their cells.
            perturb_axis = rng.standard_normal(3)
            perturb_axis /= np.linalg.norm(perturb_axis)
            angle_rad = rng.uniform(0.15, 0.35)  # ~10-20°
            parent_axis = np.array([plate.euler_pole.x, plate.euler_pole.y, plate.euler_pole.z])
            new_axis = parent_axis * np.cos(angle_rad) + np.cross(
                perturb_axis, parent_axis
            ) * np.sin(angle_rad)
            new_axis /= np.linalg.norm(new_axis)
            new_pole = EulerPole(
                x=float(new_axis[0]),
                y=float(new_axis[1]),
                z=float(new_axis[2]),
                omega_rad_yr=plate.euler_pole.omega_rad_yr * rng.uniform(0.85, 1.15),
            )
            sub_plate = TectonicPlate(
                id=sub_id,
                name=sub_name,
                type=plate.type,
                cell_ids=new_id,
                euler_pole=new_pole,
                growth_speed_multiplier=plate.growth_speed_multiplier,
            )
            plates.append(sub_plate)
            if plate_birth_step is not None:
                plate_birth_step[sub_id] = step
            for cid in new_id:
                cell_plate_map[cid] = sub_id
            added += 1
            assigned_total += len(new_id)
        # Safety: if total assigned != parent cells, revert the rift
        if assigned_total != n_cells:
            logger.warning(
                "  Rift partition lost cells: %d assigned, %d expected — reverting",
                assigned_total,
                n_cells,
            )
            # Restore parent plate (without the incomplete sub-plates)
            for _ in range(added):
                plates.pop()
            plate.cell_ids = list(plate.cell_ids)  # ensure mutable
            plates.append(plate)
            if plate_birth_step is not None:
                plate_birth_step[plate.id] = -cooldown  # don't try again soon
            for cid in plate.cell_ids:
                cell_plate_map[cid] = plate.id
            continue

    return plates, cell_plate_map


def _partition_cells(
    mesh: CVTMesh,
    plate_cells: list[int],
    seeds: list[int],
    rng: np.random.Generator,
) -> list[list[int]]:
    """Partition *plate_cells* into *len(seeds)* groups via weighted multi-source
    Dijkstra.

    Each seed expands with a random per-seed growth weight, so fragments come out
    **unequal-sized** (one or two large fragments plus smaller ones) instead of the
    near-equal regions a uniform synchronous BFS produces.  Repeated rifting of the
    large fragments then yields a skewed, power-law-like plate-size distribution
    closer to Earth's (a few great plates + many small plates), rather than the
    uniform sizes a plain Voronoi partition gives.
    """
    import heapq

    cell_set = set(plate_cells)
    n_seeds = len(seeds)
    # Per-seed growth weight: a seed with a larger weight claims cells faster and
    # thus a larger fragment.  Log-uniform spread gives a wide size range.
    weights = [float(np.exp(rng.uniform(-0.9, 0.9))) for _ in range(n_seeds)]

    dist: dict[int, float] = {}
    owner: dict[int, int] = {}
    heap: list[tuple[float, int, int]] = []
    for i, s in enumerate(seeds):
        dist[s] = 0.0
        owner[s] = i
        heapq.heappush(heap, (0.0, s, i))

    while heap:
        d, cid, i = heapq.heappop(heap)
        if d > dist.get(cid, float("inf")):
            continue  # stale heap entry
        step_cost = 1.0 / weights[i]
        for nid in mesh.cells[cid].neighbors:
            if nid in cell_set and nid not in dist:
                dist[nid] = d + step_cost
                owner[nid] = i
                heapq.heappush(heap, (dist[nid], nid, i))

    # Stranded cells (disconnected) — assign to the first seed as a fallback.
    for cid in plate_cells:
        if cid not in owner:
            owner[cid] = 0

    result: list[list[int]] = [[] for _ in seeds]
    for cid, idx in owner.items():
        result[idx].append(cid)
    return result


def _cleanup_empty(
    mesh: CVTMesh,
    cell_plate_map: dict[int, str],
    plates: list[TectonicPlate],
    *,
    absorb: bool = False,
    cooldown: int = 5,
    step: int = 0,
    plate_birth_step: dict[str, int] | None = None,
) -> tuple[list[TectonicPlate], dict[int, str]]:
    """Remove plates with 0 cells; optionally absorb very tiny plates into neighbours.

    Threshold: < 0.15% of surface (~0.75 M km² for Earth).  This is half the
    size of the smallest recognised plate (Scotia: ~1.6 M km² = 0.31%).
    """
    if len(plates) <= 2:
        return plates, cell_plate_map

    removed = 0
    absorbed = 0
    tiny_threshold = max(1, int(mesh.num_cells * 0.0015))

    for plate in list(plates):
        if len(plates) <= 2:
            break  # never go below 2 plates
        n_cells = len(plate.cell_ids)
        # Newborn oceanic plates get double cooldown protection
        if plate_birth_step is not None and plate.id.startswith("oceanic"):
            birth = plate_birth_step.get(plate.id, 0)
            if step - birth < cooldown * 2:
                continue
        if n_cells == 0:
            plates.remove(plate)
            removed += 1
            continue

        if not absorb or n_cells >= tiny_threshold:
            continue

        # Absorb tiny plate into a neighbour
        neighbour_counts: dict[str, int] = {}
        for cid in plate.cell_ids:
            for nid in mesh.cells[cid].neighbors:
                npid = cell_plate_map.get(nid, "")
                if npid and npid != plate.id:
                    neighbour_counts[npid] = neighbour_counts.get(npid, 0) + 1
        if neighbour_counts:
            target = max(neighbour_counts, key=lambda k: neighbour_counts[k])
            for cid in plate.cell_ids:
                cell_plate_map[cid] = target
            plates.remove(plate)
            absorbed += 1

    if removed or absorbed:
        logger.debug("  Cleanup: %d empty removed, %d tiny absorbed", removed, absorbed)
    return plates, cell_plate_map


def _consume_small_plates(
    mesh: CVTMesh,
    cell_plate_map: dict[int, str],
    plates: list[TectonicPlate],
    config: TerrainPipelineConfig,
    *,
    step: int = 0,
    plate_birth_step: dict[str, int] | None = None,
    cooldown: int = 1,
) -> tuple[list[TectonicPlate], dict[int, str]]:
    """Absorb very small plates into neighbours — subduction-completion balance.

    When an oceanic plate is almost fully subducted, its remaining cells are
    reassigned to the adjacent plate with the longest shared boundary.
    This prevents runaway fragmentation from the rifting step.

    Threshold: plates with < 3% of the world surface area (~15 M km² for Earth).
    Real-world examples: the Farallon plate was ~100 M km² then shrank to the
    tiny Juan de Fuca (~0.25 M km²) and Cocos (~2.9 M km²) remnants.
    """
    if len(plates) <= 2:
        return plates, cell_plate_map  # never reduce below 2 plates

    total_cells = mesh.num_cells
    # Hard floor: plates below ~0.3% of surface (~1.5 M km² for Earth)
    # are consumed.  This is roughly the Scotia plate (1.6 M km²) —
    # the smallest recognised tectonic plate on Earth.
    # No auto-balance scaling: this threshold is invariant.
    hard_min_cells = 50  # absolute floor: never consume plates with >50 cells
    min_cells = max(hard_min_cells, int(total_cells * 0.003))

    plate_dict = {p.id: p for p in plates}

    # Phase 1: absorb plates that are too small
    active_ids = {p.id for p in plates}
    for plate in list(plates):
        n_cells = len(plate.cell_ids)
        if n_cells >= min_cells:
            continue
        # Cooldown: skip newly created plates
        if plate_birth_step is not None and cooldown > 0:
            birth = plate_birth_step.get(plate.id, 0)
            if birth + cooldown > step:
                continue

        # Build neighbour-count map (only count neighbours that still exist)
        neighbour_counts: dict[str, int] = {}
        for cid in plate.cell_ids:
            for nid in mesh.cells[cid].neighbors:
                npid = cell_plate_map.get(nid, "")
                if npid and npid != plate.id and npid in active_ids:
                    neighbour_counts[npid] = neighbour_counts.get(npid, 0) + 1

        if not neighbour_counts:
            continue  # isolated plate — keep it

        target_id = max(neighbour_counts, key=lambda k: neighbour_counts[k])
        logger.info(
            "  Absorbing %s (%d cells, %.1f%%) → %s",
            plate.name,
            n_cells,
            n_cells / total_cells * 100,
            plate_dict[target_id].name if target_id in plate_dict else target_id,
        )

        # Reassign cells
        for cid in plate.cell_ids:
            cell_plate_map[cid] = target_id
        plates.remove(plate)
        active_ids.discard(plate.id)

    # Phase 2: Re-parent orphan cells (assigned to a removed plate id).
    # This happens when an absorbed plate's target was itself later absorbed.
    # Run multiple passes until stable (chain absorption).
    for _pass in range(5):
        current_ids = {p.id for p in plates}
        orphan_count = 0
        for cid, pid in list(cell_plate_map.items()):
            if pid not in current_ids:
                # Find nearest surviving plate via neighbor BFS
                for nid in mesh.cells[cid].neighbors:
                    npid = cell_plate_map.get(nid, "")
                    if npid and npid in current_ids:
                        cell_plate_map[cid] = npid
                        orphan_count += 1
                        break
                else:
                    # No surviving neighbor found — assign to first surviving plate
                    if current_ids:
                        cell_plate_map[cid] = next(iter(current_ids))
                        orphan_count += 1
        if orphan_count:
            logger.info(
                "  Consumed: re-parented %d orphan cells (pass %d)", orphan_count, _pass + 1
            )
        else:
            break

    # Phase 3: Remove plates that ended up with 0 cells
    for plate in list(plates):
        if len(plate.cell_ids) == 0:
            plates.remove(plate)

    return plates, cell_plate_map


def _rebuild_plate_cells(
    mesh: CVTMesh,
    cell_plate_map: dict[int, str],
    plates: list[TectonicPlate],
) -> None:
    """Rebuild each plate's cell list from the current cell→plate map."""
    plate_cells: dict[str, list[int]] = {p.id: [] for p in plates}
    for cid, pid in cell_plate_map.items():
        if pid in plate_cells:
            plate_cells[pid].append(cid)
    for p in plates:
        p.cell_ids = sorted(plate_cells.get(p.id, []))
        for cid in p.cell_ids:
            mesh.cells[cid].plate_id = p.id


def _assign_distinct_seeds(
    tree: Any,
    centroids: list[np.ndarray],
    k: int = 8,
) -> list[int]:
    """Map each centroid to a DISTINCT nearest cell.

    Duplicate seeds are the root cause of plate loss during re-partitioning:
    when two rotated centroids round to the same cell, one plate claims the
    shared cell and the other gets nothing, then is removed by
    ``_cleanup_empty`` (the artificial 20→6 collapse).  Querying the k nearest
    cells and greedily picking an unused one keeps every plate alive.
    """
    if not centroids:
        return []
    _, idx = tree.query(np.array(centroids), k=k)
    idx = np.atleast_2d(idx)
    used: set[int] = set()
    seeds: list[int] = []
    for i in range(idx.shape[0]):
        chosen = int(idx[i, 0])
        for j in range(idx.shape[1]):
            cand = int(idx[i, j])
            if cand not in used:
                chosen = cand
                break
        used.add(chosen)
        seeds.append(chosen)
    return seeds


def _trench_arc_relaxation(
    mesh: CVTMesh,
    cell_plate_map: dict[int, str],
    plates: list[TectonicPlate],
    radius_km: float,
    strength: float,
    arc_state: dict[tuple[str, str], float],
    locked: dict[int, str] | None = None,
    smooth_rng: np.random.Generator | None = None,
) -> dict[int, str]:
    """Bend subduction boundaries into small-circle arcs (Frank 1968).

    A subducting slab peels off the surface as a rigid spherical cap; its edge
    (the trench) is the intersection of that cap with the sphere — a SMALL
    CIRCLE.  That geometry is the origin of island-arc curvature (Frank 1968),
    with arc radius correlated to slab dip and convergence rate (Tovish 1978;
    Heuret & Lallemand 2005).  A Voronoi re-partition can NEVER produce it —
    bisectors of point seeds are geodesics/Apollonius arcs — so after each
    resample every convergent oceanic boundary segment is relaxed toward the
    small-circle arc implied by the CURRENT kinematic state:

        convergence rate (Euler poles) → slab dip (Tovish) → sagitta
        sagitta develops gradually (arc_state relaxation) → the arc EMERGES
        over the evolution instead of being authored up front.

    The arc bulges OCEANWARD (into the subducting plate), as real trenches do
    (Japan, Aleutians, Tonga).  Collision (continent–continent) segments are
    left to the orogeny model.
    """
    if strength <= 0.0:
        return cell_plate_map

    locked = locked or {}
    plate_dict = {p.id: p for p in plates}
    new_map = dict(cell_plate_map)

    cell_km = np.sqrt(4.0 * np.pi * radius_km**2 / mesh.num_cells)

    # ---- boundary cells grouped by plate pair ----------------------------
    pair_cells: dict[tuple[str, str], list[int]] = {}
    for cid, pid in cell_plate_map.items():
        for nid in mesh.cells[cid].neighbors:
            npid = cell_plate_map.get(nid, "")
            if npid and npid != pid:
                key = (pid, npid) if pid < npid else (npid, pid)
                pair_cells.setdefault(key, []).append(cid)
                break

    # Local width of each plate (area / boundary length, in cells).  The arc
    # sagitta is capped by this below: an arc deeper than a quarter of the
    # retreat plate's width would pinch small plates into braided slivers
    # (interweave regression, 2026-08-06).
    area_cells: dict[str, int] = {}
    for _cid, pid in cell_plate_map.items():
        area_cells[pid] = area_cells.get(pid, 0) + 1
    boundary_len: dict[str, int] = {}
    for (pa, pb), cells in pair_cells.items():
        boundary_len[pa] = boundary_len.get(pa, 0) + len(cells)
        boundary_len[pb] = boundary_len.get(pb, 0) + len(cells)
    widths = {pid: area_cells.get(pid, 0) / max(1, boundary_len.get(pid, 1)) for pid in area_cells}

    for (pa, pb), cells in pair_cells.items():
        pla, plb = plate_dict.get(pa), plate_dict.get(pb)
        if pla is None or plb is None:
            continue
        bset = set(cells)
        # Connected segments within this pair's boundary
        while bset:
            start = next(iter(bset))
            seg = [start]
            bset.remove(start)
            q = [start]
            while q:
                u = q.pop()
                for v in mesh.cells[u].neighbors:
                    if v in bset:
                        bset.remove(v)
                        seg.append(v)
                        q.append(v)
            # Long boundaries are often bent (L/Z-shaped); a single chord
            # frame can't carry one arc — split at the corner into straighter
            # sub-segments, each developing its own arc.
            for sub_seg in _split_bent_segment(mesh, seg, depth=0):
                if len(sub_seg) < 12:
                    continue
                _relax_segment(
                    mesh,
                    new_map,
                    sub_seg,
                    pla,
                    plb,
                    radius_km,
                    cell_km,
                    strength,
                    arc_state,
                    locked,
                    widths,
                )

    # Enclave guard: arc flips can sever thin boundary protrusions into
    # flying islands.  Absorb any disconnected fragment < 600 cells into its
    # surrounding majority plate.  Only merges DISCONNECTED fragments of the
    # same plate — standalone microplates (single component) are untouched.
    from collections import deque

    by_plate: dict[str, list[int]] = {}
    for cid, pid in new_map.items():
        by_plate.setdefault(pid, []).append(cid)
    for pid, cells in by_plate.items():
        cs = set(cells)
        seen: set[int] = set()
        comps: list[list[int]] = []
        for s in cs:
            if s in seen:
                continue
            comp = [s]
            seen.add(s)
            bq = deque([s])
            while bq:
                u = bq.popleft()
                for v in mesh.cells[u].neighbors:
                    if v in cs and v not in seen:
                        seen.add(v)
                        comp.append(v)
                        q.append(v)
            comps.append(comp)
        if len(comps) < 2:
            continue
        comps.sort(key=len, reverse=True)
        for comp in comps[1:]:
            if len(comp) >= 600:
                continue
            votes: dict[str, int] = {}
            for cid in comp:
                for v in mesh.cells[cid].neighbors:
                    npid = new_map.get(v, "")
                    if npid and npid != pid:
                        votes[npid] = votes.get(npid, 0) + 1
            target = max(votes, key=lambda k: votes[k]) if votes else pid
            for cid in comp:
                new_map[cid] = target

    # Final boundary smoothing (only on the last application): dissolves
    # residual <3-cell braids left by the arc/Voronoi superposition while
    # preserving the wide arcs (majority-vote Laplacian, Cortial 2019 §3).
    if smooth_rng is not None:
        from .plate_generator import _relax_boundaries

        _relax_boundaries(mesh, new_map, 0.12, smooth_rng)
    return new_map


def _split_bent_segment(
    mesh: CVTMesh,
    seg: list[int],
    depth: int,
) -> list[list[int]]:
    """Recursively split a boundary segment at its corner cell.

    A segment whose cells deviate from the endpoint chord by more than
    30% of the chord is bent; splitting at the farthest cell yields
    straighter sub-segments that each admit a small-circle arc fit.

    The split is CONTIGUOUS along the boundary polyline (BFS order from one
    endpoint): splitting by chord projection would interleave the arms of
    Z/U-shaped boundaries into both children, giving garbage chord frames
    and scattering arc flips into enclaves (regression of 2026-08-06).
    """
    if len(seg) < 24 or depth >= 2:
        return [seg]
    pts = np.array([[mesh.cells[c].x, mesh.cells[c].y, mesh.cells[c].z] for c in seg])
    d2 = ((pts[:, None, :] - pts[None, :, :]) ** 2).sum(-1)
    i, j = np.unravel_index(int(np.argmax(d2)), d2.shape)
    e0, e1 = pts[i], pts[j]
    chord = float(np.sqrt(d2[i, j])) + 1e-12
    t3 = (e1 - e0) / chord
    m = (e0 + e1) / 2.0
    m /= np.linalg.norm(m)
    n = np.cross(m, t3)
    nn = np.linalg.norm(n)
    if nn < 1e-9:
        return [seg]
    n /= nn
    perp = (pts - e0) @ n
    k = int(np.argmax(np.abs(perp)))
    if abs(perp[k]) < 0.3 * chord:
        return [seg]

    # Order the polyline contiguously from endpoint seg[i] (BFS within seg).
    from collections import deque

    segset = set(seg)
    order: list[int] = [seg[int(i)]]
    seen = {order[0]}
    q: deque[int] = deque(order)
    while q:
        u = q.popleft()
        for v in mesh.cells[u].neighbors:
            if v in segset and v not in seen:
                seen.add(v)
                order.append(v)
                q.append(v)
    if len(order) != len(seg):
        return [seg]  # fragmented polyline — keep as one, arcs skipped safely
    try:
        idx = order.index(seg[int(k)])
    except ValueError:
        return [seg]
    if idx < 6 or idx > len(order) - 6:
        return [seg]
    a = order[: idx + 1]
    b = order[idx:]
    return _split_bent_segment(mesh, a, depth + 1) + _split_bent_segment(mesh, b, depth + 1)


def _relax_segment(
    mesh: CVTMesh,
    cell_map: dict[int, str],
    seg: list[int],
    pla: TectonicPlate,
    plb: TectonicPlate,
    radius_km: float,
    cell_km: float,
    strength: float,
    arc_state: dict[tuple[str, str], float],
    locked: dict[int, str],
    widths: dict[str, float] | None = None,
) -> None:
    """Relax one boundary segment toward its kinematic small-circle arc.

    The boundary bulges into the *retreat side*: for oceanic subduction that
    is the subducting plate (trench rollback, Japan/Aleutians); for
    continent–continent collision the orogen arcs convex toward the indenter
    (Himalaya, Alps), approximated by the faster-converging plate.
    """

    # Oceanic fraction per side decides the regime.
    def ocean_frac(pid: str) -> float:
        n = 0
        o = 0
        for cid in seg:
            if cell_map.get(cid) == pid:
                n += 1
                if mesh.cells[cid].crust_type == "oceanic":
                    o += 1
        return o / n if n else 0.0

    fa, fb = ocean_frac(pla.id), ocean_frac(plb.id)
    mid0 = _seg_mid(mesh, seg)
    va = float(np.linalg.norm(_plate_velocity_cm_yr(pla, mid0, radius_km)))
    vb = float(np.linalg.norm(_plate_velocity_cm_yr(plb, mid0, radius_km)))
    if abs(fa - fb) > 0.2:
        # One side oceanic → subduction: boundary retreats into the oceanic
        # (subducting) plate.
        retreat, other = (pla, plb) if fa > fb else (plb, pla)
    elif max(fa, fb) >= 0.6:
        # Ocean–ocean: the faster plate subducts.
        retreat, other = (pla, plb) if va > vb else (plb, pla)
    else:
        # Continent–continent collision: orogen bulges toward the indenter
        # (faster plate).  Gentler arcs than trenches.
        retreat, other = (pla, plb) if va > vb else (plb, pla)

    # Endpoints (diameter of the segment) and chord frame
    pts = np.array([[mesh.cells[c].x, mesh.cells[c].y, mesh.cells[c].z] for c in seg])
    d2 = ((pts[:, None, :] - pts[None, :, :]) ** 2).sum(-1)
    i, j = np.unravel_index(int(np.argmax(d2)), d2.shape)
    e0, e1 = pts[i], pts[j]
    chord = float(np.sqrt(d2[i, j]))
    if chord < 0.15:  # < ~1000 km — too short to carry a meaningful arc
        return
    t3 = (e1 - e0) / chord

    side_ret = np.array(
        [
            np.mean([mesh.cells[c].x for c in seg if cell_map.get(c) == retreat.id]),
            np.mean([mesh.cells[c].y for c in seg if cell_map.get(c) == retreat.id]),
            np.mean([mesh.cells[c].z for c in seg if cell_map.get(c) == retreat.id]),
        ]
    )
    side_oth = np.array(
        [
            np.mean([mesh.cells[c].x for c in seg if cell_map.get(c) == other.id]),
            np.mean([mesh.cells[c].y for c in seg if cell_map.get(c) == other.id]),
            np.mean([mesh.cells[c].z for c in seg if cell_map.get(c) == other.id]),
        ]
    )
    # Normal = perpendicular to the chord in the local tangent plane (a side-
    # mean difference can be parallel to the chord on bent segments).  Sign it
    # toward the other (non-retreat) side.
    mid0 = (e0 + e1) / 2.0
    mid0 /= np.linalg.norm(mid0)
    n_so = np.cross(mid0, t3)
    nn = np.linalg.norm(n_so)
    if nn < 1e-9:
        return
    n_so /= nn
    if (side_oth - side_ret) @ n_so < 0:
        n_so = -n_so

    # Convergence rate at the midpoint (cm/yr) → slab dip → target sagitta.
    mid = (e0 + e1) / 2.0
    mid /= np.linalg.norm(mid)
    v_ret = _plate_velocity_cm_yr(retreat, mid, radius_km)
    v_oth = _plate_velocity_cm_yr(other, mid, radius_km)
    approach = float((v_ret - v_oth) @ n_so)
    if approach < 0.5:
        return  # not convergent (transform/divergent) — no arc forcing
    # Tovish (1978): faster convergence → steeper dip → tighter arc.
    dip_deg = float(np.clip(70.0 - 1.5 * approach, 30.0, 70.0))
    cc = max(fa, fb) < 0.6
    s_target = strength * (0.10 + 0.20 * (dip_deg - 30.0) / 40.0)
    if cc:
        s_target *= 0.7  # collision orogens arc gentler than trenches

    # Develop gradually: the arc grows over successive resamples instead of
    # appearing in one step (emergent in time, not authored).
    key = (retreat.id, other.id)
    cur = arc_state.get(key, 0.0)
    cur += (s_target - cur) * 0.3
    arc_state[key] = cur
    if cur < 0.03:
        return
    sag = cur * chord  # radians

    # Cap the arc on NARROW retreat plates (area/boundary ≈ half-strip-width).
    # An arc comparable to the plate width pinches a small plate sandwiched
    # between two larger ones into braided slivers with narrow necks
    # (interweave regression of 2026-08-06): the two flanking arcs bulge
    # toward each other and nearly touch across it.  Wide plates keep their
    # full kinematic arc.
    if widths is not None:
        half_w = widths.get(retreat.id, 1e9)
        if half_w < 12.0:
            cell_ang = float(np.sqrt(4.0 * np.pi / mesh.num_cells))
            sag = min(sag, 0.5 * half_w * cell_ang)
            if sag < 0.01:
                return

    # Flip band hugs the ACTUAL boundary (BFS from boundary cells of both
    # sides): on bent sub-segments the chord cuts across the bend interior,
    # and a chord-anchored lens would sever the bend tip into an enclave
    # (regression of 2026-08-06).  Kinks keep their raw corners — realistic.
    sources = set(seg)
    band = _bfs_distance(mesh, sources, 1.5 * sag * radius_km, cell_km)

    flipped = 0
    for cid in band:
        if locked and cid in locked:
            continue
        if cell_map.get(cid) != retreat.id:
            continue
        p = np.array([mesh.cells[cid].x, mesh.cells[cid].y, mesh.cells[cid].z])
        rel = p - e0
        t = float(np.clip((rel @ t3) / chord, 0.0, 1.0))
        h = float(rel @ n_so)  # >0 toward the other side
        h_arc = -4.0 * sag * t * (1.0 - t)  # parabola: 0 at ends, -sag mid
        if h_arc < h < 0.0 and 0.02 < t < 0.98:
            cell_map[cid] = other.id
            flipped += 1
    if flipped:
        logger.info(
            "  Trench arc: %s→%s dip=%.0f° sag=%.0f km, %d cells retreated",
            retreat.id,
            other.id,
            dip_deg,
            sag * radius_km,
            flipped,
        )


def _seg_mid(mesh: CVTMesh, seg: list[int]) -> np.ndarray:
    v = np.mean(
        [[mesh.cells[c].x, mesh.cells[c].y, mesh.cells[c].z] for c in seg],
        axis=0,
    )
    return np.asarray(v / np.linalg.norm(v))


def _smooth_partition(mesh: CVTMesh, cell_map: dict[int, str], rounds: int = 4) -> dict[int, str]:
    """Majority-vote smoothing of the final partition (removes dog-teeth).

    The cell-lattice Voronoi re-partition makes boundaries staircase-zigzag
    (mean turn angle ~76° per cell step vs ~5–15° for real Earth boundaries).
    A cell whose strict neighbour majority belongs to another plate is a
    tooth and is reassigned; four rounds remove 1–2-cell teeth while keeping
    genuine corners and triple junctions (interior cells of a ≥2-cell-wide
    band never reach a strict opposite majority).  Two-hop voting was tried
    and rejected (blocky staircases, metric regressed 38.6° → 46.1°).
    """
    from collections import Counter

    for _ in range(rounds):
        new_map = dict(cell_map)
        for cid, cell in enumerate(mesh.cells):
            pid = cell_map[cid]
            votes = Counter(cell_map[v] for v in cell.neighbors)
            top_pid, top_n = votes.most_common(1)[0]
            if top_pid != pid and top_n * 2 > len(cell.neighbors):
                new_map[cid] = top_pid
        cell_map = new_map
    return cell_map


def _merge_plate_enclaves(mesh: CVTMesh, cell_map: dict[int, str]) -> dict[int, str]:
    """Reassign tiny disconnected plate enclaves to the surrounding plate.

    The final boundary warp re-partitions from centroids and can carve
    single-cell exclaves ("dog-teeth"); rifting children (``plate_xxx_b``)
    may also leave enclaves.  Connected components smaller than
    max(20, 0.5% of the plate) are merged into the neighbour-majority
    plate, restoring connectivity without moving the large-scale partition.
    """
    from collections import Counter, deque

    by_plate: dict[str, list[int]] = {}
    for cid, pid in cell_map.items():
        by_plate.setdefault(pid, []).append(cid)

    new_map = dict(cell_map)
    for pid, cids in by_plate.items():
        cellset = set(cids)
        seen: set[int] = set()
        comps: list[list[int]] = []
        for s in cids:
            if s in seen:
                continue
            comp = [s]
            seen.add(s)
            q: deque[int] = deque([s])
            while q:
                u = q.popleft()
                for v in mesh.cells[u].neighbors:
                    if v in cellset and v not in seen:
                        seen.add(v)
                        comp.append(v)
                        q.append(v)
            comps.append(comp)
        if len(comps) < 2:
            continue
        comps.sort(key=len, reverse=True)
        min_keep = max(20, int(0.005 * len(cids)))
        for comp in comps[1:]:
            if len(comp) >= min_keep:
                continue
            votes: Counter[str] = Counter()
            for u in comp:
                for v in mesh.cells[u].neighbors:
                    p2 = new_map.get(v)
                    if p2 is not None and p2 != pid:
                        votes[p2] += 1
            target = votes.most_common(1)[0][0] if votes else pid
            for u in comp:
                new_map[u] = target
    return new_map


def warp_boundaries(
    mesh: CVTMesh,
    cell_plate_map: dict[int, str],
    config: TerrainPipelineConfig,
    plate_weights: dict[str, float] | None = None,
) -> dict[int, str]:
    """Re-partition as a noise-warped Voronoi of the current plate positions.

    Cortial et al. (2019) §3 "geodetic distance + noise warp".  Applied once to
    the FINAL partition (after tectonics) so straight geodesic boundaries become
    irregular, arc-like — making island arcs / mountain belts curve and segment
    instead of running unnaturally long and straight.  Plate shapes are preserved
    (the partition is still the Voronoi of the same plate centroids); only the
    boundaries are warped.

    ``plate_weights`` (plate id → persistent size weight) carries the size
    skew into the warp: without it this final re-partition would be an
    unweighted Voronoi and partially re-uniformise the plate areas that the
    weighted tectonic resamples preserved.
    """
    from scipy.spatial import cKDTree

    from .plate_generator import build_cell_cost, voronoi_partition_warped

    present = sorted(set(cell_plate_map.values()))
    centroids: list[np.ndarray] = []
    plate_ids: list[str] = []
    areas: list[int] = []
    for pid in present:
        cids = [cid for cid, p in cell_plate_map.items() if p == pid]
        if not cids:
            continue
        cx = float(np.mean([mesh.cells[c].x for c in cids]))
        cy = float(np.mean([mesh.cells[c].y for c in cids]))
        cz = float(np.mean([mesh.cells[c].z for c in cids]))
        norm = float(np.sqrt(cx * cx + cy * cy + cz * cz)) or 1.0
        centroids.append(np.array([cx / norm, cy / norm, cz / norm]))
        plate_ids.append(pid)
        areas.append(len(cids))

    cell_xyz = np.array([[c.x, c.y, c.z] for c in mesh.cells], dtype=np.float64)
    tree = cKDTree(cell_xyz)
    seeds = _assign_distinct_seeds(tree, centroids)
    cost = build_cell_cost(mesh, config.seed + 7777, config.boundary_warp)
    speed = _plate_speeds(plate_ids, plate_weights, areas) if plate_weights is not None else None
    warped = voronoi_partition_warped(mesh, seeds, plate_ids, cost, plate_speed=speed)
    logger.info("  Boundary warp: %d plates, amplitude=%.2f", len(plate_ids), config.boundary_warp)
    return warped
