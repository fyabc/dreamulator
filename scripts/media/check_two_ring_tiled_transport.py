"""Replay a resolved regional receiver graph through tiled accumulation and river extraction."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image

from dreamulator.map.prog_erosion import (
    LAKE_MIN_WIDTH_KM,
    keep_large_lakes,
    lake_mask,
    lake_mmu_cells,
    priority_flood,
    river_segments,
    river_segments_from_graph,
)
from dreamulator.map.river_routing import accumulate, two_ring_receivers
from dreamulator.media.canvas_flow_tiled import (
    FLOW_OFFSETS,
    load_chunk,
    save_chunk,
    tiled_accumulation,
)
from dreamulator.media.canvas_lakes_tiled import Components
from dreamulator.media.canvas_rivers_tiled import tiled_channel_graph
from dreamulator.media.lake_masks import lake_footprint


def main() -> None:
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--window-spec", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    physical_path = args.pack / "refined-out/height.pre-equilibrium.npy"
    height = np.load(physical_path)
    land = np.asarray(Image.open(args.pack / "refined-out/land.png")) > 0
    meta = json.loads((args.pack / "input/meta.json").read_text(encoding="utf-8"))
    spacing = float(meta["span_km"]) / height.shape[0]
    filled, order, base = priority_flood(height, land, eps=0)
    lakes = keep_large_lakes(
        lake_footprint(lake_mask(filled, height), filled, height),
        lake_mmu_cells(spacing),
        LAKE_MIN_WIDTH_KM,
        spacing,
    )
    assert not lakes.any(), "The replay sample must have no lake budget changes."
    receiver, stats = two_ring_receivers(filled, land, base, lakes)
    source = land.astype(np.float64)
    source[[0, -1], :] = 0
    source[:, [0, -1]] = 0
    reference = accumulate(receiver, source)
    rows, columns = height.shape
    rr, cc = np.indices(height.shape)
    target = np.maximum(receiver.reshape(height.shape), 0)
    dr, dc = target // columns - rr, target % columns - cc
    code = np.full(height.shape, 255, np.uint8)
    for k, (dy, dx) in enumerate(FLOW_OFFSETS):
        code[(receiver.reshape(height.shape) >= 0) & (dr == dy) & (dc == dx)] = k
    assert ((code.ravel() != 255) == (receiver >= 0)).all()
    # Replay supplies the known Priority-Flood order as exact integer sort labels.
    # These labels are diagnostic ordering data; they are not physical elevations.
    labels = np.full(height.size, -1, np.float32)
    valid = order[order >= 0]
    labels[valid] = np.arange(valid.size)
    labels = labels.reshape(height.shape)
    source_lines = river_segments(
        land & (reference > 64), receiver, reference, spacing, smooth=False
    )
    bounds = json.loads(args.window_spec.read_text(encoding="utf-8"))["bounds_col_row_px"]
    fig, axes = plt.subplots(1, 3, figsize=(15, 5), sharex=True, sharey=True)
    report = {
        "source_height_sha256": hashlib.sha256(physical_path.read_bytes()).hexdigest(),
        "routing": stats,
        "source_cells": int(source.sum()),
        "ordering": "diagnostic Priority-Flood rank labels; physical terrain unchanged",
        "direction_selection": "accepted in-memory receiver graph replayed into tiled consumers",
        "tiles": {},
    }

    def draw(ax, lines, title):
        local = height[int(bounds[2]) : int(bounds[3]) + 1, int(bounds[0]) : int(bounds[1]) + 1]
        ax.imshow(height, cmap="gray", vmin=local.min(), vmax=local.max())
        xy = lines / spacing
        xy[:, :, 1] = rows - 1 - xy[:, :, 1]
        ax.add_collection(LineCollection(xy, colors="#1684dc", linewidths=1))
        ax.set_xlim(*bounds[:2])
        ax.set_ylim(bounds[3], bounds[2])
        ax.set_title(title)

    draw(axes[0], source_lines[0], "Whole-grid receiver graph")
    for i, tile in enumerate((128, 256), 1):
        assert rows % tile == columns % tile == 0
        keys = [(r, c) for r in range(rows // tile) for c in range(columns // tile)]
        scratch = args.out / f"scratch-{tile}"
        store = SimpleNamespace(
            root=scratch, work=scratch / "work", tile=tile, chunks=keys, increments=None
        )
        for key in keys:
            r, c = key
            part = np.s_[r * tile : (r + 1) * tile, c * tile : (c + 1) * tile]
            for kind, array in (
                ("graded", labels),
                ("dir", code),
                ("dir_route", code),
                ("land2", land.astype(np.uint8)),
                ("source", source),
            ):
                save_chunk(store, kind, key, array[part])
            save_chunk(store, "lbl_lakes0", key, np.zeros((tile, tile), np.int32))
        tiled_accumulation(store, "source", float64=True, workers=1)
        actual = np.zeros(height.shape, np.float64)
        for r, c in keys:
            actual[r * tile : (r + 1) * tile, c * tile : (c + 1) * tile] = load_chunk(
                store, "acc_source", (r, c)
            )
        np.testing.assert_array_equal(actual, reference)
        z = np.zeros(1, np.int64)
        comps = Components(0, z.copy(), z.copy(), z.copy(), z.copy(), z.copy())
        graph = tiled_channel_graph(
            store,
            comps,
            threshold_cells=64,
            mmu_cells=lake_mmu_cells(spacing),
            km_per_px=spacing,
            pixel_rows=rows,
            acc_kind="acc_source",
            month_kind=None,
            has_descent=False,
            workers=1,
        )
        lines = river_segments_from_graph(graph, smooth=False)
        for a, b in zip(lines, source_lines, strict=True):
            np.testing.assert_array_equal(a, b)
        residual = float(actual.ravel()[receiver < 0].sum() - source.sum())
        assert residual == 0
        report["tiles"][str(tile)] = {
            "chunks": len(keys),
            "accumulation_max_difference": float(np.max(np.abs(actual - reference))),
            "unit_source_budget_residual": residual,
            "river_segments": len(lines[0]),
            "river_geometry_flow_and_regime_equal": True,
        }
        draw(axes[i], lines[0], f"Tiled replay: {tile} px tiles")
        shutil.rmtree(scratch)
        print(tile, report["tiles"][str(tile)], flush=True)
    fig.tight_layout()
    fig.savefig(args.out / "comparison.png", dpi=160)
    plt.close(fig)
    (args.out / "summary.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
