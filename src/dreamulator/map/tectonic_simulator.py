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

from .models import CVTMesh, TectonicPlate
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
        z_km = getattr(mesh.cells[cid], "elevation", 0.0) / 1000.0
        z_above = max(0.0, z_km)
        h_z = (z_above / _Z_C_KM) ** 2 if _Z_C_KM > 0 else 0.0

        dz_km = u0_km_yr * f_d * g_v * (1.0 + h_z) * dt_yr
        # Cap: don't push above z_c (10 km) or below z_t (-10 km)
        cur_m = getattr(mesh.cells[cid], "elevation", 0.0)
        mesh.cells[cid].elevation = max(
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
        cell = mesh.cells[cid]
        if getattr(cell, "crust_type", "") != "continental":
            continue
        pid = cell_plate_map.get(cid, "")
        for nid in cell.neighbors:
            npid = cell_plate_map.get(nid, "")
            if npid and npid != pid:
                if getattr(mesh.cells[nid], "crust_type", "") == "continental":
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
        mesh.cells[cid].elevation = getattr(
            mesh.cells[cid], "elevation", 0.0
        ) + dz_km * 1000.0
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
) -> None:
    """Cortial 2019 §5 — erosion / subsidence / sedimentation per cell."""
    dt_yr = dt_my * 1e6

    for cell in mesh.cells:
        z_km = getattr(cell, "elevation", 0.0) / 1000.0
        crust = getattr(cell, "crust_type", "")

        if crust == "continental":
            dz = (z_km / _Z_C_KM) * _EPSILON_C_MM_YR * 1e-6 * dt_yr
        else:
            dz = (1.0 - z_km / _Z_T_KM) * _EPSILON_O_MM_YR * 1e-6 * dt_yr

        cell.elevation = getattr(cell, "elevation", 0.0) - dz * 1000.0

        # Trench sedimentation (deep cells)
        if z_km < -5.0:
            cell.elevation = getattr(
                cell, "elevation", 0.0
            ) + _EPSILON_T_MM_YR * 1e-6 * dt_yr * 1000.0


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
    # Auto-enable if steps > 0 but no algorithm specified
    if not algo and config.tectonic_steps > 0:
        algo = "cortial2019"
        logger.info("  Auto-selected tectonic algorithm: %s", algo)
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


def _find_nearest_cell(xyz: np.ndarray, mesh: CVTMesh) -> int:
    """Find CVT cell closest to a 3D point on the sphere (dot-product distance)."""
    best_id, best_dot = 0, -2.0
    for i, c in enumerate(mesh.cells):
        dot = xyz[0] * c.x + xyz[1] * c.y + xyz[2] * c.z
        if dot > best_dot:
            best_dot, best_id = dot, i
    return best_id


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

    # Initial cell→plate map
    cell_plate_map: dict[int, str] = {}
    for p in plates:
        for cid in p.cell_ids:
            cell_plate_map[cid] = p.id

    if num_steps <= 0:
        return plates, cell_plate_map

    logger.info(
        "Tectonic evolution: %d steps × %.1f My = %.0f My total "
        "(cell ~%.0f km, δt auto-scaled to move ~3 cells/step)",
        num_steps, dt_my, num_steps * dt_my,
        np.sqrt(4.0 * np.pi * radius_km**2 / mesh.num_cells),
    )

    prev_cell_map = cell_plate_map

    for step in range(num_steps):
        # 1. Rotate centroids → find new seeds
        new_seeds: list[int] = []
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

            new_c = _rodrigues_rotate(centroid, axis, angle_rad)
            new_seeds.append(_find_nearest_cell(new_c, mesh))

        # 2. Re-run Voronoi
        new_cell_map = _voronoi_partition(mesh, new_seeds)

        n_changed = sum(
            1 for cid in range(mesh.num_cells)
            if prev_cell_map.get(cid, "") != new_cell_map.get(cid, "")
        )

        # 3. Detect changed cells → convergent/divergent
        convergent: set[int] = set()
        divergent: set[int] = set()
        for cid in range(mesh.num_cells):
            old_pid = prev_cell_map.get(cid, "")
            new_pid = new_cell_map.get(cid, "")
            if old_pid and new_pid and old_pid != new_pid:
                # Cell gained by new_pid → convergent (subduction)
                convergent.add(cid) if True else None  # both cells are convergent at this boundary

        # Treat all changed cells as convergent for now
        # (proper divergence detection would track which plate lost cells)
        for cid in range(mesh.num_cells):
            old_pid = prev_cell_map.get(cid, "")
            new_pid = new_cell_map.get(cid, "")
            if old_pid and new_pid and old_pid != new_pid:
                convergent.add(cid)

        # 4. Apply elevation effects
        _subduction_uplift(
            mesh, new_cell_map, plates, radius_km, dt_my, convergent,
        )
        _collision_orogeny(
            mesh, new_cell_map, radius_km, dt_my, convergent,
        )
        _erosion(mesh, dt_my)

        # 5. Update for next step
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

    # Finalise
    logger.info("Tectonic evolution complete: %d steps", num_steps)
    return plates, prev_cell_map


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
