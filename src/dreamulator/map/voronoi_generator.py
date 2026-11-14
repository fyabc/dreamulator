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
    """Sample the stored heightmap onto the Voronoi cells, in metres.

    ``elevation`` is the map's normalised raster (``elevation.png``), whose metres are
    ``elevation_min_m`` + v · (``elevation_max_m`` − ``elevation_min_m``) by the map's own
    ``map.yaml``.  The cells get metres, the same semantics as the CVT mesh's
    ``cell.elevation`` that the climate and ecology layers read (land is ``elevation > 0``).

    Args:
        network: Voronoi network with cell positions.
        elevation: 2-D normalised heightmap array in [0, 1].
        elevation_min_m: Metres at value 0 (the map's ``elevation_min_m``).
        elevation_max_m: Metres at value 1 (the map's ``elevation_max_m``).

    Returns:
        Updated network with elevation values in metres.
    """
    h, w = elevation.shape
    span = elevation_max_m - elevation_min_m
    updated_cells: list[VoronoiCell] = []
    for cell in network.cells:
        x, y = lon_lat_to_pixel(cell.lon, cell.lat, w, h)
        updated_cells.append(
            cell.model_copy(
                update={"elevation": float(elevation_min_m + elevation[y, x] * span)},
            )
        )
    return network.model_copy(update={"cells": updated_cells})
