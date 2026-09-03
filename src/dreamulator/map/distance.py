"""Spherical geodesic distance on the CVT mesh.

The single reference implementation for BFS distance in the map pipeline
(proposal §7: grid-resolution independence).  Distances are accumulated as
per-edge great-circle lengths ``arccos(x·y)·R``, so they are exact and
resolution-independent, unlike the mean-cell-spacing approximation
``√(4πR²/n)`` which ignores the ±30% spacing scatter of a CVT mesh (and, in
one historical case, hardcoded Earth's radius 6371).
"""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from .models import CVTMesh


def geodesic_bfs(
    mesh: CVTMesh,
    seeds: Iterable[int],
    radius_km: float,
    *,
    max_dist_km: float | None = None,
    can_expand: Callable[[int], bool] | None = None,
) -> dict[int, float]:
    """Multi-source BFS geodesic distances (km) from ``seeds``.

    Args:
        mesh: The CVT mesh.
        seeds: Source cell ids (distance 0).
        radius_km: Planet radius (angular → linear conversion).
        max_dist_km: Stop *expanding* a cell once its distance reaches this
            bound.  Its neighbours are still recorded (one band past the bound),
            matching the old mean-spacing BFS semantics.
        can_expand: Gate on which neighbours are reachable (e.g. ``crust_type ==
            "oceanic"``).  Default: all neighbours.

    Returns:
        ``{cell_id: distance_km}`` in BFS (FIFO) order.
    """
    xyz = mesh.cell_xyz
    dist: dict[int, float] = {}
    q: deque[int] = deque()
    for s in seeds:
        if s not in dist:
            dist[s] = 0.0
            q.append(s)

    while q:
        cid = q.popleft()
        d = dist[cid]
        if max_dist_km is not None and d >= max_dist_km:
            continue
        p = xyz[cid]
        for nid in mesh.cells[cid].neighbors:
            if nid in dist:
                continue
            if can_expand is not None and not can_expand(nid):
                continue
            edge = float(np.arccos(np.clip(p @ xyz[nid], -1.0, 1.0))) * radius_km
            dist[nid] = d + edge
            q.append(nid)

    return dist


def geodesic_bfs_with_source(
    mesh: CVTMesh,
    seeds: Iterable[int],
    radius_km: float,
    *,
    max_dist_km: float | None = None,
    can_expand: Callable[[int], bool] | None = None,
) -> dict[int, tuple[int, float]]:
    """Like :func:`geodesic_bfs` but tracks the nearest seed (source) per cell.

    Returns ``{cell_id: (source_id, distance_km)}`` — used to propagate a
    boundary property (boundary type / strike) from the nearest boundary cell
    outward.
    """
    xyz = mesh.cell_xyz
    result: dict[int, tuple[int, float]] = {}
    q: deque[int] = deque()
    for s in seeds:
        if s not in result:
            result[s] = (s, 0.0)
            q.append(s)

    while q:
        cid = q.popleft()
        src, d = result[cid]
        if max_dist_km is not None and d >= max_dist_km:
            continue
        p = xyz[cid]
        for nid in mesh.cells[cid].neighbors:
            if nid in result:
                continue
            if can_expand is not None and not can_expand(nid):
                continue
            edge = float(np.arccos(np.clip(p @ xyz[nid], -1.0, 1.0))) * radius_km
            result[nid] = (src, d + edge)
            q.append(nid)

    return result
