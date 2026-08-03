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

import logging

import numpy as np

from .models import CVTMesh, EulerPole, TectonicPlate
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
            if npid and npid != pid:
                if crust_arr[nid] == "continental":
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
    progress_callback: object | None = None,
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
        return plates, cell_map

    if algo not in _TECTONIC_ALGORITHMS:
        raise ValueError(
            f"Unknown tectonic algorithm '{algo}'. "
            f"Available: {sorted(_TECTONIC_ALGORITHMS.keys())}"
        )
    if algo == "cortial2019":
        return _evolve_cortial2019(
            mesh, plates, config, progress_callback=progress_callback,
        )
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
    ax = rng.standard_normal(3); ax /= np.linalg.norm(ax)
    new_pole = EulerPole(
        x=float(ax[0]), y=float(ax[1]), z=float(ax[2]),
        omega_rad_yr=parent.euler_pole.omega_rad_yr * rng.uniform(0.7, 1.3),
    )

    new_id = f"oceanic_s{step:04d}"
    new_plate = TectonicPlate(
        id=new_id, name=f"新生洋壳 t={step}",
        type="oceanic", cell_ids=new_cells, euler_pole=new_pole,
    )
    plates.append(new_plate)
    if plate_birth_step is not None:
        plate_birth_step[new_id] = step
    for cid in new_cells:
        cell_plate_map[cid] = new_id

    logger.info(
        "  Spawned oceanic crust: %d cells → plate %s at divergent boundary",
        len(new_cells), new_id,
    )
    return plates, cell_plate_map


def _rodrigues_rotate(
    xyz: np.ndarray, axis: np.ndarray, angle_rad: float,
) -> np.ndarray:
    """Rodrigues rotation of a point on the unit sphere."""
    axis = axis / np.linalg.norm(axis)
    cos_a, sin_a = np.cos(angle_rad), np.sin(angle_rad)
    return (
        xyz * cos_a
        + np.cross(axis, xyz) * sin_a
        + axis * np.dot(axis, xyz) * (1.0 - cos_a)
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
    return max(1.0, dt_my)


def _evolve_cortial2019(
    mesh: CVTMesh,
    plates: list[TectonicPlate],
    config: TerrainPipelineConfig,
    *,
    progress_callback: object | None = None,
) -> tuple[list[TectonicPlate], dict[int, str]]:
    """Cortial et al. (2019) original — centroid rotation + re-Voronoi.

    Each step: rotate plate centroids → Voronoi → boundaries shift → elevation.
    """
    from .plate_generator import _voronoi_partition

    num_steps = config.tectonic_steps
    dt_my = _auto_compute_dt(mesh, config)
    radius_km = config.radius_km
    rng = np.random.default_rng(config.seed)
    logger.info("Tectonic evolution: seed=%d, steps=%d, rift_rate=%.4f", config.seed, num_steps, config.rift_base_rate)

    # Initial cell→plate map
    cell_plate_map: dict[int, str] = {}
    for p in plates:
        for cid in p.cell_ids:
            cell_plate_map[cid] = p.id

    if num_steps <= 0:
        return plates, cell_plate_map

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
        num_steps, dt_my, num_steps * dt_my,
        np.sqrt(4.0 * np.pi * radius_km**2 / mesh.num_cells),
    )

    prev_cell_map = cell_plate_map
    plate_birth_step: dict[str, int] = {p.id: 0 for p in plates}
    COOLDOWN = max(1, num_steps // 20)  # ~5% of total run
    # Only resample Voronoi after rifting events (Cortial 2019 strategy).
    # Between rifts, cell ownership is stable — fragments survive to grow.
    RESAMPLE_EVERY = 10
    needs_resample = True
    last_rifting_step = -RESAMPLE_EVERY

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
        if rotated_centroids:
            new_seeds = _tree.query(np.array(rotated_centroids))[1].tolist()
        else:
            new_seeds = []

        # 2. Re-run Voronoi (only every N steps or after a rift)
        # Protect newborn plates: lock their cells so they survive long enough to grow
        needs_resample = (step - last_rifting_step >= RESAMPLE_EVERY)
        if needs_resample:
            locked: dict[int, str] = {}
            NEWBORN_COOLDOWN = COOLDOWN * 5  # ~25 steps — give oceanic plates time to grow
            newborn_pids = [
                pid for pid, birth in plate_birth_step.items()
                if pid.startswith("oceanic") and step - birth < NEWBORN_COOLDOWN
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
                logger.info("  Voronoi: %d cells locked for %d oceanic newborn(s)", len(locked), len({v for v in locked.values()}))
            new_cell_map = _voronoi_partition(mesh, new_seeds, locked=locked)
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
            mesh, new_cell_map, plates, radius_km, dt_my, convergent, elev_m,
        )
        _collision_orogeny(
            mesh, new_cell_map, radius_km, dt_my, convergent, elev_m, crust_arr,
        )
        _erosion(mesh, dt_my, elev_m, crust_arr)

        # 5. Plate rifting + cleanup orphan cells
        n_before = len(plates)
        plates, new_cell_map = _rift_plates(
            mesh, new_cell_map, plates, config, rng,
            step=step, plate_birth_step=plate_birth_step,
        )
        if len(plates) != n_before:
            last_rifting_step = step
        # Remove plates that ended up with 0 cells (Voronoi consolidation)
        plates, new_cell_map = _cleanup_empty(
            mesh, new_cell_map, plates,
            step=step, plate_birth_step=plate_birth_step, cooldown=COOLDOWN,
        )

        # 6. Update for next step
        prev_cell_map = new_cell_map
        _rebuild_plate_cells(mesh, new_cell_map, plates)

        if progress_callback is not None:
            try:
                progress_callback(step + 1, num_steps)  # type: ignore[call-arg]
            except Exception:
                pass
        elif step % 10 == 0 or step == num_steps - 1:
            logger.info(
                "  Step %3d/%d: %d cells changed plate",
                step + 1, num_steps, n_changed,
            )

    # Finalise — write the canonical elevation array back to cells once
    for i, c in enumerate(mesh.cells):
        c.elevation = float(elev_m[i])
    logger.info(
        "Tectonic evolution complete: %d steps, %d plates, %d cells",
        num_steps, len(plates), mesh.num_cells,
    )
    return plates, prev_cell_map


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
    COOLDOWN = 5  # steps before a new plate can rift again
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
            birth = plate_birth_step.get(plate.id, -COOLDOWN)
            if step - birth < COOLDOWN and n_cells <= avg_cells * 2:
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
            plate.name, n_cells, lam, r, n_pieces,
        )

        # Pick n_pieces random seed cells from the plate
        seed_ids = list(rng.choice(plate.cell_ids, size=min(n_pieces, n_cells), replace=False))
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
            new_axis = parent_axis * np.cos(angle_rad) + np.cross(perturb_axis, parent_axis) * np.sin(angle_rad)
            new_axis /= np.linalg.norm(new_axis)
            new_pole = EulerPole(
                x=float(new_axis[0]), y=float(new_axis[1]), z=float(new_axis[2]),
                omega_rad_yr=plate.euler_pole.omega_rad_yr * rng.uniform(0.85, 1.15),
            )
            sub_plate = TectonicPlate(
                id=sub_id, name=sub_name, type=plate.type,
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
                assigned_total, n_cells,
            )
            # Restore parent plate (without the incomplete sub-plates)
            for i in range(added):
                plates.pop()
            plate.cell_ids = list(plate.cell_ids)  # ensure mutable
            plates.append(plate)
            if plate_birth_step is not None:
                plate_birth_step[plate.id] = -COOLDOWN  # don't try again soon
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
    """Partition *plate_cells* into *len(seeds)* groups via synchronous BFS.

    Each seed starts a wavefront; cells are claimed by the first wave to reach them.
    """
    from collections import deque

    cell_set = set(plate_cells)
    queues = [deque([s]) for s in seeds]
    assigned: dict[int, int | None] = {s: i for i, s in enumerate(seeds)}
    total = len(seeds)

    while total < len(plate_cells):
        progress = 0
        for i, q in enumerate(queues):
            if not q:
                continue
            for _ in range(len(q)):
                cid = q.popleft()
                for nid in mesh.cells[cid].neighbors:
                    if nid in cell_set and nid not in assigned:
                        assigned[nid] = i
                        q.append(nid)
                        total += 1
                        progress += 1
        if progress == 0:
            # Stranded cells — assign to nearest seed
            for cid in plate_cells:
                if cid not in assigned:
                    assigned[cid] = 0  # fallback
            break

    result: list[list[int]] = [[] for _ in seeds]
    for cid, idx in assigned.items():
        if idx is not None:
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
    HARD_MIN_CELLS = 50  # absolute floor: never consume plates with >50 cells
    min_cells = max(HARD_MIN_CELLS, int(total_cells * 0.003))

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
            plate.name, n_cells,
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
            logger.info("  Consumed: re-parented %d orphan cells (pass %d)", orphan_count, _pass + 1)
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
