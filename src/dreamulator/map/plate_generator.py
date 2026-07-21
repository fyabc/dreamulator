"""Tectonic plate generation via flood-fill on the CVT mesh.

Pipeline:
    1. Select plate seed cells (random or predefined)
    2. Variable-speed parallel BFS flood-fill
    3. Assign crust types (continental / oceanic)
    4. Assign Euler poles (rotation axis + angular velocity)

See ``docs/usage/terrain-pipeline.md`` §3 for algorithm details.
"""

from __future__ import annotations

import heapq
import logging

import numpy as np

from .models import (
    CVTMesh,
    EulerPole,
    PlateType,
    TectonicPlate,
)
from .pipeline_types import TerrainPipelineConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Seed selection
# ---------------------------------------------------------------------------


def select_plate_seeds(
    mesh: CVTMesh,
    num_plates: int,
    rng: np.random.Generator,
) -> list[int]:
    """Select seed cells for tectonic plates.

    Picks *num_plates* random cells, ensuring they are well-spread by
    rejecting seeds too close to already-selected ones.

    Args:
        mesh: The CVT mesh.
        num_plates: Number of plates to create.
        rng: Random number generator.

    Returns:
        List of cell IDs to use as plate seeds.
    """
    n = mesh.num_cells
    if num_plates >= n:
        return list(range(n))

    candidates = list(range(n))
    rng.shuffle(candidates)

    seeds: list[int] = []
    min_angular_sep = np.sqrt(4 * np.pi / num_plates) * 0.3  # ~30% of avg spacing

    for cid in candidates:
        if len(seeds) >= num_plates:
            break

        cell = mesh.cells[cid]
        xyz = np.array([cell.x, cell.y, cell.z])

        # Check minimum angular separation from existing seeds
        too_close = False
        for sid in seeds:
            seed_xyz = np.array([mesh.cells[sid].x, mesh.cells[sid].y, mesh.cells[sid].z])
            dot = np.clip(np.dot(xyz, seed_xyz), -1, 1)
            angle = np.arccos(dot)
            if angle < min_angular_sep:
                too_close = True
                break

        if not too_close:
            seeds.append(cid)

    # If rejection sampling didn't find enough, just take remaining
    if len(seeds) < num_plates:
        for cid in candidates:
            if cid not in seeds:
                seeds.append(cid)
            if len(seeds) >= num_plates:
                break

    return seeds


# ---------------------------------------------------------------------------
# Flood-fill plate growth
# ---------------------------------------------------------------------------


def flood_fill_plates(
    mesh: CVTMesh,
    seeds: list[int],
    rng: np.random.Generator,
) -> dict[int, str]:
    """Grow plates from seeds using variable-speed BFS.

    Each plate has a random ``growth_speed_multiplier`` in [0.5, 2.0] that
    affects how fast it expands.  A priority queue (min-heap) ensures
    faster-growing plates claim more cells.

    Args:
        mesh: The CVT mesh.
        seeds: Cell IDs to use as plate seeds.
        rng: Random number generator.

    Returns:
        Dict mapping cell_id → plate_id.
    """
    num_plates = len(seeds)
    cell_plate_map: dict[int, str] = {}

    # Assign growth speeds
    growth_speeds = rng.uniform(0.5, 2.0, size=num_plates)

    # Priority queue: (cost, cell_id, plate_index)
    # Lower cost = higher priority.  Cost = 1 / speed.
    heap: list[tuple[float, int, int]] = []

    for i, seed_id in enumerate(seeds):
        plate_id = f"plate_{i:03d}"
        cell_plate_map[seed_id] = plate_id
        cost = 1.0 / growth_speeds[i]
        heapq.heappush(heap, (cost, seed_id, i))

    # BFS expansion
    step = 0
    while heap:
        cost, cell_id, plate_idx = heapq.heappop(heap)
        plate_id = f"plate_{plate_idx:03d}"

        for neighbor_id in mesh.cells[cell_id].neighbors:
            if neighbor_id not in cell_plate_map:
                cell_plate_map[neighbor_id] = plate_id
                new_cost = cost + 1.0 / growth_speeds[plate_idx]
                heapq.heappush(heap, (new_cost, neighbor_id, plate_idx))

        step += 1
        if step % 10000 == 0:
            logger.debug("  Flood-fill: %d / %d cells assigned", len(cell_plate_map), mesh.num_cells)

    # Verify completeness
    unassigned = mesh.num_cells - len(cell_plate_map)
    if unassigned > 0:
        logger.warning("  %d cells unassigned after flood-fill", unassigned)
        # Assign remaining to nearest plate
        for cid in range(mesh.num_cells):
            if cid not in cell_plate_map:
                for nid in mesh.cells[cid].neighbors:
                    if nid in cell_plate_map:
                        cell_plate_map[cid] = cell_plate_map[nid]
                        break

    return cell_plate_map


# ---------------------------------------------------------------------------
# Crust type assignment
# ---------------------------------------------------------------------------


def assign_crust_types(
    mesh: CVTMesh,
    cell_plate_map: dict[int, str],
    rng: np.random.Generator,
) -> None:
    """Assign crust types to cells based on their plate.

    Each plate gets a random continental_fraction in [0.1, 0.9].
    Cells in the continental fraction are assigned ``continental``,
    the rest ``oceanic``.

    Modifies ``mesh.cells[*].crust_type`` in-place.
    """
    # Group cells by plate
    plate_cells: dict[str, list[int]] = {}
    for cid, pid in cell_plate_map.items():
        plate_cells.setdefault(pid, []).append(cid)

    for plate_id, cell_ids in plate_cells.items():
        # Random continental fraction for this plate
        continental_fraction = rng.uniform(0.1, 0.9)

        # Sort cells by latitude (absolute) to prefer mid-latitudes for continents
        sorted_cells = sorted(cell_ids, key=lambda c: abs(mesh.cells[c].lat))

        n_cont = max(1, int(len(sorted_cells) * continental_fraction))
        for i, cid in enumerate(sorted_cells):
            if i < n_cont:
                mesh.cells[cid].crust_type = "continental"
            else:
                mesh.cells[cid].crust_type = "oceanic"


# ---------------------------------------------------------------------------
# Euler pole assignment
# ---------------------------------------------------------------------------


def assign_euler_poles(
    mesh: CVTMesh,
    cell_plate_map: dict[int, str],
    config: TerrainPipelineConfig,
    rng: np.random.Generator,
) -> list[TectonicPlate]:
    """Create TectonicPlate objects with random Euler poles.

    Each plate gets:
    - A random rotation axis (unit vector on sphere)
    - A random angular velocity derived from ``plate_speed_range_cm_yr``

    The Euler pole is placed such that the velocity at the plate centroid
    matches the desired speed and direction.
    """
    # Group cells by plate
    plate_cells: dict[str, list[int]] = {}
    for cid, pid in cell_plate_map.items():
        plate_cells.setdefault(pid, []).append(cid)

    speed_min = config.plate_speed_range_cm_yr[0]  # cm/year
    speed_max = config.plate_speed_range_cm_yr[1]

    # Convert cm/yr to rad/yr: speed / radius
    # radius in cm = radius_km * 1e5
    radius_cm = config.radius_km * 1e5

    plates: list[TectonicPlate] = []

    for plate_id, cell_ids in sorted(plate_cells.items()):
        plate_idx = int(plate_id.split("_")[1])

        # Random speed in range
        speed_cm_yr = rng.uniform(speed_min, speed_max)
        omega_rad_yr = speed_cm_yr / radius_cm

        # Plate centroid (for Euler pole placement)
        centroid = np.array([
            np.mean([mesh.cells[c].x for c in cell_ids]),
            np.mean([mesh.cells[c].y for c in cell_ids]),
            np.mean([mesh.cells[c].z for c in cell_ids]),
        ])
        centroid /= np.linalg.norm(centroid)

        # Random motion direction (perpendicular to centroid)
        # Pick a random vector, project out centroid component, normalize
        random_dir = rng.standard_normal(3)
        random_dir -= np.dot(random_dir, centroid) * centroid
        norm = np.linalg.norm(random_dir)
        if norm < 1e-12:
            random_dir = np.array([1.0, 0.0, 0.0])
            random_dir -= np.dot(random_dir, centroid) * centroid
            norm = np.linalg.norm(random_dir)
        motion_dir = random_dir / norm

        # Euler pole = rotation axis perpendicular to both centroid and motion
        # ω_axis = centroid × motion_dir (perpendicular to plate, gives motion)
        euler_axis = np.cross(centroid, motion_dir)
        euler_axis /= np.linalg.norm(euler_axis)

        # Determine plate type from majority crust
        n_cont = sum(1 for c in cell_ids if mesh.cells[c].crust_type == "continental")
        n_ocean = len(cell_ids) - n_cont
        if n_cont > 2 * n_ocean:
            plate_type = PlateType.CONTINENTAL
        elif n_ocean > 2 * n_cont:
            plate_type = PlateType.OCEANIC
        else:
            plate_type = PlateType.MIXED

        # Growth speed multiplier (used during flood-fill, stored for reproducibility)
        growth_speed = rng.uniform(0.5, 2.0)

        plate = TectonicPlate(
            id=plate_id,
            name=f"Plate {plate_idx + 1}",
            type=plate_type,
            cell_ids=sorted(cell_ids),
            euler_pole=EulerPole(
                x=float(euler_axis[0]),
                y=float(euler_axis[1]),
                z=float(euler_axis[2]),
                omega_rad_yr=omega_rad_yr,
            ),
            growth_speed_multiplier=growth_speed,
        )
        plates.append(plate)

        # Update cells with plate_id
        for cid in cell_ids:
            mesh.cells[cid].plate_id = plate_id

    return plates


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def generate_plates(
    mesh: CVTMesh,
    config: TerrainPipelineConfig,
) -> tuple[list[TectonicPlate], dict[int, str]]:
    """Generate tectonic plates on the CVT mesh.

    This is the main entry point for Stage 2 of the terrain pipeline.

    Args:
        mesh: The CVT mesh (modified in-place for cell.crust_type and cell.plate_id).
        config: Pipeline configuration.

    Returns:
        Tuple of (list of TectonicPlate, cell_id → plate_id mapping).
    """
    rng = np.random.default_rng(config.seed + 1)  # offset seed for variety

    logger.info("Generating %d tectonic plates", config.num_plates)

    # 1. Seed selection
    logger.info("  Step 1/4: Selecting plate seeds")
    seeds = select_plate_seeds(mesh, config.num_plates, rng)

    # 2. Flood-fill growth
    logger.info("  Step 2/4: Flood-fill plate growth")
    cell_plate_map = flood_fill_plates(mesh, seeds, rng)

    # 3. Crust type assignment
    logger.info("  Step 3/4: Assigning crust types")
    assign_crust_types(mesh, cell_plate_map, rng)

    # 4. Euler pole assignment
    logger.info("  Step 4/4: Assigning Euler poles")
    plates = assign_euler_poles(mesh, cell_plate_map, config, rng)

    # Log summary
    for plate in plates:
        n_cont = sum(1 for c in plate.cell_ids if mesh.cells[c].crust_type == "continental")
        logger.info(
            "  %s: %d cells (%d continental, %d oceanic), type=%s, speed=%.1f cm/yr",
            plate.id,
            len(plate.cell_ids),
            n_cont,
            len(plate.cell_ids) - n_cont,
            plate.type.value,
            plate.euler_pole.omega_rad_yr * config.radius_km * 1e5,
        )

    return plates, cell_plate_map
