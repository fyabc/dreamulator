"""td_canvas_mosaic — full-resolution overview image of one generated canvas.

Stitches a canvas's raw chunks (about 89.8 m per pixel) into one image, cropped to the generated
area, in the export-carto palette: the shared adaptive-terrain LUT anchored on a fixed elevation
range, the two-scale hillshade multiplied into land only and carto's saturation lift.  Chunks not
in the manifest (land owned by a neighbouring canvas, open ocean) stay paper-coloured.

The image is built in bands of one chunk row with a halo, in parallel, so no step holds the whole
height field.  ``step`` block-averages step x step pixels first (1 = native).  The structural
hillshade keeps a fixed ground scale (``struct_km``), so crops of a big image and a small overview
read alike; the fine shade is the true slope at the output pixel size.

Output by extension: ``.jpg`` (sides up to 65535 px, the format's limit), ``.png`` (lossless, any
size) or ``.tif`` (BigTIFF, tiled, deflate).  A sidecar ``<out>.json`` records the canvas, step,
pixel size and geometry.
"""

from __future__ import annotations

import json
import math
import warnings
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np

CHUNK_PX = 2048
#: Fixed tint anchors (m): one palette for every canvas, so mosaics of different continents match.
MOSAIC_RANGE_M = (-9000.0, 9000.0)
#: Structural hillshade sigma (km): 24 sheet px at a 16x overview (about 1.44 km per px).
STRUCT_KM = 24 * 23.0 / 256 * 16
PAPER_RGB = (0.97, 0.96, 0.93)
JPEG_MAX_SIDE = 65535

_ctx: dict[str, Any] = {}


def carto_tint(
    height_m: np.ndarray,
    km_per_px: float,
    world_range_m: tuple[float, float] = MOSAIC_RANGE_M,
    struct_sigma_px: float | None = None,
) -> np.ndarray:
    """Export-carto tint (float RGB 0..1) of a height field; NaN = paper."""
    from dreamulator.media.carto_render import (
        COLOR_SATURATION,
        HILLSHADE_STRENGTH,
        _lut_rgb,
        two_scale_relief,
    )

    h = np.where(np.isfinite(height_m), height_m, world_range_m[0])
    sea = h <= 0.0
    rgb = _lut_rgb(h, sea, np.where(sea, -h, 0.0), world_range_m)
    relief = two_scale_relief(h, km_per_px, struct_sigma_px=struct_sigma_px)
    shade = (1.0 - HILLSHADE_STRENGTH) + HILLSHADE_STRENGTH * relief[..., None]
    rgb[~sea] = rgb[~sea] * np.broadcast_to(shade, rgb.shape)[~sea]
    lum = rgb.mean(axis=2, keepdims=True)
    rgb = np.clip(lum + (rgb - lum) * COLOR_SATURATION, 0.0, 1.0)
    rgb[~np.isfinite(height_m)] = PAPER_RGB
    return np.asarray(rgb)


def _init(ctx: dict[str, Any]) -> None:
    _ctx.update(ctx)


def _load_rows(r0: int, r1: int) -> np.ndarray:
    """Native heights for canvas pixel rows [r0, r1) over the column span; NaN where no chunk."""
    c0, c1, files = _ctx["c0"], _ctx["c1"], _ctx["files"]
    h = np.full((r1 - r0, c1 - c0), np.nan, np.float32)
    for ci in range(r0 // CHUNK_PX, (r1 - 1) // CHUNK_PX + 1):
        a0, a1 = max(r0, ci * CHUNK_PX), min(r1, (ci + 1) * CHUNK_PX)
        for cj in range(c0 // CHUNK_PX, c1 // CHUNK_PX):
            f = files.get((ci, cj))
            if f is None:
                continue
            blk = np.load(f, mmap_mode="r")
            cols = slice(cj * CHUNK_PX - c0, (cj + 1) * CHUNK_PX - c0)
            h[a0 - r0 : a1 - r0, cols] = blk[a0 - ci * CHUNK_PX : a1 - ci * CHUNK_PX]
    return h


def _band(ci: int) -> tuple[int, np.ndarray]:
    step, halo = _ctx["step"], _ctx["halo"]
    r0, r1 = ci * CHUNK_PX, (ci + 1) * CHUNK_PX
    a0, a1 = max(_ctx["r0"], r0 - halo * step), min(_ctx["r1"], r1 + halo * step)
    h = _load_rows(a0, a1)
    if step > 1:
        h = h.reshape(h.shape[0] // step, step, h.shape[1] // step, step)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN blocks outside the manifest
            h = np.nanmean(h, axis=(1, 3))
    rgb = carto_tint(h, _ctx["km_px"], MOSAIC_RANGE_M, struct_sigma_px=_ctx["sigma_px"])
    top = (r0 - a0) // step
    return ci, np.rint(rgb[top : top + CHUNK_PX // step] * 255).astype(np.uint8)


def render_mosaic(
    canvas_dir: Path,
    out: Path,
    *,
    step: int = 1,
    struct_km: float = STRUCT_KM,
    quality: int = 90,
    workers: int = 8,
) -> dict[str, Any]:
    """Write the mosaic image and its sidecar; returns the sidecar dict."""
    if step < 1 or CHUNK_PX % step:
        raise ValueError("step must divide 2048")
    meta = json.loads((canvas_dir / "canvas.json").read_text(encoding="utf-8"))
    g = meta["geometry"]
    files = {
        (int(p.stem[1:4]), int(p.stem[6:9])): str(p)
        for p in (canvas_dir / "chunks").glob("r*_c*.npy")
    }
    if not files:
        raise FileNotFoundError(f"no chunks under {canvas_dir / 'chunks'}")
    rows = sorted({k[0] for k in files})
    cols = sorted({k[1] for k in files})
    km_px = float(g["px_km"]) * step
    sigma_px = struct_km / km_px
    ctx = {
        "files": files,
        "step": step,
        "halo": int(math.ceil(4 * sigma_px)) + 2,
        "km_px": km_px,
        "sigma_px": sigma_px,
        "r0": rows[0] * CHUNK_PX,
        "r1": (rows[-1] + 1) * CHUNK_PX,
        "c0": cols[0] * CHUNK_PX,
        "c1": (cols[-1] + 1) * CHUNK_PX,
    }
    height = (rows[-1] - rows[0] + 1) * CHUNK_PX // step
    width = (cols[-1] - cols[0] + 1) * CHUNK_PX // step
    ext = out.suffix.lower()
    if ext not in (".jpg", ".jpeg", ".png", ".tif", ".tiff"):
        raise ValueError(f"unsupported image type {ext}")
    if ext in (".jpg", ".jpeg") and max(height, width) > JPEG_MAX_SIDE:
        raise ValueError(
            f"{width} x {height} px exceeds the JPEG limit of {JPEG_MAX_SIDE} px; "
            f"use step {step * 2} or a .png/.tif output"
        )
    img = np.empty((height, width, 3), np.uint8)
    img[:] = np.rint(np.array(PAPER_RGB) * 255).astype(np.uint8)
    band_ids = range(rows[0], rows[-1] + 1)
    if workers > 1:
        with ProcessPoolExecutor(workers, initializer=_init, initargs=(ctx,)) as ex:
            bands = list(ex.map(_band, band_ids))
    else:
        _init(ctx)
        bands = [_band(ci) for ci in band_ids]
    for ci, band in bands:
        o = (ci - rows[0]) * CHUNK_PX // step
        img[o : o + band.shape[0]] = band
    out.parent.mkdir(parents=True, exist_ok=True)
    if ext in (".tif", ".tiff"):
        import tifffile

        tifffile.imwrite(
            out, img, bigtiff=True, tile=(512, 512), compression="deflate", photometric="rgb"
        )
    else:
        from PIL import Image

        Image.MAX_IMAGE_PIXELS = None
        im = Image.fromarray(img)
        if ext == ".png":
            im.save(out, compress_level=6)
        else:
            im.save(out, quality=quality, optimize=True)
    side = {
        "canvas": meta["id"],
        "step": step,
        "pixel_m": round(km_px * 1000, 2),
        "width_px": width,
        "height_px": height,
        "canvas_rows": [ctx["r0"], ctx["r1"]],
        "canvas_cols": [ctx["c0"], ctx["c1"]],
        "geometry": g,
        "palette": "export-carto LUT, two-scale hillshade",
        "struct_km": struct_km,
    }
    Path(str(out) + ".json").write_text(json.dumps(side, indent=1), encoding="utf-8")
    return side
