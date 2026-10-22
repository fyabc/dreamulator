"""Depression fill and closed-basin lakes on the spherical CVT mesh.

The global mesh no longer routes rivers: drainage is computed on the high-resolution canvas
(``docs/design/pipelines/canvas-hydrology.md``), where it is meaningful.  Two pieces stay:

- **Priority-flood depression fill** (Barnes et al. 2014, O(N log N)), used by terrain
  synthesis to find closed basins for deposition fill;
- **Closed-basin lakes**: below-sea-level cells not connected to the global ocean are marked
  ``is_lake``.  Climate, ecology, civilization, biogeography and the land/ocean split
  (``water_bodies.upgrade_large_endorheic_lakes``) read this flag.
"""

from __future__ import annotations

import heapq
from collections import deque
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from .models import CVTMesh


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


def mark_closed_basin_lakes(mesh: CVTMesh, sea_level_m: float) -> int:
    """Set ``is_lake`` on closed below-sea-level basins (keeps lakes already marked).

    Returns the number of cells marked by this call.
    """
    if mesh.num_cells == 0:
        return 0
    elevation = np.array([c.elevation for c in mesh.cells], dtype=np.float64)
    neighbors = [c.neighbors for c in mesh.cells]
    is_lake = detect_closed_basins(elevation, sea_level_m, neighbors)
    marked = 0
    for i, c in enumerate(mesh.cells):
        if is_lake[i] and not c.is_lake:
            c.is_lake = True
            marked += 1
    return marked
