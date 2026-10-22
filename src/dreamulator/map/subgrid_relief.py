"""Sub-grid relief and peak elevation of land cells (technical debt 43, phase C).

Physics and calibration: ``docs/knowledge/geology/orogen_topography.md`` §1.  A cell value is the
mean elevation over ~50 km; the relief inside a cell and its highest point are separate
quantities, needed by sub-grid orography schemes (Lott & Miller 1997) and as canvas
conditioning.  Both are read from the cell-mean field itself:

* ``relief_std_m`` μ grows with the regional gradient S (mean |Δz| / distance to the
  neighbours) times the cell size Δx, saturating at threshold-hillslope relief
  (Montgomery & Brandon 2002):  μ = c·Δx·S / (1 + c·Δx·S / μ_sat).
* ``peak_elevation_m`` = mean + r·μ.

Calibration (observation fit, Earth land, orogen_topography.md §1): Copernicus 90 m
DEM statistics in 2722 fully covered land cells of the 200k mesh (Himalaya–Tibet,
central Andes, Alps, Ahaggar, Tibesti, Appalachians, Great Plains) against the slope of
ETOPO cell means: c ≈ 0.97, μ_sat ≈ 2.9 km (log residual std 0.69, i.e. a factor of
two per cell); the peak sits a median 3.5 μ above the mean.  Land cells only, and the
slope uses land neighbours only: the calibration cells were fully covered land, so a
coast (a drop to the sea surface or seafloor) is outside it.  Ocean cells get None
(trench depths belong to phase D).  Pure function.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from dreamulator.map.models import CVTMesh

_RELIEF_COEFF = 0.97
_RELIEF_SATURATION_M = 2900.0
_PEAK_STD_RATIO = 3.5


def subgrid_relief(
    mesh: CVTMesh, radius_km: float, sea_level_m: float = 0.0
) -> tuple[np.ndarray, np.ndarray]:
    """(relief_std_m, peak_elevation_m) per cell; NaN on cells at or below sea level."""
    cells = mesh.cells
    n = len(cells)
    xyz = mesh.cell_xyz / np.linalg.norm(mesh.cell_xyz, axis=1, keepdims=True)
    z = np.array([c.elevation for c in cells], dtype=np.float64)
    land = z > sea_level_m
    rows = np.repeat(np.arange(n), [len(c.neighbors) for c in cells])
    cols = np.array([j for c in cells for j in c.neighbors], dtype=np.int64)
    dist_m = (
        np.arccos(np.clip(np.einsum("ij,ij->i", xyz[rows], xyz[cols]), -1.0, 1.0))
        * radius_km
        * 1000.0
    )
    pair = land[rows] & land[cols]
    grad = np.where(pair, np.abs(z[cols] - z[rows]) / np.maximum(dist_m, 1.0), 0.0)
    slope = np.bincount(rows, grad, n) / np.maximum(np.bincount(rows, pair.astype(float), n), 1)
    dx_m = float(np.sqrt(4.0 * np.pi * (radius_km * 1000.0) ** 2 / n))
    x = _RELIEF_COEFF * dx_m * slope
    std = x / (1.0 + x / _RELIEF_SATURATION_M)
    peak = z + _PEAK_STD_RATIO * std
    std = np.where(land, std, np.nan)
    peak = np.where(land, peak, np.nan)
    return std, peak
