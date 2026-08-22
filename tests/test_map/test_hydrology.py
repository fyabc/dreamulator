"""Tests for river network generation (map/hydrology.py)."""

from __future__ import annotations

import numpy as np

from dreamulator.map.hydrology import (
    RIVER_ORDER_THRESHOLDS,
    assign_river_ids,
    classify_rivers,
    compute_flow_accumulation,
    compute_flow_directions,
    detect_closed_basins,
    generate_rivers,
    priority_flood_fill,
    route_flat_cells,
)
from dreamulator.map.models import CVTMesh, VoronoiCell
from dreamulator.map.pipeline_types import TerrainPipelineConfig, lonlat_to_xyz


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


def _chain_dists(n: int) -> list[list[float]]:
    return [[1.0] * len(nbrs) for nbrs in _chain_neighbors(n)]


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
# compute_flow_directions
# ---------------------------------------------------------------------------


def test_flow_directions_steepest_descent():
    """Land cells point to their only downhill neighbour; ocean is a sink."""
    filled = np.array([-100.0, 10.0, 20.0, 30.0, 40.0])
    is_land = np.array([False, True, True, True, True])
    neighbors = _chain_neighbors(5)
    dists = _chain_dists(5)
    flow_dir = compute_flow_directions(filled, is_land, neighbors, dists)

    # 4 → 3 → 2 → 1 → 0, ocean (0) = -1
    assert list(flow_dir) == [-1, 0, 1, 2, 3]


# ---------------------------------------------------------------------------
# route_flat_cells
# ---------------------------------------------------------------------------


def test_flat_cells_route_to_outlet():
    """Flat cells with no downhill neighbour are routed toward the outlet."""
    filled = np.array([-10.0, 10.0, 10.0, 10.0, 30.0])
    is_land = np.array([False, True, True, True, True])
    neighbors = _chain_neighbors(5)
    dists = _chain_dists(5)
    flow_dir = compute_flow_directions(filled, is_land, neighbors, dists)
    # cells 2,3 are flat (gradient 0); cells 1 (→ocean) and 4 (→3) have direction
    assert flow_dir[2] == -1
    assert flow_dir[3] == -1

    connected = np.ones(5, dtype=bool)
    flow_dir = route_flat_cells(filled, is_land, connected, neighbors, flow_dir)
    assert flow_dir[2] == 1  # flat 2 routes toward 1
    assert flow_dir[3] == 2  # flat 3 routes toward 2 (not uphill toward 4)


# ---------------------------------------------------------------------------
# compute_flow_accumulation
# ---------------------------------------------------------------------------


def test_flow_accumulation_chain():
    """Catchment area accumulates upstream; ocean contributes nothing."""
    flow_dir = np.array([-1, 0, 1, 2, 3])
    is_land = np.array([False, True, True, True, True])
    area = np.ones(5)
    accum = compute_flow_accumulation(flow_dir, is_land, area)

    # cell 4 = 1, cell 3 = 2, cell 2 = 3, cell 1 = 4, ocean = 0
    assert list(accum) == [0.0, 4.0, 3.0, 2.0, 1.0]


# ---------------------------------------------------------------------------
# classify_rivers / assign_river_ids
# ---------------------------------------------------------------------------


def test_classify_rivers_thresholds():
    accum = np.array([0.0, 50.0, 500.0, 5_000.0, 500_000.0])
    order = classify_rivers(accum, 1.0, RIVER_ORDER_THRESHOLDS)
    assert list(order) == [0, 0, 1, 2, 4]


def test_classify_rivers_resolution_independent():
    """Thresholds scale with cell area: a 'stream' is ~N cells at any resolution."""
    accum = np.array([0.0, 500.0])
    assert classify_rivers(accum, 1.0)[1] == 1  # 500 km² = 500 cells ≥ 100 (order 1)
    assert classify_rivers(accum, 100.0)[1] == 0  # 500 km² = 5 cells < 100 (no channel)


def test_detect_closed_basins():
    """A below-sea-level cell cut off from the ocean is an endorheic lake."""
    elevation = np.array([-100.0, -90.0, 100.0, -50.0, 200.0])
    neighbors = [[1], [0, 2], [1, 3], [2, 4], [3]]
    is_lake = detect_closed_basins(elevation, 0.0, neighbors)
    assert not is_lake[0] and not is_lake[1]  # ocean component (largest)
    assert is_lake[3]  # isolated below-sea-level cell → lake


def test_assign_river_ids_traces_main_stem():
    """One mouth traces a single upstream main stem."""
    # chain 0(ocean) 1 2 3 4; accum increasing upstream to exceed threshold
    flow_dir = np.array([-1, 0, 1, 2, 3])
    is_land = np.array([False, True, True, True, True])
    accum = np.array([0.0, 50_000.0, 40_000.0, 30_000.0, 20_000.0])
    river_ids = assign_river_ids(flow_dir, is_land, accum, min_accum_km2=1_000.0)

    assert river_ids[0] is None  # ocean
    assert river_ids[1] == "river_0000"  # mouth
    assert all(rid == "river_0000" for rid in river_ids[2:])  # traced upstream


# ---------------------------------------------------------------------------
# generate_rivers (integration)
# ---------------------------------------------------------------------------


def test_generate_rivers_fills_fields():
    """A simple downhill chain yields monotone flow and correct accumulation."""
    mesh = _make_chain_mesh([-100.0, 10.0, 20.0, 30.0, 40.0])
    config = TerrainPipelineConfig(seed=0, sea_level_offset_m=0.0)
    generate_rivers(mesh, config)

    cells = mesh.cells
    assert cells[0].flow_direction is None  # ocean
    assert cells[1].flow_direction == 0
    assert cells[2].flow_direction == 1
    assert cells[3].flow_direction == 2
    assert cells[4].flow_direction == 3

    # accumulation in km² (each cell area = 1 km²)
    assert cells[4].flow_accumulation == 1.0
    assert cells[1].flow_accumulation == 4.0
    assert cells[0].flow_accumulation == 0.0

    # small catchment → no rivers
    assert all(c.river_id is None for c in cells)
    assert all(c.river_order == 0 for c in cells)


def test_generate_rivers_drains_to_ocean_no_cycles():
    """Every land cell reaches the ocean within n hops (no cycles / spurious sinks)."""
    # A pit (cell 2) behind a barrier (cell 1) — fill must connect it to the ocean.
    mesh = _make_chain_mesh([-100.0, 1000.0, 50.0, 100.0])
    config = TerrainPipelineConfig(seed=0, sea_level_offset_m=0.0)
    generate_rivers(mesh, config)

    n = mesh.num_cells
    is_land = np.array([c.elevation >= 0.0 for c in mesh.cells])
    flow_dir = np.array([-1 if c.flow_direction is None else c.flow_direction for c in mesh.cells])

    for start in range(n):
        if not is_land[start]:
            continue
        steps = 0
        cur = start
        while is_land[cur] and flow_dir[cur] >= 0:
            cur = flow_dir[cur]
            steps += 1
            assert steps <= n, f"cycle or runaway flow from cell {start}"
        # terminal must be ocean (reached sea) — no land sink in a connected mesh
        assert not is_land[cur], f"cell {start} ended at land sink {cur}"


def test_generate_rivers_deterministic():
    """Same mesh + seed → identical hydrology fields."""
    mesh1 = _make_chain_mesh([-100.0, 10.0, 20.0, 30.0, 40.0])
    mesh2 = _make_chain_mesh([-100.0, 10.0, 20.0, 30.0, 40.0])
    config = TerrainPipelineConfig(seed=0, sea_level_offset_m=0.0)
    generate_rivers(mesh1, config)
    generate_rivers(mesh2, config)

    for c1, c2 in zip(mesh1.cells, mesh2.cells, strict=True):
        assert c1.flow_direction == c2.flow_direction
        assert c1.flow_accumulation == c2.flow_accumulation
        assert c1.river_id == c2.river_id
        assert c1.river_order == c2.river_order
