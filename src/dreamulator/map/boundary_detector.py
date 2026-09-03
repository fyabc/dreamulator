"""Plate boundary detection and classification.

Pipeline:
    1. Identify boundary cells (neighbours belong to different plates)
    2. Compute relative plate velocity at each boundary cell
    3. Decompose into normal (convergent/divergent) and tangential (transform)
    4. Classify boundary type
    5. BFS distance-from-boundary for all cells

See ``docs/design/terrain-pipeline.md`` §4 for algorithm details.

Key formulas:
    v(P) = ω × P          (rigid-body velocity from Euler pole)
    v_rel = v_A(P) - v_B(P)
    v_n = v_rel · n̂       (normal component)
    v_t = |v_rel - v_n·n̂| (tangential component)
"""

from __future__ import annotations

import logging
from collections import deque
from typing import TYPE_CHECKING

import numpy as np

from .distance import geodesic_bfs_with_source

if TYPE_CHECKING:
    from .models import CVTMesh, TectonicPlate
    from .pipeline_types import TerrainPipelineConfig

logger = logging.getLogger(__name__)

# Threshold for boundary classification (cm/year).  Below this the normal
# component is "negligible" → transform (crust-conservative).  Earth's slowest
# subduction / spreading is ~1 cm/yr (Alpine Fault oblique transform ~0.5,
# Cascadia slow subduction ~3), so |v_n| < 1 cm/yr marks a transform.
_CONVERGENT_THRESHOLD = 1.0  # cm/yr


# ---------------------------------------------------------------------------
# Velocity computation
# ---------------------------------------------------------------------------


def plate_velocity_at(
    point_xyz: np.ndarray,
    plate: TectonicPlate,
) -> np.ndarray:
    """Compute velocity of a point due to plate rotation.

    v(P) = ω × P, where ω = euler_pole_axis * omega_rad_yr.

    Args:
        point_xyz: (3,) unit sphere coordinates of the point.
        plate: TectonicPlate with euler_pole.

    Returns:
        Velocity vector (3,) in rad/year * unit_sphere ≈ surface speed.
    """
    ep = plate.euler_pole
    omega_vec = np.array([ep.x, ep.y, ep.z]) * ep.omega_rad_yr
    return np.cross(omega_vec, point_xyz)


def compute_relative_velocity(
    point_xyz: np.ndarray,
    plate_a: TectonicPlate,
    plate_b: TectonicPlate,
) -> np.ndarray:
    """Compute relative velocity of plate A w.r.t. plate B at a point.

    v_rel = v_A(P) - v_B(P)

    Args:
        point_xyz: (3,) unit sphere coordinates.
        plate_a: First plate.
        plate_b: Second plate.

    Returns:
        Relative velocity vector (3,).
    """
    return np.asarray(plate_velocity_at(point_xyz, plate_a) - plate_velocity_at(point_xyz, plate_b))


def compute_boundary_normal(
    cell_xyz: np.ndarray,
    neighbor_xyz: np.ndarray,
) -> np.ndarray:
    """Compute approximate boundary normal at a cell.

    The boundary normal points from the cell toward its neighbor on the
    other plate.  On the sphere, this is the great-circle direction.

    Args:
        cell_xyz: (3,) position of the cell on unit sphere.
        neighbor_xyz: (3,) position of the neighbor on the other plate.

    Returns:
        Unit normal vector (3,) tangent to the sphere at cell_xyz.
    """
    # Direction toward neighbor
    direction = neighbor_xyz - cell_xyz * np.dot(cell_xyz, neighbor_xyz)
    norm = np.linalg.norm(direction)
    if norm < 1e-12:
        return np.zeros(3)
    return np.asarray(direction / norm)


# ---------------------------------------------------------------------------
# Boundary detection
# ---------------------------------------------------------------------------


def find_boundary_cells(
    mesh: CVTMesh,
    cell_plate_map: dict[int, str],
) -> list[tuple[int, int, str, str]]:
    """Find all cell pairs that straddle a plate boundary.

    Args:
        mesh: The CVT mesh.
        cell_plate_map: Cell → plate mapping.

    Returns:
        List of (cell_id, neighbor_id, plate_of_cell, plate_of_neighbor)
        for each boundary edge.
    """
    boundary_edges: list[tuple[int, int, str, str]] = []

    for cell_id in range(mesh.num_cells):
        plate_a = cell_plate_map.get(cell_id)
        if plate_a is None:
            continue

        for neighbor_id in mesh.cells[cell_id].neighbors:
            plate_b = cell_plate_map.get(neighbor_id)
            if plate_b is not None and plate_a != plate_b:
                boundary_edges.append((cell_id, neighbor_id, plate_a, plate_b))

    return boundary_edges


def classify_boundary(
    v_n: float,
    v_t: float,
    v_total: float,
) -> str:
    """Classify a boundary segment from the normal velocity component.

    The type is set by the NORMAL component ``v_n`` (positive = plates
    approaching → convergent; negative = separating → divergent; small = sliding
    → transform).  The tangential component ``v_t`` does NOT override the type —
    it is carried separately as ``tangential_fraction`` for the leaky-transform
    refinement (§3.7), so an oblique-convergent boundary (``v_n`` large,
    ``v_t`` larger) is still convergent (it builds mountains), not transform.

    Args:
        v_n: Normal velocity component (positive = convergent).
        v_t: Tangential velocity component (unused — see above).
        v_total: Total velocity magnitude.

    Returns:
        "convergent", "divergent", or "transform".
    """
    if v_total < 1e-12:
        return "transform"

    if v_n > _CONVERGENT_THRESHOLD:
        return "convergent"
    elif v_n < -_CONVERGENT_THRESHOLD:
        return "divergent"
    else:
        return "transform"


# ---------------------------------------------------------------------------
# Segment-based classification
# ---------------------------------------------------------------------------


def _cluster_cells(mesh: CVTMesh, cell_set: set[int]) -> list[list[int]]:
    """Cluster a set of cells into connected components via mesh adjacency."""
    segments: list[list[int]] = []
    unvisited = set(cell_set)
    while unvisited:
        start = unvisited.pop()
        segment = [start]
        stack = [start]
        while stack:
            cid = stack.pop()
            for nid in mesh.cells[cid].neighbors:
                if nid in unvisited:
                    unvisited.remove(nid)
                    segment.append(nid)
                    stack.append(nid)
        segments.append(segment)
    return segments


def _segment_normal_and_centroid(
    mesh: CVTMesh,
    segment: list[int],
    pb: str,
    cell_plate_map: dict[int, str],
) -> tuple[np.ndarray, np.ndarray] | None:
    """Mean boundary normal (toward ``pb``) + centroid for a (sub-)segment."""
    normals: list[np.ndarray] = []
    centroids: list[np.ndarray] = []
    for cid in segment:
        cell = mesh.cells[cid]
        cx = np.array([cell.x, cell.y, cell.z])
        centroids.append(cx)
        for nid in cell.neighbors:
            if cell_plate_map.get(nid) == pb:
                nb = mesh.cells[nid]
                nx = np.array([nb.x, nb.y, nb.z])
                d = nx - cx * float(np.dot(cx, nx))
                dn = float(np.linalg.norm(d))
                if dn > 1e-12:
                    normals.append(d / dn)
    if not normals:
        return None
    n_hat = np.mean(normals, axis=0)
    n_hat = n_hat / np.linalg.norm(n_hat)
    centroid = np.mean(centroids, axis=0)
    centroid = centroid / np.linalg.norm(centroid)
    return n_hat, centroid


def _assign_segment_type(
    mesh: CVTMesh,
    segment: list[int],
    plate_a: TectonicPlate,
    plate_b: TectonicPlate,
    pb: str,
    cell_plate_map: dict[int, str],
    radius_cm: float,
    cell_result: dict[int, tuple[str, float, float]],
    boundary_cell_ids: set[int],
) -> None:
    """Classify one (sub-)segment and write its type/rate to its cells."""
    res = _segment_normal_and_centroid(mesh, segment, pb, cell_plate_map)
    if res is None:
        return
    n_hat, centroid = res

    v_rel = compute_relative_velocity(centroid, plate_a, plate_b)
    v_n = float(np.dot(v_rel, n_hat))
    v_t_vec = v_rel - v_n * n_hat
    v_t = float(np.linalg.norm(v_t_vec))
    v_total = float(np.linalg.norm(v_rel))
    v_n_cm = v_n * radius_cm
    v_t_cm = v_t * radius_cm
    v_total_cm = v_total * radius_cm
    btype = classify_boundary(v_n_cm, v_t_cm, v_total_cm)
    tangential_fraction = v_t_cm / v_total_cm if v_total_cm > 1e-12 else 0.0

    for cid in segment:
        boundary_cell_ids.add(cid)
        cell_result[cid] = (btype, v_n_cm, tangential_fraction)
        for nid in mesh.cells[cid].neighbors:
            if cell_plate_map.get(nid) == pb:
                boundary_cell_ids.add(nid)
                cell_result.setdefault(nid, (btype, v_n_cm, tangential_fraction))


# Below this length a boundary is treated as one coherent stretch (too short to
# have meaningful along-strike type variation); longer boundaries are sub-
# segmented by their local normal velocity.
_MIN_SUBSEGMENT_CELLS = 8


def _classify_boundary_segments(
    mesh: CVTMesh,
    boundary_edges: list[tuple[int, int, str, str]],
    plate_map: dict[str, TectonicPlate],
    cell_plate_map: dict[int, str],
    radius_cm: float,
) -> tuple[set[int], dict[int, tuple[str, float, float]]]:
    """Classify boundary cells by plate-pair segments (continuous bands).

    Boundary cells are clustered into connected segments per plate-pair.  Each
    connected segment is then sub-segmented by its LOCAL normal velocity
    (projected onto the segment's mean normal, so the signal is smooth): a long
    boundary whose relative motion is convergent in one stretch, transform in
    another and divergent in a third (e.g. Pacific–North America) is split into
    those coherent stretches, each classified once with its own normal and
    centroid velocity.  This replaces both the noisy per-cell classification
    (red/green/yellow speckle) and the over-coarse whole-boundary classification
    (a 170-cell boundary collapsed to one type).

    Returns:
        ``(boundary_cell_ids, cell_result)`` where ``cell_result`` maps a cell
        id to ``(boundary_type, convergence_rate_cm_yr, tangential_fraction)``.
    """
    from collections import defaultdict

    # Group edges by unordered plate-pair; keep each edge oriented A→B.
    pair_edges: dict[tuple[str, str], list[tuple[int, int]]] = defaultdict(list)
    for cell_id, neighbor_id, pa, pb in boundary_edges:
        if pa < pb:
            pair_edges[(pa, pb)].append((cell_id, neighbor_id))
        else:
            pair_edges[(pb, pa)].append((neighbor_id, cell_id))

    cell_result: dict[int, tuple[str, float, float]] = {}
    boundary_cell_ids: set[int] = set()

    for (pa, pb), edges in pair_edges.items():
        plate_a = plate_map[pa]
        plate_b = plate_map[pb]
        a_side = {cell_id for cell_id, _ in edges}

        for segment in _cluster_cells(mesh, a_side):
            norm = _segment_normal_and_centroid(mesh, segment, pb, cell_plate_map)
            if norm is None:
                continue
            n_hat, _ = norm

            # Short boundary → classify whole (too short for along-strike split).
            if len(segment) < 2 * _MIN_SUBSEGMENT_CELLS:
                _assign_segment_type(
                    mesh,
                    segment,
                    plate_a,
                    plate_b,
                    pb,
                    cell_plate_map,
                    radius_cm,
                    cell_result,
                    boundary_cell_ids,
                )
                continue

            # Long boundary → sub-segment by local normal velocity.  The signal
            # uses the segment's mean normal so it is smooth (v_rel varies with
            # position, the per-cell normal would be noisy); cells whose local
            # v_n falls in the same category cluster into one coherent stretch.
            def _category(
                cid: int,
                _pa: TectonicPlate = plate_a,
                _pb: TectonicPlate = plate_b,
                _n: np.ndarray = n_hat,
            ) -> str:
                cell = mesh.cells[cid]
                cx = np.array([cell.x, cell.y, cell.z])
                v_rel = compute_relative_velocity(cx, _pa, _pb)
                v_n_cm = float(np.dot(v_rel, _n)) * radius_cm
                if v_n_cm > _CONVERGENT_THRESHOLD:
                    return "convergent"
                if v_n_cm < -_CONVERGENT_THRESHOLD:
                    return "divergent"
                return "transform"

            for cat in ("convergent", "divergent", "transform"):
                cat_cells = {cid for cid in segment if _category(cid) == cat}
                for sub in _cluster_cells(mesh, cat_cells):
                    if sub:
                        _assign_segment_type(
                            mesh,
                            sub,
                            plate_a,
                            plate_b,
                            pb,
                            cell_plate_map,
                            radius_cm,
                            cell_result,
                            boundary_cell_ids,
                        )

    return boundary_cell_ids, cell_result


# ---------------------------------------------------------------------------
# BFS distance from boundary
# ---------------------------------------------------------------------------


def compute_boundary_distance(
    mesh: CVTMesh,
    boundary_cell_ids: set[int],
    radius_km: float,
) -> None:
    """Compute distance from each cell to the nearest boundary cell via BFS.

    Modifies ``mesh.cells[*].distance_to_boundary_km`` in-place.

    Args:
        mesh: The CVT mesh.
        boundary_cell_ids: Set of cell IDs identified as boundary cells.
        radius_km: Planet radius in km (for converting angular to linear distance).
    """
    # BFS from all boundary cells simultaneously
    distances = [float("inf")] * mesh.num_cells
    queue: deque[int] = deque()

    for cid in boundary_cell_ids:
        distances[cid] = 0.0
        queue.append(cid)

    while queue:
        cell_id = queue.popleft()
        cell = mesh.cells[cell_id]
        cell_xyz = np.array([cell.x, cell.y, cell.z])

        for neighbor_id in cell.neighbors:
            if distances[neighbor_id] == float("inf"):
                neighbor = mesh.cells[neighbor_id]
                neighbor_xyz = np.array([neighbor.x, neighbor.y, neighbor.z])

                # Angular distance
                dot = np.clip(np.dot(cell_xyz, neighbor_xyz), -1, 1)
                angular_dist = np.arccos(dot)
                linear_dist = angular_dist * radius_km

                new_dist = distances[cell_id] + linear_dist
                if new_dist < distances[neighbor_id]:
                    distances[neighbor_id] = new_dist
                    queue.append(neighbor_id)

    # Write back to cells
    for i, cell in enumerate(mesh.cells):
        cell.distance_to_boundary_km = distances[i]


# ---------------------------------------------------------------------------
# Boundary type propagation
# ---------------------------------------------------------------------------


def _propagate_boundary_type(
    mesh: CVTMesh,
    boundary_cell_ids: set[int],
    config: TerrainPipelineConfig,
) -> None:
    """Propagate boundary_type and convergence_rate from boundary cells outward.

    Boundary cells sit right on the plate edge.  Cells one hop away have
    ``distance_to_boundary_km`` set but ``boundary_type=None``, which causes
    the terrain synthesizer to skip them — producing sharp elevation cliffs.

    This BFS copies the nearest boundary cell's type and rate to all cells
    within the influence radius, so the Gaussian mountain/trench/rift profiles
    extend smoothly across the landscape.
    """
    sigma = config.boundary_influence_km
    max_dist = 1.2 * sigma  # same cutoff as terrain synthesizer

    # Multi-source geodesic BFS: each boundary cell "claims" nearby cells.
    source_boundary = geodesic_bfs_with_source(
        mesh, boundary_cell_ids, config.radius_km, max_dist_km=max_dist
    )

    propagated = 0
    for cid, (src_id, _d) in source_boundary.items():
        if cid == src_id:
            continue
        # Copy boundary properties from source if not already set
        src = mesh.cells[src_id]
        cell = mesh.cells[cid]
        if cell.boundary_type is None:
            cell.boundary_type = src.boundary_type
            propagated += 1
        if cell.convergence_rate_cm_yr == 0.0:
            cell.convergence_rate_cm_yr = src.convergence_rate_cm_yr
        if cell.tangential_fraction == 0.0:
            cell.tangential_fraction = src.tangential_fraction

    if propagated > 0:
        logger.info(
            "  Propagated boundary type to %d nearby cells (within %.0f km)",
            propagated,
            max_dist,
        )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def detect_boundaries(
    mesh: CVTMesh,
    plates: list[TectonicPlate],
    cell_plate_map: dict[int, str],
    config: TerrainPipelineConfig,
) -> list[int]:
    """Detect plate boundaries and compute boundary properties.

    This is the main entry point for Stage 3 of the terrain pipeline.

    For each boundary cell:
    - Computes convergence rate (v_n in cm/year)
    - Classifies boundary type (convergent/divergent/transform)

    For all cells:
    - Computes distance to nearest boundary (km)

    Args:
        mesh: The CVT mesh (modified in-place).
        plates: List of tectonic plates.
        cell_plate_map: Cell → plate mapping.
        config: Pipeline configuration.

    Returns:
        List of boundary cell IDs.
    """
    logger.info("Detecting plate boundaries")

    # Build plate lookup
    plate_map: dict[str, TectonicPlate] = {p.id: p for p in plates}

    # 1. Find boundary edges
    logger.info("  Step 1/5: Finding boundary edges")
    boundary_edges = find_boundary_cells(mesh, cell_plate_map)
    logger.info("  Found %d boundary edges", len(boundary_edges))

    # 2. Segment-based classification (continuous boundary-type bands)
    logger.info("  Step 2/5: Classifying boundary segments")
    # Convert radius to cm for velocity calculations
    radius_cm = config.radius_km * 1e5
    boundary_cell_ids, cell_result = _classify_boundary_segments(
        mesh,
        boundary_edges,
        plate_map,
        cell_plate_map,
        radius_cm,
    )

    # 3. Write boundary properties to cells
    logger.info("  Step 3/5: Writing boundary properties to cells")
    for cid in boundary_cell_ids:
        btype, rate, tangential_fraction = cell_result[cid]
        mesh.cells[cid].convergence_rate_cm_yr = rate
        mesh.cells[cid].boundary_type = btype
        mesh.cells[cid].tangential_fraction = tangential_fraction

    # 4. BFS distance from boundary
    logger.info("  Step 4/5: Computing boundary distances (BFS)")
    compute_boundary_distance(mesh, boundary_cell_ids, config.radius_km)

    # 5. Propagate boundary type + convergence rate to all cells within
    #    the influence radius (3σ).  Without this step, cells just off the
    #    plate edge have distance_to_boundary_km set but boundary_type=None,
    #    so the terrain synthesizer skips them — creating sharp cliffs where
    #    a boundary cell gets full uplift and its immediate neighbour gets
    #    none.
    logger.info("  Step 5/5: Propagating boundary types to nearby cells")
    _propagate_boundary_type(mesh, boundary_cell_ids, config)

    # Summary
    n_convergent = sum(1 for c in boundary_cell_ids if mesh.cells[c].boundary_type == "convergent")
    n_divergent = sum(1 for c in boundary_cell_ids if mesh.cells[c].boundary_type == "divergent")
    n_transform = sum(1 for c in boundary_cell_ids if mesh.cells[c].boundary_type == "transform")
    logger.info(
        "Boundary detection complete: %d cells (%d convergent, %d divergent, %d transform)",
        len(boundary_cell_ids),
        n_convergent,
        n_divergent,
        n_transform,
    )

    return sorted(boundary_cell_ids)
