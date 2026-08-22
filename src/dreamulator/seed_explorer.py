"""Seed exploration: compare what different RNG seeds produce for a world's terrain.

Cortial-2019 terrain is highly seed-sensitive (roadmap §八 #16): across seeds
42/123/456 @100k, land/sea spatial agreement is only ~74% — different seeds are
genuinely *different planets*, not variants of one planet.  This module is the
statistics/thumbnail kernel for the ``explore-seeds`` CLI: pure functions over an
already-generated ``CVTMesh`` (+ optional plates), no IO, no RNG.

The generation itself is orchestrated by the CLI via
``dreamulator.map.terrain_pipeline.run_terrain_pipeline``; this module only turns
the resulting mesh into comparable numbers and a thumbnail.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from dreamulator.map.models import CVTMesh


def _count_continents(mesh: CVTMesh, sea_level: float) -> int:
    """Number of connected components of land cells over the cell adjacency.

    Mirrors the index-based adjacency built in ``seed_discovery._adjacency``;
    kept local so the statistics stay dependency-free and independently testable.
    """
    n = mesh.num_cells
    id_to_index = {c.id: i for i, c in enumerate(mesh.cells)}
    adj: list[list[int]] = [[] for _ in range(n)]
    for i, c in enumerate(mesh.cells):
        for nid in c.neighbors:
            j = id_to_index.get(nid)
            if j is not None:
                adj[i].append(j)

    land = {i for i, c in enumerate(mesh.cells) if c.elevation >= sea_level}
    seen: set[int] = set()
    components = 0
    for start in land:
        if start in seen:
            continue
        components += 1
        stack = [start]
        seen.add(start)
        while stack:
            u = stack.pop()
            for v in adj[u]:
                if v in land and v not in seen:
                    seen.add(v)
                    stack.append(v)
    return components


def compute_seed_stats(mesh: CVTMesh, sea_level: float = 0.0) -> dict[str, Any]:
    """Compute a compact terrain-comparison stat block for a generated mesh.

    The land/ocean definition follows the climate engine's convention
    (``elevation >= sea_level``), consistent across the comparison table.
    """
    elevations = np.array([c.elevation for c in mesh.cells], dtype=np.float64)
    is_land = elevations >= sea_level
    land_count = int(is_land.sum())
    n = mesh.num_cells

    stats: dict[str, Any] = {
        "num_cells": n,
        "land_fraction": round(land_count / n, 4),
        "ocean_fraction": round(1.0 - land_count / n, 4),
        "mean_land_elevation_m": round(float(elevations[is_land].mean()), 1)
        if land_count
        else None,
        "max_elevation_m": round(float(elevations.max()), 1),
        "max_ocean_depth_m": round(float(elevations[~is_land].min()), 1)
        if land_count < n
        else None,
        "num_continents": _count_continents(mesh, sea_level),
        "num_plates": len({c.plate_id for c in mesh.cells if c.plate_id}),
    }
    return stats


def render_seed_thumbnail(
    mesh: CVTMesh,
    width: int,
    height: int,
    sea_level: float = 0.0,
    elev_min: float | None = None,
    elev_max: float | None = None,
) -> np.ndarray:
    """Render a terrain RGBA thumbnail using the shared frontend palette.

    Elevation range defaults to the standard PNG encoding range (clamped to the
    mesh's actual extremes, like ``save_outputs``) so thumbnails across seeds
    share a common colour scale.
    """
    from dreamulator.map.export import export_cell_index_grid, render_terrain_layer
    from dreamulator.map.palettes import build_adaptive_terrain_lut

    elevations = np.array([c.elevation for c in mesh.cells], dtype=np.float64)
    if elev_min is None:
        elev_min = min(-11_000.0, float(elevations.min()))
    if elev_max is None:
        elev_max = max(9_000.0, float(elevations.max()))

    indices = export_cell_index_grid(mesh, width, height)
    lut = build_adaptive_terrain_lut(elev_min, elev_max, sea_level)
    return render_terrain_layer(mesh, indices, lut, elev_min, elev_max, sea_level)
