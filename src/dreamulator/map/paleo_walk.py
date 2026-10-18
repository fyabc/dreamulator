"""Backward walk of crust parcels on the plate topology layer (T2).

Design: ``docs/design/proposals/plate-topology.md`` §3.  The plate-boundary
graph (``paleo_topology``) decides which plate owns every place; crust parcels
only carry the crust (type, age, elevation) and keep the plate they belong to.
Each step:

1. parcels rotate back with their plates; oceanic parcels younger than ``t``
   are dropped;
2. the graph moves (``paleo_topology.step``; a boundary with continent along one
   side is attached to it) and collisions are re-closed
   (``find_crossings`` / ``reclose``);
3. the graph is rasterized: every cell gets its owning plate;
4. parcels inside another plate's polygon are reconciled by kind:
   * oceanic: overridden or past a closing ridge — deleted;
   * continental over thinned continental crust of the owning plate: the
     stretching is undone — its volume moves into that crust, which thickens
     back to at most the unstretched thickness (pure shear conserves volume,
     as in the deforming networks of Gurnis et al. 2018 and Müller et al.
     2019); a fully absorbed parcel is deleted;
   * the rest: kept and reported as continental overlap — more convergence
     than the thinned crust can take back.  Where the two plates separate
     forward in time and the overlap is deeper than one spacing on average,
     the pre-rift configuration has been reached: the pair's rift onset is set
     to now, whether or not it was a registered rift (an ocean that closed
     going back brings continents into first contact; their breakup time is
     when the conjugate margins stop overlapping, Gurnis et al. 2018).  The
     rift-closure and boundary-jump events below then act on it;
5. cells with no parcel of their owning plate within ``gap_factor`` spacings get
   synthetic oceanic crust of that plate, aged from the ridges of the current
   plate layout (``synthesize_seafloor_age``) — behind trenches this is crust
   consumed after ``t``, between colliding continents it is the ocean that
   closed.

Plate reorganizations (stage poles) happen at drawn times: candidate pole sets
around the current ones are scored by three tectonic rules — small
lithospheric net rotation (Tetley et al. 2019; Müller et al. 2022), ridges in
force keep opening forward in time, and boundaries with continent on both sides
do not open forward (going back that would push the continents into each
other) — measured on the boundary graph's segments.  After a reorganization the
segment types are reclassified and the continental rifts re-registered with the
new motion, onsets counted from the reorganization.

Continental parcels carry a crustal thickness from the present elevation by
Airy isostasy (``crust_thickness_km``); the walk keeps a volume ledger
(parcel volume, volume hidden in overlap, volume moved by unstretching).

Sutures split plates going back (``SutureBelt``, ``inactive_sutures``): at a
suture's collision age the plate holding it is cut along the belt — the
continent on each side, and the rest of the plate by nearest side — and the
split-off side gets a pole that makes the two sides converge across the suture
forward in time (a collision undone going back).

Snapshots sample, for every cell, the nearest parcel of its owning plate.
Elevations follow ``paleo_history``: oceanic parcels by the plate-cooling
increment, active orogens rolled back to their build time.  Pure functions on
numpy arrays, no IO; the only randomness is the seeded reorganization draw.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
from scipy.spatial import cKDTree

from dreamulator.map import paleo_topology as pt
from dreamulator.map.paleo_kinematics import (
    MIN_OPENING_FRAC,
    PlateKinematics,
    boundary_cells,
    boundary_speed_scale,
    fit_rotation,
    ridge_half_rates,
    synthesize_seafloor_age,
)

if TYPE_CHECKING:
    from dreamulator.map.paleo_history import OceanDepth, Orogens, YoungRift


# Airy isostasy (docs/knowledge/geology/isostasy_elevation_limits.md).  Category:
# approximate derivation with standard densities; the sea-level thickness is an
# Earth observation (about 35 km, uncertainty ±5 km) and sets only the absolute
# volume, not the restorable share.
RHO_CRUST = 2800.0  # kg/m³
RHO_MANTLE = 3300.0  # kg/m³
RHO_WATER = 1030.0  # kg/m³
CRUST_AT_SEA_LEVEL_KM = 35.0
_MIN_CRUST_KM = 5.0


def crust_thickness_km(elevation_m: np.ndarray) -> np.ndarray:
    """Continental crustal thickness compensating the elevation (Airy): land
    carries a root of ρc/(ρm − ρc) times its height, sea floor is loaded by water."""
    z = np.asarray(elevation_m, dtype=float) / 1000.0
    land = z * RHO_MANTLE / (RHO_MANTLE - RHO_CRUST)
    sea = z * (RHO_MANTLE - RHO_WATER) / (RHO_MANTLE - RHO_CRUST)
    out: np.ndarray = np.maximum(CRUST_AT_SEA_LEVEL_KM + np.where(z >= 0, land, sea), _MIN_CRUST_KM)
    return out


def elevation_from_thickness_m(thickness_km: np.ndarray) -> np.ndarray:
    """Inverse of ``crust_thickness_km``."""
    dh = np.asarray(thickness_km, dtype=float) - CRUST_AT_SEA_LEVEL_KM
    land = dh * (RHO_MANTLE - RHO_CRUST) / RHO_MANTLE
    sea = dh * (RHO_MANTLE - RHO_CRUST) / (RHO_MANTLE - RHO_WATER)
    out: np.ndarray = 1000.0 * np.where(dh >= 0, land, sea)
    return out


@dataclass(frozen=True)
class WalkConfig:
    """Parameters of the topology walk.

    Attributes:
        dt_myr: longest step.
        max_step_spacings: a step is also no longer than the time the fastest
            plate needs to move this many mesh spacings, so the outcome depends
            on displacement per step, not on the plates' overall speed.
        gap_factor: a cell with no parcel of its plate within this many spacings
            gets synthetic ocean.
        rift_cap_km: stretched width per rift side used for rift onsets
            (onset = 2 · rift_cap_km / opening rate).
        event_grid: points of the fixed sampling sphere for collision events.
        merge_contact_share: two plates merge (a rift closes) when this share of
            their common boundary is continent against continent.
        jump_max_share: a boundary jump moves a continental block only if it has
            at most this share of the smaller plate's continental parcels.  A
            ridge jump strands a microcontinent (Jan Mayen, the Seychelles bank:
            far smaller than either side); a larger block crossing over is a
            merger in disguise and is refused — the pair then merges when its
            contact reaches ``merge_contact_share`` or stays reported as overlap.
            Numerical convention separating the two events, not a fitted value.
        reorg_interval_myr: plate reorganizations are drawn uniformly in this range.
        n_candidates: pole sets drawn per reorganization.
        axis_sigma_deg, speed_sigma: spread of the pole-axis tilt and of the
            log-normal angular-speed change at a reorganization.
        speed_max_cm_yr: cap on any plate's equatorial speed (None = the fastest
            present plate).
        ridge_rule_weight, continent_rule_weight: weights of the closing-ridge and
            opening-continental-boundary fractions in the score.
        continental_speed_factor: at a reorganization a plate's speed is capped at
            speed_max · (1 − (1 − factor) · continental share): plates without
            an attached slab and with continental keels are slow (Forsyth &
            Uyeda 1975; Africa about 2 against Pacific about 10 cm/yr).  Same
            form and default as the terrain engine's continental slowdown.
        contact_onsets: set a pair's rift onset when its continents close up to
            the pre-rift fit (``_contact_onsets``), registered rift or not.
        seed: RNG seed of the reorganizations.
    """

    dt_myr: float = 1.0
    max_step_spacings: float = 0.5
    gap_factor: float = 1.0
    rift_cap_km: float = 300.0
    event_grid: int = 200_000
    merge_contact_share: float = 0.6
    jump_max_share: float = 0.1
    reorg_interval_myr: tuple[float, float] = (10.0, 40.0)
    n_candidates: int = 32
    axis_sigma_deg: float = 20.0
    speed_sigma: float = 0.3
    speed_max_cm_yr: float | None = None
    ridge_rule_weight: float = 2.0
    continent_rule_weight: float = 2.0
    continental_speed_factor: float = 0.3
    contact_onsets: bool = False
    seed: int = 0


@dataclass(frozen=True)
class WalkSnapshot:
    """Cell fields at one epoch.

    Attributes:
        t_myr: epoch, Myr before present.
        plate: (N,) owning plate from the boundary graph.
        continental: (N,) continental crust.
        age_myr: (N,) seafloor age (NaN on continents and unconstrained ocean).
        elevation_m: (N,) elevation relative to the present datum.
        synthetic: (N,) crust added in gaps (not present-day crust).
        topology: the boundary graph at ``t_myr``.
        thickness_km: (N,) continental crustal thickness (0 on ocean).
    """

    t_myr: float
    plate: np.ndarray
    continental: np.ndarray
    age_myr: np.ndarray
    elevation_m: np.ndarray
    synthetic: np.ndarray
    topology: pt.Topology
    thickness_km: np.ndarray


@dataclass
class WalkLog:
    steps: list[dict[str, float | int | dict[str, float]]] = field(default_factory=list)
    collisions: list[dict[str, float | int]] = field(default_factory=list)
    merges: list[dict[str, float | int | str]] = field(default_factory=list)
    reorganizations: list[dict[str, float | int]] = field(default_factory=list)
    refused_jumps: list[dict[str, float | int]] = field(default_factory=list)
    splits: list[dict[str, float | int | str]] = field(default_factory=list)


@dataclass(frozen=True)
class SutureBelt:
    """A suture: an inactive orogenic belt inside a continent.

    Attributes:
        age_myr: collision age; before it the two sides were separate plates.
        cells: present cells of the belt.
        age_source: how the age was estimated.
        leaving_cells: present continental cells of the side that leaves going
            back, when the sides are given (an author suture split by its path,
            ``paleo_sutures.author_suture_belts``); None to find the sides from
            the belt's connectivity.
        closing_rate_cm_yr: convergence rate before the collision, or None for
            the continental-share speed law.
        id: identifier for the log.
    """

    age_myr: float
    cells: np.ndarray
    age_source: str
    leaving_cells: np.ndarray | None = None
    closing_rate_cm_yr: float | None = None
    id: str = ""


def inactive_sutures(
    kin: PlateKinematics,
    elevation_m: np.ndarray,
    orogens: Orogens,
    *,
    min_relief_m: float = 500.0,
    reach_km: float = 300.0,
    min_cells: int = 50,
    decay_myr: float = 50.0,
    max_age_myr: float = 400.0,
) -> list[SutureBelt]:
    """Sutures from the present terrain (geological-timeline §4.0, §4.4).

    A suture is a belt of continental crust standing more than ``min_relief_m``
    above the continental baseline (area median outside active orogens), not an
    active orogen and farther than ``reach_km`` from any plate boundary: high
    ground inside a continent, away from active convergence, is where two
    continents once collided.  Belts are connected sets of such cells with at
    least ``min_cells`` cells.  The collision age comes from post-orogenic
    relief decay as in ``paleo_history.find_sutures``: the median active build
    time plus ``decay_myr`` · ln(R_active / R), R the belt's 90th-percentile
    relief (e-folding times of tens of Myr, Baldwin et al. 2003; observational
    fit with wide uncertainty), capped at ``max_age_myr``.
    """
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import connected_components

    cont = kin.continental
    active = orogens.relief_m > 0
    baseline = float(np.median(elevation_m[cont & ~active]))
    relief = elevation_m - baseline
    bnd = np.flatnonzero(boundary_cells(kin))
    d, _ = cKDTree(kin.xyz[bnd]).query(kin.xyz)
    belt = cont & ~active & (relief > min_relief_m) & (d * kin.radius_km > reach_km)
    r_active = float(np.median(relief[active])) if active.any() else 2.0 * min_relief_m
    t_active = float(np.median(orogens.build_myr[active])) if active.any() else 30.0
    rows = np.repeat(np.arange(kin.n), np.diff(kin.nbr_ptr))
    cols = kin.nbr_idx
    m = belt[rows] & belt[cols]
    g = csr_matrix((np.ones(int(m.sum())), (rows[m], cols[m])), shape=(kin.n, kin.n))
    _, lab = connected_components(g, directed=False)
    out: list[SutureBelt] = []
    for b in np.unique(lab[belt]):
        cells = np.flatnonzero(belt & (lab == b))
        if cells.size < min_cells:
            continue
        r = max(float(np.percentile(relief[cells], 90)), 1.0)
        age = t_active + decay_myr * float(np.log(max(r_active / r, 1.0)))
        out.append(SutureBelt(float(min(age, max_age_myr)), cells, "relief_decay"))
    return sorted(out, key=lambda s: s.age_myr)


def run_topology_walk(
    kin: PlateKinematics,
    topo: pt.Topology,
    age_myr: np.ndarray,
    elevation_m: np.ndarray,
    orogens: Orogens,
    depth: OceanDepth,
    epochs: list[float],
    cfg: WalkConfig,
    side_info: tuple[np.ndarray, np.ndarray, np.ndarray, cKDTree],
    rifts: dict[tuple[int, int], YoungRift] | None = None,
    sutures: list[SutureBelt] | None = None,
) -> tuple[list[WalkSnapshot], WalkLog]:
    """Walk crust parcels and the boundary graph back to ``max(epochs)``.

    ``kin`` carries the plates the graph was extracted from (``topo``) and their
    Euler poles; ``age_myr`` is the synthetic present seafloor age.  The inputs
    are not modified.
    """
    spacing = kin.spacing_km / kin.radius_km
    radius = kin.radius_km
    mesh_tree = cKDTree(kin.xyz)
    cell_area = float(np.median(kin.area_km2))
    grid = pt.event_grid(cfg.event_grid, radius) if cfg.event_grid > 0 else None
    omega = kin.omega.copy()
    log = WalkLog()

    pos = kin.xyz.copy()
    plate = kin.plate.copy()
    cont = kin.continental.copy()
    home = np.arange(kin.n)  # present cell of each parcel (−1: synthetic)
    born = np.where(cont, np.nan, age_myr)
    z_ref = elevation_m.astype(float).copy()
    thick = np.where(cont, crust_thickness_km(z_ref), 0.0)
    plain = cont & (z_ref > 0) & (orogens.relief_m <= 0)
    # unstretched thickness: the median of continental land outside orogens
    h_full = float(np.median(thick[plain])) if plain.any() else CRUST_AT_SEA_LEVEL_KM
    volume0 = float(thick.sum() * np.median(kin.area_km2))
    unstretched_km3 = 0.0
    t_ref = np.zeros(kin.n)
    relief = np.where(cont, orogens.relief_m, 0.0)
    build = np.maximum(orogens.build_myr, 1e-6)
    synthetic = np.zeros(kin.n, dtype=bool)
    ok_age = ~cont & np.isfinite(age_myr)
    default_age = float(np.nanmedian(age_myr[ok_age])) if ok_age.any() else 50.0

    # continental rifts: every continent-continent boundary that opens forward
    budget, onset = continental_rifts(kin, cfg.rift_cap_km, rifts)
    rng = np.random.default_rng(cfg.seed)
    next_reorg = float(rng.uniform(*cfg.reorg_interval_myr))
    speed_cap = cfg.speed_max_cm_yr or float(
        np.linalg.norm(kin.omega, axis=1).max() * radius * 1.0e5
    )
    jumped: set[tuple[int, int]] = set()
    refused: set[tuple[int, int]] = set()
    event_pairs: set[tuple[int, int]] = set()  # plate pairs first made adjacent by an event
    cont_parcels0 = int(cont.sum())
    pending = list(sutures or [])
    min_piece = max(50, int(0.003 * kin.n))  # the enclave rule's size

    def side_now() -> tuple[np.ndarray, np.ndarray, np.ndarray, cKDTree]:
        """Continent and seafloor age per cell from the current parcels (for
        trench polarity and new boundaries)."""
        lab = pt.rasterize(topo, kin, spacing / 3.0)
        src = _owner_parcels(kin.xyz, lab, pos, plate, None)
        s = np.maximum(src, 0)
        cc = (src >= 0) & cont[s]
        ages = np.where(~cc & np.isfinite(born[s]), born[s] - t, np.nan)
        return kin.xyz, cc, ages, mesh_tree

    def snapshot(t: float, label: np.ndarray) -> WalkSnapshot:
        src = _owner_parcels(kin.xyz, label, pos, plate, None)
        has = src >= 0
        s = np.where(has, src, 0)
        z = z_ref.copy()
        aged = ~cont & np.isfinite(born)
        z[aged] += depth(born[aged] - t_ref[aged]) - depth(born[aged] - t)
        cm = cont & (relief > 0)
        z[cm] -= relief[cm] * np.minimum(1.0, t / build[cm])
        age_t = np.where(~cont & np.isfinite(born), born - t, np.nan)
        return WalkSnapshot(
            t_myr=t,
            plate=label.copy(),
            continental=np.where(has, cont[s], False),
            age_myr=np.where(has, age_t[s], np.nan),
            elevation_m=np.where(has, z[s], -depth(np.array([default_age]))[0]),
            synthetic=np.where(has, synthetic[s], True),
            topology=topo,
            thickness_km=np.where(has & cont[s], thick[s], 0.0),
        )

    targets = sorted({float(e) for e in epochs})
    snaps: list[WalkSnapshot] = []
    label = pt.rasterize(topo, kin, spacing / 3.0)
    if targets and targets[0] <= 0.0:
        snaps.append(snapshot(0.0, label))
    t = 0.0
    t_end = targets[-1] if targets else 0.0
    while t < t_end - 1e-9:
        live_w = np.linalg.norm(omega[np.unique(plate)], axis=1)
        v_max_km_myr = float(live_w.max()) * radius * 1.0e6 if live_w.size else 0.0
        step = cfg.dt_myr
        if v_max_km_myr > 0:
            step = min(step, cfg.max_step_spacings * kin.spacing_km / v_max_km_myr)
        next_target = min(e for e in targets if e > t + 1e-9)
        t_new = min(t + step, next_target)
        dt = t_new - t

        # 0. plate reorganization: new stage poles
        if t_new >= next_reorg:
            label_now = pt.rasterize(topo, kin, spacing / 3.0)
            side = side_now()
            cell_cont = side[1]
            live = np.unique(label_now)
            ridge = _segment_probes(topo, side, spacing, want="ridge")
            contb = _segment_probes(topo, side, spacing, want="continental")
            area_p = np.bincount(label_now, weights=kin.area_km2, minlength=omega.shape[0])
            cont_p = np.bincount(
                label_now, weights=kin.area_km2 * cell_cont, minlength=omega.shape[0]
            ) / np.maximum(area_p, 1e-9)
            caps = speed_cap * (1.0 - (1.0 - cfg.continental_speed_factor) * cont_p)
            best, best_score, parts = omega, np.inf, (0.0, 0.0, 0.0)
            for _ in range(cfg.n_candidates):
                cand = _perturb_poles(omega, live, rng, cfg, caps, radius)
                nr = _net_rotation(cand, label_now, kin)
                closing = _opening_fraction(cand, ridge, opening=False)
                opening_c = _opening_fraction(cand, contb, opening=True)
                score = nr + cfg.ridge_rule_weight * closing + cfg.continent_rule_weight * opening_c
                if score < best_score:
                    best, best_score, parts = cand, score, (nr, closing, opening_c)
            omega = best
            pt.classify(topo, omega, radius, side)
            new_budget, new_onset = continental_rifts(
                PlateKinematics(
                    xyz=kin.xyz,
                    nbr_ptr=kin.nbr_ptr,
                    nbr_idx=kin.nbr_idx,
                    plate=label_now,
                    omega=omega,
                    continental=cell_cont,
                    area_km2=kin.area_km2,
                    radius_km=radius,
                ),
                cfg.rift_cap_km,
            )
            budget = new_budget
            onset = {k: t_new + v for k, v in new_onset.items()}
            log.reorganizations.append(
                {
                    "t_myr": t_new,
                    "net_rotation": round(parts[0], 4),
                    "closing_ridge_frac": round(parts[1], 4),
                    "opening_continental_frac": round(parts[2], 4),
                    "ridge_probes": int(len(ridge[0])),
                    "continental_probes": int(len(contb[0])),
                    "rifts": len(budget),
                }
            )
            next_reorg += float(rng.uniform(*cfg.reorg_interval_myr))

        # 1. parcels back with their plates; drop crust younger than t_new
        rot = pt._rotate_points(pos, omega[plate], -dt * 1.0e6)
        pos = rot
        keep = cont | ~np.isfinite(born) | (born >= t_new)
        n_dropped = int((~keep).sum())

        # 2. move the graph (boundaries attached to continents follow them)
        ci = np.flatnonzero(cont & keep)
        continents = (pos[ci], plate[ci], cKDTree(pos[ci]))
        topo = pt.step(topo, omega, dt, 0.5 * spacing, continents)
        hits = pt.find_crossings(topo, 2.0 * spacing) if grid is not None else []
        if hits and grid is not None:
            before = pt.rasterize(topo, kin, spacing / 3.0)
            topo, stats = pt.reclose(topo, grid, spacing, side_now(), omega, radius)
            stats["parcels_followed"] = _follow_ownership(
                mesh_tree, pos, plate, before, pt.rasterize(topo, kin, spacing / 3.0)
            )
            log.collisions.append({"t_myr": t_new, "crossings": len(hits), **stats})

        # 3. owning plate of every cell
        label = pt.rasterize(topo, kin, spacing / 3.0)

        # 4. reconcile parcels lying in another plate's polygon
        _, parcel_cell = mesh_tree.query(pos)
        owner = label[parcel_cell]
        foreign = keep & (owner != plate)
        del_ocean = foreign & ~cont
        keep &= ~del_ocean
        fc = np.flatnonzero(foreign & cont)
        absorbed, moved = _unstretch(
            pos, plate, thick, fc, owner[fc], keep & cont & ~foreign, h_full, spacing
        )
        keep[fc[absorbed]] = False
        unstretched_km3 += moved * cell_area
        # thickened crust stands higher (Airy)
        z_ref = np.where(cont, elevation_from_thickness_m(thick), z_ref)
        overlap = 0.0
        hidden_km3 = 0.0
        by_pair: dict[str, float] = {}
        fc = fc[~absorbed]
        contact_due = (
            _contact_onsets(kin, label, pos, plate, cont, omega, fc, owner[fc])
            if cfg.contact_onsets
            else []
        )
        for pair in contact_due:
            onset[pair] = min(onset.get(pair, np.inf), t_new)
            budget.setdefault(pair, 0.0)
        if fc.size:
            hidden_km3 = float(thick[fc].sum() * cell_area)
            pa = np.minimum(plate[fc], owner[fc])
            pb = np.maximum(plate[fc], owner[fc])
            n_pl = omega.shape[0]
            keys = pa * n_pl + pb
            for key in np.unique(keys):
                sel = fc[keys == key]
                pair = (int(key // n_pl), int(key % n_pl))
                area = sel.size * cell_area
                overlap += area
                tag = (
                    "jumped"
                    if pair in jumped
                    else (
                        "rift_after_onset"
                        if pair in budget and t_new > onset[pair]
                        else ("rift" if pair in budget else "not_rift")
                    )
                )
                by_pair[f"{pair[0]}-{pair[1]}:{tag}"] = round(area / 1e6, 2)
        sel = np.flatnonzero(keep)
        pos, plate, cont, born, thick = pos[sel], plate[sel], cont[sel], born[sel], thick[sel]
        home = home[sel]
        z_ref, t_ref, relief, build, synthetic = (
            z_ref[sel],
            t_ref[sel],
            relief[sel],
            build[sel],
            synthetic[sel],
        )

        # 4b. rift closure: plates whose common boundary is now mostly continent
        # against continent were one plate before the rift opened
        if grid is not None:
            merges = _closed_rifts(
                kin,
                label,
                pos,
                plate,
                cont,
                omega,
                cfg.merge_contact_share,
                t_new,
                onset,
                event_pairs,
            )
            if merges:
                relabel: dict[int, int] = {}
                for kept, gone, why, share in merges:
                    kept = relabel.get(kept, kept)
                    if kept == gone or gone in relabel:
                        continue
                    both = (plate == kept) | (plate == gone)
                    vel = np.cross(omega[plate[both]], pos[both])
                    omega[kept] = fit_rotation(pos[both], vel, np.ones(int(both.sum())))
                    relabel[gone] = kept
                    for k2, v2 in list(relabel.items()):
                        if v2 == gone:
                            relabel[k2] = kept
                    log.merges.append(
                        {
                            "t_myr": t_new,
                            "kept": kept,
                            "merged": gone,
                            "trigger": why,
                            "contact_share": round(share, 3),
                        }
                    )
                for gone, kept in relabel.items():
                    plate[plate == gone] = kept
                before = label.copy()
                topo, _ = pt.reclose(
                    topo, grid, spacing, side_now(), omega, radius, relabel=relabel
                )
                label = pt.rasterize(topo, kin, spacing / 3.0)
                _follow_ownership(mesh_tree, pos, plate, before, label)
                budget, onset = _rename_pairs(budget, onset, relabel)
                event_pairs = _renamed(event_pairs, relabel)
                refused = _renamed(refused, relabel)
                event_pairs |= _adjacent_pairs(kin, label) - _renamed(
                    _adjacent_pairs(kin, before), relabel
                )

        # 4c. boundary jump: a partial rift (older ocean still between the plates)
        # at its onset.  Before the rift opened the continent was whole on one
        # plate and the plate boundary ran around it; the smaller continental
        # block beside the rift goes to the plate across it.
        if grid is not None:
            due = [p for p, d in onset.items() if t_new >= d and p not in refused]
            transfers: list[tuple[np.ndarray, int]] = []
            for pair in due:
                block, to_plate = _jump_block(pos, plate, cont, pair, 1.2 * spacing)
                if block is None:
                    continue
                smaller = min(int(np.sum(cont & (plate == p))) for p in pair)
                if block.size > cfg.jump_max_share * smaller:
                    refused.add(pair)
                    log.refused_jumps.append(
                        {
                            "t_myr": t_new,
                            "a": int(pair[0]),
                            "b": int(pair[1]),
                            "block_Mkm2": round(float(block.size * cell_area / 1e6), 2),
                            "limit_Mkm2": round(
                                float(cfg.jump_max_share * smaller * cell_area / 1e6), 2
                            ),
                        }
                    )
                    continue
                transfers.append((pos[block], to_plate))
                from_plate = int(pair[0] if pair[1] == to_plate else pair[1])
                # the block and the ocean parcels sitting on its cells go across
                _, parcel_cell = mesh_tree.query(pos)
                block_cells = np.unique(parcel_cell[block])
                on_cells = np.isin(parcel_cell, block_cells) & (plate == from_plate)
                plate[block] = to_plate
                plate[on_cells] = to_plate
                budget.pop(pair, None)
                onset.pop(pair, None)
                jumped.add(pair)
                log.merges.append(
                    {
                        "t_myr": t_new,
                        "kept": to_plate,
                        "merged": from_plate,
                        "trigger": "boundary_jump",
                        "contact_share": round(float(block.size * cell_area / 1e6), 2),
                    }
                )
            if transfers:
                before = label.copy()
                topo, _ = pt.reclose(
                    topo, grid, spacing, side_now(), omega, radius, transfers=transfers
                )
                label = pt.rasterize(topo, kin, spacing / 3.0)
                _follow_ownership(mesh_tree, pos, plate, before, label)
                event_pairs |= _adjacent_pairs(kin, label) - _adjacent_pairs(kin, before)

        # 4d. suture split: at its collision age a plate holding a suture splits
        # along it; the split-off side converges on the parent forward in time
        while grid is not None and pending and pending[0].age_myr <= t_new:
            belt = pending.pop(0)
            cut = _suture_pieces(
                pos,
                plate,
                cont,
                home,
                belt.cells,
                kin.n,
                1.2 * spacing,
                min_piece,
                belt.leaving_cells,
            )
            if cut is None:
                continue
            parent, pieces = cut
            transfers = []
            for piece in pieces:
                new_id = omega.shape[0]
                rest = np.flatnonzero((plate == parent) & cont)
                share = float(cont[piece].mean())
                rate = belt.closing_rate_cm_yr or speed_cap * (
                    1.0 - (1.0 - cfg.continental_speed_factor) * share
                )
                omega = np.vstack(
                    [omega, _suture_pole(omega[parent], pos[piece], pos[rest], rate, radius)]
                )
                plate[piece] = new_id
                transfers.append((pos[piece], new_id))
                log.splits.append(
                    {
                        "t_myr": t_new,
                        "parent": int(parent),
                        "new": int(new_id),
                        "age_myr": round(belt.age_myr, 2),
                        "piece_Mkm2": round(piece.size * cell_area / 1e6, 2),
                        "age_source": belt.age_source,
                        "suture": belt.id,
                    }
                )
            before = label.copy()
            topo, _ = pt.reclose(
                topo, grid, spacing, side_now(), omega, radius, transfers=transfers
            )
            label = pt.rasterize(topo, kin, spacing / 3.0)
            _follow_ownership(mesh_tree, pos, plate, before, label)
            event_pairs |= _adjacent_pairs(kin, label) - _adjacent_pairs(kin, before)

        # 5. fill cells that no parcel of their plate covers
        src = _owner_parcels(kin.xyz, label, pos, plate, cfg.gap_factor * spacing)
        gaps = np.flatnonzero(src < 0)
        if gaps.size:
            new_age = _layout_ages(
                kin, label, omega, cont_cells=_cont_cells(kin, label, pos, plate, cont)
            )
            a = np.where(np.isfinite(new_age[gaps]), new_age[gaps], default_age)
            pos = np.vstack([pos, kin.xyz[gaps]])
            plate = np.concatenate([plate, label[gaps]])
            cont = np.concatenate([cont, np.zeros(gaps.size, dtype=bool)])
            home = np.concatenate([home, np.full(gaps.size, -1)])
            thick = np.concatenate([thick, np.zeros(gaps.size)])
            born = np.concatenate([born, t_new + a])
            z_ref = np.concatenate([z_ref, -depth(a)])
            t_ref = np.concatenate([t_ref, np.full(gaps.size, t_new)])
            relief = np.concatenate([relief, np.zeros(gaps.size)])
            build = np.concatenate([build, np.ones(gaps.size)])
            synthetic = np.concatenate([synthetic, np.ones(gaps.size, dtype=bool)])

        t = t_new
        log.steps.append(
            {
                "t_myr": t,
                "parcels": len(pos),
                "dropped": n_dropped,
                "ocean_overridden": int(del_ocean.sum()),
                "gaps_filled": int(gaps.size),
                "unstretched_km3": round(unstretched_km3),
                "continental_overlap_km2": round(overlap),
                "contact_onsets": len(contact_due),
                "volume_parcels_ratio": round(float(thick[cont].sum()) * cell_area / volume0, 4),
                "volume_hidden_ratio": round(hidden_km3 / volume0, 4),
                "continental_parcels_ratio": round(int(cont.sum()) / max(cont_parcels0, 1), 4),
                "overlap_by_pair_Mkm2": dict(sorted(by_pair.items(), key=lambda kv: -kv[1])[:6]),
            }
        )
        if any(abs(t - e) < 1e-9 for e in targets):
            snaps.append(snapshot(t, label))
    return snaps, log


def _unstretch(
    pos: np.ndarray,
    plate: np.ndarray,
    thick: np.ndarray,
    foreign: np.ndarray,
    owner: np.ndarray,
    receivers: np.ndarray,
    h_full: float,
    reach_rad: float,
) -> tuple[np.ndarray, float]:
    """Undo stretching: move the thickness of foreign continental parcels into
    thinned continental parcels of the plate they lie in (in place on ``thick``).

    Each receiver thickens to at most ``h_full``; a foreign parcel gives its
    thickness to receivers within ``reach_rad``, nearest first, and is absorbed
    when nothing is left.  Volume is conserved (parcels stand for equal areas).
    Returns the absorbed mask over ``foreign`` and the thickness moved (km summed
    over parcels).
    """
    done = np.zeros(foreign.size, dtype=bool)
    rec = np.flatnonzero(receivers & (thick < h_full))
    if rec.size == 0 or foreign.size == 0:
        return done, 0.0
    _, nb = cKDTree(pos[rec]).query(pos[foreign], k=8, distance_upper_bound=reach_rad)
    room = h_full - thick[rec]
    moved = 0.0
    for i, f in enumerate(foreign.tolist()):
        need = float(thick[f])
        for j in nb[i].tolist():
            if j >= rec.size:
                break
            if plate[rec[j]] != owner[i] or room[j] <= 0.0:
                continue
            take = min(need, float(room[j]))
            room[j] -= take
            thick[rec[j]] += take
            need -= take
            moved += take
            if need <= 1e-9:
                break
        thick[f] = need
        done[i] = need <= 1e-9
    return done, moved


def _segment_probes(
    topo: pt.Topology,
    side: tuple[np.ndarray, np.ndarray, np.ndarray, cKDTree],
    spacing: float,
    want: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Boundary points for scoring candidate poles: (points, left normals, left
    plate, right plate).

    ``want="ridge"``: points of ridge segments.  ``want="continental"``: points of
    any segment with continental crust within one spacing on both sides.
    """
    _, cc, _, tree = side
    pts, nrm, lp, rp = [], [], [], []
    for seg in topo.segments:
        q = seg.points
        n = np.cross(q, pt.tangents(q))
        if want == "ridge":
            keep = np.full(len(q), seg.kind == pt.RIDGE)
        else:
            sides = []
            for sign in (1.0, -1.0):
                x = q + sign * spacing * n
                x /= np.linalg.norm(x, axis=1, keepdims=True)
                _, idx = tree.query(x)
                sides.append(cc[idx])
            keep = sides[0] & sides[1]
        if keep.any():
            pts.append(q[keep])
            nrm.append(n[keep])
            lp.append(np.full(int(keep.sum()), seg.left))
            rp.append(np.full(int(keep.sum()), seg.right))
    if not pts:
        empty = np.zeros((0, 3))
        return empty, empty, np.zeros(0, dtype=int), np.zeros(0, dtype=int)
    return np.vstack(pts), np.vstack(nrm), np.concatenate(lp), np.concatenate(rp)


def _opening_fraction(
    omega: np.ndarray,
    probes: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray],
    *,
    opening: bool,
) -> float:
    """Share of probe points that open (``opening``) or close forward in time."""
    x, n, a, b = probes
    if len(x) == 0:
        return 0.0
    rate = np.einsum("ij,ij->i", np.cross(omega[a] - omega[b], x), n)
    return float(np.mean(rate > 0) if opening else np.mean(rate < 0))


def _net_rotation(omega: np.ndarray, label: np.ndarray, kin: PlateKinematics) -> float:
    """Lithospheric net rotation as a share of the mean plate angular speed."""
    w = omega[label]
    integrand = w - np.einsum("ij,ij->i", w, kin.xyz)[:, None] * kin.xyz
    a = kin.area_km2
    net = 1.5 * (integrand * a[:, None]).sum(axis=0) / a.sum()
    mean = float((np.linalg.norm(w, axis=1) * a).sum() / a.sum())
    return float(np.linalg.norm(net) / mean) if mean > 0 else 0.0


def _perturb_poles(
    omega: np.ndarray,
    live: np.ndarray,
    rng: np.random.Generator,
    cfg: WalkConfig,
    speed_cap_cm_yr: float | np.ndarray,
    radius_km: float,
) -> np.ndarray:
    """One candidate pole set: each live plate's axis tilted and speed rescaled,
    capped at ``speed_cap_cm_yr`` (one value, or one per plate)."""
    out = omega.copy()
    caps = np.broadcast_to(np.asarray(speed_cap_cm_yr, dtype=float), (omega.shape[0],))
    for p in live.tolist():
        cap = float(caps[p]) / (radius_km * 1.0e5)
        rate = float(np.linalg.norm(omega[p]))
        if rate == 0.0:
            continue
        axis = omega[p] / rate
        perp = np.cross(axis, rng.normal(size=3))
        perp /= max(float(np.linalg.norm(perp)), 1e-15)
        tilt = np.radians(abs(rng.normal(0.0, cfg.axis_sigma_deg)))
        axis = np.cos(tilt) * axis + np.sin(tilt) * perp
        out[p] = axis * min(rate * float(np.exp(rng.normal(0.0, cfg.speed_sigma))), cap)
    return out


def _suture_pieces(
    pos: np.ndarray,
    plate: np.ndarray,
    cont: np.ndarray,
    home: np.ndarray,
    belt_cells: np.ndarray,
    n_cells: int,
    reach_rad: float,
    min_parcels: int,
    leaving_cells: np.ndarray | None = None,
) -> tuple[int, list[np.ndarray]] | None:
    """Parcels of the sides a suture splits off its plate.

    With ``leaving_cells`` (sides given by an author's path) the parent is the
    plate holding most continental parcels of the leaving side; its continental
    parcels from those cells seed the leaving side, its other continental
    parcels outside the belt seed the staying side, and every parcel of the
    plate goes to the nearer seed.  Both sides need ``min_parcels`` seeds.
    Without it the sides are found from the belt's connectivity:

    The plate holding most of the belt's continental parcels is cut: its other
    continental parcels, linked through neighbours within ``reach_rad``, form
    blocks; blocks touching the belt with at least ``min_parcels`` parcels are
    the sides.  Every parcel of the plate (belt and ocean included) goes to the
    nearest side, so the cut runs along the belt and, across the ocean, midway
    between the sides.  The largest side keeps the plate.  Returns (plate, the
    other sides' parcel indices), or None when the belt does not separate two
    sides of one plate.
    """
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import connected_components

    in_belt = np.zeros(n_cells, dtype=bool)
    in_belt[belt_cells] = True
    is_belt = cont & (home >= 0) & in_belt[np.maximum(home, 0)]
    if leaving_cells is not None:
        in_leave = np.zeros(n_cells, dtype=bool)
        in_leave[leaving_cells] = True
        is_leave = cont & (home >= 0) & in_leave[np.maximum(home, 0)]
        if not is_leave.any():
            return None
        parent = int(np.bincount(plate[is_leave]).argmax())
        lseed = np.flatnonzero(is_leave & (plate == parent))
        sseed = np.flatnonzero(cont & (plate == parent) & ~is_leave & ~is_belt)
        if lseed.size < min_parcels or sseed.size < min_parcels:
            return None
        members = np.flatnonzero(plate == parent)
        d_l, _ = cKDTree(pos[lseed]).query(pos[members])
        d_s, _ = cKDTree(pos[sseed]).query(pos[members])
        return parent, [members[d_l < d_s]]
    if not is_belt.any():
        return None
    parent = int(np.bincount(plate[is_belt]).argmax())
    if np.mean(plate[is_belt] == parent) < 0.5:
        return None
    chord = 2.0 * np.sin(reach_rad / 2.0)
    idx = np.flatnonzero(cont & (plate == parent) & ~is_belt)
    bp = pos[is_belt & (plate == parent)]
    if idx.size == 0 or bp.size == 0:
        return None
    pairs = cKDTree(pos[idx]).query_pairs(chord, output_type="ndarray")
    g = csr_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(idx.size, idx.size))
    _, comp = connected_components(g, directed=False)
    touch = np.isfinite(cKDTree(bp).query(pos[idx], distance_upper_bound=chord)[0])
    sizes = np.bincount(comp, minlength=comp.max() + 1)
    sides = [c for c in np.unique(comp[touch]) if sizes[c] >= min_parcels]
    if len(sides) < 2:
        return None
    seeds = np.flatnonzero(np.isin(comp, sides))
    members = np.flatnonzero(plate == parent)
    _, near = cKDTree(pos[idx[seeds]]).query(pos[members])
    side_of = comp[seeds][near]
    counts = {c: int(np.sum(side_of == c)) for c in sides}
    main = max(counts, key=lambda c: counts[c])
    return parent, [members[side_of == c] for c in sides if c != main]


def _suture_pole(
    omega_parent: np.ndarray,
    piece: np.ndarray,
    rest: np.ndarray,
    rate_cm_yr: float,
    radius_km: float,
) -> np.ndarray:
    """Pole of a side split off along a suture.

    Relative to the parent the side rotates about n × c, c the suture midpoint
    (mean of the closest 5 % of piece–rest parcel pairs) and n the direction from
    the parent side to the new side at c, so its forward velocity at c relative
    to the parent is −n at ``rate_cm_yr``: the sides converge forward and
    separate going back.
    """
    _, i_rest = cKDTree(rest).query(piece)
    d = np.linalg.norm(piece - rest[i_rest], axis=1)
    k = np.argsort(d)[: max(1, len(d) // 20)]
    c = (piece[k] + rest[i_rest[k]]).mean(axis=0)
    c /= np.linalg.norm(c)
    n = piece.mean(axis=0) - rest.mean(axis=0)
    n -= (n @ c) * c
    n /= max(float(np.linalg.norm(n)), 1e-15)
    out: np.ndarray = omega_parent + rate_cm_yr / (radius_km * 1.0e5) * np.cross(n, c)
    return out


def _follow_ownership(
    mesh_tree: cKDTree,
    pos: np.ndarray,
    plate: np.ndarray,
    before: np.ndarray,
    after: np.ndarray,
) -> int:
    """Crust follows a change of ownership made by re-closing (in place).

    Where re-closing gives a cell to another plate (a ribbon split along its
    midline, a block transfer, a collision), the parcels there that belonged to
    the old owner now ride with the new one.  Returns the number moved.
    """
    _, cell = mesh_tree.query(pos)
    move = (before[cell] != after[cell]) & (plate == before[cell])
    plate[move] = after[cell[move]]
    return int(move.sum())


def _contact_onsets(
    kin: PlateKinematics,
    label: np.ndarray,
    pos: np.ndarray,
    plate: np.ndarray,
    cont: np.ndarray,
    omega: np.ndarray,
    foreign: np.ndarray,
    owner: np.ndarray,
) -> list[tuple[int, int]]:
    """Plate pairs whose continents have closed up to the pre-rift fit.

    ``foreign`` are continental parcels left in another plate's polygon after
    unstretching, ``owner`` that plate.  A pair qualifies when its plates
    separate forward in time at those parcels (median of the relative velocity
    towards the nearest common boundary edge) and the overlap is on average
    deeper than one spacing along the pair's boundary (parcels stand for one
    cell each; the boundary length counts mesh edges between the two plates).
    Converging pairs do not qualify: their overlap is not a closed rift.
    """
    if foreign.size == 0:
        return []
    rows = np.repeat(np.arange(kin.n), np.diff(kin.nbr_ptr))
    cols = kin.nbr_idx
    m = (rows < cols) & (label[rows] != label[cols])
    i, j = rows[m], cols[m]
    ea, eb = np.minimum(label[i], label[j]), np.maximum(label[i], label[j])
    mid = kin.xyz[i] + kin.xyz[j]
    mid /= np.linalg.norm(mid, axis=1, keepdims=True)
    # parcels per boundary edge for a mean depth of one spacing: edge length
    # (Voronoi edge = spacing / √3) times one spacing over the cell area
    per_edge = kin.spacing_km**2 / np.sqrt(3.0) / float(np.median(kin.area_km2))
    pa = np.minimum(plate[foreign], owner)
    pb = np.maximum(plate[foreign], owner)
    out: list[tuple[int, int]] = []
    for a, b in sorted({(int(x), int(y)) for x, y in zip(pa, pb, strict=True)}):
        sel = foreign[(pa == a) & (pb == b)]
        on_edge = np.flatnonzero((ea == a) & (eb == b))
        if on_edge.size == 0 or sel.size < max(5.0, on_edge.size * per_edge):
            continue
        x = pos[sel]
        _, k = cKDTree(mid[on_edge]).query(x)
        u = mid[on_edge][k] - x
        u -= np.einsum("ij,ij->i", u, x)[:, None] * x
        u /= np.maximum(np.linalg.norm(u, axis=1, keepdims=True), 1e-15)
        other = np.where(plate[sel] == a, b, a)
        v_rel = np.cross(omega[plate[sel]] - omega[other], x)
        if float(np.median(np.einsum("ij,ij->i", v_rel, u))) > 0.0:
            out.append((a, b))
    return out


def _jump_block(
    pos: np.ndarray,
    plate: np.ndarray,
    cont: np.ndarray,
    pair: tuple[int, int],
    reach_rad: float,
) -> tuple[np.ndarray | None, int]:
    """The continental block that changes plate in a boundary jump (parcels).

    Continental parcels of the two plates within ``reach_rad`` of each other are
    the rift contact.  On each side, the continental parcels of that plate linked
    to the contact through neighbours within ``reach_rad`` form a block — parcels
    already pushed into the other plate's polygon included, which cell sampling
    would miss.  The smaller block goes to the other plate.  Returns (parcel
    indices, receiving plate), or (None, −1) without contact.
    """
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import connected_components

    a, b = pair
    chord = 2.0 * np.sin(reach_rad / 2.0)
    ia = np.flatnonzero(cont & (plate == a))
    ib = np.flatnonzero(cont & (plate == b))
    if ia.size == 0 or ib.size == 0:
        return None, -1
    near = cKDTree(pos[ib]).query_ball_point(pos[ia], chord)
    seed_a = ia[[k for k, lst in enumerate(near) if lst]]
    seed_b = np.unique(ib[[j for lst in near for j in lst]]) if seed_a.size else ib[:0]
    if seed_a.size == 0:
        return None, -1
    blocks = {}
    for side, idx, seeds in ((a, ia, seed_a), (b, ib, seed_b)):
        pairs = cKDTree(pos[idx]).query_pairs(chord, output_type="ndarray")
        g = csr_matrix(
            (np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(idx.size, idx.size)
        )
        _, comp = connected_components(g, directed=False)
        local = np.searchsorted(idx, seeds)
        blocks[side] = idx[np.isin(comp, np.unique(comp[local]))]
    small = a if blocks[a].size <= blocks[b].size else b
    other = b if small == a else a
    return blocks[small], other


def _adjacent_pairs(kin: PlateKinematics, label: np.ndarray) -> set[tuple[int, int]]:
    """Plate pairs sharing a mesh edge, as (smaller, larger)."""
    rows = np.repeat(np.arange(kin.n), np.diff(kin.nbr_ptr))
    a, b = label[rows], label[kin.nbr_idx]
    m = a < b
    return {(int(x), int(y)) for x, y in set(zip(a[m].tolist(), b[m].tolist(), strict=True))}


def _renamed(pairs: set[tuple[int, int]], relabel: dict[int, int]) -> set[tuple[int, int]]:
    """Plate pairs after a merger (merged → kept); pairs inside one plate drop out."""
    out = set()
    for a, b in pairs:
        ra, rb = relabel.get(a, a), relabel.get(b, b)
        if ra != rb:
            out.add((min(ra, rb), max(ra, rb)))
    return out


def _rename_pairs(
    budget: dict[tuple[int, int], float],
    onset: dict[tuple[int, int], float],
    relabel: dict[int, int],
) -> tuple[dict[tuple[int, int], float], dict[tuple[int, int], float]]:
    """Rift registries after plate merges: pairs renamed, internal pairs dropped,
    pairs that became the same summed (budget) or the earlier taken (onset)."""
    nb: dict[tuple[int, int], float] = {}
    no: dict[tuple[int, int], float] = {}
    for (a, b), v in budget.items():
        a2, b2 = relabel.get(a, a), relabel.get(b, b)
        if a2 == b2:
            continue
        key = (min(a2, b2), max(a2, b2))
        nb[key] = nb.get(key, 0.0) + v
        no[key] = min(no.get(key, np.inf), onset[(a, b)])
    return nb, no


def continental_rifts(
    kin: PlateKinematics,
    cap_km: float,
    recorded: dict[tuple[int, int], YoungRift] | None = None,
    min_opening_frac: float = MIN_OPENING_FRAC,
) -> tuple[dict[tuple[int, int], float], dict[tuple[int, int], float]]:
    """Restoration budget (km²) and onset (Myr) of every continental rift.

    A continental rift is the set of mesh edges joining continental crust of two
    plates whose relative motion opens them forward in time (median opening above
    ``min_opening_frac`` of ``boundary_speed_scale``).  Its stretched crust
    is at most ``cap_km`` wide on each side (stretching factors 2–3 over rift
    widths of about 100 km), so the budget is 2 · cap_km · length and the onset
    is at most 2 · cap_km / opening rate.  Where the terrain engine recorded the
    rift (``recorded``, extension / rate) the earlier of the two onsets is used,
    since the recorded extension is inflated (roadmap tech debt 33).
    """
    floor = min_opening_frac * boundary_speed_scale(kin)
    rows = np.repeat(np.arange(kin.n), np.diff(kin.nbr_ptr))
    cols = kin.nbr_idx
    m = (rows < cols) & (kin.plate[rows] != kin.plate[cols])
    m &= kin.continental[rows] & kin.continental[cols]
    i, j = rows[m], cols[m]
    x = kin.xyz[i] + kin.xyz[j]
    x /= np.linalg.norm(x, axis=1, keepdims=True)
    n = kin.xyz[i] - kin.xyz[j]
    n -= np.einsum("ij,ij->i", n, x)[:, None] * x
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-15)
    v = np.cross(kin.omega[kin.plate[i]] - kin.omega[kin.plate[j]], x) * kin.radius_km * 1.0e5
    opening = np.einsum("ij,ij->i", v, n)
    pa = np.minimum(kin.plate[i], kin.plate[j])
    pb = np.maximum(kin.plate[i], kin.plate[j])
    edge_km = kin.spacing_km / np.sqrt(3.0)
    budget: dict[tuple[int, int], float] = {}
    onset: dict[tuple[int, int], float] = {}
    for a, b in sorted({(int(a), int(b)) for a, b in zip(pa, pb, strict=True)}):
        sel = (pa == a) & (pb == b)
        rate = float(np.median(opening[sel]))
        if rate <= floor:
            continue
        budget[(a, b)] = 2.0 * cap_km * float(sel.sum() * edge_km)
        t_cap = 2.0 * cap_km / (rate * 10.0)
        t_rec = recorded[(a, b)].onset_myr if recorded and (a, b) in recorded else np.inf
        onset[(a, b)] = float(min(t_cap, t_rec))
    return budget, onset


def _closed_rifts(
    kin: PlateKinematics,
    label: np.ndarray,
    pos: np.ndarray,
    plate: np.ndarray,
    cont: np.ndarray,
    omega: np.ndarray,
    share_needed: float,
    t: float,
    onset: dict[tuple[int, int], float],
    event_pairs: set[tuple[int, int]] | None = None,
) -> list[tuple[int, int, str, float]]:
    """Plate pairs to merge: (kept, merged, trigger, contact share).

    Only pairs that open forward in time (a rift, not a collision) merge.  A pair
    whose common boundary is at least ``share_needed`` continent against
    continent merges at its rift onset; one with ocean still between them merges
    once the share reaches ``share_needed``.  The trigger says why: a
    registered rift at its onset (``rift_onset``), or a pair brought into
    contact by the plates' own motion, the ocean between them having closed going
    back (``ocean_closed``).  A pair that an event (boundary jump, merger, suture
    split) first made adjacent does not merge unless it is a registered rift: its
    contact is the event's doing, not a closed rift (a block split off along a
    suture would otherwise rejoin a neighbour at once).  The larger plate is kept.
    """
    src = _owner_parcels(kin.xyz, label, pos, plate, kin.spacing_km / kin.radius_km)
    cell_cont = (src >= 0) & cont[np.maximum(src, 0)]
    rows = np.repeat(np.arange(kin.n), np.diff(kin.nbr_ptr))
    cols = kin.nbr_idx
    m = (rows < cols) & (label[rows] != label[cols])
    i, j = rows[m], cols[m]
    a, b = np.minimum(label[i], label[j]), np.maximum(label[i], label[j])
    both = cell_cont[i] & cell_cont[j]
    x = kin.xyz[i] + kin.xyz[j]
    x /= np.linalg.norm(x, axis=1, keepdims=True)
    nrm = kin.xyz[i] - kin.xyz[j]
    nrm -= np.einsum("ij,ij->i", nrm, x)[:, None] * x
    nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-15)
    opening = np.einsum("ij,ij->i", np.cross(omega[label[i]] - omega[label[j]], x), nrm)
    area = np.bincount(label, weights=kin.area_km2)
    out: list[tuple[int, int, str, float]] = []
    n_lab = int(label.max()) + 1
    keys = a * n_lab + b
    for key in np.unique(keys):
        sel = keys == key
        contact = sel & both
        if sel.sum() < 5 or not contact.any():
            continue
        share = float(contact.sum() / sel.sum())
        pa, pb = int(key // n_lab), int(key % n_lab)
        opening_ok = float(np.median(opening[contact])) > 0  # forward opening: a rift
        due = onset.get((pa, pb), 0.0)
        if share < share_needed or not opening_ok or t < due:
            continue
        if (pa, pb) in onset:
            trigger = "rift_onset"
        elif event_pairs and (pa, pb) in event_pairs:
            continue  # contact made by an event is no rift closure
        else:
            trigger = "ocean_closed"
        kept, gone = (pa, pb) if area[pa] >= area[pb] else (pb, pa)
        out.append((kept, gone, trigger, share))
    return out


def _owner_parcels(
    xyz: np.ndarray,
    label: np.ndarray,
    pos: np.ndarray,
    plate: np.ndarray,
    max_rad: float | None,
) -> np.ndarray:
    """For every cell, the nearest parcel of its owning plate (−1 if none within
    ``max_rad``; ``None`` = no limit)."""
    out = np.full(len(xyz), -1)
    for p in np.unique(label):
        cells = np.flatnonzero(label == p)
        mine = np.flatnonzero(plate == p)
        if mine.size == 0:
            continue
        chord = 2.0 * np.sin(max_rad / 2.0) if max_rad is not None else np.inf
        d, i = cKDTree(pos[mine]).query(xyz[cells], distance_upper_bound=chord)
        ok = np.isfinite(d)
        out[cells[ok]] = mine[i[ok]]
    return out


def _cont_cells(
    kin: PlateKinematics, label: np.ndarray, pos: np.ndarray, plate: np.ndarray, cont: np.ndarray
) -> np.ndarray:
    """Cells currently covered by continental crust of their owning plate."""
    src = _owner_parcels(kin.xyz, label, pos, plate, kin.spacing_km / kin.radius_km)
    out: np.ndarray = (src >= 0) & cont[np.maximum(src, 0)]
    return out


def _layout_ages(
    kin: PlateKinematics, label: np.ndarray, omega: np.ndarray, cont_cells: np.ndarray
) -> np.ndarray:
    """Seafloor age of every cell from the ridges of the current plate layout."""
    k = PlateKinematics(
        xyz=kin.xyz,
        nbr_ptr=kin.nbr_ptr,
        nbr_idx=kin.nbr_idx,
        plate=label,
        omega=omega,
        continental=cont_cells,
        area_km2=kin.area_km2,
        radius_km=kin.radius_km,
    )
    half, off = ridge_half_rates(k, boundary_cells(k))
    age, _ = synthesize_seafloor_age(k, half, off)
    return age
