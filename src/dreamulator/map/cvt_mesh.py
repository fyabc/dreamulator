"""Spherical CVT (Centroidal Voronoi Tessellation) mesh generation.

Pipeline:
    1. Fibonacci sphere spiral → uniform initial points
    2. Optional random jitter
    3. Lloyd relaxation iterations (Euclidean centroid → project to sphere)
    4. SphericalVoronoi computation
    5. Adjacency graph construction (Delaunay dual)
    6. Cell area computation (spherical polygon excess)

See ``docs/design/terrain-pipeline.md`` §2 for algorithm details.
"""

from __future__ import annotations

import itertools
import logging
from collections import defaultdict

import numpy as np
from scipy.spatial import SphericalVoronoi

from .models import CVTMesh, VoronoiCell
from .pipeline_types import TerrainPipelineConfig, xyz_to_lonlat

logger = logging.getLogger(__name__)

# Golden ratio for Fibonacci spiral
_PHI = (1 + np.sqrt(5)) / 2


# ---------------------------------------------------------------------------
# Point generation
# ---------------------------------------------------------------------------


def fibonacci_sphere(n: int) -> np.ndarray:
    """Generate *n* approximately uniform points on the unit sphere.

    Uses the Fibonacci spiral:
        φ_k = arccos(1 - 2(k + 0.5) / N)
        θ_k = 2π k / Φ

    Args:
        n: Number of points.

    Returns:
        Array of shape (n, 3) with unit vectors.
    """
    indices = np.arange(n, dtype=np.float64)
    phi = np.arccos(1 - 2 * (indices + 0.5) / n)  # polar angle [0, π]
    theta = 2 * np.pi * indices / _PHI  # azimuthal angle

    x = np.sin(phi) * np.cos(theta)
    y = np.cos(phi)  # y = up (north pole)
    z = np.sin(phi) * np.sin(theta)

    return np.column_stack([x, y, z])


def jitter_points(
    points: np.ndarray,
    sigma: float,
    rng: np.random.Generator,
) -> np.ndarray:
    """Apply random tangential displacement and re-project to sphere.

    Args:
        points: (n, 3) unit sphere points.
        sigma: Jitter magnitude as fraction of average cell spacing.
            Average cell spacing ≈ sqrt(4π / N).
        rng: Random number generator.

    Returns:
        Jittered points on unit sphere, shape (n, 3).
    """
    if sigma <= 0:
        return points.copy()

    n = len(points)
    avg_spacing = np.sqrt(4 * np.pi / n)
    noise_scale = sigma * avg_spacing

    # Random displacement in 3D
    noise = rng.standard_normal((n, 3)) * noise_scale

    # Add noise and re-project to unit sphere
    displaced = points + noise
    norms = np.linalg.norm(displaced, axis=1, keepdims=True)
    return displaced / np.maximum(norms, 1e-12)


# ---------------------------------------------------------------------------
# Lloyd relaxation
# ---------------------------------------------------------------------------


def lloyd_relaxation_step(points: np.ndarray) -> np.ndarray:
    """One step of Lloyd relaxation on the sphere.

    1. Compute SphericalVoronoi
    2. For each region, compute Euclidean centroid of vertices
    3. Project centroid back to unit sphere

    Args:
        points: (n, 3) current generator points on unit sphere.

    Returns:
        Relaxed points on unit sphere, shape (n, 3).
    """
    sv = SphericalVoronoi(points, radius=1.0, center=np.zeros(3))
    sv.sort_vertices_of_regions()

    n = len(points)
    regions = sv.regions

    # Stage 1.4: vectorized region centroids (was a per-region Python loop
    # with small numpy gathers — 8 × 100k iterations on gaia-m).
    region_lens = np.fromiter((len(r) for r in regions), dtype=np.int64, count=n)
    bad = region_lens == 0
    if not bad.all():
        bad |= np.fromiter(((-1 in r) for r in regions), dtype=bool, count=n)
    good_ids = np.where(~bad)[0]

    new_points = points.copy()  # degenerate regions keep original points
    if len(good_ids) > 0:
        counts = region_lens[good_ids]
        cell_of_flat = np.repeat(good_ids, counts)
        flat_idx = np.fromiter(
            itertools.chain.from_iterable(regions[i] for i in good_ids),
            dtype=np.int64,
            count=int(counts.sum()),
        )
        sums = np.zeros((n, 3), dtype=np.float64)
        np.add.at(sums, cell_of_flat, sv.vertices[flat_idx])
        centroids = sums[good_ids] / counts[:, None]
        norms = np.linalg.norm(centroids, axis=1)
        ok = norms >= 1e-12
        new_points[good_ids[ok]] = centroids[ok] / norms[ok, None]

    return new_points


def lloyd_relaxation(
    points: np.ndarray,
    iterations: int,
) -> np.ndarray:
    """Run multiple Lloyd relaxation steps.

    Args:
        points: (n, 3) initial generator points.
        iterations: Number of relaxation steps.

    Returns:
        Relaxed points on unit sphere.
    """
    try:
        from rich.progress import BarColumn, Progress, TextColumn
        _prog = Progress(
            TextColumn("  Lloyd relaxation"),
            BarColumn(),
            TextColumn("[dim]{task.completed}/{task.total}[/dim]"),
            transient=True,
        )
        _task = _prog.add_task("", total=iterations)
        _prog.start()
        for i in range(iterations):
            logger.debug("Lloyd relaxation step %d/%d", i + 1, iterations)
            points = lloyd_relaxation_step(points)
            _prog.update(_task, completed=i + 1)
        _prog.stop()
    except ImportError:
        for i in range(iterations):
            logger.debug("Lloyd relaxation step %d/%d", i + 1, iterations)
            points = lloyd_relaxation_step(points)
    return points


# ---------------------------------------------------------------------------
# Adjacency graph
# ---------------------------------------------------------------------------


def build_adjacency_graph(sv: SphericalVoronoi) -> dict[int, list[int]]:
    """Build cell adjacency graph from SphericalVoronoi (Delaunay dual).

    Two cells are adjacent if their Voronoi regions share an edge
    (i.e., at least two vertices in common).

    Args:
        sv: Computed SphericalVoronoi with sorted regions.

    Returns:
        Dict mapping cell index → list of adjacent cell indices.
    """
    n = len(sv.regions)

    # Build vertex → cells mapping
    vertex_to_cells: dict[int, list[int]] = defaultdict(list)
    for cell_id, region in enumerate(sv.regions):
        if region and -1 not in region:
            for v_idx in region:
                vertex_to_cells[v_idx].append(cell_id)

    # Two cells sharing ≥2 vertices are adjacent (share an edge)
    # Two cells sharing exactly 1 vertex are corner-neighbours (not edge-adjacent)
    adjacency: dict[int, set[int]] = defaultdict(set)

    # For each vertex, all cells meeting there are mutually adjacent
    # (on a well-formed spherical Voronoi, typically 3 cells meet at each vertex)
    for _v_idx, cells in vertex_to_cells.items():
        for i in range(len(cells)):
            for j in range(i + 1, len(cells)):
                adjacency[cells[i]].add(cells[j])
                adjacency[cells[j]].add(cells[i])

    # Convert to sorted lists
    return {i: sorted(adjacency.get(i, [])) for i in range(n)}


# ---------------------------------------------------------------------------
# Cell area computation
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def generate_cvt_mesh(config: TerrainPipelineConfig) -> CVTMesh:
    """Generate a complete CVT mesh for the given configuration.

    This is the main entry point for Stage 1 of the terrain pipeline.

    Args:
        config: Pipeline configuration.

    Returns:
        CVTMesh with cells, adjacency, vertices, and regions populated.
    """
    rng = np.random.default_rng(config.seed)
    n = config.num_nodes

    logger.info("Generating CVT mesh with %d nodes (seed=%d)", n, config.seed)

    # 1. Fibonacci sphere spiral
    logger.info("  Step 1/6: Fibonacci sphere spiral")
    points = fibonacci_sphere(n)

    # 2. Random jitter
    logger.info("  Step 2/6: Random jitter (σ=%.2f)", config.jitter_sigma)
    points = jitter_points(points, config.jitter_sigma, rng)

    # 3. Lloyd relaxation
    logger.info("  Step 3/6: Lloyd relaxation (%d iterations)", config.lloyd_iterations)
    if config.lloyd_iterations > 0:
        points = lloyd_relaxation(points, config.lloyd_iterations)

    # 4. SphericalVoronoi computation
    logger.info("  Step 4/6: SphericalVoronoi computation")
    sv = SphericalVoronoi(points, radius=1.0, center=np.zeros(3))
    sv.sort_vertices_of_regions()

    # 5. Adjacency graph
    logger.info("  Step 5/6: Adjacency graph construction")
    adjacency = build_adjacency_graph(sv)

    # 6. Build CVTMesh
    logger.info("  Step 6/6: Building CVTMesh object")
    cells = _build_cells(points, sv, adjacency, config.radius_km)
    vertices = sv.vertices.tolist()
    regions = [list(r) if r and -1 not in r else [] for r in sv.regions]

    # Adjacency keys must be strings for JSON serialization
    adj_str = {str(k): v for k, v in adjacency.items()}

    mesh = CVTMesh(
        seed=config.seed,
        num_cells=n,
        jitter_sigma=config.jitter_sigma,
        lloyd_iterations=config.lloyd_iterations,
        cells=cells,
        adjacency=adj_str,
        vertices=vertices,
        regions=regions,
    )

    logger.info(
        "CVT mesh complete: %d cells, %d vertices, %d edges",
        n,
        len(vertices),
        sum(len(v) for v in adjacency.values()) // 2,
    )
    return mesh


def _build_cells(
    points: np.ndarray,
    sv: SphericalVoronoi,
    adjacency: dict[int, list[int]],
    radius_km: float,
) -> list[VoronoiCell]:
    """Create VoronoiCell objects from generator points and SphericalVoronoi."""
    n = len(points)
    regions = sv.regions

    # Stage 1.4: vectorized spherical polygon areas via a flat triangle-fan
    # table across all cells (was a per-cell _spherical_polygon_area call
    # with an inner per-triangle numpy-scalar loop).
    region_lens = np.fromiter((len(r) for r in regions), dtype=np.int64, count=n)
    bad = region_lens == 0
    if not bad.all():
        bad |= np.fromiter(((-1 in r) for r in regions), dtype=bool, count=n)
    good_ids = np.where(~bad)[0]

    areas = np.zeros(n, dtype=np.float64)
    if len(good_ids) > 0:
        tri_owner: list[int] = []
        tri_idx: list[int] = []
        for i in good_ids:
            r = regions[i]
            for k in range(1, len(r) - 1):
                tri_owner.append(i)
                tri_idx.extend((r[0], r[k], r[k + 1]))
        owner = np.asarray(tri_owner, dtype=np.int64)
        tv = np.asarray(tri_idx, dtype=np.int64).reshape(-1, 3)
        v0 = sv.vertices[tv[:, 0]]
        v1 = sv.vertices[tv[:, 1]]
        v2 = sv.vertices[tv[:, 2]]
        # Signed solid angle of each triangle (v0, v1, v2) — L'Huilier form
        numerator = np.einsum("ij,ij->i", v0, np.cross(v1, v2))
        denominator = (
            1.0
            + np.einsum("ij,ij->i", v0, v1)
            + np.einsum("ij,ij->i", v1, v2)
            + np.einsum("ij,ij->i", v0, v2)
        )
        tri_area = np.zeros(len(owner), dtype=np.float64)
        ok = np.abs(denominator) >= 1e-15
        tri_area[ok] = 2.0 * np.arctan2(numerator[ok], denominator[ok])
        np.add.at(areas, owner, tri_area)
        areas = np.abs(areas) * radius_km**2

    cells: list[VoronoiCell] = []
    for i in range(n):
        x, y, z = float(points[i, 0]), float(points[i, 1]), float(points[i, 2])
        lon, lat = xyz_to_lonlat(x, y, z)
        cell = VoronoiCell(
            id=i,
            lon=float(lon),
            lat=float(lat),
            x=x,
            y=y,
            z=z,
            area_km2=float(areas[i]),
            neighbors=adjacency.get(i, []),
        )
        cells.append(cell)

    return cells
