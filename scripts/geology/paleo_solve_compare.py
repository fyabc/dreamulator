#!/usr/bin/env python3
"""Compare weight-sensitivity runs of ``paleo_solve.py`` with a baseline run.

For every run directory (``summary.json`` + ``solve.npz``) reports the mean
continental RMS speed in the supercontinent and dispersal eras, the deepest
penetration and the mean overlap share, the number of block-pole
reorganisations, and the area-weighted angular distance of every continental
block from its baseline position at a few epochs.  A conclusion that only holds
under one set of weights is not a conclusion (§4.3).

Usage::

    uv run python scripts/geology/paleo_solve_compare.py data/worlds/nacrea/maps/satellite_nacrea \\
        BASE_DIR RUN_DIR [RUN_DIR ...]
"""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
from paleo_rewind import World

from dreamulator.map.paleo_blocks import build_blocks, finite_rotations
from dreamulator.map.paleo_kinematics import continental_speed_poles
from dreamulator.map.paleo_sutures import load_sutures
from dreamulator.map.paleo_walk import continental_rifts

EPOCHS = (30.0, 60.0, 100.0, 150.0)
# a block's pole change between stages above this share of the reference speed
# counts as a reorganisation (reporting threshold only)
REORG_FRAC = 0.2


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("map_dir", type=Path)
    ap.add_argument("base", type=Path)
    ap.add_argument("runs", type=Path, nargs="+")
    args = ap.parse_args()

    w = World(args.map_dir)
    kin = replace(w.kin, omega=continental_speed_poles(w.kin))
    hist = args.map_dir.resolve().parents[1] / "layers" / "geological" / "input"
    _, onsets = continental_rifts(kin, 300.0)
    blocks = build_blocks(kin, load_sutures(hist / "plate_history.yaml"), onsets)
    cont = blocks.block >= 0
    barea = np.bincount(blocks.block[cont], weights=kin.area_km2[cont], minlength=blocks.n)
    centre = np.zeros((blocks.n, 3))
    np.add.at(centre, blocks.block[cont], kin.xyz[cont] * kin.area_km2[cont, None])
    centre /= np.linalg.norm(centre, axis=1, keepdims=True)

    def load(d: Path) -> tuple[dict, np.ndarray]:
        s = json.loads((d / "summary.json").read_text(encoding="utf-8"))
        return s, np.load(d / "solve.npz")["stage_omega"]

    base_s, base_om = load(args.base)
    stage = base_s["config"]["stage_myr"]

    def row(d: Path) -> dict:
        s, om = load(d)
        st = s["stages"]
        t = np.array([x["t_myr"] for x in st])
        v = np.array([x["continental_rms_cm_yr"] for x in st])
        ref = np.average(np.linalg.norm(om[0], axis=1), weights=barea)
        dpole = np.linalg.norm(np.diff(om, axis=0), axis=2) / ref
        out = {
            "run": d.name,
            "v_45_100": round(float(v[(t >= 45) & (t <= 100)].mean()), 2),
            "v_105_150": round(float(v[t >= 105].mean()), 2),
            "worst_depth_km": round(max(x["worst_depth_km"] for x in st[1:]), 0),
            "iso_misfit_km": round(float(np.median([x["isochron_misfit_km"] for x in st])), 0),
            "mean_overlap_share": round(float(np.mean([x["overlap_area_share"] for x in st])), 4),
            "reorgs": int((dpole > REORG_FRAC).any(axis=1).sum()),
            "groups_150": st[-1]["n"],
        }
        for e in EPOCHS:
            if e > t.max():
                continue
            a = finite_rotations(om, stage, e) @ centre[:, :, None]
            b = finite_rotations(base_om, stage, e) @ centre[:, :, None]
            ang = np.degrees(np.arccos(np.clip(np.sum(a[..., 0] * b[..., 0], axis=1), -1, 1)))
            out[f"shift_{e:g}_deg"] = round(float(np.average(ang, weights=barea)), 1)
        return out

    rows = [row(args.base)] + [row(d) for d in args.runs]
    keys = list(rows[0])
    print("  ".join(f"{k:>18s}" for k in keys))
    for r in rows:
        print("  ".join(f"{r[k]!s:>18s}" for k in keys))
    out = args.base.parent / "sensitivity.json"
    out.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
