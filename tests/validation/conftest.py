"""Shared fixtures for physical validation tests.

See ``docs/design/climate-validation.md`` §7 (multi-line evidence strategy).
These tests use small synthetic meshes (band-discretized spheres) — the
goal is regime / plausibility behavior, not Earth-map accuracy.
"""

from __future__ import annotations

import math

import numpy as np

from dreamulator.map.models import CVTMesh, VoronoiCell
from dreamulator.map.pipeline_types import TerrainPipelineConfig


def build_validation_mesh(
    num_bands: int = 12,
    cells_per_band: int = 12,
    ocean_bands: tuple[int, ...] = (),
    all_land: bool = False,
) -> CVTMesh:
    """Build a small band-discretized sphere mesh with adjacency.

    Args:
        num_bands: Latitude bands from +82° to -82°.
        cells_per_band: Longitude cells per band.
        ocean_bands: Band indices to set below sea level (default: none).
        all_land: Force every cell continental (overrides ocean_bands).

    Returns:
        CVTMesh with elevation, crust_type, plate_id and adjacency set.
    """
    n = num_bands * cells_per_band
    cells: list[VoronoiCell] = []

    for band in range(num_bands):
        lat = 82.0 - band * 164.0 / (num_bands - 1) if num_bands > 1 else 0.0
        lat_rad = math.radians(lat)
        for j in range(cells_per_band):
            idx = band * cells_per_band + j
            lon = j * 360.0 / cells_per_band - 180.0
            lon_rad = math.radians(lon)
            cos_lat = math.cos(lat_rad)
            x = cos_lat * math.cos(lon_rad)
            y = math.sin(lat_rad)
            z = cos_lat * math.sin(lon_rad)

            is_ocean = (not all_land) and (band in ocean_bands)
            elevation = -2500.0 if is_ocean else 250.0
            crust = "oceanic" if is_ocean else "continental"

            cells.append(
                VoronoiCell(
                    id=idx,
                    x=x,
                    y=y,
                    z=z,
                    lat=lat,
                    lon=lon,
                    area_km2=4.0 * math.pi * 6371.0**2 / n,
                    elevation=elevation,
                    crust_type=crust,
                    water_class="land" if elevation > 0 else "ocean",
                    plate_id="plate_000",
                )
            )

    # Adjacency: longitude ring within each band + meridional links
    adjacency: dict[str, list[int]] = {}
    for band in range(num_bands):
        for j in range(cells_per_band):
            idx = band * cells_per_band + j
            neighbors = [
                band * cells_per_band + (j - 1) % cells_per_band,
                band * cells_per_band + (j + 1) % cells_per_band,
            ]
            if band > 0:
                neighbors.append((band - 1) * cells_per_band + j)
            if band < num_bands - 1:
                neighbors.append((band + 1) * cells_per_band + j)
            adjacency[str(idx)] = neighbors

    mesh = CVTMesh(
        seed=42,
        num_cells=n,
        cells=cells,
        adjacency=adjacency,
    )
    for cell in mesh.cells:
        cell.neighbors = adjacency[str(cell.id)]
    return mesh


def run_climate(mesh: CVTMesh, **config_overrides) -> dict:
    """Run simulate_climate on *mesh* (in place) and return summary stats."""
    from dreamulator.map.climate_simulator import simulate_climate

    config = TerrainPipelineConfig()
    for key, value in config_overrides.items():
        setattr(config, key, value)
    simulate_climate(mesh, config)

    t = np.array([c.temperature_C for c in mesh.cells], dtype=np.float64)
    p = np.array([c.precipitation_mm for c in mesh.cells], dtype=np.float64)
    elev = np.array([c.elevation for c in mesh.cells], dtype=np.float64)
    koppen = [c.koppen_class or "" for c in mesh.cells]
    land = elev >= 0.0
    return {
        "t_mean": float(np.nanmean(t)),
        "t_land_mean": float(np.nanmean(t[land])) if land.any() else float("nan"),
        "t_ocean_mean": float(np.nanmean(t[~land])) if (~land).any() else float("nan"),
        "t_min": float(np.nanmin(t)),
        "t_max": float(np.nanmax(t)),
        "p_mean": float(np.nanmean(p)),
        "koppen": koppen,
        "koppen_counts": {k: koppen.count(k) for k in set(koppen)},
        "land_mask": land,
        "t_array": t,
    }
