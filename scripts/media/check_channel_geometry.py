"""Check mean-flow channel estimates and sediment-export inventories on saved canvases.

This research command produces figures and a report. It does not install terrain
increments, synthesize flood discharge, or build a delta from a cropped sediment budget.
Run from the repository root with explicit --canvas, --coast-canvas, and --out paths.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import LineCollection
from matplotlib.colors import LightSource, ListedColormap
from matplotlib.ticker import NullFormatter

from dreamulator.map.prog_erosion import RUNOFF_REFERENCE_MM
from dreamulator.map.surface_process import (
    SEDIMENT_EXPORT_CATEGORIES,
    SurfaceProcessParams,
    run_surface_process,
)
from dreamulator.media.canvas_pipeline import (
    CanvasStore,
    _geological_ocean,
    _mesh_sea_lake_interior,
)
from dreamulator.media.canvas_surface_process import coarse_sea
from scripts.geology.channel_geometry import (
    fit_mean_channel_geometry,
    mean_channel_geometry,
    reference_accumulation_to_discharge,
)


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def observation_check(path: Path, out: Path) -> tuple[Any, dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    groups = {}
    for use in ("calibration", "validation"):
        subset = [row for row in rows if row["use"] == use]
        groups[use] = tuple(
            np.array([float(row[field]) * factor for row in subset])
            for field, factor in (
                ("discharge_cfs", 0.3048**3),
                ("width_ft", 0.3048),
                ("mean_depth_ft", 0.3048),
            )
        )
    calibration = fit_mean_channel_geometry(*groups["calibration"])
    summary: dict[str, Any] = {"calibration": asdict(calibration), "groups": {}}
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.6), layout="constrained")
    for use, (q, w, d) in groups.items():
        geometry = mean_channel_geometry(q, calibration)
        metrics = {}
        for name, predicted, observed, ax in zip(
            ("width", "mean_depth"),
            (geometry.width_m, geometry.mean_depth_m),
            (w, d),
            axes,
            strict=True,
        ):
            ratio = predicted / observed
            median_error = float(np.median(np.abs(ratio - 1)))
            within_factor_two = float(np.mean((ratio >= 0.5) & (ratio <= 2)))
            metrics[name] = {
                "median_absolute_relative_error": median_error,
                "within_factor_two_fraction": within_factor_two,
                "rough_estimate_pass": median_error <= 0.5 and within_factor_two >= 0.8,
            }
            ax.scatter(observed, predicted, label=f"{use} (n={q.size})", alpha=0.8, s=24)
        summary["groups"][use] = {"stations": int(q.size), **metrics}
    for ax, label in zip(axes, ("Width", "Mean depth"), strict=True):
        points = np.concatenate(
            [np.asarray(collection.get_offsets()) for collection in ax.collections]
        )
        lo = float(points.min()) * 0.8
        hi = float(points.max()) * 1.2
        x = np.geomspace(lo, hi, 100)
        ax.plot(x, x, color="black", linewidth=1)
        ax.fill_between(x, x / 2, 2 * x, color="grey", alpha=0.12)
        ax.set(
            xscale="log",
            yscale="log",
            xlabel=f"Observed {label.lower()} (m)",
            ylabel=f"Estimated {label.lower()} (m)",
            title=f"{label} at mean annual flow",
            xlim=(lo, hi),
            ylim=(lo, hi),
        )
        ax.legend(fontsize=8)
        ax.grid(alpha=0.2)
        ticks = [5, 10, 20, 50, 100, 200] if label == "Width" else [0.2, 0.5, 1, 2, 5]
        tick_labels = [f"{value:g}" for value in ticks]
        ax.set_xticks(ticks, labels=tick_labels)
        ax.set_yticks(ticks, labels=tick_labels)
        ax.xaxis.set_minor_formatter(NullFormatter())
        ax.yaxis.set_minor_formatter(NullFormatter())
    fig.savefig(out / "earth-width-depth.png", dpi=180)
    plt.close(fig)
    summary["excluded_stations"] = [row for row in rows if row["use"] == "excluded"]
    summary["acceptance_rule"] = (
        "For a rough estimate, held-out median absolute relative error must be at most "
        "50%, and at least 80% of observations must be within a factor of two."
    )
    return calibration, summary


def river_check(canvas: Path, calibration: Any, out: Path) -> dict[str, Any]:
    hydro = canvas / "hydro"
    meta = json.loads((hydro / "rivers.meta.json").read_text(encoding="utf-8"))
    if meta["weight_source"] != "runoff.mm":
        raise ValueError("This check requires the physical annual reference-runoff weights.")
    flow = np.load(hydro / "rivers.flow.npy", mmap_mode="r")
    lines = np.load(hydro / "rivers.line.npy", mmap_mode="r")
    if lines.shape != (flow.size, 2, 2):
        raise ValueError("River geometries and flow records must match.")
    pixel_m = meta["km_per_px"] * 1000
    totals = np.zeros(4, dtype=np.int64)
    best = (np.inf, -1)
    max_width = 0.0
    for start in range(0, flow.size, 100_000):
        a = np.asarray(flow[start : start + 100_000], dtype=float)
        q = reference_accumulation_to_discharge(a, pixel_m, RUNOFF_REFERENCE_MM)
        g = mean_channel_geometry(q, calibration)
        totals += [
            a.size,
            np.count_nonzero(g.width_m >= pixel_m),
            np.count_nonzero(g.width_m >= 2 * pixel_m),
            np.count_nonzero(g.outside_calibration),
        ]
        max_width = max(max_width, float(g.width_m.max()))
        error = np.abs(q - 400.0)
        i = int(np.argmin(error))
        if error[i] < best[0]:
            best = (float(error[i]), start + i)
    store = CanvasStore.load(canvas, work=out / "read-work", surface="auto")
    center = lines[best[1]].mean(axis=0)
    col = int(round(center[0] / meta["km_per_px"]))
    row = store.geometry.size_px - 1 - int(round(center[1] / meta["km_per_px"]))
    ci, cj = row // store.tile, col // store.tile
    raw = store.raw(ci, cj)
    rr, cc = row % store.tile, col % store.tile
    half = 64
    r0, c0 = max(0, rr - half), max(0, cc - half)
    r1, c1 = min(store.tile, rr + half), min(store.tile, cc + half)
    terrain = raw[r0:r1, c0:c1]
    x0 = (cj * store.tile + c0) * meta["km_per_px"]
    x1 = (cj * store.tile + c1) * meta["km_per_px"]
    y0 = (store.geometry.size_px - 1 - (ci * store.tile + r1)) * meta["km_per_px"]
    y1 = (store.geometry.size_px - 1 - (ci * store.tile + r0)) * meta["km_per_px"]
    half_pixel_km = meta["km_per_px"] / 2
    # Match the terrain pixel centres to the integer river coordinates.
    x0, x1 = x0 - half_pixel_km, x1 - half_pixel_km
    y0, y1 = y0 + half_pixel_km, y1 + half_pixel_km
    local_lines, local_flow = [], []
    for start in range(0, flow.size, 100_000):
        segments = np.asarray(lines[start : start + 100_000], dtype=float)
        keep = (
            (segments[:, :, 0].min(axis=1) <= x1)
            & (segments[:, :, 0].max(axis=1) >= x0)
            & (segments[:, :, 1].min(axis=1) <= y1)
            & (segments[:, :, 1].max(axis=1) >= y0)
        )
        local_lines.append(segments[keep])
        local_flow.append(np.asarray(flow[start : start + 100_000][keep], dtype=float))
    segments = np.concatenate(local_lines)
    q = reference_accumulation_to_discharge(
        np.concatenate(local_flow), pixel_m, RUNOFF_REFERENCE_MM
    )
    widths = mean_channel_geometry(q, calibration).width_m
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.4), layout="constrained")
    shade = LightSource(315, 45).hillshade(terrain, dx=pixel_m, dy=pixel_m)
    for ax, title in zip(
        axes,
        ("Fixed display stroke (comparison)", "Estimated physical width; same river paths"),
        strict=True,
    ):
        ax.imshow(shade, cmap="Greys_r", extent=[x0, x1, y0, y1], origin="upper")
        ax.set(xlim=(x0, x1), ylim=(y0, y1), title=title, xlabel="Canvas x (km)")
        ax.set_aspect("equal")
    fig.canvas.draw()
    points_per_km = axes[1].get_window_extent().width * 72 / fig.dpi / (x1 - x0)
    axes[0].add_collection(
        LineCollection(segments, colors="#1077be", linewidths=1.0, capstyle="round")
    )
    axes[1].add_collection(
        LineCollection(
            segments, colors="#1077be", linewidths=widths / 1000 * points_per_km, capstyle="round"
        )
    )
    fig.savefig(out / "nacrea-width-comparison.png", dpi=200)
    plt.close(fig)
    np.savez_compressed(
        out / "river-window.npz",
        lines_km=segments,
        discharge_m3s=q,
        estimated_width_m=widths,
        terrain_m=terrain,
    )
    lat, lon = store.geometry.pixel_to_latlon(np.array([row]), np.array([col]))
    return {
        "segments": int(totals[0]),
        "pixel_m": pixel_m,
        "at_least_one_pixel_segments": int(totals[1]),
        "at_least_two_pixels_segments": int(totals[2]),
        "outside_calibration_segments": int(totals[3]),
        "max_estimated_width_m": max_width,
        "routing": meta.get("routing"),
        "surface": store.surface,
        "window": {
            "chunk": [ci, cj],
            "row_col": [row, col],
            "lat_lon_degrees": [float(lat[0]), float(lon[0])],
            "segments": int(q.size),
            "width_range_m": [float(widths.min()), float(widths.max())],
        },
        "window_height_files": [
            str(canvas / "chunks" / f"r{ci:03d}_c{cj:03d}.npy"),
            *(
                [str(store.increments / f"r{ci:03d}_c{cj:03d}.npy")]
                if store.increments is not None
                else []
            ),
        ],
        "count_basis": "Each saved segment is counted once; these are not river-length fractions.",
        "figure_basis": (
            "The left panel uses a fixed display stroke for comparison, "
            "not the production cartographic renderer."
        ),
    }


def plot_sediment_exports(
    z: np.ndarray, sea: np.ndarray, inventory: np.ndarray, pixel_m: float, out: Path
) -> None:
    """Draw the solver's shoreline and land-side exit cells on the saved input surface."""
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.7), layout="constrained")
    span = z.shape[0] * pixel_m / 1000
    extent = (0, span, span, 0)
    land_cmap = ListedColormap(plt.get_cmap("terrain")(np.linspace(0.25, 1, 256)))
    axes[0].imshow(
        np.ma.masked_where(~sea, z),
        cmap="Blues_r",
        vmin=min(float(np.nanmin(z)), -1.0),
        vmax=0,
        origin="upper",
        extent=extent,
    )
    axes[0].imshow(
        np.ma.masked_where(sea, z),
        cmap=land_cmap,
        vmin=0,
        vmax=max(float(np.nanmax(z)), 1.0),
        origin="upper",
        extent=extent,
    )
    centres = (np.arange(z.shape[0]) + 0.5) * pixel_m / 1000
    axes[0].contour(centres, centres, sea, levels=[0.5], colors="#222222", linewidths=0.6)
    axes[0].plot([], [], color="#222222", lw=0.8, label="Actual sea-land boundary")
    colors = ["#248bcc", "#e57c27", "#b25da8", "#555555"]
    for grid, name, color in zip(inventory, SEDIMENT_EXPORT_CATEGORIES, colors, strict=True):
        yy, xx = np.nonzero(grid > 0)
        axes[0].scatter(
            (xx + 0.5) * pixel_m / 1000,
            (yy + 0.5) * pixel_m / 1000,
            s=8,
            color=color,
            label=name.replace("_", " "),
        )
    land_fraction = float(np.mean(np.isfinite(z) & ~sea))
    axes[0].set(
        title=f"Sediment exit cells; land {land_fraction:.1%}", xlabel="x (km)", ylabel="y (km)"
    )
    axes[0].legend(fontsize=7)
    categories = inventory.sum(axis=(1, 2)) / 1e9
    axes[1].bar(range(4), categories, color=colors)
    axes[1].set_xticks(
        range(4), [name.replace("_", "\n") for name in SEDIMENT_EXPORT_CATEGORIES], fontsize=8
    )
    axes[1].set(
        ylabel="Cumulative eroded-bed-equivalent volume (km³)",
        title="50,000-year diagnostic crop; not a modern flux",
    )
    fig.savefig(out / "nacrea-sediment-exports.png", dpi=180)
    plt.close(fig)


def sediment_check(canvas: Path, key: tuple[int, int], out: Path) -> dict[str, Any]:
    store = CanvasStore.load(canvas, work=out / "coast-read-work", surface="auto")
    # Reuse one saved 90 m chunk, sampled at the erosion stage's eight-pixel scale.
    # The crop is a diagnostic domain, so its frame exports remain separate.
    factor = 8
    raw = store.raw(*key)
    z = np.ascontiguousarray(raw[::factor, ::factor])
    pixel_m = store.geometry.px_km * 1000 * factor
    row = key[0] * store.tile + np.arange(z.shape[0]) * factor
    col = key[1] * store.tile + np.arange(z.shape[1]) * factor
    coarse_indices = np.ix_(row // 256, col // 256)
    geological_ocean = _geological_ocean(canvas, store.geometry, 0.0)[coarse_indices]
    mesh_lakes = _mesh_sea_lake_interior(canvas, store.geometry)
    sea, _mesh_basin = coarse_sea(
        z, geological_ocean, None if mesh_lakes is None else mesh_lakes[coarse_indices]
    )
    land = np.isfinite(z) & ~sea
    channels = []
    for name in ("runoff.mm.npy", "precipitation.mm.npy", "temperature.C.npy"):
        a = np.load(canvas / "climate" / name, mmap_mode="r")
        channels.append(np.asarray(a[np.ix_(row // 256, col // 256)], dtype=float))
    ice = np.load(canvas / "climate" / "ice.m.npy", mmap_mode="r")
    erodible = land & (ice[np.ix_(row // 256, col // 256)] <= 1.0)
    params = SurfaceProcessParams(fixed_steps=12, parallel_flood=False)
    kwargs = {"anchor": z, "erodible": erodible}
    baseline = run_surface_process(z, land, *channels, pixel_m, 50_000, params, **kwargs)
    traced = run_surface_process(
        z, land, *channels, pixel_m, 50_000, params, track_sediment_exports=True, **kwargs
    )
    inventory = traced.exported_sediment_m3
    assert inventory is not None
    categories = dict(
        zip(SEDIMENT_EXPORT_CATEGORIES, inventory.sum(axis=(1, 2)) / 1e9, strict=True)
    )
    residual = abs(inventory.sum() / 1e9 - traced.ledger["exported_km3"])
    unchanged = (
        np.array_equal(baseline.h, traced.h)
        and np.array_equal(baseline.discharge_m3_yr, traced.discharge_m3_yr)
        and baseline.ledger == traced.ledger
    )
    plot_sediment_exports(z, sea, inventory, pixel_m, out)
    np.savez_compressed(
        out / "coast-inventory.npz",
        input_height_m=z,
        final_height_m=traced.h,
        exported_sediment_m3=inventory,
    )
    return {
        "chunk": list(key),
        "shape": list(z.shape),
        "pixel_m": pixel_m,
        "diagnostic_time_years": 50_000,
        "land_mask": "boundary-connected water with geological or mesh anchors on this crop",
        "land_cells": int(np.count_nonzero(land)),
        "inland_below_sea_level_cells": int(np.count_nonzero(land & (z <= 0))),
        "steps": traced.steps,
        "surface_and_discharge_and_ledger_bitwise_unchanged": unchanged,
        "categories_km3": categories,
        "export_inventory_residual_km3": float(residual),
        "ledger": traced.ledger,
        "inventory_check_pass": bool(unchanged and residual < 1e-9),
        "river_mouth_growth_pass": False,
        "river_mouth_growth_reason": (
            "The crop omits upstream sediment and its export history. Nonland base levels "
            "must be checked against connected ocean; grain size, deposit porosity, "
            "marine reworking, and allowed shoreline change are also undefined."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--canvas", type=Path, required=True)
    parser.add_argument("--coast-canvas", type=Path, required=True)
    parser.add_argument("--coast-chunk", nargs=2, type=int, default=(5, 4))
    parser.add_argument(
        "--observations",
        type=Path,
        default=Path(__file__).parents[1] / "geology/data/usgs_mean_channel_geometry.csv",
    )
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    calibration, earth = observation_check(args.observations, args.out)
    report = {
        "earth": earth,
        "canvas_width": river_check(args.canvas, calibration, args.out),
        "sediment": sediment_check(args.coast_canvas, tuple(args.coast_chunk), args.out),
    }
    (args.out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    paths = [
        args.observations,
        args.canvas / "canvas.json",
        args.canvas / "hydro/rivers.meta.json",
        args.canvas / "hydro/rivers.line.npy",
        args.canvas / "hydro/rivers.flow.npy",
        args.coast_canvas / "canvas.json",
        args.coast_canvas / "chunks" / f"r{args.coast_chunk[0]:03d}_c{args.coast_chunk[1]:03d}.npy",
    ]
    paths += [
        args.coast_canvas / "climate" / name
        for name in ("runoff.mm.npy", "precipitation.mm.npy", "temperature.C.npy", "ice.m.npy")
    ]
    paths += [Path(path) for path in report["canvas_width"]["window_height_files"]]
    for candidate in (
        args.coast_canvas / "geometry_fields/geological_ocean_heightmap.npy",
        args.coast_canvas / "conditioning/heightmap.npy",
        args.coast_canvas / "geometry_fields/mesh_sea_lake.npy",
    ):
        if candidate.exists():
            paths.append(candidate)
    manifest = {str(path.resolve()): digest(path) for path in paths}
    for source in (
        Path(__file__),
        Path(__file__).parents[1] / "geology/channel_geometry.py",
        Path("src/dreamulator/map/surface_process.py"),
        Path("src/dreamulator/map/_surface_process_kernels.py"),
    ):
        manifest[str(source.resolve())] = digest(source)
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {"earth_validation": earth["groups"]["validation"], "sediment": report["sediment"]},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
