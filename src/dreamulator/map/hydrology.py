"""River network generation via graph-based flow routing (D8) on the spherical CVT mesh.

Pipeline (see ``docs/design/terrain-pipeline.md`` §8):

1. **Priority-flood depression fill** (Barnes et al. 2014, O(N log N)) — raises
   every pit to its spill level so flow never terminates in a spurious local
   minimum. Operates on a **temporary array**; it is never written back to
   ``cell.elevation``.
2. **D8 flow direction** — steepest descent on the filled surface.
3. **Flat routing** — ocean-connected plateaus (spill flats) are routed toward
   the nearest outlet via BFS; otherwise they would have no downhill neighbour.
4. **Flow accumulation** — topological-sort (Kahn) upstream catchment area.
5. **River classification / ids** — accumulation-threshold stream order plus
   ``river_id`` assignment traced upstream from river mouths.

Fills the following ``VoronoiCell`` fields (ocean cells get ``flow_direction=None``
and ``flow_accumulation=0``):

- ``flow_direction``: downstream cell id, ``-1`` = sink, ``None`` = ocean
- ``flow_accumulation``: upstream catchment area in km² (not cell count)
- ``river_id``: channel id on cells with accumulation ≥ ``min_river_accum_km2``
- ``river_order``: 0 = no channel, else accumulation-threshold order (1–4)
"""

from __future__ import annotations

import heapq
from collections import deque
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from .models import CVTMesh, VoronoiCell
    from .pipeline_types import TerrainPipelineConfig

# ---------------------------------------------------------------------------
# Constants (roadmap terrain-pipeline.md §8.3 — accumulation → stream order)
# ---------------------------------------------------------------------------

#: Accumulation thresholds (km²) → stream order.
RIVER_ORDER_THRESHOLDS: dict[int, float] = {
    1: 100.0,
    2: 1_000.0,
    3: 10_000.0,
    4: 100_000.0,
}

#: Minimum upstream catchment area (km²) for a cell to count as a river channel.
DEFAULT_MIN_RIVER_ACCUM_KM2: float = 1_000.0


# ---------------------------------------------------------------------------
# Pure routing functions
# ---------------------------------------------------------------------------


def build_adjacency(
    cells: list[VoronoiCell], radius_km: float, xyz: np.ndarray
) -> tuple[list[list[int]], list[list[float]]]:
    """Build per-cell neighbour indices and great-circle edge lengths (km).

    Args:
        cells: ``mesh.cells`` (list of ``VoronoiCell``).
        radius_km: Planet radius.
        xyz: (n, 3) unit-sphere positions (``mesh.cell_xyz``).

    Returns:
        ``(neighbors, dists)`` where ``neighbors[i]`` is a list of cell indices
        and ``dists[i]`` the matching edge lengths in km.
    """
    neighbors: list[list[int]] = []
    dists: list[list[float]] = []
    for i, c in enumerate(cells):
        nbrs = list(c.neighbors)
        neighbors.append(nbrs)
        if nbrs:
            dot = np.clip(xyz[nbrs] @ xyz[i], -1.0, 1.0)
            d = np.arccos(dot) * radius_km
            dists.append([float(v) for v in d])
        else:
            dists.append([])
    return neighbors, dists


def priority_flood_fill(
    elevation: np.ndarray,
    is_land: np.ndarray,
    neighbors: list[list[int]],
) -> tuple[np.ndarray, np.ndarray]:
    """Priority-flood depression fill (Barnes et al. 2014).

    Seeds the fill from ocean cells and raises each pit to its spill level.
    On a connected spherical mesh every cell is reachable from the ocean, so the
    ``connected`` mask is all-True; it is returned anyway for robustness (and so
    a disconnected/land-only mesh would still terminate gracefully).

    Args:
        elevation: (n,) float elevations (m).
        is_land: (n,) bool land mask.
        neighbors: per-cell neighbour index lists.

    Returns:
        ``(filled, connected)`` — filled elevation (temporary) and the
        ocean-connected mask.
    """
    n = len(elevation)
    filled = elevation.astype(np.float64, copy=True)
    connected = np.zeros(n, dtype=bool)
    heap: list[tuple[float, int]] = []

    for i in range(n):
        if not is_land[i]:
            connected[i] = True
            heapq.heappush(heap, (float(filled[i]), i))

    while heap:
        e, i = heapq.heappop(heap)
        for j in neighbors[i]:
            if connected[j]:
                continue
            connected[j] = True
            filled[j] = max(float(elevation[j]), e)
            heapq.heappush(heap, (float(filled[j]), j))

    return filled, connected


def compute_flow_directions(
    filled: np.ndarray,
    is_land: np.ndarray,
    neighbors: list[list[int]],
    dists: list[list[float]],
) -> np.ndarray:
    """D8 steepest-descent flow direction on the filled surface.

    Args:
        filled: (n,) filled elevation (from :func:`priority_flood_fill`).
        is_land: (n,) bool land mask.
        neighbors: per-cell neighbour index lists.
        dists: per-cell edge lengths (km).

    Returns:
        (n,) int32 array: downstream neighbour index, or ``-1`` for sinks
        (ocean cells, and land cells with no strictly-downhill neighbour).
    """
    n = len(filled)
    flow_dir = np.full(n, -1, dtype=np.int32)

    for i in range(n):
        if not is_land[i]:
            continue  # ocean = sink
        best = -1
        best_grad = 0.0
        for j, d in zip(neighbors[i], dists[i], strict=True):
            if d <= 0:
                continue
            grad = (filled[i] - filled[j]) / d
            if grad > best_grad:
                best_grad = grad
                best = j
        flow_dir[i] = best  # -1 if flat (no strictly-downhill neighbour)

    return flow_dir


def route_flat_cells(
    filled: np.ndarray,
    is_land: np.ndarray,
    connected: np.ndarray,
    neighbors: list[list[int]],
    flow_dir: np.ndarray,
) -> np.ndarray:
    """Route ocean-connected flat cells toward the nearest outlet via BFS.

    Flat cells have no strictly-downhill neighbour (``flow_dir == -1``) despite
    draining to the ocean; without routing they would become spurious sinks.
    BFS from all resolved cells (ocean + cells already holding a downhill
    direction), routing each unresolved land cell to a parent that is **not
    uphill** (``filled[parent] <= filled[child]``) — otherwise an upstream
    source cell (e.g. a ridge draining into the flat) would capture the flat
    and send water uphill.

    Args:
        filled: (n,) filled elevation (from :func:`priority_flood_fill`).
        is_land: (n,) bool land mask.
        connected: (n,) ocean-connected mask (from :func:`priority_flood_fill`).
        neighbors: per-cell neighbour index lists.
        flow_dir: (n,) int32 from :func:`compute_flow_directions`.

    Returns:
        Updated ``flow_dir`` (modified in place and returned).
    """
    n = len(is_land)
    resolved = np.zeros(n, dtype=bool)
    resolved[~is_land] = True
    resolved[flow_dir >= 0] = True

    q: deque[int] = deque()
    for i in range(n):
        if resolved[i]:
            q.append(i)

    while q:
        i = q.popleft()
        for j in neighbors[i]:
            if is_land[j] and connected[j] and not resolved[j] and filled[i] <= filled[j]:
                resolved[j] = True
                flow_dir[j] = i
                q.append(j)

    return flow_dir


def compute_flow_accumulation(
    flow_dir: np.ndarray,
    is_land: np.ndarray,
    area_km2: np.ndarray,
) -> np.ndarray:
    """Upstream catchment area via Kahn's topological sort.

    Each land cell contributes its own area plus everything upstream; ocean
    cells contribute nothing. Sinks (``flow_dir == -1``) accumulate their basin
    but pass nothing on.

    Args:
        flow_dir: (n,) int32 flow directions.
        is_land: (n,) bool land mask.
        area_km2: (n,) cell areas (km²).

    Returns:
        (n,) float accumulation in km².
    """
    n = len(flow_dir)
    accum = np.where(is_land, area_km2, 0.0)
    in_degree = np.zeros(n, dtype=np.int32)
    for i in range(n):
        t = flow_dir[i]
        if t >= 0:
            in_degree[t] += 1

    q: deque[int] = deque(i for i in range(n) if is_land[i] and in_degree[i] == 0)
    while q:
        i = q.popleft()
        t = flow_dir[i]
        # Only propagate into land cells — ocean cells are terminal sinks and
        # must keep accumulation 0 (the mouth land cell already holds the full
        # catchment, so discharge is available there).
        if t >= 0 and is_land[t]:
            accum[t] += accum[i]
            in_degree[t] -= 1
            if in_degree[t] == 0:
                q.append(t)

    return accum


def classify_rivers(
    accum_km2: np.ndarray,
    cell_area_km2: float,
    thresholds: dict[int, float] | None = None,
) -> np.ndarray:
    """Accumulation-threshold stream order (0 = no channel).

    The thresholds are Earth-DEM-calibrated (km² at ~1 km² cell resolution);
    they are scaled by ``cell_area_km2`` so the classification is resolution-
    independent (order 1 ≈ 100 cells, order 2 ≈ 1000 cells, …).

    Args:
        accum_km2: (n,) flow accumulation.
        cell_area_km2: mean cell area (km²) — the resolution scale.
        thresholds: order → threshold (km², Earth reference). Defaults to
            ``RIVER_ORDER_THRESHOLDS``.

    Returns:
        (n,) int32 array of stream orders.
    """
    if thresholds is None:
        thresholds = RIVER_ORDER_THRESHOLDS
    order = np.zeros(len(accum_km2), dtype=np.int32)
    for o, thresh in sorted(thresholds.items()):
        order[accum_km2 >= thresh * cell_area_km2] = o
    return order


def assign_river_ids(
    flow_dir: np.ndarray,
    is_land: np.ndarray,
    accum_km2: np.ndarray,
    min_accum_km2: float = DEFAULT_MIN_RIVER_ACCUM_KM2,
) -> list[str | None]:
    """Assign ``river_id`` to channel cells, tracing upstream from river mouths.

    A mouth is a land cell draining into an ocean cell with accumulation above
    the threshold. Each river follows the largest upstream tributary (greedy),
    matching ``terrain-pipeline.md`` §8.4.

    Args:
        flow_dir: (n,) int32 flow directions.
        is_land: (n,) bool land mask.
        accum_km2: (n,) flow accumulation.
        min_accum_km2: channel threshold.

    Returns:
        List of ``river_id`` (``f"river_{i:04d}"``) or ``None`` per cell.
    """
    n = len(flow_dir)
    river_id: list[str | None] = [None] * n

    reverse: list[list[int]] = [[] for _ in range(n)]
    for i in range(n):
        t = flow_dir[i]
        if t >= 0:
            reverse[t].append(i)

    rid = 0
    for mouth in range(n):
        if not is_land[mouth]:
            continue
        t = flow_dir[mouth]
        if not (t >= 0 and not is_land[t] and accum_km2[mouth] >= min_accum_km2):
            continue

        cur_id = f"river_{rid:04d}"
        rid += 1
        stack = [mouth]
        while stack:
            i = stack.pop()
            if river_id[i] is not None:
                continue
            river_id[i] = cur_id
            ups = [u for u in reverse[i] if accum_km2[u] >= min_accum_km2]
            if ups:
                stack.append(max(ups, key=lambda u: accum_km2[u]))

    return river_id


def detect_closed_basins(
    elevation: np.ndarray,
    sea_level: float,
    neighbors: list[list[int]],
) -> np.ndarray:
    """Detect closed below-sea-level depressions (endorheic lakes).

    Cells below sea level that are NOT connected to the largest such connected
    component (the global ocean) are closed basins — inland seas/lakes with no
    outlet (Caspian / Dead Sea / Great Salt Lake type).  Returns a bool mask.

    The "largest component = ocean" heuristic assumes a connected world with a
    dominant ocean; on a land-dominated world the largest component may itself
    be a lake (no global ocean), which this does not special-case.

    Args:
        elevation: (n,) elevation (m).
        sea_level: sea surface elevation (m).
        neighbors: per-cell neighbour index lists.

    Returns:
        (n,) bool mask — True for closed-lake cells.
    """
    n = len(elevation)
    below = elevation < sea_level
    comp = np.full(n, -1, dtype=np.int32)
    sizes: list[int] = []
    for s in range(n):
        if not below[s] or comp[s] >= 0:
            continue
        cid = len(sizes)
        q: deque[int] = deque([s])
        comp[s] = cid
        cnt = 1
        while q:
            i = q.popleft()
            for j in neighbors[i]:
                if below[j] and comp[j] < 0:
                    comp[j] = cid
                    cnt += 1
                    q.append(j)
        sizes.append(cnt)

    if not sizes:
        return np.zeros(n, dtype=bool)

    ocean = int(np.argmax(sizes))
    is_lake = np.zeros(n, dtype=bool)
    is_lake[below & (comp != ocean)] = True
    return is_lake


# ---------------------------------------------------------------------------
# Pipeline entry point
# ---------------------------------------------------------------------------


def generate_rivers(mesh: CVTMesh, config: TerrainPipelineConfig) -> None:
    """Run river generation on the CVT mesh, filling hydrology fields in place.

    Reads ``cell.elevation`` and the sea level from ``config.sea_level_offset_m``
    (identical to the climate engine's land mask). Never modifies elevation.

    Args:
        mesh: CVT mesh with elevation set.
        config: Pipeline configuration.
    """
    n = mesh.num_cells
    if n == 0:
        return

    elevation = np.array([c.elevation for c in mesh.cells], dtype=np.float64)
    area_km2 = np.array([c.area_km2 for c in mesh.cells], dtype=np.float64)
    is_land = elevation >= config.sea_level_offset_m

    neighbors, dists = build_adjacency(mesh.cells, config.radius_km, mesh.cell_xyz)

    filled, connected = priority_flood_fill(elevation, is_land, neighbors)
    flow_dir = compute_flow_directions(filled, is_land, neighbors, dists)
    flow_dir = route_flat_cells(filled, is_land, connected, neighbors, flow_dir)

    accum_km2 = compute_flow_accumulation(flow_dir, is_land, area_km2)
    cell_area = float(area_km2.mean())  # resolution scale for thresholds
    order = classify_rivers(accum_km2, cell_area)
    river_ids = assign_river_ids(
        flow_dir, is_land, accum_km2, min_accum_km2=DEFAULT_MIN_RIVER_ACCUM_KM2 * cell_area
    )
    is_lake = detect_closed_basins(elevation, config.sea_level_offset_m, neighbors)

    for i, c in enumerate(mesh.cells):
        c.flow_direction = None if not is_land[i] else int(flow_dir[i])
        c.flow_accumulation = float(accum_km2[i])
        c.river_id = river_ids[i]
        c.river_order = int(order[i])
        c.is_lake = bool(is_lake[i])
