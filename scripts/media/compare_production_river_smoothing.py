"""Isolate production drawing changes on one fixed D8 graph per held terrain."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import types
from pathlib import Path

import numpy as np
from PIL import Image

from dreamulator.map.prog_erosion import flow_accumulation, priority_flood
from dreamulator.map.prog_erosion import river_segments as production_segments
from scripts.media import bounded_river_lines
from scripts.media.compare_dinf_routing import frame
from scripts.media.diagnose_river_directions import DirectionStats


def baseline_module() -> types.ModuleType:
    source = subprocess.run(
        ["git", "show", "f838893:src/dreamulator/map/prog_erosion.py"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    module = types.ModuleType("dreamulator.map._drawing_baseline")
    module.__package__ = "dreamulator.map"
    sys.modules[module.__name__] = module
    exec(compile(source, "f838893/prog_erosion.py", "exec"), module.__dict__)
    return module


def pack_control(
    name: str, pack: Path, previous: Path, out: Path, baseline: types.ModuleType
) -> dict:
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection

    held = json.loads((previous / "summary.json").read_text(encoding="utf-8"))["packs"][name]
    height = np.load(pack / "refined-out/height.pre-equilibrium.npy")
    land = np.asarray(Image.open(pack / "refined-out/land.png")) > 0
    lake = np.asarray(Image.open(pack / "refined-out/lake.png")) > 0
    stop = frame(height.shape) | ~land | lake
    _, order, receiver = priority_flood(height, ~stop, eps=1e-4)
    weight = (~stop).astype(float)
    acc = flow_accumulation(order, receiver, weight)
    rivers = (~stop) & (acc > 64)
    spacing = held["spacing_km"]
    arrays = (receiver, acc, rivers, lake)
    digests = [hashlib.sha256(a.tobytes()).hexdigest() for a in arrays]
    old, old_flow, old_regime = baseline.river_segments(rivers, receiver, acc, spacing, lake=lake)
    new, new_flow, new_regime = production_segments(rivers, receiver, acc, spacing, lake=lake)
    assert digests == [hashlib.sha256(a.tobytes()).hexdigest() for a in arrays]
    assert len(new) == len(new_flow) == len(new_regime)
    assert np.isfinite(new).all() and np.isfinite(new_flow).all()
    assert set(np.unique(old_regime)) == set(np.unique(new_regime))
    cells = np.flatnonzero(rivers.ravel())
    targets = receiver[cells]
    incoming = np.bincount(targets[targets >= 0], minlength=height.size)
    heads = cells[incoming[cells] == 0]
    junctions = cells[incoming[cells] > 1]
    outlets = targets[(targets >= 0) & ~rivers.ravel()[np.maximum(targets, 0)]]
    critical = np.unique(np.r_[heads, junctions, outlets])
    coordinates = [
        (int(c % height.shape[1]), int(height.shape[0] - 1 - c // height.shape[1]))
        for c in critical
    ]
    old_vertices = set(map(tuple, np.round(old.reshape(-1, 2) / spacing, 8)))
    new_vertices = set(map(tuple, np.round(new.reshape(-1, 2) / spacing, 8)))
    missing_old = sum(p not in old_vertices for p in coordinates)
    missing_new = sum(p not in new_vertices for p in coordinates)
    assert missing_new == 0
    stats = {}
    for label, segments, flows, regimes in (
        ("baseline", old, old_flow, old_regime),
        ("d8_simple", new, new_flow, new_regime),
    ):
        direction = DirectionStats()
        direction.add(segments[:, 1] - segments[:, 0])
        stats[label] = direction.report()
        np.save(out / f"{name}-{label}.line.npy", segments.astype(np.float32))
        np.save(out / f"{name}-{label}.flow.npy", flows.astype(np.float32))
        np.save(out / f"{name}-{label}.regime.npy", regimes)
    centre = max((p for p in held["paths"] if p["status"] != "absorbed"), key=lambda p: p["steps"])[
        "end_rc"
    ]
    for detail in (False, True):
        fig, axes = plt.subplots(1, 2, figsize=(10, 5), sharex=True, sharey=True)
        for ax, segments, title in zip(
            axes,
            (old, new),
            ("Existing production D8 drawing", "D8 + bounded simple smoothing"),
            strict=True,
        ):
            ax.imshow(height, cmap="gray")
            xy = segments / spacing
            xy[:, :, 1] = height.shape[0] - 1 - xy[:, :, 1]
            ax.add_collection(
                LineCollection(xy, colors="#1684dc", linewidths=0.9 if detail else 0.5)
            )
            if detail:
                ax.set_xlim(centre[1] - 24, centre[1] + 24)
                ax.set_ylim(centre[0] + 24, centre[0] - 24)
            ax.set_title(title)
        fig.tight_layout()
        fig.savefig(out / f"{name}-{'detail' if detail else 'overview'}.png", dpi=170)
        plt.close(fig)
    report = {
        "direction_stats": stats,
        "same_graph_and_water_fields_unchanged": True,
        "water_budget_relative_residual": abs(float(acc[stop].sum() - weight.sum())) / weight.sum(),
        "river_cells": len(cells),
        "heads": len(heads),
        "junctions": len(junctions),
        "unique_outlets": len(np.unique(outlets)),
        "critical_nodes": len(critical),
        "missing_critical_nodes_baseline": missing_old,
        "missing_critical_nodes_simple": missing_new,
        "segment_count_ratio": len(new) / len(old),
        "input_array_sha256": digests,
    }
    print(name, {k: v["within_5deg_of_grid_percent"] for k, v in stats.items()}, flush=True)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pack", action="append", default=[])
    parser.add_argument("--sample-spacing-px", type=float, choices=(1.0, 2.0), default=2.0)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    # This is a fixed-scale research comparison, not a production user option.
    original = bounded_river_lines.smooth_line

    def candidate(points: np.ndarray, **kwargs: object) -> object:
        kwargs["sample_spacing"] = float(kwargs["sample_spacing"]) * args.sample_spacing_px / 2
        return original(points, **kwargs)

    bounded_river_lines.smooth_line = candidate
    import dreamulator.map.prog_erosion as production

    production.river_segments_from_graph = bounded_river_lines.bounded_segments_from_graph
    baseline = baseline_module()
    report = {
        "baseline_commit": "f838893",
        "threshold_cells": 64,
        "sample_spacing_px": args.sample_spacing_px,
        "maximum_offset_px": 0.5,
        "packs": {},
    }
    for entry in args.pack:
        name, path = entry.split("=", 1)
        report["packs"][name] = pack_control(name, Path(path), args.previous, args.out, baseline)
    (args.out / "summary.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
