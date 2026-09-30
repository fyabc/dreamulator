"""Deep-ocean floor clamp: Earth-envelope caps for continental-crust and
coast-adjacent ocean cells (2026-09-30, nacrea #95271 incident).

Real-Earth CVT reference (ETOPO1 @ ~51 km): continental-crust seafloor min
−5312 m, coast-ring (first ocean ring) min −5979 m.  The clamp must enforce
both floors without letting any clamped cell cross the sea surface.
"""

from __future__ import annotations

import numpy as np

from dreamulator.map.models import CVTMesh, VoronoiCell
from dreamulator.map.pipeline_types import TerrainPipelineConfig
from dreamulator.map.terrain_synthesizer import _clamp_deep_ocean_floors


def _mesh(elevations: list[float], crust: list[str]) -> CVTMesh:
    """5-cell strip: [0]-[4] chained as neighbours, cell 2 is the land island."""
    cells = []
    for i, (el, cr) in enumerate(zip(elevations, crust, strict=True)):
        neighbors = [j for j in (i - 1, i + 1) if 0 <= j < len(elevations)]
        cells.append(
            VoronoiCell(
                id=i,
                lon=float(i * 10.0 - 20.0),
                lat=0.0,
                elevation=el,
                crust_type=cr,
                neighbors=neighbors,
            )
        )
    return CVTMesh(seed=1, num_cells=len(cells), cells=cells)


def test_continental_crust_floor() -> None:
    # Deep continental seafloor (trench relief carved into relabelled crust)
    mesh = _mesh(
        [-100.0, -10481.0, 100.0, -4000.0, -6001.0],
        ["continental", "continental", "continental", "continental", "oceanic"],
    )
    config = TerrainPipelineConfig()
    out = _clamp_deep_ocean_floors(mesh, np.array([c.elevation for c in mesh.cells]), config)
    # Continental ocean cells clamped to −5300 (idx 1 violates the floor);
    # idx 3 (−4000) already above the floor → untouched; oceanic idx 4 is not
    # adjacent to land → untouched; land idx 2 untouched.
    assert out[1] == -5300.0
    assert out[3] == -4000.0
    assert out[4] == -6001.0  # oceanic, not adjacent to land
    assert out[2] == 100.0


def test_coast_ring_floor_oceanic() -> None:
    # Oceanic trench axis directly on the coast (nacrea #95271 shape)
    mesh = _mesh(
        [-2000.0, -9000.0, 50.0, -8000.0, -6500.0],
        ["oceanic", "oceanic", "continental", "oceanic", "oceanic"],
    )
    config = TerrainPipelineConfig()
    elev = np.array([c.elevation for c in mesh.cells])
    out = _clamp_deep_ocean_floors(mesh, elev, config)
    # idx 1 & 3 are coastal (neighbour idx 2 is land) → floored at −6000;
    # idx 4 is one ring further out → untouched.
    assert out[1] == -6000.0
    assert out[3] == -6000.0
    assert out[4] == -6500.0


def test_no_cell_crosses_sea_level() -> None:
    # Even with a high sea-level offset, clamped cells stay submerged.
    mesh = _mesh(
        [-100.0, -10481.0, 100.0, -5500.0, -9000.0],
        ["continental", "continental", "continental", "oceanic", "oceanic"],
    )
    config = TerrainPipelineConfig(sea_level_offset_m=200.0)
    elev = np.array([c.elevation for c in mesh.cells])
    out = _clamp_deep_ocean_floors(mesh, elev, config)
    # 洋侧格全部仍在海平面之下（海岸线不变式）
    assert out[0] <= 200.0 and out[1] <= 200.0 and out[3] <= 200.0 and out[4] <= 200.0


def test_input_array_not_mutated() -> None:
    mesh = _mesh([-100.0, -10481.0, 100.0], ["continental", "continental", "continental"])
    config = TerrainPipelineConfig()
    elev = np.array([c.elevation for c in mesh.cells])
    orig = elev.copy()
    _clamp_deep_ocean_floors(mesh, elev, config)
    assert np.array_equal(elev, orig)
