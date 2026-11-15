"""Two fixed cartographic smoothing scales on frozen accepted river traces."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

from scripts.media.bounded_river_lines import smooth_line
from scripts.media.compare_dinf_routing import frame
from scripts.media.continuous_flowline import first_absorber
from scripts.media.diagnose_river_directions import DirectionStats


def points_from_segments(
    segments: np.ndarray, rows: list[dict], spacing: float
) -> list[np.ndarray]:
    paths, offset = [], 0
    for row in rows:
        count = row["points"] - 1
        part = segments[offset : offset + count] / spacing
        paths.append(np.vstack((part[0, 0], part[:, 1])))
        offset += count
    if offset != len(segments):
        raise ValueError("accepted path counts differ from vector file")
    return paths


def shared_junctions(paths: list[np.ndarray]) -> list[tuple[int, ...]]:
    incoming = defaultdict(set)
    owners = defaultdict(set)
    for number, path in enumerate(paths):
        keys = [tuple(np.round(point, 8)) for point in path]
        for before, key in zip(keys[:-1], keys[1:], strict=True):
            incoming[key].add(before)
            owners[key].add(number)
    junctions = {key for key in incoming if len(incoming[key]) > 1 and len(owners[key]) > 1}
    return [
        tuple(i for i, point in enumerate(path) if tuple(np.round(point, 8)) in junctions)
        for path in paths
    ]


def preserves_first_water_touch(path: np.ndarray, stop: np.ndarray) -> bool:
    rc = np.column_stack((stop.shape[0] - 1 - path[:, 1], path[:, 0]))
    for a, b in zip(rc[:-1], rc[1:], strict=True):
        hit = first_absorber(a, b, stop)
        if hit is not None:
            return bool(np.linalg.norm(hit[0] - rc[-1]) <= 1e-8)
    # A path entering a lake toward decreasing row/column can end exactly on
    # its right/bottom edge. Check closed pixel boxes rather than floor's
    # asymmetric assignment of that boundary point to the land-side pixel.
    row, col = np.floor(rc[-1] + 0.5).astype(int)
    for r in range(max(0, row - 1), min(stop.shape[0], row + 2)):
        for c in range(max(0, col - 1), min(stop.shape[1], col + 2)):
            if stop[r, c] and np.max(abs(rc[-1] - [r, c])) <= 0.5 + 1e-9:
                return True
    return False


def stats_for(paths: list[np.ndarray], spacing: float) -> tuple[np.ndarray, dict]:
    segments = np.concatenate([np.stack((path[:-1], path[1:]), axis=1) for path in paths]) * spacing
    stats = DirectionStats()
    stats.add(segments[:, 1] - segments[:, 0])
    return segments, stats.report()


def controls() -> dict:
    results = {}
    for step in (1.0, 2.0):
        maximum = 0.0
        for angle in np.arange(0.25, 180, 2.5):
            a = np.radians(angle)
            points = np.linspace(0, 32, 129)[:, None] * np.array([np.cos(a), np.sin(a)])
            result = smooth_line(points, sample_spacing=step)
            v = np.diff(result.points, axis=0)
            error = abs(np.degrees(np.angle(np.exp(1j * (np.arctan2(v[:, 1], v[:, 0]) - a)))))
            maximum = max(maximum, float(error.max()))
        theta = np.linspace(0, np.pi / 2, 401)
        circle = 100 * np.column_stack((np.cos(theta), np.sin(theta)))
        result = smooth_line(circle, sample_spacing=step)
        radial = float(abs(np.linalg.norm(result.points, axis=1) - 100).max())
        results[str(step)] = {
            "maximum_plane_error_deg": maximum,
            "circle_radial_error_px": radial,
            "passes": maximum <= 1e-7 and radial <= 0.5,
        }
    return results


def pack_control(name: str, source: Path, pack: Path, out: Path) -> dict:
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection

    report = json.loads((source / "summary.json").read_text(encoding="utf-8"))["packs"][name]
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    vector = source / f"{name}-triangular.line.npy"
    digest = hashlib.sha256(vector.read_bytes()).hexdigest()
    if digest != manifest["artifact_sha256"][vector.name]:
        raise ValueError("accepted vector checksum changed")
    old = json.loads(
        (source.parent / "continuous-river-pilot-20261115/summary.json").read_text(encoding="utf-8")
    )["packs"][name]
    spacing = old["spacing_km"]
    raw = points_from_segments(np.load(vector), report["paths"], spacing)
    anchors = shared_junctions(raw)
    height = np.load(pack / "refined-out/height.pre-equilibrium.npy", mmap_mode="r")
    land = np.asarray(Image.open(pack / "refined-out/land.png")) > 0
    lake = np.asarray(Image.open(pack / "refined-out/lake.png")) > 0
    stop = frame(height.shape) | ~land | lake
    assert all(preserves_first_water_touch(path, stop) for path in raw)
    result = {
        "source_sha256": digest,
        "source_paths": len(raw),
        "junction_occurrences": sum(map(len, anchors)),
        "baseline_d8": report["direction_stats"]["d8-original"],
        "variants": {},
    }
    groups = [raw]
    labels = ["Accepted triangular traces"]
    raw_segments, raw_stats = stats_for(raw, spacing)
    result["raw_triangular"] = raw_stats
    for step in (1.0, 2.0):
        candidates, rejected, maximum = [], 0, 0.0
        for path, fixed in zip(raw, anchors, strict=True):
            candidate = smooth_line(path, sample_spacing=step, anchors=fixed)
            if not preserves_first_water_touch(candidate.points, stop):
                points = path
                rejected += 1
            else:
                points = candidate.points
                maximum = max(maximum, candidate.maximum_offset)
            np.testing.assert_array_equal(points[[0, -1]], path[[0, -1]])
            assert all((points == path[i]).all(axis=1).any() for i in fixed)
            candidates.append(points)
        segments, stats = stats_for(candidates, spacing)
        np.save(out / f"{name}-sample-{step:.0f}px.line.npy", segments)
        result["variants"][str(step)] = {
            "maximum_offset_px": maximum,
            "first_water_rejected_paths": rejected,
            "endpoints_and_junctions_exact": True,
            "first_water_touch_passes": True,
            "direction_stats": stats,
            "direction_improves_against_d8": stats["within_5deg_of_grid_percent"]
            < result["baseline_d8"]["within_5deg_of_grid_percent"],
        }
        groups.append(candidates)
        labels.append(f"{step:g}-pixel samples; {rejected} retain original")
    fig, axes = plt.subplots(1, 3, figsize=(15, 5), sharex=True, sharey=True)
    for ax, group, label in zip(axes, groups, labels, strict=True):
        ax.imshow(height, cmap="gray")
        lines = [np.column_stack((p[:, 0], height.shape[0] - 1 - p[:, 1])) for p in group]
        ax.add_collection(LineCollection(lines, colors="#1684dc", linewidths=0.8))
        ax.set_title(label)
    fig.tight_layout()
    fig.savefig(out / f"{name}-overview.png", dpi=170)
    plt.close(fig)
    # Show the same held valley used by the preceding acceptance screenshot.
    oldstop = max((q for q in old["paths"] if q["status"] != "absorbed"), key=lambda q: q["steps"])[
        "end_rc"
    ]
    fig, axes = plt.subplots(1, 3, figsize=(15, 5), sharex=True, sharey=True)
    for ax, group, label in zip(axes, groups, labels, strict=True):
        ax.imshow(height, cmap="gray")
        lines = [np.column_stack((p[:, 0], height.shape[0] - 1 - p[:, 1])) for p in group]
        ax.add_collection(LineCollection(lines, colors="#1684dc", linewidths=1))
        ax.set_xlim(max(0, oldstop[1] - 24), min(height.shape[1] - 1, oldstop[1] + 24))
        ax.set_ylim(min(height.shape[0] - 1, oldstop[0] + 24), max(0, oldstop[0] - 24))
        ax.set_title(label)
    fig.tight_layout()
    fig.savefig(out / f"{name}-detail.png", dpi=170)
    plt.close(fig)
    print(
        name,
        {
            key: row["direction_stats"]["within_5deg_of_grid_percent"]
            for key, row in result["variants"].items()
        },
        flush=True,
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pack", action="append", default=[])
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    report = {
        "controls": controls(),
        "packs": {},
        "hydrological_graph": "unchanged",
        "maximum_offset_px": 0.5,
    }
    for entry in args.pack:
        name, path = entry.split("=", 1)
        report["packs"][name] = pack_control(name, args.source, Path(path), args.out)
    report["variants_pass"] = {
        str(step): all(
            row["variants"][str(step)]["direction_improves_against_d8"]
            for row in report["packs"].values()
        )
        and report["controls"][str(step)]["passes"]
        for step in (1.0, 2.0)
    }
    (args.out / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(report["variants_pass"]), flush=True)


if __name__ == "__main__":
    main()
