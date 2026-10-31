"""relief_render — natural-colour shaded-relief sheet (video chain render leg).

Satellite-imagery style after NASA Blue Marble NG topography/bathymetry:
land colour comes from the engine's biome classification through the
satellite compositor (:func:`dreamulator.media.satellite_color.colorize` —
climate-authoritative hue, warped+blurred ecotone transitions, NPP and
surface-texture variation, rock on steep slopes), and elevation carries no
colour of its own: terrain reads only through the multi-scale hillshade.
The ocean is the compositor's depth-graded bathy gradient, unshaded.

The result is the imagery counterpart of the survey sheet (hypsometric
tints) and the biome sheet (flat choropleth): same furniture (vector
rivers, legends, scale bar, north arrow, graticule, title), no contours
and no elevation ladder — there is no elevation colour to key them to.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .carto_render import (
    HILLSHADE_STRUCT_SIGMA_PX,
    TITLE_SIZE,
    _combined_legend,
    _graticule,
    _north_arrow,
    _points_per_data_unit,
    _river_collections,
    _river_regime_legend,
    _scale_bar,
    fmt_deg,
    planet_display_name,
    two_scale_relief,
)
from .satellite_color import (
    BIOME_COLORS,
    ColorizeInputs,
    colorize,
    load_inputs,
    reconcile_ocean_on_land,
)

# --- sheet constants (cartographic choices) ---------------------------------

#: Ecotone blur width in engine cells.  The satellite leg's fixed σ20 px
#: lands at ~2.7 km on this grid — the class boundaries still read as
#: edges.  Blue-Marble-style imagery wants transitions a good fraction of
#: a climate cell wide (σ ≈ 0.2 cell ≈ 10 km here, zone ≈ ±2σ).
RELIEF_ECOTONE_CELLS = 0.20

#: Relief shading on land, centred on unity: the hillshade modulates
#: brightness AROUND 1.0 (sun-facing slopes lift, shadows drop) instead of
#: purely multiplying down.  A plain ``(1-s)+s·hs`` multiply darkens land by
#: ~20% on average — the sheet read as evening light next to the Blue
#: Marble NG reference, which keeps imagery luminosity with relief punch.
#: The swing is asymmetric (highlight shoulder < shadow): a symmetric
#: +0.45 pushed bright deserts and sun-facing crests into channel clipping
#: — warm whites lost their hue gradation (measured: 18% of the sheet core
#: above luminance 0.82, R pinned at 1.0).
#: The sea stays flat — its depth gradient carries the bathymetry.
RELIEF_SHADE_SWING = 0.52  # max fractional drop below 1.0
RELIEF_SHADE_SWING_BRIGHT = 0.35  # max fractional lift above 1.0
RELIEF_SHADE_GAIN = 2.5  # swing per unit of relief deviation from its mean
#: Surface-grain gain for the sheet.  The satellite albedo's full uncorrelated
#: fBm mottle measured LARGER than the relief signal itself on the sheet
#: (texture luminance std 0.018 vs shade std 0.013) and drowned the terrain —
#: the Blue-Marble reference carries no such background noise.  A reduced
#: gain keeps a whisper of canopy/dune life at well under half the relief.
RELIEF_TEXTURE_GAIN = 0.35
#: Mild mid-tone lift for the same reason: the satellite palette is tuned
#: "deliberately muted" for the Blender albedo chain; the sheet wants the
#: brighter composite-imagery family (exponent < 1 brightens mid-tones).
RELIEF_GAMMA = 1.0 / 1.12
#: One water family for the sheet (user ruling 2026-10-17): the river ink
#: IS the lake pseudo-depth gradient's deep end, so channels, lakes and
#: their shores read as one hydrology.
RELIEF_WATER_RGB = (74, 116, 156)


def compose_relief_rgb(
    inputs: ColorizeInputs,
    *,
    res: int = 2048,
    texture: bool = True,
    biome_colors: dict[str, tuple[int, int, int]] | None = None,
) -> tuple[np.ndarray, np.ndarray, list[tuple[str, tuple[int, int, int]]]]:
    """Relief-sheet underlay: (h, w, 3) float 0..1 + sea mask + legend entries.

    The satellite compositor runs at the full build grid with a wider
    ecotone blur (a fraction of the engine cell, see RELIEF_ECOTONE_CELLS),
    and the two-scale hillshade is likewise computed on the FULL field and
    multiplied in BEFORE the block-mean downsample: dune-scale relief
    survives into the sheet as luminance mottling, whereas shading the
    downsampled field erases it (flat deserts were the visible symptom).
    """
    n = inputs.height_m.shape[0]
    f = n // res
    if n % res != 0:
        raise ValueError(f"grid {n} not divisible by res {res}")

    sigma = RELIEF_ECOTONE_CELLS * inputs.cell_px if inputs.cell_px > 0 else None
    albedo = colorize(
        inputs,
        texture=texture,
        ecotone_sigma_px=sigma,
        texture_gain=RELIEF_TEXTURE_GAIN,
        biome_colors=biome_colors,
    ).astype(np.float32)
    albedo /= 255.0

    land = ~inputs.sea_water
    relief = two_scale_relief(
        inputs.height_m, inputs.km_per_px, struct_sigma_px=HILLSHADE_STRUCT_SIGMA_PX * f
    )
    # Deviation from the LAND mean (flat sea at hs≈0.707 would bias the
    # centre upward and over-lift every plain).
    dev = (relief - relief[land].mean()) * RELIEF_SHADE_GAIN
    shade = np.where(
        dev >= 0.0,
        1.0 + RELIEF_SHADE_SWING_BRIGHT * dev,
        1.0 + RELIEF_SHADE_SWING * dev,
    )
    shade = np.clip(shade, 1.0 - RELIEF_SHADE_SWING, 1.0 + RELIEF_SHADE_SWING_BRIGHT)
    albedo[land] = np.clip(albedo[land] ** RELIEF_GAMMA, 0.0, 1.0) * shade[land][..., None]
    albedo = np.clip(albedo, 0.0, 1.0)
    rgb = albedo.reshape(res, f, res, f, 3).mean(axis=(1, 3)).astype(np.float32)
    sea = inputs.sea_water.reshape(res, f, res, f).mean(axis=(1, 3)) > 0.5

    # Legend: land classes present (post ocean reconciliation, so classes
    # erased by it drop out), palette order of the satellite table — with
    # the same vegetation overrides the base layer used.
    biome = reconcile_ocean_on_land(inputs.biome_codes, inputs.biome_legend, inputs.sea_water)[
        ::f, ::f
    ]
    land_codes = set(int(c) for c in np.unique(biome[~sea]))
    merged = {**BIOME_COLORS, **(biome_colors or {})}
    order = {name: i for i, name in enumerate(merged)}
    entries = sorted(
        (
            (inputs.biome_legend[c], merged[inputs.biome_legend[c]])
            for c in land_codes
            if inputs.biome_legend.get(c) in merged
        ),
        key=lambda e: order[e[0]],
    )
    return rgb, sea, entries


def render_relief_sheet(
    inputs: ColorizeInputs,
    out_dir: Path,
    *,
    res: int = 2048,
    dpi: int = 300,
    title: str = "",
    graticule: bool = True,
    biome_legend: bool = False,
    svg: bool = False,
    center_lat: float = 0.0,
    center_lon: float = 0.0,
    biome_colors: dict[str, tuple[int, int, int]] | None = None,
) -> dict[str, object]:
    """Write ``relief.png`` (+ ``relief.svg`` when ``svg``); returns sheet metadata."""
    import matplotlib

    matplotlib.use("Agg")
    matplotlib.rcParams["font.sans-serif"] = [
        "Microsoft YaHei",
        "SimHei",
        "Noto Sans CJK SC",
        "DejaVu Sans",
    ]
    matplotlib.rcParams["axes.unicode_minus"] = False
    import matplotlib.pyplot as plt

    out_dir.mkdir(parents=True, exist_ok=True)
    n = inputs.height_m.shape[0]
    f = n // res
    km = res * inputs.km_per_px * f

    rgb, sea, entries = compose_relief_rgb(inputs, res=res, biome_colors=biome_colors)
    rivers = inputs.rivers[::f, ::f].astype(np.float32)
    rivers[sea] = 0.0

    fig, ax = plt.subplots(figsize=(12, 12), dpi=dpi)
    ax.set_position((0.04, 0.06, 0.90, 0.86))
    ax.imshow(rgb, extent=(0, km, 0, km), interpolation="bilinear", zorder=1)

    ax.set_xlim(0, km)
    ax.set_ylim(0, km)
    ax.set_aspect("equal")
    if inputs.river_segments is not None and inputs.river_segment_flows is not None:
        for collection in _river_collections(
            inputs.river_segments,
            inputs.river_segment_flows,
            inputs.river_segment_regimes,
            points_per_unit=_points_per_data_unit(ax),
            ink=RELIEF_WATER_RGB,
        ):
            ax.add_collection(collection)
    elif rivers.any():
        ax.contour(
            rivers,
            extent=(0, km, 0, km),
            origin="upper",
            levels=[0.5],
            colors=["#{:02x}{:02x}{:02x}".format(*RELIEF_WATER_RGB)],
            linewidths=[0.7],
            zorder=5,
        )

    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_edgecolor("#5a4632")
        spine.set_linewidth(1.2)

    if biome_legend:
        _combined_legend(ax, km, inputs.river_segment_regimes, entries, river_rgb=RELIEF_WATER_RGB)
    else:
        _river_regime_legend(ax, inputs.river_segment_regimes, y_base_km=km * 0.003, x_frac=0.035)
    _scale_bar(ax, km)
    _north_arrow(ax, km)
    if graticule:
        _graticule(ax, km, center_lat, center_lon, inputs.km_per_deg, inputs.projection)
    if title:
        fig.suptitle(title, fontsize=TITLE_SIZE, color="#4a3620")

    outputs = ("png", "svg") if svg else ("png",)
    for ext in outputs:
        fig.savefig(out_dir / f"relief.{ext}", dpi=dpi, facecolor="#f8f4e9")
    plt.close(fig)
    return {"res": res, "extent_km": round(km, 1), "classes": len(entries)}


def _load_vegetation_palette(path: Path | None) -> dict[str, tuple[int, int, int]] | None:
    """Read a JSON vegetation palette: biome name → ``#rrggbb`` or ``[r, g, b]``.

    The relief sheet's world-specific colour hook (e.g. a non-green
    photosynthetic canon): entries override the Earth-prior ``BIOME_COLORS``
    by name; unspecified names fall back to the default table.
    """
    import json

    if path is None:
        return None
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    out: dict[str, tuple[int, int, int]] = {}
    for name, value in raw.items():
        if isinstance(value, str):
            v = int(value.lstrip("#"), 16)
            out[str(name)] = ((v >> 16) & 255, (v >> 8) & 255, v & 255)
        else:
            out[str(name)] = (int(value[0]), int(value[1]), int(value[2]))
    return out


def relief_region(
    pack_dir: Path,
    out_dir: Path | None = None,
    *,
    gaea_dir: Path | None = None,
    res: int = 2048,
    dpi: int = 300,
    data_dir: Path | None = None,
    title: str | None = None,
    graticule: bool = True,
    biome_legend: bool = False,
    svg: bool = False,
    vegetation_palette: Path | None = None,
) -> dict[str, object]:
    """CLI entry: render the natural-colour relief sheet for a region pack.

    The terrain source defaults to the best available build (``refined-out``
    → ``gaea-out`` → the pack's own ``input/`` grid, which needs no build
    step at all), same fallback chain as the biome sheet.
    """
    import json

    if gaea_dir is None:
        for candidate in ("refined-out", "gaea-out", "input"):
            if (pack_dir / candidate).is_dir():
                gaea_dir = pack_dir / candidate
                break
    assert gaea_dir is not None  # pack_dir/input always exists (CLI-checked)
    inputs = load_inputs(pack_dir / "input", gaea_dir)
    meta = json.loads((pack_dir / "input" / "meta.json").read_text(encoding="utf-8"))
    world = str(meta["source"].get("world", "?"))
    planet_id = str(meta["source"].get("planet", ""))
    name = planet_display_name(data_dir or Path("data"), world, planet_id) if planet_id else world
    center_lat, center_lon = float(meta["center_lat"]), float(meta["center_lon"])
    if title is None:
        lat_ns = "N" if center_lat >= 0 else "S"
        lon_ew = "E" if center_lon >= 0 else "W"
        title = (
            f"{name} 遥感图 —— {fmt_deg(abs(center_lat))}°{lat_ns} "
            f"{fmt_deg(abs(center_lon))}°{lon_ew} 附近"
        )
    return render_relief_sheet(
        inputs,
        out_dir or pack_dir / "carto",
        res=res,
        dpi=dpi,
        title=title,
        graticule=graticule,
        biome_legend=biome_legend,
        svg=svg,
        center_lat=center_lat,
        center_lon=center_lon,
        biome_colors=_load_vegetation_palette(vegetation_palette),
    )
