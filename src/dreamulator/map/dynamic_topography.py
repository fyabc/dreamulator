"""Dynamic topography of the engine's mantle flow (technical debt 43, phase E step 2).

Physics: ``docs/knowledge/geology/terrain_synthesis.md`` §4.3.1.  Mantle flow deflects the
surface by the radial stress it exerts, h = σ_rr / (Δρ·g) (Hager & Clayton 1989).  The
engine's mantle flow (``plate_generator.coherent_velocity_field``) is a degree-2 poloidal cell
about the poloidal axis (the tidal axis of a locked body, else the rotation axis) plus
degree-2 toroidal cells; toroidal flow has no radial component, so the dynamic topography is
the degree-2 zonal harmonic about that axis,

    h = A · P₂(cos θ),   P₂(x) = (3x² − 1) / 2,

uplift A over the two upwellings (θ = 0, π) and −A/2 along the downwelling ring.  Buoyancy and
the surface deflection both scale with g, so the amplitude carries over between worlds.

Closures:

* A = 800 m under water — observation fit: the degree-2 component of Earth's residual
  (dynamic) topography peaks at ≈ 0.8 ± 0.1 km, water-loaded (Davies et al. 2019; Hoggard
  et al. 2016 find ≤ ±0.5 km at that wavelength).  Under air the same stress deflects the
  surface by (ρm − ρw)/ρm as much, ≈ 550 m; oceanic crust is taken as water-loaded,
  continental and transitional crust as air-loaded.
* The 10³–5×10³ km continental residuals of Earth (±1–2 km, lithosphere thickness and
  small-scale convection, Stephenson et al. 2024) have no counterpart in the engine's flow.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from dreamulator.map.models import CVTMesh

AMPLITUDE_WATER_M = 800.0
_RHO_MANTLE = 3300.0
_RHO_WATER = 1030.0
AMPLITUDE_AIR_M = AMPLITUDE_WATER_M * (_RHO_MANTLE - _RHO_WATER) / _RHO_MANTLE


def dynamic_topography(mesh: CVTMesh, poloidal_axis: np.ndarray) -> np.ndarray:
    """Dynamic topography (m) of every cell: A · P₂ about the poloidal axis."""
    xyz = mesh.cell_xyz / np.linalg.norm(mesh.cell_xyz, axis=1, keepdims=True)
    axis = np.asarray(poloidal_axis, dtype=np.float64)
    c = xyz @ (axis / np.linalg.norm(axis))
    p2 = 0.5 * (3.0 * c * c - 1.0)
    oceanic = np.array([cell.crust_type == "oceanic" for cell in mesh.cells])
    out: np.ndarray = np.where(oceanic, AMPLITUDE_WATER_M, AMPLITUDE_AIR_M) * p2
    return out
