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
   * continental across a young rift (``YoungRift``) before its onset: stretched
     crust restored — deleted, at most ``rift_cap_km`` per side times the rift
     length per plate pair (the terrain engine's recorded extension is
     inflated, roadmap tech debt 33, so a physical cap of rift width at
     stretching factors 2–3 applies);
   * other continental: kept and reported as continental overlap, a signal
     that an event (rift closure, suture) is due;
5. cells with no parcel of their owning plate within ``gap_factor`` spacings get
   synthetic oceanic crust of that plate, aged from the ridges of the current
   plate layout (``synthesize_seafloor_age``) — behind trenches this is crust
   consumed after ``t``, between colliding continents it is the ocean that
   closed.

Snapshots sample, for every cell, the nearest parcel of its owning plate.
Elevations follow ``paleo_history``: oceanic parcels by the plate-cooling
increment, active orogens rolled back to their build time.  Poles are fixed in
T2.  Pure functions on numpy arrays, no IO, no RNG.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
from scipy.spatial import cKDTree

from dreamulator.map import paleo_topology as pt
from dreamulator.map.paleo_kinematics import (
    PlateKinematics,
    boundary_cells,
    fit_rotation,
    ridge_half_rates,
    synthesize_seafloor_age,
)

if TYPE_CHECKING:
    from dreamulator.map.paleo_history import OceanDepth, Orogens, YoungRift


@dataclass(frozen=True)
class WalkConfig:
    """Parameters of the topology walk.

    Attributes:
        dt_myr: step length.
        gap_factor: a cell with no parcel of its plate within this many spacings
            gets synthetic ocean.
        rift_cap_km: largest stretched width restored per rift side.
        event_grid: points of the fixed sampling sphere for collision events.
        merge_contact_share: two plates merge (a rift closes) when this share of
            their common boundary is continent against continent.
    """

    dt_myr: float = 1.0
    gap_factor: float = 1.0
    rift_cap_km: float = 300.0
    event_grid: int = 200_000
    merge_contact_share: float = 0.6


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
    """

    t_myr: float
    plate: np.ndarray
    continental: np.ndarray
    age_myr: np.ndarray
    elevation_m: np.ndarray
    synthetic: np.ndarray
    topology: pt.Topology


@dataclass
class WalkLog:
    steps: list[dict[str, float | int | dict[str, float]]] = field(default_factory=list)
    collisions: list[dict[str, float | int]] = field(default_factory=list)
    merges: list[dict[str, float | int | str]] = field(default_factory=list)


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
    born = np.where(cont, np.nan, age_myr)
    z_ref = elevation_m.astype(float).copy()
    t_ref = np.zeros(kin.n)
    relief = np.where(cont, orogens.relief_m, 0.0)
    build = np.maximum(orogens.build_myr, 1e-6)
    synthetic = np.zeros(kin.n, dtype=bool)
    ok_age = ~cont & np.isfinite(age_myr)
    default_age = float(np.nanmedian(age_myr[ok_age])) if ok_age.any() else 50.0

    # continental rifts: every continent-continent boundary that opens forward
    budget, onset = continental_rifts(kin, cfg.rift_cap_km, rifts)
    jumped: set[tuple[int, int]] = set()
    n_pl = omega.shape[0]
    cont_parcels0 = int(cont.sum())

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
        )

    targets = sorted({float(e) for e in epochs})
    snaps: list[WalkSnapshot] = []
    label = pt.rasterize(topo, kin, spacing / 3.0)
    if targets and targets[0] <= 0.0:
        snaps.append(snapshot(0.0, label))
    t = 0.0
    t_end = targets[-1] if targets else 0.0
    while t < t_end - 1e-9:
        t_new = min(t + cfg.dt_myr, t_end)
        dt = t_new - t

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
            topo, stats = pt.reclose(topo, grid, spacing, side_info, omega, radius)
            log.collisions.append({"t_myr": t_new, "crossings": len(hits), **stats})

        # 3. owning plate of every cell
        label = pt.rasterize(topo, kin, spacing / 3.0)

        # 4. reconcile parcels lying in another plate's polygon
        _, parcel_cell = mesh_tree.query(pos)
        owner = label[parcel_cell]
        foreign = keep & (owner != plate)
        del_ocean = foreign & ~cont
        keep &= ~del_ocean
        rift_deleted = 0.0
        overlap = 0.0
        by_pair: dict[str, float] = {}
        fc = np.flatnonzero(foreign & cont)
        if fc.size:
            pa = np.minimum(plate[fc], owner[fc])
            pb = np.maximum(plate[fc], owner[fc])
            keys = pa * n_pl + pb
            for key in np.unique(keys):
                sel = fc[keys == key]
                pair = (int(key // n_pl), int(key % n_pl))
                area = sel.size * cell_area
                if pair in budget and t_new <= onset[pair] and budget[pair] > 0:
                    # stretched rift crust: restore up to the budget, lowest first
                    order = sel[np.argsort(z_ref[sel])]
                    n_take = int(min(order.size, budget[pair] // cell_area))
                    keep[order[:n_take]] = False
                    budget[pair] -= n_take * cell_area
                    rift_deleted += n_take * cell_area
                    overlap += (order.size - n_take) * cell_area
                else:
                    overlap += area
                    tag = (
                        "jumped"
                        if pair in jumped
                        else (
                            "rift_after_onset"
                            if pair in budget and t_new > onset[pair]
                            else ("rift_budget_spent" if pair in budget else "not_rift")
                        )
                    )
                    by_pair[f"{pair[0]}-{pair[1]}:{tag}"] = round(area / 1e6, 2)
        sel = np.flatnonzero(keep)
        pos, plate, cont, born = pos[sel], plate[sel], cont[sel], born[sel]
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
                kin, label, pos, plate, cont, omega, cfg.merge_contact_share, t_new, onset
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
                topo, _ = pt.reclose(topo, grid, spacing, side_info, omega, radius, relabel=relabel)
                label = pt.rasterize(topo, kin, spacing / 3.0)
                budget, onset = _rename_pairs(budget, onset, relabel)

        # 4c. boundary jump: a partial rift (older ocean still between the plates)
        # at its onset.  Before the rift opened the continent was whole on one
        # plate and the plate boundary ran around it; the smaller continental
        # block beside the rift goes to the plate across it.
        if grid is not None:
            due = [p for p, d in onset.items() if t_new >= d]
            transfers: list[tuple[np.ndarray, int]] = []
            for pair in due:
                block, to_plate = _jump_block(pos, plate, cont, pair, 1.2 * spacing)
                if block is None:
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
                topo, _ = pt.reclose(
                    topo, grid, spacing, side_info, omega, radius, transfers=transfers
                )
                label = pt.rasterize(topo, kin, spacing / 3.0)

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
                "rift_restored_km2": round(rift_deleted),
                "continental_overlap_km2": round(overlap),
                "continental_parcels_ratio": round(int(cont.sum()) / max(cont_parcels0, 1), 4),
                "overlap_by_pair_Mkm2": dict(sorted(by_pair.items(), key=lambda kv: -kv[1])[:6]),
            }
        )
        if any(abs(t - e) < 1e-9 for e in targets):
            snaps.append(snapshot(t, label))
    return snaps, log


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
    min_opening_cm_yr: float = 0.2,
) -> tuple[dict[tuple[int, int], float], dict[tuple[int, int], float]]:
    """Restoration budget (km²) and onset (Myr) of every continental rift.

    A continental rift is the set of mesh edges joining continental crust of two
    plates whose relative motion opens them forward in time.  Its stretched crust
    is at most ``cap_km`` wide on each side (stretching factors 2–3 over rift
    widths of about 100 km), so the budget is 2 · cap_km · length and the onset
    is at most 2 · cap_km / opening rate.  Where the terrain engine recorded the
    rift (``recorded``, extension / rate) the earlier of the two onsets is used,
    since the recorded extension is inflated (roadmap tech debt 33).
    """
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
        if rate <= min_opening_cm_yr:
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
) -> list[tuple[int, int, str, float]]:
    """Plate pairs to merge: (kept, merged, trigger, contact share).

    Only pairs that open forward in time (a rift, not a collision) merge.  A pair
    whose common boundary is at least ``share_needed`` continent against
    continent merges at its rift onset; one with ocean still between them merges
    once the share reaches ``share_needed`` (the ocean has closed going back).
    The larger plate is kept.
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
        trigger = "rift_onset" if (pa, pb) in onset else "ocean_closed"
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
