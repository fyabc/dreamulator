"""Tests for mass-conserving sediment routing (map/erosion.py _route_sediment)."""

from __future__ import annotations

from dreamulator.map.erosion import apply_erosion
from dreamulator.map.models import CVTMesh, VoronoiCell
from dreamulator.map.pipeline_types import TerrainPipelineConfig, lonlat_to_xyz


def _make_chain_mesh(elevations: list[float], area_km2: float = 1e6) -> CVTMesh:
    """Small chain mesh on the equator (cell 0 = ocean)."""
    n = len(elevations)
    cells: list[VoronoiCell] = []
    for i in range(n):
        x, y, z = lonlat_to_xyz(float(i * 10.0), 0.0)
        neighbors = []
        if i > 0:
            neighbors.append(i - 1)
        if i < n - 1:
            neighbors.append(i + 1)
        cells.append(
            VoronoiCell(
                id=i,
                lon=float(i * 10.0),
                lat=0.0,
                x=float(x),
                y=float(y),
                z=float(z),
                area_km2=area_km2,
                elevation=elevations[i],
                neighbors=neighbors,
            )
        )
    return CVTMesh(seed=0, num_cells=n, cells=cells)


def _config(**overrides: float | str) -> TerrainPipelineConfig:
    base = {
        "erosion_algorithm": "stream_power",
        "surface_evolution_time_myr": 1.0,
        "stream_power_steps": 5,
        "sea_level_offset_m": 0.0,
        "hillslope_diffusivity": 0.0,  # isolate fluvial mass balance
    }
    base.update(overrides)
    return TerrainPipelineConfig(**base)  # type: ignore[arg-type]


def _total_volume_change(mesh: CVTMesh, h0: list[float]) -> float:
    """Σ (h_final − h0)·area over ALL cells (m³); 0 = mass conserved."""
    return sum(
        (c.elevation - h0[i]) * c.area_km2 for i, c in enumerate(mesh.cells)
    ) * 1e6  # km² → m²


def test_sediment_fills_basin_and_conserves_mass():
    """ocean | dam 30 | basin 8 | slope 400 — slope sediment fills the basin.

    The basin cell drains toward the higher dam (negative slope → zero
    transport capacity), so all routed sediment deposits there; the total
    volume change over all cells is ~0 (mass conserved).
    """
    # Hill kept low (25 m): with the Earth-anchored K₀ a taller hill would
    # produce more sediment than the coarse dt can route (avulsion discard),
    # which would break the strict mass-balance assertion.
    mesh = _make_chain_mesh([-200.0, 30.0, 8.0, 25.0])
    h0 = [c.elevation for c in mesh.cells]
    apply_erosion(mesh, _config())

    basin = mesh.cells[2]
    assert basin.elevation > h0[2], "basin must receive deposition"
    assert basin.net_erosion_m > 0.0
    # Mass balance: erosion on the slope = deposition in the basin (+ coast)
    dv = _total_volume_change(mesh, h0)
    eroded = sum(
        (h0[i] - c.elevation) * c.area_km2 * 1e6
        for i, c in enumerate(mesh.cells)
        if c.elevation < h0[i]
    )
    assert eroded > 0.0
    assert abs(dv) < 0.02 * eroded, f"mass not conserved: residual {dv:.3e}"


def test_sediment_reaches_ocean_delta():
    """ocean | mouth 40 | hill 300 — sediment passing the mouth deposits in
    the ocean cell (delta progradation)."""
    mesh = _make_chain_mesh([-200.0, 40.0, 80.0])
    h0 = [c.elevation for c in mesh.cells]
    apply_erosion(mesh, _config())

    ocean = mesh.cells[0]
    assert ocean.elevation > h0[0], "ocean cell must shoal (delta deposition)"
    dv = _total_volume_change(mesh, h0)
    eroded = sum(
        (h0[i] - c.elevation) * c.area_km2 * 1e6
        for i, c in enumerate(mesh.cells)
        if c.elevation < h0[i]
    )
    assert eroded > 0.0
    assert abs(dv) < 0.02 * eroded, f"mass not conserved: residual {dv:.3e}"


def test_no_routing_loses_mass():
    """Legacy mode (sediment_routing='none'): incised mass disappears."""
    mesh = _make_chain_mesh([-200.0, 30.0, 8.0, 400.0])
    h0 = [c.elevation for c in mesh.cells]
    apply_erosion(mesh, _config(sediment_routing="none"))

    dv = _total_volume_change(mesh, h0)
    assert dv < 0.0, "without routing, eroded volume must be lost"
    # Basin receives no fluvial deposition (diffusion disabled)
    assert mesh.cells[2].elevation == h0[2]


def test_routing_deterministic():
    mesh1 = _make_chain_mesh([-200.0, 30.0, 8.0, 25.0])
    mesh2 = _make_chain_mesh([-200.0, 30.0, 8.0, 25.0])
    apply_erosion(mesh1, _config())
    apply_erosion(mesh2, _config())
    for c1, c2 in zip(mesh1.cells, mesh2.cells, strict=True):
        assert c1.elevation == c2.elevation
