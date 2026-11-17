"""Compare production D8 plus bounded smoothing with frozen triangular traces."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

from dreamulator.map.prog_erosion import _chaikin, flow_accumulation, priority_flood
from scripts.media.bounded_river_lines import smooth_line
from scripts.media.compare_bounded_river_lines import (
    points_from_segments,
    preserves_first_water_touch,
    shared_junctions,
    stats_for,
)
from scripts.media.compare_dinf_routing import frame, plane
from scripts.media.continuous_flowline import first_absorber


def raw_d8_path(receiver: np.ndarray, stop: np.ndarray, seed: tuple) -> np.ndarray:
    """Follow production receivers and clip at the first declared water/frame edge."""
    cell = int(seed[0]) * stop.shape[1] + int(seed[1])
    points = [np.array(seed, dtype=float)]
    for _ in range(stop.size):
        target = int(receiver[cell])
        if target < 0:
            raise ValueError("D8 trace stopped before a declared absorber")
        end = np.array(divmod(target, stop.shape[1]), dtype=float)
        hit = first_absorber(points[-1], end, stop)
        if hit is not None:
            points.append(hit[0])
            rc = np.asarray(points)
            return np.column_stack((rc[:, 1], stop.shape[0] - 1 - rc[:, 0]))
        points.append(end)
        cell = target
    raise ValueError("D8 trace did not terminate")


def plane_control() -> dict:
    errors, smooth_errors = [], []
    for angle in np.arange(0.25, 180, 2.5):
        height = plane((65, 65), angle)
        stop = frame(height.shape)
        _, _, receiver = priority_flood(height, ~stop, eps=1e-4)
        raw = raw_d8_path(receiver, stop, (32, 32))
        smooth = smooth_line(raw, sample_spacing=1).points
        for path, values in ((raw, errors), (smooth, smooth_errors)):
            delta = np.diff(path, axis=0)
            lengths = np.linalg.norm(delta, axis=1)
            error = abs(
                np.degrees(
                    np.angle(
                        np.exp(1j * (np.arctan2(delta[:, 1], delta[:, 0]) - np.radians(angle)))
                    )
                )
            )
            values.append(float(np.dot(lengths, error) / lengths.sum()))
    return {
        "planes": len(errors),
        "d8_mean_error_deg": float(np.mean(errors)),
        "d8_smooth_mean_error_deg": float(np.mean(smooth_errors)),
        "d8_smooth_maximum_error_deg": max(smooth_errors),
    }


def path_distance(a: np.ndarray, b: np.ndarray) -> float:
    """Symmetric sampled distance between two traces from the same seed, in pixels."""
    from scipy.spatial import cKDTree

    def sample(path):
        station = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(path, axis=0), axis=1))]
        query = np.r_[np.arange(0, station[-1], 0.25), station[-1]]
        return np.column_stack([np.interp(query, station, path[:, axis]) for axis in range(2)])

    aa, bb = sample(a), sample(b)
    return float(max(cKDTree(aa).query(bb)[0].max(), cKDTree(bb).query(aa)[0].max()))


def pack_control(name: str, pack: Path, source: Path, accepted: Path, out: Path) -> dict:
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection

    old = json.loads(
        (source.parent / "continuous-river-pilot-20261115/summary.json").read_text(encoding="utf-8")
    )["packs"][name]
    original = json.loads((source / "summary.json").read_text(encoding="utf-8"))["packs"][name]
    current = json.loads((accepted / "summary.json").read_text(encoding="utf-8"))["packs"][name]
    hpath = pack / "refined-out/height.pre-equilibrium.npy"
    if hashlib.sha256(hpath.read_bytes()).hexdigest() != old["height_sha256"]:
        raise ValueError("held source DEM changed")
    height = np.load(hpath)
    land = np.asarray(Image.open(pack / "refined-out/land.png")) > 0
    lake = np.asarray(Image.open(pack / "refined-out/lake.png")) > 0
    stop = frame(height.shape) | ~land | lake
    filled, order, receiver = priority_flood(height, ~stop, eps=1e-4)
    cells = np.flatnonzero(~stop.ravel())
    rank = np.full(height.size, -1, dtype=np.int64)
    used = order[order >= 0]
    rank[used] = np.arange(len(used))
    assert (receiver[cells] >= 0).all()
    assert (rank[receiver[cells]] < rank[cells]).all()
    assert (filled.ravel()[receiver[cells]] < filled.ravel()[cells]).all()
    weight = (~stop).astype(float)
    acc = flow_accumulation(order, receiver, weight)
    residual = abs(float(acc[stop].sum() - weight.sum())) / weight.sum()
    assert residual <= 1e-12
    raw = [raw_d8_path(receiver, stop, tuple(seed)) for seed in old["seeds"]]
    anchors = shared_junctions(raw)
    smooth, rejected, maximum = [], 0, 0.0
    for path, fixed in zip(raw, anchors, strict=True):
        candidate = smooth_line(path, sample_spacing=1.0, anchors=fixed)
        if preserves_first_water_touch(candidate.points, stop):
            points = candidate.points
            maximum = max(maximum, candidate.maximum_offset)
        else:
            points = path
            rejected += 1
        np.testing.assert_array_equal(points[[0, -1]], path[[0, -1]])
        assert all((points == path[i]).all(axis=1).any() for i in fixed)
        assert preserves_first_water_touch(points, stop)
        smooth.append(points)
    spacing = old["spacing_km"]
    triangular = points_from_segments(
        np.load(source / f"{name}-triangular.line.npy"), original["paths"], spacing
    )
    accepted_segments = np.load(accepted / f"{name}-sample-1px.line.npy") / spacing
    raw_segments, raw_stats = stats_for(raw, spacing)
    _, existing_stats = stats_for([_chaikin(path) for path in raw], spacing)
    smooth_segments, smooth_stats = stats_for(smooth, spacing)
    np.save(out / f"{name}-d8-raw.line.npy", raw_segments)
    np.save(out / f"{name}-d8-smooth-1px.line.npy", smooth_segments)
    groups = [raw_segments / spacing, smooth_segments / spacing, accepted_segments]
    titles = [
        "Production D8, raw",
        "Production D8 + 1-pixel smoothing",
        "Triangular + 1-pixel smoothing",
    ]
    oldstop = max((p for p in old["paths"] if p["status"] != "absorbed"), key=lambda p: p["steps"])[
        "end_rc"
    ]
    for detail in (False, True):
        fig, axes = plt.subplots(1, 3, figsize=(15, 5), sharex=True, sharey=True)
        for ax, group, title in zip(axes, groups, titles, strict=True):
            ax.imshow(height, cmap="gray")
            xy = group.copy()
            xy[:, :, 1] = height.shape[0] - 1 - xy[:, :, 1]
            ax.add_collection(LineCollection(xy, colors="#1684dc", linewidths=1 if detail else 0.8))
            if detail:
                ax.set_xlim(oldstop[1] - 24, oldstop[1] + 24)
                ax.set_ylim(oldstop[0] + 24, oldstop[0] - 24)
            ax.set_title(title)
        fig.tight_layout()
        fig.savefig(out / f"{name}-{'detail' if detail else 'overview'}.png", dpi=170)
        plt.close(fig)
    endpoint_delta = np.array(
        [np.linalg.norm(a[-1] - b[-1]) for a, b in zip(raw, triangular, strict=True)]
    )
    distances = np.array([path_distance(a, b) for a, b in zip(raw, triangular, strict=True)])
    report = {
        "source_height_sha256": old["height_sha256"],
        "same_seeds_count": len(raw),
        "production_d8_epsilon_m": 1e-4,
        "acyclic_and_all_land_routes_to_absorbers": True,
        "water_budget_relative_residual": residual,
        "d8_raw": raw_stats,
        "d8_existing_chaikin": existing_stats,
        "d8_smooth_1px": smooth_stats,
        "triangular_smooth_1px": current["variants"]["1.0"]["direction_stats"],
        "maximum_d8_smoothing_offset_px": maximum,
        "endpoints_and_junctions_exact": True,
        "first_water_touch_passes": True,
        "first_water_rejected_paths": rejected,
        "d8_vs_triangular_endpoint_delta_px": {
            "median": float(np.median(endpoint_delta)),
            "maximum": float(endpoint_delta.max()),
            "within_1px_count": int((endpoint_delta <= 1).sum()),
        },
        "d8_vs_triangular_sampled_path_distance_px": {
            "median": float(np.median(distances)),
            "maximum": float(distances.max()),
        },
    }
    print(name, smooth_stats["within_5deg_of_grid_percent"], flush=True)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--accepted", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pack", action="append", default=[])
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    report = {
        "plane_control": plane_control(),
        "method": "Existing production Priority-Flood with epsilon; D8; bounded two-round Chaikin.",
        "comparison_scope": "Held terrain and starts; each route retains its own outlets.",
        "packs": {},
    }
    for entry in args.pack:
        name, path = entry.split("=", 1)
        report["packs"][name] = pack_control(name, Path(path), args.source, args.accepted, args.out)
    (args.out / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
