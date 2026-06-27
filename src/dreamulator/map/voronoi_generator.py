"""Voronoi network generator — seed points, Lloyd relaxation, cell adjacency.

Generates a Voronoi tessellation on the equirectangular map plane.  Handles
longitude wrap-around by placing ghost points at lon±360 before computing
the diagram, then clipping results back to the [-180, 180] range.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from scipy.spatial import Delaunay, Voronoi

from .elevation_codec import lon_lat_to_pixel
from .models import VoronoiCell, VoronoiNetwork

if TYPE_CHECKING:
    from .models import MapMetadata, TectonicPlate


# ---------------------------------------------------------------------------
# Core generation
# ---------------------------------------------------------------------------


def generate_voronoi(
    width: int,
    height: int,
    seed: int,
    num_cells: int,
    relaxation_iterations: int = 3,
) -> VoronoiNetwork:
    """Generate a Voronoi network on an equirectangular map.

    Args:
        width: Map width in pixels (used only for aspect ratio).
        height: Map height in pixels.
        seed: RNG seed for reproducible generation.
        num_cells: Target number of cells.
        relaxation_iterations: Number of Lloyd relaxation passes.

    Returns:
        VoronoiNetwork with cells positioned in (lon, lat) space.
    """
    rng = np.random.default_rng(seed)
    aspect = width / height  # equirectangular aspect ratio (2:1 typically)

    # Generate initial points in normalised [0, 1] × [0, 1] space
    points = rng.random((num_cells, 2))
    # Scale x by aspect ratio to get uniform distribution in lon/lat
    points[:, 0] *= aspect

    # Lloyd relaxation
    for _ in range(relaxation_iterations):
        points = _lloyd_relax(points, aspect)

    # Convert from normalised to (lon, lat)
    lons = (points[:, 0] / aspect) * 360.0 - 180.0
    lats = 90.0 - points[:, 1] * 180.0

    # Compute Voronoi diagram for adjacency
    neighbors = _compute_adjacency(points)

    cells: list[VoronoiCell] = []
    for i in range(num_cells):
        cells.append(
            VoronoiCell(
                id=i,
                lon=float(lons[i]),
                lat=float(lats[i]),
                neighbors=sorted(neighbors.get(i, [])),
            )
        )

    return VoronoiNetwork(
        seed=seed,
        num_cells=num_cells,
        relaxation_iterations=relaxation_iterations,
        cells=cells,
    )


def _lloyd_relax(points: np.ndarray, aspect: float) -> np.ndarray:
    """Perform one iteration of Lloyd relaxation.

    Uses ghost points at x±aspect to handle horizontal wrap-around.

    Args:
        points: (N, 2) array in scaled normalised space.
        aspect: Width/height aspect ratio.

    Returns:
        Relaxed (N, 2) array.
    """
    n = len(points)

    # Create ghost points for wrap-around
    ghosts_left = points.copy()
    ghosts_left[:, 0] -= aspect
    ghosts_right = points.copy()
    ghosts_right[:, 0] += aspect

    all_points = np.vstack([points, ghosts_left, ghosts_right])

    vor = Voronoi(all_points)

    new_points = np.empty_like(points)
    for i in range(n):
        region_idx = vor.point_region[i]
        region = vor.regions[region_idx]
        if not region or -1 in region:
            # Boundary region — keep original point
            new_points[i] = points[i]
            continue

        vertices = vor.vertices[region]
        centroid = vertices.mean(axis=0)

        # Wrap x back to [0, aspect]
        cx = centroid[0] % aspect
        cy = np.clip(centroid[1], 0.0, 1.0)
        new_points[i] = [cx, cy]

    return new_points


def _compute_adjacency(points: np.ndarray) -> dict[int, list[int]]:
    """Compute cell adjacency using Delaunay triangulation.

    Uses ghost points for wrap-around, then maps ghost indices back.

    Args:
        points: (N, 2) array in scaled normalised space.

    Returns:
        Dict mapping cell_id → list of neighbour cell_ids.
    """
    n = len(points)
    aspect = points[:, 0].max() - points[:, 0].min()
    if aspect < 0.01:
        aspect = 2.0  # fallback

    # Ghost points for wrap-around
    ghosts_left = points.copy()
    ghosts_left[:, 0] -= aspect
    ghosts_right = points.copy()
    ghosts_right[:, 0] += aspect

    all_points = np.vstack([points, ghosts_left, ghosts_right])

    tri = Delaunay(all_points)

    adj: dict[int, set[int]] = {i: set() for i in range(n)}

    for simplex in tri.simplices:
        for a in simplex:
            for b in simplex:
                if a != b:
                    # Map ghost indices back to real indices
                    ra = a % n
                    rb = b % n
                    if ra != rb:
                        adj[ra].add(rb)

    return {k: sorted(v) for k, v in adj.items()}


# ---------------------------------------------------------------------------
# Heightmap sampling
# ---------------------------------------------------------------------------


def sample_heightmap(
    network: VoronoiNetwork,
    elevation: np.ndarray,
    elevation_min_m: float = -11_000.0,
    elevation_max_m: float = 9_000.0,
) -> VoronoiNetwork:
    """Sample elevation values from the heightmap for each Voronoi cell.

    Args:
        network: Voronoi network with cell positions.
        elevation: 2-D normalised heightmap array.
        elevation_min_m: Minimum elevation in metres (unused, for API compat).
        elevation_max_m: Maximum elevation in metres (unused, for API compat).

    Returns:
        Updated network with elevation values filled in.
    """
    h, w = elevation.shape
    updated_cells: list[VoronoiCell] = []
    for cell in network.cells:
        x, y = lon_lat_to_pixel(cell.lon, cell.lat, w, h)
        updated_cells.append(
            cell.model_copy(
                update={"elevation": float(elevation[y, x])},
            )
        )
    return network.model_copy(update={"cells": updated_cells})


# ---------------------------------------------------------------------------
# Plate assignment
# ---------------------------------------------------------------------------


def assign_cells_to_plates(
    network: VoronoiNetwork,
    num_plates: int,
    sea_level: float,
    rng: np.random.Generator | None = None,
) -> list[TectonicPlate]:
    """Assign Voronoi cells to tectonic plates using flood-fill from seeds.

    Args:
        network: Voronoi network (with elevation sampled).
        num_plates: Number of plates to create.
        sea_level: Normalised sea level (cells below → oceanic tendency).
        rng: Optional RNG for reproducibility.

    Returns:
        List of TectonicPlate objects.
    """
    from .models import PlateType, PlateVelocity, TectonicPlate

    if rng is None:
        rng = np.random.default_rng(42)

    n = network.num_cells
    if n == 0 or num_plates == 0:
        return []

    # Pick random seed cells for each plate
    seeds = rng.choice(n, size=min(num_plates, n), replace=False).tolist()

    # Flood-fill from seeds
    assignments = np.full(n, -1, dtype=np.int32)
    queue: list[tuple[int, int]] = []  # (cell_id, plate_idx)
    for plate_idx, seed_cell in enumerate(seeds):
        assignments[seed_cell] = plate_idx
        queue.append((seed_cell, plate_idx))

    head = 0
    while head < len(queue):
        cell_id, plate_idx = queue[head]
        head += 1
        for nb in network.cells[cell_id].neighbors:
            if assignments[nb] == -1:
                assignments[nb] = plate_idx
                queue.append((nb, plate_idx))

    # Group cells by plate
    plate_cells: dict[int, list[int]] = {i: [] for i in range(len(seeds))}
    for cell_id in range(n):
        pid = assignments[cell_id]
        if pid >= 0:
            plate_cells[pid].append(cell_id)

    # Classify plates as oceanic/continental based on mean elevation
    plates: list[TectonicPlate] = []
    for plate_idx in range(len(seeds)):
        cells = plate_cells[plate_idx]
        if not cells:
            continue

        mean_elev = float(np.mean([network.cells[c].elevation for c in cells]))
        plate_type = PlateType.OCEANIC if mean_elev < sea_level else PlateType.CONTINENTAL

        # Check if mixed (significant portion on both sides of sea level)
        above = sum(1 for c in cells if network.cells[c].elevation >= sea_level)
        ratio = above / len(cells)
        if 0.2 < ratio < 0.8:
            plate_type = PlateType.MIXED

        plates.append(
            TectonicPlate(
                id=f"plate_{plate_idx}",
                name=f"Plate {plate_idx}",
                type=plate_type,
                cell_ids=cells,
                velocity=PlateVelocity(
                    dx=float(rng.uniform(-0.05, 0.05)),
                    dy=float(rng.uniform(-0.05, 0.05)),
                ),
            )
        )

    return plates
