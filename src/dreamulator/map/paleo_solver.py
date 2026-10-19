"""Receding-horizon solver for the motions of the continental blocks (G2, §4.6).

Design: ``docs/design/proposals/geological-timeline.md`` §4.3–4.6.  The unknowns
are the Euler poles of every weld group (``paleo_blocks``) in every stage of
``stage_myr``, going back from the present.  Present seafloor moves rigidly with
the nearest continental block of its plate (a passive margin) and exists at a
time t only where it is at least t old; seafloor older than ``memory_myr`` or of
unknown age is left out.  The objective adds two hard terms and three priors,
all dimensionless:

* **overlap** (hard, large weight): crust that exists at t may not reach deeper
  than ``overlap_tol_km`` into another group's crust, continental or oceanic.
  Present seafloor was never subducted, so it cannot have lain on other crust.
  Depth is read from each block's signed distance field on the present mesh
  (its continental crust plus its seafloor older than t), linearised about the
  nearest cell so the term has a gradient.  Continental crust within
  ``margin_km`` of another plate's present ridge is a stretched margin with no
  conjugate seafloor on its side; like the overlap across a rift, it is taken
  back by thinning and leaves the term in both directions;
* **isochron fit** (hard): the two flanks of a present ridge meet at the ridge
  when their crust of age t forms, so at t the age-t isochrons of the two flanks
  coincide (Hellinger 1981).  A flank particle of age a ≥ t lies (a − t) times
  its ridge's half-rate from the ridge, so it may be that far, plus
  ``isochron_tol_km``, from the nearest conjugate cell of age about t; beyond
  that it is pulled towards it.  Particles that miss their conjugate isochron
  by more than ``isochron_check_km`` under the very poles that synthesised the
  ages (seafloor reached along a transform rather than a flowline) are left out
  of this term;
* **speed**: each group's angular speed stays near the continental-share law of
  ``paleo_kinematics.continental_speed_poles``; poles should be given in the
  no-net-rotation frame (``paleo_kinematics.no_net_rotation``), where absolute
  speeds mean something;
* **reorganisation**: a pseudo-Huber penalty on each block's pole change from one
  stage to the next, so poles stay put most of the time and change at once;
* **net rotation**: the area-weighted mean rotation of the continents stays near
  that of the stage-0 poles (the frame of the engine's poles is kept).

Welds give way to the seafloor record: no weld may put the two flanks of a
present ridge into one group while seafloor older than the weld time lies
between them (``ridge_record``).  A rift weld that would is postponed to that
seafloor's age (``seafloor_welds``); a contact weld that would is not made.
Rift onsets and contacts are estimates, the seafloor is a record.

The solve slides a window of ``window_stages`` stages back in time, optimises it
with L-BFGS and keeps only its first stage.  After each kept stage, groups whose
continental margins have come into contact going back (and were apart at
present) are welded from that time on: the contact time is their break-up time
(§4.5).  Stage 0 uses the poles the seafloor ages were synthesised with.
Gradients are exact: a stage rotation exp([θ]×) varies by the world rotation
J_l(θ)·dθ (left Jacobian of SO(3)), carried back through the later stages by an
adjoint pass.  Pure numpy/scipy, no IO; deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
from scipy.optimize import minimize
from scipy.spatial import cKDTree

from dreamulator.map.paleo_blocks import Blocks, Weld
from dreamulator.map.paleo_kinematics import rotation_matrices

if TYPE_CHECKING:
    from dreamulator.map.paleo_kinematics import PlateKinematics


# floor of a group's target angular speed, as a share of the reference speed
# (numerical safeguard: plates nearly at rest in the frame of the poles)
MIN_TARGET_FRAC = 0.1


@dataclass(frozen=True)
class SolverConfig:
    """Numerical conventions of the solve (§11: checked by sensitivity runs).

    Attributes:
        stage_myr: stage length.
        window_stages: stages optimised together; only the first is kept.
        end_myr: how far back to solve.
        n_particles: continental particles taking part in the objective.
        n_ocean_particles: seafloor particles taking part in the objective.
        seed: subsampling seed.
        overlap_tol_km: penetration tolerated before the overlap term acts
            (margin crust that thinned stretching can take back).
        depth_ref_km: distance that counts as one unit in the overlap and
            isochron terms.
        isochron_tol_km: isochron misfit tolerated before the isochron term acts.
        isochron_check_km: largest misfit under the synthesising poles for a
            particle to take part in the isochron term.
        contact_km: distance within which two margins count as touching.
        contact_share: margin share of the smaller block that must touch for a
            contact weld.
        margin_km: width of the stretched margin next to another plate's ridge,
            equal to the per-side stretching width of the rift onsets
            (``paleo_walk.continental_rifts``).
        reorg_eps: pseudo-Huber smoothing of the reorganisation term, in units of
            the reference angular speed.
        memory_myr: oldest seafloor that takes part (§3.3); older seafloor, made
            by ridges of about 1 cm/yr, is left unconstrained.
        w_overlap, w_isochron, w_speed, w_reorg, w_net_rotation: term weights.
        max_iter: L-BFGS iterations per window.
    """

    stage_myr: float = 5.0
    window_stages: int = 4
    end_myr: float = 150.0
    n_particles: int = 6000
    n_ocean_particles: int = 6000
    seed: int = 0
    overlap_tol_km: float = 30.0
    depth_ref_km: float = 100.0
    isochron_tol_km: float = 60.0
    isochron_check_km: float = 150.0
    contact_km: float = 100.0
    contact_share: float = 0.2
    margin_km: float = 300.0
    reorg_eps: float = 0.05
    memory_myr: float = 150.0
    w_overlap: float = 1000.0
    w_isochron: float = 100.0
    w_speed: float = 1.0
    w_reorg: float = 1.0
    w_net_rotation: float = 1.0
    max_iter: int = 200


@dataclass(frozen=True)
class Field:
    """Signed distance (km) to the edge of each block's crust on the present mesh.

    Attributes:
        sdf: (B, N) positive inside, negative outside, −inf beyond the contact band.
        near: (B, N) the nearest cell across the edge, from which the gradient
            direction is read.
        centre: (B, 3) and cap_cos: (B,) a spherical cap holding each block's
            crust plus the contact band.
    """

    sdf: np.ndarray
    near: np.ndarray
    centre: np.ndarray
    cap_cos: np.ndarray


@dataclass(frozen=True)
class SolverSetup:
    """Everything the objective needs that does not change during the solve.

    Attributes:
        p0: (Pn, 3) present positions of the particles, continental first.
        pblock: (Pn,) block each particle moves with.
        weight: (Pn,) area of each particle over the continental area.
        ocean: (Pn,) seafloor particle.
        age: (Pn,) seafloor age (Myr), NaN on continental particles.
        margin: (Pn,) continental particle on its block's edge.
        soft: (Pn,) continental particle on a stretched margin next to a ridge.
        ridge: (Pn,) ridge (index into ``ridge_plates``) that made a seafloor
            particle, −1 elsewhere; flank: (Pn,) 0 or 1, which side of it.
        half_km_myr: (Pn,) half-rate of that ridge (km/Myr).
        ridge_plates: (plate a, plate b) of each present ridge.
        cont_field: continental crust only (contact detection).
        cell_block: (N,) block of each continental cell, −1 elsewhere.
        cell_soft: (N,) continental cell on a stretched margin next to a ridge.
        cell_host: (N,) block a seafloor cell moves with, −1 where it is left out.
        cell_age: (N,) seafloor age (Myr) of the cells that take part.
        cell_ridge, cell_flank: (N,) the same as ``ridge`` and ``flank`` per cell.
        target_rate: (B,) angular speed (rad/yr) of each block's present plate
            under the continental-share law.
        present_omega: (B, 3) stage-0 pole of each block's plate.
        rate_ref: reference angular speed (area-weighted mean of target_rate).
        tree: KD-tree of the present cell centres.
        xyz: (N, 3) present cell centres; nbr_rows, nbr_cols: mesh edges.
        radius_km: planet radius; spacing_km: mesh spacing.
        cache: crust fields by time (``crust_field``).
    """

    p0: np.ndarray
    pblock: np.ndarray
    weight: np.ndarray
    ocean: np.ndarray
    age: np.ndarray
    margin: np.ndarray
    soft: np.ndarray
    ridge: np.ndarray
    flank: np.ndarray
    half_km_myr: np.ndarray
    ridge_plates: list[tuple[int, int]]
    cont_field: Field
    cell_block: np.ndarray
    cell_soft: np.ndarray
    cell_host: np.ndarray
    cell_age: np.ndarray
    cell_ridge: np.ndarray
    cell_flank: np.ndarray
    target_rate: np.ndarray
    present_omega: np.ndarray
    rate_ref: float
    tree: cKDTree
    xyz: np.ndarray
    nbr_rows: np.ndarray
    nbr_cols: np.ndarray
    radius_km: float
    spacing_km: float
    cache: dict[float, Field] = field(default_factory=dict)


@dataclass
class SolveResult:
    """Kept stages of a solve.

    Attributes:
        stage_omega: (S, B, 3) pole of each block in each kept stage.
        groups: (S, B) weld group of each block in each stage.
        contact_welds: welds added when margins touched going back.
        stats: one dict per stage (objective terms, worst penetration, iterations).
    """

    stage_omega: np.ndarray
    groups: np.ndarray
    contact_welds: list[Weld] = field(default_factory=list)
    stats: list[dict[str, float]] = field(default_factory=list)


def skew(v: np.ndarray) -> np.ndarray:
    """(..., 3, 3) cross-product matrices [v]×."""
    z = np.zeros(v.shape[:-1])
    return np.stack(
        [
            np.stack([z, -v[..., 2], v[..., 1]], axis=-1),
            np.stack([v[..., 2], z, -v[..., 0]], axis=-1),
            np.stack([-v[..., 1], v[..., 0], z], axis=-1),
        ],
        axis=-2,
    )


def left_jacobian(theta: np.ndarray) -> np.ndarray:
    """(K, 3, 3) left Jacobians of SO(3): d exp([θ]×) = [J_l dθ]× exp([θ]×)."""
    phi = np.linalg.norm(theta, axis=1)
    k = skew(theta)
    small = phi < 1e-6
    ps = np.where(small, 1.0, phi)
    a = np.where(small, 0.5 - phi**2 / 24.0, (1.0 - np.cos(ps)) / ps**2)
    b = np.where(small, 1.0 / 6.0 - phi**2 / 120.0, (ps - np.sin(ps)) / ps**3)
    jac: np.ndarray = np.eye(3)[None] + a[:, None, None] * k + b[:, None, None] * (k @ k)
    return jac


def build_setup(
    kin: PlateKinematics,
    blocks: Blocks,
    stage0_omega: np.ndarray,
    target_omega: np.ndarray,
    seafloor_age: np.ndarray,
    ridge_source: np.ndarray,
    half_rate: np.ndarray,
    config: SolverConfig,
) -> SolverSetup:
    """Particles, crust fields and prior targets for a solve.

    ``stage0_omega`` (P, 3) are the poles the seafloor ages were synthesised with
    (``synthesize_seafloor_age`` gives ``seafloor_age`` and ``ridge_source``,
    ``ridge_half_rates`` the ``half_rate`` (cm/yr) of the ridge cells);
    ``target_omega`` (P, 3) the continental-share poles (``continental_speed_poles``)
    that set the speed prior.
    """
    rng = np.random.default_rng(config.seed)
    area = kin.area_km2
    cont = np.flatnonzero(blocks.block >= 0)
    a_cont = float(area[cont].sum())
    rows = np.repeat(np.arange(kin.n), np.diff(kin.nbr_ptr))
    cols = kin.nbr_idx

    # seafloor that takes part: known age within the memory window; it moves with
    # the nearest continental block of its plate
    ok = (~kin.continental) & np.isfinite(seafloor_age) & (seafloor_age <= config.memory_myr)
    host = np.full(kin.n, -1)
    for p in np.unique(kin.plate[ok]):
        sea = np.flatnonzero(ok & (kin.plate == p))
        land = np.flatnonzero((blocks.block >= 0) & (kin.plate == p))
        if land.size == 0:
            continue
        _, j = cKDTree(kin.xyz[land]).query(kin.xyz[sea])
        host[sea] = blocks.block[land[j]]
    cell_age = np.where(host >= 0, seafloor_age, np.nan)

    # present ridges and the flank of each seafloor cell
    ridge_of = np.full(kin.n, -1)
    flank_of = np.zeros(kin.n, dtype=np.int64)
    keys: dict[tuple[int, int], int] = {}
    for cell in np.flatnonzero(host >= 0):
        r = int(ridge_source[cell])
        if r < 0:
            continue
        nb = kin.neighbors(r)
        other = kin.plate[nb][kin.plate[nb] != kin.plate[r]]
        if other.size == 0:
            continue
        key = (int(min(kin.plate[cell], other[0])), int(max(kin.plate[cell], other[0])))
        ridge_of[cell] = keys.setdefault(key, len(keys))
        flank_of[cell] = 0 if kin.plate[cell] == key[0] else 1

    # stretched margins: continental crust within margin_km of another plate's ridge
    soft = np.zeros(kin.n, dtype=bool)
    ridge_cells = np.flatnonzero(np.isfinite(half_rate))
    if ridge_cells.size:
        d, j = cKDTree(kin.xyz[ridge_cells]).query(
            kin.xyz[cont], distance_upper_bound=config.margin_km / kin.radius_km
        )
        hit = np.isfinite(d)
        soft[cont[hit]] = kin.plate[ridge_cells[j[hit]]] != kin.plate[cont[hit]]

    # particles: uniform subsamples, each block keeping its own area
    pick_c = np.sort(rng.choice(cont, size=min(config.n_particles, cont.size), replace=False))
    sea = np.flatnonzero(host >= 0)
    pick_o = np.sort(rng.choice(sea, size=min(config.n_ocean_particles, sea.size), replace=False))
    w_c = area[pick_c].copy()
    for b in range(blocks.n):
        sel = blocks.block[pick_c] == b
        if sel.any():
            w_c[sel] *= area[blocks.block == b].sum() / w_c[sel].sum()
    w_o = area[pick_o] * (area[sea].sum() / max(area[pick_o].sum(), 1e-30))
    pick = np.concatenate([pick_c, pick_o])
    edge = np.zeros(kin.n, dtype=bool)
    edge[rows[blocks.block[rows] != blocks.block[cols]]] = True
    n_c = pick_c.size

    setup = SolverSetup(
        p0=kin.xyz[pick],
        pblock=np.concatenate([blocks.block[pick_c], host[pick_o]]),
        weight=np.concatenate([w_c, w_o]) / a_cont,
        ocean=np.arange(pick.size) >= n_c,
        age=np.concatenate([np.full(n_c, np.nan), cell_age[pick_o]]),
        margin=np.concatenate([edge[pick_c], np.zeros(pick_o.size, dtype=bool)]),
        soft=np.concatenate([soft[pick_c], np.zeros(pick_o.size, dtype=bool)]),
        ridge=np.concatenate([np.full(n_c, -1), ridge_of[pick_o]]),
        flank=np.concatenate([np.zeros(n_c, dtype=np.int64), flank_of[pick_o]]),
        half_km_myr=np.concatenate(
            [np.zeros(n_c), 10.0 * half_rate[np.maximum(ridge_source[pick_o], 0)]]
        ),
        ridge_plates=sorted(keys, key=lambda k: keys[k]),
        cont_field=Field(np.zeros((0, 0)), np.zeros((0, 0)), np.zeros((0, 3)), np.zeros(0)),
        cell_block=blocks.block.copy(),
        cell_soft=soft,
        cell_host=host,
        cell_age=cell_age,
        cell_ridge=ridge_of,
        cell_flank=flank_of,
        target_rate=np.linalg.norm(target_omega, axis=1)[blocks.plate],
        present_omega=stage0_omega[blocks.plate],
        rate_ref=0.0,
        tree=cKDTree(kin.xyz),
        xyz=kin.xyz,
        nbr_rows=rows,
        nbr_cols=cols,
        radius_km=kin.radius_km,
        spacing_km=kin.spacing_km,
    )
    barea = np.array([area[blocks.block == b].sum() for b in range(blocks.n)])
    rate_ref = float(np.average(setup.target_rate, weights=barea))
    setup = _replace_setup(setup, ridge=_consistent_ridge(setup, config, stage0_omega, kin.plate))
    cont_field = _region_field(setup, config, blocks.block[None] == np.arange(blocks.n)[:, None])
    return _replace_setup(setup, cont_field=cont_field, rate_ref=rate_ref)


def _consistent_ridge(
    setup: SolverSetup, config: SolverConfig, omega: np.ndarray, plate: np.ndarray
) -> np.ndarray:
    """``setup.ridge`` with particles that miss their own isochron set to −1.

    Each ridge particle is turned back to its own age with the present poles
    (``omega`` per plate, the poles that synthesised the ages); there it should
    lie on the conjugate isochron (§4.1).
    """
    ridge = setup.ridge.copy()
    idx = np.flatnonzero(ridge >= 0)
    if idx.size == 0:
        return ridge
    cells = setup.tree.query(setup.p0[idx])[1]
    step = 0.5 * config.stage_myr
    for t in np.arange(0.0, float(np.nanmax(setup.age[idx])) + step, step):
        sel = idx[(setup.age[idx] >= t) & (setup.age[idx] < t + step)]
        if sel.size == 0:
            continue
        own = cells[np.searchsorted(idx, sel)]
        x = np.einsum("pij,pj->pi", rotation_matrices(omega[plate[own]], -t * 1.0e6), setup.p0[sel])
        for r in np.unique(ridge[sel]):
            for side in (0, 1):
                src = sel[(ridge[sel] == r) & (setup.flank[sel] == side)]
                if src.size == 0:
                    continue
                dst = np.flatnonzero(
                    (setup.cell_ridge == r)
                    & (setup.cell_flank == 1 - side)
                    & (setup.cell_age >= t)
                    & (setup.cell_age <= t + step)
                )
                if dst.size == 0:
                    ridge[src] = -1
                    continue
                xd = np.einsum(
                    "pij,pj->pi", rotation_matrices(omega[plate[dst]], -t * 1.0e6), setup.xyz[dst]
                )
                d, _ = cKDTree(xd).query(x[np.searchsorted(sel, src)])
                miss = d * setup.radius_km - (setup.age[src] - t) * setup.half_km_myr[src]
                ridge[src[miss > config.isochron_check_km]] = -1
    return ridge


def ridge_record(setup: SolverSetup) -> dict[tuple[int, int], float]:
    """Block pairs that may not share a weld group before a seafloor age.

    For each present ridge the record age is the 90th percentile age of its
    particles that passed the isochron check; the blocks hosting its two flanks
    moved apart over that time.
    """
    forbid: dict[tuple[int, int], float] = {}
    for r in np.unique(setup.ridge[setup.ridge >= 0]):
        sel = setup.ridge == r
        age = float(np.percentile(setup.age[sel], 90))
        sides = [set(setup.pblock[sel & (setup.flank == f)].tolist()) for f in (0, 1)]
        for a in sides[0]:
            for b in sides[1]:
                if a != b:
                    key = (min(a, b), max(a, b))
                    forbid[key] = max(forbid.get(key, 0.0), age)
    return forbid


def seafloor_welds(blocks: Blocks, setup: SolverSetup) -> tuple[Blocks, list[dict[str, float]]]:
    """Rift welds postponed so that no weld group spans a ridge with older seafloor.

    Rift welds are added in order of onset; one that would join a pair of
    ``ridge_record`` is postponed to the pair's record age and tried again.
    Returns the new blocks and the postponed welds.
    """
    forbid = ridge_record(setup)
    welds = [w for w in blocks.welds if w.kind != "rift"]
    pending = sorted(
        (w for w in blocks.welds if w.kind == "rift"), key=lambda w: (w.since_myr or 0.0, w.a, w.b)
    )
    changed: list[dict[str, float]] = []
    while pending:
        w = pending.pop(0)
        t = float(w.since_myr or 0.0)
        trial = Blocks(block=blocks.block, plate=blocks.plate, welds=[*welds, w])
        g = trial.groups(t + 1e-6)
        clash = [age for (a, b), age in forbid.items() if g[a] == g[b] and age > t + 1e-6]
        if not clash:
            welds.append(w)
            continue
        later = min(max(clash), w.until_myr if w.until_myr is not None else np.inf)
        changed.append({"a": w.a, "b": w.b, "from_myr": t, "to_myr": later})
        if w.until_myr is None or later < w.until_myr:
            moved = Weld(w.a, w.b, w.kind, until_myr=w.until_myr, since_myr=later)
            pending.append(moved)
            pending.sort(key=lambda x: (x.since_myr or 0.0, x.a, x.b))
    return Blocks(block=blocks.block, plate=blocks.plate, welds=welds, names=blocks.names), changed


def _replace_setup(setup: SolverSetup, **changes: object) -> SolverSetup:
    from dataclasses import replace

    return replace(setup, **changes)  # type: ignore[arg-type]


def _region_field(setup: SolverSetup, config: SolverConfig, member: np.ndarray) -> Field:
    """Signed distance field of each block's region ``member`` (B, N)."""
    nb, n = member.shape
    band = config.contact_km / setup.radius_km
    half = 0.5 * setup.spacing_km
    sdf = np.full((nb, n), -np.inf, dtype=np.float32)
    near = np.zeros((nb, n), dtype=np.int32)
    centre = np.zeros((nb, 3))
    cap_cos = np.full(nb, 2.0)  # an empty region matches nothing
    rows, cols = setup.nbr_rows, setup.nbr_cols
    for b in range(nb):
        inside = member[b]
        cells_in = np.flatnonzero(inside)
        if cells_in.size == 0:
            continue
        cross = inside[rows] & ~inside[cols]
        edge_in = np.unique(rows[cross])
        edge_out = np.unique(cols[cross])
        c = setup.xyz[cells_in].mean(axis=0)
        c /= max(float(np.linalg.norm(c)), 1e-15)
        centre[b] = c
        ang = float(np.arccos(np.clip(setup.xyz[cells_in] @ c, -1.0, 1.0)).max())
        cap_cos[b] = np.cos(min(ang + 2.0 * band, np.pi))
        if edge_out.size:
            d, j = cKDTree(setup.xyz[edge_out]).query(setup.xyz[cells_in])
            sdf[b, cells_in] = d * setup.radius_km - half
            near[b, cells_in] = edge_out[j]
        else:
            sdf[b, cells_in] = np.inf
        cand = np.flatnonzero((setup.xyz @ c >= cap_cos[b]) & ~inside)
        if edge_in.size and cand.size:
            d, j = cKDTree(setup.xyz[edge_in]).query(
                setup.xyz[cand], distance_upper_bound=band * 1.5
            )
            hit = np.isfinite(d)
            sdf[b, cand[hit]] = -(d[hit] * setup.radius_km) + half
            near[b, cand[hit]] = edge_in[j[hit]]
    return Field(sdf=sdf, near=near, centre=centre, cap_cos=cap_cos)


def crust_field(setup: SolverSetup, config: SolverConfig, t_myr: float) -> Field:
    """Field of each block's crust at ``t_myr``: continent plus seafloor ≥ t old."""
    key = round(t_myr, 6)
    if key not in setup.cache:
        nb = setup.present_omega.shape[0]
        ids = np.arange(nb)[:, None]
        sea = (setup.cell_host >= 0) & (setup.cell_age >= t_myr)
        land = np.where(setup.cell_soft, -1, setup.cell_block)
        member = (land[None] == ids) | (sea[None] & (setup.cell_host[None] == ids))
        setup.cache[key] = _region_field(setup, config, member)
    return setup.cache[key]


def _tangent_away(x: np.ndarray, p: np.ndarray) -> np.ndarray:
    """Unit tangent at ``x`` pointing away from ``p`` along the great circle."""
    t = x - p
    t -= np.einsum("ij,ij->i", t, x)[:, None] * x
    out: np.ndarray = t / np.maximum(np.linalg.norm(t, axis=1, keepdims=True), 1e-15)
    return out


def groups_at(blocks: Blocks, extra: list[Weld], t_myr: float) -> np.ndarray:
    """(B,) weld group of each block at ``t_myr``, including contact welds."""
    return Blocks(block=blocks.block, plate=blocks.plate, welds=blocks.welds + extra).groups(t_myr)


def _exempt(blocks: Blocks, t_myr: float) -> np.ndarray:
    """Block pairs across a rift, whose overlap the objective allows at ``t_myr``.

    Going back, the two sides of a rift approach until its onset and are welded
    after it; the overlap is the stretched margin the onset was derived from.
    The exemption ends at the collision age of a suture the rift reopened, when
    the two sides were apart.
    """
    out = np.zeros((blocks.n, blocks.n), dtype=bool)
    for w in blocks.welds:
        if w.kind == "rift" and (w.until_myr is None or t_myr <= w.until_myr):
            out[w.a, w.b] = out[w.b, w.a] = True
    return out


def _penetration(
    setup: SolverSetup,
    fld: Field,
    x: np.ndarray,
    active: np.ndarray,
    frame: np.ndarray,
    group: np.ndarray,
    exempt: np.ndarray,
) -> list[tuple[np.ndarray, int, np.ndarray, np.ndarray]]:
    """Particles reaching into other groups' crust at one stage.

    ``x`` (Pn, 3) are particle positions, ``active`` (Pn,) the particles whose
    crust exists, ``frame`` (B, 3, 3) the finite rotations of the blocks,
    ``group`` (B,) their groups, ``exempt`` (B, B) the block pairs whose overlap
    is allowed (``_exempt``).  Returns, per block c, (particle indices, c, depth
    km, world gradient of depth per unit displacement) for active particles of
    other groups inside c's contact band.
    """
    out = []
    pg = group[setup.pblock]
    for c in range(fld.sdf.shape[0]):
        cand = np.flatnonzero(active & (pg != group[c]) & ~exempt[setup.pblock, c])
        if cand.size == 0:
            continue
        y = x[cand] @ frame[c]  # rows: R_cᵀ x
        inside_cap = y @ fld.centre[c] >= fld.cap_cos[c]
        cand, y = cand[inside_cap], y[inside_cap]
        if cand.size == 0:
            continue
        _, k = setup.tree.query(y)
        s = fld.sdf[c, k].astype(float)
        live = np.isfinite(s)
        if not live.any():
            continue
        cand, y, k, s = cand[live], y[live], k[live], s[live]
        g = np.sign(s)[:, None] * _tangent_away(setup.xyz[k], setup.xyz[fld.near[c, k]])
        depth = s + setup.radius_km * np.einsum("ij,ij->i", g, y - setup.xyz[k])
        gw = setup.radius_km * (g @ frame[c].T)  # R_c g
        out.append((cand, c, depth, gw))
    return out


def _isochron_pairs(
    setup: SolverSetup,
    config: SolverConfig,
    x: np.ndarray,
    frame: np.ndarray,
    group: np.ndarray,
    t_myr: float,
) -> list[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]]:
    """Flank particles of age ≥ t and their nearest conjugate cells of age about t.

    Returns per ridge flank (particles, their allowed distance km, conjugate
    cells' host blocks, conjugate cells' world positions).  Particles within
    one stage of age t take part; conjugate cells within half a stage above t.
    Pairs whose blocks are in one group are left out (their misfit cannot change).
    """
    out = []
    iso = setup.ocean & (setup.age >= t_myr) & (setup.age <= t_myr + config.stage_myr)
    iso &= setup.ridge >= 0
    edge = (setup.cell_ridge >= 0) & (setup.cell_age >= t_myr)
    edge &= setup.cell_age <= t_myr + 0.5 * config.stage_myr
    for r in np.unique(setup.ridge[iso]):
        for side in (0, 1):
            src = np.flatnonzero(iso & (setup.ridge == r) & (setup.flank == side))
            dst = np.flatnonzero(edge & (setup.cell_ridge == r) & (setup.cell_flank == 1 - side))
            if src.size == 0 or dst.size == 0:
                continue
            host = setup.cell_host[dst]
            xd = np.einsum("pij,pj->pi", frame[host], setup.xyz[dst])
            _, j = cKDTree(xd).query(x[src])
            keep = group[setup.pblock[src]] != group[host[j]]
            if keep.any():
                src, j = src[keep], j[keep]
                allow = (setup.age[src] - t_myr) * setup.half_km_myr[src] + config.isochron_tol_km
                out.append((src, allow, host[j], xd[j]))
    return out


def _window_objective(
    u: np.ndarray,
    setup: SolverSetup,
    config: SolverConfig,
    frame0: np.ndarray,
    omega_prev: np.ndarray,
    group_lists: list[np.ndarray],
    exempts: list[np.ndarray],
    t_ends: list[float],
) -> tuple[float, np.ndarray, dict[str, float]]:
    """Objective and gradient of one window in scaled unknowns u = ω / rate_ref."""
    nb = frame0.shape[0]
    dt_yr = config.stage_myr * 1.0e6
    ref = setup.rate_ref
    offsets = np.cumsum([0] + [int(g.max()) + 1 for g in group_lists])
    omega_g = (u * ref).reshape(-1, 3)
    grad_g = np.zeros_like(omega_g)
    n_st = len(group_lists)
    om_b = [omega_g[offsets[s] + group_lists[s]] for s in range(n_st)]  # (B, 3) per stage
    rot = [rotation_matrices(om_b[s], -dt_yr) for s in range(n_st)]
    frames = []
    f = frame0
    for s in range(n_st):
        f = np.einsum("bij,bjk->bik", rot[s], f)
        frames.append(f)
    terms = {"overlap": 0.0, "isochron": 0.0, "speed": 0.0, "reorg": 0.0, "net_rotation": 0.0}
    gamma = [np.zeros((nb, 3)) for _ in range(n_st)]  # dL / d(world rotation of block)
    d_ref = config.depth_ref_km
    for s in range(n_st):
        t = t_ends[s]
        x = np.einsum("pij,pj->pi", frames[s][setup.pblock], setup.p0)
        active = (~setup.ocean & ~setup.soft) | (setup.age >= t)
        fld = crust_field(setup, config, t)
        for cand, c, depth, gw in _penetration(
            setup, fld, x, active, frames[s], group_lists[s], exempts[s]
        ):
            over = depth - config.overlap_tol_km
            hit = over > 0
            if not hit.any():
                continue
            cand, over, gw = cand[hit], over[hit], gw[hit]
            w = setup.weight[cand]
            terms["overlap"] += float(np.sum(w * (over / d_ref) ** 2))
            dldp = config.w_overlap * 2.0 * w * over / d_ref**2
            torque = dldp[:, None] * np.cross(x[cand], gw)
            np.add.at(gamma[s], setup.pblock[cand], torque)
            gamma[s][c] -= torque.sum(axis=0)
        pairs = _isochron_pairs(setup, config, x, frames[s], group_lists[s], t)
        n_iso = sum(p[0].size for p in pairs)
        for src, allow, mate_block, xm in pairs:
            diff = x[src] - xm
            dist = np.linalg.norm(diff, axis=1)
            miss = dist * setup.radius_km - allow
            hit = miss > 0
            if not hit.any():
                continue
            src, mate_block, xm = src[hit], mate_block[hit], xm[hit]
            diff, dist, miss = diff[hit], dist[hit], miss[hit]
            terms["isochron"] += float(np.sum((miss / d_ref) ** 2)) / n_iso
            dldd = config.w_isochron * 2.0 * miss / d_ref**2 / n_iso * setup.radius_km
            gx = (dldd / np.maximum(dist, 1e-15))[:, None] * diff  # dL/dx_src = −dL/dx_mate
            np.add.at(gamma[s], setup.pblock[src], np.cross(x[src], gx))
            np.add.at(gamma[s], mate_block, -np.cross(xm, gx))
    # adjoint pass: world rotations at stage s carried to later stages
    lam = np.zeros((nb, 3))
    for s in range(n_st - 1, -1, -1):
        lam = gamma[s] + (np.einsum("bji,bj->bi", rot[s + 1], lam) if s + 1 < n_st else 0.0)
        jl = left_jacobian(-om_b[s] * dt_yr)
        g_omega = -dt_yr * np.einsum("bji,bj->bi", jl, lam)  # per block
        np.add.at(grad_g, offsets[s] + group_lists[s], g_omega)

    land = ~setup.ocean
    barea = np.bincount(setup.pblock[land], weights=setup.weight[land], minlength=nb)
    # continental inertia at the window start (held fixed so the gradient is exact)
    x0 = np.einsum("pij,pj->pi", frame0[setup.pblock[land]], setup.p0[land])
    ib = np.zeros((nb, 3, 3))
    np.add.at(
        ib,
        setup.pblock[land],
        setup.weight[land, None, None] * (np.eye(3)[None] - x0[:, :, None] * x0[:, None, :]),
    )
    m_inv = np.linalg.inv(ib.sum(axis=0))
    for s in range(n_st):
        gl = group_lists[s]
        ng = int(gl.max()) + 1
        ga = np.bincount(gl, weights=barea, minlength=ng)
        tgt = np.bincount(gl, weights=barea * setup.target_rate, minlength=ng) / np.maximum(
            ga, 1e-30
        )
        # a target near zero would make the relative deviation blow up
        tgt = np.maximum(tgt, MIN_TARGET_FRAC * ref)
        om = omega_g[offsets[s] : offsets[s] + ng]
        rate = np.linalg.norm(om, axis=1)
        dev = (rate - tgt) / np.maximum(tgt, 1e-30)
        terms["speed"] += float(np.sum(ga * dev**2))
        grad_g[offsets[s] : offsets[s] + ng] += (
            config.w_speed
            * (2.0 * ga * dev / np.maximum(tgt, 1e-30) / np.maximum(rate, 1e-30))[:, None]
            * om
        )
        # reorganisation: each block's pole change from the previous stage
        prev = omega_prev if s == 0 else om_b[s - 1]
        d = (om_b[s] - prev) / ref
        hub = np.sqrt(np.sum(d**2, axis=1) + config.reorg_eps**2)
        terms["reorg"] += float(np.sum(barea * (hub - config.reorg_eps)))
        gd = config.w_reorg * (barea / hub)[:, None] * d / ref
        np.add.at(grad_g, offsets[s] + gl, gd)
        if s > 0:
            np.add.at(grad_g, offsets[s - 1] + group_lists[s - 1], -gd)
        # net rotation of the continents relative to that of the stage-0 poles
        net = m_inv @ np.einsum("bij,bj->i", ib, om_b[s] - setup.present_omega)
        terms["net_rotation"] += float(net @ net) / ref**2
        gn = config.w_net_rotation * 2.0 / ref**2 * np.einsum("bij,jk,k->bi", ib, m_inv, net)
        np.add.at(grad_g, offsets[s] + gl, gn)
    value = (
        config.w_overlap * terms["overlap"]
        + config.w_isochron * terms["isochron"]
        + config.w_speed * terms["speed"]
        + config.w_reorg * terms["reorg"]
        + config.w_net_rotation * terms["net_rotation"]
    )
    return value, (grad_g * ref).ravel(), terms


def stage_diagnostics(
    setup: SolverSetup,
    config: SolverConfig,
    frame: np.ndarray,
    group: np.ndarray,
    exempt: np.ndarray,
    t_myr: float,
) -> dict[str, float]:
    """Deepest penetration (km), overlapping area share and isochron misfit.

    The misfit is the 90th percentile (km) of the distance beyond the allowed one.
    """
    x = np.einsum("pij,pj->pi", frame[setup.pblock], setup.p0)
    active = (~setup.ocean & ~setup.soft) | (setup.age >= t_myr)
    worst = 0.0
    hit = np.zeros(setup.p0.shape[0], dtype=bool)
    fld = crust_field(setup, config, t_myr)
    for cand, _, depth, _ in _penetration(setup, fld, x, active, frame, group, exempt):
        if depth.size:
            worst = max(worst, float(depth.max()))
            hit[cand[depth > config.overlap_tol_km]] = True
    miss = [
        np.maximum(np.linalg.norm(x[a] - xm, axis=1) * setup.radius_km - allow, 0.0)
        for a, allow, _, xm in _isochron_pairs(setup, config, x, frame, group, t_myr)
    ]
    return {
        "worst_depth_km": worst,
        "overlap_area_share": float(setup.weight[hit].sum()),
        "ocean_overlap_share": float(setup.weight[hit & setup.ocean].sum()),
        "isochron_misfit_km": float(np.percentile(np.concatenate(miss), 90)) if miss else 0.0,
    }


def _value_and_grad(u: np.ndarray, *args: object) -> tuple[float, np.ndarray]:
    value, grad, _ = _window_objective(u, *args)  # type: ignore[arg-type]
    return value, grad


def _contact_welds(
    setup: SolverSetup,
    config: SolverConfig,
    blocks: Blocks,
    frame: np.ndarray,
    group: np.ndarray,
    present_share: dict[tuple[int, int], float],
    forbid: dict[tuple[int, int], float],
    t_myr: float,
) -> tuple[list[Weld], int]:
    """New welds between groups whose continental margins touch at ``t_myr`` (§4.5).

    A contact that would join a pair of ``ridge_record`` before its record age is
    not welded.  Returns the welds and the number of contacts refused.
    """
    # pairs with a weld relation already (rift, suture) follow that relation
    related = {(min(w.a, w.b), max(w.a, w.b)) for w in blocks.welds}
    share = _margin_contact(setup, config, frame, group)
    out = []
    refused = 0
    for (a, b), sh in sorted(share.items()):
        if group[a] == group[b] or (a, b) in related:
            continue
        if (
            sh >= config.contact_share
            and present_share.get((a, b), 0.0) < 0.5 * config.contact_share
        ):
            pair = {group[a], group[b]}
            if any({group[x], group[y]} == pair and age > t_myr for (x, y), age in forbid.items()):
                refused += 1
                continue
            out.append(Weld(a, b, "contact", since_myr=t_myr))
            group = np.where(group == group[b], group[a], group)
    return out, refused


def _margin_contact(
    setup: SolverSetup, config: SolverConfig, frame: np.ndarray, group: np.ndarray | None
) -> dict[tuple[int, int], float]:
    """Share of the smaller block's margin particles within ``contact_km`` of the other."""
    nb = frame.shape[0]
    fld = setup.cont_field
    x = np.einsum("pij,pj->pi", frame[setup.pblock], setup.p0)
    n_margin = np.bincount(setup.pblock[setup.margin], minlength=nb)
    touch: dict[tuple[int, int], int] = {}
    m_idx = np.flatnonzero(setup.margin)
    for c in range(nb):
        cand = m_idx[setup.pblock[m_idx] != c]
        if group is not None:
            cand = cand[group[setup.pblock[cand]] != group[c]]
        y = x[cand] @ frame[c]
        inside_cap = y @ fld.centre[c] >= fld.cap_cos[c]
        cand, y = cand[inside_cap], y[inside_cap]
        if cand.size == 0:
            continue
        _, k = setup.tree.query(y)
        s = fld.sdf[c, k]
        hit = cand[np.isfinite(s) & (s > -config.contact_km)]
        for b, n in zip(*np.unique(setup.pblock[hit], return_counts=True), strict=True):
            key = (int(min(b, c)), int(max(b, c)))
            touch[key] = touch.get(key, 0) + int(n)
    out = {}
    for (a, b), n in touch.items():
        smaller = max(min(n_margin[a], n_margin[b]), 1)
        out[(a, b)] = min(n / (2.0 * smaller), 1.0)
    return out


def solve(blocks: Blocks, setup: SolverSetup, config: SolverConfig) -> SolveResult:
    """Solve the block motions from the present back to ``config.end_myr``.

    Stage 0 uses ``setup.present_omega`` (§4.3, start).
    """
    dt = config.stage_myr
    n_stages = int(round(config.end_myr / dt))
    nb = blocks.n
    land = ~setup.ocean
    barea = np.bincount(setup.pblock[land], weights=setup.weight[land], minlength=nb)
    omegas = [setup.present_omega.copy()]
    welds: list[Weld] = []
    groups = [groups_at(blocks, welds, 0.5 * dt)]
    frame = rotation_matrices(setup.present_omega, -dt * 1.0e6)
    stats: list[dict[str, float]] = [
        {"t_myr": dt, **stage_diagnostics(setup, config, frame, groups[0], _exempt(blocks, dt), dt)}
    ]
    present_share = _margin_contact(setup, config, np.repeat(np.eye(3)[None], nb, axis=0), None)
    forbid = ridge_record(setup)
    welds += _contact_welds(setup, config, blocks, frame, groups[0], present_share, forbid, dt)[0]
    for k in range(1, n_stages):
        stages = list(range(k, min(k + config.window_stages, n_stages)))
        glists = []
        for s in stages:
            g = groups_at(blocks, welds, (s + 0.5) * dt)
            _, inv = np.unique(g, return_inverse=True)
            glists.append(inv.astype(np.int64))
        exempts = [_exempt(blocks, (s + 1) * dt) for s in stages]
        t_ends = [(s + 1) * dt for s in stages]
        for key in [key for key in setup.cache if key < t_ends[0] - 1e-6]:
            del setup.cache[key]
        prev = omegas[-1]
        x0 = np.concatenate([_group_mean(prev, gl, barea) for gl in glists]).ravel()
        x0 /= setup.rate_ref

        args = (setup, config, frame, prev, glists, exempts, t_ends)
        res = minimize(
            _value_and_grad,
            x0,
            args=args,
            jac=True,
            method="L-BFGS-B",
            options={"maxiter": config.max_iter},
        )
        ng0 = int(glists[0].max()) + 1
        _, _, terms = _window_objective(
            res.x[: 3 * ng0], setup, config, frame, prev, glists[:1], exempts[:1], t_ends[:1]
        )
        om0 = (res.x[: 3 * ng0] * setup.rate_ref).reshape(-1, 3)[glists[0]]
        omegas.append(om0)
        groups.append(groups_at(blocks, welds, (k + 0.5) * dt))
        frame = np.einsum("bij,bjk->bik", rotation_matrices(om0, -dt * 1.0e6), frame)
        new, refused = _contact_welds(
            setup, config, blocks, frame, groups[-1], present_share, forbid, (k + 1) * dt
        )
        welds += new
        stats.append(
            {
                "t_myr": (k + 1) * dt,
                "value": float(res.fun),
                "iterations": float(res.nit),
                "new_contact_welds": float(len(new)),
                "refused_contacts": float(refused),
                **{key: float(v) for key, v in terms.items()},
                **stage_diagnostics(setup, config, frame, groups[-1], exempts[0], (k + 1) * dt),
            }
        )
    return SolveResult(
        stage_omega=np.stack(omegas), groups=np.stack(groups), contact_welds=welds, stats=stats
    )


def _group_mean(omega: np.ndarray, group: np.ndarray, area: np.ndarray) -> np.ndarray:
    """(G, 3) area-weighted mean pole of each group: the start of a merged group."""
    ng = int(group.max()) + 1
    total = np.bincount(group, weights=area, minlength=ng)
    out = np.zeros((ng, 3))
    np.add.at(out, group, omega * area[:, None])
    mean: np.ndarray = out / np.maximum(total, 1e-30)[:, None]
    return mean
