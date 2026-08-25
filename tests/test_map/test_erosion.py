"""Tests for fluvial erosion (map/erosion.py + map/precip_proxy.py)."""

from __future__ import annotations

import numpy as np
import pytest

from dreamulator.map.erosion import apply_erosion
from dreamulator.map.models import CVTMesh, VoronoiCell
from dreamulator.map.pipeline_types import TerrainPipelineConfig, lonlat_to_xyz
from dreamulator.map.precip_proxy import geomorphic_precipitation


def _make_chain_mesh(elevations: list[float], area_km2: float = 1.0) -> CVTMesh:
    """Build a small chain CVT mesh on the equator (cell 0 = ocean)."""
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


# ---------------------------------------------------------------------------
# geomorphic_precipitation
# ---------------------------------------------------------------------------


def _proxy_args(elevations, lats_deg):
    """Build geomorphic_precipitation args with empty neighbours (base field only)."""
    n = len(elevations)
    elev = np.array(elevations, dtype=np.float64)
    lat_deg = np.array(lats_deg, dtype=np.float64)
    lat_r = np.radians(lat_deg)
    xyz = np.column_stack([np.cos(lat_r), np.sin(lat_r), np.zeros(n)])
    is_land = np.ones(n, dtype=bool)
    neighbors = [[] for _ in range(n)]
    dists_m = [[] for _ in range(n)]
    return elev, lat_deg, xyz, is_land, neighbors, dists_m


def test_precip_none_uniform():
    elev, lat_deg, xyz, is_land, nb, dm = _proxy_args([0.0, 500.0, 2000.0], [0.0, 0.0, 0.0])
    config = TerrainPipelineConfig(climate_coupling="none", precip_proxy_base_mm=800.0)
    p = geomorphic_precipitation(elev, lat_deg, xyz, is_land, nb, dm, config)
    np.testing.assert_array_equal(p, 800.0)


def test_precip_proxy_base_latitude():
    """Base field: equator wet, pole near-dry (no 0.2 floor).

    ``storm_track_amplitude_mm=0`` isolates the base field from the storm-track
    term (a mid-latitude Gaussian whose tail reaches the pole); the base field
    alone (ITCZ + subtropical suppression) is near-zero at the pole.
    """
    elev, lat_deg, xyz, is_land, nb, dm = _proxy_args([0.0, 0.0, 0.0], [0.0, 45.0, 90.0])
    config = TerrainPipelineConfig(
        climate_coupling="proxy", precip_proxy_base_mm=1000.0, storm_track_amplitude_mm=0.0
    )
    p = geomorphic_precipitation(elev, lat_deg, xyz, is_land, nb, dm, config)

    assert p[0] > 500.0  # equator is wet (near base)
    assert p[2] < 50.0  # pole is near-dry
    assert p[0] > p[2]


def test_precip_full_raises():
    elev, lat_deg, xyz, is_land, nb, dm = _proxy_args([0.0], [0.0])
    config = TerrainPipelineConfig(climate_coupling="full")
    with pytest.raises(NotImplementedError):
        geomorphic_precipitation(elev, lat_deg, xyz, is_land, nb, dm, config)


def test_precip_unknown_raises():
    elev, lat_deg, xyz, is_land, nb, dm = _proxy_args([0.0], [0.0])
    config = TerrainPipelineConfig(climate_coupling="bogus")
    with pytest.raises(ValueError):
        geomorphic_precipitation(elev, lat_deg, xyz, is_land, nb, dm, config)


# ---------------------------------------------------------------------------
# apply_erosion
# ---------------------------------------------------------------------------


def test_apply_erosion_noop_when_disabled():
    mesh = _make_chain_mesh([-100.0, 100.0, 200.0, 300.0])
    before = [c.elevation for c in mesh.cells]
    config = TerrainPipelineConfig(erosion_algorithm="none")
    apply_erosion(mesh, config)
    assert [c.elevation for c in mesh.cells] == before


def test_apply_erosion_lowers_peak():
    """Erosion should lower the highest land cell and never raise it."""
    mesh = _make_chain_mesh([-100.0, 100.0, 200.0, 500.0, 300.0])
    peak_before = max(c.elevation for c in mesh.cells)
    config = TerrainPipelineConfig(erosion_algorithm="stream_power", surface_evolution_time_myr=5.0)
    apply_erosion(mesh, config)
    peak_after = max(c.elevation for c in mesh.cells)
    assert peak_after < peak_before  # peak is incised


def test_apply_erosion_bounded_above_sea_level():
    """No general marine transgression: without a dammed basin, land stays ≥ sea level + 1."""
    mesh = _make_chain_mesh([-100.0, 100.0, 200.0, 500.0, 300.0])
    config = TerrainPipelineConfig(
        erosion_algorithm="stream_power", surface_evolution_time_myr=5.0, sea_level_offset_m=0.0
    )
    apply_erosion(mesh, config)
    for c in mesh.cells:
        if c.elevation > 0.0 or c.id == 0:  # ocean cell 0 stays negative
            pass
        # every non-ocean cell stays at or above sea level + 1
        if c.id != 0:
            assert c.elevation >= 1.0


def test_apply_erosion_deterministic():
    mesh1 = _make_chain_mesh([-100.0, 100.0, 200.0, 500.0, 300.0])
    mesh2 = _make_chain_mesh([-100.0, 100.0, 200.0, 500.0, 300.0])
    config = TerrainPipelineConfig(erosion_algorithm="stream_power", surface_evolution_time_myr=5.0)
    apply_erosion(mesh1, config)
    apply_erosion(mesh2, config)
    for c1, c2 in zip(mesh1.cells, mesh2.cells, strict=True):
        assert c1.elevation == c2.elevation
        assert c1.net_erosion_m == c2.net_erosion_m


def test_apply_erosion_writes_net_erosion():
    mesh = _make_chain_mesh([-100.0, 100.0, 200.0, 500.0, 300.0])
    config = TerrainPipelineConfig(erosion_algorithm="stream_power", surface_evolution_time_myr=5.0)
    apply_erosion(mesh, config)
    # net erosion is filled (negative for eroded peaks, ~0 for ocean)
    assert mesh.cells[3].net_erosion_m < 0.0  # peak eroded
    assert mesh.cells[0].net_erosion_m == 0.0  # ocean untouched


def test_erosion_breaches_dammed_basin():
    """Roadmap §7 #7 capability: erosion cuts open a blocked shallow strait.

    Layout (chain on the equator): ocean | low coast | sill A | sill B |
    inland sea (below sea level, dammed by the sills) | upstream land draining
    into the inland sea.  The sills are worn down to the sea-level clamp and
    then breached so the inland sea connects to the ocean.
    """
    mesh = _make_chain_mesh(
        [-200.0, 2.0, 20.0, 40.0, -50.0, 100.0, 80.0, 60.0], area_km2=1e6
    )
    # Default erodibility K₀ — barrier cells incise without width dilution
    # (concentrated notch).  At this synthetic geometry (1112 km cell spacing,
    # default n=1 fractal scaling) cutting the 40 m sill to the clamp takes
    # ~75 Myr of simulated time; nacrea's 51 km cells incise ~22× faster.
    config = TerrainPipelineConfig(
        erosion_algorithm="stream_power",
        surface_evolution_time_myr=80.0,
        stream_power_steps=5,
        sea_level_offset_m=0.0,
    )
    apply_erosion(mesh, config)

    # Both sill cells are breached below sea level…
    assert mesh.cells[2].elevation < 0.0
    assert mesh.cells[3].elevation < 0.0
    # …so the inland sea (cell 4) reaches the ocean through cells < sea level.
    path = [c.elevation for c in mesh.cells[0:5]]
    assert all(e < 0.0 for e in path), f"dammed basin not connected: {path}"
    # Breach counts as erosion in the bookkeeping.
    assert mesh.cells[2].net_erosion_m < 0.0
    assert mesh.cells[3].net_erosion_m < 0.0


def test_erosion_no_breach_without_dammed_basin():
    """A simple coast (single water body) never triggers the breach pass."""
    mesh = _make_chain_mesh([-100.0, 3.0, 30.0, 10.0], area_km2=1e6)
    config = TerrainPipelineConfig(
        erosion_algorithm="stream_power",
        surface_evolution_time_myr=5.0,
        stream_power_steps=5,
        sea_level_offset_m=0.0,
    )
    apply_erosion(mesh, config)
    for c in mesh.cells[1:]:
        assert c.elevation >= 1.0  # land stays at or above the clamp


def test_erosion_never_raises_land():
    """Erosion must never raise a cell (no fabricated deposition).

    Flat-routed cells behind a dammed basin can have an uphill downstream
    parent; the overshoot guard must not lift them to the parent's elevation.
    """
    elevations = [-200.0, 2.0, 20.0, 40.0, -50.0, 100.0, 80.0, 60.0]
    mesh = _make_chain_mesh(elevations, area_km2=1e6)
    config = TerrainPipelineConfig(
        erosion_algorithm="stream_power",
        surface_evolution_time_myr=5.0,
        stream_power_steps=5,
        sea_level_offset_m=0.0,
    )
    apply_erosion(mesh, config)
    for c, h0 in zip(mesh.cells, elevations, strict=True):
        assert c.elevation <= h0 + 1e-9, f"cell {c.id} raised {h0} -> {c.elevation}"


def test_stream_power_steps_stable_and_deterministic():
    """Implicit scheme with a small step count stays stable and deterministic."""
    mesh1 = _make_chain_mesh([-100.0, 100.0, 200.0, 500.0, 300.0])
    mesh2 = _make_chain_mesh([-100.0, 100.0, 200.0, 500.0, 300.0])
    config = TerrainPipelineConfig(
        erosion_algorithm="stream_power",
        surface_evolution_time_myr=5.0,
        stream_power_steps=5,
    )
    apply_erosion(mesh1, config)
    apply_erosion(mesh2, config)
    assert mesh1.cells[0].elevation == -100.0  # ocean unchanged
    assert any(c.net_erosion_m < 0.0 for c in mesh1.cells[1:])  # erosion happened
    for c1, c2 in zip(mesh1.cells, mesh2.cells, strict=True):
        assert c1.elevation == c2.elevation
