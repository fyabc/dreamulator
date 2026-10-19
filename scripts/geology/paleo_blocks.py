#!/usr/bin/env python3
"""Geological timeline G1 diagnostic: continental blocks, welds, weld groups over time.

Builds the blocks of ``map/paleo_blocks.py`` from a built map (read-only), the
world's ``plate_history.yaml`` sutures and the continental rifts, prints the
blocks and welds, reports the weld groups (the continental plates) at a few
epochs, and checks that a snapshot driven by the blocks with the present poles
reproduces the M1 fixed-pole rewind.  With ``--plot`` it maps the weld groups at
each epoch on present coordinates (``blocks.png``).

Usage::

    uv run python scripts/geology/paleo_blocks.py data/worlds/nacrea/maps/satellite_nacrea \\
        --out-dir /tmp/blocks --plot
"""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
from paleo_rewind import World

from dreamulator.map.paleo_blocks import block_snapshot, build_blocks, finite_rotations
from dreamulator.map.paleo_kinematics import (
    boundary_cells,
    continental_speed_poles,
    rewind,
    ridge_half_rates,
    rotation_matrices,
    synthesize_seafloor_age,
)
from dreamulator.map.paleo_sutures import load_sutures
from dreamulator.map.paleo_walk import continental_rifts


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("map_dir", type=Path)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--epochs", type=float, nargs="+", default=[0, 10, 40, 80, 120, 160])
    ap.add_argument("--plate-history", type=Path, default=None)
    ap.add_argument("--rift-cap-km", type=float, default=300.0)
    ap.add_argument("--plot", action="store_true")
    args = ap.parse_args()

    w = World(args.map_dir)
    kin = replace(w.kin, omega=continental_speed_poles(w.kin))
    hist = args.plate_history or (
        args.map_dir.resolve().parents[1] / "layers" / "geological" / "input" / "plate_history.yaml"
    )
    sutures = load_sutures(hist)
    _, onsets = continental_rifts(kin, args.rift_cap_km)
    blocks = build_blocks(kin, sutures, onsets)
    a = kin.area_km2
    rows = []
    for b in range(blocks.n):
        sel = blocks.block == b
        rows.append(
            {"block": b, "name": blocks.names[b], "Mkm2": round(float(a[sel].sum() / 1e6), 2)}
        )
    summary: dict = {
        "blocks": rows,
        "welds": [
            {"a": wd.a, "b": wd.b, "kind": wd.kind, "until": wd.until_myr, "since": wd.since_myr}
            for wd in blocks.welds
        ],
        "groups": [],
    }
    for t in args.epochs:
        g = blocks.groups(t)
        cont_by_group = {
            int(x): round(float(a[np.isin(blocks.block, np.flatnonzero(g == x))].sum() / 1e6), 1)
            for x in np.unique(g)
        }
        largest = max(cont_by_group.values())
        summary["groups"].append(
            {"t_myr": t, "n_groups": len(cont_by_group), "largest_Mkm2": largest}
        )
        print(f"t={t:g} Myr: {len(cont_by_group)} continental groups, largest {largest} Mkm²")

    # regression: blocks driven by the present poles reproduce the M1 rewind
    half, offset = ridge_half_rates(kin, boundary_cells(kin))
    age, _ = synthesize_seafloor_age(kin, half, offset)
    t = 20.0
    stage = np.repeat(kin.omega[blocks.plate][None], 4, axis=0)
    snap = block_snapshot(
        kin, age, blocks, finite_rotations(stage, 5.0, t), rotation_matrices(kin.omega, -t * 1e6), t
    )
    m1 = rewind(kin, age, t)
    agree = float(np.mean(snap.src == m1.src))
    summary["regression_m1_agreement_20myr"] = round(agree, 6)
    print(f"block snapshot vs M1 rewind at {t:g} Myr: {agree:.4%} of cells identical")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(rows, ensure_ascii=False))
    if args.plot:
        import colorsys

        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        pal = np.array([colorsys.hls_to_rgb((i * 0.618034) % 1.0, 0.5, 0.65) for i in range(64)])
        n = len(args.epochs)
        fig, axes = plt.subplots((n + 1) // 2, 2, figsize=(18, 4.6 * ((n + 1) // 2)), squeeze=False)
        for ax, t in zip(axes.ravel(), args.epochs, strict=False):
            g = blocks.groups(t)
            cont = blocks.block >= 0
            col = np.full((kin.n, 3), 0.88)
            col[cont] = pal[g[blocks.block[cont]] % len(pal)]
            ax.scatter(w.lon, w.lat, s=1.5, c=col, lw=0, marker="h", rasterized=True)
            ax.set(xlim=(-180, 180), ylim=(-90, 90), aspect="equal", xticks=[], yticks=[])
            ax.set_title(
                f"weld groups at −{t:g} Myr ({len(np.unique(g))} groups), present coordinates"
            )
        for ax in axes.ravel()[n:]:
            ax.axis("off")
        fig.tight_layout()
        fig.savefig(args.out_dir / "blocks.png", dpi=110)


if __name__ == "__main__":
    main()
