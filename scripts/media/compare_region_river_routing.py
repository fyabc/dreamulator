"""Run the actual region orchestrator on frozen donors and compare complete networks."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import types
from pathlib import Path

import numpy as np
from numba import njit

from dreamulator.map import prog_erosion
from dreamulator.map.river_routing import accumulate
from dreamulator.media import terrain_refine
from dreamulator.media.terrain_blend import RefinementMode
from scripts.media.compare_constrained_receivers import window_crossings
from scripts.media.compare_river_window_algorithms import clip
from scripts.media.diagnose_river_directions import DirectionStats


@njit(cache=True)
def count_raw_crossings(vertices: np.ndarray, rows: int, columns: int) -> int:
    """Check strict intersections independently using integer orientation signs."""
    heads = np.full(rows * columns, -1, dtype=np.int64)
    links = np.full(len(vertices), -1, dtype=np.int64)
    for i in range(len(vertices)):
        x, y = vertices[i, 0]
        cell = y * columns + x
        links[i] = heads[cell]
        heads[cell] = i
    hits = 0
    for i in range(len(vertices)):
        ax, ay = vertices[i, 0]
        bx, by = vertices[i, 1]
        assert max(abs(bx - ax), abs(by - ay)) <= 2
        for y in range(max(0, ay - 4), min(rows, ay + 5)):
            for x in range(max(0, ax - 4), min(columns, ax + 5)):
                j = heads[y * columns + x]
                while j >= 0:
                    if j > i:
                        cx, cy = vertices[j, 0]
                        dx, dy = vertices[j, 1]
                        o1 = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
                        o2 = (bx - ax) * (dy - ay) - (by - ay) * (dx - ax)
                        o3 = (dx - cx) * (ay - cy) - (dy - cy) * (ax - cx)
                        o4 = (dx - cx) * (by - cy) - (dy - cy) * (bx - cx)
                        if o1 * o2 < 0 and o3 * o4 < 0:
                            hits += 1
                    j = links[j]
    return hits


def baseline_module() -> types.ModuleType:
    source = subprocess.check_output(
        ["git", "show", "f838893:src/dreamulator/media/terrain_refine.py"],
        text=True,
        encoding="utf-8",
    )
    module = types.ModuleType("dreamulator.media._region_routing_baseline")
    module.__package__ = "dreamulator.media"
    sys.modules[module.__name__] = module
    exec(compile(source, "f838893/terrain_refine.py", "exec"), module.__dict__)
    return module


def copy_pack(source: Path, target: Path) -> dict:
    target.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source / "input", target / "input", dirs_exist_ok=True)
    out = target / "refined-out"
    out.mkdir(exist_ok=True)
    for name in ("meta.json", "height.donor.npy"):
        shutil.copy2(source / "refined-out" / name, out / name)
    return json.loads((out / "meta.json").read_text(encoding="utf-8"))


def main() -> None:
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--previous", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    baseline = baseline_module()
    previous = json.loads((args.previous / "summary.json").read_text(encoding="utf-8"))
    bounds_external = previous["bounds_col_row_px"]
    cases = [
        ("alps", "earth_alps_360m", "pack"),
        ("external", "external_350m", "pack"),
        ("nacrea", "nacrea_coarse_50km_full", "pack"),
        ("external_redraw", "external_350m", "redraw-pack"),
    ]
    report = {
        "baseline_commit": "f838893",
        "qa_river_threshold": 64,
        "default_river_threshold_unchanged": True,
        "cases": {},
    }
    real_segments = prog_erosion.river_segments
    real_flood = prog_erosion.priority_flood
    captured = {}
    prepared = {}

    def capture_flood(height, land, **kwargs):
        result = real_flood(height, land, **kwargs)
        prepared.update(order=result[1].copy(), land=land.copy())
        return result

    def capture(rivers, receiver, acc, spacing, **kwargs):
        captured.clear()
        captured.update(
            rivers=rivers.copy(),
            receiver=receiver.copy(),
            acc=acc.copy(),
            spacing=spacing,
            month=kwargs.get("month_active"),
            lake=kwargs.get("lake"),
            lake_descend=kwargs.get("lake_descend"),
        )
        return real_segments(rivers, receiver, acc, spacing, **kwargs)

    prog_erosion.river_segments = capture
    prog_erosion.priority_flood = capture_flood
    fig, axes = plt.subplots(len(cases), 2, figsize=(12, 6 * len(cases)))
    try:
        for row, (name, directory, pack_name) in enumerate(cases):
            old_source = args.source / directory / pack_name
            info, products = {}, {}
            for key, module in (("baseline", baseline), ("two_ring", terrain_refine)):
                target = args.out / name / key / "pack"
                meta = copy_pack(old_source, target)
                mode = RefinementMode(meta["mode"])
                kwargs = {"mode": mode, "reuse_height": True, "river_threshold": 64}
                if mode == RefinementMode.BLEND:
                    cache = meta["cache_contract"]
                    kwargs.update(
                        native_resolution_km=cache["native_resolution_km"],
                        preserve_wavelength_km=cache["preserve_wavelength_km"],
                        depth_cap=cache["cap_depression_depth"],
                    )
                module.refine_region_pack(target, None, **kwargs)
                out = target / "refined-out"
                output_meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
                lines = np.load(out / "rivers.line.npy")
                flow = np.load(out / "rivers.flow.npy")
                regime = np.load(out / "rivers.regime.npy")
                assert len(lines) == len(flow) == len(regime)
                assert np.isfinite(lines).all() and np.isfinite(flow).all()
                height = np.load(out / "height.meters.npy")
                old_height = np.load(old_source / "refined-out/height.meters.npy")
                if mode == RefinementMode.BLEND:
                    np.testing.assert_array_equal(height, old_height)
                stats = DirectionStats()
                stats.add(lines[:, 1] - lines[:, 0])
                entry = {
                    "segments": len(lines),
                    "direction": stats.report(),
                    "height_sha256": hashlib.sha256(height.tobytes()).hexdigest(),
                    "source_bed_unchanged": bool(np.array_equal(height, old_height)),
                    "terminal_lakes": output_meta["terminal_lakes"],
                    "routing": output_meta.get("hydrology_routing", "D8 baseline"),
                    "regimes": np.unique(regime).tolist(),
                }
                source = prepared["land"].astype(np.float64)
                source[[0, -1], :] = 0
                source[:, [0, -1]] = 0
                receiver = captured["receiver"].ravel()
                graph_acc = accumulate(receiver, source)
                production_acc = prog_erosion.flow_accumulation(prepared["order"], receiver, source)
                np.testing.assert_allclose(production_acc, graph_acc, atol=0, rtol=0)
                residual = float(graph_acc.ravel()[receiver < 0].sum() - source.sum())
                assert residual == 0
                entry["unit_source_graph_residual"] = residual
                entry["production_vs_topological_accumulation_max_difference"] = float(
                    np.max(np.abs(production_acc - graph_acc))
                )
                entry["lake_records"] = len(output_meta["lakes"])
                if key == "two_ring":
                    lake = prog_erosion.keep_large_lakes(
                        captured["lake"],
                        prog_erosion.lake_mmu_cells(captured["spacing"]),
                        prog_erosion.LAKE_MIN_WIDTH_KM,
                        captured["spacing"],
                    )
                    cells = np.flatnonzero((captured["rivers"] & ~lake).ravel())
                    receiver = captured["receiver"].ravel()
                    isolated_sinks = cells[receiver[cells] < 0]
                    cells = cells[receiver[cells] >= 0]
                    down = receiver[cells]
                    incoming = np.bincount(down[down >= 0], minlength=height.size)
                    critical = np.unique(np.r_[cells[incoming[cells] != 1], down[down >= 0]])
                    # Raw receiver extraction must retain every routing station it visits.
                    xy = lines / captured["spacing"]
                    vertices = set(map(tuple, np.rint(xy.reshape(-1, 2)).astype(np.int64)))
                    np.testing.assert_allclose(xy, np.rint(xy), atol=2e-4, rtol=0)
                    absent = [
                        int(c)
                        for c in critical
                        if (
                            int(c % height.shape[1]),
                            int(height.shape[0] - 1 - c // height.shape[1]),
                        )
                        not in vertices
                    ]
                    missing = len(absent)
                    assert missing == 0, (name, missing, absent[:20])
                    entry["river_sink_cells"] = len(isolated_sinks)
                    entry["missing_receiver_stations"] = missing
                    crossings = count_raw_crossings(np.rint(xy).astype(np.int64), *height.shape)
                    assert crossings == 0, (name, crossings)
                    entry["complete_network_crossings"] = crossings
                info[key] = entry
                products[key] = lines
                ax = axes[row, 0 if key == "baseline" else 1]
                ax.imshow(height, cmap="gray")
                xy = lines / captured["spacing"]
                xy[:, :, 1] = height.shape[0] - 1 - xy[:, :, 1]
                ax.add_collection(LineCollection(xy, colors="#1684dc", linewidths=0.45))
                ax.set_title(f"{name}: {key}; complete region pipeline")
            if name == "external":
                detail, subs = plt.subplots(1, 2, figsize=(12, 6), sharex=True, sharey=True)
                c0, c1, r0, r1 = bounds_external
                local_height = height[int(r0) : int(r1) + 1, int(c0) : int(c1) + 1]
                for ax, key in zip(subs, ("baseline", "two_ring"), strict=True):
                    segments = products[key] / captured["spacing"]
                    segments = segments[:, :, ::-1] * [-1, 1] + [height.shape[0] - 1, 0]
                    cropped = clip(segments, bounds_external)
                    ax.imshow(
                        height,
                        cmap="gray",
                        vmin=float(local_height.min()),
                        vmax=float(local_height.max()),
                    )
                    ax.add_collection(
                        LineCollection(cropped[:, :, ::-1], colors="#1684dc", linewidths=1)
                    )
                    ax.set_xlim(*bounds_external[:2])
                    ax.set_ylim(bounds_external[3], bounds_external[2])
                    ax.set_title(f"Complete river extraction: {key}")
                    stats = DirectionStats()
                    stats.add((cropped[:, 1] - cropped[:, 0])[:, ::-1])
                    info[key]["fixed_window_direction"] = stats.report()
                    info[key]["fixed_window_crossings"] = len(window_crossings(cropped))
                    np.save(args.out / f"external-{key}.window-rc.line.npy", cropped)
                detail.tight_layout()
                detail.savefig(args.out / "external-detail.png", dpi=180)
                plt.close(detail)
                assert info["two_ring"]["fixed_window_crossings"] == 0
            report["cases"][name] = info
            print(
                name,
                {k: v["direction"]["within_5deg_of_grid_percent"] for k, v in info.items()},
                flush=True,
            )
    finally:
        prog_erosion.river_segments = real_segments
        prog_erosion.priority_flood = real_flood
    fig.tight_layout()
    fig.savefig(args.out / "networks.png", dpi=150)
    plt.close(fig)
    (args.out / "summary.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
