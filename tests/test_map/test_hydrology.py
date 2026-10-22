"""Tests for depression fill and closed-basin lakes (map/hydrology.py)."""

from __future__ import annotations

import numpy as np

from dreamulator.map.hydrology import (
    detect_closed_basins,
    mark_closed_basin_lakes,
    priority_flood_fill,
)
from dreamulator.map.models import CVTMesh, VoronoiCell
from dreamulator.map.pipeline_types import lonlat_to_xyz


def _chain_neighbors(n: int) -> list[list[int]]:
    """Neighbour lists for a 1-D chain 0-1-2-...-(n-1)."""
    out: list[list[int]] = []
    for i in range(n):
        nbrs = []
        if i > 0:
            nbrs.append(i - 1)
        if i < n - 1:
            nbrs.append(i + 1)
        out.append(nbrs)
    return out


def _make_chain_mesh(elevations: list[float], area_km2: list[float] | None = None) -> CVTMesh:
    """Build a small chain CVT mesh on the equator (cell 0 = ocean)."""
    n = len(elevations)
    cells: list[VoronoiCell] = []
    neighbors = _chain_neighbors(n)
    for i in range(n):
        x, y, z = lonlat_to_xyz(float(i * 10.0), 0.0)  # 10° spacing on equator
        cells.append(
            VoronoiCell(
                id=i,
                lon=float(i * 10.0),
                lat=0.0,
                x=float(x),
                y=float(y),
                z=float(z),
                area_km2=1.0 if area_km2 is None else area_km2[i],
                elevation=elevations[i],
                neighbors=neighbors[i],
            )
        )
    return CVTMesh(seed=0, num_cells=n, cells=cells)


# ---------------------------------------------------------------------------
# priority_flood_fill
# ---------------------------------------------------------------------------


def test_fill_raises_pit_to_spill_level():
    """A pit behind a barrier is filled to the barrier's spill height."""
    elev = np.array([-100.0, 1000.0, 50.0, 100.0])  # 0=ocean, 1=barrier, 2=pit, 3=land
    is_land = elev >= 0.0
    neighbors = _chain_neighbors(4)
    filled, connected = priority_flood_fill(elev, is_land, neighbors)

    assert filled[0] == -100.0  # ocean unchanged
    assert filled[2] == 1000.0  # pit raised to spill over the barrier
    assert filled[3] == 1000.0  # interior cell raised too
    assert bool(connected.all())  # connected sphere: everything reaches ocean


def test_fill_is_noop_without_pits():
    """A monotonic slope has no depressions; fill leaves it unchanged."""
    elev = np.array([-100.0, 10.0, 20.0, 30.0])
    is_land = elev >= 0.0
    neighbors = _chain_neighbors(4)
    filled, _ = priority_flood_fill(elev, is_land, neighbors)
    np.testing.assert_array_equal(filled, elev)


# ---------------------------------------------------------------------------
# detect_closed_basins
# ---------------------------------------------------------------------------


def test_detect_closed_basins():
    """A below-sea-level cell cut off from the ocean is an endorheic lake."""
    elevation = np.array([-100.0, -90.0, 100.0, -50.0, 200.0])
    neighbors = [[1], [0, 2], [1, 3], [2, 4], [3]]
    is_lake = detect_closed_basins(elevation, 0.0, neighbors)
    assert not is_lake[0] and not is_lake[1]  # ocean component (largest)
    assert is_lake[3]  # isolated below-sea-level cell → lake


def test_mark_closed_basin_lakes_keeps_existing():
    """Closed basins become lakes; lakes marked earlier (deposition fill) stay lakes."""
    mesh = _make_chain_mesh([-100.0, -90.0, 100.0, -50.0, 200.0, 30.0])
    mesh.cells[5].is_lake = True
    assert mark_closed_basin_lakes(mesh, 0.0) == 1
    assert [c.is_lake for c in mesh.cells] == [False, False, False, True, False, True]
