"""Render the exact reported external window with held sources and routing references."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image

from dreamulator.map.prog_erosion import flow_accumulation, priority_flood
from scripts.media.bounded_river_lines import smooth_line
from scripts.media.compare_bounded_river_lines import shared_junctions, stats_for
from scripts.media.compare_d8_bounded_lines import raw_d8_path
from scripts.media.compare_dinf_routing import frame
from scripts.media.continuous_flowline import CubicSurface, trace
from scripts.media.dinf_original import accumulate, prepare, routing
from scripts.media.extended_receiver_local import plane_resolution, receivers
from scripts.media.triangular_flowline import TriangularSurface, trace_triangles


def clip(segments: np.ndarray, bounds: list[float]) -> np.ndarray:
    """Clip row/column segments to the exact requested rectangle."""
    lower = np.array([bounds[2], bounds[0]])
    upper = np.array([bounds[3], bounds[1]])
    start, delta = segments[:, 0], segments[:, 1] - segments[:, 0]
    lo, hi = np.zeros(len(segments)), np.ones(len(segments))
    valid = np.ones(len(segments), dtype=bool)
    for axis in (0, 1):
        moving = abs(delta[:, axis]) > 1e-14
        valid &= moving | ((start[:, axis] >= lower[axis]) & (start[:, axis] <= upper[axis]))
        a = np.full(len(segments), -np.inf)
        b = np.full(len(segments), np.inf)
        np.divide(lower[axis] - start[:, axis], delta[:, axis], out=a, where=moving)
        np.divide(upper[axis] - start[:, axis], delta[:, axis], out=b, where=moving)
        lo = np.maximum(lo, np.minimum(a, b))
        hi = np.minimum(hi, np.maximum(a, b))
    valid &= (hi > lo + 1e-12) & (np.linalg.norm(delta, axis=1) > 1e-12)
    result = np.stack((start + lo[:, None] * delta, start + hi[:, None] * delta), axis=1)[valid]
    # A shared downstream edge is drawn once even when multiple sources use it.
    _, keep = np.unique(np.round(result.reshape(-1, 4), 8), axis=0, return_index=True)
    return result[np.sort(keep)]


def rc_segments(paths: list[np.ndarray], rows: int, spacing: float) -> np.ndarray:
    segs, _ = stats_for(paths, spacing)
    segs /= spacing
    return segs[:, :, ::-1] * [-1, 1] + [rows - 1, 0]


def held_seeds(receiver: np.ndarray, rivers: np.ndarray, bounds: list[float]) -> list[tuple]:
    cells = np.flatnonzero(rivers.ravel())
    down = receiver[cells]
    incoming = np.bincount(down[down >= 0], minlength=rivers.size)
    selected = []
    for cell in cells[incoming[cells] == 0]:
        current = int(cell)
        while current >= 0:
            r, c = divmod(current, rivers.shape[1])
            if bounds[0] <= c <= bounds[1] and bounds[2] <= r <= bounds[3]:
                selected.append(divmod(int(cell), rivers.shape[1]))
                break
            current = int(receiver[current])
    return selected


def ridge_control() -> dict:
    h = np.full((7, 7), 10.0)
    h[3, 3], h[4, 3], h[5, 3], h[6, 3] = 2, 1.9, 1.8, 0
    h[3, 4], h[3, 5], h[3, 6] = 9, 0, 0
    p = prepare(h, frame(h.shape))
    candidate = receivers(p.height_m, p.absorbing, p.d8_receiver, 2)
    target = divmod(int(candidate[3 * 7 + 3]), 7)
    assert target == (3, 5)
    return {
        "source_height_m": float(p.height_m[3, 3]),
        "target_rc": target,
        "target_height_m": float(p.height_m[target]),
        "intermediate_height_m": float(p.height_m[3, 4]),
        "skips_ridge": True,
        "interpretation": "Endpoint-slope descent alone can jump over higher intermediate terrain.",
    }


def main() -> None:
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--production", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    held = json.loads((args.previous / "summary.json").read_text(encoding="utf-8"))["packs"][
        "external"
    ]
    centre = max((q for q in held["paths"] if q["status"] != "absorbed"), key=lambda q: q["steps"])[
        "end_rc"
    ]
    bounds = [centre[1] - 24, centre[1] + 24, centre[0] - 24, centre[0] + 24]
    spacing = held["spacing_km"]
    hpath = args.pack / "refined-out/height.pre-equilibrium.npy"
    assert hashlib.sha256(hpath.read_bytes()).hexdigest() == held["height_sha256"]
    height = np.load(hpath)
    land = np.asarray(Image.open(args.pack / "refined-out/land.png")) > 0
    lake = np.asarray(Image.open(args.pack / "refined-out/lake.png")) > 0
    stop = frame(height.shape) | ~land | lake
    filled, order, d8 = priority_flood(height, ~stop, eps=1e-4)
    acc = flow_accumulation(order, d8, (~stop).astype(float))
    seeds = held_seeds(d8, (~stop) & (acc > 64), bounds)
    print(
        f"Fixed {len(seeds)} original D8 heads whose paths visit the requested window", flush=True
    )
    prepared = prepare(height, stop)
    triangular, cubic = TriangularSurface(prepared), CubicSurface(prepared.height_m)
    groups, endings, titles = {}, {}, {}
    rows = height.shape[0]
    for key, title in (
        ("baseline", "Existing production D8"),
        ("d8_simple", "Production D8 + bounded smoothing"),
    ):
        xy = np.load(args.production / f"external-{key}.line.npy") / spacing
        groups[key] = xy[:, :, ::-1] * [-1, 1] + [rows - 1, 0]
        titles[key] = title
    d8paths = [raw_d8_path(d8, stop, seed) for seed in seeds]
    groups["d8_raw"] = rc_segments(d8paths, rows, spacing)
    titles["d8_raw"] = "Raw D8 paths; held sources"
    report = {
        "bounds_col_row_px": bounds,
        "spacing_m": spacing * 1000,
        "window_width_km": 48 * spacing,
        "height_sha256": held["height_sha256"],
        "seeds_rc": seeds,
        "plane_controls": [plane_resolution(r) for r in (1, 2, 3)],
        "ridge_control": ridge_control(),
        "variants": {},
        "scope": (
            "Cached production panels preserve the reported figure. Traces and split routing "
            "use the same selected D8 sources. D-infinity depicts its two-receiver graph, "
            "not a continuous centerline."
        ),
    }
    for key, surface, function in (
        ("triangular", triangular, trace_triangles),
        ("cubic", cubic, trace),
    ):
        paths = [function(surface, tuple(seed), stop) for seed in seeds]
        xy = [np.column_stack((p.points_rc[:, 1], rows - 1 - p.points_rc[:, 0])) for p in paths]
        groups[key] = rc_segments(xy, rows, spacing)
        endings[key] = [p.points_rc[-1] for p in paths if p.status != "absorbed"]
        report["variants"][key] = {"statuses": dict(Counter(p.status for p in paths))}
        titles[key] = f"{key.title()} terrain descent; held sources"
        if key == "triangular":
            anchors = shared_junctions(xy)
            smooth = [
                smooth_line(p, sample_spacing=2, anchors=a).points
                for p, a in zip(xy, anchors, strict=True)
            ]
            groups["triangular_smooth"] = rc_segments(smooth, rows, spacing)
            titles["triangular_smooth"] = "Triangular + same 2-pixel smoothing"
        print(key, report["variants"][key], flush=True)
    route = routing(prepared)
    source = np.zeros(height.shape)
    for seed in seeds:
        source[seed] = 1
    dinf_acc = accumulate(prepared, route, source)
    rec, proportions = route.receiver.reshape(-1, 2), route.proportion.reshape(-1, 2)
    flux = dinf_acc.ravel()[:, None] * proportions
    cell, edge = np.nonzero(flux >= 0.01)
    target = rec[cell, edge]
    start = np.column_stack(np.divmod(cell, rows))
    end = np.column_stack(np.divmod(target, rows))
    groups["dinf"] = np.stack((start, end), axis=1)
    titles["dinf"] = "D-infinity two-receiver graph; >=1% source"
    sinks = route.proportion.sum(axis=2) == 0
    residual = abs(float(dinf_acc[sinks].sum() - source.sum())) / source.sum()
    assert residual <= 1e-12 and not (sinks & ~stop).any()
    report["variants"]["dinf"] = {
        "unexplained_sinks": 0,
        "relative_budget_residual": residual,
        "display_edge_source_fraction_minimum": 0.01,
    }
    for radius in (2, 3):
        recwide = receivers(prepared.height_m, stop, prepared.d8_receiver, radius)
        paths = [raw_d8_path(recwide, stop, seed) for seed in seeds]
        key = f"radius_{radius}"
        groups[key] = rc_segments(paths, rows, spacing)
        titles[key] = f"{radius}-ring endpoint slope (exploration)"
        report["variants"][key] = {
            "absorbed_paths": len(paths),
            "intermediate_barriers_checked": False,
            "water_budget_validated": False,
        }
    keys = [
        "baseline",
        "d8_simple",
        "d8_raw",
        "dinf",
        "triangular",
        "triangular_smooth",
        "cubic",
        "radius_2",
        "radius_3",
    ]
    clipped = {key: clip(groups[key], bounds) for key in keys}

    def draw(ax, key):
        ax.imshow(height, cmap="gray")
        ax.add_collection(
            LineCollection(clipped[key][:, :, ::-1], colors="#1684dc", linewidths=0.9)
        )
        if endings.get(key):
            pts = np.array(endings[key])
            ax.scatter(pts[:, 1], pts[:, 0], c="#ff684a", marker="x", s=24)
        ax.set_xlim(*bounds[:2])
        ax.set_ylim(bounds[3], bounds[2])
        ax.set_title(titles[key], fontsize=10)

    fig, axes = plt.subplots(3, 3, figsize=(15, 15), sharex=True, sharey=True)
    for ax, key in zip(axes.flat, keys, strict=True):
        draw(ax, key)
        fig2, single = plt.subplots(figsize=(6, 6))
        draw(single, key)
        fig2.tight_layout()
        fig2.savefig(args.out / f"{key}.png", dpi=180)
        plt.close(fig2)
        xy = clipped[key][:, :, ::-1] * [1, -1]
        from scripts.media.diagnose_river_directions import DirectionStats

        stats = DirectionStats()
        stats.add((xy[:, 1] - xy[:, 0]) * spacing)
        report["variants"].setdefault(key, {})["window_direction_stats"] = stats.report()
        np.save(args.out / f"{key}.window-rc.line.npy", clipped[key])
    fig.suptitle(
        f"Exact reported window: {spacing * 1000:.2f} m/pixel; {len(seeds)} held sources; "
        "red crosses = incomplete traces",
        fontsize=13,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.975))
    fig.savefig(args.out / "comparison.png", dpi=180)
    plt.close(fig)
    (args.out / "summary.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
