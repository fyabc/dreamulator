"""Compare two-ring terrain and crossing constraints in the held river window."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from time import perf_counter

import numpy as np
from numba import njit
from PIL import Image

from scripts.media.bounded_river_lines import smooth_line
from scripts.media.compare_bounded_river_lines import shared_junctions
from scripts.media.compare_d8_bounded_lines import raw_d8_path
from scripts.media.compare_dinf_routing import frame
from scripts.media.compare_river_window_algorithms import clip, rc_segments
from scripts.media.constrained_receiver_local import (
    accumulate,
    candidates,
    clear_descent,
    crosses,
    prune_crossings,
)
from scripts.media.dinf_original import prepare
from scripts.media.extended_receiver_local import receivers


@njit(cache=True)
def audit_extensions(height: np.ndarray, stop: np.ndarray, receiver: np.ndarray):
    nc = height.shape[1]
    extensions, invalid, crossings = 0, 0, 0
    for cell, target in enumerate(receiver):
        if target < 0:
            continue
        r, c = divmod(cell, nc)
        tr, tc = divmod(target, nc)
        if max(abs(r - tr), abs(c - tc)) <= 1:
            continue
        extensions += 1
        if not clear_descent(height, stop, r, c, tr - r, tc - c):
            invalid += 1
        for rr in range(max(0, r - 4), min(height.shape[0], r + 5)):
            for cc in range(max(0, c - 4), min(nc, c + 5)):
                other = rr * nc + cc
                down = receiver[other]
                if other == cell or down < 0:
                    continue
                dr, dc = divmod(down, nc)
                other_long = max(abs(rr - dr), abs(cc - dc)) > 1
                if other_long and other < cell:
                    continue
                if crosses(cell, target, other, down, nc):
                    crossings += 1
    return extensions, invalid, crossings


def graph_report(prepared, receiver, source):
    units = (~prepared.absorbing).astype(float)
    total = accumulate(receiver, units)
    selected = accumulate(receiver, source)
    sinks = receiver < 0
    active = ~sinks
    src = np.flatnonzero(active)
    target = receiver[active]
    height = prepared.height_m.ravel()
    assert (height[src] >= height[target]).all()
    unexplained = int((sinks & ~prepared.absorbing.ravel()).sum())
    full_residual = abs(total.ravel()[sinks].sum() - units.sum()) / units.sum()
    selected_residual = abs(selected.ravel()[sinks].sum() - source.sum()) / source.sum()
    assert unexplained == 0 and max(full_residual, selected_residual) <= 1e-12
    base = prepared.d8_receiver.ravel()
    flat = (base >= 0) & (height == height[np.maximum(base, 0)])
    assert (receiver[flat] == base[flat]).all()
    return {
        "unexplained_sinks": unexplained,
        "unit_source_budget_residual": float(full_residual),
        "held_source_budget_residual": float(selected_residual),
        "flat_receivers_unchanged": True,
        "cyclic_nodes": 0,
        "skipped_cells": "Each cell injects once; all its inflow follows its one receiver.",
    }


def window_crossings(segments: np.ndarray) -> list[list[float]]:
    """Independently solve line intersections in the exported display geometry."""
    hits = []
    for i, (a, b) in enumerate(segments):
        for c, d in segments[i + 1 :]:
            if np.any(np.maximum(a, b) < np.minimum(c, d)) or np.any(
                np.maximum(c, d) < np.minimum(a, b)
            ):
                continue
            matrix = np.column_stack((b - a, c - d))
            if abs(np.linalg.det(matrix)) < 1e-10:
                continue
            t, u = np.linalg.solve(matrix, c - a)
            if 1e-8 < t < 1 - 1e-8 and 1e-8 < u < 1 - 1e-8:
                hits.append((a + t * (b - a)).tolist())
    return hits


def main() -> None:
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    held = json.loads((args.previous / "summary.json").read_text(encoding="utf-8"))
    hpath = args.pack / "refined-out/height.pre-equilibrium.npy"
    assert hashlib.sha256(hpath.read_bytes()).hexdigest() == held["height_sha256"]
    height = np.load(hpath)
    land = np.asarray(Image.open(args.pack / "refined-out/land.png")) > 0
    lake = np.asarray(Image.open(args.pack / "refined-out/lake.png")) > 0
    stop = frame(height.shape) | ~land | lake
    prepared = prepare(height, stop)
    bounds, spacing = held["bounds_col_row_px"], held["spacing_m"] / 1000
    seeds = [tuple(seed) for seed in held["seeds_rc"]]
    source = np.zeros(height.shape)
    for seed in seeds:
        source[seed] = 1
    report = {
        "height_sha256": held["height_sha256"],
        "bounds_col_row_px": bounds,
        "spacing_m": spacing * 1000,
        "held_sources": len(seeds),
        "variants": {},
        "scope": "Research only. Single-receiver budgets do not validate all erosion uses.",
    }
    base = prepared.d8_receiver.ravel()
    start = perf_counter()
    proposed = candidates(prepared.height_m, stop, base)
    candidate_time = perf_counter() - start
    start = perf_counter()
    order = np.argsort(-prepared.height_m.ravel(), kind="stable")
    strict, rejected = prune_crossings(base, proposed, order, height.shape[1])
    crossing_time = perf_counter() - start
    print(
        f"Crossing constraint rejected {rejected} of {(proposed != base).sum()} extensions",
        flush=True,
    )
    report["candidate_solve_s"] = candidate_time
    report["crossing_solve_s"] = crossing_time
    groups, titles = {}, {}
    for key in ("baseline", "d8_simple", "triangular", "triangular_smooth"):
        groups[key] = np.load(args.previous / f"{key}.window-rc.line.npy")
    titles.update(
        baseline="Existing production D8",
        d8_simple="Production D8 + bounded smoothing",
        triangular="Triangular held-source traces",
        triangular_smooth="Triangular + bounded smoothing",
    )
    for key, rec, title in (
        ("endpoint", receivers(prepared.height_m, stop, base, 2), "2-ring endpoint slope only"),
        ("terrain", proposed, "2-ring terrain + water constraints"),
        ("constrained", strict, "2-ring terrain + water + crossing constraints"),
    ):
        if key != "endpoint":
            info = graph_report(prepared, rec, source)
        else:
            info = {"unconstrained_control": True}
        extensions, invalid, intersections = audit_extensions(prepared.height_m, stop, rec)
        info.update(
            extended_receivers=int(extensions),
            invalid_terrain_or_water_extensions=int(invalid),
            unjoined_crossing_pairs_involving_extensions=int(intersections),
        )
        if key != "endpoint":
            assert invalid == 0
        if key == "constrained":
            assert intersections == 0
            info["crossing_rejected_extensions"] = int(rejected)
        paths = [raw_d8_path(rec, stop, seed) for seed in seeds]
        info["absorbed_paths"] = len(paths)
        groups[key] = clip(rc_segments(paths, height.shape[0], spacing), bounds)
        titles[key] = title
        report["variants"][key] = info
        np.save(args.out / f"{key}.receiver.npy", rec)
        if key == "constrained":
            anchors = shared_junctions(paths)
            smoothed = [
                smooth_line(path, sample_spacing=2, anchors=a).points
                for path, a in zip(paths, anchors, strict=True)
            ]
            groups["constrained_smooth"] = clip(
                rc_segments(smoothed, height.shape[0], spacing), bounds
            )
            titles["constrained_smooth"] = "Constrained 2-ring + bounded smoothing"
        print(key, info, flush=True)
    keys = [
        "baseline",
        "d8_simple",
        "endpoint",
        "terrain",
        "constrained",
        "constrained_smooth",
        "triangular",
        "triangular_smooth",
    ]
    fig, axes = plt.subplots(2, 4, figsize=(20, 10), sharex=True, sharey=True)
    from scripts.media.diagnose_river_directions import DirectionStats

    intersections = {
        key: window_crossings(groups[key])
        for key in ("terrain", "constrained", "constrained_smooth")
    }
    assert not intersections["constrained"]
    for key, points in intersections.items():
        report["variants"].setdefault(key, {}).update(
            display_unjoined_crossings=len(points), crossing_points_rc=points
        )
    report["variants"]["constrained"]["acceptance"] = (
        "Routing checks passed; author visual acceptance pending."
    )
    report["variants"]["constrained_smooth"]["acceptance"] = (
        "Rejected: independent smoothing creates unjoined display crossings."
        if intersections["constrained_smooth"]
        else "Display crossing check passed."
    )
    if intersections["constrained_smooth"]:
        titles["constrained_smooth"] = "Constrained + smoothing: REJECTED (red crosses)"

    def draw(ax, key):
        ax.imshow(height, cmap="gray")
        ax.add_collection(LineCollection(groups[key][:, :, ::-1], colors="#1684dc", linewidths=0.9))
        ax.set_xlim(*bounds[:2])
        ax.set_ylim(bounds[3], bounds[2])
        ax.set_title(titles[key], fontsize=10)
        if key == "constrained_smooth" and intersections[key]:
            points = np.array(intersections[key])
            ax.scatter(points[:, 1], points[:, 0], c="#ff684a", marker="x", s=28)

    for ax, key in zip(axes.flat, keys, strict=True):
        draw(ax, key)
        single, sub = plt.subplots(figsize=(6, 6))
        draw(sub, key)
        single.tight_layout()
        single.savefig(args.out / f"{key}.png", dpi=180)
        plt.close(single)
        segments = groups[key]
        stats = DirectionStats()
        stats.add((segments[:, 1] - segments[:, 0])[:, ::-1] * [spacing, -spacing])
        report["variants"].setdefault(key, {})["window_direction_stats"] = stats.report()
        np.save(args.out / f"{key}.window-rc.line.npy", segments)
    fig.suptitle(
        f"Fixed reported window; {spacing * 1000:.2f} m/pixel; {len(seeds)} held sources",
        fontsize=14,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    fig.savefig(args.out / "comparison.png", dpi=180)
    plt.close(fig)
    accepted, axes = plt.subplots(1, 3, figsize=(15, 5), sharex=True, sharey=True)
    for ax, key in zip(axes, ("baseline", "d8_simple", "constrained"), strict=True):
        draw(ax, key)
    accepted.tight_layout()
    accepted.savefig(args.out / "acceptance.png", dpi=180)
    plt.close(accepted)
    (args.out / "summary.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
