"""Receding-horizon solver for the motions of the continental blocks (G2).

Design: ``docs/design/proposals/geological-timeline.md`` §4.3–4.5.  The unknowns
are the Euler poles of every weld group (``paleo_blocks``) in every stage of
``stage_myr``, going back from the present.  The objective adds one hard term
and four priors, all dimensionless:

* **overlap** (hard, large weight): continental crust of one group may not
  reach deeper than ``overlap_tol_km`` into another group's block.  Depth is read
  from each block's signed distance field on the present mesh, linearised about
  the nearest cell so the term has a gradient;
* **speed**: each group's angular speed stays near the continental-share law of
  ``paleo_kinematics.continental_speed_poles``;
* **reorganisation**: a pseudo-Huber penalty on each block's pole change from one
  stage to the next, so poles stay put most of the time and change at once;
* **net rotation**: the area-weighted mean rotation of the continents stays near
  that of the present poles (the frame of the engine's poles is kept);
* **seafloor record**: two blocks separated by a present ridge keep the present
  relative motion while the seafloor between them exists (memory window).

The solve slides a window of ``window_stages`` stages back in time, optimises it
with L-BFGS and keeps only its first stage.  After each kept stage, groups whose
margins have come into contact going back (and were apart at present) are welded
from that time on: the contact time is their break-up time (§4.5).  Stage 0 uses
the present poles.  Gradients are exact: a stage rotation exp([θ]×) varies by
the world rotation J_l(θ)·dθ (left Jacobian of SO(3)), carried back through the
later stages by an adjoint pass.  Pure numpy/scipy, no IO; deterministic.
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


@dataclass(frozen=True)
class SolverConfig:
    """Numerical conventions of the solve (§11: checked by sensitivity runs).

    Attributes:
        stage_myr: stage length.
        window_stages: stages optimised together; only the first is kept.
        end_myr: how far back to solve.
        n_particles: continental particles taking part in the objective.
        seed: subsampling seed.
        overlap_tol_km: penetration tolerated before the overlap term acts
            (margin crust that thinned stretching can take back).
        depth_ref_km: depth that counts as one unit in the overlap term.
        contact_km: distance within which two margins count as touching.
        contact_share: margin share of the smaller block that must touch for a
            contact weld.
        reorg_eps: pseudo-Huber smoothing of the reorganisation term, in units of
            the reference angular speed.
        memory_myr: longest time the seafloor record constrains (§3.3).
        w_overlap, w_speed, w_reorg, w_net_rotation, w_seafloor: term weights.
        max_iter: L-BFGS iterations per window.
    """

    stage_myr: float = 5.0
    window_stages: int = 4
    end_myr: float = 150.0
    n_particles: int = 6000
    seed: int = 0
    overlap_tol_km: float = 30.0
    depth_ref_km: float = 100.0
    contact_km: float = 100.0
    contact_share: float = 0.2
    reorg_eps: float = 0.05
    memory_myr: float = 150.0
    w_overlap: float = 1000.0
    w_speed: float = 1.0
    w_reorg: float = 1.0
    w_net_rotation: float = 1.0
    w_seafloor: float = 1.0
    max_iter: int = 200


@dataclass(frozen=True)
class SolverSetup:
    """Everything the objective needs that does not change during the solve.

    Attributes:
        p0: (Pn, 3) present positions of the particles.
        pblock: (Pn,) block of each particle.
        weight: (Pn,) area share of each particle (sums to 1).
        margin: (Pn,) particle on its block's edge (next to ocean or another block).
        sdf: (B, N) signed distance (km) to each block's edge on the present
            mesh: positive inside, negative outside, −inf beyond the contact band.
        grad: (B, N, 3) unit tangent along which ``sdf`` grows.
        cap_centre: (B, 3) and cap_cos: (B,) a spherical cap holding each block
            plus the contact band.
        target_rate: (B,) angular speed (rad/yr) of each block's present plate
            under the continental-share law.
        present_omega: (B, 3) present (continental-share) pole of each block's plate.
        rate_ref: reference angular speed (area-weighted mean of target_rate).
        ridge_pairs: (block a, block b, seafloor age Myr) of blocks separated by a
            present ridge; the age is the 90th percentile of the seafloor that
            ridge made, at most ``memory_myr``.
        tree: KD-tree of the present cell centres.
        xyz: (N, 3) present cell centres.
        radius_km: planet radius.
    """

    p0: np.ndarray
    pblock: np.ndarray
    weight: np.ndarray
    margin: np.ndarray
    sdf: np.ndarray
    grad: np.ndarray
    cap_centre: np.ndarray
    cap_cos: np.ndarray
    target_rate: np.ndarray
    present_omega: np.ndarray
    rate_ref: float
    ridge_pairs: list[tuple[int, int, float]]
    tree: cKDTree
    xyz: np.ndarray
    radius_km: float


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
    present_omega: np.ndarray,
    seafloor_age: np.ndarray,
    ridge_source: np.ndarray,
    config: SolverConfig,
) -> SolverSetup:
    """Particles, signed distance fields and prior targets for a solve.

    ``present_omega`` is the (P, 3) continental-share pole of each present plate
    (``continental_speed_poles``); ``seafloor_age`` and ``ridge_source`` come from
    ``synthesize_seafloor_age``.
    """
    rng = np.random.default_rng(config.seed)
    cont = np.flatnonzero(blocks.block >= 0)
    a_cont = float(kin.area_km2[cont].sum())
    # particles: a uniform subsample, each block keeping its own area
    pick = np.sort(rng.choice(cont, size=min(config.n_particles, cont.size), replace=False))
    pblock = blocks.block[pick]
    weight = kin.area_km2[pick].copy()
    for b in range(blocks.n):
        sel = pblock == b
        if sel.any():
            weight[sel] *= kin.area_km2[blocks.block == b].sum() / weight[sel].sum()
    weight /= a_cont
    rows = np.repeat(np.arange(kin.n), np.diff(kin.nbr_ptr))
    cols = kin.nbr_idx
    edge = np.zeros(kin.n, dtype=bool)
    edge[rows[blocks.block[rows] != blocks.block[cols]]] = True
    margin = edge[pick]

    tree = cKDTree(kin.xyz)
    band = config.contact_km / kin.radius_km
    sdf = np.full((blocks.n, kin.n), -np.inf, dtype=np.float32)
    grad = np.zeros((blocks.n, kin.n, 3), dtype=np.float32)
    centre = np.zeros((blocks.n, 3))
    cap_cos = np.zeros(blocks.n)
    half = 0.5 * kin.spacing_km
    for b in range(blocks.n):
        inside = blocks.block == b
        edge_in = np.zeros(kin.n, dtype=bool)  # block cells next to a non-block cell
        edge_out = np.zeros(kin.n, dtype=bool)  # non-block cells next to the block
        cross = inside[rows] & ~inside[cols]
        edge_in[rows[cross]] = True
        edge_out[cols[cross]] = True
        cells_in = np.flatnonzero(inside)
        c = kin.xyz[cells_in].mean(axis=0)
        c /= np.linalg.norm(c)
        centre[b] = c
        ang = float(np.arccos(np.clip(kin.xyz[cells_in] @ c, -1.0, 1.0)).max())
        cap_cos[b] = np.cos(min(ang + 2.0 * band, np.pi))
        out_pts = np.flatnonzero(edge_out)
        if out_pts.size:
            d, j = cKDTree(kin.xyz[out_pts]).query(kin.xyz[cells_in])
            near = kin.xyz[out_pts[j]]
            sdf[b, cells_in] = d * kin.radius_km - half
            grad[b, cells_in] = _tangent_away(kin.xyz[cells_in], near)
        else:
            sdf[b, cells_in] = np.inf
        in_pts = np.flatnonzero(edge_in)
        cand = np.flatnonzero((kin.xyz @ c >= cap_cos[b]) & ~inside)
        if in_pts.size and cand.size:
            d, j = cKDTree(kin.xyz[in_pts]).query(kin.xyz[cand], distance_upper_bound=band * 1.5)
            ok = np.isfinite(d)
            near = kin.xyz[in_pts[j[ok]]]
            sdf[b, cand[ok]] = -(d[ok] * kin.radius_km) + half
            grad[b, cand[ok]] = -_tangent_away(kin.xyz[cand[ok]], near)

    rate_p = np.linalg.norm(present_omega, axis=1)
    target = rate_p[blocks.plate]
    barea = np.array([kin.area_km2[blocks.block == b].sum() for b in range(blocks.n)])
    rate_ref = float(np.average(target, weights=barea))

    # blocks separated by a present ridge: largest block of each plate, oldest age
    big: dict[int, int] = {}
    for b in np.argsort(-barea):
        big.setdefault(int(blocks.plate[b]), int(b))
    ages: dict[tuple[int, int], list[float]] = {}
    ocean = np.isfinite(seafloor_age) & (ridge_source >= 0)
    for cell in np.flatnonzero(ocean):
        r = int(ridge_source[cell])
        nb = kin.neighbors(r)
        other = kin.plate[nb][kin.plate[nb] != kin.plate[r]]
        if other.size == 0:
            continue
        key = (int(min(kin.plate[cell], other[0])), int(max(kin.plate[cell], other[0])))
        ages.setdefault(key, []).append(float(seafloor_age[cell]))
    oldest = {k: min(float(np.percentile(v, 90)), config.memory_myr) for k, v in ages.items()}
    ridge_pairs = [
        (big[p], big[q], age) for (p, q), age in sorted(oldest.items()) if p in big and q in big
    ]
    return SolverSetup(
        p0=kin.xyz[pick],
        pblock=pblock,
        weight=weight,
        margin=margin,
        sdf=sdf,
        grad=grad,
        cap_centre=centre,
        cap_cos=cap_cos,
        target_rate=target,
        present_omega=present_omega[blocks.plate],
        rate_ref=rate_ref,
        ridge_pairs=ridge_pairs,
        tree=tree,
        xyz=kin.xyz,
        radius_km=kin.radius_km,
    )


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
    setup: SolverSetup, x: np.ndarray, frame: np.ndarray, group: np.ndarray, exempt: np.ndarray
) -> list[tuple[np.ndarray, int, np.ndarray, np.ndarray]]:
    """Particles reaching into other groups' blocks at one stage.

    ``x`` (Pn, 3) are particle positions, ``frame`` (B, 3, 3) the finite
    rotations of the blocks, ``group`` (B,) their groups, ``exempt`` (B, B) the
    block pairs whose overlap is allowed (``_exempt``).  Returns, per block c,
    (particle indices, c, depth km, world gradient of depth per unit
    displacement) for particles of other groups inside c's contact band.
    """
    out = []
    pg = group[setup.pblock]
    for c in range(setup.sdf.shape[0]):
        cand = np.flatnonzero((pg != group[c]) & ~exempt[setup.pblock, c])
        if cand.size == 0:
            continue
        y = x[cand] @ frame[c]  # rows: R_cᵀ x
        near = y @ setup.cap_centre[c] >= setup.cap_cos[c]
        cand, y = cand[near], y[near]
        if cand.size == 0:
            continue
        _, k = setup.tree.query(y)
        s = setup.sdf[c, k].astype(float)
        live = np.isfinite(s)
        if not live.any():
            continue
        cand, y, k, s = cand[live], y[live], k[live], s[live]
        g = setup.grad[c, k].astype(float)
        depth = s + setup.radius_km * np.einsum("ij,ij->i", g, y - setup.xyz[k])
        gw = setup.radius_km * (g @ frame[c].T)  # R_c g
        out.append((cand, c, depth, gw))
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
    terms = {"overlap": 0.0, "speed": 0.0, "reorg": 0.0, "net_rotation": 0.0, "seafloor": 0.0}
    gamma = [np.zeros((nb, 3)) for _ in range(n_st)]  # dL / d(world rotation of block)
    worst = 0.0
    for s in range(n_st):
        x = np.einsum("pij,pj->pi", frames[s][setup.pblock], setup.p0)
        for cand, c, depth, gw in _penetration(setup, x, frames[s], group_lists[s], exempts[s]):
            over = depth - config.overlap_tol_km
            hit = over > 0
            if not hit.any():
                continue
            cand, over, gw = cand[hit], over[hit], gw[hit]
            worst = max(worst, float(over.max() + config.overlap_tol_km))
            w = setup.weight[cand]
            terms["overlap"] += float(np.sum(w * (over / config.depth_ref_km) ** 2))
            dldp = config.w_overlap * 2.0 * w * over / config.depth_ref_km**2
            torque = dldp[:, None] * np.cross(x[cand], gw)
            np.add.at(gamma[s], setup.pblock[cand], torque)
            gamma[s][c] -= torque.sum(axis=0)
    # adjoint pass: world rotations at stage s carried to later stages
    lam = np.zeros((nb, 3))
    for s in range(n_st - 1, -1, -1):
        lam = gamma[s] + (np.einsum("bji,bj->bi", rot[s + 1], lam) if s + 1 < n_st else 0.0)
        jl = left_jacobian(-om_b[s] * dt_yr)
        g_omega = -dt_yr * np.einsum("bji,bj->bi", jl, lam)  # per block
        np.add.at(grad_g, offsets[s] + group_lists[s], g_omega)

    barea = np.bincount(setup.pblock, weights=setup.weight, minlength=nb)
    # continental inertia at the window start (held fixed so the gradient is exact)
    x0 = np.einsum("pij,pj->pi", frame0[setup.pblock], setup.p0)
    ib = np.zeros((nb, 3, 3))
    np.add.at(
        ib,
        setup.pblock,
        setup.weight[:, None, None] * (np.eye(3)[None] - x0[:, :, None] * x0[:, None, :]),
    )
    m_inv = np.linalg.inv(ib.sum(axis=0))
    for s in range(n_st):
        gl = group_lists[s]
        ng = int(gl.max()) + 1
        ga = np.bincount(gl, weights=barea, minlength=ng)
        tgt = np.bincount(gl, weights=barea * setup.target_rate, minlength=ng) / np.maximum(
            ga, 1e-30
        )
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
        # net rotation of the continents relative to that of the present poles
        net = m_inv @ np.einsum("bij,bj->i", ib, om_b[s] - setup.present_omega)
        terms["net_rotation"] += float(net @ net) / ref**2
        gn = config.w_net_rotation * 2.0 / ref**2 * np.einsum("bij,jk,k->bi", ib, m_inv, net)
        np.add.at(grad_g, offsets[s] + gl, gn)
        # seafloor record: relative motion across present ridges in the memory window
        for a, b, age in setup.ridge_pairs:
            if t_ends[s] > age or gl[a] == gl[b]:
                continue
            r = (om_b[s][a] - om_b[s][b] - setup.present_omega[a] + setup.present_omega[b]) / ref
            k = max(len(setup.ridge_pairs), 1)
            terms["seafloor"] += float(r @ r) / k
            gr = config.w_seafloor * 2.0 * r / ref / k
            grad_g[offsets[s] + gl[a]] += gr
            grad_g[offsets[s] + gl[b]] -= gr
    value = (
        config.w_overlap * terms["overlap"]
        + config.w_speed * terms["speed"]
        + config.w_reorg * terms["reorg"]
        + config.w_net_rotation * terms["net_rotation"]
        + config.w_seafloor * terms["seafloor"]
    )
    terms["worst_depth_km"] = worst
    return value, (grad_g * ref).ravel(), terms


def stage_overlap(
    setup: SolverSetup,
    config: SolverConfig,
    frame: np.ndarray,
    group: np.ndarray,
    exempt: np.ndarray,
) -> dict[str, float]:
    """Deepest penetration (km) and continental area share beyond the tolerance."""
    x = np.einsum("pij,pj->pi", frame[setup.pblock], setup.p0)
    worst = 0.0
    hit = np.zeros(setup.p0.shape[0], dtype=bool)
    for cand, _, depth, _ in _penetration(setup, x, frame, group, exempt):
        if depth.size:
            worst = max(worst, float(depth.max()))
            hit[cand[depth > config.overlap_tol_km]] = True
    return {"worst_depth_km": worst, "overlap_area_share": float(setup.weight[hit].sum())}


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
    t_myr: float,
) -> list[Weld]:
    """New welds between groups whose margins touch at ``t_myr`` (§4.5)."""
    # pairs with a weld relation already (rift, suture) follow that relation
    related = {(min(w.a, w.b), max(w.a, w.b)) for w in blocks.welds}
    share = _margin_contact(setup, config, frame, group)
    out = []
    for (a, b), sh in sorted(share.items()):
        if group[a] == group[b] or (a, b) in related:
            continue
        if (
            sh >= config.contact_share
            and present_share.get((a, b), 0.0) < 0.5 * config.contact_share
        ):
            out.append(Weld(a, b, "contact", since_myr=t_myr))
            group = np.where(group == group[b], group[a], group)
    return out


def _margin_contact(
    setup: SolverSetup, config: SolverConfig, frame: np.ndarray, group: np.ndarray | None
) -> dict[tuple[int, int], float]:
    """Share of the smaller block's margin particles within ``contact_km`` of the other."""
    nb = frame.shape[0]
    x = np.einsum("pij,pj->pi", frame[setup.pblock], setup.p0)
    n_margin = np.bincount(setup.pblock[setup.margin], minlength=nb)
    touch: dict[tuple[int, int], int] = {}
    m_idx = np.flatnonzero(setup.margin)
    for c in range(nb):
        cand = m_idx[setup.pblock[m_idx] != c]
        if group is not None:
            cand = cand[group[setup.pblock[cand]] != group[c]]
        y = x[cand] @ frame[c]
        near = y @ setup.cap_centre[c] >= setup.cap_cos[c]
        cand, y = cand[near], y[near]
        if cand.size == 0:
            continue
        _, k = setup.tree.query(y)
        s = setup.sdf[c, k]
        hit = cand[np.isfinite(s) & (s > -config.contact_km)]
        for b, n in zip(*np.unique(setup.pblock[hit], return_counts=True), strict=True):
            key = (int(min(b, c)), int(max(b, c)))
            touch[key] = touch.get(key, 0) + int(n)
    out = {}
    for (a, b), n in touch.items():
        smaller = max(min(n_margin[a], n_margin[b]), 1)
        out[(a, b)] = min(n / (2.0 * smaller), 1.0)
    return out


def solve(
    blocks: Blocks, setup: SolverSetup, config: SolverConfig, present_block_omega: np.ndarray
) -> SolveResult:
    """Solve the block motions from the present back to ``config.end_myr``.

    ``present_block_omega`` (B, 3) is used for stage 0 (§4.3, start).
    """
    dt = config.stage_myr
    n_stages = int(round(config.end_myr / dt))
    nb = blocks.n
    barea = np.bincount(setup.pblock, weights=setup.weight, minlength=nb)
    omegas = [present_block_omega.copy()]
    welds: list[Weld] = []
    groups = [groups_at(blocks, welds, 0.5 * dt)]
    stats: list[dict[str, float]] = [
        {
            "t_myr": dt,
            **stage_overlap(
                setup,
                config,
                frame0 := rotation_matrices(present_block_omega, -dt * 1.0e6),
                groups[0],
                _exempt(blocks, dt),
            ),
        }
    ]
    frame = frame0
    present_share = _margin_contact(setup, config, np.repeat(np.eye(3)[None], nb, axis=0), None)
    welds += _contact_welds(setup, config, blocks, frame, groups[0], present_share, dt)
    for k in range(1, n_stages):
        stages = list(range(k, min(k + config.window_stages, n_stages)))
        glists = []
        for s in stages:
            g = groups_at(blocks, welds, (s + 0.5) * dt)
            _, inv = np.unique(g, return_inverse=True)
            glists.append(inv.astype(np.int64))
        exempts = [_exempt(blocks, (s + 1) * dt) for s in stages]
        t_ends = [(s + 1) * dt for s in stages]
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
        new = _contact_welds(setup, config, blocks, frame, groups[-1], present_share, (k + 1) * dt)
        welds += new
        stats.append(
            {
                "t_myr": (k + 1) * dt,
                "value": float(res.fun),
                "iterations": float(res.nit),
                "new_contact_welds": float(len(new)),
                **{key: float(v) for key, v in terms.items() if key != "worst_depth_km"},
                **stage_overlap(setup, config, frame, groups[-1], exempts[0]),
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
