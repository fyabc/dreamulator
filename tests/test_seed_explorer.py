"""Unit tests for the seed-explorer statistics + thumbnail kernel."""

import numpy as np

from dreamulator.map.models import CVTMesh, VoronoiCell
from dreamulator.seed_explorer import (
    _count_continents,
    compute_seed_stats,
    render_seed_thumbnail,
)


def _mesh() -> CVTMesh:
    """Six equatorial cells: 0-1 land (continent A), 2-3 land (B), 4-5 ocean."""
    elevations = [100.0, 200.0, 150.0, 250.0, -2000.0, -4000.0]
    neighbors = [[1], [0], [3], [2], [5], [4]]
    plates = ["p0", "p0", "p1", "p1", "p2", "p2"]
    cells = []
    for i in range(6):
        lon = -150.0 + i * 60.0
        rad = float(np.radians(lon))
        cells.append(
            VoronoiCell(
                id=i,
                lon=lon,
                lat=0.0,
                x=float(np.cos(rad)),
                y=0.0,
                z=float(np.sin(rad)),
                elevation=elevations[i],
                neighbors=neighbors[i],
                plate_id=plates[i],
            )
        )
    return CVTMesh(seed=42, num_cells=len(cells), cells=cells)


def test_compute_seed_stats():
    stats = compute_seed_stats(_mesh(), sea_level=0.0)
    assert stats["num_cells"] == 6
    assert stats["land_fraction"] == round(4 / 6, 4)
    assert stats["ocean_fraction"] == round(2 / 6, 4)
    assert stats["mean_land_elevation_m"] == 175.0
    assert stats["max_elevation_m"] == 250.0
    assert stats["max_ocean_depth_m"] == -4000.0
    assert stats["num_continents"] == 2
    assert stats["num_plates"] == 3


def test_count_continents():
    assert _count_continents(_mesh(), 0.0) == 2


def test_render_seed_thumbnail():
    rgba = render_seed_thumbnail(_mesh(), 64, 32, sea_level=0.0)
    assert rgba.shape == (32, 64, 4)
    assert rgba.dtype == np.uint8
    # Terrain is always fully opaque.
    assert int(rgba[0, 0, 3]) == 255
