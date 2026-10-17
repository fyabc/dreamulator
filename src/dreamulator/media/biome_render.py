"""biome_render — categorical biome sheet (video chain render leg).

A flat choropleth of the engine's Whittaker biome classification, styled
after the classic world biome maps (the Wikipedia ``Vegetation.png``
convention): flat class fills with hairline class boundaries, the ocean
left as blank paper with an inked coastline, vector rivers, graticule,
and a categorical legend of the classes present in the window.

Colours come from ``palettes.json`` (``categorical.whittaker``) — the same
single source the frontend's biome mode uses — via
:func:`dreamulator.map.palettes.whittaker_colors`.  Class fills stay flat
(cartographic authority); a weak hillshade underlay keeps the terrain
legible without competing with the class hue.

Shares the sheet furniture (graticule / scale bar / north arrow / title)
with the survey sheet in :mod:`.carto_render`.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from dreamulator.map.palettes import hex_to_rgb, whittaker_colors

from .carto_render import (
    PAPER_RGB,
    TITLE_SIZE,
    _combined_legend,
    _graticule,
    _north_arrow,
    _paper_texture,
    _points_per_data_unit,
    _river_collections,
    _scale_bar,
    fmt_deg,
    planet_display_name,
)
from .satellite_color import ColorizeInputs, hillshade, load_inputs, reconcile_ocean_on_land

# --- sheet constants (cartographic choices) ---------------------------------

#: Class-boundary hairline: darken boundary pixels by this factor (a raster
#: hairline — a vector trace of every class edge would drown the sheet in
#: paths; 1 px at 2048 reads as a print hairline).
BOUNDARY_DARKEN = 0.72

#: Relief underlay strength for the land class fills (0 = flat, the classic
#: biome-map convention; the default keeps terrain legible at a level where
#: the class hue still dominates).
HILLSHADE_STRENGTH = 0.28

#: Water inks (survey freshwater convention — the palette's categorical
#: ``lake`` cyan is a UI accent, too loud for print).
LAKE_FILL = (92, 148, 188)
LAKE_SHORE = (64, 120, 168)
COASTLINE_RGB = (52, 84, 100)
#: One water family (user ruling 2026-10-17): the river ink is the lake
#: shore-ring tone — channels and lakes read as one hydrology.
BIOME_WATER_RGB = LAKE_SHORE


def compose_biome_rgb(
    inputs: ColorizeInputs,
    *,
    res: int = 2048,
    hillshade_strength: float = HILLSHADE_STRENGTH,
) -> tuple[np.ndarray, np.ndarray, list[tuple[str, tuple[int, int, int]]]]:
    """Biome sheet underlay: (h, w, 3) float 0..1 + sea mask + legend entries.

    The categorical grid is nearest-subsampled to the sheet resolution (class
    edges must stay crisp — block means would invent mixed colours).  The
    legend lists the classes actually present, in palette order, excluding
    ocean (blank paper) and missing.
    """
    n = inputs.height_m.shape[0]
    f = n // res
    if n % res != 0:
        raise ValueError(f"grid {n} not divisible by res {res}")

    # Same dry-ocean reconciliation as the satellite leg: erosion/refinement
    # can lift engine-ocean cells above the waterline — painting them with
    # the palette's ocean blue shows navy blobs on land.
    biome = reconcile_ocean_on_land(inputs.biome_codes, inputs.biome_legend, inputs.sea_water)[
        ::f, ::f
    ]
    sea = inputs.sea_water[::f, ::f]
    height = inputs.height_m[::f, ::f]

    palette_rgb = whittaker_colors()
    max_code = int(max(biome.max(initial=0), *inputs.biome_legend.keys()))
    table = np.full((max_code + 1, 3), 0.5, dtype=np.float32)  # missing → grey
    for code, name in inputs.biome_legend.items():
        hex_color = palette_rgb.get(name)
        if hex_color:
            table[code] = np.asarray(hex_to_rgb(hex_color), dtype=np.float32) / 255.0
    rgb = table[biome]

    # Ocean: blank paper (classic biome-map convention); the coastline ink
    # is drawn as a hairline below.
    paper = np.asarray(PAPER_RGB, dtype=np.float32) / 255.0
    rgb[sea] = paper

    # Lakes (endorheic fill mask): flat freshwater ink with a darker shore.
    if inputs.lake is not None:
        lake = inputs.lake[::f, ::f]
        if lake.any():
            from scipy.ndimage import binary_erosion

            shore = lake & ~binary_erosion(lake)
            rgb[lake] = np.asarray(LAKE_FILL, dtype=np.float32) / 255.0
            rgb[shore] = np.asarray(LAKE_SHORE, dtype=np.float32) / 255.0

    # Weak relief underlay on land only (class hue stays dominant).
    if hillshade_strength > 0:
        hs = hillshade(height, inputs.km_per_px * f)
        shade = (1.0 - hillshade_strength) + hillshade_strength * hs[..., None]
        rgb[~sea] = rgb[~sea] * np.broadcast_to(shade, rgb.shape)[~sea]

    # Class-boundary hairline: pixels whose 4-neighbourhood holds another
    # class (land only — the coastline gets its own ink).
    same = np.ones((res, res), dtype=bool)
    for shift in ((1, 0), (0, 1)):
        shifted = np.roll(biome, shift, axis=(0, 1))
        same &= biome == shifted
    boundary = ~same & ~sea
    rgb[boundary] *= BOUNDARY_DARKEN

    # Coastline ink: land pixels touching the sea.
    from scipy.ndimage import binary_dilation

    coast = binary_dilation(sea) & ~sea
    rgb[coast] = np.asarray(COASTLINE_RGB, dtype=np.float32) / 255.0

    rgb *= _paper_texture(res)[..., None]

    # Legend: classes present, palette order, ocean/missing excluded.
    present = set(int(c) for c in np.unique(biome)) - {0}
    order = {name: i for i, name in enumerate(palette_rgb)}
    entries = sorted(
        (
            (inputs.biome_legend[c], hex_to_rgb(palette_rgb[inputs.biome_legend[c]]))
            for c in present
            if inputs.biome_legend.get(c) in palette_rgb and inputs.biome_legend[c] != "ocean"
        ),
        key=lambda e: order[e[0]],
    )
    return np.asarray(np.clip(rgb, 0.0, 1.0), dtype=np.float32), sea, entries


def render_biome_sheet(
    inputs: ColorizeInputs,
    out_dir: Path,
    *,
    res: int = 2048,
    dpi: int = 300,
    title: str = "",
    hillshade_strength: float = HILLSHADE_STRENGTH,
    svg: bool = False,
    center_lat: float = 0.0,
    center_lon: float = 0.0,
) -> dict[str, object]:
    """Write ``biome.png`` (+ ``biome.svg`` when ``svg``); returns sheet metadata."""
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

    rgb, sea, entries = compose_biome_rgb(inputs, res=res, hillshade_strength=hillshade_strength)
    rivers = inputs.rivers[::f, ::f].astype(np.float32)
    rivers[sea] = 0.0

    fig, ax = plt.subplots(figsize=(12, 12), dpi=dpi)
    ax.set_position((0.04, 0.06, 0.90, 0.86))
    ax.imshow(rgb, extent=(0, km, 0, km), interpolation="nearest", zorder=1)

    ax.set_xlim(0, km)
    ax.set_ylim(0, km)
    ax.set_aspect("equal")
    if inputs.river_segments is not None and inputs.river_segment_flows is not None:
        for collection in _river_collections(
            inputs.river_segments,
            inputs.river_segment_flows,
            inputs.river_segment_regimes,
            points_per_unit=_points_per_data_unit(ax),
            ink=BIOME_WATER_RGB,
        ):
            ax.add_collection(collection)
    elif rivers.any():
        ax.contour(
            rivers,
            extent=(0, km, 0, km),
            origin="upper",
            levels=[0.5],
            colors=["#{:02x}{:02x}{:02x}".format(*BIOME_WATER_RGB)],
            linewidths=[0.7],
            zorder=5,
        )

    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_edgecolor("#5a4632")
        spine.set_linewidth(1.2)

    _combined_legend(ax, km, inputs.river_segment_regimes, entries, river_rgb=BIOME_WATER_RGB)
    _scale_bar(ax, km)
    _north_arrow(ax, km)
    _graticule(ax, km, center_lat, center_lon)
    if title:
        fig.suptitle(title, fontsize=TITLE_SIZE, color="#4a3620")

    outputs = ("png", "svg") if svg else ("png",)
    for ext in outputs:
        fig.savefig(out_dir / f"biome.{ext}", dpi=dpi, facecolor="#f8f4e9")
    plt.close(fig)
    return {"res": res, "extent_km": round(km, 1), "classes": len(entries)}


def biome_region(
    pack_dir: Path,
    out_dir: Path | None = None,
    *,
    gaea_dir: Path | None = None,
    res: int = 2048,
    dpi: int = 300,
    data_dir: Path | None = None,
    title: str | None = None,
    hillshade_strength: float = HILLSHADE_STRENGTH,
    svg: bool = False,
) -> dict[str, object]:
    """CLI entry: render the biome sheet for a region pack directory.

    The terrain source defaults to the best available build (``refined-out``
    → ``gaea-out`` → the pack's own ``input/`` grid, which needs no build
    step at all); rivers/lakes/sea come from the same source.
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
            f"{name} 群系图 —— {fmt_deg(abs(center_lat))}°{lat_ns} "
            f"{fmt_deg(abs(center_lon))}°{lon_ew} 附近"
        )
    return render_biome_sheet(
        inputs,
        out_dir or pack_dir / "carto",
        res=res,
        dpi=dpi,
        title=title,
        hillshade_strength=hillshade_strength,
        svg=svg,
        center_lat=center_lat,
        center_lon=center_lon,
    )
