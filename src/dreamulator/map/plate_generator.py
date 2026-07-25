"""Tectonic plate generation on the spherical CVT mesh.

Algorithm (Cortial et al. 2019, "Procedural Tectonic Planets")
--------------------------------------------------------------
    1. Poisson-disc seed selection on the sphere
    2. Synchronous multi-source BFS → spherical Voronoi partition
    3. Boundary noise perturbation → organic edges
    4. Assign crust types (continental / oceanic)
    5. Assign Euler poles (rotation axis + angular velocity)

Step 3 follows Cortial et al. §3 "noise-warped geodetic distance":
a fraction of boundary cells are randomly reassigned to adjacent
plates, turning straight Voronoi edges into natural, irregular
boundaries.

References
----------
* Cortial, Y., Peytavie, A., Galin, E., & Guérin, E. (2019). Procedural
  Tectonic Planets. Computer Graphics Forum (Eurographics), 38(2), 1–11.
  https://doi.org/10.1111/cgf.13614
* weigert/SimpleTectonics — Poisson disc + GPU Voronoi.
  https://github.com/weigert/SimpleTectonics
"""

from __future__ import annotations

import logging
from collections import deque

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
# Seed selection — Poisson-disc on sphere
# ---------------------------------------------------------------------------


def select_plate_seeds(
    mesh: CVTMesh,
    num_plates: int,
    rng: np.random.Generator,
) -> list[int]:
    """Select seed cells for tectonic plates (Poisson-disc on sphere).

    Picks *num_plates* random cells, rejecting candidates too close to
    already-selected seeds.  This produces a well-spread distribution so
    Voronoi cells have natural size variation without extreme outliers.

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
    # Minimum angular separation: ~30% of the average spacing for N points
    # on a unit sphere (√(4π/N)).
    min_angular_sep = np.sqrt(4 * np.pi / num_plates) * 0.3

    for cid in candidates:
        if len(seeds) >= num_plates:
            break

        cell = mesh.cells[cid]
        xyz = np.array([cell.x, cell.y, cell.z])

        too_close = False
        for sid in seeds:
            seed_xyz = np.array([
                mesh.cells[sid].x, mesh.cells[sid].y, mesh.cells[sid].z,
            ])
            dot = np.clip(np.dot(xyz, seed_xyz), -1, 1)
            if np.arccos(dot) < min_angular_sep:
                too_close = True
                break

        if not too_close:
            seeds.append(cid)

    # Fallback: if rejection sampling didn't find enough, take remaining
    if len(seeds) < num_plates:
        for cid in candidates:
            if cid not in seeds:
                seeds.append(cid)
            if len(seeds) >= num_plates:
                break

    return seeds


# ---------------------------------------------------------------------------
# Spherical Voronoi partition — synchronous multi-source BFS
# ---------------------------------------------------------------------------
#
# Cortial et al. (2019) §3: each surface point is assigned to the nearest
# seed centroid, producing a spherical Voronoi diagram.  On the CVT graph
# we compute this via synchronous BFS — all seeds expand one layer per
# round, so every cell joins the plate whose wavefront reaches it first.
# Voronoi cells are convex in graph space → plates never enclose each other.


def _voronoi_partition(
    mesh: CVTMesh,
    seeds: list[int],
) -> dict[int, str]:
    """Synchronous multi-source BFS — spherical Voronoi on the CVT graph.

    All seeds expand one layer per round.  Cells are assigned to the plate
    whose wavefront reaches them first.  Complexity: O(N) — each cell and
    edge is visited exactly once.

    Returns:
        Dict mapping cell_id → plate_id.
    """
    num_plates = len(seeds)
    cell_plate_map: dict[int, str] = {}

    # One FIFO queue per plate, initialised with the seed cell
    queues: list[deque[int]] = [deque([s]) for s in seeds]
    for i, seed_id in enumerate(seeds):
        cell_plate_map[seed_id] = f"plate_{i:03d}"

    total_assigned = num_plates
    round_num = 0

    while total_assigned < mesh.num_cells:
        round_num += 1

        for plate_idx in range(num_plates):
            q = queues[plate_idx]
            if not q:
                continue  # this plate is saturated

            plate_id = f"plate_{plate_idx:03d}"
            # Process exactly one layer: all cells currently in q
            for _ in range(len(q)):
                cell_id = q.popleft()
                for neighbor_id in mesh.cells[cell_id].neighbors:
                    if neighbor_id not in cell_plate_map:
                        cell_plate_map[neighbor_id] = plate_id
                        q.append(neighbor_id)
                        total_assigned += 1

        if round_num % 2 == 0:
            logger.debug(
                "  Voronoi BFS round %d: %d / %d cells",
                round_num, total_assigned, mesh.num_cells,
            )

    logger.info(
        "  Voronoi BFS: %d rounds, %d cells assigned",
        round_num, total_assigned,
    )
    return cell_plate_map


def _relax_boundaries(
    mesh: CVTMesh,
    cell_plate_map: dict[int, str],
    strength: float,
    rng: np.random.Generator,
) -> None:
    """Laplacian boundary smoothing — arc-like edges via majority voting.

    Real plate boundaries (Japan, Andes, Aleutians) are *arcs*, not jagged
    cell-edge staircases.  We approximate this with iterative Laplacian
    relaxation: each boundary cell looks at its neighbours and adopts the
    plate that would make the local boundary smoother.

    *strength* = 0.0 keeps the raw Voronoi boundaries (straight cell edges).
    Values around 0.05–0.15 produce natural, arc-like boundaries.  Internally
    the strength controls the number of smoothing passes (1–5).

    Modifies *cell_plate_map* in-place.
    """
    if strength <= 0.0:
        return

    # Strength → number of smoothing passes
    passes = max(1, min(5, round(strength * 30)))

    for p in range(passes):
        # Find current boundary cells
        boundary: list[int] = []
        for cid, pid in cell_plate_map.items():
            for nid in mesh.cells[cid].neighbors:
                if cell_plate_map.get(nid, "") != pid:
                    boundary.append(cid)
                    break

        rng.shuffle(boundary)  # avoid systematic bias per pass

        flipped = 0
        for cid in boundary:
            pid = cell_plate_map[cid]

            # Tally neighbour-plate votes
            votes: dict[str, int] = {}
            for nid in mesh.cells[cid].neighbors:
                npid = cell_plate_map.get(nid, "")
                if npid:
                    votes[npid] = votes.get(npid, 0) + 1

            own = votes.get(pid, 0)
            # Best alternative plate (exclude own)
            best = max(
                ((v, p) for p, v in votes.items() if p != pid),
                default=(0, pid),
            )

            # Require a clear majority (≥2 more votes) to flip.
            # This prevents oscillation and ensures only "obvious" flips.
            if best[0] >= own + 2:
                cell_plate_map[cid] = best[1]
                flipped += 1

        if flipped > 0:
            logger.debug(
                "  Smoothing pass %d/%d: %d cells flipped",
                p + 1, passes, flipped,
            )
        else:
            break  # converged — no more obvious flips

    logger.info(
        "  Boundary smoothing: %d passes (strength=%.2f)",
        p + 1, strength,
    )


# ---------------------------------------------------------------------------
# Crust type assignment
# ---------------------------------------------------------------------------


def assign_crust_types(
    mesh: CVTMesh,
    cell_plate_map: dict[int, str],
    rng: np.random.Generator,
) -> None:
    """Assign crust types to cells based on their plate.

    Each plate gets a random continental fraction in [0.1, 0.9].
    3D simplex noise (OpenSimplex) sampled at cell positions produces
    spatially coherent continental blocks — adjacent cells get similar
    noise values, so continents are contiguous, not scattered.

    Latitude bias: lower latitudes are weighted toward continental
    (Earth-like continent distribution).

    References
    ----------
    * Perlin, K. (2001). "Noise Hardware." In *Real-Time Shading*
      (SIGGRAPH Course Notes). — original simplex noise algorithm.
    * Spencer, K. (2014). OpenSimplex — patent-free simplex noise
      implementation. https://github.com/KdotJPG/OpenSimplex2
    * Musgrave, F.K., Kolb, C.E., & Mace, R.S. (1989). "The synthesis
      and rendering of eroded fractal terrains." *SIGGRAPH '89*.
      — using coherent noise for natural-looking terrain features.

    Modifies ``mesh.cells[*].crust_type`` in-place.
    """
    plate_cells: dict[str, list[int]] = {}
    for cid, pid in cell_plate_map.items():
        plate_cells.setdefault(pid, []).append(cid)

    # Spatial noise generator for coherent crust assignment.
    # Using 3D simplex noise at cell positions ensures neighbouring cells
    # get similar values → contiguous continental blocks, not salt-and-pepper.
    try:
        import opensimplex
        _has_noise = True
    except ImportError:
        _has_noise = False

    for plate_id, cell_ids in plate_cells.items():
        continental_fraction = rng.uniform(0.1, 0.9)
        n_cont = max(1, int(len(cell_ids) * continental_fraction))

        if _has_noise:
            # Spatial noise: coherent values for adjacent cells
            noise_seed = rng.integers(0, 1 << 20)  # < 2^20 avoids opensimplex overflow warning
            opensimplex.seed(noise_seed)
            # Noise scale: ~1 cell → large coherent blobs
            scale = 0.6
            # Latitude bias: equatorial preference (Earth-like)
            noise_vals = np.array([
                opensimplex.noise3(
                    float(mesh.cells[c].x * scale),
                    float(mesh.cells[c].y * scale),
                    float(mesh.cells[c].z * scale),
                ) - 0.3 * abs(mesh.cells[c].lat) / 90.0
                for c in cell_ids
            ])
        else:
            # Fallback: latitude-weighted + mild spatial jitter
            noise_vals = np.array([
                1.0 - 0.5 * abs(mesh.cells[c].lat) / 90.0
                + rng.uniform(-0.15, 0.15)
                for c in cell_ids
            ])

        # Top N by noise value → continental (threshold varies per plate)
        sorted_idx = np.argsort(noise_vals)[::-1]
        for rank, idx in enumerate(sorted_idx):
            cid = cell_ids[idx]
            if rank < n_cont:
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

    Each plate receives:
    - A random rotation axis (unit vector on the sphere).
    - An angular velocity derived from ``plate_speed_range_cm_yr``.
    - Plate type determined by majority crust.

    Plate speed defaults from Cortial 2019: 1–10 cm/yr, with
    v₀ = 100 mm/yr as the maximum reference speed.
    """
    plate_cells: dict[str, list[int]] = {}
    for cid, pid in cell_plate_map.items():
        plate_cells.setdefault(pid, []).append(cid)

    speed_min, speed_max = config.plate_speed_range_cm_yr
    radius_cm = config.radius_km * 1e5  # for cm/yr → rad/yr conversion

    plates: list[TectonicPlate] = []

    for plate_id, cell_ids in sorted(plate_cells.items()):
        plate_idx = int(plate_id.split("_")[1])

        speed_cm_yr = rng.uniform(speed_min, speed_max)
        omega_rad_yr = speed_cm_yr / radius_cm

        # Plate centroid (unit vector)
        centroid = np.array([
            np.mean([mesh.cells[c].x for c in cell_ids]),
            np.mean([mesh.cells[c].y for c in cell_ids]),
            np.mean([mesh.cells[c].z for c in cell_ids]),
        ])
        centroid /= np.linalg.norm(centroid)

        # Random motion direction (perpendicular to centroid)
        random_dir = rng.standard_normal(3)
        random_dir -= np.dot(random_dir, centroid) * centroid
        norm = np.linalg.norm(random_dir)
        if norm < 1e-12:
            random_dir = np.array([1.0, 0.0, 0.0])
            random_dir -= np.dot(random_dir, centroid) * centroid
            norm = np.linalg.norm(random_dir)
        motion_dir = random_dir / norm

        # Euler pole axis ← centroid × motion_dir
        euler_axis = np.cross(centroid, motion_dir)
        euler_axis /= np.linalg.norm(euler_axis)

        # Plate type from majority crust
        n_cont = sum(
            1 for c in cell_ids if mesh.cells[c].crust_type == "continental"
        )
        n_ocean = len(cell_ids) - n_cont
        if n_cont > 2 * n_ocean:
            plate_type = PlateType.CONTINENTAL
        elif n_ocean > 2 * n_cont:
            plate_type = PlateType.OCEANIC
        else:
            plate_type = PlateType.MIXED

        plates.append(TectonicPlate(
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
            growth_speed_multiplier=1.0,
        ))

        # Update mesh cells with plate_id
        for cid in cell_ids:
            mesh.cells[cid].plate_id = plate_id

    return plates


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Strategy registry
# ---------------------------------------------------------------------------
#
# Each plate algorithm is a callable (mesh, config) → (plates, cell_map).
# Add new algorithms here and reference them by name in ``plate_algorithm``.


_PLATE_ALGORITHMS: dict[str, str] = {
    "cortial2019": "cortial2019",
}


def _generate_cortial2019(
    mesh: CVTMesh,
    config: TerrainPipelineConfig,
) -> tuple[list[TectonicPlate], dict[int, str]]:
    """Cortial et al. (2019) §3 — Poisson-disc + spherical Voronoi."""
    return _generate_plates_impl(mesh, config)


def generate_plates(
    mesh: CVTMesh,
    config: TerrainPipelineConfig,
) -> tuple[list[TectonicPlate], dict[int, str]]:
    """Generate tectonic plates on the spherical CVT mesh.

    Dispatches to the algorithm named in ``config.plate_algorithm``.
    Currently supported:

    ``"cortial2019"`` (default)
        Poisson-disc seed selection → synchronous Voronoi BFS → boundary
        smoothing → crust types → Euler poles.  Follows Cortial et al.
        (2019) *Procedural Tectonic Planets* §3.

    Args:
        mesh: CVT mesh (modified in-place).
        config: Pipeline configuration.

    Returns:
        Tuple of (list of TectonicPlate, cell_id → plate_id mapping).
    """
    algo = config.plate_algorithm
    if algo not in _PLATE_ALGORITHMS:
        raise ValueError(
            f"Unknown plate algorithm '{algo}'. "
            f"Available: {sorted(_PLATE_ALGORITHMS.keys())}"
        )
    if algo == "cortial2019":
        return _generate_cortial2019(mesh, config)
    raise ValueError(f"Plate algorithm '{algo}' not implemented")  # unreachable


def _generate_plates_impl(
    mesh: CVTMesh,
    config: TerrainPipelineConfig,
) -> tuple[list[TectonicPlate], dict[int, str]]:
    """Internal implementation — Cortial 2019 Voronoi partition."""
    rng = np.random.default_rng(config.seed + 1)

    logger.info("Generating %d tectonic plates", config.num_plates)

    # 1. Seed selection
    logger.info("  Step 1/4: Selecting plate seeds")
    seeds = select_plate_seeds(mesh, config.num_plates, rng)

    # 2. Spherical Voronoi partition (Cortial 2019 §3)
    logger.info("  Step 2/5: Spherical Voronoi partition")
    cell_plate_map = _voronoi_partition(mesh, seeds)

    # 3. Boundary smoothing (Cortial 2019 "noise-warped geodetic distance")
    logger.info("  Step 3/5: Boundary smoothing (strength=%.2f)",
                config.boundary_noise)
    _relax_boundaries(mesh, cell_plate_map, config.boundary_noise, rng)

    # Log plate size distribution
    plate_sizes = sorted(
        [sum(1 for v in cell_plate_map.values() if v == f"plate_{i:03d}")
         for i in range(config.num_plates)],
        reverse=True,
    )
    logger.info(
        "  Plate sizes (cells): %s",
        ", ".join(f"{s:4d}" for s in plate_sizes),
    )

    # 4. Crust types
    logger.info("  Step 4/5: Assigning crust types")
    assign_crust_types(mesh, cell_plate_map, rng)

    # 5. Euler poles
    logger.info("  Step 5/5: Assigning Euler poles")
    plates = assign_euler_poles(mesh, cell_plate_map, config, rng)

    for plate in plates:
        n_cont = sum(
            1 for c in plate.cell_ids
            if mesh.cells[c].crust_type == "continental"
        )
        logger.info(
            "  %s: %d cells (%d continental, %d oceanic), "
            "type=%s, speed=%.1f cm/yr",
            plate.id, len(plate.cell_ids),
            n_cont, len(plate.cell_ids) - n_cont,
            plate.type.value,
            plate.euler_pole.omega_rad_yr * config.radius_km * 1e5,
        )

    return plates, cell_plate_map
