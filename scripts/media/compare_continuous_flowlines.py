"""Local exported-flowline acceptance: planes, curved valley, and held terrain.

Run as a module with --out <exports directory> and --pack NAME=PATH.
The cubic-height trajectory is a geometry candidate with a separate completion
gate. Point counts and attractive pictures do not substitute for outlet reach.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image

from scripts.media.compare_dinf_routing import frame, hash_file, plane
from scripts.media.continuous_flowline import (
    MIN_PROGRESS_PX,
    CubicSurface,
    Flowline,
    export_segments,
    trace,
)
from scripts.media.diagnose_river_directions import DirectionStats
from scripts.media.dinf_local import accumulate, directions


def d8_path(height: np.ndarray, receiver: np.ndarray, seed: tuple[float, float]) -> Flowline:
    """Follow the fixed D8 graph from the same nodal seed as the continuous candidate."""
    nr, nc = height.shape
    row, col = np.rint(seed).astype(int)
    cell = row * nc + col
    points, heights = [], []
    for _ in range(height.size):
        row, col = divmod(cell, nc)
        points.append([row, col])
        heights.append(height[row, col])
        target = int(receiver[row, col, 0])
        if target < 0:
            return Flowline(np.asarray(points), np.asarray(heights), "absorbed", (row, col), 0)
        cell = target
    return Flowline(np.asarray(points), np.asarray(heights), "step_limit", None, 0)


def smoothed_d8_segments(path: Flowline, shape: tuple[int, int], spacing_km: float) -> np.ndarray:
    from dreamulator.map.prog_erosion import _chaikin

    if len(path.points_rc) < 2:
        return np.empty((0, 2, 2))
    smooth = _chaikin(path.points_rc)
    return export_segments(
        Flowline(smooth, np.empty(0), path.status, path.sink_cell, 0), shape, spacing_km
    )


def plane_controls(out: Path) -> dict:
    import matplotlib.pyplot as plt

    rows = []
    for angle in np.arange(0.25, 180, 2.5):
        h = plane((65, 65), angle)
        stop = frame(h.shape)
        d8 = directions(h, 1, stop, method="d8")
        paths = {
            "d8": d8_path(h, d8.receiver, (32, 32)),
            "continuous": trace(CubicSurface(h), (32, 32), stop),
        }
        row = {"angle_deg": float(angle)}
        for method, path in paths.items():
            segs = (
                smoothed_d8_segments(path, h.shape, 1)
                if method == "d8"
                else export_segments(path, h.shape, 1)
            )
            v = segs[:, 1] - segs[:, 0]
            length = np.linalg.norm(v, axis=1)
            delta = np.abs(
                np.degrees(
                    np.angle(np.exp(1j * (np.arctan2(v[:, 1], v[:, 0]) - np.radians(angle))))
                )
            )
            row[method + "_length_weighted_error_deg"] = float(np.dot(delta, length) / length.sum())
            row[method + "_maximum_error_deg"] = float(delta.max())
            row[method + "_status"] = path.status
        rows.append(row)
    continuous_max = max(r["continuous_maximum_error_deg"] for r in rows)
    fig, ax = plt.subplots(figsize=(10, 4.5))
    for method, title in (
        ("d8", "D8 with existing Chaikin smoothing"),
        ("continuous", "Continuous cubic-height trajectory"),
    ):
        ax.plot(
            [r["angle_deg"] for r in rows],
            [r[method + "_length_weighted_error_deg"] for r in rows],
            label=title,
        )
    ax.set(xlabel="Analytical downslope azimuth (deg)", ylabel="Exported line error (deg)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out / "plane-export-directions.png", dpi=160)
    plt.close(fig)
    return {
        "rows": rows,
        "maximum_continuous_error_deg": continuous_max,
        "passes": bool(
            continuous_max <= 1e-7 and all(r["continuous_status"] == "absorbed" for r in rows)
        ),
    }


def valley_control(out: Path) -> dict:
    import matplotlib.pyplot as plt

    row, col = np.indices((129, 129))
    radius = np.hypot(col + 20, 128 - row + 20)
    theta = np.arctan2(128 - row + 20, col + 20)
    h = -60 * theta + 0.03 * (radius - 100) ** 2
    seed = (128 - (100 * np.sin(np.radians(20)) - 20), 100 * np.cos(np.radians(20)) - 20)
    surface, stop = CubicSurface(h), frame(h.shape)
    paths = [trace(surface, seed, stop, step_px=s) for s in (0.5, 0.25, 0.125)]
    errors = []
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.imshow(h, cmap="terrain")
    angles = np.radians(np.linspace(20, 78.5, 500))
    ax.plot(
        100 * np.cos(angles) - 20,
        148 - 100 * np.sin(angles),
        "k--",
        label="Analytical valley centerline",
    )
    for step, path in zip((0.5, 0.25, 0.125), paths, strict=True):
        r = np.hypot(path.points_rc[:, 1] + 20, 148 - path.points_rc[:, 0])
        errors.append(float(abs(r - 100).max()))
        ax.plot(path.points_rc[:, 1], path.points_rc[:, 0], label=f"Step {step} pixels")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out / "circular-valley.png", dpi=160)
    plt.close(fig)
    endpoints = [
        float(np.linalg.norm(paths[i].points_rc[-1] - paths[i + 1].points_rc[-1])) for i in (0, 1)
    ]
    return {
        "maximum_radial_errors_px": errors,
        "endpoint_halving_difference_px": endpoints,
        "status": [p.status for p in paths],
        "passes": bool(
            max(errors) <= 0.5
            and max(endpoints) <= 0.01
            and all(p.status == "absorbed" for p in paths)
        ),
    }


def choose_seeds(acc: np.ndarray, stop: np.ndarray) -> list[tuple[float, float]]:
    """Choose the highest accepted D-infinity flow in each of 64 fixed spatial bins."""
    seeds = []
    for row in range(0, acc.shape[0], 128):
        for col in range(0, acc.shape[1], 128):
            crop = np.s_[row : row + 128, col : col + 128]
            valid = ~stop[crop]
            if not valid.any():
                continue
            values = np.where(valid, acc[crop], -np.inf)
            r, c = np.unravel_index(np.argmax(values), values.shape)
            seeds.append((float(row + r), float(col + c)))
    return seeds


def monotone_valley_control(out: Path) -> dict:
    """A strictly descending nodal valley can acquire an interpolated local minimum."""
    import matplotlib.pyplot as plt

    row, col = np.indices((25, 33))
    h = -(col // 4) * 5 - col * 1e-4 + 0.2 * (row - 10.4) ** 2
    surface = CubicSurface(h)
    path = trace(surface, (10.4, 4), frame(h.shape))
    sample_x = np.linspace(2, 7, 1000)
    heights = surface.spline.ev(np.full_like(sample_x, 10.4), sample_x)
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(sample_x, heights, label="Cubic surface on valley centerline")
    ax.plot(
        np.arange(2, 8), h[10, 2:8] - 0.2 * 0.4**2, "o--", label="Strictly descending nodal heights"
    )
    ax.scatter([path.points_rc[-1, 1]], [path.height_m[-1]], c="red", label="Continuous path stop")
    ax.set(xlabel="Column (pixels)", ylabel="Height (m)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out / "monotone-valley-overshoot.png", dpi=160)
    plt.close(fig)
    return {
        "all_nodal_rows_strictly_descend": bool((np.diff(h, axis=1) < 0).all()),
        "continuous_status": path.status,
        "end_rc": path.points_rc[-1].tolist(),
        "end_height_m": float(path.height_m[-1]),
    }


def draw_paths(
    ax, h: np.ndarray, paths: list[np.ndarray], title: str, unresolved: list[Flowline]
) -> None:
    from matplotlib.collections import LineCollection

    ax.imshow(h, cmap="gray", origin="upper")
    ax.add_collection(LineCollection(paths, colors="#1684dc", linewidths=0.9))
    if unresolved:
        ends = np.array([p.points_rc[-1] for p in unresolved])
        ax.scatter(ends[:, 1], ends[:, 0], c="red", s=9, label="Stopped before declared sink")
        ax.legend(loc="lower left", fontsize=8)
    ax.set_title(title)


def pack_control(name: str, pack: Path, out: Path) -> dict:
    import matplotlib.pyplot as plt

    from dreamulator.map.prog_erosion import priority_flood

    hpath = pack / "refined-out/height.pre-equilibrium.npy"
    h = np.load(hpath, mmap_mode="r")
    if h.ndim != 2 or max(h.shape) > 1024 or min(h.shape) < 4 or not np.isfinite(h).all():
        raise ValueError("local pack requires finite height samples on a grid of 4 to 1024")
    land = np.asarray(Image.open(pack / "refined-out/land.png")) > 0
    lake = np.asarray(Image.open(pack / "refined-out/lake.png")) > 0
    stop = frame(h.shape) | ~land | lake
    meta = json.loads((pack / "input/meta.json").read_text(encoding="utf-8"))
    if meta["extent_km"]["x"] / h.shape[1] != meta["extent_km"]["y"] / h.shape[0]:
        raise ValueError("local geometry pilot requires square grid cells")
    spacing_km = meta["extent_km"]["x"] / h.shape[1]
    prepared, _, _ = priority_flood(h, land, eps=1e-4)
    runoff = np.load(pack / "input/runoff.mm.npy")
    weights = np.repeat(
        np.repeat(runoff, h.shape[0] // runoff.shape[0], axis=0),
        h.shape[1] // runoff.shape[1],
        axis=1,
    )
    source = weights.astype(float) / 1000 * (spacing_km * 1000) ** 2
    source[stop] = 0
    dinf = directions(prepared, spacing_km * 1000, stop)
    acc = accumulate(prepared, dinf, source)
    seeds = choose_seeds(acc, stop)
    surface, d8 = CubicSurface(prepared), directions(prepared, spacing_km * 1000, stop, method="d8")
    base = [d8_path(prepared, d8.receiver, s) for s in seeds]
    if not all(p.sink_cell is not None and stop[p.sink_cell] for p in base):
        raise ValueError("D8 comparison path failed to reach a declared sink")
    coarse = []
    fine = []
    for i, seed in enumerate(seeds):
        coarse.append(trace(surface, seed, stop, step_px=0.5))
        fine.append(trace(surface, seed, stop, step_px=0.25))
        if (i + 1) % 16 == 0:
            print(f"{name}: completed {i + 1}/{len(seeds)} seeds", flush=True)
    figs, axes = plt.subplots(1, 3, figsize=(15, 5), sharex=True, sharey=True)
    line_sets = []
    direction_stats = {}
    for method, paths, ax in zip(
        ("d8", "continuous-050", "continuous-025"), (base, coarse, fine), axes, strict=True
    ):
        lines = []
        segs = []
        stats = DirectionStats()
        for path in paths:
            export = (
                smoothed_d8_segments(path, h.shape, spacing_km)
                if method == "d8"
                else export_segments(path, h.shape, spacing_km)
            )
            segs.append(export)
            stats.add(export[:, 1] - export[:, 0])
            pixels = export / spacing_km
            pixels[..., 1] = h.shape[0] - 1 - pixels[..., 1]
            lines.extend(pixels)
        segments = np.concatenate(segs) if segs else np.empty((0, 2, 2))
        np.save(out / f"{name}-{method}.line.npy", segments)
        unresolved = [p for p in paths if p.status != "absorbed"]
        draw_paths(
            ax,
            prepared,
            lines,
            f"{method}: {len(paths) - len(unresolved)}/{len(paths)} reach sink",
            unresolved,
        )
        line_sets.append(lines)
        direction_stats[method] = stats.report()
    figs.tight_layout()
    figs.savefig(out / f"{name}-flowlines.png", dpi=170)
    plt.close(figs)
    stopped = [p for p in coarse if p.status != "absorbed"]
    if stopped:
        point = max(stopped, key=lambda p: len(p.points_rc)).points_rc[-1]
        fig, axes = plt.subplots(1, 2, figsize=(10, 5), sharex=True, sharey=True)
        for ax, lines, title, unresolved in zip(
            axes,
            line_sets[:2],
            ("D8 with Chaikin", "Continuous trajectory"),
            ([], stopped),
            strict=True,
        ):
            draw_paths(ax, prepared, lines, title, unresolved)
            ax.set_xlim(point[1] - 64, point[1] + 64)
            ax.set_ylim(point[0] + 64, point[0] - 64)
        fig.tight_layout()
        fig.savefig(out / f"{name}-stopped-detail.png", dpi=170)
        plt.close(fig)
    endings = [
        float(np.linalg.norm(a.points_rc[-1] - b.points_rc[-1]))
        for a, b in zip(coarse, fine, strict=True)
    ]
    nodal = surface.spline(np.arange(h.shape[0]), np.arange(h.shape[1]))
    return {
        "seeds": seeds,
        "seed_selection": "largest D-infinity accumulation per fixed 128-square bin",
        "height_sha256": hash_file(hpath),
        "spacing_km": spacing_km,
        "maximum_nodal_interpolation_error_m": float(abs(nodal - prepared).max()),
        "status_d8": dict(Counter(p.status for p in base)),
        "direction_stats": direction_stats,
        "status_continuous_050": dict(Counter(p.status for p in coarse)),
        "status_continuous_025": dict(Counter(p.status for p in fine)),
        "endpoint_halving_difference_px": {
            "median": float(np.median(endings)),
            "maximum": float(max(endings)),
        },
        "all_continuous_accepted_steps_descend": bool(
            all((np.diff(p.height_m) < 0).all() for p in coarse + fine)
        ),
        "outlet_completion_passes": bool(all(p.status == "absorbed" for p in coarse + fine)),
        "paths": [
            {
                "seed": seed,
                "status": p.status,
                "sink_cell": p.sink_cell,
                "end_rc": p.points_rc[-1].tolist(),
                "steps": len(p.points_rc) - 1,
                "rejected_steps": p.rejected_steps,
            }
            for seed, p in zip(seeds, coarse, strict=True)
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pack", action="append", default=[])
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    report = {
        "candidate": "exact-nodal cubic-height descent with midpoint integration",
        "minimum_progress_px": MIN_PROGRESS_PX,
        "plane": plane_controls(args.out),
        "circular_valley": valley_control(args.out),
        "monotone_valley": monotone_valley_control(args.out),
        "packs": {},
    }
    for entry in args.pack:
        name, path = entry.split("=", 1)
        if not name.replace("-", "").replace("_", "").isalnum():
            raise ValueError("pack name must be alphanumeric")
        report["packs"][name] = pack_control(name, Path(path), args.out)
    report["geometry_candidate_passes"] = bool(
        report["plane"]["passes"]
        and report["circular_valley"]["passes"]
        and all(q["outlet_completion_passes"] for q in report["packs"].values())
    )
    (args.out / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps({"geometry_candidate_passes": report["geometry_candidate_passes"]}), flush=True
    )


if __name__ == "__main__":
    main()
