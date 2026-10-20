"""canvas_window — S3: crop a region window from an S1 canvas + S2 hydrology.

Writes the **existing** pack vocabulary so every render leg (colorize /
carto / relief / Blender) and the /packs page keep working unchanged:

    <window>/input/          pack channels + meta.json (export-region contract)
    <window>/refined-out/    height.meters.npy, lake.png, sea-water.png,
                             rivers.png, rivers.line/flow/regime.npy, meta.json

Geometry: the window is the same azimuthal-equidistant square as
:func:`dreamulator.map.region_export.region_window`; every window pixel maps
to (lat, lon) and then into the canvas plane through
:class:`dreamulator.map.td_canvas.CanvasGeometry` (the single conversion
source).  Elevation is bilinearly sampled from the canvas chunks; the
canvas is int16 at 90 m, so a window at 2048² resamples about 2.7x.

Masks come from S2: lake pixels from the sparse per-chunk lake files
(``hydro/lakes.sparse/``), rivers from the vector segments (transformed into
window coordinates and rasterised with a one-pixel brush).  Sea water is
derived from the height (sea level = 0 per the canvas contract).  Climate
channels are sampled from the canvas coarse grid: bilinear for scalars,
nearest for codes.

The skeleton assembles the window's bounding box in canvas pixels (chunks
loaded on demand), so memory scales with the *window*, not the canvas.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from dreamulator.map.region_export import RegionWindow, region_window
from dreamulator.map.td_canvas import PX_PER_CELL, CanvasGeometry

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["CanvasSource", "crop_canvas_window"]

#: Canvas chunk edge in pixels (contract §3).
CHUNK_PX = 2048
#: Coarse cell edge in pixels (contract §3).
CELL_PX = PX_PER_CELL


@dataclass
class CanvasSource:
    """One S1 canvas: geometry, chunk list, lazy chunk/climate readers."""

    root: Path
    geometry: CanvasGeometry
    chunks: set[tuple[int, int]]
    tile: int = CHUNK_PX
    _chunk_cache: dict[tuple[int, int], np.ndarray] | None = None

    @classmethod
    def load(cls, root: Path) -> CanvasSource:
        meta = json.loads((root / "canvas.json").read_text(encoding="utf-8"))
        geom = meta["geometry"]
        geometry = CanvasGeometry(
            float(geom["center_lat"]),
            float(geom["center_lon"]),
            float(geom["radius_km"]),
            int(geom["ncell"]),
        )
        chunks = {(int(c[0]), int(c[1])) for c in meta.get("chunks", [])}
        if not chunks:
            chunks = {
                (int(p.stem.removeprefix("r").split("_c")[0]), int(p.stem.split("_c")[1]))
                for p in (root / "chunks").glob("r*_c*.npy")
            }
        first = sorted(chunks)[0]
        first_path = root / "chunks" / f"r{first[0]:03d}_c{first[1]:03d}.npy"
        tile = int(np.load(first_path, mmap_mode="r").shape[0])
        return cls(root=root, geometry=geometry, chunks=set(chunks), tile=tile, _chunk_cache={})

    def chunk(self, ci: int, cj: int) -> np.ndarray | None:
        key = (ci, cj)
        if key not in self.chunks:
            return None
        assert self._chunk_cache is not None
        if key not in self._chunk_cache:
            path = self.root / "chunks" / f"r{ci:03d}_c{cj:03d}.npy"
            self._chunk_cache[key] = np.load(path)
        return self._chunk_cache[key]

    def climate(self, name: str) -> np.ndarray | None:
        path = self.root / "climate" / f"{name}.npy"
        return np.load(path) if path.exists() else None

    def elevation_range(self) -> tuple[float, float]:
        """Canvas-wide elevation range (palette anchor across windows).

        Reads ``canvas.json``'s ``elevation_m`` when the server writes it;
        otherwise scans the chunk headers with mmap (one read of the canvas,
        cached on the instance).
        """
        meta_path = self.root / "canvas.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        rng = meta.get("elevation_m") or meta.get("elevation_range")
        if isinstance(rng, list) and len(rng) == 2:
            return (float(rng[0]), float(rng[1]))
        lo, hi = np.inf, -np.inf
        for ci, cj in self.chunks:
            path = self.root / "chunks" / f"r{ci:03d}_c{cj:03d}.npy"
            arr = np.load(path, mmap_mode="r")
            lo = min(lo, float(arr.min()))
            hi = max(hi, float(arr.max()))
        return (lo, hi)


def _canvas_raster(source: CanvasSource, r0: int, c0: int, r1: int, c1: int) -> np.ndarray:
    """Assemble the canvas sub-rectangle [r0:r1, c0:c1] from its chunks."""
    h, w = r1 - r0, c1 - c0
    out = np.full((h, w), np.nan, dtype=np.float64)
    t = source.tile
    for ci in range(r0 // t, (r1 - 1) // t + 1):
        for cj in range(c0 // t, (c1 - 1) // t + 1):
            arr = source.chunk(ci, cj)
            if arr is None:
                continue
            tr0, tc0 = ci * t, cj * t
            ir0, ic0 = max(r0, tr0), max(c0, tc0)
            ir1, ic1 = min(r1, tr0 + t), min(c1, tc0 + t)
            if ir1 <= ir0 or ic1 <= ic0:
                continue
            out[ir0 - r0 : ir1 - r0, ic0 - c0 : ic1 - c0] = arr[
                ir0 - tr0 : ir1 - tr0, ic0 - tc0 : ic1 - tc0
            ]
    return out


def _bilinear(raster: np.ndarray, rows: np.ndarray, cols: np.ndarray) -> np.ndarray:
    """Bilinear sample at fractional pixel coordinates (centres at +0.5)."""
    h, w = raster.shape
    r = np.clip(rows, 0, h - 1.001)
    c = np.clip(cols, 0, w - 1.001)
    r0 = np.floor(r).astype(int)
    c0 = np.floor(c).astype(int)
    dr = r - r0
    dc = c - c0
    v00 = raster[r0, c0]
    v01 = raster[r0, np.minimum(c0 + 1, w - 1)]
    v10 = raster[np.minimum(r0 + 1, h - 1), c0]
    v11 = raster[np.minimum(r0 + 1, h - 1), np.minimum(c0 + 1, w - 1)]
    return np.asarray(
        v00 * (1 - dr) * (1 - dc) + v01 * (1 - dr) * dc + v10 * dr * (1 - dc) + v11 * dr * dc
    )


def _nearest(raster: np.ndarray, rows: np.ndarray, cols: np.ndarray) -> np.ndarray:
    h, w = raster.shape
    r = np.clip(np.round(rows - 0.5), 0, h - 1).astype(int)
    c = np.clip(np.round(cols - 0.5), 0, w - 1).astype(int)
    return np.asarray(raster[r, c])


def _coarse_indices(rows: np.ndarray, cols: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Canvas pixel coords → coarse-cell fractional indices (centres +0.5)."""
    return (rows - (CELL_PX - 1) / 2.0) / CELL_PX, (cols - (CELL_PX - 1) / 2.0) / CELL_PX


def _fill_raster(source: CanvasSource, r0: int, c0: int, r1: int, c1: int) -> np.ndarray:
    """Stage-3 filled surface for the crop [r0:r1, c0:c1] (NaN outside chunks)."""
    out = np.full((r1 - r0, c1 - c0), np.nan, dtype=np.float64)
    t = source.tile
    final = source.root / "hydro-work" / "final"
    if not final.is_dir():
        final = source.root / "hydrology-work" / "final"
    for ci in range(r0 // t, (r1 - 1) // t + 1):
        for cj in range(c0 // t, (c1 - 1) // t + 1):
            path = final / f"r{ci:03d}_c{cj:03d}.i16.npy"
            if not path.exists():
                continue
            arr = np.load(path)
            tr0, tc0 = ci * t, cj * t
            ir0, ic0 = max(r0, tr0), max(c0, tc0)
            ir1, ic1 = min(r1, tr0 + t), min(c1, tc0 + t)
            out[ir0 - r0 : ir1 - r0, ic0 - c0 : ic1 - c0] = arr[
                ir0 - tr0 : ir1 - tr0, ic0 - tc0 : ic1 - tc0
            ]
    return out


def _lake_raster(source: CanvasSource, r0: int, c0: int, r1: int, c1: int) -> np.ndarray:
    """Lake id per canvas pixel in the crop (0 = dry).

    Reads the S2 sparse lake files; when those are absent (the lake product
    is not extracted yet) falls back to the filled surface.  The draw mask is
    the whole footprint above a shallow fill threshold, not only the 5 m-deep
    core the river chain uses to stop reaches: the fill surface is the water
    level, and a core-only mask leaves shallow rims as ragged holes and opens
    a land sliver where a river meets the lake (2026-10-21 user report).  The
    component MMU still rejects TD speckle.
    """
    out = np.zeros((r1 - r0, c1 - c0), dtype=np.uint16)
    t = source.tile
    sparse_dir = source.root / "hydro" / "lakes.sparse"
    if not sparse_dir.is_dir():
        from dreamulator.map.prog_erosion import lake_mask

        raw = _canvas_raster(source, r0, c0, r1, c1)
        fill = _fill_raster(source, r0, c0, r1, c1)
        ok = np.isfinite(raw) & np.isfinite(fill)
        if ok.any():
            from scipy.ndimage import binary_fill_holes

            mask = lake_mask(np.where(ok, fill, 0.0), np.where(ok, raw, 0.0), 0.5) & ok
            # Interior holes are quantisation residuals (the rounded fill
            # meets the rounded ground inside one water body); fill them so
            # the sheet does not show speckled lake surfaces.
            out[binary_fill_holes(mask)] = 1
        return out
    for ci in range(r0 // t, (r1 - 1) // t + 1):
        for cj in range(c0 // t, (c1 - 1) // t + 1):
            path = sparse_dir / f"lake.r{ci:03d}_c{cj:03d}.npz"
            if not path.exists():
                continue
            data = np.load(path)
            idx = data["idx"].astype(np.int64)
            lake_id = data["lake_id"].astype(np.uint16)
            rr = idx // t + ci * t
            cc = idx % t + cj * t
            keep = (rr >= r0) & (rr < r1) & (cc >= c0) & (cc < c1)
            out[rr[keep] - r0, cc[keep] - c0] = lake_id[keep]
    return out


def _rasterise_rivers(
    source: CanvasSource,
    window: RegionWindow,
    out_res: int,
) -> np.ndarray:
    """Rasterise S2 river segments onto the window grid (1-px brush)."""
    mask = np.zeros((out_res, out_res), dtype=bool)
    path = source.root / "hydro" / "rivers.line.npy"
    if not path.exists():
        return mask
    segs = np.load(path).astype(np.float64)
    geom = source.geometry
    half = window.half_km
    for seg in segs:
        # S2 vectors are SW-origin canvas km (``cell_xyz_km`` convention);
        # the projection plane is centred, so shift by the canvas half-side.
        lat, lon = geom.xy_to_latlon(seg[:, 0] - geom.half_km, seg[:, 1] - geom.half_km)
        wx, wy = window.latlon_to_xy(lat, lon)
        col = (np.asarray(wx) + half) / window.span_km * out_res
        row = (half - np.asarray(wy)) / window.span_km * out_res
        if len(col) < 2:
            continue
        for i in range(len(col) - 1):
            r0c, c0c = row[i], col[i]
            r1c, c1c = row[i + 1], col[i + 1]
            steps = int(max(abs(r1c - r0c), abs(c1c - c0c))) + 1
            rr = np.linspace(r0c, r1c, steps)
            cc = np.linspace(c0c, c1c, steps)
            ri = np.clip(np.round(rr).astype(int), 0, out_res - 1)
            ci = np.clip(np.round(cc).astype(int), 0, out_res - 1)
            mask[ri, ci] = True
    return mask


def crop_canvas_window(
    source: CanvasSource,
    *,
    center_lat: float,
    center_lon: float,
    span_km: float,
    out_res: int,
    out_dir: Path,
) -> dict[str, object]:
    """Crop the AEQ window from the canvas and write the pack vocabulary.

    Returns the written pack ``input/meta.json`` dict.  Missing canvas chunks
    or hydrology leave NaN height / empty masks and are counted in the meta
    (``missing``), so a partially generated canvas still produces a
    traceable, renderable pack.
    """
    geom = source.geometry
    window = region_window(center_lat, center_lon, span_km, geom.radius_km)
    x_grid, y_grid = window.out_xy(out_res)
    lat_grid, lon_grid = window.xy_to_latlon(x_grid, y_grid)
    rows, cols = geom.latlon_to_pixel(lat_grid, lon_grid)
    rows = np.asarray(rows, dtype=np.float64)
    cols = np.asarray(cols, dtype=np.float64)

    size = geom.size_px
    r_lo = max(0, int(np.floor(rows.min())) - 1)
    c_lo = max(0, int(np.floor(cols.min())) - 1)
    r_hi = min(size, int(np.ceil(rows.max())) + 2)
    c_hi = min(size, int(np.ceil(cols.max())) + 2)
    if r_hi <= r_lo or c_hi <= c_lo:
        raise ValueError("window does not intersect the canvas")

    raster = _canvas_raster(source, r_lo, c_lo, r_hi, c_hi)
    height = _bilinear(raster, rows - r_lo, cols - c_lo)
    missing = int(np.isnan(height).sum())

    lake_raster = _lake_raster(source, r_lo, c_lo, r_hi, c_hi)
    lake = (_nearest(lake_raster, rows - r_lo, cols - c_lo) > 0) & ~np.isnan(height)
    if lake.any():
        # Same MMU gates the river chain used to stop reaches at lakes, at
        # the window's own pixel pitch (the mask is on the window grid).
        km_px = span_km / out_res
        from dreamulator.map.prog_erosion import (
            LAKE_MIN_WIDTH_KM,
            keep_large_lakes,
            lake_mmu_cells,
        )

        lake = keep_large_lakes(lake, lake_mmu_cells(km_px), LAKE_MIN_WIDTH_KM, km_px)
    sea = (height <= 0.0) & ~np.isnan(height)
    river = _rasterise_rivers(source, window, out_res)

    out_dir.mkdir(parents=True, exist_ok=True)
    refined = out_dir / "refined-out"
    inp = out_dir / "input"
    refined.mkdir(exist_ok=True)
    inp.mkdir(exist_ok=True)

    height32 = height.astype(np.float32)
    np.save(refined / "height.meters.npy", height32)
    np.save(inp / "height.meters.npy", height32)
    _write_mask(refined / "lake.png", lake)
    _write_mask(refined / "sea-water.png", sea)
    _write_mask(refined / "rivers.png", river)

    # Rivers: transform into the window frame (SW-origin km) and copy the
    # per-segment flow/regime columns.
    line_path = source.root / "hydro" / "rivers.line.npy"
    flows_path = source.root / "hydro" / "rivers.flow.npy"
    regimes_path = source.root / "hydro" / "rivers.regime.npy"
    if line_path.exists():
        segs = np.load(line_path).astype(np.float64)
        lat, lon = geom.xy_to_latlon(segs[..., 0] - geom.half_km, segs[..., 1] - geom.half_km)
        wx, wy = window.latlon_to_xy(lat, lon)
        half = window.half_km
        np.save(
            refined / "rivers.line.npy",
            np.stack([np.asarray(wx) + half, np.asarray(wy) + half], axis=-1).astype(np.float32),
        )
        if flows_path.exists():
            np.save(refined / "rivers.flow.npy", np.load(flows_path))
        if regimes_path.exists():
            np.save(refined / "rivers.regime.npy", np.load(regimes_path))

    # Climate channels from the canvas coarse grid.
    cr, cc = _coarse_indices(rows, cols)
    scalars = (
        "temperature.C",
        "precipitation.mm",
        "runoff.mm",
        "pet_hamon.mm",
        "ice.m",
        "npp.gc_m2_yr",
    )
    for name in scalars:
        arr = source.climate(name)
        if arr is not None:
            np.save(
                inp / f"{name}.npy",
                _bilinear(np.asarray(arr, dtype=np.float64), cr, cc).astype(np.float32),
            )
    for name in ("koppen.codes", "biome.codes"):
        arr = source.climate(name)
        if arr is not None:
            np.save(inp / f"{name}.npy", _nearest(np.asarray(arr), cr, cc).astype(np.uint8))
    # Channels the render legs load unconditionally: write explicit defaults
    # when the canvas climate lacks them (zero glacier thickness, NaN NPP).
    if not (inp / "biome.codes.npy").exists():
        np.save(inp / "biome.codes.npy", np.zeros((out_res, out_res), dtype=np.uint8))
    if not (inp / "ice.m.npy").exists():
        np.save(inp / "ice.m.npy", np.zeros((out_res, out_res), dtype=np.float32))
    if not (inp / "npp.gc_m2_yr.npy").exists():
        np.save(inp / "npp.gc_m2_yr.npy", np.full((out_res, out_res), np.nan, dtype=np.float32))

    canvas_meta = json.loads((source.root / "canvas.json").read_text(encoding="utf-8"))
    legends: dict[str, dict[str, str]] = {}
    for key in ("koppen_legend", "biome_legend"):
        if key in canvas_meta:
            legends[key.split("_")[0]] = {str(k): str(v) for k, v in canvas_meta[key].items()}
    if "koppen" not in legends and (inp / "koppen.codes.npy").exists():
        codes = np.unique(np.load(inp / "koppen.codes.npy"))
        legends["koppen"] = {str(int(c)): f"class_{int(c)}" for c in codes}
    if "biome" not in legends and (inp / "biome.codes.npy").exists():
        codes = np.unique(np.load(inp / "biome.codes.npy"))
        legends["biome"] = {str(int(c)): f"class_{int(c)}" for c in codes}

    h_lo = float(np.nanmin(height32)) if np.isfinite(height32).any() else 0.0
    h_hi = float(np.nanmax(height32)) if np.isfinite(height32).any() else 0.0
    g_lo, g_hi = source.elevation_range()
    # Anchor the shared palette on the canvas-wide range (sea level 0 inside),
    # not the window's own range — otherwise a high window renders all-sea-blue.
    g_lo = min(g_lo, h_lo, 0.0)
    g_hi = max(g_hi, h_hi, 1.0)
    # Sea-depth mask in the pack's convention: depth normalised by the same
    # span the renderer multiplies back (height_gaea_png_range_m).  Without
    # it the carto LUT reads zero depth everywhere and paints the ocean at
    # sea level (the 0 m land stop, i.e. green).
    span_m = g_hi - g_lo or 1.0
    depth = np.clip(-np.nan_to_num(height32, nan=0.0), 0.0, None) / span_m
    from PIL import Image

    Image.fromarray(np.clip(depth * 65535, 0, 65535).astype(np.uint16)).save(
        refined / "sea-depth.png"
    )
    canvas_source = canvas_meta.get("source")
    inherited = (
        {k: canvas_source[k] for k in ("world", "planet", "branch") if k in canvas_source}
        if isinstance(canvas_source, dict)
        else {}
    )
    meta: dict[str, object] = {
        "pack_version": 4,
        "projection": "azimuthal_equidistant",
        "center_lat": float(center_lat),
        "center_lon": float(center_lon),
        "span_km": float(span_km),
        "radius_km": float(geom.radius_km),
        "grid": {"w": out_res, "h": out_res},
        "extent_km": {"x": float(span_km), "y": float(span_km)},
        "km_per_px": {"x": span_km / out_res, "y": span_km / out_res},
        "elevation_m": {"min": h_lo, "max": h_hi},
        "elevation_m_global": [g_lo, g_hi],
        "height_png_range_m": [h_lo, h_hi],
        "height_gaea_png_range_m": [g_lo, g_hi],
        "seafloor_clamp_m": -400.0,
        "sea_level_m": 0.0,
        "cell_pitch_km": round(2 * np.pi * geom.radius_km / np.sqrt(2e5), 2),
        "ocean_fraction": round(float(sea.mean()), 4),
        "missing_cells": missing,
        "source": {
            **inherited,
            "canvas": source.root.name,
            "geometry_center": [geom.center_lat, geom.center_lon],
            "projection": "azimuthal_equidistant",
        },
        "climate": {key: {"legend": legend} for key, legend in legends.items()},
    }
    (inp / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    refined_meta = {
        "sea_level_m": 0.0,
        "source": meta["source"],
        "projection": "azimuthal_equidistant",
        "height_png_range_m": [h_lo, h_hi],
        "missing_cells": missing,
    }
    (refined / "meta.json").write_text(
        json.dumps(refined_meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return meta


def _write_mask(path: Path, mask: np.ndarray) -> None:
    from PIL import Image

    Image.fromarray((mask.astype(np.uint8) * 255), mode="L").save(path)
