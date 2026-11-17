"""Compare original D-infinity flat handling and separate triangular flowlines.

Held seeds and the previous cubic result are read from --previous. Pack entries
use NAME=PATH. All output belongs under the main repository exports directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image

from scripts.media.compare_continuous_flowlines import d8_path, draw_paths, smoothed_d8_segments
from scripts.media.compare_dinf_routing import frame, hash_file, plane
from scripts.media.continuous_flowline import CubicSurface, export_segments, trace
from scripts.media.diagnose_river_directions import DirectionStats
from scripts.media.dinf_original import accumulate, prepare, routing, topological_order
from scripts.media.triangular_flowline import HEIGHT_TOL_M, TriangularSurface, trace_triangles


def controls(out: Path) -> dict:
    import matplotlib.pyplot as plt

    rows = []
    for angle in np.arange(0.25, 180, 2.5):
        h = plane((65, 65), angle)
        p = prepare(h, frame(h.shape))
        route = routing(p)
        path = trace_triangles(TriangularSurface(p), (32, 32), p.absorbing)
        delta = np.diff(path.points_rc, axis=0)
        errors = abs(
            np.degrees(
                np.angle(np.exp(1j * (np.arctan2(-delta[:, 0], delta[:, 1]) - np.radians(angle))))
            )
        )
        nodal_error = abs(
            np.degrees(np.angle(np.exp(1j * (route.angle_rad[32, 32] - np.radians(angle)))))
        )
        rows.append(
            {
                "angle_deg": float(angle),
                "triangle_export_maximum_error_deg": float(errors.max()),
                "original_dinf_angle_error_deg": float(nodal_error),
                "status": path.status,
            }
        )
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.plot([r["angle_deg"] for r in rows], [r["triangle_export_maximum_error_deg"] for r in rows])
    ax.set(
        xlabel="Analytical downslope azimuth (degrees)",
        ylabel="Triangular exported line error (degrees)",
    )
    fig.tight_layout()
    fig.savefig(out / "plane-directions.png", dpi=160)
    plt.close(fig)

    row, col = np.indices((129, 129))
    radius, theta = np.hypot(col + 20, 148 - row), np.arctan2(148 - row, col + 20)
    h = -60 * theta + 0.03 * (radius - 100) ** 2
    seed = (148 - 100 * np.sin(np.radians(20)), 100 * np.cos(np.radians(20)) - 20)
    p = prepare(h, frame(h.shape))
    surface = TriangularSurface(p)
    paths = [trace_triangles(surface, seed, p.absorbing, sample_px=s) for s in (0.5, 0.25)]
    radial_errors = [
        float(abs(np.hypot(path.points_rc[:, 1] + 20, 148 - path.points_rc[:, 0]) - 100).max())
        for path in paths
    ]
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.imshow(h, cmap="terrain")
    angles = np.radians(np.linspace(20, 78.5, 500))
    ax.plot(
        100 * np.cos(angles) - 20, 148 - 100 * np.sin(angles), "k--", label="Analytical centerline"
    )
    ax.plot(paths[0].points_rc[:, 1], paths[0].points_rc[:, 0], label="Exact triangular events")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out / "circular-valley.png", dpi=160)
    plt.close(fig)

    row, col = np.indices((25, 33))
    h = -(col // 4) * 5 - col * 1e-4 + 0.2 * (row - 10.4) ** 2
    p = prepare(h, frame(h.shape))
    surface = TriangularSurface(p)
    path = trace_triangles(surface, (10.4, 4), p.absorbing)
    x = np.linspace(2, 8, 500)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    axes[0].plot(
        x, [surface.height(np.array([10.4, c])) for c in x], label="Triangular height at row 10.4"
    )
    axes[0].scatter(np.arange(2, 9), h[10, 2:9], label="Row-10 nodal heights")
    axes[0].set(xlabel="Column (pixels)", ylabel="Height (m)")
    axes[0].legend()
    axes[1].imshow(h, cmap="terrain")
    axes[1].plot(
        path.points_rc[:, 1], path.points_rc[:, 0], label="Continuous path reaches boundary"
    )
    axes[1].legend()
    fig.tight_layout()
    fig.savefig(out / "monotone-valley.png", dpi=160)
    plt.close(fig)
    return {
        "plane": {
            "rows": rows,
            "passes": bool(
                max(r["triangle_export_maximum_error_deg"] for r in rows) <= 1e-7
                and all(r["status"] == "absorbed" for r in rows)
            ),
        },
        "circular_valley": {
            "maximum_radial_errors_px": radial_errors,
            "status": [p.status for p in paths],
            "passes": bool(
                max(radial_errors) <= 0.5 and all(p.status == "absorbed" for p in paths)
            ),
        },
        "monotone_valley": {
            "status": path.status,
            "end_rc": path.points_rc[-1].tolist(),
            "passes": path.status == "absorbed",
        },
    }


def pack_control(name: str, pack: Path, previous: Path, out: Path) -> dict:
    import matplotlib.pyplot as plt

    old = json.loads((previous / "summary.json").read_text(encoding="utf-8"))["packs"][name]
    seeds = [tuple(seed) for seed in old["seeds"]]
    hpath = pack / "refined-out/height.pre-equilibrium.npy"
    if hash_file(hpath) != old["height_sha256"]:
        raise ValueError("held source DEM changed since the cubic comparison")
    h = np.load(hpath)
    land = np.asarray(Image.open(pack / "refined-out/land.png")) > 0
    lake = np.asarray(Image.open(pack / "refined-out/lake.png")) > 0
    stop = frame(h.shape) | ~land | lake
    p = prepare(h, stop)
    if not p.reached[np.isfinite(h)].all():
        raise ValueError("finite component has no declared outlet")
    route = routing(p, old["spacing_km"] * 1000)
    topological_order(p.height_m, route)
    runoff = np.load(pack / "input/runoff.mm.npy")
    source = np.repeat(
        np.repeat(runoff, h.shape[0] // runoff.shape[0], axis=0),
        h.shape[1] // runoff.shape[1],
        axis=1,
    ).astype(float)
    source *= (old["spacing_km"] * 1000) ** 2 / 1000
    source[stop] = 0
    acc = accumulate(p, route, source)
    sinks = route.proportion.sum(axis=2) == 0
    source_total, sink_total = float(source.sum()), float(acc[sinks].sum())
    unexplained = sinks & ~stop & np.isfinite(h)
    surface = TriangularSurface(p)
    # D8 uses the same zero-epsilon preparation, including equal-height routing.
    d8_receiver = np.full((*h.shape, 2), -1, dtype=np.int64)
    d8_receiver[..., 0] = p.d8_receiver
    base = [d8_path(p.height_m, d8_receiver, seed) for seed in seeds]
    cubic_surface = CubicSurface(p.height_m)
    cubic_paths = [trace(cubic_surface, seed, stop) for seed in seeds]
    paths = []
    for i, seed in enumerate(seeds):
        paths.append(trace_triangles(surface, seed, stop))
        if (i + 1) % 16 == 0:
            print(f"{name}: completed {i + 1}/{len(seeds)} triangular paths", flush=True)
    # Export subdivision cannot change an exact event path. Independently rerun
    # the first eight traces with half spacing to check this invariant.
    fine = [trace_triangles(surface, seed, stop, sample_px=0.25) for seed in seeds[:8]]
    endpoint_difference = [
        float(np.linalg.norm(a.points_rc[-1] - b.points_rc[-1]))
        for a, b in zip(paths[:8], fine, strict=True)
    ]
    fig, axes = plt.subplots(1, 3, figsize=(16, 5), sharex=True, sharey=True)
    stats = {}
    all_segments = {}
    for method, group, ax in zip(
        ("d8-original", "triangular"), (base, paths), (axes[0], axes[2]), strict=True
    ):
        segments = np.concatenate(
            [
                smoothed_d8_segments(path, h.shape, old["spacing_km"])
                if method == "d8-original"
                else export_segments(path, h.shape, old["spacing_km"])
                for path in group
            ]
        )
        np.save(out / f"{name}-{method}.line.npy", segments)
        all_segments[method] = segments
        direction = DirectionStats()
        direction.add(segments[:, 1] - segments[:, 0])
        stats[method] = direction.report()
        pixels = segments.copy() / old["spacing_km"]
        pixels[..., 1] = h.shape[0] - 1 - pixels[..., 1]
        unresolved = [path for path in group if path.status != "absorbed"]
        draw_paths(
            ax,
            p.height_m,
            list(pixels),
            f"{method}: {len(group) - len(unresolved)}/{len(group)} reach sink",
            unresolved,
        )
    cubic = np.concatenate(
        [export_segments(path, h.shape, old["spacing_km"]) for path in cubic_paths]
    )
    np.save(out / f"{name}-cubic-same-preparation.line.npy", cubic)
    pixels = cubic.copy() / old["spacing_km"]
    pixels[..., 1] = h.shape[0] - 1 - pixels[..., 1]
    draw_paths(
        axes[1],
        p.height_m,
        list(pixels),
        f"Cubic, same preparation: {sum(q.status == 'absorbed' for q in cubic_paths)}/{len(seeds)}",
        [],
    )
    stopped = [q.points_rc[-1] for q in cubic_paths if q.status != "absorbed"]
    if stopped:
        points = np.array(stopped)
        axes[1].scatter(points[:, 1], points[:, 0], c="red", s=9)
    fig.tight_layout()
    fig.savefig(out / f"{name}-flowlines.png", dpi=170)
    plt.close(fig)
    if stopped:
        center = max(
            (q for q in cubic_paths if q.status != "absorbed"), key=lambda q: len(q.points_rc)
        ).points_rc[-1]
        fig, axes = plt.subplots(1, 2, figsize=(11, 5), sharex=True, sharey=True)
        tri_pixels = all_segments["triangular"].copy() / old["spacing_km"]
        tri_pixels[..., 1] = h.shape[0] - 1 - tri_pixels[..., 1]
        draw_paths(axes[0], p.height_m, list(pixels), "Cubic stop on same prepared DEM", [])
        axes[0].scatter([center[1]], [center[0]], c="red", s=20)
        axes[1].scatter(
            [center[1]], [center[0]], c="red", s=20, label="Previous spline stop location"
        )
        draw_paths(axes[1], p.height_m, list(tri_pixels), "Triangular valley-edge continuation", [])
        for ax in axes:
            ax.set_xlim(max(0, center[1] - 24), min(h.shape[1] - 1, center[1] + 24))
            ax.set_ylim(min(h.shape[0] - 1, center[0] + 24), max(0, center[0] - 24))
        fig.tight_layout()
        fig.savefig(out / f"{name}-detail.png", dpi=170)
        plt.close(fig)
    equal = (route.proportion > 0) & (route.receiver >= 0)
    target_heights = p.height_m.ravel()[np.maximum(route.receiver, 0)]
    equal &= target_heights == p.height_m[..., None]
    relative_residual = abs(sink_total - source_total) / max(source_total, 1)
    maximum_rise = max(
        float(np.diff(path.height_m).max()) for path in paths if len(path.height_m) > 1
    )
    return {
        "source_height_sha256": hash_file(hpath),
        "prepared_height_sha256": hashlib.sha256(p.height_m.tobytes()).hexdigest(),
        "seeds": seeds,
        "original_routing": {
            "equal_height_edges": int(equal.sum()),
            "unexplained_sinks": int(unexplained.sum()),
            "source_m3_per_year": source_total,
            "sinks_m3_per_year": sink_total,
            "relative_budget_residual": relative_residual,
            "acyclic": True,
        },
        "status_d8": dict(Counter(path.status for path in base)),
        "status_cubic_same_preparation": dict(Counter(path.status for path in cubic_paths)),
        "status_cubic_previous_preparation": old["status_continuous_050"],
        "status_triangular": dict(Counter(path.status for path in paths)),
        "maximum_sampled_height_rise_m": maximum_rise,
        "half_spacing_endpoint_difference_px": max(endpoint_difference),
        "direction_stats": stats,
        "paths": [
            {
                "seed": seed,
                "status": path.status,
                "sink_cell": path.sink_cell,
                "end_rc": path.points_rc[-1].tolist(),
                "points": len(path.points_rc),
            }
            for seed, path in zip(seeds, paths, strict=True)
        ],
        "original_routing_passes": bool(not unexplained.any() and relative_residual <= 1e-12),
        "geometry_passes": bool(
            all(
                path.status == "absorbed" and path.sink_cell is not None and stop[path.sink_cell]
                for path in paths
            )
            and maximum_rise <= HEIGHT_TOL_M
            and max(endpoint_difference) <= 1e-10
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--pack", action="append", default=[])
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    report = {
        "original_method": (
            "eight-facet D-infinity with zero-epsilon pit filling and D8 equal-height resolution"
        ),
        "geometry_extension": (
            "nonoverlapping valley-diagonal triangles, exact facet/edge/vertex descent, D8 flats"
        ),
        "controls": controls(args.out),
        "packs": {},
    }
    for entry in args.pack:
        name, path = entry.split("=", 1)
        if not name.replace("-", "").replace("_", "").isalnum():
            raise ValueError("pack names must be alphanumeric")
        report["packs"][name] = pack_control(name, Path(path), args.previous, args.out)
    report["original_routing_passes"] = all(
        p["original_routing_passes"] for p in report["packs"].values()
    )
    report["geometry_candidate_passes"] = all(
        p["geometry_passes"] for p in report["packs"].values()
    ) and all(p["passes"] for p in report["controls"].values())
    report["native_direction_improves_against_smoothed_d8"] = all(
        p["direction_stats"]["triangular"]["within_5deg_of_grid_percent"]
        < p["direction_stats"]["d8-original"]["within_5deg_of_grid_percent"]
        for p in report["packs"].values()
    )
    report["river_line_replacement_passes"] = bool(
        report["geometry_candidate_passes"]
        and report["native_direction_improves_against_smoothed_d8"]
    )
    (args.out / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {key: report[key] for key in ("original_routing_passes", "geometry_candidate_passes")}
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
