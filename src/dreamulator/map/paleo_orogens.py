"""Old orogens along paleo-sutures (technical debt 43, phase E step 1).

Physics: ``docs/knowledge/geology/terrain_synthesis.md`` §4.3.  An orogen whose collision
ended keeps part of its height: denudation scales with mean elevation and isostatic rebound
returns most of the eroded thickness, so the excess height decays exponentially
(Pinet & Souriau 1988; Pazzaglia & Brandon 1996) towards a residual that erosion thresholds
and sediment-supply feedback maintain for 10⁸ years (Egholm et al. 2013).  The crest of a belt
whose collision ended ``t`` Myr ago stands

    Δh(t) = h_r + (h₀ − h_r) · e^(−t/τ)

above the continental base.  Decay lowers a belt without narrowing it: the cross-section is
the active orogen's wedge, half-width W = h₀ / tan(flank slope) (the observed cell-mean flank
slope of ``orogen_profile``), scaled to the decayed crest, Δh(t) · (1 − d/W).  The suture's
``width_km`` marks the belt for the geological timeline and does not set the orogen width.
Old belts come only from the history input (``plate_history.yaml`` sutures with a collision
age, history-contract.md); without sutures a world has no old orogens (author ruling
2026-10-21).

Closures:

* τ = 70 My — observation fit with isostasy (Pazzaglia & Brandon 1996: 1/(c·k_d) ≈ 68 My;
  global re-fit of Pinet & Souriau ≈ 69 My); range 50–130 My.
* h_r = 400 m — observation fit: crest (90th percentile of cell means) above the adjacent
  platform of belts ~300 My old without later uplift, on the 200k grid: southern
  Appalachians 587 m, northern Appalachians 301 m, Urals 359 m.  The crustal root is not
  the support (roots turn to eclogite, Leech 2001).
* h₀ — the crest of a typical collision of the same world: the median over its collision
  segments of the segment crest (``orogen_profile.collision_crests_m``; Earth's active
  collisions are typically ~1.5–2.2 km); the collision cap above the base when the world has
  no collision (author ruling 2026-10-21).  The geological timeline reads collision ages
  from relief with the inverse of the same law (``collision_age_from_crest``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from dreamulator.map.orogen_profile import _PRO_SLOPE_DEG
from dreamulator.map.paleo_sutures import polyline_geometry

if TYPE_CHECKING:
    from dreamulator.map.models import CVTMesh
    from dreamulator.map.paleo_sutures import AuthorSuture

DECAY_MYR = 70.0
RESIDUAL_CREST_M = 400.0


def residual_crest_m(age_myr: float, active_crest_m: float) -> float:
    """Crest height (m above the continental base) of a belt ``age_myr`` after collision."""
    excess = max(active_crest_m - RESIDUAL_CREST_M, 0.0)
    return float(RESIDUAL_CREST_M + excess * np.exp(-max(age_myr, 0.0) / DECAY_MYR))


def collision_age_from_crest(
    crest_m: float, active_crest_m: float, max_age_myr: float = 400.0
) -> float:
    """Time since collision (Myr) of a belt whose crest stands ``crest_m``: inverse of
    ``residual_crest_m``; a belt at or below the residual gets ``max_age_myr``."""
    excess = crest_m - RESIDUAL_CREST_M
    start = active_crest_m - RESIDUAL_CREST_M
    if excess <= 0.0 or start <= 0.0:
        return max_age_myr
    return float(min(max(DECAY_MYR * np.log(start / excess), 0.0), max_age_myr))


def paleo_orogen_relief(
    mesh: CVTMesh,
    sutures: list[AuthorSuture],
    active_crest_m: float,
    radius_km: float,
) -> np.ndarray:
    """Cell-mean relief (m above the continental base) of old orogens on non-oceanic cells.

    Each suture with a collision age contributes ``residual_crest_m · (1 − d/W)`` within the
    active wedge half-width W of the path; overlapping belts keep the higher value.
    """
    cells = mesh.cells
    relief = np.zeros(len(cells), dtype=np.float64)
    land_crust = np.array([c.crust_type != "oceanic" for c in cells])
    if not sutures or not land_crust.any():
        return relief
    xyz = mesh.cell_xyz / np.linalg.norm(mesh.cell_xyz, axis=1, keepdims=True)
    idx = np.flatnonzero(land_crust)
    half_width_km = active_crest_m / 1000.0 / float(np.tan(np.radians(_PRO_SLOPE_DEG)))
    for s in sutures:
        if s.collision_age_myr is None or len(s.path) < 2:
            continue
        crest = residual_crest_m(s.collision_age_myr, active_crest_m)
        d_km = polyline_geometry(xyz[idx], s.path)[0] * radius_km
        inside = d_km < half_width_km
        v = crest * (1.0 - d_km[inside] / half_width_km)
        tgt = idx[inside]
        relief[tgt] = np.maximum(relief[tgt], v)
    return relief
