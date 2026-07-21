"""Plate boundary detection and classification.

Pipeline:
    1. Identify boundary cells (neighbours belong to different plates)
    2. Compute relative plate velocity at each boundary cell
    3. Decompose into normal (convergent/divergent) and tangential (transform)
    4. Classify boundary type
    5. BFS distance-from-boundary for all cells

See ``docs/usage/terrain-pipeline.md`` §4 for algorithm details.

Key formulas:
    v(P) = ω × P          (rigid-body velocity from Euler pole)
    v_rel = v_A(P) - v_B(P)
    v_n = v_rel · n̂       (normal component)
    v_t = |v_rel - v_n·n̂| (tangential component)
"""

from __future__ import annotations

import logging
from collections import deque

import numpy as np

from .models import CVTMesh, TectonicPlate
from .pipeline_types import TerrainPipelineConfig

logger = logging.getLogger(__name__)

# Threshold for boundary classification (cm/year)
_CONVERGENT_THRESHOLD = 0.5  # cm/yr
_TRANSFORM_THRESHOLD = 0.3  # ratio of tangential to total


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
    return plate_velocity_at(point_xyz, plate_a) - plate_velocity_at(point_xyz, plate_b)


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
    return direction / norm


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
    """Classify a boundary segment based on velocity decomposition.

    Args:
        v_n: Normal velocity component (positive = convergent).
        v_t: Tangential velocity component.
        v_total: Total velocity magnitude.

    Returns:
        "convergent", "divergent", or "transform".
    """
    if v_total < 1e-12:
        return "transform"

    # Transform if tangential dominates
    if v_t / v_total > (1 - _TRANSFORM_THRESHOLD):
        return "transform"

    if v_n > _CONVERGENT_THRESHOLD:
        return "convergent"
    elif v_n < -_CONVERGENT_THRESHOLD:
        return "divergent"
    else:
        return "transform"


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
    logger.info("  Step 1/4: Finding boundary edges")
    boundary_edges = find_boundary_cells(mesh, cell_plate_map)
    logger.info("  Found %d boundary edges", len(boundary_edges))

    # 2. Compute velocities and classify
    logger.info("  Step 2/4: Computing velocities and classifying boundaries")
    boundary_cell_ids: set[int] = set()
    # Convert radius to cm for velocity calculations
    radius_cm = config.radius_km * 1e5

    # Track per-cell accumulated boundary properties
    cell_v_n: dict[int, list[float]] = {}
    cell_btype: dict[int, list[str]] = {}

    for cell_id, neighbor_id, plate_a_id, plate_b_id in boundary_edges:
        plate_a = plate_map.get(plate_a_id)
        plate_b = plate_map.get(plate_b_id)
        if plate_a is None or plate_b is None:
            continue

        cell = mesh.cells[cell_id]
        neighbor = mesh.cells[neighbor_id]

        cell_xyz = np.array([cell.x, cell.y, cell.z])
        neighbor_xyz = np.array([neighbor.x, neighbor.y, neighbor.z])

        # Relative velocity
        v_rel = compute_relative_velocity(cell_xyz, plate_a, plate_b)

        # Boundary normal (from cell toward neighbor)
        n_hat = compute_boundary_normal(cell_xyz, neighbor_xyz)

        # Normal and tangential components
        v_n = float(np.dot(v_rel, n_hat))
        v_t_vec = v_rel - v_n * n_hat
        v_t = float(np.linalg.norm(v_t_vec))
        v_total = float(np.linalg.norm(v_rel))

        # Convert from rad/yr to cm/yr
        v_n_cm_yr = v_n * radius_cm
        v_t_cm_yr = v_t * radius_cm
        v_total_cm_yr = v_total * radius_cm

        btype = classify_boundary(v_n_cm_yr, v_t_cm_yr, v_total_cm_yr)

        boundary_cell_ids.add(cell_id)
        cell_v_n.setdefault(cell_id, []).append(v_n_cm_yr)
        cell_btype.setdefault(cell_id, []).append(btype)

    # 3. Write boundary properties to cells
    logger.info("  Step 3/4: Writing boundary properties to cells")
    for cid in boundary_cell_ids:
        # Average convergence rate
        rates = cell_v_n.get(cid, [0.0])
        mesh.cells[cid].convergence_rate_cm_yr = sum(rates) / len(rates)

        # Most common boundary type
        types = cell_btype.get(cid, ["transform"])
        from collections import Counter

        mesh.cells[cid].boundary_type = Counter(types).most_common(1)[0][0]

    # 4. BFS distance from boundary
    logger.info("  Step 4/4: Computing boundary distances (BFS)")
    compute_boundary_distance(mesh, boundary_cell_ids, config.radius_km)

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
