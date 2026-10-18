#!/usr/bin/env python3
"""Plate topology layer T1 diagnostic: extract, smooth, move and rasterize the
boundary graph with fixed Euler poles.

Reads a built map (read-only), builds the reconstruction plate model
(``paleo_kinematics.reconstruction_plates``), extracts its boundary graph
(``dreamulator.map.paleo_topology``), and walks it back with the present poles.
At each epoch it rasterizes the graph to cells and reports:

* the topology rules of ``docs/design/proposals/plate-topology.md`` §5;
* agreement with the starting labels at t = 0 (smoothing moves boundaries a
  little);
* agreement with the M1 parcel rewind (``paleo_kinematics.rewind``, same poles):
  the share of continental cells whose plate in the rewind equals the plate of
  the rasterized graph.

Outputs ``summary.json`` and, with ``--plot``, ``topology.png`` into ``--out-dir``.

Usage::

    uv run python scripts/geology/plate_topology.py \\
        data/worlds/nacrea/maps/satellite_nacrea --out-dir /tmp/topo --plot
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import numpy as np
from paleo_rewind import World
from scipy.spatial import cKDTree

from dreamulator.map import paleo_topology as pt
from dreamulator.map.paleo_kinematics import (
    boundary_cells,
    continental_speed_poles,
    reconstruction_plates,
    rewind,
    ridge_half_rates,
    synthesize_seafloor_age,
)

KIND_COLOUR = {pt.RIDGE: "tab:red", pt.TRENCH: "tab:blue", pt.TRANSFORM: "tab:green"}


def lonlat(p: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    lat = np.degrees(np.arcsin(np.clip(p[:, 1], -1, 1)))
    lon = np.degrees(np.arctan2(p[:, 2], p[:, 0]))
    return lon, lat


def plot(
    w: World, frames: list[tuple[float, np.ndarray, pt.Topology, np.ndarray]], out: Path
) -> None:
    import colorsys

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    pal = np.array([colorsys.hls_to_rgb((i * 0.618034) % 1.0, 0.5, 0.7) for i in range(64)])
    ncol = 2
    nrow = (len(frames) + 1) // ncol
    fig, axes = plt.subplots(nrow, ncol, figsize=(16, 4.3 * nrow), squeeze=False)
    for ax, (t, lab, topo, cont) in zip(axes.ravel(), frames, strict=False):
        col = pal[lab % len(pal)]
        col = np.where(cont[:, None], col * 0.8, 0.45 * col + 0.55)
        ax.scatter(w.lon, w.lat, s=1.6, c=col, lw=0, marker="h", rasterized=True)
        for seg in topo.segments:
            lon, lat = lonlat(seg.points)
            jumps = np.flatnonzero(np.abs(np.diff(lon)) > 180) + 1
            for part_lon, part_lat in zip(np.split(lon, jumps), np.split(lat, jumps), strict=True):
                ax.plot(part_lon, part_lat, color=KIND_COLOUR.get(seg.kind, "k"), lw=1.2)
        if len(topo.nodes):
            nlon, nlat = lonlat(topo.nodes)
            ax.scatter(nlon, nlat, s=10, c="k", zorder=5)
        ax.set(xlim=(-180, 180), ylim=(-90, 90), aspect="equal", xticks=[], yticks=[])
        ax.set_title(
            f"−{t:g} Myr (red ridge, blue trench, green transform, dots junctions)", fontsize=9
        )
    for ax in axes.ravel()[len(frames) :]:
        ax.axis("off")
    fig.tight_layout()
    fig.savefig(out / "topology.png", dpi=130)
    plt.close(fig)


def walk(
    args: argparse.Namespace,
    w: World,
    kin: Any,
    topo: pt.Topology,
    age: np.ndarray,
    side_info: Any,
    summary: dict[str, Any],
) -> None:
    """T2: parcels walked on the boundary graph (``paleo_walk``)."""
    from paleo_rewind import ocean_params

    from dreamulator.map.paleo_history import OceanDepth, active_orogens, rift_onsets
    from dreamulator.map.paleo_kinematics import boundary_opening_rates
    from dreamulator.map.paleo_walk import (
        WalkConfig,
        crust_thickness_km,
        inactive_sutures,
        run_topology_walk,
    )

    opening, _ = boundary_opening_rates(kin, boundary_cells(kin))
    orogens = active_orogens(kin, w.elevation, opening, w.cumulative_convergence_km)
    rifts = rift_onsets(kin, w.divergent, w.cumulative_divergence_km)
    sutures = inactive_sutures(kin, w.elevation, orogens) if args.sutures else []
    summary["sutures"] = [
        {"age_myr": round(s.age_myr, 2), "cells": int(s.cells.size)} for s in sutures
    ]
    cfg = WalkConfig(
        dt_myr=args.dt_myr,
        rift_cap_km=args.rift_cap_km,
        event_grid=args.event_grid,
        reorg_interval_myr=(args.reorg_min_myr, args.reorg_max_myr),
        contact_onsets=args.contact_onsets,
        max_step_spacings=args.max_step_spacings,
        seed=args.seed,
    )
    snaps, log = run_topology_walk(
        kin,
        topo,
        age,
        w.elevation,
        orogens,
        OceanDepth(**ocean_params(args.map_dir, None)),
        list(args.epochs),
        cfg,
        side_info,
        rifts,
        sutures,
    )
    a = kin.area_km2
    cont0 = a[kin.continental].sum()
    thick0 = np.where(kin.continental, crust_thickness_km(w.elevation), 0.0)
    frames = []
    for s in snaps:
        chk = pt.check(kin, s.plate)
        empty: dict[str, Any] = {}
        step: dict[str, Any] = next(
            (x for x in log.steps if abs(float(str(x["t_myr"])) - s.t_myr) < 1e-9), empty
        )
        entry: dict[str, Any] = {
            "t_myr": s.t_myr,
            **asdict(chk),
            "continental_area_ratio": round(float(a[s.continental].sum() / cont0), 4),
            "synthetic_frac": round(float(a[s.synthetic].sum() / a.sum()), 4),
            "land_frac": round(float(a[s.elevation_m > 0].sum() / a.sum()), 4),
            "volume_visible_ratio": round(
                float((a * s.thickness_km).sum() / (a * thick0).sum()), 4
            ),
            **{
                k: step[k]
                for k in (
                    "continental_parcels_ratio",
                    "continental_overlap_km2",
                    "volume_parcels_ratio",
                    "volume_hidden_ratio",
                )
                if k in step
            },
        }
        summary["epochs"].append(entry)
        frames.append((s.t_myr, s.plate, s.topology, s.continental))
        print(json.dumps(entry, ensure_ascii=False))
    if args.save_snapshots:
        np.savez_compressed(
            args.out_dir / "snapshots.npz",
            t_myr=np.array([s.t_myr for s in snaps]),
            plate=np.stack([s.plate for s in snaps]),
            continental=np.stack([s.continental for s in snaps]),
            thickness_km=np.stack([s.thickness_km for s in snaps]),
            elevation_m=np.stack([s.elevation_m for s in snaps]),
        )
    summary["young_rifts"] = len(rifts)
    summary["collision_events"] = log.collisions
    summary["merges"] = log.merges
    summary["reorganizations"] = log.reorganizations
    summary["splits"] = log.splits
    summary["refused_jumps"] = log.refused_jumps
    summary["steps"] = log.steps
    restored = float(str(log.steps[-1]["unstretched_km3"])) if log.steps else 0.0
    summary["unstretched_km3"] = round(restored)
    print(
        json.dumps(
            {
                "collision_events": len(log.collisions),
                "reorganizations": log.reorganizations,
                "splits": log.splits,
                "unstretched_Mkm3": round(restored / 1e6, 2),
            }
        )
    )
    (args.out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    if args.plot:
        plot(w, frames, args.out_dir)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("map_dir", type=Path)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--epochs", type=float, nargs="+", default=[0.0, 5.0, 10.0, 20.0])
    ap.add_argument("--dt-myr", type=float, default=1.0)
    ap.add_argument("--smooth", type=int, default=8)
    ap.add_argument(
        "--walk",
        action="store_true",
        help="T2: walk crust parcels on the topology (reconcile, gaps, young rifts)",
    )
    ap.add_argument("--rift-cap-km", type=float, default=300.0)
    ap.add_argument(
        "--reorg-min-myr",
        type=float,
        default=10.0,
        help="plate reorganizations are drawn every reorg-min to reorg-max Myr "
        "(a huge value keeps the present poles)",
    )
    ap.add_argument("--reorg-max-myr", type=float, default=40.0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument(
        "--max-step-spacings",
        type=float,
        default=0.5,
        help="a step is no longer than the fastest plate needs to move this many spacings",
    )
    ap.add_argument(
        "--contact-onsets",
        action="store_true",
        help="set a pair's rift onset when its continents close up to the pre-rift fit",
    )
    ap.add_argument(
        "--event-grid",
        type=int,
        default=200_000,
        help="points of the fixed sampling sphere for boundary-collision events (0 = off)",
    )
    ap.add_argument(
        "--plates",
        choices=("blocks", "engine"),
        default="engine",
        help="blocks: reconstruction model (rigid continental blocks); engine: the terrain "
        "engine's own plates and poles from plates.json",
    )
    ap.add_argument(
        "--start",
        choices=("smoothed", "engine"),
        default="engine",
        help="engine: t = 0 uses the terrain engine's boundary geometry unsmoothed and its "
        "per-cell boundary types (aligned with the present orogens and rifts)",
    )
    ap.add_argument("--plot", action="store_true")
    ap.add_argument(
        "--speed-scale",
        type=float,
        default=1.0,
        help="multiply every Euler pole rate (scale-invariance check: the walk at scale k "
        "and time t/k should match scale 1 at time t)",
    )
    ap.add_argument("--save-snapshots", action="store_true", help="write snapshots.npz")
    ap.add_argument(
        "--no-sutures",
        dest="sutures",
        action="store_false",
        help="do not split plates along inactive orogenic belts at their collision ages",
    )
    ap.add_argument(
        "--initial-speeds",
        choices=("continental", "engine"),
        default="continental",
        help="continental: present pole speeds set by each plate's continental share "
        "(axes kept, oceanic RMS speed kept); engine: plates.json as is (legacy nacrea)",
    )
    args = ap.parse_args()

    w = World(args.map_dir)
    if args.plates == "engine":
        kin = w.kin  # the terrain engine's own plates and Euler poles (plates.json)
    else:
        rp = reconstruction_plates(w.kin, w.convergent)
        kin = replace(w.kin, plate=rp.plate, omega=rp.omega)
    if args.initial_speeds == "continental":
        kin = replace(kin, omega=continental_speed_poles(kin))
    if args.speed_scale != 1.0:
        kin = replace(kin, omega=kin.omega * args.speed_scale)
    half, offset = ridge_half_rates(kin, boundary_cells(kin))
    age, _ = synthesize_seafloor_age(kin, half, offset)
    spacing_rad = kin.spacing_km / kin.radius_km

    start_label = pt.clean_labels(kin, kin.plate)
    smooth_iter = 0 if args.start == "engine" else args.smooth
    topo = pt.prepare(pt.extract(kin.xyz, start_label), 0.5 * spacing_rad, smooth_iter)
    side_info = (kin.xyz, kin.continental, age, cKDTree(kin.xyz))
    engine_typed = 0
    if args.start == "engine":
        engine_typed = pt.classify_from_cells(
            topo, kin.xyz, w.boundary_type, side_info, (kin.omega, kin.radius_km)
        )
    else:
        pt.classify(topo, kin.omega, kin.radius_km, side_info)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    kinds: dict[str, int] = {}
    for seg in topo.segments:
        kinds[seg.kind] = kinds.get(seg.kind, 0) + 1
    summary: dict[str, Any] = {
        "map_dir": str(args.map_dir),
        "nodes": int(len(topo.nodes)),
        "segments": len(topo.segments),
        "segment_kinds": kinds,
        "loops": sum(1 for s in topo.segments if s.start < 0),
        "start": args.start,
        "plates": args.plates,
        "segments_typed_by_engine": engine_typed,
        "epochs": [],
    }
    cont_idx = np.flatnonzero(kin.continental)

    def continental_positions(k: Any, label: np.ndarray, tt: float) -> np.ndarray:
        from dreamulator.map.paleo_kinematics import rotation_matrices

        rot = rotation_matrices(k.omega, -tt * 1.0e6)
        out: np.ndarray = np.einsum("nij,nj->ni", rot[label[cont_idx]], k.xyz[cont_idx])
        return out

    if args.walk:
        walk(args, w, kin, topo, age, side_info, summary)
        return

    grid = pt.event_grid(args.event_grid, kin.radius_km) if args.event_grid > 0 else None
    events: list[dict[str, Any]] = []
    frames = []
    t = 0.0
    a = kin.area_km2
    for target in sorted(args.epochs):
        while t < target - 1e-9:
            dt = min(args.dt_myr, target - t)
            # continental crust at time t: present continental cells rotated back
            # with their plates (fixed poles in T1)
            cpos = continental_positions(kin, start_label, t)
            topo = pt.step(
                topo, kin.omega, dt, 0.5 * spacing_rad, (cpos, start_label[cont_idx], cKDTree(cpos))
            )
            t += dt
            if grid is not None:
                hits = pt.find_crossings(topo, 2.0 * spacing_rad)
                if hits:
                    topo, stats = pt.reclose(
                        topo, grid, spacing_rad, side_info, kin.omega, kin.radius_km
                    )
                    events.append({"t_myr": round(t, 3), "crossings": len(hits), **stats})
        lab = pt.rasterize(topo, kin, spacing_rad / 3.0)
        chk = pt.check(kin, lab)
        entry: dict[str, Any] = {"t_myr": t, **asdict(chk)}
        if t == 0.0:
            entry["agreement_with_start"] = round(float(a[lab == start_label].sum() / a.sum()), 4)
        st = rewind(replace(kin, plate=start_label), age, t)
        ok = (st.src >= 0) & kin.continental[np.maximum(st.src, 0)]
        m1_plate = start_label[np.maximum(st.src, 0)]
        entry["continental_agreement_with_m1"] = round(
            float(a[ok & (m1_plate == lab)].sum() / a[ok].sum()), 4
        )
        summary["epochs"].append(entry)
        cont_now = np.zeros(kin.n, dtype=bool)  # continents moved back (M1 parcels)
        cont_now[ok] = True
        frames.append((t, lab, topo, cont_now))
        print(json.dumps(entry, ensure_ascii=False))
    summary["collision_events"] = events
    print(json.dumps({"collision_events": len(events)}, ensure_ascii=False))
    (args.out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in summary.items() if k != "epochs"}, ensure_ascii=False))
    if args.plot:
        plot(w, frames, args.out_dir)


if __name__ == "__main__":
    main()
