"""Snapshots derived from the solved block motions (§4.6, §4.8).

Design: ``docs/design/proposals/geological-timeline.md`` §4.6 and §4.8.  At a
time t every present parcel that existed then moves with its body: continental
crust with its block, present seafloor with the nearest continental block of
its plate (the solver's passive margins), seafloor of plates without continental
crust with the present pole of its plate.  The parcels are resampled onto the
present mesh (``paleo_kinematics.rewind_rotated``).  Mesh cells that no parcel
reaches are seafloor that has since been subducted; they join the nearest
plate, and their age is the distance to a ridge placed midway between the two
nearest plates divided by those plates' half-rate.

The plates of the snapshot are the weld groups at t (plus the plates without
continental crust).  Their boundaries are extracted and typed from the relative
motion of the groups (``paleo_topology``), and checked against the topology
rules of appendix A.3.  Elevation: continental parcels keep their present
elevation less the part of an active orogen built after t (``Orogens``); seafloor
follows the age–depth law of the terrain engine.  The land mask is recomputed
from elevation and sea level with the terrain engine's rule (water connected to
the largest water body is ocean).  Pure numpy/scipy, no IO.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

from dreamulator.map import paleo_topology as pt
from dreamulator.map.paleo_blocks import finite_rotations
from dreamulator.map.paleo_kinematics import ocean_depth_m, rewind_rotated, rotation_matrices

if TYPE_CHECKING:
    from dreamulator.map.paleo_blocks import Blocks
    from dreamulator.map.paleo_history import Orogens
    from dreamulator.map.paleo_kinematics import PlateKinematics

_CM_PER_KM = 1.0e5
# half-rate floor (cm/yr) for the ages of subducted seafloor between plates that
# hardly separate; ages beyond the cooling cap no longer change the depth
_MIN_HALF_RATE_CM_YR = 1.0


@dataclass(frozen=True)
class DepthLaw:
    """Plate-cooling depth law of the terrain engine (positive metres)."""

    ridge_depth_m: float
    subsidence_coeff: float
    max_depth_m: float

    def __call__(self, age_myr: np.ndarray) -> np.ndarray:
        return ocean_depth_m(age_myr, self.ridge_depth_m, self.subsidence_coeff, self.max_depth_m)


@dataclass(frozen=True)
class Snapshot:
    """One time slice on the present mesh.

    Attributes:
        t_myr: time before present.
        label: (N,) plate of each cell (weld group, or ``n_groups + plate`` for
            plates without continental crust).
        continental: (N,) continental crust.
        age_myr: (N,) seafloor age at t (NaN on continents).
        elevation_m: (N,) elevation relative to the present datum.
        land: (N,) land after the connectivity rule.
        src: (N,) present cell sampled by each cell, −1 where subducted seafloor
            was filled in.
        overlap: (N,) parcels of two bodies both lie close to the cell centre.
        omega: (L, 3) pole of each label in the stage containing t.
        topology: typed boundary graph.
        check: topology rules of appendix A.3.
    """

    t_myr: float
    label: np.ndarray
    continental: np.ndarray
    age_myr: np.ndarray
    elevation_m: np.ndarray
    land: np.ndarray
    src: np.ndarray
    overlap: np.ndarray
    omega: np.ndarray
    topology: pt.Topology
    check: pt.TopologyCheck


def ocean_hosts(kin: PlateKinematics, blocks: Blocks) -> np.ndarray:
    """(N,) continental block that each oceanic cell moves with, −1 elsewhere.

    The nearest continental cell of the same plate decides; oceanic cells of
    plates without continental crust get −1.
    """
    host = np.full(kin.n, -1)
    sea = ~kin.continental
    for p in np.unique(kin.plate[sea]):
        cells = np.flatnonzero(sea & (kin.plate == p))
        land = np.flatnonzero((blocks.block >= 0) & (kin.plate == p))
        if land.size:
            _, j = cKDTree(kin.xyz[land]).query(kin.xyz[cells])
            host[cells] = blocks.block[land[j]]
    return host


def land_mask(kin: PlateKinematics, elevation_m: np.ndarray, sea_level_m: float) -> np.ndarray:
    """Land after the terrain engine's rule (``water_bodies.compute_land_mask``).

    A cell is ocean when it lies at or below sea level and belongs to the
    largest connected body of such cells; closed basins below sea level are land.
    """
    rows = np.repeat(np.arange(kin.n), np.diff(kin.nbr_ptr))
    cols = kin.nbr_idx
    water = elevation_m <= sea_level_m
    if not water.any():
        return np.ones(kin.n, dtype=bool)
    both = water[rows] & water[cols]
    g = csr_matrix((np.ones(int(both.sum())), (rows[both], cols[both])), shape=(kin.n, kin.n))
    _, comp = connected_components(g, directed=False)
    size = np.bincount(comp[water])
    ocean = water & (comp == int(np.argmax(size)))
    out: np.ndarray = ~ocean
    return out


def snapshot(
    kin: PlateKinematics,
    blocks: Blocks,
    seafloor_age: np.ndarray,
    stage_omega: np.ndarray,
    groups: np.ndarray,
    stage_myr: float,
    t_myr: float,
    present_omega: np.ndarray,
    elevation_m: np.ndarray,
    depth: DepthLaw,
    orogens: Orogens | None = None,
    sea_level_m: float = 0.0,
) -> Snapshot:
    """Snapshot at ``t_myr`` from the solved stage poles of the blocks.

    ``stage_omega`` (S, B, 3) and ``groups`` (S, B) come from
    ``paleo_solver.solve``; ``present_omega`` (P, 3) moves the plates without
    continental crust; ``seafloor_age`` is the synthetic present age used by the
    solve.  ``orogens`` (from ``paleo_history.active_orogens``) are rolled back
    by the fraction ``min(1, t / build_myr)``.
    """
    nb = blocks.n
    s = min(max(int(np.ceil(t_myr / stage_myr)) - 1, 0), groups.shape[0] - 1)
    group = np.unique(groups[s], return_inverse=True)[1]
    n_groups = int(group.max()) + 1

    frame = (
        finite_rotations(stage_omega, stage_myr, t_myr)
        if t_myr > 0
        else (np.repeat(np.eye(3)[None], nb, axis=0))
    )
    host = ocean_hosts(kin, blocks)
    body = np.where(blocks.block >= 0, blocks.block, host)
    free = body < 0  # seafloor of plates without continental crust
    body = np.where(free, nb + kin.plate, body)
    rot = np.empty((kin.n, 3, 3))
    rot[~free] = frame[body[~free]]
    if free.any():
        rot[free] = rotation_matrices(present_omega, -t_myr * 1.0e6)[kin.plate[free]]
    state = rewind_rotated(kin, seafloor_age, t_myr, rot, body=body)

    ok = state.src >= 0
    src = np.where(ok, state.src, 0)
    b = body[src]
    label = np.where(b < nb, group[np.minimum(b, nb - 1)], n_groups + kin.plate[src])
    omega = np.zeros((n_groups + present_omega.shape[0], 3))
    for g in range(n_groups):
        omega[g] = stage_omega[s][np.flatnonzero(group == g)[0]]
    omega[n_groups:] = present_omega

    # subducted seafloor: nearest plate; age from a ridge midway to the next plate
    gap = ~ok
    if gap.any():
        tree = cKDTree(kin.xyz[ok])
        _, j = tree.query(kin.xyz[gap])
        label[gap] = label[ok][j]
    label = pt.clean_labels(kin, label)

    continental = ok & kin.continental[src]
    age_t = np.full(kin.n, np.nan)
    a0 = seafloor_age[src]
    aged = ok & ~continental & np.isfinite(a0)
    age_t[aged] = a0[aged] - t_myr
    if gap.any():
        age_t[gap] = _gap_age(kin, label, ok, gap, omega)
    # unconstrained present seafloor keeps no age; give it the median of the rest
    rest = ~continental & np.isnan(age_t)
    if rest.any():
        age_t[rest] = float(np.nanmedian(age_t)) if np.isfinite(age_t).any() else 0.0

    # present seafloor: shallower by the cooling it had not yet done (seamounts and
    # other detail survive, t = 0 is the identity); filled-in seafloor: the law
    elev = elevation_m[src].astype(float)
    elev[aged] += depth(a0[aged]) - depth(age_t[aged])
    elev[gap] = -depth(age_t[gap])
    if orogens is not None and t_myr > 0:
        frac = np.minimum(1.0, t_myr / np.maximum(orogens.build_myr[src], 1e-9))
        cut = continental & (orogens.relief_m[src] > 0)
        elev[cut] -= frac[cut] * orogens.relief_m[src][cut]

    topo = pt.extract(kin.xyz, label)
    side_info = (kin.xyz, continental, age_t, cKDTree(kin.xyz))
    pt.classify(topo, omega, kin.radius_km, side_info)
    return Snapshot(
        t_myr=t_myr,
        label=label,
        continental=continental,
        age_myr=np.where(continental, np.nan, age_t),
        elevation_m=elev,
        land=land_mask(kin, elev, sea_level_m),
        src=np.where(ok, state.src, -1),
        overlap=state.overlap,
        omega=omega,
        topology=topo,
        check=pt.check(kin, label),
    )


def _gap_age(
    kin: PlateKinematics,
    label: np.ndarray,
    ok: np.ndarray,
    gap: np.ndarray,
    omega: np.ndarray,
) -> np.ndarray:
    """Age (Myr) of filled-in seafloor: distance to the midway ridge / half-rate.

    For a gap cell of plate A, d_own is the distance to the nearest sampled
    crust of A and d_other to the nearest sampled crust of any other plate B;
    the ridge lies midway, (d_own + d_other) / 2 from A's crust, so the cell is
    (d_other − d_own) / 2 from it.  The half-rate is half the relative speed of
    A and B at the cell, at least ``_MIN_HALF_RATE_CM_YR``.
    """
    cells = np.flatnonzero(gap)
    d_own = np.full(cells.size, np.inf)
    d_other = np.full(cells.size, np.inf)
    other = np.full(cells.size, -1)
    for q in np.unique(label[cells]):
        mine = cells[label[cells] == q]
        sel = np.searchsorted(cells, mine)
        own = np.flatnonzero(ok & (label == q))
        if own.size:
            d_own[sel] = cKDTree(kin.xyz[own]).query(kin.xyz[mine])[0]
        rest = np.flatnonzero(ok & (label != q))
        if rest.size:
            d, j = cKDTree(kin.xyz[rest]).query(kin.xyz[mine])
            d_other[sel] = d
            other[sel] = label[rest[j]]
    d_own = np.where(np.isfinite(d_own), d_own, 0.0) * kin.radius_km
    d_other = np.where(np.isfinite(d_other), d_other, d_own) * kin.radius_km
    own_lab = label[cells]
    rel = np.cross(omega[own_lab] - omega[np.maximum(other, 0)], kin.xyz[cells])
    half = 0.5 * np.linalg.norm(rel, axis=1) * kin.radius_km * _CM_PER_KM
    half = np.maximum(half, _MIN_HALF_RATE_CM_YR)
    dist_km = np.maximum(d_other - d_own, 0.0) / 2.0
    out: np.ndarray = dist_km / (half * 10.0)  # cm/yr → km/Myr
    return out
