"""Orogen cell-mean relief from retained crust (technical debt 43, phase A).

Design: ``docs/design/proposals/orogen-topography.md`` §1.2–1.4 and §3.2.  Each contact
cell of the history contract carries a retained shortening ``L_ret`` (km); the crust it
keeps in the orogen has cross-section ``A = L_ret · H0``.  Airy isostasy turns
thickening into elevation (1 km per ``ρm / (ρm − ρc)`` ≈ 6.6 km of crust), so the
elevation cross-section is ``A / 6.6``.  The profile is a doubly vergent wedge with
separate pro (down-going plate) and retro (overriding plate) flank slopes, both set to
the observed cell-mean flank slope for now, whose top is capped at the mean-elevation
limit of its type (collision: buoyancy–strength force balance; Andean: Altiplano); a
cross-section larger than the capped wedge widens into a plateau on the overriding
plate (volume conservation, Molnar & Lyon-Caen 1988).  Values are cell
means (profile at the cell centre).  Pure function apart from the mesh it reads.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree

if TYPE_CHECKING:
    from dreamulator.map.models import CVTMesh
    from dreamulator.map.orogen_contract import OrogenContract

# Airy: km of crustal thickening per km of elevation, ρm / (ρm − ρc) with
# ρc = 2800, ρm = 3300 kg/m³ (observation-constrained densities).
_AIRY_THICKENING_PER_ELEVATION = 3300.0 / (3300.0 - 2800.0)
# Reference continental crust thickness (km; Earth continental mean, ±5 km).
_REFERENCE_CRUST_KM = 35.0
# Collision cap from a force balance (orogen-topography.md §1.3): a plateau stops rising
# when the buoyancy force of its Airy-compensated thick crust per unit boundary length,
#     ΔF(h) = ρc·g·h·(H0 + h·ρm / (2Δρ)),
# equals the force the lithosphere can transmit, F_L; beyond that it only widens.  ΔF is
# the buoyancy term of the thin viscous sheet equations (England & McKenzie 1982;
# Sonder & England 1986).  F_L is calibrated on the Tibetan plateau surface (~5.0 km on the
# 200k grid, ΔF ≈ 7.1×10¹² N/m) — observation fit — and multiplied by a strength factor
# (1 everywhere until the heat-pipe provinces of debt 44 provide a weakening field).
# The strain-rate dependence of F_L, (U/W)^(1/n), is not included.
_RHO_CRUST = 2800.0
_RHO_MANTLE = 3300.0
_G_EARTH_M_S2 = 9.80665
_TIBET_PLATEAU_M = 5000.0
# Andean cap: Altiplano (~3.8 km on Earth), set by megathrust shear stress rather than
# continental strength (Lamb & Davis 2003); observation calibration scaled by 1/g, an
# assumption ruled by the author 2026-10-21.
_ANDEAN_CAP_EARTH_M = 3800.0
# Flank slopes of the cell-mean profile.  Observation fit (orogen-topography.md §5.1):
# on the 200k grid ETOPO cell-mean flanks are 0.31–0.74° (Tibet north 0.57°, Andes east
# 0.74°, Zagros 0.31°, Alps 0.43° / 0.58°) with the Himalayan front the exception
# (2.81°); the median 0.6° is used on both sides.  Critical-taper theory sets the form
# (slope ∝ effective basal friction / wedge strength, Davis et al. 1983) but décollement
# lithology is unknown on a fictional map, so steep-front classes are left for later.
_PRO_SLOPE_DEG = 0.6
_RETRO_SLOPE_DEG = 0.6
# Contact-cell shortening is averaged along strike over this radius (km) before
# building profiles (cells of one boundary are not independent orogens).
_ALONG_STRIKE_KM = 300.0
# Graph distance limit for the profile search (km); wider than any orogen.
_SEARCH_KM = 3000.0


def _buoyancy_force(h_m: float, gravity_m_s2: float) -> float:
    """ΔF(h) per unit boundary length (N/m) of an Airy-compensated plateau of height h."""
    drho = _RHO_MANTLE - _RHO_CRUST
    h0 = _REFERENCE_CRUST_KM * 1000.0
    return _RHO_CRUST * gravity_m_s2 * h_m * (h0 + h_m * _RHO_MANTLE / (2.0 * drho))


def collision_cap_m(gravity_m_s2: float, strength_factor: float = 1.0) -> float:
    """Mean-elevation cap of a collision plateau (m): solves ΔF(h) = F_L for h."""
    force = strength_factor * _buoyancy_force(_TIBET_PLATEAU_M, _G_EARTH_M_S2)
    drho = _RHO_MANTLE - _RHO_CRUST
    a = _RHO_CRUST * gravity_m_s2 * _RHO_MANTLE / (2.0 * drho)
    b = _RHO_CRUST * gravity_m_s2 * _REFERENCE_CRUST_KM * 1000.0
    return float((-b + np.sqrt(b * b + 4.0 * a * force)) / (2.0 * a))


def andean_cap_m(gravity_m_s2: float) -> float:
    """Mean-elevation cap of an Andean margin (m): Altiplano scaled by 1/g."""
    return _ANDEAN_CAP_EARTH_M * _G_EARTH_M_S2 / gravity_m_s2


def orogen_relief(
    mesh: CVTMesh,
    contract: OrogenContract,
    radius_km: float,
    gravity_m_s2: float,
    base_m: float,
) -> np.ndarray:
    """Cell-mean orogen relief (m above the continental base) on continental cells.

    ``base_m`` is the continental base elevation the relief stands on; the cap applies
    to base + relief.  Each continental cell takes the profile of its nearest contact
    cell (graph distance), on the pro side if it belongs to that segment's down-going
    plate and on the retro side if it belongs to the overriding plate; overlapping
    orogens keep the higher value.
    """
    cells = mesh.cells
    n = len(cells)
    relief = np.zeros(n, dtype=np.float64)
    sources = [k for k, v in contract.retained_km.items() if v > 0.0]
    if not sources:
        return relief
    seg_of = {k: s for s in contract.segments for k in s.cell_ids}
    xyz = mesh.cell_xyz / np.linalg.norm(mesh.cell_xyz, axis=1, keepdims=True)

    # along-strike averaging among contact cells of the same kind
    src = np.array(sorted(sources))
    kinds = np.array([seg_of[int(k)].kind for k in src])
    ret = np.array([contract.retained_km[int(k)] for k in src])
    smooth = np.empty_like(ret)
    for kind in ("collision", "andean"):
        sel = np.flatnonzero(kinds == kind)
        if sel.size == 0:
            continue
        tree = cKDTree(xyz[src[sel]])
        for j, nb in zip(
            sel, tree.query_ball_point(xyz[src[sel]], _ALONG_STRIKE_KM / radius_km), strict=True
        ):
            smooth[j] = ret[sel[nb]].mean()
    smooth_of = dict(zip(src.tolist(), smooth.tolist(), strict=True))

    rows = np.repeat(np.arange(n), [len(c.neighbors) for c in cells])
    cols = np.array([j for c in cells for j in c.neighbors], dtype=np.int64)
    w = np.arccos(np.clip(np.einsum("ij,ij->i", xyz[rows], xyz[cols]), -1.0, 1.0)) * radius_km
    graph = csr_matrix((w, (rows, cols)), shape=(n, n))
    dist, _, nearest = dijkstra(
        graph, indices=src, min_only=True, limit=_SEARCH_KM, return_predecessors=True
    )

    caps_m = {"collision": collision_cap_m(gravity_m_s2), "andean": andean_cap_m(gravity_m_s2)}
    sp = float(np.tan(np.radians(_PRO_SLOPE_DEG)))  # km per km
    sr = float(np.tan(np.radians(_RETRO_SLOPE_DEG)))
    half_inv = 0.5 * (1.0 / sp + 1.0 / sr)  # triangle area = P² · half_inv
    plate_of = [c.plate_id for c in cells]
    for i in np.flatnonzero(np.isfinite(dist)):
        if cells[i].crust_type != "continental":
            continue
        b = int(nearest[i])
        seg = seg_of.get(b)
        if seg is None:
            continue
        if plate_of[i] == seg.retro_plate:
            retro = True
        elif plate_of[i] == seg.pro_plate:
            retro = False
        else:
            continue
        cap_km = max(caps_m[seg.kind] - base_m, 0.0) / 1000.0
        area = smooth_of[b] * _REFERENCE_CRUST_KM / _AIRY_THICKENING_PER_ELEVATION  # km²
        d = float(dist[i])
        peak = float(np.sqrt(area / half_inv))
        if peak <= cap_km:  # wedge below the cap
            v = peak - (sr if retro else sp) * d
        else:  # capped: the excess widens a plateau on the overriding plate
            plateau = (area - cap_km * cap_km * half_inv) / cap_km
            if retro:
                v = cap_km if d <= plateau else cap_km - sr * (d - plateau)
            else:
                v = cap_km - sp * d
        if v > 0.0:
            relief[i] = max(relief[i], 1000.0 * v)
    return relief
