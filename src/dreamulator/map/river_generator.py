"""River network generation — pipeline entry point.

The routing implementation (depression fill, D8, accumulation, river ids) lives
in :mod:`dreamulator.map.hydrology` so the erosion loop (§10) can reuse the pure
routing functions without importing the pipeline glue here.
"""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from .models import CVTMesh, MapFeature
    from .pipeline_types import TerrainPipelineConfig


def generate_rivers(mesh: CVTMesh, config: TerrainPipelineConfig) -> None:
    """Generate river networks on the CVT mesh.

    Fills ``flow_direction`` / ``flow_accumulation`` / ``river_id`` /
    ``river_order`` on each ``VoronoiCell``. See
    ``docs/design/terrain-pipeline.md`` §9 for the algorithm design.

    Args:
        mesh: The CVT mesh with elevation data (hydrology fields modified in place).
        config: Pipeline configuration.
    """
    from .hydrology import generate_rivers as _generate

    _generate(mesh, config)


def extract_river_features(mesh: CVTMesh, min_order: int = 1) -> list[MapFeature]:
    """Extract river polylines from the hydrology fields for the vector layer.

    Drawing algorithm (docs/design/pipelines/geological-pipeline.md §10):

    - **Channel cells**: ``river_order >= min_order``.  The order thresholds
      are resolution-independent (scaled by cell area in ``classify_rivers``),
      so at 200k cells only trunk networks (~top 2–3 % of land by catchment)
      qualify — the density of rivers on a world map.
    - **Polyline tracing**: a walk starts at each channel *source* (no
      upstream channel neighbour) and follows ``flow_direction`` downstream.
      Where the stream order increases (confluence), the walk stops and a new
      polyline starts there, so each polyline carries one width class.  Cells
      already walked (trunk reached first from another source) terminate the
      tributary walk — tributaries end on the trunk.
    - **Antimeridian**: polylines are split where consecutive points jump
      more than 180° in longitude.

    Args:
        mesh: CVT mesh with hydrology fields filled (``generate_rivers``).
        min_order: minimum stream order to draw (default 1).

    Returns:
        ``MapFeature`` list (type RIVER, ``order`` = width class).
    """
    from .models import FeatureType, MapFeature

    cells = mesh.cells
    n = len(cells)
    if n == 0:
        return []

    idx_of: dict[int, int] = {c.id: i for i, c in enumerate(cells)}
    order = np.array([c.river_order for c in cells], dtype=np.int32)
    flow = np.array(
        [c.flow_direction if c.flow_direction is not None else -1 for c in cells],
        dtype=np.int64,
    )
    channel = order >= min_order

    # Upstream adjacency (index space).
    reverse: list[list[int]] = [[] for _ in range(n)]
    for i in range(n):
        j = int(flow[i])
        if j >= 0 and j in idx_of:
            reverse[idx_of[j]].append(i)

    # Sources: channel cells with no upstream channel neighbour.
    starts = deque(
        i
        for i in range(n)
        if channel[i] and not any(channel[u] for u in reverse[i])
    )

    features: list[MapFeature] = []
    walked: set[int] = set()
    k = 0

    def _emit(points: list[tuple[float, float]], o: int, name: str) -> None:
        nonlocal k
        if len(points) >= 2:
            features.append(
                MapFeature(
                    id=f"river_line_{k:04d}",
                    name=name,
                    type=FeatureType.RIVER,
                    coordinates=points,
                    order=int(o),
                )
            )
            k += 1

    while starts:
        s = starts.popleft()
        if not channel[s] or s in walked:
            continue
        cur = s
        cur_order = int(order[cur])
        name = cells[cur].river_id or ""
        pts: list[tuple[float, float]] = []
        while True:
            walked.add(cur)
            lon, lat = float(cells[cur].lon), float(cells[cur].lat)
            if pts and abs(lon - pts[-1][0]) > 180.0:
                _emit(pts, cur_order, name)  # antimeridian split
                pts = []
            pts.append((lon, lat))
            nxt_id = int(flow[cur])
            nxt = idx_of.get(nxt_id) if nxt_id >= 0 else None
            if nxt is None or not channel[nxt] or nxt in walked:
                break
            if int(order[nxt]) != cur_order:
                starts.append(nxt)  # width class changes downstream
                break
            cur = nxt
        _emit(pts, cur_order, name)

    return features
