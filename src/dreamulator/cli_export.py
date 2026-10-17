"""Headless map-layer export CLI — bake layers to colour PNGs.

The colours come from the same ``palettes.json`` single source the frontend
reads, so the exported PNGs match the in-browser map rendering byte-for-byte
(modulo the 1-pixel antimeridian seam).  This is the取证 leg for the guard
axis: ``/read-map`` skill, ``ai civ``, and CI auditing all need headless layer
rasters without a browser or manual screenshots.

Usage:
    dreamulator export layers nacrea --layers terrain,koppen,biome,agriculture,habitability
"""

from __future__ import annotations

import math
import time
from pathlib import Path
from typing import TYPE_CHECKING

import typer
from pydantic import TypeAdapter
from rich.console import Console
from rich.table import Table

if TYPE_CHECKING:
    import numpy as np

from dreamulator.map.export import (
    export_cell_index_grid,
    render_categorical_layer,
    render_continuous_layer,
    render_plate_motion_layer,
    render_terrain_layer,
    render_value_layer,
    save_rgba_png,
)
from dreamulator.map.manager import MapManager
from dreamulator.map.models import CVTMesh, TectonicPlate
from dreamulator.map.palettes import (
    build_adaptive_terrain_lut,
    continuous_scale,
    koppen_colors,
    whittaker_colors,
)
from dreamulator.map.region_export import (
    RegionWindowError,
    export_region_pack,
    mesh_fingerprint,
    read_radius_km,
)
from dreamulator.world_manager import WorldManager

export_app = typer.Typer(
    help="Headless map-layer export utilities (colour PNGs matching the frontend).",
    no_args_is_help=True,
)
console = Console()

_VALID_LAYERS = frozenset(
    {
        "terrain",
        "koppen",
        "biome",
        "agriculture",
        "habitability",
        "plate_motion",
        "temperature",
        "precipitation",
        "pressure",
    }
)
#: Layers comparing --mesh (or the world mesh) against --compare-mesh.
_DIFF_LAYERS = frozenset({"temperature_diff", "precipitation_diff", "koppen_agreement"})

#: Köppen agreement colours: same class / same main group / different group.
_KOPPEN_AGREEMENT_COLORS = {"same": (46, 160, 67), "group": (234, 179, 8), "differ": (220, 38, 38)}


def _set_data_dir(data_dir: Path | None) -> None:
    import os

    if data_dir is not None:
        os.environ["DREAMULATOR_DATA_DIR"] = str(data_dir.resolve())


def _render_layer(
    name: str,
    mesh: CVTMesh,
    indices: np.ndarray,
    elev_min: float,
    elev_max: float,
    sea_level: float,
    omega_by_plate: dict[str, tuple[np.ndarray, float]] | None = None,
    radius_km: float = 6371.0,
) -> np.ndarray:
    if name == "terrain":
        lut = build_adaptive_terrain_lut(elev_min, elev_max, sea_level)
        return render_terrain_layer(mesh, indices, lut, elev_min, elev_max, sea_level)
    if name == "koppen":
        return render_categorical_layer(
            mesh, indices, "koppen_class", koppen_colors(), ocean_fallback="Ocean"
        )
    if name == "biome":
        return render_categorical_layer(mesh, indices, "biome", whittaker_colors())
    if name == "agriculture":
        return render_continuous_layer(
            mesh,
            indices,
            "agriculture_score",
            continuous_scale("agriculture"),
            normalize=lambda s: s / 100.0,
            land_only=True,
            sea_level=sea_level,
        )
    if name == "habitability":
        return render_continuous_layer(
            mesh,
            indices,
            "habitability_score",
            continuous_scale("habitability"),
            normalize=lambda s: s / 100.0,
            land_only=True,
            sea_level=sea_level,
        )
    if name == "plate_motion":
        if omega_by_plate is None:
            raise ValueError("plate_motion layer requires loaded plate Euler poles")
        return render_plate_motion_layer(mesh, indices, omega_by_plate, radius_km)
    # Climate layers: same ranges and land masks as frontend layerBakes.ts.
    if name == "temperature":  # fixed −40…+40 °C, land only
        return render_continuous_layer(
            mesh,
            indices,
            "temperature_C",
            continuous_scale("temperature"),
            normalize=lambda t: (t + 40.0) / 80.0,
            land_only=True,
            sea_level=sea_level,
        )
    if name == "precipitation":  # log10(P + 1) / log10(30001), land only
        return render_continuous_layer(
            mesh,
            indices,
            "precipitation_mm",
            continuous_scale("precip"),
            normalize=lambda p: math.log10(p + 1.0) / math.log10(30001.0),
            land_only=True,
            sea_level=sea_level,
        )
    if name == "pressure":  # annual ΔP, ±5 hPa, land and ocean; ice-cap/high-terrain mask
        import numpy as np

        dp = _cell_array(mesh, "pressure_anomaly_annual_hpa")
        reliable = np.array([c.slp_reduction_unreliable is not True for c in mesh.cells])
        return render_value_layer(
            dp, indices, continuous_scale("temperature"), lambda d: (d + 5.0) / 10.0, reliable
        )
    raise ValueError(f"Unknown layer: {name}")


def _cell_array(mesh: CVTMesh, field: str) -> np.ndarray:
    import numpy as np

    return np.array(
        [
            np.nan if getattr(c, field, None) is None else float(getattr(c, field))
            for c in mesh.cells
        ]
    )


def _render_diff_layer(
    name: str, mesh: CVTMesh, ref: CVTMesh, indices: np.ndarray, sea_level: float
) -> np.ndarray:
    """Difference layers ``mesh − ref`` (same ranges as the frontend error layers)."""
    import numpy as np

    land = np.array([c.elevation >= sea_level for c in mesh.cells])
    if name == "temperature_diff":  # ±20 K, land only
        delta = _cell_array(mesh, "temperature_C") - _cell_array(ref, "temperature_C")
        return render_value_layer(
            delta, indices, continuous_scale("temperature"), lambda d: (d + 20.0) / 40.0, land
        )
    if name == "precipitation_diff":  # ±2000 mm/yr, land only
        delta = _cell_array(mesh, "precipitation_mm") - _cell_array(ref, "precipitation_mm")
        return render_value_layer(
            delta, indices, continuous_scale("temperature"), lambda d: (d + 2000.0) / 4000.0, land
        )
    if name == "koppen_agreement":  # same class / same main group / different, land only
        colors = np.zeros((mesh.num_cells, 4), dtype=np.uint8)
        for i, (a, b) in enumerate(zip(mesh.cells, ref.cells, strict=True)):
            ka, kb = a.koppen_class, b.koppen_class
            if not land[i] or not ka or not kb or "Ocean" in (ka, kb):
                continue
            key = "same" if ka == kb else ("group" if ka[0] == kb[0] else "differ")
            colors[i, :3] = _KOPPEN_AGREEMENT_COLORS[key]
            colors[i, 3] = 255
        return np.asarray(colors[indices])
    raise ValueError(f"Unknown diff layer: {name}")


@export_app.command("layers")
def export_layers(
    world: str = typer.Argument(help="World name"),
    layers: str = typer.Option(
        "terrain,koppen,biome,agriculture,habitability",
        "--layers",
        "-l",
        help="Comma-separated layer names: terrain,koppen,biome,agriculture,habitability,"
        "plate_motion,temperature,precipitation,pressure; with --compare-mesh also "
        "temperature_diff,precipitation_diff,koppen_agreement",
    ),
    mesh_path: Path | None = typer.Option(
        None,
        "--mesh",
        help="Render this mesh file instead of the world's built mesh (e.g. a GCM projection "
        "from scripts/climate/gcm/gcm_to_mesh.py); map metadata still comes from the world",
    ),
    compare_mesh: Path | None = typer.Option(
        None,
        "--compare-mesh",
        help="Reference mesh for the *_diff / koppen_agreement layers (rendered as mesh − "
        "reference); must share the cell geometry",
    ),
    grid: str | None = typer.Option(
        None,
        "--grid",
        "-g",
        help="Output resolution WxH (default: map.yaml width/height)",
    ),
    planet: str | None = typer.Option(None, "--planet", "-p", help="Planet ID"),
    branch: str | None = typer.Option(None, "--branch", "-b", help="Branch name"),
    output: Path = typer.Option(Path("export/"), "--output", "-o", help="Output directory"),
    data_dir: Path | None = typer.Option(None, "--data-dir", help="Worlds data directory"),
) -> None:
    """Headlessly bake map layers to colour PNGs (frontend palette, byte-parity)."""
    _set_data_dir(data_dir)

    requested = [name.strip() for name in layers.split(",") if name.strip()]
    if not requested:
        console.print("[red]No layers requested.[/red]")
        raise typer.Exit(code=2) from None
    invalid = [name for name in requested if name not in _VALID_LAYERS | _DIFF_LAYERS]
    if invalid:
        console.print(f"[red]Unknown layer(s): {', '.join(invalid)}[/red]")
        console.print(f"  Valid layers: {', '.join(sorted(_VALID_LAYERS | _DIFF_LAYERS))}")
        raise typer.Exit(code=2) from None
    if any(name in _DIFF_LAYERS for name in requested) and compare_mesh is None:
        console.print("[red]*_diff / koppen_agreement layers need --compare-mesh.[/red]")
        raise typer.Exit(code=2) from None

    mgr = WorldManager()
    try:
        world_dir = mgr.world_dir(world)
    except FileNotFoundError:
        console.print(f"[red]World '{world}' not found[/red]")
        raise typer.Exit(code=1) from None

    mm = MapManager(world_dir, branch)

    planet_id = planet
    if planet_id is None:
        planets = mm.list_planets_with_maps()
        if not planets:
            console.print("[red]No map data found for this world.[/red]")
            raise typer.Exit(code=1) from None
        planet_id = planets[0]

    from dreamulator.map.export import find_mesh_file

    map_dir = mm._maps_dir(planet_id)
    mesh_file = find_mesh_file(map_dir) if map_dir is not None else None
    if map_dir is None or mesh_file is None:
        console.print(f"[red]No mesh file found for planet '{planet_id}'.[/red]")
        raise typer.Exit(code=1) from None

    meta = mm.get_map_metadata(planet_id)
    width = meta.width if meta else 4096
    height = meta.height if meta else 2048
    elev_min = meta.elevation_min_m if meta else -11_000.0
    elev_max = meta.elevation_max_m if meta else 9_000.0
    sea_level = meta.sea_level_m if meta else 0.0

    if grid is not None:
        try:
            w_str, h_str = grid.lower().split("x")
            width, height = int(w_str), int(h_str)
        except ValueError:
            console.print(f"[red]Invalid --grid '{grid}' (expected WxH, e.g. 4096x2048)[/red]")
            raise typer.Exit(code=2) from None

    from dreamulator.map.export import load_cvt_mesh_model

    if mesh_path is not None:
        if not mesh_path.exists():
            console.print(f"[red]Mesh file not found: {mesh_path}[/red]")
            raise typer.Exit(code=1) from None
        mesh_file = mesh_path
    mesh = load_cvt_mesh_model(mesh_file)
    ref_mesh: CVTMesh | None = None
    if compare_mesh is not None:
        ref_mesh = load_cvt_mesh_model(compare_mesh)
        if ref_mesh.num_cells != mesh.num_cells or any(
            a.id != b.id for a, b in zip(mesh.cells, ref_mesh.cells, strict=True)
        ):
            console.print("[red]--compare-mesh has a different cell geometry.[/red]")
            raise typer.Exit(code=1) from None

    console.print(
        f"Baking {len(requested)} layer(s) for {world}/{planet_id} "
        f"({width}×{height}, {mesh.num_cells:,} cells)…"
    )
    indices = export_cell_index_grid(mesh, width, height)
    output.mkdir(parents=True, exist_ok=True)

    radius_km = float(getattr(meta, "radius_km", 6371.0) or 6371.0)
    omega_by_plate: dict[str, tuple[np.ndarray, float]] | None = None
    if "plate_motion" in requested:
        plates_path = map_dir / "plates.json"
        if not plates_path.exists():
            console.print("[red]plate_motion layer needs plates.json — build first.[/red]")
            raise typer.Exit(code=1) from None
        import numpy as np

        plates = TypeAdapter(list[TectonicPlate]).validate_json(plates_path.read_bytes())
        omega_by_plate = {
            p.id: (
                np.asarray([p.euler_pole.x, p.euler_pole.y, p.euler_pole.z], dtype=float),
                float(p.euler_pole.omega_rad_yr),
            )
            for p in plates
        }

    table = Table(title=f"Exported layers — {world}/{planet_id}")
    table.add_column("Layer", style="cyan")
    table.add_column("File", style="green")
    table.add_column("Size", style="dim")

    for name in requested:
        start = time.perf_counter()
        if name in _DIFF_LAYERS:
            assert ref_mesh is not None
            rgba = _render_diff_layer(name, mesh, ref_mesh, indices, sea_level)
        else:
            rgba = _render_layer(
                name, mesh, indices, elev_min, elev_max, sea_level, omega_by_plate, radius_km
            )
        path = output / f"{name}.png"
        save_rgba_png(rgba, path)
        elapsed = time.perf_counter() - start
        size_kb = path.stat().st_size / 1024
        table.add_row(name, str(path), f"{size_kb:.0f} KB · {elapsed:.1f}s")

    console.print(table)


@export_app.command("region")
def export_region(
    world: str = typer.Argument(help="World name"),
    lat: float = typer.Option(0.0, "--lat", help="Region centre latitude (degrees)"),
    lon: float = typer.Option(0.0, "--lon", help="Region centre longitude (degrees)"),
    span_km: float = typer.Option(2500.0, "--span-km", help="Square region side length (km)"),
    climate: bool = typer.Option(
        True,
        "--climate/--no-climate",
        help="Also export the climate channels (precipitation/temperature/ice/köppen/biome)",
    ),
    seafloor_clamp: float = typer.Option(
        -400.0,
        "--seafloor-clamp",
        help="Gaea-ready height.gaea.png: seafloor clamp depth in metres "
        "(Gaea 2.3 caps Terrain Definition Height at 10 km)",
    ),
    out_res: int = typer.Option(
        2048,
        "--out-res",
        help="Pack raster resolution (square N×N; scalar channels are "
        "Delaunay-interpolated from cell centres, so N can exceed the "
        "base-grid crop without terracing)",
    ),
    planet: str | None = typer.Option(None, "--planet", "-p", help="Planet ID"),
    branch: str | None = typer.Option(None, "--branch", "-b", help="Branch name"),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Pack ROOT dir (channels land in <root>/input/; "
        "default: private/video/<world>-<lat>_<lon>_<span>km)",
    ),
    data_dir: Path | None = typer.Option(None, "--data-dir", help="Worlds data directory"),
) -> None:
    """Export a square region data pack for external renderers (Gaea/Blender chain)."""
    _set_data_dir(data_dir)

    mgr = WorldManager()
    try:
        world_dir = mgr.world_dir(world)
    except FileNotFoundError:
        console.print(f"[red]World '{world}' not found[/red]")
        raise typer.Exit(code=1) from None

    mm = MapManager(world_dir, branch)

    planet_id = planet
    if planet_id is None:
        planets = mm.list_planets_with_maps()
        if not planets:
            console.print("[red]No map data found for this world.[/red]")
            raise typer.Exit(code=1) from None
        planet_id = planets[0]

    from dreamulator.map.export import find_mesh_file, load_cvt_mesh_model

    map_dir = mm._maps_dir(planet_id)
    mesh_file = find_mesh_file(map_dir) if map_dir is not None else None
    if map_dir is None or mesh_file is None:
        console.print(f"[red]No mesh file found for planet '{planet_id}'.[/red]")
        raise typer.Exit(code=1) from None

    meta = mm.get_map_metadata(planet_id)
    width = meta.width if meta else 4096
    height = meta.height if meta else 2048
    elev_min = meta.elevation_min_m if meta else -11_000.0
    elev_max = meta.elevation_max_m if meta else 9_000.0
    sea_level = meta.sea_level_m if meta else 0.0
    radius_km = read_radius_km(map_dir)

    mesh = load_cvt_mesh_model(mesh_file)

    out_dir = output or (Path("private/video") / f"{world}-{lat:g}_{lon:g}_{span_km:g}km")
    input_dir = out_dir / "input"  # pack layout: input/ + gaea-out/ + color/
    console.print(
        f"Exporting region pack for {world}/{planet_id} — "
        f"centre ({lat:g}, {lon:g}), span {span_km:g} km → {input_dir}"
    )
    try:
        pack_meta = export_region_pack(
            mesh,
            center_lat=lat,
            center_lon=lon,
            span_km=span_km,
            radius_km=radius_km,
            grid_width=width,
            grid_height=height,
            elev_min_m=elev_min,
            elev_max_m=elev_max,
            sea_level_m=sea_level,
            out_dir=input_dir,
            source={
                "world": world,
                "planet": planet_id,
                "branch": branch,
                **mesh_fingerprint(mesh_file),
            },
            include_climate=climate,
            seafloor_clamp_m=seafloor_clamp,
            out_res=out_res,
        )
    except RegionWindowError as exc:
        console.print(f"[red]Region rejected: {exc}[/red]")
        raise typer.Exit(code=2) from None

    table = Table(title=f"Region pack — {world}/{planet_id} ({out_dir})")
    table.add_column("File", style="green")
    table.add_column("Size", style="dim")
    for path in sorted(input_dir.iterdir()):
        if path.is_file():
            table.add_row(path.name, f"{path.stat().st_size / 1024:.0f} KB")
    console.print(table)
    console.print(
        f"Grid {pack_meta['grid']['w']}×{pack_meta['grid']['h']} px · "
        f"extent {pack_meta['extent_km']['x']}×{pack_meta['extent_km']['y']} km · "
        f"elev {pack_meta['elevation_m']['min']:.0f}…{pack_meta['elevation_m']['max']:.0f} m · "
        f"ocean {pack_meta['ocean_fraction'] * 100:.1f}%"
    )
    max_off = pack_meta["alignment_probe_max_offset_deg"]
    if max_off > 1.0:
        console.print(
            f"[red]Alignment probe failed (max offset {max_off}° > 1°) — "
            "pack is suspect, do not use.[/red]"
        )
        raise typer.Exit(code=3) from None
    console.print(f"[green]Alignment probe OK (max offset {max_off}°).[/green]")


@export_app.command("colorize")
def export_colorize(
    pack: Path = typer.Argument(
        help="Region pack ROOT dir (with input/ subdir), e.g. private/video/nacrea-15_90_2350km"
    ),
    gaea: Path | None = typer.Option(
        None, "--gaea", "-g", help="Gaea build output dir (default: <pack>/gaea-out)"
    ),
    output: Path | None = typer.Option(
        None, "--output", "-o", help="Output dir (default: <pack>/color)"
    ),
    texture: bool = typer.Option(
        True,
        "--texture/--no-texture",
        help="Per-biome vegetation/surface grain (Sentinel-2-style mottling; default on)",
    ),
) -> None:
    """Satellite true-color compositing (video chain step ③).

    Engine biomes drive the base colours; Gaea masks (slope/wear/deposits/
    rivers/sea) modulate texture. Needs the 'media' extra (OpenEXR).
    """
    from dreamulator.media.satellite_color import colorize_region

    gaea_dir = gaea or (pack / "gaea-out")
    out_dir = output or (pack / "color")
    if not (pack / "input" / "meta.json").exists():
        console.print(f"[red]No input/meta.json in {pack} — is this a pack root?[/red]")
        raise typer.Exit(code=2) from None
    if not gaea_dir.is_dir():
        console.print(f"[red]Gaea output dir not found: {gaea_dir}[/red]")
        raise typer.Exit(code=2) from None

    console.print(f"Colorizing {pack}/input + {gaea_dir} → {out_dir}")
    try:
        paths = colorize_region(pack, gaea_dir, out_dir, texture=texture)
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None
    for name, path in paths.items():
        console.print(f"  [green]{name}[/green] → {path} ({path.stat().st_size / 1024:.0f} KB)")


@export_app.command("erode")
def export_erode(
    pack: Path = typer.Argument(
        help="Region pack ROOT dir (with input/ subdir), e.g. private/video/nacrea-15_90_2350km"
    ),
    steps: int = typer.Option(30, "--steps", help="SPL time steps"),
    dt_yr: float = typer.Option(5e4, "--dt", help="Step length (years)"),
    k_spl: float = typer.Option(2e-7, "--k", help="Stream-power erodibility K"),
    river_threshold: int = typer.Option(
        3000, "--river-threshold", help="Channel onset: upstream cells (rain-weighted)"
    ),
) -> None:
    """Programmatic SPL erosion (video chain step ② programmatic variant).

    Priority-Flood drainage (Barnes 2014) + implicit stream-power erosion
    (Braun & Willett 2013), driven by the pack's own precipitation field.
    Writes the gaea-out file vocabulary to <pack>/prog-out/ so every render
    leg (colorize/carto/blender) consumes it unchanged.
    """
    from typing import cast

    from dreamulator.map.prog_erosion import erode_region_pack

    if not (pack / "input" / "meta.json").exists():
        console.print(f"[red]No input/meta.json in {pack} — is this a pack root?[/red]")
        raise typer.Exit(code=2) from None

    console.print(f"Eroding {pack} (steps={steps}, dt={dt_yr:.0e} yr, K={k_spl:.0e})")
    info: dict[str, object] = erode_region_pack(
        pack, steps=steps, dt_yr=dt_yr, k_spl=k_spl, river_threshold=river_threshold
    )
    rng = cast("list[float]", info["height_range_m"])
    console.print(
        f"  prog-out/: rivers {info['river_pct_of_land']}% of land · "
        f"height [{rng[0]:.0f}, {rng[1]:.0f}] m"
    )


@export_app.command("refine")
def export_refine(
    pack: Path = typer.Argument(
        help="Region pack ROOT dir (with input/ subdir), e.g. private/video/nacrea-15_-100_550km"
    ),
    td: Path | None = typer.Option(
        None,
        "--td",
        help="terrain-diffusion repo clone (with .venv) — "
        "external tool, see terrain-chain manual for setup (not needed with --reuse-height)",
    ),
    river_threshold: int | None = typer.Option(
        None,
        "--river-threshold",
        help="Channel onset in upstream cells (default scales with grid: 3000 at pack resolution)",
    ),
    coast_warp: bool = typer.Option(
        False,
        "--coast-warp",
        help="Warp conditioning sea-land edges before "
        "inference (bends straight Voronoi shorelines; off by default)",
    ),
    reuse_height: bool = typer.Option(
        False,
        "--reuse-height",
        help="Skip TD inference and re-extract hydrology from the existing "
        "refined-out/height.meters.npy (fast iteration on drainage semantics)",
    ),
) -> None:
    """Terrain-diffusion refinement + hydrology (terrain chain step ②, main).

    Regenerates the landscape at 90 m from the pack's conditioning fields
    (inference runs in the external td venv), then extracts drainage
    (Priority-Flood rivers + endorheic lakes). Writes <pack>/refined-out/.
    """
    from dreamulator.media.terrain_refine import refine_region_pack

    if not (pack / "input" / "meta.json").exists():
        console.print(f"[red]No input/meta.json in {pack} — is this a pack root?[/red]")
        raise typer.Exit(code=2) from None
    if td is None and not reuse_height:
        console.print(
            "[red]--td is required for a full refine (or pass --reuse-height "
            "to re-extract from the cached refined DEM)[/red]"
        )
        raise typer.Exit(code=2) from None

    console.print(f"Refining {pack} via terrain-diffusion ({td.name if td else 'cached height'})")
    info = refine_region_pack(
        pack,
        td,
        river_threshold=river_threshold,
        coast_warp=coast_warp,
        reuse_height=reuse_height,
    )
    console.print(
        f"  refined-out/: res {info['res']}² · lakes {info['lakes_pct']}% of land · "
        f"{info['river_segments']} river segments"
    )


@export_app.command("carto")
def export_carto(
    pack: Path = typer.Argument(
        help="Region pack ROOT dir (with input/ subdir), e.g. private/video/nacrea-15_90_2350km"
    ),
    output: Path | None = typer.Option(
        None, "--output", "-o", help="Output dir (default: <pack>/carto)"
    ),
    gaea: Path | None = typer.Option(
        None,
        "--gaea",
        "-g",
        help="Build dir (default: <pack>/gaea-out; pass "
        "<pack>/prog-out for programmatic-erosion builds)",
    ),
    style: str = typer.Option(
        "survey",
        "--style",
        help="Sheet style: survey (contours+legend, topo.svg+topo.png) | "
        "hand (print-artefact variant, topo.hand.png) | "
        "medieval (parchment illustration, medieval.png) | "
        "biome (categorical biome sheet, biome.svg+biome.png)",
    ),
    title: str | None = typer.Option(None, "--title", help="Override the default sheet title"),
    res: int = typer.Option(2048, "--res", help="Contour grid resolution"),
    dpi: int = typer.Option(300, "--dpi", help="PNG output DPI"),
    data_dir: Path | None = typer.Option(
        None, "--data-dir", help="Worlds data dir (for the catalog body name in the title)"
    ),
    contour_labels: bool = typer.Option(
        False, "--contour-labels", help="Inline elevation labels on index contours (default off)"
    ),
    contours: bool = typer.Option(
        False,
        "--contours/--no-contours",
        help="Draw contour lines (default off — "
        "real-DEM reference sheets at small scale run tint-only, OpenTopoMap z≤11)",
    ),
) -> None:
    """Cartographic sheet (video chain step ③-alt): --style survey | hand | medieval | biome.

    survey = hypsometric tints + contours + legend/scale/graticule/north
    arrow (SVG + PNG).  hand = survey with print artefacts (watercolour,
    misregistration, re-inked lines).  medieval = parchment illustration
    (symbol herds, ribbon title, no contours/legend).  biome = categorical
    Whittaker biome sheet (flat class fills, palette single source,
    class legend + graticule).  Needs the 'media' extra (OpenEXR + matplotlib).
    """
    if style not in ("survey", "hand", "medieval", "biome"):
        console.print(f"[red]Unknown style '{style}' — use survey | hand | medieval | biome[/red]")
        raise typer.Exit(code=2) from None
    build_dir = gaea or (pack / "gaea-out")
    if not (pack / "input" / "meta.json").exists():
        console.print(f"[red]No input/meta.json in {pack} — is this a pack root?[/red]")
        raise typer.Exit(code=2) from None

    out_dir = output or (pack / "carto")
    if style == "biome":
        # Biome sheet needs no build: without --gaea it falls back to the
        # best available terrain source (refined-out → gaea-out → input/).
        from dreamulator.media.biome_render import biome_region

        console.print(f"Rendering [biome] sheet {pack} → {out_dir}")
        info = biome_region(
            pack,
            out_dir,
            gaea_dir=gaea,
            res=res,
            dpi=dpi,
            data_dir=data_dir,
            title=title,
        )
        for ext in ("svg", "png"):
            p = out_dir / f"biome.{ext}"
            console.print(f"  [green]biome.{ext}[/green] → {p} ({p.stat().st_size / 1024:.0f} KB)")
        console.print(f"  classes: {info['classes']}")
        return

    if not build_dir.is_dir():
        console.print(f"[red]Build dir not found: {build_dir}[/red]")
        raise typer.Exit(code=2) from None

    console.print(f"Rendering [{style}] sheet {pack} ({build_dir.name}) → {out_dir}")
    if style == "medieval":
        from dreamulator.media.medieval_render import medieval_region

        info = medieval_region(pack, out_dir, res=res, dpi=dpi, title=title, gaea_dir=gaea)
        p = out_dir / "medieval.png"
        console.print(f"  [green]medieval.png[/green] → {p} ({p.stat().st_size / 1024:.0f} KB)")
        console.print(
            f"  symbols: {info['mountains']} mountains, {info['trees']} trees, "
            f"{info['rivers']} river lines"
        )
        return

    from dreamulator.media.carto_render import carto_region

    info = carto_region(
        pack,
        out_dir,
        res=res,
        dpi=dpi,
        data_dir=data_dir,
        contour_labels=contour_labels,
        contours=contours,
        hand=(style == "hand"),
        title=title,
        gaea_dir=gaea,
    )
    for ext in ("hand.png",) if style == "hand" else ("svg", "png"):
        p = out_dir / f"topo.{ext}"
        console.print(f"  [green]topo.{ext}[/green] → {p} ({p.stat().st_size / 1024:.0f} KB)")
    console.print(f"  contours: {info['minor_levels']} minor + {info['major_levels']} index")
