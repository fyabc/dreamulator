"""Stepwise backward plate history (geological timeline M2).

M1 (``paleo_kinematics``) rotates the present crust back to one time ``t`` in a
single step with fixed Euler poles.  That cannot carry state: crust that has to be
added behind a trench at 10 Myr must keep moving with its plate back to 50 Myr,
and plates change direction at reorganizations.  This module therefore walks
backward in steps of ``dt_myr`` over a set of crust parcels.  Each step:

1. **Reorganize** (at drawn times): every plate gets a new stage pole.  Candidate
   pole sets are drawn around the current ones under the speed cap and scored by
   two tectonic rules (Tetley et al. 2019; Müller et al. 2022): small lithospheric
   net rotation; the ridges in force keep opening in forward time (an ocean
   closes in the reverse order of its opening, so a reorganization may not turn
   a spreading ridge into a convergent boundary).  A hinged plate keeps its
   rotation about the hinge through a reorganization.
2. **Rotate** every parcel back by its plate's stage rotation.
3. **Drop** oceanic parcels born after the new time (younger than ``t``).
4. **Delete overlaps**: an oceanic parcel closer than ``overlap_factor`` cell
   spacings to a parcel of another plate is deleted when the other parcel is
   continental or older oceanic crust (it is crust that later became the gap a
   ridge filled, or that the overriding plate covers).  Continental parcels are
   never deleted.
5. **Fill gaps**: mesh cells with no parcel within ``gap_factor`` spacings get a
   new oceanic parcel.  Behind a trench this is crust consumed after ``t``.  The
   consumed side is the older ocean, so the filler joins the plate of the oldest
   of the nearest oceanic parcels, and is older than the nearest parcel of that
   plate by distance / spreading half-rate, the tracer age gradient of Karlsen et al.
   (2020) and Williams et al. (2021) collapsed to one step.  A gap whose nearest
   ocean is younger than ``ridge_gap_age_myr`` sits at a ridge whose flanks do
   not meet (the stage motion and the synthetic ages disagree, or a ridge slower
   than one cell spacing per step loses a whole parcel row); it is filled with
   zero-age crust that the next step drops again, so a ridge that stays open stays
   young instead of accumulating filler.  The area is reported as
   ``ridge_mismatch`` (a consistency diagnostic, not geology).  At every
   reorganization the synthetic crust is re-aged from the plate boundaries then
   in force (``synthesize_seafloor_age`` on the resampled mesh with the new
   poles): once the walk passes the oldest present crust no present ridge is
   left, and the boundaries that open forward in time at ``t`` are the ridges of
   that time, so the crust next to them is young.  Present-day crust keeps its
   own ages.
6. **Merge plates**: when two plates' continental parcels come into contact along
   more than ``merge_contact_km`` and over at least ``merge_contact_frac`` of the
   whole boundary between the two plates, while closing (backward in time; they
   separate forward in time, so this is a rift closing), they become one plate
   whose pole is refitted to both.  The fraction rule closes a basin like a
   zipper: merging on first contact would freeze the still-open part of the
   ocean between them inside one rigid plate.  At first contact (at least
   ``hinge_contact_km``) the smaller plate is hinged instead: its pole relative
   to the other plate moves to the contact (the rift tip, where conjugate plates
   rotate about a nearby pole), so
   the rest of the basin keeps closing without the contact overlapping.  At a
   merge the conjugate-margin misfit is recorded (Bullard et al. 1965 measured
   the same quantity at the 500-fathom isobath).

7. **Absorb enclaves**: with the terrain engine's rule
   (``tectonic_simulator._merge_plate_enclaves``), every piece of a plate other
   than its largest, smaller than ``max(50, 0.3 % of the cells)``, joins the
   surrounding plate.  Resampling and gap filling leave such enclaves; without
   this they accumulate into multiply-connected plates (numerical
   stabilization; the count is logged).

8. **Relax oceanic boundaries**: plate boundaries are kinematic objects, not
   material lines — ridges sit midway between their flanks and trenches are
   smooth arcs (Frank 1968; Macdonald et al. 1988; Schellart et al. 2007) — but
   here a boundary is wherever the parcels of two plates meet, so gap and
   overlap noise accumulates on it.  Each step, an oceanic boundary cell joins
   the plate that holds at least ``boundary_relax_majority`` of the cells within
   ``boundary_relax_km``; continental cells never change plate.  This is a
   curvature flow that removes embayments narrower than about twice the radius
   and the coastline-shaped boundaries a reassigned continental block brings
   (passive margins are intraplate).  Numerical stabilization, with the radius
   set by the observed smoothness scale of oceanic boundaries.

**Young rifts** (optional ``rifts``): continental crust of two plates that touch
across a boundary the terrain engine drew as a rift has only just started rifting,
so the continents are not yet apart.  Its onset time is the extension the
terrain engine recorded there (``cumulative_divergence_km``, which also sets the
rift-valley width) divided by the opening rate.  Before the onset is reached the
two sides overlap going back; the lower parcel of each overlapping pair is
deleted, which restores the narrower, unstretched crust (the rift valley
disappears).  At the onset stretching ends; when the rift makes up at least
``merge_contact_frac`` of the plates' common boundary it is where they
separated, and the two plates merge.

Continental elevation rolls back active orogens linearly to their build time;
oceanic elevation follows the plate-cooling increment, so at ``t = 0`` every cell
is exactly the present field.  Seeded RNG: same inputs and seed give the same
history.

Design: ``docs/design/proposals/geological-timeline.md`` §4.2–§4.4.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.sparse import csr_matrix
from scipy.spatial import cKDTree

from dreamulator.map.paleo_kinematics import (
    MIN_MOTION_FRAC,
    MIN_OPENING_FRAC,
    PlateKinematics,
    boundary_cells,
    boundary_speed_scale,
    fit_rotation,
    ocean_depth_m,
    ridge_half_rates,
    rotation_matrices,
    synthesize_seafloor_age,
)

_CM_PER_KM = 1.0e5
_KM_PER_MYR_PER_CM_YR = 10.0


@dataclass(frozen=True)
class HistoryConfig:
    """Parameters of the backward walk (all have a physical or numerical meaning).

    Attributes:
        dt_myr: step length; one step should move the fastest plate by about one
            cell spacing or less so gaps stay one or two cells wide.
        reorg_interval_myr: plate reorganizations are drawn uniformly in this range
            (Earth: about 10–40 Myr between global reorganizations).
        n_candidates: pole sets drawn per reorganization.
        axis_sigma_deg: spread of the pole-axis change at a reorganization.
        speed_sigma: log-normal spread of the angular-speed change.
        speed_max_cm_yr: hard cap on any plate's equatorial surface speed.
        gap_factor: a cell with no parcel within this many spacings is a gap.
        overlap_factor: parcels of two plates closer than this many spacings overlap.
        merge_contact_km: continental contact length that merges two plates.
        merge_contact_frac: and the share of the two plates' common boundary
            that the continental contact must cover.
        hinge_contact_km: continental contact length that hinges two plates.
        boundary_relax_km: disc radius of the oceanic boundary relaxation (0 = off).
        boundary_relax_majority: plate share in the disc needed to flip a cell.
        split_speed_cm_yr: relative speed across a suture after it is split.
        ridge_gap_age_myr: a gap next to ocean younger than this is a ridge gap.
        ridge_rule_weight: weight of the closing-ridge fraction in the score.
        seed: RNG seed.
    """

    dt_myr: float = 1.0
    reorg_interval_myr: tuple[float, float] = (10.0, 40.0)
    n_candidates: int = 32
    axis_sigma_deg: float = 20.0
    speed_sigma: float = 0.3
    speed_max_cm_yr: float = 15.0
    gap_factor: float = 1.0
    overlap_factor: float = 0.35
    merge_contact_km: float = 1000.0
    merge_contact_frac: float = 0.6
    hinge_contact_km: float = 300.0
    boundary_relax_km: float = 200.0
    boundary_relax_majority: float = 0.6
    split_speed_cm_yr: float = 5.0
    ridge_gap_age_myr: float = 2.0
    ridge_rule_weight: float = 2.0
    seed: int = 0


@dataclass(frozen=True)
class OceanDepth:
    """Plate-cooling depth law (positive metres): ridge + coeff · √age, capped."""

    ridge_depth_m: float
    subsidence_coeff: float
    max_depth_m: float

    def __call__(self, age_myr: np.ndarray) -> np.ndarray:
        return ocean_depth_m(age_myr, self.ridge_depth_m, self.subsidence_coeff, self.max_depth_m)


@dataclass(frozen=True)
class Orogens:
    """Present orogens to roll back.

    Attributes:
        relief_m: (N,) relief above the continental baseline built by the active
            convergence, 0 elsewhere.
        build_myr: (N,) time the relief took to build; going back ``t`` removes the
            fraction ``min(1, t / build_myr)``.
    """

    relief_m: np.ndarray
    build_myr: np.ndarray


@dataclass(frozen=True)
class Snapshot:
    """Mesh fields at one epoch (same mesh as the present).

    Attributes:
        t_myr: epoch, Myr before present.
        plate: (N,) plate index (after merges), into the present plate list.
        continental: (N,) continental crust.
        age_myr: (N,) seafloor age at ``t`` (NaN on continents and unconstrained ocean).
        elevation_m: (N,) elevation relative to the present datum.
        synthetic: (N,) crust added by gap filling (not present-day crust).
        ridge_mismatch: (N,) ridge-gap filler (see module docstring, step 5).
        enclosed_ocean: (N,) oceanic crust in a basin that touches no plate
            boundary (an ocean frozen inside a merged plate; see ``merge_contact_km``).
        omega: (P, 3) stage rotation vectors in force at ``t``.
    """

    t_myr: float
    plate: np.ndarray
    continental: np.ndarray
    age_myr: np.ndarray
    elevation_m: np.ndarray
    synthetic: np.ndarray
    ridge_mismatch: np.ndarray
    enclosed_ocean: np.ndarray
    omega: np.ndarray


@dataclass
class HistoryLog:
    """Events and per-step bookkeeping of a backward walk."""

    reorganizations: list[dict[str, float]] = field(default_factory=list)
    rift_onsets: list[dict[str, float | int | str | bool]] = field(default_factory=list)
    splits: list[dict[str, float | int | str]] = field(default_factory=list)
    hinges: list[dict[str, float | int]] = field(default_factory=list)
    merges: list[dict[str, float | int]] = field(default_factory=list)
    steps: list[dict[str, float | dict[str, int]]] = field(default_factory=list)


def net_rotation(omega: np.ndarray, plate: np.ndarray, xyz: np.ndarray, area: np.ndarray) -> float:
    """Lithospheric net rotation as a fraction of the mean plate angular speed.

    ω_net = (3 / 8π R²) ∫ x × (ω_p × x) dA (the rigid rotation that best fits the
    whole velocity field); a uniform rotation of every plate gives 1, a field with
    no net spin gives 0.
    """
    w = omega[plate]
    integrand = w - np.einsum("ij,ij->i", w, xyz)[:, None] * xyz
    total = area.sum()
    net = 1.5 * (integrand * area[:, None]).sum(axis=0) / total
    mean_speed = float((np.linalg.norm(w, axis=1) * area).sum() / total)
    return float(np.linalg.norm(net) / mean_speed) if mean_speed > 0 else 0.0


def _perturb(
    omega: np.ndarray, rng: np.random.Generator, cfg: HistoryConfig, radius_km: float
) -> np.ndarray:
    """One candidate pole set: tilt each axis and rescale each speed, then cap."""
    out = omega.copy()
    cap = cfg.speed_max_cm_yr / (radius_km * _CM_PER_KM)
    for p in range(omega.shape[0]):
        rate = float(np.linalg.norm(omega[p]))
        if rate == 0.0:
            continue
        axis = omega[p] / rate
        perp = np.cross(axis, rng.normal(size=3))
        perp /= max(float(np.linalg.norm(perp)), 1e-15)
        angle = np.radians(abs(rng.normal(0.0, cfg.axis_sigma_deg)))
        axis = np.cos(angle) * axis + np.sin(angle) * perp
        rate = min(rate * float(np.exp(rng.normal(0.0, cfg.speed_sigma))), cap)
        out[p] = axis * rate
    return out


def run_history(
    kin: PlateKinematics,
    age_myr: np.ndarray,
    elevation_m: np.ndarray,
    orogens: Orogens,
    depth: OceanDepth,
    epochs: list[float],
    cfg: HistoryConfig,
    rifts: dict[tuple[int, int], YoungRift] | None = None,
    sutures: list[Suture] | None = None,
) -> tuple[list[Snapshot], HistoryLog]:
    """Walk the plates back to ``max(epochs)``, snapshotting each epoch.

    ``rifts`` maps a plate pair (smaller index first) to its young rift
    (``rift_onsets``); ``sutures`` (``find_sutures``) are split going back at
    their collision ages; see the module docstring.

    ``kin`` should carry the reconstruction plate model (``reconstruction_plates``)
    and ``age_myr`` the synthetic present seafloor age.  The inputs are not
    modified.
    """
    rng = np.random.default_rng(cfg.seed)
    spacing = kin.spacing_km
    radius = kin.radius_km
    mesh_tree = cKDTree(kin.xyz)
    cell_area = float(np.median(kin.area_km2))
    edge_km = spacing / np.sqrt(3.0)  # hexagonal Voronoi edge length
    log = HistoryLog()

    # Parcel state; present parcels have reference time 0.
    pos = kin.xyz.copy()
    plate = kin.plate.copy()
    cont = kin.continental.copy()
    born = np.where(cont, np.nan, age_myr)  # epoch of formation (Myr before present)
    z_ref = elevation_m.astype(float).copy()
    t_ref = np.zeros(kin.n)
    relief = np.where(cont, orogens.relief_m, 0.0)
    build = np.maximum(orogens.build_myr, 1e-6)
    synthetic = np.zeros(kin.n, dtype=bool)
    origin = np.arange(kin.n)  # present cell of each parcel, -1 for synthetic crust
    pending = sorted(sutures or [], key=lambda s: s.age_myr)
    # room for the plates that suture splits will create
    omega = np.vstack([kin.omega, np.zeros((len(pending), 3))])
    next_plate = kin.omega.shape[0]

    ok_age = ~cont & np.isfinite(age_myr)
    # Age gradient of gap-filling crust: half the median surface speed of the
    # oceanic parcels, i.e. a typical spreading half-rate of the world.
    speeds = np.linalg.norm(np.cross(omega[kin.plate], kin.xyz), axis=1) * radius * _CM_PER_KM
    half_rate = 0.5 * float(np.median(speeds[ok_age])) if ok_age.any() else 2.5
    tracer_km_per_myr = max(half_rate, 0.5) * _KM_PER_MYR_PER_CM_YR
    default_age = float(np.nanmedian(age_myr[ok_age])) if ok_age.any() else 50.0

    def elevation_at(t: float) -> np.ndarray:
        z = z_ref.copy()
        aged = ~cont & np.isfinite(born)
        if aged.any():
            z[aged] += depth(born[aged] - t_ref[aged]) - depth(born[aged] - t)
        cm = cont & (relief > 0)
        z[cm] -= relief[cm] * np.minimum(1.0, t / build[cm])
        return z

    rows_m = np.repeat(np.arange(kin.n), np.diff(kin.nbr_ptr))
    cols_m = kin.nbr_idx
    disc = _disc_matrix(kin, cfg.boundary_relax_km) if cfg.boundary_relax_km > 0 else None

    def snapshot(t: float) -> Snapshot:
        _, src = cKDTree(pos).query(kin.xyz)
        z = elevation_at(t)
        age_t = np.where(~cont & np.isfinite(born), born - t, np.nan)
        cell_plate = _majority_plate(plate[src], rows_m, cols_m, kin.n)
        cell_ocean = ~cont[src]
        return Snapshot(
            t_myr=t,
            plate=cell_plate,
            continental=cont[src].copy(),
            age_myr=age_t[src],
            elevation_m=z[src],
            synthetic=synthetic[src].copy(),
            ridge_mismatch=(synthetic & ~cont & (born <= t + 1e-9))[src],
            enclosed_ocean=_enclosed_ocean(cell_plate, cell_ocean, rows_m, cols_m, kin.n),
            omega=omega.copy(),
        )

    if disc is not None:
        # the starting plates come from the reconstruction model, whose block
        # reassignment leaves coastline-shaped oceanic boundaries: relax them first
        identity = np.arange(kin.n)
        for _ in range(20):
            if not _relax_ocean_boundaries(
                plate, cont, identity, disc, kin, omega.shape[0], cfg.boundary_relax_majority
            ):
                break

    targets = sorted({float(e) for e in epochs})
    snaps: list[Snapshot] = []
    if targets and targets[0] <= 0.0:
        snaps.append(snapshot(0.0))
    t = 0.0
    t_end = targets[-1] if targets else 0.0
    next_reorg = float(rng.uniform(*cfg.reorg_interval_myr))
    # pair (smaller index first) -> (fixed plate, hinged plate)
    hinged: dict[tuple[int, int], tuple[int, int]] = {}
    active_rifts: dict[tuple[int, int], YoungRift] = dict(rifts or {})
    n_pl = omega.shape[0]

    def merge(p_a: int, p_b: int) -> None:
        """Plate p_b joins p_a; the pole is refitted to both; pair keys follow."""
        nonlocal active_rifts, hinged
        both = (plate == p_a) | (plate == p_b)
        vel = np.cross(omega[plate[both]], pos[both])
        plate[plate == p_b] = p_a
        omega[p_a] = fit_rotation(pos[both], vel, np.ones(int(both.sum())))
        omega[p_b] = 0.0

        def ren(k: tuple[int, int]) -> tuple[int, int]:
            x, y = (p_a if k[0] == p_b else k[0]), (p_a if k[1] == p_b else k[1])
            return (min(x, y), max(x, y))

        new_rifts: dict[tuple[int, int], YoungRift] = {}
        for k, v in active_rifts.items():
            kk = ren(k)
            if kk[0] == kk[1]:
                continue
            if kk not in new_rifts or v.onset_myr < new_rifts[kk].onset_myr:
                new_rifts[kk] = v
        active_rifts = new_rifts
        new_hinged: dict[tuple[int, int], tuple[int, int]] = {}
        for k, (fx, hg) in hinged.items():
            kk = ren(k)
            fx2, hg2 = (p_a if fx == p_b else fx), (p_a if hg == p_b else hg)
            if kk[0] != kk[1] and fx2 != hg2:
                new_hinged[kk] = (fx2, hg2)
        hinged = new_hinged

    cont_area0 = float(kin.area_km2[kin.continental].sum())

    while t < t_end - 1e-9:
        t_new = min(t + cfg.dt_myr, t_end)
        dt = t_new - t

        # 1. reorganization
        if t_new >= next_reorg:
            live = np.unique(plate)
            area_w = np.full(len(pos), cell_area)
            ridge_x, ridge_n, ridge_a, ridge_b = _live_ridges(kin, pos, plate, cont, omega)
            best, best_score = omega, np.inf
            best_parts = (0.0, 0.0)
            for _ in range(cfg.n_candidates):
                cand = _keep_hinges(_perturb(omega, rng, cfg, radius), omega, hinged)
                nr = net_rotation(cand, plate, pos, area_w)
                closing = _closing_fraction(cand, ridge_x, ridge_n, ridge_a, ridge_b)
                score = nr + cfg.ridge_rule_weight * closing
                if score < best_score:
                    best, best_score, best_parts = cand, score, (nr, closing)
            mask = np.zeros(omega.shape[0], dtype=bool)
            mask[live] = True
            omega = np.where(mask[:, None], best, omega)
            # re-age the synthetic crust from the boundaries now in force
            _, cell_src = cKDTree(pos).query(kin.xyz)
            kin_t = PlateKinematics(
                xyz=kin.xyz,
                nbr_ptr=kin.nbr_ptr,
                nbr_idx=kin.nbr_idx,
                plate=plate[cell_src],
                omega=omega,
                continental=cont[cell_src],
                area_km2=kin.area_km2,
                radius_km=radius,
            )
            half_t, off_t = ridge_half_rates(kin_t, boundary_cells(kin_t))
            age_t, _ = synthesize_seafloor_age(kin_t, half_t, off_t)
            _, parcel_cell = mesh_tree.query(pos)
            new_age = age_t[parcel_cell]
            redo = synthetic & ~cont & np.isfinite(new_age)
            born[redo] = t_new + new_age[redo]
            t_ref[redo] = t_new
            z_ref[redo] = -depth(new_age[redo])
            log.reorganizations.append(
                {
                    "t_myr": t_new,
                    "net_rotation": round(best_parts[0], 4),
                    "closing_ridge_frac": round(best_parts[1], 4),
                    "ridge_edges": len(ridge_x),
                    "reaged_parcels": int(redo.sum()),
                }
            )
            next_reorg += float(rng.uniform(*cfg.reorg_interval_myr))

        # 2. rotate back
        rot = rotation_matrices(omega, -dt * 1.0e6)
        pos = np.einsum("nij,nj->ni", rot[plate], pos)
        pos /= np.linalg.norm(pos, axis=1, keepdims=True)

        # 2a. sutures whose collision age is passed: before it the two sides were
        # separate plates (going back, a collision un-happens)
        while pending and pending[0].age_myr <= t_new:
            sut = pending.pop(0)
            piece = np.zeros(kin.n, dtype=bool)
            piece[sut.piece_cells] = True
            on_piece = cont & (origin >= 0) & piece[np.maximum(origin, 0)]
            if not on_piece.any():
                continue
            parent = int(np.bincount(plate[on_piece]).argmax())
            rest = cont & (plate == parent) & ~on_piece
            if not rest.any():
                continue
            new_id = next_plate
            next_plate += 1
            # oceanic parcels of the parent go with whichever continental side is nearer
            ocean_parent = np.flatnonzero(~cont & (plate == parent))
            if ocean_parent.size:
                d_piece, _ = cKDTree(pos[on_piece]).query(pos[ocean_parent])
                d_rest, _ = cKDTree(pos[rest]).query(pos[ocean_parent])
                plate[ocean_parent[d_piece < d_rest]] = new_id
            plate[on_piece] = new_id
            omega[new_id] = _suture_pole(omega[parent], pos[on_piece], pos[rest], rng, cfg, radius)
            log.splits.append(
                {
                    "t_myr": t_new,
                    "parent": parent,
                    "new_plate": new_id,
                    "age_myr": round(sut.age_myr, 1),
                    "age_source": sut.age_source,
                    "piece_area_frac": round(sut.piece_area_frac, 4),
                }
            )

        # 2b. rifts whose onset is passed: stretching ends; a rift that makes up
        # most of the plates' common boundary is where they separated, so before
        # the onset they were one plate
        for pair, rift in sorted(active_rifts.items(), key=lambda kv: kv[1].onset_myr):
            if rift.onset_myr > t_new or pair not in active_rifts:
                continue
            merged = rift.share >= cfg.merge_contact_frac
            if merged:
                p_a, p_b = pair
                if (plate == p_b).sum() > (plate == p_a).sum():
                    p_a, p_b = p_b, p_a
                merge(p_a, p_b)
            else:
                del active_rifts[pair]
            log.rift_onsets.append(
                {
                    "t_myr": t_new,
                    "plates": f"{pair[0]}-{pair[1]}",
                    "onset_myr": round(rift.onset_myr, 1),
                    "share": round(rift.share, 2),
                    "merged": merged,
                }
            )

        # 3. drop crust younger than t_new
        keep = cont | ~np.isfinite(born) | (born >= t_new)
        n_dropped = int((~keep).sum())

        # 4. overlaps: delete oceanic parcels covered by another plate's crust
        tree = cKDTree(pos)
        chord = 2.0 * np.sin(cfg.overlap_factor * spacing / (2.0 * radius))
        pairs = tree.query_pairs(chord, output_type="ndarray")
        cont_overlap_pairs: dict[str, int] = {}
        if len(pairs):
            a, b = pairs[:, 0], pairs[:, 1]
            cross = plate[a] != plate[b]
            a, b = a[cross], b[cross]
            age_a = np.where(np.isfinite(born[a]), born[a], np.inf)
            age_b = np.where(np.isfinite(born[b]), born[b], np.inf)
            # delete a when it is oceanic and b is continental or older ocean
            del_a = ~cont[a] & (cont[b] | (age_b > age_a))
            del_b = ~cont[b] & ~del_a & (cont[a] | (age_a >= age_b))
            cc = cont[a] & cont[b]
            if cc.any():
                ka = np.minimum(plate[a[cc]], plate[b[cc]])
                kb = np.maximum(plate[a[cc]], plate[b[cc]])
                keys_cc, counts_cc = np.unique(ka * n_pl + kb, return_counts=True)
                for kk, cnt in sorted(zip(keys_cc, counts_cc, strict=True), key=lambda z: -z[1])[
                    :3
                ]:
                    cont_overlap_pairs[f"{kk // n_pl}-{kk % n_pl}"] = int(cnt)
            if active_rifts:
                # stretched rift crust: the lower parcel of a continental pair goes
                keys = np.minimum(plate[a], plate[b]) * n_pl + np.maximum(plate[a], plate[b])
                rift_keys = np.array([x * n_pl + y for x, y in active_rifts])
                in_rift = cont[a] & cont[b] & np.isin(keys, rift_keys)
                lower_a = z_ref[a] <= z_ref[b]
                del_a |= in_rift & lower_a
                del_b |= in_rift & ~lower_a
            keep[a[del_a]] = False
            keep[b[del_b]] = False
        n_overlap_deleted = int(len(pos) - keep.sum() - n_dropped)
        sel = np.flatnonzero(keep)
        pos, plate, cont, born = pos[sel], plate[sel], cont[sel], born[sel]
        z_ref, t_ref, relief, build, synthetic, origin = (
            z_ref[sel],
            t_ref[sel],
            relief[sel],
            build[sel],
            synthetic[sel],
            origin[sel],
        )

        # 5. fill gaps with older ocean
        tree = cKDTree(pos)
        dist, _ = tree.query(kin.xyz)
        dist_km = 2.0 * radius * np.arcsin(np.clip(dist / 2.0, 0.0, 1.0))
        gaps = np.flatnonzero(dist_km > cfg.gap_factor * spacing)
        n_ridge_gap = 0
        if gaps.size:
            new_plate, new_age, ridge_gap = _gap_crust(
                kin.xyz[gaps],
                pos,
                plate,
                cont,
                born,
                t_new,
                n_pl,
                radius,
                default_age,
                tracer_km_per_myr,
                cfg.ridge_gap_age_myr,
            )
            new_age = np.where(ridge_gap, 0.0, new_age)
            new_born = t_new + new_age
            n_ridge_gap = int(ridge_gap.sum())
            pos = np.vstack([pos, kin.xyz[gaps]])
            plate = np.concatenate([plate, new_plate])
            cont = np.concatenate([cont, np.zeros(gaps.size, dtype=bool)])
            born = np.concatenate([born, new_born])
            z_ref = np.concatenate([z_ref, -depth(new_age)])
            t_ref = np.concatenate([t_ref, np.full(gaps.size, t_new)])
            relief = np.concatenate([relief, np.zeros(gaps.size)])
            build = np.concatenate([build, np.ones(gaps.size)])
            synthetic = np.concatenate([synthetic, np.ones(gaps.size, dtype=bool)])
            origin = np.concatenate([origin, np.full(gaps.size, -1)])

        # 7 (before merging). clean plate fragments on the resampled mesh
        _, src_all = cKDTree(pos).query(kin.xyz)
        n_relabel = _clean_fragments(pos, plate, plate[src_all], mesh_tree, kin)
        n_relaxed = 0
        if disc is not None:
            n_relaxed = _relax_ocean_boundaries(
                plate, cont, src_all, disc, kin, n_pl, cfg.boundary_relax_majority
            )

        # 6. merges: continental contact between two plates that close backward
        c_plate = plate[src_all]
        c_cont = cont[src_all]
        rows = np.repeat(np.arange(kin.n), np.diff(kin.nbr_ptr))
        cols = kin.nbr_idx
        cross_all = (rows < cols) & (c_plate[rows] != c_plate[cols])
        n_pl = omega.shape[0]
        pair_all = (
            np.minimum(c_plate[rows], c_plate[cols]) * n_pl
            + np.maximum(c_plate[rows], c_plate[cols])
        )[cross_all]
        boundary_len = np.bincount(pair_all, minlength=n_pl * n_pl) * edge_km
        touch = cross_all & c_cont[rows] & c_cont[cols]
        if touch.any():
            i, j = rows[touch], cols[touch]
            pa, pb = np.minimum(c_plate[i], c_plate[j]), np.maximum(c_plate[i], c_plate[j])
            x = kin.xyz[i] + kin.xyz[j]
            x /= np.linalg.norm(x, axis=1, keepdims=True)
            nrm = kin.xyz[i] - kin.xyz[j]
            nrm -= np.einsum("ij,ij->i", nrm, x)[:, None] * x
            nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-15)
            # forward-time opening rate of i's plate relative to j's plate
            v = np.cross(omega[c_plate[i]] - omega[c_plate[j]], x) * radius * _CM_PER_KM
            opening = np.einsum("ij,ij->i", v, nrm)
            for key in np.unique(pa * omega.shape[0] + pb):
                m = (pa * omega.shape[0] + pb) == key
                contact = float(m.sum() * edge_km)
                share = contact / max(float(boundary_len[key]), 1e-9)
                if contact < cfg.hinge_contact_km or float(np.median(opening[m])) <= 0.0:
                    continue
                p_a, p_b = int(key // omega.shape[0]), int(key % omega.shape[0])
                if (p_a, p_b) in active_rifts:
                    continue  # young rifts merge at their onset
                if (plate == p_b).sum() > (plate == p_a).sum():
                    p_a, p_b = p_b, p_a
                if share < cfg.merge_contact_frac or contact < cfg.merge_contact_km:
                    if (min(p_a, p_b), max(p_a, p_b)) in hinged:
                        continue
                    hinge = x[m].mean(axis=0)
                    hinge /= max(float(np.linalg.norm(hinge)), 1e-15)
                    omega[p_b] = _hinged_pole(
                        omega, pos, plate, cont, p_a, p_b, hinge, dt, cfg.speed_max_cm_yr, radius
                    )
                    hinged[(min(p_a, p_b), max(p_a, p_b))] = (p_a, p_b)
                    log.hinges.append(
                        {
                            "t_myr": t_new,
                            "fixed": p_a,
                            "hinged": p_b,
                            "contact_km": round(contact),
                            "contact_share": round(share, 3),
                        }
                    )
                    break
                misfit = _margin_misfit(pos, plate, cont, p_a, p_b, radius, spacing)
                merge(p_a, p_b)
                log.merges.append(
                    {
                        "t_myr": t_new,
                        "kept": p_a,
                        "merged": p_b,
                        "contact_km": round(contact),
                        "contact_share": round(share, 3),
                        "margin_misfit_km": round(misfit, 1),
                    }
                )
                break  # one merge per step; plate labels changed

        t = t_new
        log.steps.append(
            {
                "t_myr": t,
                "parcels": len(pos),
                "dropped": n_dropped,
                "overlap_deleted": n_overlap_deleted,
                "gaps_filled": int(gaps.size),
                "ridge_mismatch_filled": n_ridge_gap,
                "fragment_parcels_relabeled": n_relabel,
                "boundary_cells_relaxed": n_relaxed,
                "continental_cells_ratio": round(
                    float(kin.area_km2[cont[src_all]].sum()) / cont_area0 if cont_area0 else 0.0, 4
                ),
                "continental_overlap_pairs": cont_overlap_pairs,
                "continental_area_ratio": round(
                    float(cont.sum()) * cell_area / cont_area0 if cont_area0 else 0.0, 4
                ),
            }
        )
        if any(abs(t - e) < 1e-9 for e in targets):
            snaps.append(snapshot(t))
    return snaps, log


@dataclass(frozen=True)
class YoungRift:
    """A rift between two plates' continents that has only just started.

    Attributes:
        onset_myr: rift onset (recorded extension / opening rate, median).
        share: rift length / length of the plates' whole common boundary.
        length_km: rift length.
    """

    onset_myr: float
    share: float
    length_km: float


def rift_onsets(
    kin: PlateKinematics,
    divergent: np.ndarray,
    divergence_km: np.ndarray,
    min_opening_frac: float = MIN_OPENING_FRAC,
) -> dict[tuple[int, int], YoungRift]:
    """Young rifts between plate pairs, from the terrain engine's rift record.

    A rift edge joins continental cells of two plates that the boundary detector
    flagged divergent and where the terrain engine recorded extension (it drew a
    rift valley there).  The onset is the median, over edges that open faster
    than ``min_opening_frac`` of the boundary speed scale, of the recorded
    extension divided by the opening rate.
    """
    rows = np.repeat(np.arange(kin.n), np.diff(kin.nbr_ptr))
    cols = kin.nbr_idx
    cross = (rows < cols) & (kin.plate[rows] != kin.plate[cols])
    pa_all = np.minimum(kin.plate[rows], kin.plate[cols])
    pb_all = np.maximum(kin.plate[rows], kin.plate[cols])
    ext_all = np.maximum(divergence_km[rows], divergence_km[cols])
    m = cross & kin.continental[rows] & kin.continental[cols]
    m &= divergent[rows] & divergent[cols] & (ext_all > 0)
    i, j = rows[m], cols[m]
    x = kin.xyz[i] + kin.xyz[j]
    x /= np.linalg.norm(x, axis=1, keepdims=True)
    n = kin.xyz[i] - kin.xyz[j]
    n -= np.einsum("ij,ij->i", n, x)[:, None] * x
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-15)
    v = np.cross(kin.omega[kin.plate[i]] - kin.omega[kin.plate[j]], x) * kin.radius_km * _CM_PER_KM
    opening = np.einsum("ij,ij->i", v, n)
    ok = opening > min_opening_frac * boundary_speed_scale(kin)
    onset = ext_all[m] / np.maximum(opening, 1e-9) / _KM_PER_MYR_PER_CM_YR
    pa, pb = pa_all[m], pb_all[m]
    edge_km = kin.spacing_km / np.sqrt(3.0)
    out: dict[tuple[int, int], YoungRift] = {}
    for a, b in sorted({(int(a), int(b)) for a, b in zip(pa, pb, strict=True)}):
        sel = (pa == a) & (pb == b)
        if not (sel & ok).any():
            continue
        total = int((cross & (pa_all == a) & (pb_all == b)).sum())
        out[(a, b)] = YoungRift(
            onset_myr=float(np.median(onset[sel & ok])),
            share=float(sel.sum() / max(total, 1)),
            length_km=float(sel.sum() * edge_km),
        )
    return out


def _gap_crust(
    gap_xyz: np.ndarray,
    pos: np.ndarray,
    plate: np.ndarray,
    cont: np.ndarray,
    born: np.ndarray,
    t: float,
    n_plates: int,
    radius_km: float,
    default_age: float,
    tracer_km_per_myr: float,
    ridge_gap_age_myr: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Plate, age and ridge-gap flag of the crust filling each gap cell.

    Each gap lies between its nearest plate and the nearest different plate.  The
    consumed plate of a plate pair is decided once for the whole pair: the one
    with the older ocean next to the gaps (continental crust is never consumed).
    Deciding per cell would alternate along a trench and speckle the plates.
    The filler's age is the age of the nearest oceanic parcel of the consumed
    plate plus distance / spreading half-rate.
    """
    k = min(12, len(pos))
    dist, idx = cKDTree(pos).query(gap_xyz, k=k)
    dist, idx = dist.reshape(len(gap_xyz), k), idx.reshape(len(gap_xyz), k)
    rows = np.arange(len(gap_xyz))
    pk = plate[idx]
    p1 = pk[:, 0]
    differs = pk != p1[:, None]
    p2 = np.where(differs.any(axis=1), pk[rows, np.argmax(differs, axis=1)], p1)
    ocean_k = ~cont[idx]
    age_k = np.where(ocean_k, np.where(np.isfinite(born[idx]), born[idx] - t, default_age), np.nan)

    pair = np.minimum(p1, p2) * n_plates + np.maximum(p1, p2)
    consumed = np.empty(len(gap_xyz), dtype=plate.dtype)
    for key in np.unique(pair):
        sel = pair == key
        a, b = int(key // n_plates), int(key % n_plates)
        mean_age = []
        for q in (a, b):
            vals = age_k[sel][pk[sel] == q]
            vals = vals[np.isfinite(vals)]
            mean_age.append(float(vals.mean()) if vals.size else -np.inf)
        consumed[sel] = a if mean_age[0] >= mean_age[1] else b
    on_plate = (pk == consumed[:, None]) & ocean_k
    has = on_plate.any(axis=1)
    pick = np.argmax(on_plate, axis=1)
    src_age = np.where(has, age_k[rows, pick], default_age)
    src_km = 2.0 * radius_km * np.arcsin(np.clip(dist[rows, pick] / 2.0, 0.0, 1.0))
    age = src_age + np.where(has, src_km, 0.0) / tracer_km_per_myr
    young = np.where(np.isfinite(age_k), age_k, np.inf).min(axis=1) < ridge_gap_age_myr
    ridge_gap = young & (
        np.nanmax(np.where(np.isfinite(age_k), age_k, -np.inf), axis=1) < ridge_gap_age_myr
    )
    return consumed, age, ridge_gap


def _disc_matrix(kin: PlateKinematics, radius_km: float) -> csr_matrix:
    """Sparse (N, N) area weights of the cells within ``radius_km`` of each cell."""
    chord = 2.0 * np.sin(radius_km / (2.0 * kin.radius_km))
    nbrs = cKDTree(kin.xyz).query_ball_point(kin.xyz, chord)
    lens = np.fromiter((len(x) for x in nbrs), dtype=np.int64, count=kin.n)
    rows = np.repeat(np.arange(kin.n), lens)
    cols = np.fromiter((j for x in nbrs for j in x), dtype=np.int64, count=int(lens.sum()))
    return csr_matrix((kin.area_km2[cols], (rows, cols)), shape=(kin.n, kin.n))


def _relax_ocean_boundaries(
    plate: np.ndarray,
    cont: np.ndarray,
    src: np.ndarray,
    disc: csr_matrix,
    kin: PlateKinematics,
    n_plates: int,
    majority: float,
) -> int:
    """One pass of the oceanic boundary relaxation (in place); returns flipped cells.

    ``src`` maps each mesh cell to its parcel.  An oceanic cell on a plate
    boundary takes the plate holding at least ``majority`` of the disc area
    around it; the parcel behind the cell follows.
    """
    cell_plate = plate[src]
    cell_ocean = ~cont[src]
    rows = np.repeat(np.arange(kin.n), np.diff(kin.nbr_ptr))
    on_boundary = np.zeros(kin.n, dtype=bool)
    on_boundary[rows[cell_plate[rows] != cell_plate[kin.nbr_idx]]] = True
    cand = np.flatnonzero(on_boundary & cell_ocean)
    if cand.size == 0:
        return 0
    onehot = csr_matrix((np.ones(kin.n), (np.arange(kin.n), cell_plate)), shape=(kin.n, n_plates))
    share = (disc[cand] @ onehot).toarray()
    share /= np.maximum(share.sum(axis=1, keepdims=True), 1e-12)
    best = np.argmax(share, axis=1)
    flip = (best != cell_plate[cand]) & (share[np.arange(cand.size), best] >= majority)
    cells = cand[flip]
    plate[src[cells]] = best[flip]
    return int(cells.size)


def _clean_fragments(
    pos: np.ndarray,
    plate: np.ndarray,
    cell_plate: np.ndarray,
    mesh_tree: cKDTree,
    kin: PlateKinematics,
) -> int:
    """Absorb plate enclaves into the surrounding plate (in place).

    Same rule as the terrain engine's ``tectonic_simulator._merge_plate_enclaves``:
    on the resampled mesh each plate keeps its largest connected piece; every
    other piece smaller than ``max(50, 0.3 % of the cells)`` (about the share of
    the smallest recognised Earth plate) takes the most common plate among the
    cells bordering it.  A plate that is a single piece is never touched, so
    microplates survive.  Returns the number of parcels relabeled.
    """
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import connected_components

    rows = np.repeat(np.arange(kin.n), np.diff(kin.nbr_ptr))
    cols = kin.nbr_idx
    same = cell_plate[rows] == cell_plate[cols]
    g = csr_matrix((np.ones(int(same.sum())), (rows[same], cols[same])), shape=(kin.n, kin.n))
    _, label = connected_components(g, directed=False)
    size = np.bincount(label)
    comp_plate = np.zeros(size.size, dtype=cell_plate.dtype)
    comp_plate[label] = cell_plate
    # largest piece of each plate
    order = np.lexsort((-size, comp_plate))  # by plate, largest piece first
    first = np.ones(order.size, dtype=bool)
    first[1:] = comp_plate[order[1:]] != comp_plate[order[:-1]]
    largest = np.zeros(size.size, dtype=bool)
    largest[order[first]] = True
    min_keep = max(50, int(0.003 * kin.n))
    enclave = ~largest & (size < min_keep)
    if not enclave.any():
        return 0
    border = ~same & enclave[label[rows]]
    b_lab, b_nb = label[rows[border]], cell_plate[cols[border]]
    target = np.full(size.size, -1)
    for comp in np.unique(b_lab):
        vals, counts = np.unique(b_nb[b_lab == comp], return_counts=True)
        target[comp] = vals[np.argmax(counts)]
    _, parcel_cell = mesh_tree.query(pos)
    new = target[label[parcel_cell]]
    move = new >= 0
    plate[move] = new[move]
    return int(move.sum())


@dataclass(frozen=True)
class Suture:
    """A suture inside a continental block, split going back at its collision age.

    Attributes:
        age_myr: collision age (the two sides were separate plates before it).
        piece_cells: present cells of the side that becomes a new plate.
        piece_area_frac: that side's share of the planet's area.
        age_source: ``"convergence"`` (accumulated shortening / rate at an active
            orogen) or ``"relief_decay"`` (residual relief of an inactive orogen).
    """

    age_myr: float
    piece_cells: np.ndarray
    piece_area_frac: float
    age_source: str


def find_sutures(
    kin: PlateKinematics,
    block: np.ndarray,
    present_plate: np.ndarray,
    elevation_m: np.ndarray,
    orogens: Orogens,
    *,
    max_age_myr: float = 400.0,
) -> list[Suture]:
    """Sutures inside the reconstruction model's rigid continental blocks.

    A block glues together continental crust that the terrain engine put on
    different plates; the engine boundaries running through the block are read
    as sutures, where the parts once collided (geological-timeline §4.0, §4.4).
    Cutting the block along them gives its sub-blocks; sub-blocks of at least
    ``max(50, 0.3 %)`` cells (the enclave rule's size) are kept, smaller pieces
    join the nearest kept one.  The largest sub-block keeps the block's plate;
    every other one is split off going back at its collision age, estimated from
    its seam (cells within two spacings of the rest of the block):

    * at an active orogen (``orogens.relief_m > 0`` on at least half the seam):
      the orogen build time, accumulated shortening / convergence rate;
    * otherwise from relief decay of the seam's mountains (90th percentile of
      relief above the continental baseline), the inverse of the law the terrain
      engine builds old orogens with (``paleo_orogens.collision_age_from_crest``,
      R_active the median relief of the active orogens); a seam with little relief
      gets an old age, capped at ``max_age_myr``.
    """
    from scipy.sparse.csgraph import connected_components

    from dreamulator.map.paleo_orogens import collision_age_from_crest

    rows = np.repeat(np.arange(kin.n), np.diff(kin.nbr_ptr))
    cols = kin.nbr_idx
    cont = kin.continental
    baseline = float(np.median(elevation_m[cont & (orogens.relief_m <= 0)]))
    relief = elevation_m - baseline
    active = orogens.relief_m > 0
    r_active = float(np.median(relief[active])) if active.any() else 2000.0
    min_cells = max(50, int(0.003 * kin.n))
    total_area = float(kin.area_km2.sum())
    reach = 2.0 * kin.spacing_km
    out: list[Suture] = []
    for b in np.unique(block[block >= 0]):
        in_b = block == b
        keep = in_b[rows] & in_b[cols] & (present_plate[rows] == present_plate[cols])
        g = csr_matrix((np.ones(int(keep.sum())), (rows[keep], cols[keep])), shape=(kin.n, kin.n))
        _, lab = connected_components(g, directed=False)
        sizes = np.bincount(lab[in_b], minlength=lab.max() + 1)
        big = np.flatnonzero(sizes >= min_cells)
        if big.size < 2:
            continue
        big_cells = np.flatnonzero(in_b & np.isin(lab, big))
        _, near = cKDTree(kin.xyz[big_cells]).query(kin.xyz[in_b])
        piece_of = np.full(kin.n, -1)
        piece_of[np.flatnonzero(in_b)] = lab[big_cells[near]]
        areas = {int(p): float(kin.area_km2[piece_of == p].sum()) for p in big}
        main = max(areas, key=lambda p: areas[p])
        for p in big:
            if int(p) == main:
                continue
            cells_p = np.flatnonzero(piece_of == p)
            others = np.flatnonzero(in_b & (piece_of != p))
            d, _ = cKDTree(kin.xyz[others]).query(kin.xyz[cells_p])
            seam = cells_p[d * kin.radius_km < reach]
            if seam.size == 0:
                continue
            act = seam[active[seam]]
            if act.size >= max(1, seam.size // 2):
                age = float(np.median(orogens.build_myr[act]))
                source = "convergence"
            else:
                r = max(float(np.percentile(relief[seam], 90)), 1.0)
                age = collision_age_from_crest(r, r_active, max_age_myr)
                source = "relief_decay"
            out.append(
                Suture(
                    age_myr=float(min(age, max_age_myr)),
                    piece_cells=cells_p,
                    piece_area_frac=float(kin.area_km2[cells_p].sum() / total_area),
                    age_source=source,
                )
            )
    return out


def _suture_pole(
    omega_parent: np.ndarray,
    piece: np.ndarray,
    rest: np.ndarray,
    rng: np.random.Generator,
    cfg: HistoryConfig,
    radius_km: float,
) -> np.ndarray:
    """Pole of a plate split off along a suture.

    Relative to its parent the new plate rotates about the axis n × c, where c is
    the suture midpoint and n the unit direction from the parent side to the new
    side at c; then the forward relative velocity at c is −n (the sides converge
    forward, so they separate going back).  The rate gives ``split_speed_cm_yr``
    at the suture; the axis is tilted by up to ``axis_sigma_deg``.
    """
    _, i_rest = cKDTree(rest).query(piece)
    d = np.linalg.norm(piece - rest[i_rest], axis=1)
    k = np.argsort(d)[: max(1, len(d) // 20)]  # the seam: closest 5 % of pairs
    c = (piece[k] + rest[i_rest[k]]).mean(axis=0)
    c /= np.linalg.norm(c)
    n = piece.mean(axis=0) - rest.mean(axis=0)
    n -= (n @ c) * c
    n /= max(float(np.linalg.norm(n)), 1e-15)
    axis = np.cross(n, c)
    perp = np.cross(axis, rng.normal(size=3))
    perp /= max(float(np.linalg.norm(perp)), 1e-15)
    tilt = np.radians(abs(rng.normal(0.0, cfg.axis_sigma_deg)))
    axis = np.cos(tilt) * axis + np.sin(tilt) * perp
    rate = cfg.split_speed_cm_yr / (radius_km * _CM_PER_KM)
    new = omega_parent + rate * axis
    cap = cfg.speed_max_cm_yr / (radius_km * _CM_PER_KM)
    norm = float(np.linalg.norm(new))
    result: np.ndarray = new * (cap / norm) if norm > cap else new
    return result


def _keep_hinges(
    cand: np.ndarray, omega: np.ndarray, hinged: dict[tuple[int, int], tuple[int, int]]
) -> np.ndarray:
    """A hinged plate keeps its rotation about the hinge relative to its partner."""
    for fixed, hinge in hinged.values():
        cand[hinge] = cand[fixed] + (omega[hinge] - omega[fixed])
    return cand


def _closing_fraction(
    omega: np.ndarray, x: np.ndarray, n: np.ndarray, a: np.ndarray, b: np.ndarray
) -> float:
    """Share of ridge edges that the rotation set ``omega`` would make converge."""
    if not len(x):
        return 0.0
    v = np.cross(omega[a] - omega[b], x)
    return float(np.mean(np.einsum("ij,ij->i", v, n) < 0.0))


def _hinged_pole(
    omega: np.ndarray,
    pos: np.ndarray,
    plate: np.ndarray,
    cont: np.ndarray,
    p_a: int,
    p_b: int,
    hinge: np.ndarray,
    dt: float,
    speed_max_cm_yr: float,
    radius_km: float,
) -> np.ndarray:
    """New pole of plate ``p_b`` rotating about ``hinge`` relative to ``p_a``.

    The relative rotation keeps its rate, capped so that ``p_b`` stays under the
    speed limit; the sense is the one that brings the two continental margins
    closer in the next backward step.
    """
    rel_rate = float(np.linalg.norm(omega[p_b] - omega[p_a]))
    a_pts = pos[(plate == p_a) & cont]
    b_pts = pos[(plate == p_b) & cont]
    if rel_rate == 0.0 or a_pts.size == 0 or b_pts.size == 0:
        same: np.ndarray = omega[p_b].copy()
        return same
    a_tree = cKDTree(a_pts)
    _, near = a_tree.query(b_pts)
    # the facing margin: B parcels nearest to A (closest 10 %)
    d0 = np.linalg.norm(b_pts - a_pts[near], axis=1)
    margin = b_pts[d0 <= np.quantile(d0, 0.1)]
    rot_a = rotation_matrices(omega[p_a][None, :], -dt * 1.0e6)[0]
    a_moved = cKDTree(a_pts @ rot_a.T)
    best: np.ndarray = omega[p_b].copy()
    best_d = np.inf
    cap = speed_max_cm_yr / (radius_km * _CM_PER_KM)
    for sign in (1.0, -1.0):
        cand = omega[p_a] + sign * rel_rate * hinge
        rate = float(np.linalg.norm(cand))
        if rate > cap:
            cand *= cap / rate
        rot_b = rotation_matrices(cand[None, :], -dt * 1.0e6)[0]
        d, _ = a_moved.query(margin @ rot_b.T)
        if float(d.mean()) < best_d:
            best, best_d = cand, float(d.mean())
    return best


def _majority_plate(plate: np.ndarray, rows: np.ndarray, cols: np.ndarray, n: int) -> np.ndarray:
    """One majority pass over cell + neighbours: removes single-cell resampling speckle.

    Parcels of two plates interleave along a boundary after resampling; a cell
    whose neighbours mostly belong to another plate takes that plate.  Ties keep
    the cell's own label.
    """
    out = plate.copy()
    nb_plate = plate[cols]
    same = nb_plate == plate[rows]
    own_votes = np.bincount(rows, weights=same, minlength=n) + 1.0  # the cell itself
    deg = np.bincount(rows, minlength=n).astype(float)
    weak = own_votes <= 0.5 * (deg + 1.0)
    for i in np.flatnonzero(weak):
        lo, hi = np.searchsorted(rows, i), np.searchsorted(rows, i, side="right")
        nb = nb_plate[lo:hi]
        vals, counts = np.unique(nb, return_counts=True)
        best = int(np.argmax(counts))
        if counts[best] > own_votes[i]:
            out[i] = vals[best]
    return out


def _enclosed_ocean(
    plate: np.ndarray, ocean: np.ndarray, rows: np.ndarray, cols: np.ndarray, n: int
) -> np.ndarray:
    """Oceanic cells in same-plate ocean basins that touch no plate boundary."""
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import connected_components

    same = (plate[rows] == plate[cols]) & ocean[rows] & ocean[cols]
    g = csr_matrix((np.ones(int(same.sum())), (rows[same], cols[same])), shape=(n, n))
    _, label = connected_components(g, directed=False)
    on_boundary = np.zeros(n, dtype=bool)
    on_boundary[rows[plate[rows] != plate[cols]]] = True
    touching = np.zeros(int(label.max()) + 1, dtype=bool)
    touching[label[on_boundary & ocean]] = True
    enclosed: np.ndarray = ocean & ~touching[label]
    return enclosed


def _live_ridges(
    kin: PlateKinematics,
    pos: np.ndarray,
    plate: np.ndarray,
    cont: np.ndarray,
    omega: np.ndarray,
    min_opening_cm_yr: float = 0.5,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Ridge edges in force: oceanic plate boundaries that open forward in time.

    The parcels are resampled on the mesh; a ridge edge joins two oceanic mesh
    neighbours on different plates whose forward opening rate under ``omega``
    exceeds ``min_opening_cm_yr``.  Returns the edge midpoints, the boundary
    normals (pointing from the second plate to the first), and the two plate
    indices, so that a candidate's forward opening rate is ((ω_a − ω_b) × x) · n.
    """
    _, src = cKDTree(pos).query(kin.xyz)
    p = plate[src]
    ocean = ~cont[src]
    rows = np.repeat(np.arange(kin.n), np.diff(kin.nbr_ptr))
    cols = kin.nbr_idx
    m = (rows < cols) & (p[rows] != p[cols]) & ocean[rows] & ocean[cols]
    i, j = rows[m], cols[m]
    x = kin.xyz[i] + kin.xyz[j]
    x /= np.maximum(np.linalg.norm(x, axis=1, keepdims=True), 1e-15)
    n = kin.xyz[i] - kin.xyz[j]
    n -= np.einsum("ij,ij->i", n, x)[:, None] * x
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-15)
    a, b = p[i], p[j]
    v = np.cross(omega[a] - omega[b], x) * kin.radius_km * _CM_PER_KM
    live = np.einsum("ij,ij->i", v, n) > min_opening_cm_yr
    return x[live], n[live], a[live], b[live]


def _margin_misfit(
    pos: np.ndarray,
    plate: np.ndarray,
    cont: np.ndarray,
    p_a: int,
    p_b: int,
    radius_km: float,
    spacing_km: float,
) -> float:
    """Median gap (km) between the facing continental margins of two plates.

    Margin parcels are each plate's continental parcels within three spacings of
    the other plate's continental crust; the misfit is the median distance from a
    margin parcel to the nearest margin parcel across, minus one spacing (the
    distance of touching parcels).
    """
    a = np.flatnonzero((plate == p_a) & cont)
    b = np.flatnonzero((plate == p_b) & cont)
    if a.size == 0 or b.size == 0:
        return float("nan")
    reach = 2.0 * np.sin(3.0 * spacing_km / (2.0 * radius_km))
    da, _ = cKDTree(pos[b]).query(pos[a], distance_upper_bound=reach)
    db, _ = cKDTree(pos[a]).query(pos[b], distance_upper_bound=reach)
    d = np.concatenate([da[np.isfinite(da)], db[np.isfinite(db)]])
    if d.size == 0:
        return float("nan")
    km = 2.0 * radius_km * np.arcsin(np.clip(d / 2.0, 0.0, 1.0))
    return float(max(np.median(km) - spacing_km, 0.0))


def active_orogens(
    kin: PlateKinematics,
    elevation_m: np.ndarray,
    closing_cm_yr: np.ndarray,
    cumulative_convergence_km: np.ndarray,
    *,
    min_relief_m: float = 500.0,
    reach_km: float = 500.0,
    build_range_myr: tuple[float, float] = (5.0, 100.0),
    min_closing_frac: float = MIN_MOTION_FRAC,
) -> Orogens:
    """Relief and build time of orogens next to active convergent boundaries.

    The baseline is the area-median elevation of continental crust farther than
    ``reach_km`` from any closing boundary.  A continental cell within ``reach_km``
    of a closing boundary cell and more than ``min_relief_m`` above the baseline
    carries the excess as orogen relief.  Its build time is the cumulative
    convergence at the nearest closing cell divided by that cell's closing rate,
    clipped to ``build_range_myr``; cells whose boundary has no recorded
    convergence take the median build time.

    Args:
        kin: reconstruction kinematics.
        elevation_m: (N,) present elevation.
        closing_cm_yr: (N,) signed opening rate at boundary cells (negative =
            closing; NaN off the boundary), from ``boundary_opening_rates``.
        cumulative_convergence_km: (N,) present-day accumulated shortening.
    """
    floor = min_closing_frac * boundary_speed_scale(kin)
    closing = np.isfinite(closing_cm_yr) & (closing_cm_yr < -floor)
    relief = np.zeros(kin.n)
    build = np.full(kin.n, build_range_myr[1])
    if not closing.any():
        return Orogens(relief_m=relief, build_myr=build)
    ci = np.flatnonzero(closing)
    d, k = cKDTree(kin.xyz[ci]).query(kin.xyz)
    d_km = 2.0 * kin.radius_km * np.arcsin(np.clip(d / 2.0, 0.0, 1.0))
    near = d_km < reach_km
    far_cont = kin.continental & ~near
    pool = far_cont if far_cont.any() else kin.continental
    order = np.argsort(elevation_m[pool])
    cum = np.cumsum(kin.area_km2[pool][order])
    baseline = float(elevation_m[pool][order][np.searchsorted(cum, 0.5 * cum[-1])])
    oro = kin.continental & near & (elevation_m > baseline + min_relief_m)
    nearest = ci[k]
    rate_km_myr = -closing_cm_yr[nearest] * _KM_PER_MYR_PER_CM_YR
    s_km = cumulative_convergence_km[nearest]
    t_build = np.where(s_km > 0, s_km / np.maximum(rate_km_myr, 1e-6), np.nan)
    fallback = float(np.nanmedian(t_build[oro])) if np.isfinite(t_build[oro]).any() else 30.0
    t_build = np.clip(np.where(np.isfinite(t_build), t_build, fallback), *build_range_myr)
    relief[oro] = elevation_m[oro] - baseline
    build[oro] = t_build[oro]
    return Orogens(relief_m=relief, build_myr=build)
