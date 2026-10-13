"""carto_render — survey-style topographic sheet from a region pack.

Fourth leg of the video-material chain, sharing steps ①② with the satellite
chain (``dreamulator export region`` → Gaea build) and swapping the Blender
renderer for a fully vector cartographic compositor:

    pack + gaea-out  →  carto/{topo.svg, topo.png}

Aesthetic target = modern survey sheet (Swiss style): hypsometric tints,
hillshade, two-weight contours with inline elevation labels, water in flat
inks, legend/scale bar/north arrow.  All colours and intervals are module
constants (cartographic choices, not physics).

The height source is the same colour-authority chain the Blender leg uses:
``gaea-out/rivers-h.exr`` (Gaea-eroded, 8K) through
:func:`dreamulator.media.satellite_color.load_inputs`.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from matplotlib.axes import Axes

from dreamulator.map.palettes import build_adaptive_terrain_lut

from .satellite_color import ColorizeInputs, hillshade, load_inputs

# --- paper & inks -----------------------------------------------------------
PAPER_RGB = (248, 244, 233)

#: Contour interval.  The sheet covers ~2400 km (≈1:10 M small scale) —
#: intervals below read as noise at that scale; 500/1000 m matches what
#: hand-drawn OC sheets actually use.
CONTOUR_MINOR_M = 500.0
CONTOUR_MAJOR_M = 1000.0
CONTOUR_MINOR_COLOR = (150, 110, 70)
CONTOUR_MAJOR_COLOR = (108, 74, 40)
CONTOUR_MINOR_LW = 0.35
CONTOUR_MAJOR_LW = 0.9
CONTOUR_LABEL_SIZE = 10.0

RIVER_COLOR = (72, 119, 148)
RIVER_MIN_LW = 0.7

#: Ocean ink comes from the shared LUT on the planet-wide anchor (same
#: elevation → same colour on every sheet).  Historically the LUT's sea
#: anchors stretched with the palette range (−200 m band landing at −413 m,
#: shallows tinted land-green); fixed at the palette level by capping the
#: clamp (see palettes.py), so depths chart physically everywhere.

#: Relief rendering: reference sheets (OpenTopoMap style) read as two
#: stacked shades — a structural shadow on the smooth field plus a fine
#: relief on the raw field.  A single-scale shade leaves the mid-frequencies
#: flat, which was the dominant quality gap vs. real-DEM renders.
HILLSHADE_STRENGTH = 0.60
HILLSHADE_STRUCT_SIGMA_PX = 24.0  # structural layer smoothing (sheet px)
HILLSHADE_STRUCT_WEIGHT = 0.4  # share of the structural layer in the blend
#: Post-LUT saturation boost: the shared palette interpolates linearly
#: between stops and the stack (shade + paper grain) washes it further;
#: reference sheets run visibly richer colour than the raw LUT mix.
COLOR_SATURATION = 1.30

#: Sheet furniture type sizes (pt) — the "readable at arm's length" tier;
#: a hand-drawn sheet keeps its furniture this large relative to contours.
TITLE_SIZE = 22.0
LEGEND_SIZE = 14.0
SCALEBAR_SIZE = 13.0

#: Hand-drawn feel (stage-two pass, but part of the MVP chain deliverable:
#: the wobbled sheet doubles as video material).
PAPER_TEXTURE_STRENGTH = 0.030  # multiply grain depth (reduced: stacked
# with the saturation lift it read as dirt, not paper)
WOBBLE_AMPLITUDE_PX = 1.3  # contour vertex displacement (sheet px)
WOBBLE_WAVELENGTH_PX = 90.0  # displacement wavelength (sheet px)
WOBBLE_SEED = 7

#: Full hand-drawn pass (--hand → topo_hand.png, the video-material variant;
#: the clean sheet stays the default deliverable).  Cartographic choices
#: benchmarked against hand-drawn OC sheets (see the research note).
MISREGISTER_PX = 1.2  # plate offset: colour layer drift vs the ink lines
WATERCOLOR_BLUR_PX = 1.6  # tint diffusion — watercolour edges, not print edges
VIGNETTE_STRENGTH = 0.35  # corner wear toward paper white
INK_LW_JITTER = 0.55  # line-width modulation depth (fraction of base lw)
INK_SEGMENT_PX = 14.0  # ink re-stroke segment length (sheet px)
HAND_FONT_STACK = ["KaiTi", "Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "DejaVu Sans"]

#: Legend band ladder (metres) — round chart-conventional boundaries.  The
#: sheet's colour comes from the continuous shared LUT; the legend samples it
#: at these rounded boundaries (survey convention: legends list round values
#: that occur in the sheet, not the palette's anchored fractions).
LEGEND_LADDER_M = [
    -6000.0, -4000.0, -2000.0, -1000.0, -500.0, -200.0, -80.0, -30.0, -10.0, 0.0,
    200.0, 500.0, 1000.0, 1500.0, 2000.0, 3000.0, 4000.0, 5000.0, 6000.0, 8000.0,
]


def _lut_rgb(
    height_m: np.ndarray, sea: np.ndarray, sea_depth_m: np.ndarray, rng_m: tuple[float, float]
) -> np.ndarray:
    """Hypsometric tint per pixel from the shared adaptive-terrain palette.

    Same single source as the frontend's terrain mode (``palettes.json`` →
    ``build_adaptive_terrain_lut``): ETOPO ocean blues + Natural Earth land
    bands.  ``rng_m`` is the *unclamped* engine elevation range — the Gaea
    heightfield flattens the seafloor at −400 m, so the sea is looked up
    through its true depth channel instead (analogously, the LUT's
    min-anchored deep-blue gradient only lands in the ocean on the full
    range, which is exactly why the clamped grid must not drive it).
    """
    lut = build_adaptive_terrain_lut(rng_m[0], rng_m[1], sea_level=0.0)
    lo, hi = rng_m
    # Sea-level pin: land cells round UP so 0…+20 m never quantises into
    # the −10 m shallow-sea bin (one LUT step ≈ 20 m on planet-wide
    # anchors); sea cells are depth-keyed below and always shallow-blue.
    frac = (height_m - lo) / (hi - lo) * (len(lut) - 1)
    idx = np.where(height_m >= 0, np.ceil(frac), np.rint(frac))
    idx = np.clip(idx, 0, len(lut) - 1)
    rgb = lut[idx.astype(np.int32)] / 255.0
    sea_idx = np.clip(
        np.rint((-sea_depth_m - lo) / (hi - lo) * (len(lut) - 1)), 0, len(lut) - 1
    )
    rgb[sea] = lut[sea_idx[sea].astype(np.int32)] / 255.0
    return rgb


def contour_levels(h_min: float, h_max: float) -> tuple[np.ndarray, np.ndarray]:
    """(minor, major) contour levels in metres, land only (>= 0)."""

    def ladder(step: float) -> np.ndarray:
        lo = max(np.ceil(h_min / step) * step, step)
        return np.arange(lo, h_max, step)

    minor_all = ladder(CONTOUR_MINOR_M)
    major = ladder(CONTOUR_MAJOR_M)
    minor = np.setdiff1d(minor_all, major)
    return minor, major


def _paper_texture(n: int, seed: int = 7) -> np.ndarray:
    """Multiplicative paper grain in [1−s, 1]: low-frequency fibres plus
    fine speckle, both normalised to unit peak before mixing."""
    from scipy.ndimage import gaussian_filter

    rng = np.random.default_rng(seed)
    fibre = gaussian_filter(rng.normal(0.0, 1.0, (n, n)), sigma=n / 50.0)
    speckle = rng.normal(0.0, 1.0, (n, n))
    grain = 0.6 * fibre / np.abs(fibre).max() + 0.4 * speckle / np.abs(speckle).max()
    shaded = 1.0 - PAPER_TEXTURE_STRENGTH * np.clip(grain, 0.0, None) * 2.0
    return np.asarray(shaded, dtype=np.float64)


def _wobble(vertices: np.ndarray, px_km: float, seed: int) -> np.ndarray:
    """Displace contour vertices along a low-frequency noise field — the
    mechanical mpl spline becomes an inked line without losing shape
    (amplitude stays far below one contour interval in plan distance)."""
    import opensimplex

    rng = opensimplex.OpenSimplex(seed)
    step = int(WOBBLE_WAVELENGTH_PX) // 4 or 1
    gx = np.arange(0, vertices[:, 0].max() + step, step * px_km)
    gy = np.arange(0, vertices[:, 1].max() + step, step * px_km)
    wl_km = WOBBLE_WAVELENGTH_PX * px_km
    field = rng.noise2array(gx / wl_km, gy / wl_km)
    amp = WOBBLE_AMPLITUDE_PX * px_km
    xi = np.clip((vertices[:, 0] / (step * px_km)).astype(int), 0, field.shape[1] - 1)
    yi = np.clip((vertices[:, 1] / (step * px_km)).astype(int), 0, field.shape[0] - 1)
    out = vertices.copy()
    out[:, 0] += amp * field[np.clip(yi - 1, 0, field.shape[0] - 1), xi]
    out[:, 1] += amp * field[yi, xi]
    return out


def _wobble_contours(cs: object, px_km: float, seed: int) -> None:
    # matplotlib ≥3.10 removed QuadContourSet.collections; get_paths() is the
    # supported accessor for the line geometries.
    for path in cs.get_paths():  # type: ignore[attr-defined]
        if len(path.vertices) > 2:
            path.vertices = _wobble(path.vertices, px_km, seed)


def _hand_tint_pass(rgb: np.ndarray, res: int) -> np.ndarray:
    """Raster side of the hand-drawn look: watercolour blur, plate
    misregistration, corner wear.  All are printing/material artefacts —
    they layer on top of the colour-authority tint without touching it."""
    from scipy.ndimage import gaussian_filter, map_coordinates

    # Watercolour diffusion: soften the tint edges slightly (a brush loads
    # pigment past a hard boundary; a press does not).
    rgb = gaussian_filter(rgb, sigma=WATERCOLOR_BLUR_PX)
    # Misregistration: the colour plate drifts off the ink plate — shift the
    # chroma layers a hair in opposite directions, luminance stays put.
    d = MISREGISTER_PX
    yy, xx = np.mgrid[0:rgb.shape[0], 0:rgb.shape[1]]
    r = map_coordinates(rgb[..., 0], [yy + d, xx + d], order=1, mode="nearest")
    b = map_coordinates(rgb[..., 2], [yy - d, xx - d], order=1, mode="nearest")
    rgb[..., 0], rgb[..., 2] = r, b
    # Corner wear: darken-free vignette toward paper white (thumb-worn edges).
    y, x = np.mgrid[0:res, 0:res]
    nx, ny = (x / res - 0.5) * 2, (y / res - 0.5) * 2
    corner = np.clip(np.hypot(nx, ny) - 1.05, 0.0, None) * 4.0
    paper = np.asarray(PAPER_RGB) / 255.0
    rgb = rgb + (paper - rgb) * (corner * VIGNETTE_STRENGTH)[..., None]
    return np.asarray(np.clip(rgb, 0.0, 1.0), dtype=np.float64)


def compose_rgb(
    inputs: ColorizeInputs,
    rng_m: tuple[float, float],
    *,
    res: int = 2048,
    hand: bool = False,
) -> np.ndarray:
    """The raster underlay as an (h, w, 3) float 0..1 image.

    ``res`` downsamples the 8K Gaea grid for matplotlib (the vector contours
    are drawn from the same downsampled field — 2048 keeps both the sheet
    crisp at A2 print size and the SVG file a few MB, not hundreds).
    ``rng_m`` is the unclamped engine elevation range driving the shared
    palette (see :func:`_lut_rgb`).  ``hand`` adds the printing/material
    artefacts of the hand-drawn variant.
    """
    f = inputs.height_m.shape[0] // res
    if inputs.height_m.shape[0] % res != 0:
        raise ValueError(f"grid {inputs.height_m.shape[0]} not divisible by res {res}")
    height = inputs.height_m.reshape(res, f, res, f).mean(axis=(1, 3))
    sea = inputs.sea_water.reshape(res, f, res, f).mean(axis=(1, 3)) > 0.5
    sea_depth = inputs.sea_depth_m.reshape(res, f, res, f).mean(axis=(1, 3))
    lake = (
        inputs.lake.reshape(res, f, res, f).mean(axis=(1, 3)) > 0.5
        if inputs.lake is not None
        else None
    )
    hs = hillshade(height, inputs.km_per_px * f)

    rgb = _lut_rgb(height, sea, sea_depth, rng_m)
    if lake is not None and lake.any():
        # Freshwater lakes: pale blue, flat ink (survey water convention) —
        # the filled surface is the water level, the DEM below is invisible.
        from scipy.ndimage import binary_erosion

        shore = lake & ~binary_erosion(lake)
        rgb[lake] = np.asarray((92, 148, 188)) / 255.0
        rgb[shore] = np.asarray((64, 120, 168)) / 255.0
    # Two-scale relief (see HILLSHADE_* constants): structural shadow from
    # the smoothed field, fine relief from the raw one.
    from scipy.ndimage import gaussian_filter

    smooth = gaussian_filter(height, sigma=HILLSHADE_STRUCT_SIGMA_PX)
    hs_struct = hillshade(smooth, inputs.km_per_px * f)
    relief = HILLSHADE_STRUCT_WEIGHT * hs_struct + (1.0 - HILLSHADE_STRUCT_WEIGHT) * hs
    # Multiply the relief into the land only (paper LDR pipeline — same
    # doctrine as the Blender leg's Standard view: the tint table is the
    # colour authority; survey convention keeps water flat ink).
    shade = (1.0 - HILLSHADE_STRENGTH) + HILLSHADE_STRENGTH * relief[..., None]
    rgb[~sea] = rgb[~sea] * np.broadcast_to(shade, rgb.shape)[~sea]
    # Saturation lift around the pixel's own luminance (keeps the palette's
    # hue ordering, counters the wash from stacking shade + grain).
    lum = rgb.mean(axis=2, keepdims=True)
    rgb = np.clip(lum + (rgb - lum) * COLOR_SATURATION, 0.0, 1.0)
    rgb *= _paper_texture(res)[..., None]
    if hand:
        rgb = _hand_tint_pass(rgb, res)
    return np.asarray(np.clip(rgb, 0.0, 1.0), dtype=np.float32)


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _subpaths(path: object) -> list[np.ndarray]:
    """Split a contour Path into its connected rings.

    QuadContourSet packs disconnected rings of one level into a single Path,
    separated by MOVETO codes (or NaN vertices).  Treating it as one
    polyline draws straight connector lines across the map — split on MOVETO
    and on vertex jumps far beyond the local step (also drops NaN seams).
    """
    from matplotlib.path import Path

    v = np.asarray(path.vertices)  # type: ignore[attr-defined]
    codes = getattr(path, "codes", None)
    jumps = np.hypot(*np.diff(v, axis=0).T)
    median = float(np.median(jumps)) if len(jumps) else 1.0
    out, start = [], 0
    for i in range(1, len(v)):
        broken = bool(np.isnan(jumps[i - 1])) or jumps[i - 1] > max(4.0 * median, 1e-9)
        if codes is not None and codes[i] == Path.MOVETO:
            broken = True
        if broken:
            out.append(v[start:i])
            start = i
    out.append(v[start:])
    return [s for s in out if len(s) >= 3]


def _ink_restroke(ax: Axes, cs: object, rgb: tuple[int, int, int], px_km: float, seed: int) -> None:
    """Re-ink one contour set with brush-width variation.

    A pen stroke wavers in width along its length; matplotlib draws uniform
    polylines.  Split each contour ring into re-stroke segments and modulate
    the segment width with the same low-frequency field family as the line
    wobble, then blank the original uniform line.
    """
    import opensimplex
    from matplotlib.collections import LineCollection

    rng = opensimplex.OpenSimplex(seed)
    seg_km = INK_SEGMENT_PX * px_km
    wl_km = WOBBLE_WAVELENGTH_PX * px_km
    base_hex = _hex(rgb)
    for path in cs.get_paths():  # type: ignore[attr-defined]
        for sub in _subpaths(path):
            v = np.asarray(sub)
            # Split the polyline into ~segment-length pieces (by arc length).
            dv = np.diff(v, axis=0)
            lens = np.hypot(dv[:, 0], dv[:, 1])
            cuts = [0]
            acc = 0.0
            for i, ln in enumerate(lens):
                acc += ln
                if acc >= seg_km:
                    cuts.append(i + 1)
                    acc = 0.0
            cuts.append(len(v))
            segs, lws = [], []
            for a, b in zip(cuts[:-1], cuts[1:], strict=True):
                if b - a < 2:
                    continue
                piece = v[a : b + 1]
                segs.append(piece)
                mid = piece[len(piece) // 2]
                n = rng.noise2array(
                    np.array([mid[0] / wl_km]), np.array([mid[1] / wl_km])
                )[0, 0]
                lws.append(1.0 + INK_LW_JITTER * n)
            if not segs:
                continue
            ax.add_collection(
                LineCollection(
                    segs, colors=[base_hex], linewidths=lws, zorder=6,
                    capstyle="round", joinstyle="round",
                )
            )
    # Blank the uniform source ink (geometry object stays for clabel).
    cs.set_alpha(0.0)  # type: ignore[attr-defined]


def render_carto(
    inputs: ColorizeInputs,
    out_dir: Path,
    rng_m: tuple[float, float],
    *,
    res: int = 2048,
    dpi: int = 300,
    title: str = "",
    contour_labels: bool = False,
    contours: bool = False,
    hand: bool = False,
    center_lat: float = 0.0,
    center_lon: float = 0.0,
) -> dict[str, object]:
    """Write ``carto/topo.svg`` + ``carto/topo.png``; returns sheet metadata.

    ``hand`` additionally writes ``topo_hand.png`` — the video-material
    variant with printing/material artefacts (watercolour tints, misregistered
    colour plates, re-inked line widths, brush-script annotations, corner
    wear).  The clean survey sheet stays the default deliverable.
    """
    import matplotlib

    matplotlib.use("Agg")
    # CJK-capable stack first (titles carry the body's Chinese name; without
    # this the glyphs render as boxes on a default matplotlib install).
    # Hand-drawn mode prefers KaiTi (brush script) for the annotations.
    stack = HAND_FONT_STACK if hand else [
        "Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "DejaVu Sans",
    ]
    matplotlib.rcParams["font.sans-serif"] = stack
    matplotlib.rcParams["axes.unicode_minus"] = False
    import matplotlib.pyplot as plt

    out_dir.mkdir(parents=True, exist_ok=True)
    f = inputs.height_m.shape[0] // res
    height = inputs.height_m.reshape(res, f, res, f).mean(axis=(1, 3))
    sea = inputs.sea_water.reshape(res, f, res, f).mean(axis=(1, 3)) > 0.5
    # Rivers only on land: Gaea's mask bleeds into the sea near mouths, and
    # survey sheets never ink submerged channels.
    rivers = inputs.rivers.reshape(res, f, res, f).mean(axis=(1, 3))
    rivers[sea] = 0.0
    km = res * inputs.km_per_px * f

    rgb = compose_rgb(inputs, rng_m, res=res, hand=hand)
    minor, major = contour_levels(float(height.min()), float(height.max()))

    fig, ax = plt.subplots(figsize=(12, 12), dpi=dpi)
    # Leave a head band for the suptitle; the map itself stays square.
    # Margins host the graticule degree labels (drawn just outside the axes):
    # 5% right + 6% bottom beats the label extents at the default DPI sizes.
    ax.set_position((0.04, 0.06, 0.90, 0.86))
    ax.imshow(rgb, extent=(0, km, 0, km), interpolation="bilinear", zorder=1)

    extent = (0, km, 0, km)
    px_km = inputs.km_per_px * f
    if contours:
        cs_minor = ax.contour(
            height, extent=extent, origin="upper", levels=minor,
            colors=[_hex(CONTOUR_MINOR_COLOR)], linewidths=CONTOUR_MINOR_LW, zorder=3,
        )
        cs_major = ax.contour(
            height, extent=extent, origin="upper", levels=major,
            colors=[_hex(CONTOUR_MAJOR_COLOR)], linewidths=CONTOUR_MAJOR_LW, zorder=4,
        )
        # Inked-line feel: displace contour vertices along a low-frequency
        # noise field (amplitude ≪ one contour interval in plan distance).
        _wobble_contours(cs_minor, px_km, WOBBLE_SEED)
        _wobble_contours(cs_major, px_km, WOBBLE_SEED + 1)
        if hand:
            # Re-stroke the wobbled contours with brush-width variation
            # (uniform source ink blanked; geometry objects stay for clabel).
            _ink_restroke(ax, cs_minor, CONTOUR_MINOR_COLOR, px_km, WOBBLE_SEED + 2)
            _ink_restroke(ax, cs_major, CONTOUR_MAJOR_COLOR, px_km, WOBBLE_SEED + 3)
        if contour_labels:
            ax.clabel(cs_major, fmt=lambda m: f"{m:.0f}",
                      fontsize=CONTOUR_LABEL_SIZE, colors="#6c4a28")

    if inputs.river_segments is not None and inputs.river_segment_flows is not None:
        # Vector channels (flow-graded width): mask-contour rendering of the
        # 1-cell channel band straightens rivers onto grid/45° lines.
        from matplotlib.collections import LineCollection

        flows = inputs.river_segment_flows
        # Width reads discharge (√-law on upstream cells — hydraulic
        # geometry, Leopold & Maddock) but stays inside survey-ink limits:
        # at this sheet's ~1:1.8 M scale, 0.25–1.4 pt = 0.09–0.5 mm ≈
        # 160–880 m on the ground — real sheets draw rivers ≤ 0.6 mm.
        w_n = np.clip(flows / max(flows.max(), 1.0), 0.0, 1.0) ** 0.5
        widths = 0.25 + 1.15 * w_n
        seg_list = [tuple(map(tuple, seg)) for seg in inputs.river_segments]
        ax.add_collection(LineCollection(
            seg_list, colors=[_hex(RIVER_COLOR)],
            linewidths=widths, zorder=5, capstyle="round",
        ))
    elif rivers.any():
        ax.contour(
            rivers, extent=extent, origin="upper", levels=[0.02, 0.2, 0.5],
            colors=[_hex(RIVER_COLOR)], linewidths=[RIVER_MIN_LW, 0.55, 0.8], zorder=5,
        )

    ax.set_xlim(0, km)
    ax.set_ylim(0, km)
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_edgecolor("#5a4632")
        spine.set_linewidth(1.2)

    _elevation_legend(ax, km, rng_m)
    _scale_bar(ax, km)
    _north_arrow(ax, km)
    _graticule(ax, km, center_lat, center_lon)
    if title:
        # Figure-level title: an axes title gets clipped by the axes box at
        # this size, suptitle sits above it regardless of layout.
        fig.suptitle(title, fontsize=TITLE_SIZE, color="#4a3620")

    outputs = ["svg", "png"] if not hand else ["hand.png"]
    for ext in outputs:
        fig.savefig(out_dir / f"topo.{ext}", dpi=dpi, facecolor="#f8f4e9")
    plt.close(fig)
    return {
        "res": res,
        "extent_km": round(km, 1),
        "minor_levels": len(minor),
        "major_levels": len(major),
        "hand": hand,
    }


#: Graticule (survey grid): thin dashed rules with edge degree labels; the
#: step self-adapts so 3–8 lines cross the sheet.
GRATICULE_COLOR = "#8c7355"
GRATICULE_LW = 0.5
GRATICULE_STEPS_DEG = (1.0, 2.0, 5.0, 10.0, 15.0, 30.0)


def _graticule(ax: Axes, km: float, center_lat: float, center_lon: float) -> float:
    """Dashed lon/lat grid + edge degree labels; returns the step in degrees."""
    import math

    lat_span = km / 111.19
    lon_span = km / (111.19 * math.cos(math.radians(center_lat)))
    step = GRATICULE_STEPS_DEG[-1]
    for s in GRATICULE_STEPS_DEG:
        if max(lat_span, lon_span) / s <= 8:
            step = s
            break

    def deg_fmt(v: float, is_lat: bool) -> str:
        hemi = ("N", "S") if is_lat else ("E", "W")
        return f"{abs(v):g}°{hemi[0 if v >= 0 else 1]}"

    half_lat, half_lon = lat_span / 2, lon_span / 2
    lats = np.arange(
        math.ceil((center_lat - half_lat) / step) * step, center_lat + half_lat, step
    )
    lons = np.arange(
        math.ceil((center_lon - half_lon) / step) * step, center_lon + half_lon, step
    )
    pad = km * 0.012
    for lat in lats:
        y = (lat - center_lat) * 111.19 + km / 2
        ax.plot([0, km], [y, y], ls=(0, (6, 4)), color=GRATICULE_COLOR,
                lw=GRATICULE_LW, zorder=7)
        ax.text(km + pad * 0.3, y, deg_fmt(lat, True), fontsize=SCALEBAR_SIZE * 0.85,
                ha="left", va="center", color=GRATICULE_COLOR, zorder=7)
    for lon in lons:
        x = (lon - center_lon) * 111.19 * math.cos(math.radians(center_lat)) + km / 2
        ax.plot([x, x], [0, km], ls=(0, (6, 4)), color=GRATICULE_COLOR,
                lw=GRATICULE_LW, zorder=7)
        ax.text(x, -pad, deg_fmt(lon, False), fontsize=SCALEBAR_SIZE * 0.85,
                ha="center", va="top", color=GRATICULE_COLOR, zorder=7)
    return step


def _elevation_legend(ax: Axes, km: float, rng_m: tuple[float, float]) -> None:
    """Hypsometric legend sampled from the shared adaptive-terrain palette.

    Round chart-conventional bands (LEGEND_LADDER_M) clipped to the
    elevations that actually occur in the sheet — survey convention: legends
    list the round values present on the map, never the palette's internal
    anchored fractions.  Band colour = the shared LUT at the band's lower
    boundary, so sheet and legend stay single-sourced.  Vertical layout
    (horizontal strips put 4-digit numbers closer than one glyph width).
    """
    from matplotlib.patches import Rectangle

    lo, hi = rng_m
    edges = [b for b in LEGEND_LADDER_M if lo < b < hi]
    edges = [lo] + edges + [hi] if edges else [lo, hi]
    lut = build_adaptive_terrain_lut(lo, hi, sea_level=0.0)

    def lut_at(elev: float) -> tuple[int, int, int]:
        # Land lookups round UP: on planet-wide anchors one LUT step is
        # ~20 m, and rint at 0 m lands one bin below sea level — the 0 m
        # legend band rendered shallow-sea blue instead of land green.
        frac = (elev - lo) / (hi - lo) * (len(lut) - 1)
        idx = int(np.clip(np.ceil(frac) if elev >= 0 else np.rint(frac), 0, len(lut) - 1))
        c = lut[idx]
        return (int(c[0]), int(c[1]), int(c[2]))

    x0, y0 = km * 0.035, km * 0.055
    w, h = km * 0.013, km * 0.020
    for i in range(len(edges) - 1):
        ax.add_patch(
            Rectangle((x0, y0 + i * h), w, h, facecolor=_hex(lut_at(edges[i])),
                      edgecolor="#5a4632", linewidth=0.6, zorder=8)
        )
    for i, elev in enumerate(edges[1:-1]):
        ax.text(x0 + w + km * 0.006, y0 + (i + 1) * h, f"{elev:.0f}", fontsize=SCALEBAR_SIZE,
                ha="left", va="center", color="#1a1a1a", zorder=8)
    n_bands = len(edges) - 1
    ax.text(x0 + w / 2, y0 + n_bands * h + km * 0.008, "高程 / m",
            fontsize=LEGEND_SIZE, ha="center", va="bottom", color="#1a1a1a", zorder=8)


def _scale_bar(ax: Axes, km: float) -> None:
    """Two-segment alternating bar, bottom-right, short (survey convention:
    a sixth of the sheet width reads as a glance, not a ruler)."""
    from matplotlib.patches import Rectangle

    seg_km = _nice_segment(km / 24)
    n_seg = 2
    x0, y0, h = km * 0.90 - n_seg * seg_km, km * 0.05, km * 0.007
    for i in range(n_seg):
        ax.add_patch(
            Rectangle((x0 + i * seg_km, y0), seg_km, h,
                      facecolor="#1a1a1a" if i % 2 == 0 else "#f8f4e9",
                      edgecolor="#1a1a1a", linewidth=0.7, zorder=8)
        )
    ax.text(x0, y0 - km * 0.024, "0", fontsize=SCALEBAR_SIZE, ha="center",
            color="#1a1a1a", zorder=8)
    ax.text(x0 + n_seg * seg_km, y0 - km * 0.024, f"{n_seg * seg_km:.0f} km",
            fontsize=SCALEBAR_SIZE, ha="center", color="#1a1a1a", zorder=8)


def _nice_segment(v: float) -> float:
    for step in (10, 25, 50, 100, 250, 500, 1000):
        if v <= step:
            return float(step)
    return 1000.0


def _north_arrow(ax: Axes, km: float) -> None:
    """North mark: the letter plus a half-dark diamond head, nothing more."""
    from matplotlib.patches import Polygon

    cx, tip = km * 0.945, km * 0.945
    w, dh = km * 0.009, km * 0.030
    ax.add_patch(
        Polygon([(cx, tip), (cx - w, tip - dh), (cx, tip - dh * 0.55)],
                closed=True, facecolor="#1a1a1a", edgecolor="#1a1a1a", lw=0.6, zorder=9)
    )
    ax.add_patch(
        Polygon([(cx, tip), (cx + w, tip - dh), (cx, tip - dh * 0.55)],
                closed=True, facecolor="#f8f4e9", edgecolor="#1a1a1a", lw=0.6, zorder=9)
    )
    ax.text(cx, tip + km * 0.008, "N", fontsize=16, color="#1a1a1a",
            ha="center", va="bottom", zorder=9)


def planet_display_name(data_dir: Path, world: str, planet_id: str) -> str:
    """Display body name from the world's system catalog.

    Catalog names follow「中文名 · English」; the English part (title case)
    is the sheet-title convention.  Falls back to the world id when the
    catalog or the body is missing (e.g. packs from other machines).
    """
    import yaml

    catalog = (
        data_dir / "worlds" / world / "layers" / "astronomy" / "derived" / "system_catalog.yaml"
    )
    if not catalog.exists():
        return world
    doc = yaml.safe_load(catalog.read_text(encoding="utf-8")) or {}
    bodies = doc.get("bodies", []) if isinstance(doc, dict) else doc
    for body in bodies:
        if isinstance(body, dict) and body.get("id") == planet_id:
            name = str(body.get("name", world))
            parts = name.split(" · ")
            return parts[1].strip() if len(parts) > 1 else parts[0].strip()
    return world


def carto_region(
    pack_dir: Path,
    out_dir: Path | None = None,
    *,
    gaea_dir: Path | None = None,
    res: int = 2048,
    dpi: int = 300,
    data_dir: Path | None = None,
    contour_labels: bool = False,
    contours: bool = False,
    hand: bool = False,
    title: str | None = None,
) -> dict[str, object]:
    """CLI entry: render the topographic sheet for a region pack directory."""
    import json

    inputs = load_inputs(pack_dir / "input", gaea_dir or pack_dir / "gaea-out")
    meta = json.loads((pack_dir / "input" / "meta.json").read_text(encoding="utf-8"))
    world = str(meta["source"].get("world", "?"))
    planet_id = str(meta["source"].get("planet", ""))
    name = (
        planet_display_name(data_dir or Path("data"), world, planet_id)
        if planet_id
        else world
    )
    center_lat, center_lon = float(meta["center_lat"]), float(meta["center_lon"])
    if title is None:
        lat_ns = "N" if center_lat >= 0 else "S"
        lon_ew = "E" if center_lon >= 0 else "W"
        title = (
            f"{name} —— "
            f"{abs(center_lat):.0f}°{lat_ns} {abs(center_lon):.0f}°{lon_ew} 附近"
        )
    # Unclamped engine range drives the shared palette (seafloor-clamped
    # Gaea heights would misplace the min-anchored deep-water gradient).
    # Palette anchor range: the planet-wide elevation range when the pack
    # records it (same elevation → same colour on every sheet/window,
    # cross-map comparability), falling back to the window range with a
    # virtual-ocean reserve for landlocked windows (sea anchors would
    # collapse and the min-anchored deep-water gradient would eat the
    # lowland bands).
    if "elevation_m_global" in meta:
        rng_m = (float(meta["elevation_m_global"][0]), float(meta["elevation_m_global"][1]))
    else:
        rng_lo, rng_hi = (float(v) for v in meta["height_png_range_m"])
        if rng_lo > float(meta["sea_level_m"]):
            rng_lo = float(meta["sea_level_m"]) - 1000.0
        rng_m = (rng_lo, rng_hi)
    return render_carto(
        inputs, out_dir or pack_dir / "carto", rng_m, res=res, dpi=dpi, title=title,
        contour_labels=contour_labels, contours=contours, hand=hand,
        center_lat=center_lat, center_lon=center_lon,
    )
