"""Orogen cell-mean relief from retained crust (technical debt 43, phase A).

Physics and calibration: ``docs/knowledge/geology/orogen_topography.md`` §2–4.  Each contact
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
# Collision cap from a force balance (orogen_topography.md §3): a plateau stops rising
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
# Flank slopes of the cell-mean profile.  Observation fit (orogen_topography.md §4):
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


def collision_crests_m(contract: OrogenContract, gravity_m_s2: float, base_m: float) -> list[float]:
    """Crest relief (m above the continental base) of each collision segment.

    The wedge peak of the segment's median retained shortening, capped at the collision
    mean-elevation cap; segments too young to thicken give 0.
    """
    sp = float(np.tan(np.radians(_PRO_SLOPE_DEG)))
    sr = float(np.tan(np.radians(_RETRO_SLOPE_DEG)))
    half_inv = 0.5 * (1.0 / sp + 1.0 / sr)
    cap_km = max(collision_cap_m(gravity_m_s2) - base_m, 0.0) / 1000.0
    out = []
    for seg in contract.segments:
        if seg.kind != "collision":
            continue
        ret = float(np.median([contract.retained_km.get(k, 0.0) for k in seg.cell_ids]))
        area = max(ret, 0.0) * _REFERENCE_CRUST_KM / _AIRY_THICKENING_PER_ELEVATION
        out.append(1000.0 * min(float(np.sqrt(area / half_inv)), cap_km))
    return out


def _profile_extent_km(
    area_km2: float, cap_km: float, sp: float, sr: float, half_inv: float
) -> float:
    """Distance from the boundary to the far end of a profile (km), retro side."""
    peak = float(np.sqrt(area_km2 / half_inv))
    if peak <= cap_km or cap_km <= 0.0:
        return peak / min(sp, sr) + 1.0
    plateau = (area_km2 - cap_km * cap_km * half_inv) / cap_km
    return plateau + cap_km / min(sp, sr) + 1.0


def orogen_relief(
    mesh: CVTMesh,
    contract: OrogenContract,
    radius_km: float,
    gravity_m_s2: float,
    base_m: float,
    forearc_km: dict[int, float] | None = None,
    *,
    segment_contributions: dict[str, np.ndarray] | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Cell-mean orogen relief (m above the continental base) and the cap that bounds it.

    Returns ``(relief, cap_m)``: ``cap_m`` is the absolute mean-elevation cap (m above
    sea level) of the segment that gave the cell its relief, ``inf`` where there is no
    relief — the synthesizer bounds the final cell mean with it (``apply_orogen_cap``).

    ``base_m`` is the continental base elevation the relief stands on; the cap applies
    to base + relief.  Each continental cell takes the profile of its nearest contact
    cell (graph distance), on the pro side if it belongs to that segment's down-going
    plate and on the retro side if it belongs to the overriding plate; overlapping
    orogens keep the higher value.

    ``forearc_km`` (Andean contact cells, from ``trench_flexure.forearc``) moves an Andean
    profile behind the forearc: its trench-facing flank rises from the forearc's inner edge
    (the coast), so the crest stands one flank length (crest / tan slope) further inland and
    the retro flank continues beyond it; the cross-section is unchanged.
    """
    cells = mesh.cells
    n = len(cells)
    relief = np.zeros(n, dtype=np.float64)
    cap_of = np.full(n, np.inf)
    sources = [k for k, v in contract.retained_km.items() if v > 0.0]
    if segment_contributions is not None:
        segment_contributions.clear()
    if not sources:
        return relief, cap_of
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
    # Each land-crust cell takes the highest profile over all segments, each measured
    # through its own side: the pro side is the down-going plate, the retro side is all
    # land crust beyond the boundary (an overriding plateau spans blocks of several
    # plates).  Taking the nearest contact overall, or stopping a plateau at a plate
    # boundary, cuts cliffs; the maximum over segments is continuous.
    caps_m = {"collision": collision_cap_m(gravity_m_s2), "andean": andean_cap_m(gravity_m_s2)}
    sp = float(np.tan(np.radians(_PRO_SLOPE_DEG)))  # km per km
    sr = float(np.tan(np.radians(_RETRO_SLOPE_DEG)))
    half_inv = 0.5 * (1.0 / sp + 1.0 / sr)  # triangle area = P² · half_inv
    plate_arr = np.array([c.plate_id or "" for c in cells])
    land_crust = np.array([c.crust_type != "oceanic" for c in cells])
    seg_src: dict[str, list[int]] = {}
    for b in src:
        seg_src.setdefault(seg_of[int(b)].id, []).append(int(b))
    segs = {s.id: s for s in contract.segments}
    for sid, bs in seg_src.items():
        seg = segs[sid]
        segment_out = np.zeros(n) if segment_contributions is not None else None
        cap_km = max(caps_m[seg.kind] - base_m, 0.0) / 1000.0
        # search far enough to reach the end of this segment's widest profile
        a_max = max(smooth_of[b] for b in bs) * _REFERENCE_CRUST_KM / _AIRY_THICKENING_PER_ELEVATION
        reach = _profile_extent_km(a_max, cap_km, sp, sr, half_inv)
        if forearc_km is not None and seg.kind == "andean":
            reach += max((forearc_km.get(b, 0.0) for b in bs), default=0.0) + cap_km / sp
        # Far from the boundary a cell sees the whole segment, not one contact cell: the
        # cross-section blends from the local (300 km along-strike) value to the segment
        # mean over a distance equal to the segment length.  Otherwise neighbouring cells
        # whose nearest contacts differ get different plateau widths and a cliff.
        a_seg = float(np.mean([smooth_of[b] for b in bs]))
        bp = xyz[np.array(bs)]
        seg_len = max(
            float(np.arccos(np.clip(bp @ bp.T, -1.0, 1.0)).max()) * radius_km, _ALONG_STRIKE_KM
        )
        pro_cells = plate_arr == seg.pro_plate
        for side_mask, retro in ((~pro_cells, True), (pro_cells, False)):
            own = np.flatnonzero(side_mask & land_crust)
            if own.size == 0:
                continue
            nodes = np.unique(np.concatenate([own, np.array(bs, dtype=np.int64)]))
            d_loc, _, near_loc = dijkstra(
                graph[nodes][:, nodes],
                indices=np.searchsorted(nodes, bs),
                min_only=True,
                limit=reach,
                return_predecessors=True,
            )
            loc = np.searchsorted(nodes, own)
            ok = np.isfinite(d_loc[loc])
            for i, d0, b in zip(own[ok], d_loc[loc[ok]], nodes[near_loc[loc[ok]]], strict=True):
                d = float(d0)
                back = retro  # behind the profile's crest (overriding side)
                t = min(1.0, d / seg_len)
                shortening = (1.0 - t) * smooth_of[int(b)] + t * a_seg
                area = shortening * _REFERENCE_CRUST_KM / _AIRY_THICKENING_PER_ELEVATION
                peak = float(np.sqrt(area / half_inv))
                if retro and forearc_km is not None and seg.kind == "andean":
                    # the trench-facing flank rises from the coast (the forearc's inner
                    # edge): the crest stands one flank length inland of it
                    d -= forearc_km.get(int(b), 0.0) + min(peak, cap_km) / sp
                    if d < 0.0:
                        d, back = -d, False
                if peak <= cap_km:  # wedge below the cap
                    v = peak - (sr if back else sp) * d
                else:  # capped: the excess widens a plateau on the overriding plate
                    plateau = (area - cap_km * cap_km * half_inv) / cap_km
                    if back:
                        v = cap_km if d <= plateau else cap_km - sr * (d - plateau)
                    else:
                        v = cap_km - sp * d
                if segment_out is not None:
                    segment_out[i] = max(1000.0 * v, 0.0)
                if v > 0.0 and 1000.0 * v > relief[i]:
                    relief[i] = 1000.0 * v
                    cap_of[i] = caps_m[seg.kind]
        if segment_contributions is not None and segment_out is not None:
            segment_out.setflags(write=False)
            segment_contributions[sid] = segment_out
    return relief, cap_of


# Softness of the final mean-elevation cap (m): Tibetan plateau cell means scatter by
# ~±0.3 km about 5.0 km on the 200k grid (observation fit).
_CAP_SOFTNESS_M = 300.0


def apply_orogen_cap(elevation_m: np.ndarray, cap_m: np.ndarray, sea_level_m: float) -> np.ndarray:
    """Bound the final cell-mean elevation of orogen cells by their cap (§1.3).

    The collapse limit acts on the actual mean surface, so texture noise added after the
    profile must not lift a plateau above it: excess over the cap is compressed smoothly,
    ``cap + δ·tanh(excess/δ)`` with δ = ``_CAP_SOFTNESS_M``; cells below the cap are
    untouched.
    """
    out = elevation_m.copy()
    cap_abs = cap_m + sea_level_m
    over = np.isfinite(cap_abs) & (out > cap_abs)
    excess = out[over] - cap_abs[over]
    out[over] = cap_abs[over] + _CAP_SOFTNESS_M * np.tanh(excess / _CAP_SOFTNESS_M)
    return out
