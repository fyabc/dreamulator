"""Run native-canvas CLI hydrology on frozen terrain and export routing acceptance figures."""

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
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dreamulator.map.prog_erosion import RUNOFF_REFERENCE_MM  # noqa: E402
from dreamulator.map.river_routing import accumulate  # noqa: E402
from dreamulator.map.td_canvas import CanvasGeometry  # noqa: E402
from dreamulator.media.canvas_pipeline import CanvasStore, canvas_flow_fields  # noqa: E402
from scripts.media.compare_region_river_routing import count_raw_crossings  # noqa: E402
from scripts.media.compare_river_window_algorithms import clip  # noqa: E402
from scripts.media.diagnose_river_directions import DirectionStats  # noqa: E402


def baseline() -> types.ModuleType:
    source = subprocess.check_output(
        ["git", "show", "16bc63d:src/dreamulator/media/canvas_pipeline.py"],
        text=True,
        encoding="utf-8",
    )
    module = types.ModuleType("dreamulator.media._canvas_d8_reference")
    module.__package__ = "dreamulator.media"
    sys.modules[module.__name__] = module
    exec(compile(source, "16bc63d/canvas_pipeline.py", "exec"), module.__dict__)
    return module


def make_canvas(root: Path, height: np.ndarray, tile: int) -> CanvasStore:
    root.mkdir(parents=True)
    (root / "chunks").mkdir()
    (root / "climate").mkdir()
    geom = CanvasGeometry(0, 0, 6371, 2)
    keys = [(r, c) for r in range(len(height) // tile) for c in range(len(height) // tile)]
    (root / "canvas.json").write_text(
        json.dumps({"geometry": geom.to_dict(), "chunks": keys}, indent=2) + "\n",
        encoding="utf-8",
    )
    for r, c in keys:
        np.save(
            root / "chunks" / f"r{r:03d}_c{c:03d}.npy",
            height[r * tile : (r + 1) * tile, c * tile : (c + 1) * tile],
        )
    for name, value in (
        ("runoff.mm", RUNOFF_REFERENCE_MM),
        ("precipitation.mm", 1200),
        ("temperature.C", 20),
        ("lake_evaporation.mm", 400),
    ):
        np.save(root / "climate" / f"{name}.npy", np.full((2, 2), value, np.float32))
    np.save(
        root / "climate/runoff_monthly.mm.npy",
        np.full((12, 2, 2), RUNOFF_REFERENCE_MM / 12, np.float32),
    )
    np.save(root / "climate/precipitation_monthly.mm.npy", np.full((12, 2, 2), 100, np.float32))
    np.save(
        root / "climate/lake_evaporation_monthly.mm.npy", np.full((12, 2, 2), 400 / 12, np.float32)
    )
    return CanvasStore.load(root)


def main() -> None:
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--window-spec", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    scratch = args.out / "work"
    if scratch.exists():
        shutil.rmtree(scratch)
    physical = args.pack / "refined-out/height.pre-equilibrium.npy"
    original = np.load(physical)
    # Native canvases use 23 km / 256 pixels. This external image has assumed placement,
    # so resample it onto a 46 km canvas and record both geometries explicitly.
    resized = np.asarray(Image.fromarray(original).resize((512, 512), Image.Resampling.BILINEAR))
    height = np.rint(resized).astype(np.int16)
    original_meta = json.loads((args.pack / "input/meta.json").read_text(encoding="utf-8"))
    bounds = np.asarray(
        json.loads(args.window_spec.read_text(encoding="utf-8"))["bounds_col_row_px"]
    ) * (512 / original.shape[0])
    sets = []
    report = {
        "source_height_sha256": hashlib.sha256(physical.read_bytes()).hexdigest(),
        "source_span_km": original_meta["span_km"],
        "source_shape": list(original.shape),
        "canvas_span_km": 46,
        "canvas_shape": [512, 512],
        "km_per_px": 23 / 256,
        "terrain_preparation": "bilinear resample, nearest integer metre, assumed 46 km placement",
        "climate": "uniform QA forcing; annual runoff reference, monthly runoff reference / 12",
        "bounds_col_row_px": bounds.tolist(),
        "runs": {},
    }
    reference_products = None
    for tile, solver in ((128, "in-memory"), (128, "out-of-core"), (256, "out-of-core")):
        name = f"{solver}-{tile}"
        store = make_canvas(scratch / name, height, tile)
        if reference_products is None:
            old = baseline()
            old.run_canvas_fill(store, workers=1, verbose=False)
            old.run_canvas_rivers(store, threshold_cells=64, verbose=False)
            sets.append(("D8 reference", np.load(store.root / "hydro/rivers.line.npy")))
        command = [
            sys.executable,
            "-c",
            "from dreamulator.cli import app; app()",
            "canvas",
            "hydrology",
            str(store.root),
            f"--{solver}",
            "--force",
            "--workers",
            "1",
            "--river-threshold",
            "64",
        ]
        subprocess.run(command, check=True)
        products = {
            kind: np.load(store.root / "hydro" / f"rivers.{kind}.npy")
            for kind in ("line", "flow", "regime")
        }
        if reference_products is None:
            reference_products = products
        else:
            for kind, array in products.items():
                np.testing.assert_array_equal(array, reference_products[kind])
        meta = json.loads((store.root / "hydro/rivers.meta.json").read_text(encoding="utf-8"))
        assert meta["routing"] == "constrained-two-ring-v1"
        z, _dem, rec, _acc, land, _order, _weight, _inland = canvas_flow_fields(
            store, two_ring=True
        )
        unit = accumulate(rec, land.astype(np.float64))
        residual = float(unit.ravel()[rec < 0].sum() - land.sum())
        assert residual == 0
        vertices = products["line"].astype(np.float64) / store.geometry.px_km
        vertices[:, :, 1] = len(height) - 1 - vertices[:, :, 1]
        crossing_count = int(count_raw_crossings(np.rint(vertices).astype(np.int64), 512, 512))
        assert crossing_count == 0
        sets.append((f"Two-ring {name}", products["line"]))
        report["runs"][name] = {
            "cli_command": command[3:5] + ["<canvas>"] + command[6:],
            "metadata": meta,
            "unit_source_budget_residual": residual,
            "raw_river_crossings": crossing_count,
            "river_geometry_flow_and_regime_equal": True,
        }
        print(name, meta["routing_stats"], "segments", len(products["line"]), flush=True)
        del z, rec, unit
    fig, axes = plt.subplots(2, 4, figsize=(20, 10))
    for col, (name, lines) in enumerate(sets):
        xy = lines.astype(np.float64) / (23 / 256)
        xy[:, :, 1] = len(height) - 1 - xy[:, :, 1]
        rowcol = xy[:, :, ::-1]
        local_lines = clip(rowcol, bounds.tolist())
        stats = DirectionStats()
        stats.add((local_lines[:, 1] - local_lines[:, 0]) * (23 / 256))
        report["runs"].setdefault(name, {})["detail_direction"] = stats.report()
        for row in (0, 1):
            ax = axes[row, col]
            ax.imshow(height, cmap="gray", vmin=0, vmax=800)
            ax.add_collection(
                LineCollection(xy, colors="#1684dc", linewidths=0.4 if row == 0 else 1)
            )
            if row:
                ax.set_xlim(bounds[0], bounds[1])
                ax.set_ylim(bounds[3], bounds[2])
            else:
                ax.set_xlim(0, 511)
                ax.set_ylim(511, 0)
            ax.set_title(name)
    fig.tight_layout()
    fig.savefig(args.out / "comparison.png", dpi=160)
    plt.close(fig)
    (args.out / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    shutil.rmtree(scratch)


if __name__ == "__main__":
    main()
