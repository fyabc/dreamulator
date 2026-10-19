#!/usr/bin/env python3
"""Geological timeline G2: solve the continental blocks' motions back in time.

Builds the blocks of ``map/paleo_blocks.py`` (author sutures + continental
rifts) from a built map (read-only), sets up the objective of
``map/paleo_solver.py`` and solves from the present back to ``--end``.  Writes
``summary.json`` (configuration, per-stage terms, weld groups, contact welds,
continental speeds) and ``solve.npz`` (stage poles and groups); with ``--plot``
it maps the continents at a few epochs (``continents.png``), coloured by weld
group and drawn at their solved positions.

``--scale term=factor`` multiplies a term weight (overlap, isochron, speed,
reorg, net_rotation) for the weight-sensitivity runs of §4.3.  Stage 0 and the
seafloor ages use the engine's own poles; the speed prior uses the
continental-share poles.

Usage::

    uv run python scripts/geology/paleo_solve.py data/worlds/nacrea/maps/satellite_nacrea \\
        --out-dir /tmp/solve --end 150 --plot
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
from paleo_rewind import World

from dreamulator.map.paleo_blocks import build_blocks, finite_rotations
from dreamulator.map.paleo_kinematics import (
    boundary_cells,
    continental_speed_poles,
    ridge_half_rates,
    synthesize_seafloor_age,
)
from dreamulator.map.paleo_solver import SolverConfig, build_setup, seafloor_welds, solve
from dreamulator.map.paleo_sutures import load_sutures
from dreamulator.map.paleo_walk import continental_rifts

TERMS = ("overlap", "isochron", "speed", "reorg", "net_rotation")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("map_dir", type=Path)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--end", type=float, default=150.0)
    ap.add_argument("--epochs", type=float, nargs="+", default=[0, 30, 60, 90, 120, 150])
    ap.add_argument("--particles", type=int, default=6000)
    ap.add_argument("--max-iter", type=int, default=200)
    ap.add_argument("--scale", action="append", default=[], metavar="TERM=FACTOR")
    ap.add_argument("--plate-history", type=Path, default=None)
    ap.add_argument("--plot", action="store_true")
    args = ap.parse_args()

    config = SolverConfig(end_myr=args.end, n_particles=args.particles, max_iter=args.max_iter)
    for item in args.scale:
        term, factor = item.split("=")
        if term not in TERMS:
            raise SystemExit(f"unknown term {term!r}; one of {TERMS}")
        key = f"w_{term}"
        config = replace(config, **{key: getattr(config, key) * float(factor)})

    w = World(args.map_dir)
    kin = replace(w.kin, omega=continental_speed_poles(w.kin))
    hist = args.plate_history or (
        args.map_dir.resolve().parents[1] / "layers" / "geological" / "input" / "plate_history.yaml"
    )
    _, onsets = continental_rifts(kin, 300.0)
    blocks = build_blocks(kin, load_sutures(hist), onsets)
    # seafloor ages from the engine's own poles: the continental-share
    # correction slows some ridges to a few mm/yr and inflates their ages
    half, offset = ridge_half_rates(w.kin, boundary_cells(w.kin))
    age, source = synthesize_seafloor_age(w.kin, half, offset)
    t0 = time.time()
    setup = build_setup(kin, blocks, w.kin.omega, kin.omega, age, source, half, config)
    blocks, postponed = seafloor_welds(blocks, setup)
    for c in postponed:
        print(
            f"rift weld {blocks.names[int(c['a'])]} – {blocks.names[int(c['b'])]}"
            f" postponed {c['from_myr']:.1f} → {c['to_myr']:.1f} Myr (seafloor record)"
        )
    t1 = time.time()
    res = solve(blocks, setup, config)
    t2 = time.time()
    print(f"setup {t1 - t0:.1f} s, solve {t2 - t1:.1f} s")

    a = kin.area_km2
    barea = np.array([a[blocks.block == b].sum() for b in range(blocks.n)])
    rms_cm = []
    for s in range(res.stage_omega.shape[0]):
        frames = finite_rotations(res.stage_omega, config.stage_myr, s * config.stage_myr)
        land = ~setup.ocean
        x = np.einsum("pij,pj->pi", frames[setup.pblock[land]], setup.p0[land])
        v = np.cross(res.stage_omega[s][setup.pblock[land]], x) * kin.radius_km * 1.0e5
        rms = np.sqrt(np.average(np.sum(v**2, axis=1), weights=setup.weight[land]))
        rms_cm.append(float(rms))
    groups = []
    for s in range(res.groups.shape[0]):
        g = res.groups[s]
        sizes = sorted((float(barea[g == x].sum() / 1e6) for x in np.unique(g)), reverse=True)
        groups.append({"n": len(sizes), "largest_Mkm2": round(sizes[0], 1)})
    summary = {
        "config": asdict(config),
        "seconds": {"setup": round(t1 - t0, 1), "solve": round(t2 - t1, 1)},
        "ridges": [list(r) for r in setup.ridge_plates],
        "soft_margin_share": round(float(a[setup.cell_soft].sum() / a[blocks.block >= 0].sum()), 4),
        "stages": [
            {**st, "continental_rms_cm_yr": round(r, 2), **gr}
            for st, r, gr in zip(res.stats, rms_cm, groups, strict=True)
        ],
        "postponed_rift_welds": [
            {
                "a": blocks.names[int(c["a"])],
                "b": blocks.names[int(c["b"])],
                "from_myr": round(c["from_myr"], 1),
                "to_myr": round(c["to_myr"], 1),
            }
            for c in postponed
        ],
        "contact_welds": [
            {"a": blocks.names[c.a], "b": blocks.names[c.b], "since_myr": c.since_myr}
            for c in res.contact_welds
        ],
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    np.savez(args.out_dir / "solve.npz", stage_omega=res.stage_omega, groups=res.groups)
    for st in summary["stages"]:
        terms = "  ".join(f"{k[:5]} {st[k]:.3g}" for k in TERMS if k in st)
        print(
            f"t={st['t_myr']:5.0f}  groups {st['n']:2d} ({st['largest_Mkm2']:6.1f} Mkm²)"
            f"  v {st['continental_rms_cm_yr']:4.1f} cm/yr  depth {st['worst_depth_km']:5.0f} km"
            f"  over {st['overlap_area_share']:.3f} (sea {st['ocean_overlap_share']:.3f})"
            f"  iso {st['isochron_misfit_km']:4.0f} km  it {st.get('iterations', 0):.0f}  {terms}"
        )
    for c in summary["contact_welds"]:
        print("contact weld", c)

    if args.plot:
        import colorsys

        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        pal = np.array([colorsys.hls_to_rgb((i * 0.618034) % 1.0, 0.5, 0.65) for i in range(64)])
        cont = np.flatnonzero(blocks.block >= 0)
        n = len(args.epochs)
        fig, axes = plt.subplots((n + 1) // 2, 2, figsize=(18, 4.6 * ((n + 1) // 2)), squeeze=False)
        for ax, t in zip(axes.ravel(), args.epochs, strict=False):
            frames = finite_rotations(res.stage_omega, config.stage_myr, t)
            sea = np.flatnonzero((setup.cell_host >= 0) & (setup.cell_age >= t))
            xs = np.einsum("pij,pj->pi", frames[setup.cell_host[sea]], kin.xyz[sea])
            ax.scatter(
                np.degrees(np.arctan2(xs[:, 2], xs[:, 0])),
                np.degrees(np.arcsin(np.clip(xs[:, 1], -1, 1))),
                s=0.3,
                c=[(0.62, 0.72, 0.85)],
                lw=0,
                rasterized=True,
            )
            x = np.einsum("pij,pj->pi", frames[blocks.block[cont]], kin.xyz[cont])
            lon = np.degrees(np.arctan2(x[:, 2], x[:, 0]))
            lat = np.degrees(np.arcsin(np.clip(x[:, 1], -1, 1)))
            s = min(int(t / config.stage_myr), res.groups.shape[0] - 1)
            col = pal[res.groups[s][blocks.block[cont]] % len(pal)]
            ax.scatter(lon, lat, s=0.6, c=col, lw=0, rasterized=True)
            ax.set(xlim=(-180, 180), ylim=(-90, 90), aspect="equal", xticks=[], yticks=[])
            ax.set_facecolor((0.9, 0.93, 0.97))
            ax.set_title(
                f"−{t:g} Myr: continents by weld group ({len(np.unique(res.groups[s]))}),"
                " blue = present seafloor that exists"
            )
        for ax in axes.ravel()[n:]:
            ax.axis("off")
        fig.tight_layout()
        fig.savefig(args.out_dir / "continents.png", dpi=110)


if __name__ == "__main__":
    main()
