"""Plot two canvases' current surface, ice, lakes and rivers in one geographic window.

Example: uv run python scripts/media/render_canvas_seam_products.py <left> <right>
    --lat -65.46 --lon -37.19 --output exports/canvas-seams/window.png
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import LineCollection

from dreamulator.map.td_canvas import CanvasGeometry
from dreamulator.media.canvas_surface_process import resolve_increments


def geometry(path: Path) -> tuple[CanvasGeometry, dict]:
    meta = json.loads((path / "canvas.json").read_text(encoding="utf-8"))
    g = meta["geometry"]
    return CanvasGeometry(g["center_lat"], g["center_lon"], g["radius_km"], g["ncell"]), meta


def fields(
    path: Path, lat: np.ndarray, lon: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    geom, meta = geometry(path)
    tile = int(meta["geometry"]["chunk_px"])
    rows, cols = geom.latlon_to_pixel(lat, lon)
    rows, cols = np.floor(rows).astype(int), np.floor(cols).astype(int)
    z = np.full(rows.shape, np.nan)
    ice = np.full(rows.shape, np.nan)
    lakes = np.zeros(rows.shape, dtype=bool)
    inc = resolve_increments(path)
    for ci, cj in set(zip((rows // tile).ravel(), (cols // tile).ravel(), strict=True)):
        take = (rows // tile == ci) & (cols // tile == cj)
        rr, cc = rows[take] % tile, cols[take] % tile
        name = f"r{ci:03d}_c{cj:03d}.npy"
        source = path / "chunks" / name
        if not source.exists():
            continue
        z[take] = np.load(source, mmap_mode="r")[rr, cc]
        if inc is not None:
            z[take] += np.load(inc / name, mmap_mode="r")[rr, cc]
        h = path / "surface/ice_chunks" / name
        if h.exists():
            ice[take] = np.load(h, mmap_mode="r")[rr, cc]
        elif (meta.get("surface_refinement") or {}).get("zero_ice"):
            ice[take] = 0
        sparse = path / "hydro/lakes.sparse" / f"lake.r{ci:03d}_c{cj:03d}.npz"
        if sparse.exists():
            with np.load(sparse) as table:
                lakes[take] = np.isin(rr * tile + cc, table["idx"])
    return z, ice, lakes


def river_lines(path: Path, centre: CanvasGeometry, half_km: float) -> np.ndarray:
    geom, _ = geometry(path)
    corner = np.asarray([-half_km, half_km])
    xx, yy = np.meshgrid(corner, corner)
    lat, lon = centre.xy_to_latlon(xx, yy)
    row, col = geom.latlon_to_pixel(lat, lon)
    px = geom.px_km
    x, y = (col - 0.5) * px, (geom.size_px - 0.5 - row) * px
    line = np.load(path / "hydro/rivers.line.npy", mmap_mode="r")
    margin = 2 * px
    selected = (
        (line[:, :, 0].max(axis=1) >= x.min() - margin)
        & (line[:, :, 0].min(axis=1) <= x.max() + margin)
        & (line[:, :, 1].max(axis=1) >= y.min() - margin)
        & (line[:, :, 1].min(axis=1) <= y.max() + margin)
    )
    line = line[selected].astype(float)
    lat, lon = geom.xy_to_latlon(
        line[:, :, 0] - geom.half_km + px / 2, line[:, :, 1] - geom.half_km + px / 2
    )
    x, y = centre.latlon_to_xy(lat, lon)
    return np.stack([x, y], axis=-1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    parser.add_argument("--lat", required=True, type=float)
    parser.add_argument("--lon", required=True, type=float)
    parser.add_argument("--span-km", default=46.0, type=float)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.span_km <= 0:
        parser.error("--span-km must be positive")
    first, _ = geometry(args.left)
    centre = CanvasGeometry(args.lat, args.lon, first.radius_km, 2)
    half = args.span_km / 2
    n = max(2, int(round(args.span_km / first.px_km)) + 1)
    x = np.linspace(-half, half, n)
    edge = half + (x[1] - x[0]) / 2
    xx, yy = np.meshgrid(x, x)
    lat, lon = centre.xy_to_latlon(xx, yy)
    paths = [args.left, args.right]
    products = [fields(path, lat, lon) for path in paths]
    fig, axes = plt.subplots(2, 2, figsize=(12, 11), layout="constrained")
    for row, label, colour in [(0, "Current surface", "gray"), (1, "Ice thickness", "Blues")]:
        cmap = matplotlib.colormaps[colour].copy()
        cmap.set_bad("#f4d7bd")
        values = [p[row] for p in products]
        low = min(float(np.nanpercentile(a, 1)) for a in values)
        high = max(float(np.nanpercentile(a, 99)) for a in values)
        high = max(high, low + 1)
        for col, (path, product) in enumerate(zip(paths, products, strict=True)):
            ax = axes[row, col]
            im = ax.imshow(
                product[row],
                origin="lower",
                extent=(-edge, edge, -edge, edge),
                cmap=cmap,
                vmin=low,
                vmax=high,
            )
            if product[2].any():
                ax.contour(
                    xx, yy, product[2].astype(float), levels=[0.5], colors="#22b8c5", linewidths=0.5
                )
            ax.add_collection(
                LineCollection(river_lines(path, centre, half), colors="#1978ce", linewidths=0.6)
            )
            ax.plot(0, 0, "k+", markersize=9)
            ax.set(
                xlim=(-half, half),
                ylim=(-half, half),
                xlabel="East of point (km)",
                ylabel="North of point (km)",
                title=label + "\n" + path.name,
            )
            fig.colorbar(im, ax=ax, label="m")
    fig.suptitle(
        f"Same {args.span_km:g} km window: {args.lat:.4f}, {args.lon:.4f}\n"
        "Surface-matched two-ring rivers and monthly lake products\n"
        "Blue: rivers; cyan: lake boundaries; peach: no data"
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output, dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    main()
