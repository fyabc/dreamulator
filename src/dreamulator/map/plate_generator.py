"""Tectonic plate generation on the spherical CVT mesh.

Algorithm (Cortial et al. 2019, "Procedural Tectonic Planets")
--------------------------------------------------------------
    1. Poisson-disc seed selection on the sphere
    2. Synchronous multi-source BFS → spherical Voronoi partition
    3. Boundary noise perturbation → organic edges
    4. Assign crust types via 5-octave fBm (continental / oceanic)
       — fractal coastlines with detail at all resolvable scales
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
* Mandelbrot, B.B. (1967). "How Long Is the Coast of Britain? Statistical
  Self-Similarity and Fractional Dimension." *Science*, 156(3775), 636–638.
  — coastlines are fractal; fBm noise produces statistically self-similar
  crust boundaries (step 4, ``assign_crust_types``).
* weigert/SimpleTectonics — Poisson disc + GPU Voronoi.
  https://github.com/weigert/SimpleTectonics
"""

from __future__ import annotations

import logging
from collections import deque
from typing import TYPE_CHECKING

import numpy as np

from .models import (
    CVTMesh,
    EulerPole,
    PlateType,
    TectonicPlate,
)
from .pipeline_types import lonlat_to_xyz

if TYPE_CHECKING:
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
    """Select seed cells for tectonic plates (variable-density Poisson-disc).

    Picks *num_plates* random cells, rejecting candidates too close to
    already-selected seeds.  Each seed draws a random "size factor" that scales
    its minimum spacing, so seeds land at NON-uniform density and the resulting
    Voronoi plates have a skewed size distribution (a few large plates + several
    small ones), closer to Earth's power-law plate-size distribution than the
    near-equal sizes a uniform Poisson-disc sampling gives.

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
    seed_sep: list[float] = []
    # Base minimum angular separation: ~30% of the average spacing for N points
    # on a unit sphere (√(4π/N)).  Each seed scales this by a log-uniform size
    # factor — a large factor keeps neighbours far away (big plate), a small one
    # allows close packing (small plate).
    base_sep = np.sqrt(4 * np.pi / num_plates) * 0.3

    for cid in candidates:
        if len(seeds) >= num_plates:
            break

        cell = mesh.cells[cid]
        xyz = np.array([cell.x, cell.y, cell.z])
        size_factor = float(np.exp(rng.uniform(-0.8, 0.8)))  # ~0.45–2.2
        sep = base_sep * size_factor

        too_close = False
        for sid in seeds:
            seed_xyz = np.array(
                [
                    mesh.cells[sid].x,
                    mesh.cells[sid].y,
                    mesh.cells[sid].z,
                ]
            )
            dot = np.clip(np.dot(xyz, seed_xyz), -1, 1)
            # Use the candidate's own spacing: small-spacing seeds can nestle
            # close to existing seeds (small plates), large-spacing seeds keep
            # clear (large plates) → skewed size distribution.
            if np.arccos(dot) < sep:
                too_close = True
                break

        if not too_close:
            seeds.append(cid)
            seed_sep.append(sep)

    # Fallback: if rejection sampling didn't find enough, take remaining
    if len(seeds) < num_plates:
        for cid in candidates:
            if cid not in seeds:
                seeds.append(cid)
            if len(seeds) >= num_plates:
                break

    return seeds


def _connected_components(mesh: CVTMesh, labels: np.ndarray) -> list[list[int]]:
    """Connected components of the cells where ``labels[i]`` is True.

    Deterministic: cells are swept in index order and components are returned
    in first-touch order (ties broken by cell index).
    """
    n = mesh.num_cells
    comps: list[list[int]] = []
    seen = np.zeros(n, dtype=np.bool_)
    for start in range(n):
        if not labels[start] or seen[start]:
            continue
        comp: list[int] = []
        stack = [start]
        seen[start] = True
        while stack:
            cid = stack.pop()
            comp.append(cid)
            for nb in mesh.cells[cid].neighbors:
                if labels[nb] and not seen[nb]:
                    seen[nb] = True
                    stack.append(nb)
        comps.append(comp)
    return comps


def select_geography_seeds(
    mesh: CVTMesh,
    mask: np.ndarray,
    field: np.ndarray,
    num_plates: int,
) -> list[int]:
    """Select plate seeds aligned to authored geography (§5 方案 2).

    Continents are plates and oceans are plates: each connected continental or
    oceanic region of at least ``0.5%`` of the surface gets one seed at its
    interior (the cell with the largest ``|field|`` — deepest land or deepest
    ocean).  Remaining seeds are placed by farthest-point sampling over non-coast
    cells, spreading plates evenly while keeping every seed off a coastline.  The
    resulting Voronoi partition has boundaries near continental margins instead of
    through continent interiors / ocean basins.

    Fully deterministic (no RNG): component order follows cell index, and the
    interior/farthest picks use ``max``/``argmax`` with stable tie-breaking.
    """
    n = mesh.num_cells
    xyz = mesh.cell_xyz

    # Non-coast cells: every neighbour has the same crust type.
    interior = np.ones(n, dtype=np.bool_)
    for i in range(n):
        for nb in mesh.cells[i].neighbors:
            if mask[nb] != mask[i]:
                interior[i] = False
                break

    min_size = max(1, int(n * 0.005))
    comps = _connected_components(mesh, mask) + _connected_components(mesh, ~mask)
    comps = [c for c in comps if len(c) >= min_size]
    comps.sort(key=len, reverse=True)

    seeds: list[int] = []
    used: set[int] = set()
    for comp in comps:
        if len(seeds) >= num_plates:
            break
        cands = [i for i in comp if interior[i]] or comp
        best = max(cands, key=lambda i: abs(field[i]))
        if best in used:
            continue
        seeds.append(best)
        used.add(best)

    # Farthest-point sampling over the remaining non-coast cells to reach
    # ``num_plates``.  This splits the largest regions further while keeping a
    # near-uniform spread (and the power-law size skew is inherited from the
    # component sizes, not the seed spacing).
    cand_idx = np.array([i for i in range(n) if interior[i] and i not in used], dtype=np.int64)
    if not seeds and len(cand_idx) > 0:
        # No component reached min_size (tiny authored geography): start from
        # the deepest-interior cell.
        best = int(cand_idx[int(np.argmax(np.abs(field[cand_idx])))])
        seeds.append(best)
        used.add(best)
        cand_idx = cand_idx[cand_idx != best]

    if seeds:
        seed_xyz = xyz[np.asarray(seeds, dtype=np.int64)]
        while len(seeds) < num_plates and len(cand_idx) > 0:
            dots = np.clip(xyz[cand_idx] @ seed_xyz.T, -1.0, 1.0)
            nearest = np.arccos(dots).min(axis=1)
            j = int(np.argmax(nearest))
            new_cell = int(cand_idx[j])
            seeds.append(new_cell)
            seed_xyz = np.vstack([seed_xyz, xyz[new_cell]])
            cand_idx = np.delete(cand_idx, j)

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
    *,
    locked: dict[int, str] | None = None,
    plate_ids: list[str] | None = None,
) -> dict[int, str]:
    """Synchronous BFS Voronoi.  Cells in *locked* keep their current plate.

    *locked* maps cell_id → plate_id.  These cells are never reassigned —
    useful for protecting newborn plates during their growth phase.

    *plate_ids* (optional) gives the plate id for ``seeds[i]``.  When omitted,
    plates are named ``plate_{i:03d}`` by seed index.  During tectonic
    re-partitioning the caller MUST pass the actual plate ids — naming by index
    mismatches rifted plates (e.g. ``plate_011_a``) and silently orphans their
    cells, which is what collapsed the plate count.
    """
    num_plates = len(seeds)
    ids = plate_ids if plate_ids is not None else [f"plate_{i:03d}" for i in range(num_plates)]
    cell_plate_map: dict[int, str] = {}

    # Pre-assign locked cells
    locked_count = 0
    if locked:
        for cid, pid in locked.items():
            cell_plate_map[cid] = pid
            locked_count += 1

    # One FIFO queue per plate, initialised with the seed cell
    queues: list[deque[int]] = [deque([s]) for s in seeds]
    for i, seed_id in enumerate(seeds):
        pid = ids[i]
        if seed_id not in cell_plate_map:
            cell_plate_map[seed_id] = pid

    total_assigned = len(cell_plate_map)
    round_num = 0

    prev_assigned = 0
    while total_assigned < mesh.num_cells:
        round_num += 1

        for plate_idx in range(num_plates):
            q = queues[plate_idx]
            if not q:
                continue

            plate_id = ids[plate_idx]
            for _ in range(len(q)):
                cell_id = q.popleft()
                for neighbor_id in mesh.cells[cell_id].neighbors:
                    if neighbor_id not in cell_plate_map and neighbor_id not in (locked or {}):
                        cell_plate_map[neighbor_id] = plate_id
                        q.append(neighbor_id)
                        total_assigned += 1

        # Safety: if no progress was made this round, the mesh is disconnected
        if total_assigned == prev_assigned:
            logger.warning(
                "Voronoi BFS stalled at %d/%d cells (mesh may be disconnected)",
                total_assigned,
                mesh.num_cells,
            )
            break
        prev_assigned = total_assigned

    logger.info(
        "  Voronoi BFS: %d rounds, %d cells assigned",
        round_num,
        total_assigned,
    )
    return cell_plate_map


# ---------------------------------------------------------------------------
# Noise-warped Voronoi (Cortial 2019 §3 "geodetic distance + noise warp")
# ---------------------------------------------------------------------------
# The synchronous BFS above produces geodesic (great-circle) plate boundaries
# — long and unnaturally straight.  The paper warps the distance metric with
# noise so boundaries weave into irregular, arc-like shapes.  We implement that
# as a multi-source Dijkstra where the cost of entering each cell is perturbed
# by deterministic per-cell noise: wavefronts advance unevenly, so the
# resulting plate boundaries curve and segment instead of running straight.
#
# The noise is LOW-FREQUENCY fBm (wavelength comparable to a plate) so boundaries
# bend into smooth, island-arc-like curves rather than fine-grained jaggies.


def build_cell_cost(
    mesh: CVTMesh,
    rng_seed: int,
    amplitude: float,
    base_freq: float = 2.0,
) -> np.ndarray:
    """Per-cell traversal cost for the noise-warped partition.

    Returns ``1 + amplitude * noise`` (clamped to stay positive), where noise
    ∈ [-1, 1] is deterministic fBm sampled at each cell's 3D position.  Low-cost
    cells attract boundaries, high-cost cells repel them, warping the edges.
    ``base_freq`` ~2 gives wavelengths of a few thousand km (about a plate), so
    boundaries bend into visible arcs/segments instead of running straight.
    """
    from .noise_kernels import fbm_on_points

    n = mesh.num_cells
    x = np.fromiter((c.x for c in mesh.cells), dtype=np.float64, count=n)
    y = np.fromiter((c.y for c in mesh.cells), dtype=np.float64, count=n)
    z = np.fromiter((c.z for c in mesh.cells), dtype=np.float64, count=n)
    noise = fbm_on_points(
        x,
        y,
        z,
        int(rng_seed),
        octaves=1,
        lacunarity=2.0,
        persistence=0.5,
        base_freq=base_freq,
    )
    cost = 1.0 + float(amplitude) * noise
    return np.maximum(cost, 0.05)


def voronoi_partition_warped(
    mesh: CVTMesh,
    seeds: list[int],
    plate_ids: list[str],
    cell_cost: np.ndarray,
    *,
    plate_speed: np.ndarray | None = None,
    locked: dict[int, str] | None = None,
) -> dict[int, str]:
    """Noise-warped spherical Voronoi — multi-source Dijkstra.

    ``seeds[i]`` is the seed cell for plate ``plate_ids[i]``.  The cost of
    entering cell ``v`` is ``cell_cost[v]``; each cell joins the plate whose
    wavefront reaches it with the smallest accumulated cost.  Produces
    irregular, jagged boundaries (vs. the straight geodesic edges of the
    uniform BFS above).

    ``plate_speed`` (optional): per-plate expansion multiplier — a
    MULTIPLICATIVELY WEIGHTED Voronoi diagram (graph analogue of the
    Apollonius diagram).  Wavefront ``i`` pays ``cell_cost[v] / speed[i]``
    to enter cell ``v``, so a plate with speed 2 expands twice as fast and
    claims roughly twice the area.  This is what lets a re-partition PRESERVE
    a skewed size distribution: plain (unit-speed) Voronoi of moving
    centroids is Lloyd iteration, whose attractor is a centroidal Voronoi
    tessellation with near-EQUAL cell areas; prescribed speeds move the
    attractor to a *weighted* CVT whose area ratios match the speeds.

    ``locked`` (optional): cell_id → plate_id assignments that are never
    reassigned (newborn-plate protection during tectonic resamples).  Locked
    cells keep their owner and are opaque to the wavefronts — matching the
    uniform-BFS locked semantics.
    """
    import heapq

    n = mesh.num_cells
    inf = float("inf")
    dist = np.full(n, inf, dtype=np.float64)
    owner = np.full(n, -1, dtype=np.int64)

    is_locked: np.ndarray | None = None
    if locked:
        pid_idx = {pid: i for i, pid in enumerate(plate_ids)}
        is_locked = np.zeros(n, dtype=np.bool_)
        for cid, pid in locked.items():
            idx = pid_idx.get(pid)
            if idx is not None:
                owner[cid] = idx
                is_locked[cid] = True

    if plate_speed is None:
        inv_speed = None
    else:
        # Clamp away from zero — a zero/negative speed would strand the seed.
        inv_speed = 1.0 / np.maximum(np.asarray(plate_speed, dtype=np.float64), 1e-6)

    # Heap entries carry the PROPAGATING plate index explicitly: when a seed
    # falls on a locked cell the lock keeps the cell, but the wavefront still
    # emanates from it (matches the uniform BFS, where every seed starts a
    # queue regardless of pre-assignment).
    heap: list[tuple[float, int, int]] = []
    for i, s in enumerate(seeds):
        if is_locked is not None and is_locked[s]:
            heapq.heappush(heap, (0.0, s, i))
            continue
        if dist[s] > 0.0:  # first seed at this cell wins
            dist[s] = 0.0
            owner[s] = i
            heapq.heappush(heap, (0.0, s, i))

    neighbors = [c.neighbors for c in mesh.cells]
    while heap:
        d, u, i = heapq.heappop(heap)
        if d > dist[u]:
            continue  # stale heap entry
        step_scale = 1.0 if inv_speed is None else inv_speed[i]
        for v in neighbors[u]:
            if is_locked is not None and is_locked[v]:
                continue
            nd = d + cell_cost[v] * step_scale
            if nd < dist[v]:
                dist[v] = nd
                owner[v] = i
                heapq.heappush(heap, (nd, v, i))

    cell_plate_map: dict[int, str] = {}
    for c in range(n):
        o = owner[c]
        cell_plate_map[c] = plate_ids[o] if o >= 0 else plate_ids[0]
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
                p + 1,
                passes,
                flipped,
            )
        else:
            break  # converged — no more obvious flips

    logger.info(
        "  Boundary smoothing: %d passes (strength=%.2f)",
        p + 1,
        strength,
    )


# ---------------------------------------------------------------------------
# Crust type assignment
# ---------------------------------------------------------------------------


def assign_crust_types(
    mesh: CVTMesh,
    cell_plate_map: dict[int, str],
    rng: np.random.Generator,
    continental_fraction_min: float = 0.25,
    continental_fraction_max: float = 0.65,
    lat_bias: float = 0.7,
) -> None:
    """Assign crust types to cells based on their plate.

    Each plate gets a random continental fraction uniformly in
    ``[continental_fraction_min, continental_fraction_max]``.
    Fractal Brownian Motion (fBm) — 5 octaves of 3D simplex noise with
    gentle amplitude scaling (persistence=0.45, lacunarity=2.0).  This
    keeps the fractal coastline character while suppressing the single-cell
    checkerboard artefacts that higher-octave noise introduces.

    Latitude bias: lower latitudes are weighted toward continental
    (Earth-like continent distribution).

    References
    ----------
    * Mandelbrot, B.B. (1967). "How Long Is the Coast of Britain?
      Statistical Self-Similarity and Fractional Dimension." *Science*,
      156(3775), 636–638. — coastlines are fractal; their measured
      length grows as the measurement scale shrinks.
    * Musgrave, F.K., Kolb, C.E., & Mace, R.S. (1989). "The synthesis
      and rendering of eroded fractal terrains." *SIGGRAPH '89*.
      — fBm as the standard model for natural terrain; 1/f noise
      produces fractal surfaces whose roughness is scale-invariant.
    * Perlin, K. (2001). "Noise Hardware." In *Real-Time Shading*
      (SIGGRAPH Course Notes). — original simplex noise algorithm.
    * Spencer, K. (2014). OpenSimplex — patent-free simplex noise
      implementation. https://github.com/KdotJPG/OpenSimplex2

    Modifies ``mesh.cells[*].crust_type`` in-place.
    """
    plate_cells: dict[str, list[int]] = {}
    for cid, pid in cell_plate_map.items():
        plate_cells.setdefault(pid, []).append(cid)

    # Latitude-primary, fBm-texture crust assignment.
    #
    # Latitude score (weight 0.7) is the *primary* signal — equatorial
    # cells are systematically favoured for continental crust.  fBm noise
    # (weight 0.3) is a *texture perturbation* that adds fractal boundary
    # detail without creating single-cell checkerboard artefacts.
    from .noise_kernels import noise_on_points

    for plate_id, cell_ids in plate_cells.items():
        continental_fraction = rng.uniform(continental_fraction_min, continental_fraction_max)
        n_cont = max(1, int(len(cell_ids) * continental_fraction))

        noise_seed = rng.integers(0, 1 << 20)
        n_cells = len(cell_ids)
        base_freq = 2.0 / max(n_cells, 1) ** 0.15
        octaves = 5
        lacunarity = 2.5
        persistence = 0.5
        _lat_weight = lat_bias

        # fBm noise, normalised to [-1, 1] (Stage 1.1: Numba kernel;
        # per-plate rng draw order unchanged → deterministic).
        px = np.fromiter((mesh.cells[c].x for c in cell_ids), dtype=np.float64, count=n_cells)
        py = np.fromiter((mesh.cells[c].y for c in cell_ids), dtype=np.float64, count=n_cells)
        pz = np.fromiter((mesh.cells[c].z for c in cell_ids), dtype=np.float64, count=n_cells)
        noise_vals = np.zeros(n_cells, dtype=np.float64)
        amplitude = 1.0
        frequency = base_freq
        for octave in range(octaves):
            octave_seed = int(noise_seed) + octave * 1000
            noise_vals += amplitude * noise_on_points(
                px * frequency, py * frequency, pz * frequency, octave_seed
            )
            amplitude *= persistence
            frequency *= lacunarity
        noise_vals /= (1.0 - persistence**octaves) / (1.0 - persistence)

        # Latitude score: 1.0 at equator, 0.0 at poles
        lat_score = np.array([1.0 - abs(mesh.cells[c].lat) / 90.0 for c in cell_ids])

        # Combined: latitude dominates, fBm adds fractal texture
        score = _lat_weight * lat_score + (1.0 - _lat_weight) * noise_vals

        # Top N by score → continental (threshold varies per plate)
        sorted_idx = np.argsort(score)[::-1]
        actual = 0
        for rank, idx in enumerate(sorted_idx):
            cid = cell_ids[idx]
            if rank < n_cont:
                mesh.cells[cid].crust_type = "continental"
                actual += 1
            else:
                mesh.cells[cid].crust_type = "oceanic"
        logger.warning(
            "  ASSIGNED: %s n_cont=%d actual=%d cells=%d lat_bias=%.2f score_range=[%.3f,%.3f]",
            plate_id,
            n_cont,
            actual,
            n_cells,
            _lat_weight,
            float(np.min(score)),
            float(np.max(score)),
        )


# ---------------------------------------------------------------------------
# Euler pole assignment
# ---------------------------------------------------------------------------


def _cross_matrix(v: np.ndarray) -> np.ndarray:
    """Skew-symmetric cross-product matrix ``[v]_×`` (3×3)."""
    x, y, z = v
    return np.array([[0.0, -z, y], [z, 0.0, -x], [-y, x, 0.0]])


def _coherent_poloidal_axis(config: TerrainPipelineConfig) -> np.ndarray:
    """Symmetry axis of the coherent poloidal flow.

    Tidally-locked bodies (tidal plate-speed coupling on) anchor the flow to
    the sub-planet (tidal) axis; otherwise the rotation axis (y = north).
    """
    if config.tidal_plate_speed_enabled:
        ax = lonlat_to_xyz(config.sub_planet_longitude_deg, config.sub_planet_latitude_deg)
        return np.asarray(ax, dtype=np.float64)
    return np.array([0.0, 1.0, 0.0], dtype=np.float64)


def coherent_velocity_field(
    points: np.ndarray,
    poloidal_axis: np.ndarray,
    poloidal_amp_cm_yr: float,
    extra_fields: list[tuple[np.ndarray, float]] | None = None,
) -> np.ndarray:
    """Coherent poloidal + toroidal surface velocity field (cm/yr).

    The dominant degree-2 tidal POLOIDAL cell (upwelling at ``P = ±â``,
    downwelling on the ring ``P·â = 0``, peak speed ``A/2`` at ``c = ±1/√2``)
    plus optional ``extra_fields`` — degree-2 TOROIDAL cells (``c·(âₖ × P)``,
    divergence-free differential rotation about random axes).  A purely
    poloidal field is a gradient, so its rigid-rotation fit is forced ⊥ the
    tidal axis for every plate (transform-dominated boundaries); the toroidal
    cells add the divergent-rotation component that diversifies the fitted
    Euler poles, representing internal-heating convection's vorticity.

    .. math::

        v(P) = A \\, c\\,(c\\,P - \\hat a), \\qquad c = P\\cdot\\hat a
    """
    c = points @ poloidal_axis
    v = poloidal_amp_cm_yr * c[:, None] * (c[:, None] * points - poloidal_axis[None, :])
    if extra_fields:
        for axis, amp in extra_fields:
            cc = points @ axis
            v = v + amp * cc[:, None] * np.cross(axis, points)
    return v  # type: ignore[no-any-return]


def _convection_harmonics(
    rng: np.random.Generator,
    base_amp: float,
    num: int,
    rel_amp: float,
) -> list[tuple[np.ndarray, float]]:
    """Random degree-2 toroidal convection cells (internal-heating diversity).

    Each cell is a degree-2 TOROIDAL field ``c·(âₖ × P)`` about a random axis
    ``âₖ`` with amplitude ``rel_amp · base_amp · U(0.5, 1)``.  Physically these
    are the ~15% internal heating (radiogenic + secular cooling) whose
    multi-cell convection carries vorticity (differential rotation) not tied to
    the tidal axis; a poloidal gradient alone would force every plate's Euler
    pole ⊥ the tidal axis, and the toroidal cells break that symmetry.
    """
    fields: list[tuple[np.ndarray, float]] = []
    for _ in range(num):
        axis = rng.standard_normal(3)
        axis = axis / np.linalg.norm(axis)
        amp = base_amp * rel_amp * float(rng.uniform(0.5, 1.0))
        fields.append((np.asarray(axis), amp))
    return fields


def _fit_rotation_vector(points: np.ndarray, velocities: np.ndarray) -> np.ndarray:
    """Least-squares rigid rotation ``ω`` (cm/yr) fitting ``ω × P_i ≈ v_i``.

    Solved via normal equations ``H ω = b`` (3×3).  ``ω × P = −[P]_× ω``, so
    ``H = Σ AᵀA`` and ``b = Σ Aᵀv`` with ``A = −[P]_×``.  The solve uses
    ``np.linalg.solve`` (LU) rather than ``lstsq`` (SVD) because SVD is
    non-deterministic under multithreaded BLAS, which would break pipeline
    reproducibility.  A tiny ridge regularises the (never-hit in practice)
    degenerate case of a plate whose cells all lie on one great circle.
    """
    h = np.zeros((3, 3))
    b = np.zeros(3)
    for i in range(len(points)):
        a = -_cross_matrix(points[i])
        h += a.T @ a
        b += a.T @ velocities[i]
    omega = np.linalg.solve(h + np.eye(3) * 1e-12, b)
    return np.asarray(omega, dtype=np.float64)


def _plate_type_from_cells(mesh: CVTMesh, cell_ids: list[int]) -> PlateType:
    """Plate type from majority crust (continental / oceanic / mixed)."""
    n_cont = sum(1 for c in cell_ids if mesh.cells[c].crust_type == "continental")
    n_ocean = len(cell_ids) - n_cont
    if n_cont > 2 * n_ocean:
        return PlateType.CONTINENTAL
    if n_ocean > 2 * n_cont:
        return PlateType.OCEANIC
    return PlateType.MIXED


def _assign_coherent_euler_poles(
    mesh: CVTMesh,
    plate_cells: dict[str, list[int]],
    config: TerrainPipelineConfig,
    radius_cm: float,
    rng: np.random.Generator,
) -> list[TectonicPlate]:
    """Euler poles fit (least squares) to a coherent poloidal velocity field.

    The field is the dominant degree-2 tidal cell anchored to the tidal axis
    plus random higher-harmonic convection cells (see
    :func:`coherent_velocity_field`); each plate's rigid rotation is the best
    fit to that field over its cells, so plate-motion directions are coherent
    but diverse (not all ⊥ the tidal axis).
    """
    _, speed_max = config.plate_speed_range_cm_yr
    poloidal_axis = _coherent_poloidal_axis(config)
    # Peak poloidal surface speed = speed_max → A = 2·speed_max.
    poloidal_amp = 2.0 * speed_max

    # Internal-heating convection diversity (§ 方向 3): random extra cells
    # generated ONCE so every plate sees the same global field.
    extra_fields = _convection_harmonics(
        rng,
        poloidal_amp,
        config.convection_harmonics,
        config.convection_harmonic_amp,
    )

    omega_fit: dict[str, np.ndarray] = {}
    for plate_id, cell_ids in sorted(plate_cells.items()):
        pts = np.array([[mesh.cells[c].x, mesh.cells[c].y, mesh.cells[c].z] for c in cell_ids])
        pts /= np.linalg.norm(pts, axis=1, keepdims=True)
        vel = coherent_velocity_field(pts, poloidal_axis, poloidal_amp, extra_fields)
        omega_fit[plate_id] = _fit_rotation_vector(pts, vel)

    # Renormalise so the fastest plate matches speed_max (tidal-derived anchor).
    max_omega = max((float(np.linalg.norm(w)) for w in omega_fit.values()), default=1.0)
    scale = speed_max / max_omega if max_omega > 1e-12 else 1.0

    plates: list[TectonicPlate] = []
    for plate_id, cell_ids in sorted(plate_cells.items()):
        plate_idx = int(plate_id.split("_")[1])
        omega_cm_yr = omega_fit[plate_id] * scale
        # Continental slowdown (§5.5): scale the rotation by the plate's
        # continental-cell fraction so continental rifts don't open as fast as
        # mid-ocean ridges (Africa ~2 vs Pacific ~10 cm/yr ≈ 0.2–0.3).
        n_cont = sum(1 for c in cell_ids if mesh.cells[c].crust_type == "continental")
        cont_frac = n_cont / len(cell_ids) if cell_ids else 0.0
        slowdown = 1.0 - (1.0 - config.continental_plate_speed_factor) * cont_frac
        omega_cm_yr = omega_cm_yr * slowdown
        mag = float(np.linalg.norm(omega_cm_yr))
        if mag < 1e-15:
            axis = np.array([0.0, 0.0, 1.0])
            omega_rad_yr = 0.0
        else:
            axis = omega_cm_yr / mag
            omega_rad_yr = mag / radius_cm
        plates.append(
            TectonicPlate(
                id=plate_id,
                name=f"Plate {plate_idx + 1}",
                type=_plate_type_from_cells(mesh, cell_ids),
                cell_ids=sorted(cell_ids),
                euler_pole=EulerPole(
                    x=float(axis[0]),
                    y=float(axis[1]),
                    z=float(axis[2]),
                    omega_rad_yr=omega_rad_yr,
                ),
                growth_speed_multiplier=1.0,
            )
        )
        for cid in cell_ids:
            mesh.cells[cid].plate_id = plate_id

    return plates


def assign_euler_poles(
    mesh: CVTMesh,
    cell_plate_map: dict[int, str],
    config: TerrainPipelineConfig,
    rng: np.random.Generator,
) -> list[TectonicPlate]:
    """Create TectonicPlate objects with Euler poles.

    With ``config.coherent_motion`` (default) the poles are fit (least squares)
    to a coherent poloidal velocity field derived from tidal-heating geometry,
    so plate-motion directions are coherent rather than random — see
    ``docs/design/proposals/plate-motion-coherence.md``.  With it off, the
    original Cortial 2019 random-direction poles are used.
    """
    plate_cells: dict[str, list[int]] = {}
    for cid, pid in cell_plate_map.items():
        plate_cells.setdefault(pid, []).append(cid)

    speed_min, speed_max = config.plate_speed_range_cm_yr
    radius_cm = config.radius_km * 1e5  # for cm/yr → rad/yr conversion

    if config.coherent_motion:
        return _assign_coherent_euler_poles(mesh, plate_cells, config, radius_cm, rng)

    plates: list[TectonicPlate] = []

    for plate_id, cell_ids in sorted(plate_cells.items()):
        plate_idx = int(plate_id.split("_")[1])

        speed_cm_yr = rng.uniform(speed_min, speed_max)
        omega_rad_yr = speed_cm_yr / radius_cm

        # Plate centroid (unit vector)
        centroid = np.array(
            [
                np.mean([mesh.cells[c].x for c in cell_ids]),
                np.mean([mesh.cells[c].y for c in cell_ids]),
                np.mean([mesh.cells[c].z for c in cell_ids]),
            ]
        )
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

        plate_type = _plate_type_from_cells(mesh, cell_ids)

        plates.append(
            TectonicPlate(
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
            )
        )

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
    *,
    raster_bias: np.ndarray | None = None,
) -> tuple[list[TectonicPlate], dict[int, str]]:
    """Cortial et al. (2019) §3 — Poisson-disc + spherical Voronoi."""
    return _generate_plates_impl(mesh, config, raster_bias=raster_bias)


def generate_plates(
    mesh: CVTMesh,
    config: TerrainPipelineConfig,
    *,
    raster_bias: np.ndarray | None = None,
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
            f"Unknown plate algorithm '{algo}'. Available: {sorted(_PLATE_ALGORITHMS.keys())}"
        )
    if algo == "cortial2019":
        return _generate_cortial2019(mesh, config, raster_bias=raster_bias)
    raise ValueError(f"Plate algorithm '{algo}' not implemented")  # unreachable


def _generate_plates_impl(
    mesh: CVTMesh,
    config: TerrainPipelineConfig,
    *,
    raster_bias: np.ndarray | None = None,
) -> tuple[list[TectonicPlate], dict[int, str]]:
    """Internal implementation — Cortial 2019 Voronoi partition."""
    rng = np.random.default_rng(config.seed + 1)

    logger.info("Generating %d tectonic plates", config.num_plates)

    from .geography import apply_geography_crust, build_geography_coast_cost

    # Geography-aligned partition (§5 方案 2): with authored geography, a
    # coastline is a plate boundary (continent ↔ ocean).  Seed each major
    # continent/ocean basin and weight the partition so plate boundaries settle
    # on continental margins instead of running through interiors.
    coast = build_geography_coast_cost(mesh, config, raster_bias=raster_bias)

    if coast is not None:
        coast_cost, field, mask = coast
        logger.info("  Step 1/5: Geography-aligned seed selection")
        seeds = select_geography_seeds(mesh, mask, field, config.num_plates)
        logger.info("  Step 2/5: Weighted Voronoi partition (coast-attracted)")
        cell_plate_map = voronoi_partition_warped(
            mesh,
            seeds,
            [f"plate_{i:03d}" for i in range(len(seeds))],
            coast_cost,
        )
    else:
        # 1. Seed selection
        logger.info("  Step 1/5: Selecting plate seeds")
        seeds = select_plate_seeds(mesh, config.num_plates, rng)

        # 2. Spherical Voronoi partition (Cortial 2019 §3)
        logger.info("  Step 2/5: Spherical Voronoi partition")
        cell_plate_map = _voronoi_partition(mesh, seeds)

    # 3. Boundary smoothing (Cortial 2019 "noise-warped geodetic distance")
    logger.info("  Step 3/5: Boundary smoothing (strength=%.2f)", config.boundary_noise)
    _relax_boundaries(mesh, cell_plate_map, config.boundary_noise, rng)

    # Log plate size distribution
    plate_sizes = sorted(
        [
            sum(1 for v in cell_plate_map.values() if v == f"plate_{i:03d}")
            for i in range(len(seeds))
        ],
        reverse=True,
    )
    logger.info(
        "  Plate sizes (cells): %s",
        ", ".join(f"{s:4d}" for s in plate_sizes),
    )

    # 4. Crust types
    if coast is not None:
        # Authored geography: assign crust from the land-bias field via a
        # global threshold (realizes named continents/oceans).  The plate
        # partition above is already aligned to the coast; only crust is set.
        logger.info("  Step 4/5: Assigning crust types (authored geography)")
        apply_geography_crust(mesh, config, raster_bias=raster_bias)
    else:
        logger.info("  Step 4/5: Assigning crust types")
        assign_crust_types(
            mesh,
            cell_plate_map,
            rng,
            config.continental_fraction_min,
            config.continental_fraction_max,
            config.lat_bias,
        )

    # 5. Euler poles
    logger.info("  Step 5/5: Assigning Euler poles")
    plates = assign_euler_poles(mesh, cell_plate_map, config, rng)

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
