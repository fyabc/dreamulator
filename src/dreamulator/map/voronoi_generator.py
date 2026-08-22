"""Voronoi network helper — heightmap sampling.

The legacy Voronoi-network generation and plate assignment (generate_voronoi,
assign_cells_to_plates) were removed together with the old heightmap-based
pipeline; the current build uses cvt_mesh.py + plate_generator.py.
sample_heightmap is kept because sync_voronoi_from_elevation (the elevation
import workflow) still uses it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .elevation_codec import lon_lat_to_pixel

if TYPE_CHECKING:
    import numpy as np

    from .models import VoronoiCell, VoronoiNetwork


def sample_heightmap(
    network: VoronoiNetwork,
    elevation: np.ndarray,
    elevation_min_m: float = -11_000.0,
    elevation_max_m: float = 9_000.0,
) -> VoronoiNetwork:
    """Sample elevation values from the heightmap for each Voronoi cell.

    Args:
        network: Voronoi network with cell positions.
        elevation: 2-D normalised heightmap array.
        elevation_min_m: Minimum elevation in metres (unused, for API compat).
        elevation_max_m: Maximum elevation in metres (unused, for API compat).

    Returns:
        Updated network with elevation values filled in.
    """
    h, w = elevation.shape
    updated_cells: list[VoronoiCell] = []
    for cell in network.cells:
        x, y = lon_lat_to_pixel(cell.lon, cell.lat, w, h)
        updated_cells.append(
            cell.model_copy(
                update={"elevation": float(elevation[y, x])},
            )
        )
    return network.model_copy(update={"cells": updated_cells})
