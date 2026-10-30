"""td_canvas_mosaic — full-resolution overview image of one generated canvas.

Stitches a canvas's raw chunks (about 89.8 m per pixel) into one image, cropped to the generated
area, in the export-carto palette: the shared adaptive-terrain LUT anchored on a fixed elevation
range, the two-scale hillshade multiplied into land only and carto's saturation lift.  Chunks not
in the manifest (land owned by a neighbouring canvas, open ocean) stay paper-coloured (or the
sea grey with ``sea="grey"``).

The image is built in bands of one chunk row with a halo, in parallel, so no step holds the whole
height field.  ``step`` block-averages step x step pixels first (1 = native).  The structural
hillshade keeps a fixed ground scale (``struct_km``), so crops of a big image and a small overview
read alike; the fine shade is the true slope at the output pixel size.

Colour and shading are independent options.  ``style`` picks the shading: ``carto`` (default) is
the export-carto look above; ``relief`` is a shaded-relief look for overview prints, a
multi-directional hillshade on vertically exaggerated heights (default exaggeration = pixel size
/ 90 m, so a block-averaged pixel shades about as steeply as the native one) with a soft shadow
along the coast.  ``palette`` picks the land colours from ``hypsometric_palettes.json`` (or the
built-in ``adaptive`` export-carto LUT); ``sea`` picks the ocean: ``carto`` (the export-carto
depth blues, default), ``palette`` (the palette's own bathymetry where it has one) or ``grey``.
``intertidal_m`` paints a height band around sea level (default ±2 m) in the IHO S-52 intertidal
colour, as charts tint drying areas.  The ``cross-blended`` palette (Patterson & Jenny 2011)
blends arid, warm-humid, cold-humid and polar ramps per pixel from the canvas's coarse climate
channels.  All are rendering choices, not terrain changes.

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
STYLES = ("carto", "relief")
#: Relief style: light directions (azimuth deg, weight) at 40 deg altitude, NW key light.
RELIEF_LIGHTS = ((315.0, 0.5), (270.0, 0.2), (0.0, 0.2), (225.0, 0.1))
RELIEF_ALTITUDE_DEG = 40.0
SEAS = ("carto", "palette", "grey")
SEA_GREY_RGB = (0.88, 0.88, 0.88)
#: Coast shadow on the sea: depth of the darkening and its e-folding distance (km).
RELIEF_COAST_SHADOW = (0.12, 2.0)
#: Default palette per style.
DEFAULT_PALETTE = {"carto": "adaptive", "relief": "pastel"}
#: Intertidal band (m): pixels with height in [lo, hi] get the intertidal colour, the
#: cartographic convention for drying areas (charts tint the foreshore between low and high water
#: separately).  Default ±2 m (author choice 2026-10-25); a rendering class, not a land/sea test —
#: the data contract stays "land is above 0 m".
INTERTIDAL_M: tuple[float, float] | None = (-2.0, 2.0)
#: IHO S-52 colour token DEPIT (intertidal area), DAY_BRIGHT table, as shipped in OpenCPN's
#: chartsymbols.xml: (131, 178, 149).
INTERTIDAL_RGB = (131 / 255, 178 / 255, 149 / 255)
#: Default shading of the mosaic command (the print look; carto stays available).
DEFAULT_STYLE = "relief"
#: Cross-blended weights (rendering choices): aridity index P/PET from the dry sub-humid bound
#: 0.65 to the arid bound 0.2 (UNEP classes); warm vs cold humid over a 8–18 °C annual mean;
#: polar below a 10 °C warmest month (Köppen E) with a ±2 K blend, and wherever ice lies.
CB_ARID_AI = (0.65, 0.2)
CB_WARM_C = (8.0, 18.0)
CB_POLAR_TMAX_C = (12.0, 8.0)
JPEG_MAX_SIDE = 65535

_ctx: dict[str, Any] = {}
_HYPSO: dict[str, Any] = json.loads(
    Path(__file__).with_name("hypsometric_palettes.json").read_text(encoding="utf-8")
)["palettes"]


def palette_names() -> list[str]:
    """``adaptive`` (the export-carto LUT) plus every palette of ``hypsometric_palettes.json``."""
    return ["adaptive", *_HYPSO]


def _ramp(h: np.ndarray, stops: list[list[float]]) -> np.ndarray:
    """Piecewise-linear RGB 0..1 over (elevation m, r, g, b) stops, clamped at both ends."""
    st = np.asarray(stops, dtype=np.float64)
    return np.stack([np.interp(h, st[:, 0], st[:, k] / 255.0) for k in (1, 2, 3)], axis=-1)


def _smoothstep(t: np.ndarray) -> np.ndarray:
    t = np.clip(t, 0.0, 1.0)
    return np.asarray(t * t * (3.0 - 2.0 * t))


def cross_blend_weights(canvas_dir: Path) -> dict[str, np.ndarray]:
    """Per coarse cell weights ``arid``, ``warm`` and ``polar`` (0..1) from the climate channels."""
    from scipy.ndimage import distance_transform_edt

    c = canvas_dir / "climate"
    p = np.load(c / "precipitation.mm.npy").astype(np.float64)
    pet = np.load(c / "pet_hamon.mm.npy").astype(np.float64)
    t = np.load(c / "temperature.C.npy").astype(np.float64)
    tmax = np.load(c / "temperature_monthly.C.npy").astype(np.float64).max(axis=0)
    ice = np.load(c / "ice.m.npy").astype(np.float64)
    ai = p / np.maximum(pet, 1.0)
    bad = ~np.isfinite(ai)  # ocean cells: take the nearest land value
    if bad.any() and not bad.all():
        _, (ii, jj) = distance_transform_edt(bad, return_indices=True)
        ai = ai[ii, jj]
    ai = np.where(np.isfinite(ai), ai, 1.0)
    w_arid = _smoothstep((CB_ARID_AI[0] - ai) / (CB_ARID_AI[0] - CB_ARID_AI[1]))
    w_warm = _smoothstep((t - CB_WARM_C[0]) / (CB_WARM_C[1] - CB_WARM_C[0]))
    w_polar = _smoothstep((CB_POLAR_TMAX_C[0] - tmax) / (CB_POLAR_TMAX_C[0] - CB_POLAR_TMAX_C[1]))
    w_polar = np.maximum(w_polar, (np.nan_to_num(ice) > 0).astype(np.float64))
    return {"arid": w_arid, "warm": w_warm, "polar": w_polar}


def land_rgb(
    h: np.ndarray, palette: str, weights: dict[str, np.ndarray] | None = None
) -> np.ndarray:
    """Land colours (RGB 0..1) of heights ``h`` in a named palette (sea pixels get colours too)."""
    if palette == "adaptive":
        from dreamulator.media.carto_render import _lut_rgb

        land = np.zeros(h.shape, dtype=bool)
        return np.asarray(_lut_rgb(h, land, np.zeros_like(h), MOSAIC_RANGE_M))
    spec = _HYPSO[palette]
    if spec.get("kind") == "cross_blended":
        if weights is None:
            raise ValueError("the cross-blended palette needs climate weights")
        r = spec["ramps"]
        humid = _blend(_ramp(h, r["cold_humid"]), _ramp(h, r["warm_humid"]), weights["warm"])
        low = _blend(humid, _ramp(h, r["arid"]), weights["arid"])
        return _blend(low, _ramp(h, r["polar"]), weights["polar"])
    return _ramp(h, spec["land"])


def _blend(a: np.ndarray, b: np.ndarray, w: np.ndarray) -> np.ndarray:
    return np.asarray(a * (1.0 - w[..., None]) + b * w[..., None])


#: Shallowest depth (m) used for the sea-colour lookup: the LUT's 0 m bin is the first land colour,
#: so pixels sitting exactly on sea level (about 1% of a TD canvas) must look up as shallow sea.
MIN_SEA_DEPTH_M = 1.0


def _sea_depth(h: np.ndarray) -> np.ndarray:
    return np.asarray(np.maximum(-np.minimum(h, 0.0), MIN_SEA_DEPTH_M))


def sea_rgb(h: np.ndarray, sea: str, palette: str) -> np.ndarray:
    """Ocean colours (RGB 0..1) of heights ``h`` (land pixels get colours too)."""
    spec = _HYPSO.get(palette, {})
    if sea == "grey":
        return np.broadcast_to(np.array(SEA_GREY_RGB), (*h.shape, 3)).copy()
    if sea == "palette" and spec.get("sea"):
        return _ramp(h, spec["sea"])
    from dreamulator.media.carto_render import _lut_rgb

    wet = np.ones(h.shape, dtype=bool)
    return np.asarray(_lut_rgb(h, wet, _sea_depth(h), MOSAIC_RANGE_M))


def carto_tint(
    height_m: np.ndarray,
    km_per_px: float,
    world_range_m: tuple[float, float] = MOSAIC_RANGE_M,
    struct_sigma_px: float | None = None,
    *,
    palette: str = "adaptive",
    sea_mode: str = "carto",
    weights: dict[str, np.ndarray] | None = None,
    intertidal_m: tuple[float, float] | None = INTERTIDAL_M,
) -> np.ndarray:
    """Export-carto shading (float RGB 0..1) of a height field; NaN = paper."""
    from dreamulator.media.carto_render import (
        COLOR_SATURATION,
        HILLSHADE_STRENGTH,
        _lut_rgb,
        two_scale_relief,
    )

    h = np.where(np.isfinite(height_m), height_m, world_range_m[0])
    sea = h <= 0.0
    if palette == "adaptive" and sea_mode == "carto":
        rgb = _lut_rgb(h, sea, np.where(sea, _sea_depth(h), 0.0), world_range_m)
    else:
        rgb = np.where(sea[..., None], sea_rgb(h, sea_mode, palette), land_rgb(h, palette, weights))
    relief = two_scale_relief(h, km_per_px, struct_sigma_px=struct_sigma_px)
    shade = (1.0 - HILLSHADE_STRENGTH) + HILLSHADE_STRENGTH * relief[..., None]
    rgb[~sea] = rgb[~sea] * np.broadcast_to(shade, rgb.shape)[~sea]
    lum = rgb.mean(axis=2, keepdims=True)
    rgb = np.clip(lum + (rgb - lum) * COLOR_SATURATION, 0.0, 1.0)
    _paint_intertidal(rgb, height_m, intertidal_m, sea, km_per_px)
    rgb[~np.isfinite(height_m)] = SEA_GREY_RGB if sea_mode == "grey" else PAPER_RGB
    return np.asarray(rgb)


def relief_tint(
    height_m: np.ndarray,
    km_per_px: float,
    exaggeration: float,
    world_range_m: tuple[float, float] = MOSAIC_RANGE_M,
    *,
    palette: str = "pastel",
    sea_mode: str = "carto",
    weights: dict[str, np.ndarray] | None = None,
    intertidal_m: tuple[float, float] | None = INTERTIDAL_M,
) -> np.ndarray:
    """Shaded-relief shading (float RGB 0..1) of a height field; NaN = paper (or the sea grey)."""
    from scipy.ndimage import distance_transform_edt

    h = np.where(np.isfinite(height_m), height_m, world_range_m[0])
    sea = h <= 0.0
    tint = land_rgb(h, palette, weights)
    gy, gx = np.gradient(np.where(sea, 0.0, h) * exaggeration, km_per_px * 1000.0)
    slope = np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    alt = np.radians(RELIEF_ALTITUDE_DEG)
    shade = np.zeros_like(h)
    for az, wt in RELIEF_LIGHTS:
        lit = np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(
            np.radians(az) - aspect
        )
        shade += wt * np.clip(lit, 0.0, 1.0)
    rgb = np.clip(tint * (0.35 + 0.85 * shade[..., None]), 0.0, 1.0)
    depth, efold = RELIEF_COAST_SHADOW
    dist_km = distance_transform_edt(sea) * km_per_px
    ocean = sea_rgb(h, sea_mode, palette)
    rgb[sea] = ocean[sea] * (1.0 - depth * np.exp(-dist_km[sea] / efold))[:, None]
    _paint_intertidal(rgb, height_m, intertidal_m, sea, km_per_px)
    rgb[~np.isfinite(height_m)] = SEA_GREY_RGB if sea_mode == "grey" else PAPER_RGB
    return np.asarray(rgb)


#: Drying foreshore reaches at most this far from the waterline — the tidal
#: working range.  Interior lowland at the same elevations is NOT foreshore,
#: and lakes inside the band are water rather than shore.
INTERTIDAL_MAX_SEA_DIST_KM = 3.0


def intertidal_mask(
    height_m: np.ndarray,
    band: tuple[float, float] | None,
    sea: np.ndarray,
    km_per_px: float,
    *,
    exclude: np.ndarray | None = None,
) -> np.ndarray:
    """The drying-foreshore mask: the height band ACROSS the waterline
    (IHO foreshore spans chart datum to high water — the sea-side shallow
    strip belongs to it), within the tidal working range of the OPEN sea
    (water deeper than the band's low edge), minus excluded water (lakes).

    Single source for the mosaic painting, the survey sheet painting and
    the survey legend's presence check — all three must agree.
    """
    from scipy.ndimage import distance_transform_edt

    if band is None:
        return np.zeros(height_m.shape, dtype=bool)
    lo, hi = band
    with np.errstate(invalid="ignore"):
        m = (height_m >= lo) & (height_m <= hi)
    open_sea = sea & ~(height_m > lo)  # below the low-water edge
    m &= ~open_sea
    if exclude is not None:
        m &= ~exclude
    if m.any():
        # Distance from the WATERLINE (any sea), not the deep water: the
        # foreshore itself is shore — the gate exists to drop interior
        # lowland at the same elevations.
        dist = distance_transform_edt(~sea, sampling=(km_per_px, km_per_px))
        m &= dist <= INTERTIDAL_MAX_SEA_DIST_KM
    return m


def _paint_intertidal(
    rgb: np.ndarray,
    height_m: np.ndarray,
    band: tuple[float, float] | None,
    sea: np.ndarray,
    km_per_px: float,
    *,
    exclude: np.ndarray | None = None,
) -> None:
    """Flat intertidal tint on the foreshore mask (in place)."""
    m = intertidal_mask(height_m, band, sea, km_per_px, exclude=exclude)
    rgb[m] = INTERTIDAL_RGB


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
    weights = None
    if _ctx["weights"] is not None:
        from scipy.ndimage import map_coordinates

        # output pixel centres in coarse-cell coordinates (cell i spans pixels [256i, 256i + 256))
        rr = (a0 + (np.arange(h.shape[0]) + 0.5) * step) / 256.0 - 0.5
        cc = (_ctx["c0"] + (np.arange(h.shape[1]) + 0.5) * step) / 256.0 - 0.5
        gr, gc = np.meshgrid(rr, cc, indexing="ij")
        weights = {
            k: map_coordinates(v, [gr, gc], order=1, mode="nearest")
            for k, v in _ctx["weights"].items()
        }
    kw = {
        "palette": _ctx["palette"],
        "sea_mode": _ctx["sea"],
        "weights": weights,
        "intertidal_m": _ctx["intertidal"],
    }
    if _ctx["style"] == "relief":
        rgb = relief_tint(h, _ctx["km_px"], _ctx["exaggeration"], **kw)
    else:
        rgb = carto_tint(h, _ctx["km_px"], MOSAIC_RANGE_M, struct_sigma_px=_ctx["sigma_px"], **kw)
    top = (r0 - a0) // step
    return ci, np.rint(rgb[top : top + CHUNK_PX // step] * 255).astype(np.uint8)


def render_mosaic(
    canvas_dir: Path,
    out: Path,
    *,
    step: int = 1,
    struct_km: float = STRUCT_KM,
    style: str = "carto",
    palette: str | None = None,
    sea: str = "carto",
    exaggeration: float | None = None,
    intertidal_m: tuple[float, float] | None = INTERTIDAL_M,
    quality: int = 90,
    workers: int = 8,
) -> dict[str, Any]:
    """Write the mosaic image and its sidecar; returns the sidecar dict."""
    if step < 1 or CHUNK_PX % step:
        raise ValueError("step must divide 2048")
    if style not in STYLES:
        raise ValueError(f"unknown style {style!r}; use one of {', '.join(STYLES)}")
    palette = palette or DEFAULT_PALETTE[style]
    if palette not in palette_names():
        raise ValueError(f"unknown palette {palette!r}; use one of {', '.join(palette_names())}")
    if sea not in SEAS:
        raise ValueError(f"unknown sea {sea!r}; use one of {', '.join(SEAS)}")
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
    ve = float(exaggeration) if exaggeration is not None else km_px / (23.0 / 256)
    ctx = {
        "files": files,
        "step": step,
        "halo": int(math.ceil(4 * sigma_px)) + 2,
        "km_px": km_px,
        "sigma_px": sigma_px,
        "style": style,
        "palette": palette,
        "sea": sea,
        "weights": cross_blend_weights(canvas_dir)
        if _HYPSO.get(palette, {}).get("kind") == "cross_blended"
        else None,
        "exaggeration": ve,
        "intertidal": intertidal_m,
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
        "style": style,
        "palette": palette,
        "sea": sea,
        "intertidal_m": list(intertidal_m) if intertidal_m else None,
        "exaggeration": round(ve, 3) if style == "relief" else None,
        "struct_km": struct_km,
    }
    Path(str(out) + ".json").write_text(json.dumps(side, indent=1), encoding="utf-8")
    return side
