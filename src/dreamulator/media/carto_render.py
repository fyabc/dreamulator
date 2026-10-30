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
    from matplotlib.collections import LineCollection

from dreamulator.map.palettes import build_adaptive_terrain_lut

from .satellite_color import EARTH_KM_PER_DEG, ColorizeInputs, hillshade, load_inputs

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

#: The one water ink for rivers and lakes alike (survey single-colour
#: convention).  Depth is tuned for lowland legibility: the lowland greens
#: of the shared terrain LUT sit at luminance ≈107 (Rec.709), so the ink
#: stays ≈20 points darker (≈84) — at (72,119,148) it matched the greens'
#: luminance almost exactly and vanished on 0–200 m plains (2026-10-16
#: user feedback).  Deep sea (LUT) reaches ≈73, so the ink never crosses it.
RIVER_COLOR = (44, 92, 130)
#: Lake shore ring: the same blue a step deeper — a crisp outline keeps
#: small lakes readable where the fill alone would wash against greens.
LAKE_SHORE_COLOR = (34, 78, 116)
#: Perennially ice-covered lakes: pale ice fill over the same shoreline
#: ring, following the permanent-ice convention of national topo sheets
#: (blue-tinted ice areas carrying their own symbol rather than the open-
#: water ink).  Seasonal cover keeps the water ink; lake_ice.months.npy's
#: 12-month class is the trigger.
LAKE_ICE_COLOR = (209, 230, 240)
RIVER_MIN_LW = 0.7
#: Flow-regime line styles: US Topo's solid perennial and dash-dot
#: non-perennial convention, restricted to the two classes monthly data can
#: support honestly.  Dash and gap lengths are in points.  Non-perennial
#: channels use butt caps, and their marks are longer than the line width:
#: round, width-long dots read as a string of tiny lakes rather than as a
#: river (2026-10-17 sheet review).
RIVER_LS_NON_PERENNIAL = (0, (12.0, 2.4, 1.8, 2.4, 1.8, 2.4))

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
#: Legend annotation tier (2026-10-17 review): elevation numbers/titles and
#: the boxed river-regime legend read as furniture, not map content, and
#: stay a step smaller than scale-bar labels.
LEGEND_SMALL_SIZE = 10.5

#: Chinese display names for biome legend rows (print artefact convention,
#: same as the Chinese sheet title).  Missing names fall back to the
#: English biome id.
BIOME_DISPLAY_ZH: dict[str, str] = {
    "tropical_rainforest": "热带雨林",
    "tropical_seasonal_forest": "热带季雨林",
    "tropical_savanna": "热带稀树草原",
    "tropical_desert": "热带荒漠",
    "temperate_rainforest": "温带雨林",
    "temperate_forest": "温带森林",
    "temperate_grassland": "温带草原",
    "temperate_desert": "温带荒漠",
    "boreal_forest": "北方针叶林",
    "boreal_shrubland": "北方灌丛",
    "tundra": "苔原",
    "ice": "冰盖",
    "lake": "湖泊",
    "ocean": "海洋",
}


def _combined_legend(
    ax: Axes,
    km: float,
    regimes: np.ndarray | None,
    biome_entries: list[tuple[str, tuple[int, int, int]]],
    *,
    river_rgb: tuple[int, int, int] = RIVER_COLOR,
) -> None:
    """The sheet's single legend box: river regime rows with biome swatches
    appended below (one frame for everything — sheets that carry no class
    legend at all pass an empty list and get the river-only box).

    River rows reuse the survey sheet's continuous-dash samples; biome rows
    are swatch + display name, same pitch.  Box geometry follows
    :func:`_river_regime_legend` so both stay in the same visual family.
    """
    from matplotlib.collections import LineCollection
    from matplotlib.patches import Rectangle

    present = [r for r in (0, 1) if regimes is not None and np.any(regimes == r)]
    if not present and not biome_entries:
        return

    x0 = ax.get_xlim()[0] + (ax.get_xlim()[1] - ax.get_xlim()[0]) * 0.035
    points_per_unit = _points_per_data_unit(ax)
    pad_x, pad_y = km * 0.009, km * 0.006
    sample_len = km * 0.026
    swatch_w = km * 0.011
    text_gap = km * 0.007
    row_h = title_h = km * 0.0195
    names = ["常流河", "非常流河"] + [BIOME_DISPLAY_ZH.get(nm, nm) for nm, _ in biome_entries]
    text_w = max(len(s) for s in names) * LEGEND_SMALL_SIZE * 0.95 / 72 / (12 * 0.90) * km
    n_rows = len(present) + len(biome_entries)
    box_w = pad_x + max(sample_len, swatch_w) + text_gap + text_w + pad_x
    box_h = pad_y + title_h + row_h * n_rows + pad_y
    y0 = km * 0.003
    ax.add_patch(
        Rectangle(
            (x0 - pad_x, y0),
            box_w,
            box_h,
            facecolor="#ffffff",
            edgecolor=_hex(river_rgb),
            linewidth=0.9,
            zorder=8,
        )
    )
    ax.text(
        x0 - pad_x + box_w / 2,
        y0 + box_h - pad_y - title_h / 2,
        "图例",
        fontsize=LEGEND_SMALL_SIZE + 1,
        ha="center",
        va="center",
        color="#1a1a1a",
        zorder=9,
    )
    sample = np.array([[[x0, 0.0], [x0 + sample_len, 0.0]]])
    y_top = y0 + box_h - pad_y - title_h

    def row_label(y: float, label: str) -> None:
        ax.text(
            x0 + max(sample_len, swatch_w) + text_gap,
            y,
            label,
            fontsize=LEGEND_SMALL_SIZE,
            ha="left",
            va="center",
            color="#1a1a1a",
            zorder=9,
        )

    for i, regime in enumerate(present):
        y = y_top - (i + 0.5) * row_h
        sample[0, :, 1] = y
        if regime == 0:
            paths = [sample[0].copy()]
            capstyle = "round"
            label = "常流河"
        else:
            paths, _widths = _continuous_dash_paths(
                sample, np.ones(1), RIVER_LS_NON_PERENNIAL[1], points_per_unit
            )
            capstyle = "butt"
            label = "非常流河"
        ax.add_collection(
            LineCollection(
                paths,
                colors=[_hex(river_rgb)],
                linewidths=[1.0] * len(paths),
                linestyles="solid",
                capstyle=capstyle,
                joinstyle="round",
                zorder=9,
            )
        )
        row_label(y, label)
    for j, (name, rgb) in enumerate(biome_entries):
        y = y_top - (len(present) + j + 0.5) * row_h
        ax.add_patch(
            Rectangle(
                (x0, y - row_h * 0.33),
                swatch_w,
                row_h * 0.66,
                facecolor="#{:02x}{:02x}{:02x}".format(*rgb),
                edgecolor="#5a4632",
                linewidth=0.6,
                zorder=9,
            )
        )
        row_label(y, BIOME_DISPLAY_ZH.get(name, name))


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
    -6000.0,
    -4000.0,
    -2000.0,
    -1000.0,
    -500.0,
    -200.0,
    -80.0,
    -30.0,
    -10.0,
    0.0,
    200.0,
    500.0,
    1000.0,
    1500.0,
    2000.0,
    3000.0,
    4000.0,
    5000.0,
    6000.0,
    8000.0,
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
    sea_idx = np.clip(np.rint((-sea_depth_m - lo) / (hi - lo) * (len(lut) - 1)), 0, len(lut) - 1)
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
    yy, xx = np.mgrid[0 : rgb.shape[0], 0 : rgb.shape[1]]
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


def two_scale_relief(
    height_m: np.ndarray, km_per_px: float, *, struct_sigma_px: float | None = None
) -> np.ndarray:
    """Structural + fine hillshade blend, 0..1 (see HILLSHADE_* constants).

    Reference sheets (OpenTopoMap style) read as two stacked shades — a
    structural shadow on the smoothed field plus a fine relief on the raw
    field.  A single-scale shade leaves the mid-frequencies flat.
    ``struct_sigma_px`` overrides the structural smoothing (callers working
    at a different grid resolution scale it to keep the same ground scale).
    """
    from scipy.ndimage import gaussian_filter

    sigma = HILLSHADE_STRUCT_SIGMA_PX if struct_sigma_px is None else struct_sigma_px
    hs = hillshade(height_m, km_per_px)
    smooth = gaussian_filter(height_m, sigma=sigma)
    hs_struct = hillshade(smooth, km_per_px)
    return HILLSHADE_STRUCT_WEIGHT * hs_struct + (1.0 - HILLSHADE_STRUCT_WEIGHT) * hs


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
        # 0.25 (any-of-4 at the 2x downsample): branched lakes end in narrow
        # arms a cell or two wide, and a 0.5 mean erodes those tips whole —
        # the river line then touched the mask edge over water that never
        # rendered, reading as a gap (2026-10-16 red-box report).
        inputs.lake.reshape(res, f, res, f).mean(axis=(1, 3)) > 0.25
        if inputs.lake is not None
        else None
    )

    rgb = _lut_rgb(height, sea, sea_depth, rng_m)
    # Multiply the two-scale relief into the land only (paper LDR pipeline —
    # same doctrine as the Blender leg's Standard view: the tint table is the
    # colour authority; survey convention keeps water flat ink).
    relief = two_scale_relief(height, inputs.km_per_px * f)
    shade = (1.0 - HILLSHADE_STRENGTH) + HILLSHADE_STRENGTH * relief[..., None]
    rgb[~sea] = rgb[~sea] * np.broadcast_to(shade, rgb.shape)[~sea]
    # Saturation lift around the pixel's own luminance (keeps the palette's
    # hue ordering, counters the wash from stacking shade + grain).
    lum = rgb.mean(axis=2, keepdims=True)
    rgb = np.clip(lum + (rgb - lum) * COLOR_SATURATION, 0.0, 1.0)
    rgb *= _paper_texture(res)[..., None]
    if hand:
        rgb = _hand_tint_pass(rgb, res)
    if lake is not None and lake.any():
        # Freshwater lakes go in LAST, after every multiply: the SAME water
        # blue as the river ink, flat — survey sheets use one water colour,
        # and the vector river lines carry no shade/saturation/paper either,
        # so a lake filled before the multiplies drifted away from them
        # (most visibly on flat lowlands, 2026-10-16 user feedback).  The
        # filled surface is the water level; the DEM below is invisible.
        from scipy.ndimage import binary_erosion

        shore = lake & ~binary_erosion(lake)
        rgb[lake] = np.asarray(RIVER_COLOR) / 255.0
        if inputs.lake_ice_months is not None:
            # Class channel: a block is frozen when any subpixel is (max,
            # not mean — averaging would dissolve the 12-month class).
            months = inputs.lake_ice_months.reshape(res, f, res, f).max(axis=(1, 3))
            rgb[lake & (months >= 12)] = np.asarray(LAKE_ICE_COLOR) / 255.0
        rgb[shore] = np.asarray(LAKE_SHORE_COLOR) / 255.0
    # Intertidal (drying-foreshore) band: pixels within ±2 m of sea level
    # across the waterline, painted flat after every multiply like the lake
    # fill — the charting convention's own colour (IHO S-52 DEPIT; same
    # constants as the canvas mosaic, single source).  A rendering class,
    # not a land/sea test.
    from dreamulator.map.td_canvas_mosaic import INTERTIDAL_M, INTERTIDAL_RGB

    if INTERTIDAL_M is not None:
        band = (height >= INTERTIDAL_M[0]) & (height <= INTERTIDAL_M[1])
        rgb[band] = np.asarray(INTERTIDAL_RGB, dtype=np.float64)
    return np.asarray(np.clip(rgb, 0.0, 1.0), dtype=np.float32)


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _points_per_data_unit(ax: Axes) -> float:
    """Display points per data unit on an equal-aspect sheet."""
    ax.apply_aspect()
    x0, x1 = ax.get_xlim()
    return float(ax.get_window_extent().width * 72.0 / ax.figure.dpi / abs(x1 - x0))


def _continuous_dash_paths(
    segments: np.ndarray,
    widths: np.ndarray,
    pattern: tuple[float, ...],
    points_per_unit: float,
) -> tuple[list[np.ndarray], list[float]]:
    """Cut one chain into continuous on-strokes for an on/off dash pattern.

    Each output path is ONE visible stroke, possibly following many of the
    original sub-pixel segments around bends.  Butt caps therefore occur
    only at true dash ends, never at the extraction segments inside a
    stroke.  The pattern is scaled once by the chain's median width, while
    each stroke's own width is the overlap-length-weighted mean of its
    source segments; downstream width grading survives without changing
    the dash rhythm from segment to segment.
    """
    lengths = np.hypot(*(segments[:, 1] - segments[:, 0]).T) * points_per_unit
    if len(segments) == 0 or float(lengths.sum()) <= 0.0:
        return [], []
    pattern_scaled = np.asarray(pattern, dtype=np.float64) * float(np.median(widths))
    period = float(pattern_scaled.sum())
    on_offsets: list[float] = []
    on_lengths: list[float] = []
    cursor = 0.0
    for j, dash in enumerate(pattern_scaled):
        if j % 2 == 0:
            on_offsets.append(cursor)
            on_lengths.append(float(dash))
        cursor += float(dash)

    starts = np.concatenate(([0.0], np.cumsum(lengths)))
    total = float(starts[-1])
    periods = max(1, int(np.ceil(total / period)))
    bases = np.arange(periods, dtype=np.float64) * period
    on_starts = bases[:, None] + np.asarray(on_offsets)[None, :]
    on_ends = on_starts + np.asarray(on_lengths)[None, :]
    on_starts_flat = on_starts.ravel()
    on_ends_flat = on_ends.ravel()

    # (on-interval id, clipped start, clipped end, width, overlap length)
    pieces: list[tuple[int, np.ndarray, np.ndarray, float, float]] = []
    for i, (xy0, xy1) in enumerate(segments):
        start, end = float(starts[i]), float(starts[i + 1])
        if end <= start:
            continue
        k0 = int(np.searchsorted(on_ends_flat, start, side="right"))
        k1 = int(np.searchsorted(on_starts_flat, end, side="left"))
        for k in range(k0, min(k1, len(on_starts_flat))):
            a = max(start, float(on_starts_flat[k]))
            b = min(end, float(on_ends_flat[k]))
            if b <= a:
                continue
            f0 = (a - start) / (end - start)
            f1 = (b - start) / (end - start)
            p0 = xy0 + (xy1 - xy0) * f0
            p1 = xy0 + (xy1 - xy0) * f1
            pieces.append((k, p0, p1, float(widths[i]), b - a))

    paths: list[np.ndarray] = []
    path_widths: list[float] = []
    current_id = -1
    path: list[np.ndarray] = []
    overlap_sum = 0.0
    weighted_width = 0.0
    for on_id, p0, p1, width, overlap in pieces:
        if on_id != current_id:
            if path:
                paths.append(np.asarray(path))
                path_widths.append(weighted_width / overlap_sum)
            current_id = on_id
            path = [p0]
            overlap_sum = 0.0
            weighted_width = 0.0
        if not np.allclose(path[-1], p0, atol=1e-9, rtol=0.0):
            path.append(p0)
        path.append(p1)
        overlap_sum += overlap
        weighted_width += width * overlap
    if path:
        paths.append(np.asarray(path))
        path_widths.append(weighted_width / overlap_sum)
    return paths, path_widths


def _river_collections(
    segments: np.ndarray,
    flows: np.ndarray,
    regimes: np.ndarray | None,
    *,
    zorder: float = 5,
    points_per_unit: float = 1.0,
    ink: tuple[int, int, int] = RIVER_COLOR,
) -> list[LineCollection]:
    """Vector river collections, partitioned by perennial/non-perennial.

    Width reads discharge (a square-root law on upstream accumulation —
    hydraulic geometry, Leopold & Maddock) but stays inside survey-ink
    limits: at the 550 km sheet's ~1:1.8 M scale, 0.25–1.4 pt is
    0.09–0.49 mm, or roughly 160–880 m on the ground; real sheets draw
    rivers no wider than about 0.6 mm.  Both regimes use the same water
    ink; only the line style changes.  ``regimes=None`` is the legacy
    all-perennial rendering.

    Seasonal dashes are cut as continuous paths rather than delegated to
    Matplotlib per segment.  Chaikin chains contain thousands of sub-pixel
    segments: independent dash state makes them solid, while per-segment
    dash offsets make a noisy string of blue fragments.  Continuous strokes
    avoid both artefacts and put butt caps only at genuine dash ends.
    """
    from matplotlib.collections import LineCollection

    if len(segments) == 0:
        return []
    flows = np.asarray(flows, dtype=np.float64)
    w_n = np.clip(flows / max(float(flows.max()), 1.0), 0.0, 1.0) ** 0.5
    widths = 0.25 + 1.15 * w_n
    if regimes is None:
        regime_arr = np.zeros(len(segments), dtype=np.uint8)
    else:
        regime_arr = np.asarray(regimes)
        if regime_arr.shape != (len(segments),):
            raise ValueError(
                f"river regime shape {regime_arr.shape} does not match {len(segments)} segments"
            )

    new_chain = np.ones(len(segments), dtype=bool)
    new_chain[1:] = np.any(segments[1:, 0] != segments[:-1, 1], axis=1) | (
        regime_arr[1:] != regime_arr[:-1]
    )
    bounds = np.flatnonzero(new_chain).tolist() + [len(segments)]
    paths_by_regime: dict[int, list[np.ndarray]] = {0: [], 1: []}
    widths_by_regime: dict[int, list[float]] = {0: [], 1: []}
    for start, end in zip(bounds[:-1], bounds[1:], strict=True):
        regime = int(regime_arr[start])
        chain_widths = widths[start:end]
        if regime == 0:
            paths = [np.asarray(seg) for seg in segments[start:end]]
            path_widths = chain_widths.tolist()
        else:
            paths, path_widths = _continuous_dash_paths(
                segments[start:end], chain_widths, RIVER_LS_NON_PERENNIAL[1], points_per_unit
            )
        paths_by_regime[regime].extend(paths)
        widths_by_regime[regime].extend(path_widths)

    collections: list[LineCollection] = []
    for regime in (0, 1):
        paths = paths_by_regime[regime]
        if not paths:
            continue
        collections.append(
            LineCollection(
                paths,
                colors=[_hex(ink)],
                linewidths=widths_by_regime[regime],
                linestyles="solid",
                zorder=zorder,
                capstyle="round" if regime == 0 else "butt",
                joinstyle="round",
            )
        )
    return collections


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
                n = rng.noise2array(np.array([mid[0] / wl_km]), np.array([mid[1] / wl_km]))[0, 0]
                lws.append(1.0 + INK_LW_JITTER * n)
            if not segs:
                continue
            ax.add_collection(
                LineCollection(
                    segs,
                    colors=[base_hex],
                    linewidths=lws,
                    zorder=6,
                    capstyle="round",
                    joinstyle="round",
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
    svg: bool = False,
    center_lat: float = 0.0,
    center_lon: float = 0.0,
) -> dict[str, object]:
    """Write ``carto/topo.png`` (+ ``topo.svg`` when ``svg``); returns metadata.

    ``hand`` writes ``topo_hand.png`` instead — the video-material variant
    with printing/material artefacts (watercolour tints, misregistered
    colour plates, re-inked line widths, brush-script annotations, corner
    wear).  The clean survey sheet stays the default deliverable.
    """
    import matplotlib

    matplotlib.use("Agg")
    # CJK-capable stack first (titles carry the body's Chinese name; without
    # this the glyphs render as boxes on a default matplotlib install).
    # Hand-drawn mode prefers KaiTi (brush script) for the annotations.
    stack = (
        HAND_FONT_STACK
        if hand
        else [
            "Microsoft YaHei",
            "SimHei",
            "Noto Sans CJK SC",
            "DejaVu Sans",
        ]
    )
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
            height,
            extent=extent,
            origin="upper",
            levels=minor,
            colors=[_hex(CONTOUR_MINOR_COLOR)],
            linewidths=CONTOUR_MINOR_LW,
            zorder=3,
        )
        cs_major = ax.contour(
            height,
            extent=extent,
            origin="upper",
            levels=major,
            colors=[_hex(CONTOUR_MAJOR_COLOR)],
            linewidths=CONTOUR_MAJOR_LW,
            zorder=4,
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
            ax.clabel(
                cs_major, fmt=lambda m: f"{m:.0f}", fontsize=CONTOUR_LABEL_SIZE, colors="#6c4a28"
            )

    ax.set_xlim(0, km)
    ax.set_ylim(0, km)
    ax.set_aspect("equal")
    if inputs.river_segments is not None and inputs.river_segment_flows is not None:
        # Vector channels: mask-contour rendering of the 1-cell channel band
        # straightens rivers onto grid/45° lines.  Line style carries the
        # monthly flow regime; width still carries discharge.
        for collection in _river_collections(
            inputs.river_segments,
            inputs.river_segment_flows,
            inputs.river_segment_regimes,
            points_per_unit=_points_per_data_unit(ax),
        ):
            ax.add_collection(collection)
    elif rivers.any():
        ax.contour(
            rivers,
            extent=extent,
            origin="upper",
            levels=[0.02, 0.2, 0.5],
            colors=[_hex(RIVER_COLOR)],
            linewidths=[RIVER_MIN_LW, 0.55, 0.8],
            zorder=5,
        )

    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_edgecolor("#5a4632")
        spine.set_linewidth(1.2)

    _elevation_legend(ax, km, rng_m)
    _river_regime_legend(
        ax,
        inputs.river_segment_regimes,
        y_base_km=km * 0.003,
        ice_lakes=_has_perennial_ice(inputs),
        intertidal=_has_intertidal(inputs),
    )
    _scale_bar(ax, km)
    _north_arrow(ax, km)
    _graticule(ax, km, center_lat, center_lon, inputs.km_per_deg, inputs.projection)
    if title:
        # Figure-level title: an axes title gets clipped by the axes box at
        # this size, suptitle sits above it regardless of layout.
        fig.suptitle(title, fontsize=TITLE_SIZE, color="#4a3620")

    outputs = ["hand.png"] if hand else (["png"] + (["svg"] if svg else []))
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


def _pick_step(span_deg: float) -> float:
    """Graticule interval for one axis: the smallest class giving ≤8 lines."""
    for s in GRATICULE_STEPS_DEG:
        if span_deg / s <= 8:
            return s
    return GRATICULE_STEPS_DEG[-1]


def _graticule(
    ax: Axes,
    km: float,
    center_lat: float,
    center_lon: float,
    km_per_deg: float = EARTH_KM_PER_DEG,
    projection: str = "equirect",
) -> tuple[float, float]:
    """Dashed lon/lat grid + edge degree labels; returns the (lat, lon) steps.

    The two axes pick their intervals independently: at high latitudes a
    550 km window spans tens of degrees of longitude but only ~5 of latitude,
    so a shared step would leave a single parallel on the sheet.

    Pack v4+ windows are azimuthal-equidistant squares: parallels are arcs
    and meridians converge toward the pole, so the grid is drawn as projected
    polylines clipped to the frame (labels sit where each curve leaves it).
    Legacy equirect windows keep the straight-line approximation.
    """
    import math

    def deg_fmt(v: float, is_lat: bool) -> str:
        hemi = ("N", "S") if is_lat else ("E", "W")
        return f"{abs(v):g}°{hemi[0 if v >= 0 else 1]}"

    if projection == "azimuthal_equidistant":
        from dreamulator.map.td_canvas import CanvasGeometry

        radius_km = km_per_deg * 180.0 / math.pi
        geom = CanvasGeometry(center_lat, center_lon, radius_km, 1)
        half = km / 2.0
        # Covered ranges from the frame perimeter (a polar window can span
        # most longitudes; the pole itself may sit outside the frame).
        t = np.linspace(-half, half, 65)
        px = np.concatenate([t, t, np.full_like(t, -half), np.full_like(t, half)])
        py = np.concatenate([np.full_like(t, -half), np.full_like(t, half), t, t])
        plat, plon = geom.xy_to_latlon(px, py)
        dlon = (np.asarray(plon) - center_lon + 180.0) % 360.0 - 180.0
        lat_lo, lat_hi = float(np.min(plat)), float(np.max(plat))
        lon_lo, lon_hi = float(np.min(dlon)), float(np.max(dlon))
        lat_step = _pick_step(lat_hi - lat_lo)
        lon_step = _pick_step(lon_hi - lon_lo)
        pad = km * 0.012
        lons_probe = center_lon + np.linspace(lon_lo - lon_step, lon_hi + lon_step, 241)
        lats_probe = np.linspace(lat_lo - lat_step, lat_hi + lat_step, 241)
        lat_lines = np.arange(math.ceil(lat_lo / lat_step) * lat_step, lat_hi + 1e-9, lat_step)
        lon_lines = np.arange(
            math.ceil((center_lon + lon_lo) / lon_step) * lon_step,
            center_lon + lon_hi + 1e-9,
            lon_step,
        )
        for lat in lat_lines:
            xs, ys = geom.latlon_to_xy(np.full_like(lons_probe, lat), lons_probe)
            xs, ys = np.asarray(xs) + half, np.asarray(ys) + half
            ax.plot(xs, ys, ls=(0, (6, 4)), color=GRATICULE_COLOR, lw=GRATICULE_LW, zorder=7)
            edge = _edge_crossing(xs, ys, km, vertical=True)
            if edge is not None:
                side, x_edge, y_edge = edge
                ax.text(
                    x_edge + (pad * 0.3 if side == "right" else -pad * 0.3),
                    y_edge,
                    deg_fmt(lat, True),
                    fontsize=SCALEBAR_SIZE * 0.85,
                    ha="left" if side == "right" else "right",
                    va="center",
                    color=GRATICULE_COLOR,
                    zorder=7,
                )
        for lon in lon_lines:
            xs, ys = geom.latlon_to_xy(lats_probe, np.full_like(lats_probe, lon))
            xs, ys = np.asarray(xs) + half, np.asarray(ys) + half
            ax.plot(xs, ys, ls=(0, (6, 4)), color=GRATICULE_COLOR, lw=GRATICULE_LW, zorder=7)
            edge = _edge_crossing(xs, ys, km, vertical=False)
            if edge is not None:
                side, x_edge, y_edge = edge
                ax.text(
                    x_edge,
                    y_edge + (-pad * 0.6 if side == "bottom" else pad * 0.6),
                    deg_fmt((lon + 180.0) % 360.0 - 180.0, False),
                    fontsize=SCALEBAR_SIZE * 0.85,
                    ha="center",
                    va="top" if side == "bottom" else "bottom",
                    color=GRATICULE_COLOR,
                    zorder=7,
                )
        return lat_step, lon_step

    lat_span = km / km_per_deg
    lon_span = km / (km_per_deg * math.cos(math.radians(center_lat)))
    lat_step = _pick_step(lat_span)
    lon_step = _pick_step(lon_span)

    half_lat, half_lon = lat_span / 2, lon_span / 2
    lats = np.arange(
        math.ceil((center_lat - half_lat) / lat_step) * lat_step,
        center_lat + half_lat,
        lat_step,
    )
    lons = np.arange(
        math.ceil((center_lon - half_lon) / lon_step) * lon_step,
        center_lon + half_lon,
        lon_step,
    )
    pad = km * 0.012
    for lat in lats:
        y = (lat - center_lat) * km_per_deg + km / 2
        ax.plot([0, km], [y, y], ls=(0, (6, 4)), color=GRATICULE_COLOR, lw=GRATICULE_LW, zorder=7)
        ax.text(
            km + pad * 0.3,
            y,
            deg_fmt(lat, True),
            fontsize=SCALEBAR_SIZE * 0.85,
            ha="left",
            va="center",
            color=GRATICULE_COLOR,
            zorder=7,
        )
    for lon in lons:
        x = (lon - center_lon) * km_per_deg * math.cos(math.radians(center_lat)) + km / 2
        ax.plot([x, x], [0, km], ls=(0, (6, 4)), color=GRATICULE_COLOR, lw=GRATICULE_LW, zorder=7)
        ax.text(
            x,
            -pad,
            deg_fmt(lon, False),
            fontsize=SCALEBAR_SIZE * 0.85,
            ha="center",
            va="top",
            color=GRATICULE_COLOR,
            zorder=7,
        )
    return lat_step, lon_step


def _edge_crossing(
    xs: np.ndarray, ys: np.ndarray, km: float, *, vertical: bool
) -> tuple[str, float, float] | None:
    """First crossing of a projected polyline with the sheet frame.

    ``vertical=True`` looks for the right edge first (then left, for
    latitude labels on curves that exit left); ``vertical=False`` looks for
    the bottom edge first (then top).  Returns (side, x, y) in frame km.
    """
    order = (
        (("right", km, 0.0), ("left", 0.0, 0.0))
        if vertical
        else (("bottom", 0.0, 0.0), ("top", km, 0.0))
    )
    for side, edge_val, _ in order:
        for i in range(len(xs) - 1):
            a = xs[i] if vertical else ys[i]
            b = xs[i + 1] if vertical else ys[i + 1]
            if (a - edge_val) * (b - edge_val) <= 0 and abs(b - a) > 1e-12:
                f = (edge_val - a) / (b - a)
                other = ys[i] if vertical else xs[i]
                other_next = ys[i + 1] if vertical else xs[i + 1]
                pos = other + f * (other_next - other)
                if 0.0 <= pos <= km:
                    return (side, edge_val, pos) if vertical else (side, pos, edge_val)
    return None


def _has_intertidal(inputs: ColorizeInputs) -> bool:
    """The sheet carries a visible intertidal band (DEPIT strip around sea level)."""
    from dreamulator.map.td_canvas_mosaic import INTERTIDAL_M

    if INTERTIDAL_M is None or not bool(inputs.sea_water.any()):
        return False
    band = (inputs.height_m >= INTERTIDAL_M[0]) & (inputs.height_m <= INTERTIDAL_M[1])
    return bool(band.sum() > inputs.height_m.size * 1e-5)


def _has_perennial_ice(inputs: ColorizeInputs) -> bool:
    """True when the sheet carries at least one perennially ice-covered lake."""
    return bool(
        inputs.lake is not None
        and inputs.lake_ice_months is not None
        and np.any(inputs.lake & (inputs.lake_ice_months >= 12))
    )


def _river_regime_legend(
    ax: Axes,
    regimes: np.ndarray | None,
    *,
    y_base_km: float = 0.0,
    x_frac: float = 0.118,
    ice_lakes: bool = False,
    intertidal: bool = False,
) -> None:
    """Boxed two-class river-regime legend, listing only classes present.

    ``ice_lakes`` appends the perennial-ice lake swatch (pale ice fill) when
    the sheet has lakes whose monthly climate keeps them frozen year-round.
    ``intertidal`` appends the drying-foreshore swatch (IHO S-52 DEPIT) when
    the sheet carries an intertidal band — charts list the class in their
    symbol legends.

    The samples are generated by the same continuous-stroke cutter as the
    map itself, so the legend cannot drift away from the sheet's dash
    rhythm.  The box is white with a water-blue border and titled「图例」
    generically so later legends can join the same panel.  Line pitch is
    ~1.4x the glyph height — rows at the font's own size read as touching
    (2026-10-17 review).  ``x_frac`` places the box clear of the elevation
    numbers on the survey sheet (whose bar sits in the bottom-left corner);
    the biome sheet passes a smaller value to align with its categorical
    panel, and ``y_base_km`` stacks it above that panel without overlap.
    """
    from matplotlib.collections import LineCollection
    from matplotlib.patches import Rectangle

    if regimes is None or len(regimes) == 0:
        if not ice_lakes and not intertidal:
            return
        present = []
    else:
        present = [regime for regime in (0, 1) if np.any(regimes == regime)]
        if not present and not ice_lakes and not intertidal:
            return
    x0 = ax.get_xlim()[0] + (ax.get_xlim()[1] - ax.get_xlim()[0]) * x_frac
    km = ax.get_xlim()[1] - ax.get_xlim()[0]
    points_per_unit = _points_per_data_unit(ax)

    pad_x, pad_y = km * 0.009, km * 0.006
    sample_len = km * 0.026
    text_gap = km * 0.007
    row_h = title_h = km * 0.0195
    text_w = 5 * LEGEND_SMALL_SIZE * 0.95 / 72 / (12 * 0.90) * km
    box_w = pad_x + sample_len + text_gap + text_w + pad_x
    n_rows = len(present) + int(ice_lakes) + int(intertidal)
    box_h = pad_y + title_h + row_h * n_rows + pad_y
    ax.add_patch(
        Rectangle(
            (x0 - pad_x, y_base_km),
            box_w,
            box_h,
            facecolor="#ffffff",
            edgecolor=_hex(RIVER_COLOR),
            linewidth=0.9,
            zorder=8,
        )
    )
    ax.text(
        x0 - pad_x + box_w / 2,
        y_base_km + box_h - pad_y - title_h / 2,
        "图例",
        fontsize=LEGEND_SMALL_SIZE + 1,
        ha="center",
        va="center",
        color="#1a1a1a",
        zorder=9,
    )
    sample = np.array([[[x0, 0.0], [x0 + sample_len, 0.0]]])
    y_top = y_base_km + box_h - pad_y - title_h
    for i, regime in enumerate(present):
        y = y_top - (i + 0.5) * row_h
        sample[0, :, 1] = y
        if regime == 0:
            paths = [sample[0].copy()]
            capstyle = "round"
            label = "常流河"
        else:
            paths, _widths = _continuous_dash_paths(
                sample, np.ones(1), RIVER_LS_NON_PERENNIAL[1], points_per_unit
            )
            capstyle = "butt"
            label = "非常流河"
        ax.add_collection(
            LineCollection(
                paths,
                colors=[_hex(RIVER_COLOR)],
                linewidths=[1.0] * len(paths),
                linestyles="solid",
                capstyle=capstyle,
                joinstyle="round",
                zorder=9,
            )
        )
        ax.text(
            x0 + sample_len + text_gap,
            y,
            label,
            fontsize=LEGEND_SMALL_SIZE,
            ha="left",
            va="center",
            color="#1a1a1a",
            zorder=9,
        )

    if ice_lakes:
        iy = y_top - (len(present) + 0.5) * row_h
        swatch_w = km * 0.011
        ax.add_patch(
            Rectangle(
                (x0, iy - row_h * 0.32),
                swatch_w,
                row_h * 0.64,
                facecolor=_hex(LAKE_ICE_COLOR),
                edgecolor=_hex(LAKE_SHORE_COLOR),
                linewidth=0.7,
                zorder=9,
            )
        )
        ax.text(
            x0 + max(sample_len, swatch_w) + text_gap,
            iy,
            "常年封冻湖",
            fontsize=LEGEND_SMALL_SIZE,
            ha="left",
            va="center",
            color="#1a1a1a",
            zorder=9,
        )

    if intertidal:
        from dreamulator.map.td_canvas_mosaic import INTERTIDAL_RGB

        ty = y_top - (len(present) + int(ice_lakes) + 0.5) * row_h
        swatch_w = km * 0.011
        ax.add_patch(
            Rectangle(
                (x0, ty - row_h * 0.32),
                swatch_w,
                row_h * 0.64,
                facecolor="#{:02x}{:02x}{:02x}".format(
                    *(int(round(c * 255)) for c in INTERTIDAL_RGB)
                ),
                edgecolor="#5a4632",
                linewidth=0.7,
                zorder=9,
            )
        )
        ax.text(
            x0 + max(sample_len, swatch_w) + text_gap,
            ty,
            "潮间带",
            fontsize=LEGEND_SMALL_SIZE,
            ha="left",
            va="center",
            color="#1a1a1a",
            zorder=9,
        )


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

    x0, y0 = km * 0.035, km * 0.006
    w, h = km * 0.013 * 0.9, km * 0.020 * 0.9
    for i in range(len(edges) - 1):
        ax.add_patch(
            Rectangle(
                (x0, y0 + i * h),
                w,
                h,
                facecolor=_hex(lut_at(edges[i])),
                edgecolor="#5a4632",
                linewidth=0.6,
                zorder=8,
            )
        )
    for i, elev in enumerate(edges[1:-1]):
        ax.text(
            x0 + w + km * 0.005,
            y0 + (i + 1) * h,
            f"{elev:.0f}",
            fontsize=LEGEND_SMALL_SIZE,
            ha="left",
            va="center",
            color="#1a1a1a",
            zorder=8,
        )
    n_bands = len(edges) - 1
    ax.text(
        x0 + w / 2,
        y0 + n_bands * h + km * 0.006,
        "高程 / m",
        fontsize=LEGEND_SMALL_SIZE + 1,
        ha="center",
        va="bottom",
        color="#1a1a1a",
        zorder=8,
    )


def _scale_bar(ax: Axes, km: float) -> None:
    """Two-segment alternating bar, bottom-right, short (survey convention:
    a sixth of the sheet width reads as a glance, not a ruler)."""
    from matplotlib.patches import Rectangle

    seg_km = _nice_segment(km / 24)
    n_seg = 2
    x0, y0, h = km * 0.90 - n_seg * seg_km, km * 0.05, km * 0.007
    for i in range(n_seg):
        ax.add_patch(
            Rectangle(
                (x0 + i * seg_km, y0),
                seg_km,
                h,
                facecolor="#1a1a1a" if i % 2 == 0 else "#f8f4e9",
                edgecolor="#1a1a1a",
                linewidth=0.7,
                zorder=8,
            )
        )
    ax.text(
        x0, y0 - km * 0.024, "0", fontsize=SCALEBAR_SIZE, ha="center", color="#1a1a1a", zorder=8
    )
    ax.text(
        x0 + n_seg * seg_km,
        y0 - km * 0.024,
        f"{n_seg * seg_km:.0f} km",
        fontsize=SCALEBAR_SIZE,
        ha="center",
        color="#1a1a1a",
        zorder=8,
    )


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
        Polygon(
            [(cx, tip), (cx - w, tip - dh), (cx, tip - dh * 0.55)],
            closed=True,
            facecolor="#1a1a1a",
            edgecolor="#1a1a1a",
            lw=0.6,
            zorder=9,
        )
    )
    ax.add_patch(
        Polygon(
            [(cx, tip), (cx + w, tip - dh), (cx, tip - dh * 0.55)],
            closed=True,
            facecolor="#f8f4e9",
            edgecolor="#1a1a1a",
            lw=0.6,
            zorder=9,
        )
    )
    ax.text(
        cx, tip + km * 0.008, "N", fontsize=16, color="#1a1a1a", ha="center", va="bottom", zorder=9
    )


def fmt_deg(v: float) -> str:
    """Format a centre coordinate for titles: integral values drop the
    decimal, half-degree centres keep one (a plain ``:.0f`` rounds 21.5 up
    to 22 and the sheet stops matching its pack directory name)."""
    return f"{v:.0f}" if float(v) == int(v) else f"{v:.1f}"


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
    svg: bool = False,
    title: str | None = None,
) -> dict[str, object]:
    """CLI entry: render the topographic sheet for a region pack directory."""
    import json

    inputs = load_inputs(pack_dir / "input", gaea_dir or pack_dir / "gaea-out")
    meta = json.loads((pack_dir / "input" / "meta.json").read_text(encoding="utf-8"))
    world = str(meta["source"].get("world", "?"))
    planet_id = str(meta["source"].get("planet", ""))
    name = planet_display_name(data_dir or Path("data"), world, planet_id) if planet_id else world
    center_lat, center_lon = float(meta["center_lat"]), float(meta["center_lon"])
    if title is None:
        lat_ns = "N" if center_lat >= 0 else "S"
        lon_ew = "E" if center_lon >= 0 else "W"
        title = (
            f"{name} 地形图 —— {fmt_deg(abs(center_lat))}°{lat_ns} "
            f"{fmt_deg(abs(center_lon))}°{lon_ew} 附近"
        )
    # Fixed ±9000 m planet-wide palette anchor (same as the mosaic adaptive
    # LUT): one shared elevation axis across every sheet, window and canvas —
    # the same elevation always maps to the same colour, and no window's own
    # range renormalises the bands (a low island canvas must not spend its
    # white end at 3 km).  The meta range fields stay as record-keeping.
    rng_m = (-9000.0, 9000.0)
    return render_carto(
        inputs,
        out_dir or pack_dir / "carto",
        rng_m,
        res=res,
        dpi=dpi,
        title=title,
        contour_labels=contour_labels,
        contours=contours,
        hand=hand,
        svg=svg,
        center_lat=center_lat,
        center_lon=center_lon,
    )
