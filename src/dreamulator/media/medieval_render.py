"""medieval_render — parchment illustrated map from a region pack.

The illustrated sibling of the survey sheet: no contours, no legend, no
scale — Crusader Kings / Battle for Wesnoth style.  Terrain speaks in
symbols (mountain ridges, forest stands, broad rivers), the sheet is
parchment with worn and scorched edges, and the title sits on a ribbon
inside the map frame.

    pack + gaea-out  →  carto/medieval.png

Shares only the data layer with carto_render (``load_inputs``); everything
downstream is a different drawing tradition.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from matplotlib.axes import Axes

from dreamulator.map.palettes import build_adaptive_terrain_lut

from .satellite_color import ColorizeInputs, load_inputs

# --- palette (illuminator's desk) -------------------------------------------
PARCHMENT_RGB = (214, 189, 148)
SCORCH_RGB = (82, 52, 30)
SEA_WASH = np.asarray((163, 170, 172)) / 255.0
INK = "#4a3422"
MOUNTAIN_INK = "#604632"
MOUNTAIN_SHADE = "#8a6c4c"
TREE_GREEN = "#42603a"
TREE_EDGE = "#31452c"
TREE_TRUNK = "#4a3822"
RIVER_BLUE = "#3a547a"
BANNER_RED = "#6e2226"
GOLD = "#c69c42"

#: Symbol fields.  Spacing is deliberately loose (illustration, not data):
#  a Wesnoth/CK sheet reads as herds and stands, not wallpaper.
MOUNTAIN_MIN_ELEV_M = 1200.0  # peaks live on the high ground
MOUNTAIN_GRID_PX = 36.0  # ridge-symbol spacing (sheet px at 2048)
MOUNTAIN_SIZE_KM = 0.016  # glyph height at mid-elevation (× sheet width)
TREE_GRID_PX = 32.0
TREE_RADIUS_KM = 0.0055
FOREST_BIOME_KEYS = ("forest", "jungle", "taiga", "rainforest")

#: Rivers: only the substantial channels get inked.
RIVER_LEVEL = 0.12  # depth-mask contour level that counts as "main"
RIVER_LW = 2.6
RIVER_TAPER_LW = 1.4

TITLE_SIZE = 24.0
HAND_FONT_STACK = ["KaiTi", "Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "DejaVu Sans"]

PARCHMENT_SEED = 11


def _grad_mag(a: np.ndarray) -> np.ndarray:
    gy, gx = np.gradient(a)
    return np.asarray(np.hypot(gx, gy))


def _mode_pool(codes: np.ndarray, res: int, f: int) -> np.ndarray:
    """Mode of each f×f block (categorical channels can't be averaged)."""
    from scipy.stats import mode

    return np.asarray(mode(codes.reshape(res, f, res, f), axis=(1, 3)).mode)


def _jitter_grid(mask: np.ndarray, step: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    """One candidate per step×step cell inside the mask, jittered."""
    g = np.random.default_rng(seed)
    n = mask.shape[0]
    ys, xs = [], []
    for y0 in range(0, n, step):
        for x0 in range(0, n, step):
            y = min(int(y0 + g.uniform(0, step)), n - 1)
            x = min(int(x0 + g.uniform(0, step)), n - 1)
            if mask[y, x]:
                ys.append(y)
                xs.append(x)
    return np.asarray(ys, dtype=int), np.asarray(xs, dtype=int)


def _parchment(
    n: int, sea: np.ndarray, sea_depth_m: np.ndarray, rng_m: tuple[float, float], seed: int
) -> np.ndarray:
    """Parchment ground: mottled hide, sea washed pale indigo, scorched rim.

    The sea wash mixes a low paint load of the shared palette's ocean ramp
    (looked up through the true depth channel, same doctrine as the survey
    sheet) into a neutral wash colour, so the sheet still agrees with the
    survey legend's blues.  The scorch is a noise-broken rim gradient —
    irregular, not circular.
    """
    from scipy.ndimage import gaussian_filter

    g = np.random.default_rng(seed)
    mottle = gaussian_filter(g.normal(0.0, 1.0, (n, n)), sigma=n / 18.0)
    mottle /= np.abs(mottle).max()
    rgb = np.ones((n, n, 3)) * (np.asarray(PARCHMENT_RGB) / 255.0)
    stains = (1.0 - 0.10 * np.clip(mottle, 0.0, None))[..., None]  # age marks
    rgb = rgb * stains

    lo, hi = rng_m
    lut = build_adaptive_terrain_lut(lo, hi, sea_level=0.0) / 255.0
    idx = np.clip(
        np.rint((-sea_depth_m - lo) / (hi - lo) * (len(lut) - 1)), 0, len(lut) - 1
    ).astype(int)
    rgb[sea] = 0.35 * lut[idx][sea] + 0.65 * SEA_WASH

    # Scorched rim: radial falloff broken by large-scale noise.
    yy, xx = np.mgrid[0:n, 0:n]
    r = np.hypot(xx - n / 2, yy - n / 2) / (n * 0.72)
    brk = gaussian_filter(g.normal(0.0, 1.0, (n, n)), sigma=n / 10.0)
    brk /= np.abs(brk).max()
    scorch = np.clip(np.clip(r - 0.92 - 0.10 * brk, 0.0, None) * 6.0, 0.0, 1.0)[..., None]
    scorched = np.asarray(SCORCH_RGB) / 255.0
    rgb = rgb + (scorched - rgb) * scorch
    return np.asarray(np.clip(rgb, 0.0, 1.0), dtype=np.float64)


def _mountains(ax: Axes, height: np.ndarray, sea: np.ndarray, km: float, seed: int) -> int:
    """Ridge-symbol herd: a peak glyph with a shaded east face per site."""
    from matplotlib.patches import Polygon

    n = height.shape[0]
    slope = _grad_mag(height)
    want = (height > MOUNTAIN_MIN_ELEV_M) & (~sea) & (slope > np.percentile(slope[~sea], 55))
    ys, xs = _jitter_grid(want, max(2, int(MOUNTAIN_GRID_PX * n / 2048)), seed)
    kmpp = km / n
    for y, x in zip(ys, xs, strict=True):
        # Taller glyphs on higher ground.
        h_km = (0.9 + 0.9 * min(height[y, x] / 6000.0, 1.0)) * km * MOUNTAIN_SIZE_KM
        cx, cy = x * kmpp, (n - 1 - y) * kmpp
        w = h_km * 1.15
        ax.add_patch(
            Polygon(
                [(cx - w, cy), (cx - w * 0.12, cy + h_km), (cx + w, cy)],
                closed=True,
                fill=False,
                edgecolor=MOUNTAIN_INK,
                lw=0.8,
                zorder=5,
            )
        )
        ax.add_patch(
            Polygon(
                [(cx - w * 0.12, cy + h_km), (cx + w, cy), (cx + w * 0.35, cy)],
                closed=True,
                facecolor=MOUNTAIN_SHADE,
                edgecolor="none",
                alpha=0.55,
                zorder=4,
            )
        )
    return len(ys)


def _trees(
    ax: Axes, inputs: ColorizeInputs, sea: np.ndarray, km: float, res: int, f: int, seed: int
) -> int:
    """Tree stands on the forest biomes (mode-pooled to the sheet grid)."""
    from matplotlib.patches import Circle

    forest = np.zeros(inputs.biome_codes.shape, dtype=bool)
    for code, name in inputs.biome_legend.items():
        if any(k in name.lower() for k in FOREST_BIOME_KEYS):
            forest |= inputs.biome_codes == code
    if not forest.any():
        return 0
    forest = _mode_pool(forest.astype(np.uint8), res, f).astype(bool) & ~sea
    ys, xs = _jitter_grid(forest, max(2, int(TREE_GRID_PX * res / 2048)), seed)
    kmpp = km / res
    for y, x in zip(ys, xs, strict=True):
        cx, cy = x * kmpp, (res - 1 - y) * kmpp
        r = km * TREE_RADIUS_KM
        ax.plot([cx, cx], [cy - r * 1.6, cy - r * 0.4], color=TREE_TRUNK, lw=0.7, zorder=4)
        ax.add_patch(
            Circle((cx, cy), r, facecolor=TREE_GREEN, edgecolor=TREE_EDGE, lw=0.4, zorder=4)
        )
    return len(ys)


def _rivers(ax: Axes, rivers: np.ndarray, km: float) -> int:
    """Broad indicative channels: only the deep mask contours get ink."""
    cs = ax.contour(
        rivers,
        extent=(0, km, 0, km),
        origin="upper",
        levels=[RIVER_LEVEL, 0.55],
        colors=[RIVER_BLUE],
        linewidths=[RIVER_TAPER_LW, RIVER_LW],
        zorder=6,
    )
    return len(cs.get_paths())


def _coastline(ax: Axes, sea: np.ndarray, km: float) -> None:
    ax.contour(
        sea.astype(float),
        extent=(0, km, 0, km),
        origin="upper",
        levels=[0.5],
        colors=[INK],
        linewidths=[1.4],
        zorder=6,
    )


def _title_banner(ax: Axes, km: float, title: str) -> None:
    """Ribbon across the top of the map: wine-red field, gold trim, tails."""
    from matplotlib.patches import Polygon

    cx, y = km / 2, km * 0.945
    w, h = km * 0.36, km * 0.028
    body = [(cx - w, y - h), (cx + w, y - h), (cx + w, y + h), (cx - w, y + h)]
    tail_l = [(cx - w, y - h), (cx - w, y + h), (cx - w - km * 0.022, y)]
    tail_r = [(cx + w, y - h), (cx + w, y + h), (cx + w + km * 0.022, y)]
    for pts in (body, tail_l, tail_r):
        ax.add_patch(
            Polygon(pts, closed=True, facecolor=BANNER_RED, edgecolor=GOLD, lw=1.2, zorder=9)
        )
    ax.text(
        cx,
        y - h * 0.28,
        title,
        fontsize=TITLE_SIZE,
        color="#e8d9a8",
        ha="center",
        va="center",
        zorder=10,
    )


def _compass_rose(ax: Axes, km: float) -> None:
    """Sixteen-point rose: two stacked stars, gold under ink, north up."""
    import math

    from matplotlib.patches import Circle, Polygon

    cx, cy, r0 = km * 0.88, km * 0.84, km * 0.050
    for long_frac, color, z in ((1.0, GOLD, 8), (0.62, INK, 9)):
        pts = []
        for i in range(16):
            ang = math.pi / 8 * i + math.pi / 2
            r = r0 * (long_frac if i % 2 == 0 else 0.42)
            pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
        ax.add_patch(
            Polygon(pts, closed=True, facecolor=color, edgecolor="#3a2818", lw=0.5, zorder=z)
        )
    ax.add_patch(
        Circle((cx, cy), r0 * 0.10, facecolor="#e8d9a8", edgecolor="#3a2818", lw=0.6, zorder=10)
    )
    ax.text(cx, cy + r0 * 1.18, "N", fontsize=15, color="#3a2818", ha="center", zorder=10)


def _frame(ax: Axes, km: float) -> None:
    """Double rule with diamond rosettes at the corners."""
    from matplotlib.patches import Polygon

    for off, lw in ((0.012, 1.6), (0.026, 0.7)):
        x0, x1 = km * off, km * (1 - off)
        ax.add_patch(
            Polygon(
                [(x0, x0), (x1, x0), (x1, x1), (x0, x1)],
                closed=True,
                fill=False,
                edgecolor=INK,
                lw=lw,
                zorder=8,
            )
        )
    d = km * 0.008
    for cx, cy in (
        (km * 0.019, km * 0.019),
        (km * 0.981, km * 0.019),
        (km * 0.019, km * 0.981),
        (km * 0.981, km * 0.981),
    ):
        ax.add_patch(
            Polygon(
                [(cx - d, cy), (cx, cy + d), (cx + d, cy), (cx, cy - d)],
                closed=True,
                facecolor=GOLD,
                edgecolor="#3a2818",
                lw=0.5,
                zorder=8,
            )
        )


def render_medieval(
    inputs: ColorizeInputs,
    out_dir: Path,
    rng_m: tuple[float, float],
    *,
    res: int = 2048,
    dpi: int = 300,
    title: str = "",
) -> dict[str, object]:
    """Write ``carto/medieval.png``; returns sheet metadata."""
    import matplotlib

    matplotlib.use("Agg")
    matplotlib.rcParams["font.sans-serif"] = HAND_FONT_STACK
    matplotlib.rcParams["axes.unicode_minus"] = False
    import matplotlib.pyplot as plt

    out_dir.mkdir(parents=True, exist_ok=True)
    if inputs.height_m.shape[0] % res != 0:
        raise ValueError(f"grid {inputs.height_m.shape[0]} not divisible by res {res}")
    f = inputs.height_m.shape[0] // res
    height = inputs.height_m.reshape(res, f, res, f).mean(axis=(1, 3))
    sea = inputs.sea_water.reshape(res, f, res, f).mean(axis=(1, 3)) > 0.5
    sea_depth = inputs.sea_depth_m.reshape(res, f, res, f).mean(axis=(1, 3))
    rivers = inputs.rivers.reshape(res, f, res, f).mean(axis=(1, 3))
    rivers[sea] = 0.0
    km = res * inputs.km_per_px * f

    rgb = _parchment(res, sea, sea_depth, rng_m, PARCHMENT_SEED)
    fig, ax = plt.subplots(figsize=(12, 12), dpi=dpi)
    ax.set_position((0.02, 0.02, 0.96, 0.96))
    ax.imshow(rgb, extent=(0, km, 0, km), interpolation="bilinear", zorder=1)

    n_mount = _mountains(ax, height, sea, km, seed=21)
    n_trees = _trees(ax, inputs, sea, km, res, f, seed=22)
    n_rivers = _rivers(ax, rivers, km)
    _coastline(ax, sea, km)
    _frame(ax, km)
    _compass_rose(ax, km)
    if title:
        _title_banner(ax, km, title)

    ax.set_xlim(0, km)
    ax.set_ylim(0, km)
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)

    out = out_dir / "medieval.png"
    fig.savefig(out, dpi=dpi, facecolor="#d6bd94")
    plt.close(fig)
    return {"mountains": n_mount, "trees": n_trees, "rivers": n_rivers}


def medieval_region(
    pack_dir: Path,
    out_dir: Path | None = None,
    *,
    gaea_dir: Path | None = None,
    res: int = 2048,
    dpi: int = 300,
    title: str | None = None,
) -> dict[str, object]:
    """CLI entry: render the medieval sheet for a region pack directory."""
    import json

    from .carto_render import planet_display_name

    inputs = load_inputs(pack_dir / "input", gaea_dir or pack_dir / "gaea-out")
    meta = json.loads((pack_dir / "input" / "meta.json").read_text(encoding="utf-8"))
    if title is None:
        world = str(meta["source"].get("world", "?"))
        planet_id = str(meta["source"].get("planet", ""))
        name = planet_display_name(Path("data"), world, planet_id) if planet_id else world
        lat_ns = "N" if meta["center_lat"] >= 0 else "S"
        lon_ew = "E" if meta["center_lon"] >= 0 else "W"
        title = (
            f"{name} · {abs(meta['center_lat']):.0f}°{lat_ns} "
            f"{abs(meta['center_lon']):.0f}°{lon_ew}"
        )
    rng_m = (float(meta["height_png_range_m"][0]), float(meta["height_png_range_m"][1]))
    return render_medieval(
        inputs, out_dir or pack_dir / "carto", rng_m, res=res, dpi=dpi, title=title
    )
