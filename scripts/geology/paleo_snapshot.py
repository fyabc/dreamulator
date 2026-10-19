#!/usr/bin/env python3
"""Geological timeline §4.6/§4.8: snapshots from a solve of ``paleo_solve.py``.

Reads a solve directory (``summary.json`` + ``solve.npz``) and the built map it
was solved on (read-only), and at each epoch derives the snapshot of
``map/paleo_snapshot.py``: plates, typed boundaries, crust, seafloor age,
elevation with orogens rolled back, and the land mask.  Writes
``snapshots.json`` (per epoch: topology check, boundary lengths by type, land
and continental fractions, filled-in and overlapping shares), one
``snapshot_<t>.npz`` per epoch, and with ``--plot`` ``snapshot_plates.png`` and
``snapshot_elevation.png``.

Usage::

    uv run python scripts/geology/paleo_snapshot.py data/worlds/nacrea/maps/satellite_nacrea \\
        --solve-dir /tmp/solve --out-dir /tmp/snap --plot
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
from paleo_rewind import World, ocean_params

from dreamulator.map.paleo_blocks import build_blocks
from dreamulator.map.paleo_history import active_orogens
from dreamulator.map.paleo_kinematics import (
    boundary_cells,
    boundary_opening_rates,
    continental_speed_poles,
    no_net_rotation,
    ridge_half_rates,
    synthesize_seafloor_age,
)
from dreamulator.map.paleo_snapshot import DepthLaw, snapshot
from dreamulator.map.paleo_solver import SolverConfig, build_setup, seafloor_welds
from dreamulator.map.paleo_sutures import load_sutures
from dreamulator.map.paleo_walk import continental_rifts


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("map_dir", type=Path)
    ap.add_argument("--solve-dir", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--epochs", type=float, nargs="+", default=[0, 10, 30, 60, 90, 120, 150])
    ap.add_argument("--sea-level-m", type=float, default=0.0)
    ap.add_argument("--plate-history", type=Path, default=None)
    ap.add_argument("--plot", action="store_true")
    args = ap.parse_args()

    summary = json.loads((args.solve_dir / "summary.json").read_text(encoding="utf-8"))
    config = SolverConfig(**summary["config"])
    solved = np.load(args.solve_dir / "solve.npz")
    w = World(args.map_dir)
    # absolute speeds refer to the no-net-rotation frame (PB2002 holds the Pacific fixed)
    w.kin = replace(w.kin, omega=no_net_rotation(w.kin))
    kin = replace(w.kin, omega=continental_speed_poles(w.kin))
    hist = args.plate_history or (
        args.map_dir.resolve().parents[1] / "layers" / "geological" / "input" / "plate_history.yaml"
    )
    _, onsets = continental_rifts(kin, 300.0)
    blocks = build_blocks(kin, load_sutures(hist), onsets)
    half, offset = ridge_half_rates(w.kin, boundary_cells(w.kin))
    age, source = synthesize_seafloor_age(w.kin, half, offset)
    setup = build_setup(kin, blocks, w.kin.omega, kin.omega, age, source, half, config)
    blocks, _ = seafloor_welds(blocks, setup)
    opening, _ = boundary_opening_rates(w.kin, boundary_cells(w.kin))
    orogens = active_orogens(w.kin, w.elevation, opening, w.cumulative_convergence_km)
    params = ocean_params(args.map_dir, None)
    depth = DepthLaw(params["ridge_depth_m"], params["subsidence_coeff"], params["max_depth_m"])

    a = kin.area_km2
    total = float(a.sum())
    rows = []
    snaps = []
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for t in args.epochs:
        snap = snapshot(
            w.kin,
            blocks,
            age,
            solved["stage_omega"],
            solved["groups"],
            config.stage_myr,
            t,
            w.kin.omega,
            w.elevation,
            depth,
            orogens,
            args.sea_level_m,
        )
        snaps.append(snap)
        lengths: dict[str, float] = {}
        for seg in snap.topology.segments:
            d = np.arccos(np.clip(np.sum(seg.points[1:] * seg.points[:-1], axis=1), -1, 1))
            lengths[seg.kind] = lengths.get(seg.kind, 0.0) + float(d.sum()) * kin.radius_km
        row = {
            "t_myr": t,
            "check": asdict(snap.check),
            "boundary_km": {k: round(v) for k, v in sorted(lengths.items())},
            "land_frac": round(float(a[snap.land].sum() / total), 4),
            "continental_frac": round(float(a[snap.continental].sum() / total), 4),
            "filled_in_frac": round(float(a[snap.src < 0].sum() / total), 4),
            "overlap_frac": round(float(a[snap.overlap].sum() / total), 4),
            "seafloor_age_p50_myr": round(float(np.nanmedian(snap.age_myr)), 1),
        }
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False))
        np.savez_compressed(
            args.out_dir / f"snapshot_{t:g}.npz",
            label=snap.label,
            continental=snap.continental,
            age_myr=snap.age_myr,
            elevation_m=snap.elevation_m,
            land=snap.land,
            src=snap.src,
        )
    (args.out_dir / "snapshots.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    if args.plot:
        _plot(w, snaps, args.out_dir)


def _plot(w: World, snaps: list, out: Path) -> None:  # type: ignore[type-arg]
    import colorsys

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    colours = {"ridge": "red", "trench": "black", "transform": "limegreen", "diffuse": "grey"}
    pal = np.array([colorsys.hls_to_rgb((i * 0.618034) % 1.0, 0.6, 0.55) for i in range(128)])
    n = len(snaps)
    rows = (n + 1) // 2
    for name in ("plates", "elevation"):
        fig, axes = plt.subplots(rows, 2, figsize=(18, 4.6 * rows), squeeze=False)
        for ax, snap in zip(axes.ravel(), snaps, strict=False):
            if name == "plates":
                col = pal[snap.label % len(pal)].copy()
                col[snap.continental] *= 0.75
                ax.scatter(w.lon, w.lat, s=0.4, c=col, lw=0, rasterized=True)
                for seg in snap.topology.segments:
                    lon = np.degrees(np.arctan2(seg.points[:, 2], seg.points[:, 0]))
                    lat = np.degrees(np.arcsin(np.clip(seg.points[:, 1], -1, 1)))
                    cut = np.flatnonzero(np.abs(np.diff(lon)) > 180) + 1
                    for lo, la in zip(np.split(lon, cut), np.split(lat, cut), strict=True):
                        ax.plot(lo, la, color=colours.get(seg.kind, "grey"), lw=0.9)
                title = (
                    f"−{snap.t_myr:g} Myr: {snap.check.plates} plates; red ridge,"
                    " black trench, green transform; dark = continental"
                )
            else:
                sc = ax.scatter(
                    w.lon,
                    w.lat,
                    s=0.4,
                    c=snap.elevation_m,
                    cmap="terrain",
                    vmin=-6000,
                    vmax=4000,
                    lw=0,
                    rasterized=True,
                )
                coast = snap.land
                ax.scatter(w.lon[coast], w.lat[coast], s=0.05, c="k", alpha=0.08, lw=0)
                title = f"−{snap.t_myr:g} Myr: elevation (m)"
            ax.set(xlim=(-180, 180), ylim=(-90, 90), aspect="equal", xticks=[], yticks=[])
            ax.set_title(title, fontsize=9)
        for ax in axes.ravel()[n:]:
            ax.axis("off")
        if name == "elevation":
            fig.colorbar(sc, ax=axes.ravel().tolist(), shrink=0.4)
        else:
            fig.tight_layout()
        fig.savefig(out / f"snapshot_{name}.png", dpi=100)
        plt.close(fig)


if __name__ == "__main__":
    main()
