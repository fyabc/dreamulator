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
from typing import TYPE_CHECKING, TypeVar

import numpy as np
import typer
from pydantic import TypeAdapter
from rich.console import Console
from rich.table import Table

if TYPE_CHECKING:
    import numpy as np

    from dreamulator.media.atmosphere_render import AtmosphereModel
    from dreamulator.media.cloud_config import AtmosphereSettings

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
from dreamulator.map.prog_erosion import RIVER_THRESHOLD_CELLS
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
        "default: <data-dir>/<world>/packs/<world>-<lat>_<lon>_<span>km)",
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
    radius_km = read_radius_km(map_dir, world_dir)

    mesh = load_cvt_mesh_model(mesh_file)

    # Monthly climate series → the runoff channel (Manabe-bucket annual land
    # runoff, the hydrology legs' accumulation weight).  Worlds whose build
    # products lack the series export without it; hydrology then falls back
    # to the precipitation weight with a notice at refine time.
    climate_monthly: tuple[np.ndarray, np.ndarray] | None = None
    if climate:
        from dreamulator.map.export import load_climate_monthly

        try:
            climate_monthly = load_climate_monthly(map_dir)
        except FileNotFoundError:
            console.print(
                "[yellow]no climate_monthly.msgpack under "
                f"{map_dir} — runoff.mm channel not written; hydrology legs "
                "will fall back to the precipitation weight[/yellow]"
            )

    # Default pack home: inside the world's data dir next to maps/ (both are
    # gitignored build outputs — one place for all bulk world data).  The
    # basename keeps the world prefix so pack names stay unique across worlds
    # (the /packs API and deep links key on the directory name).
    from dreamulator.world_manager import _data_dir

    out_dir = output or (_data_dir() / world / "packs" / f"{world}-{lat:g}_{lon:g}_{span_km:g}km")
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
            climate_monthly=climate_monthly,
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


@export_app.command("build")
def export_build(
    pack: Path = typer.Argument(
        help="Region pack ROOT dir (with input/ subdir), e.g. "
        "data/worlds/nacrea/packs/nacrea-15_-100_550km"
    ),
    method: str = typer.Option(
        "td", "--method", help="Terrain build method: td (terrain-diffusion) | spl (programmatic)"
    ),
    td: Path | None = typer.Option(
        None,
        "--td",
        help="terrain-diffusion repo clone (with .venv) — required for --method td "
        "(not needed with --reuse-height); see terrain-chain manual",
    ),
    river_threshold: int | None = typer.Option(
        None,
        "--river-threshold",
        help="Channel onset in upstream cells (default scales with grid)",
    ),
    coast_warp: bool = typer.Option(
        False, "--coast-warp", help="Warp conditioning sea-land edges before TD inference"
    ),
    reuse_height: bool = typer.Option(
        False,
        "--reuse-height",
        help="TD method only: skip inference and re-extract hydrology from the cached refined DEM",
    ),
    steps: int = typer.Option(30, "--steps", help="SPL method: time steps"),
    dt_yr: float = typer.Option(5e4, "--dt", help="SPL method: step length (years)"),
    k_spl: float = typer.Option(2e-7, "--k", help="SPL method: stream-power erodibility K"),
) -> None:
    """Build the high-resolution terrain of a region pack.

    --method td  : terrain-diffusion refinement + hydrology -> <pack>/refined-out/
    --method spl : programmatic SPL erosion -> <pack>/prog-out/ (same legend as gaea-out)
    """
    if not (pack / "input" / "meta.json").exists():
        console.print(f"[red]No input/meta.json in {pack} — is this a pack root?[/red]")
        raise typer.Exit(code=2) from None
    if method == "td":
        from dreamulator.media.terrain_refine import refine_region_pack

        if td is None and not reuse_height:
            console.print(
                "[red]--td is required for --method td (or pass --reuse-height "
                "to re-extract from the cached refined DEM)[/red]"
            )
            raise typer.Exit(code=2) from None
        console.print(
            f"Refining {pack} via terrain-diffusion ({td.name if td else 'cached height'})"
        )
        td_info = refine_region_pack(
            pack,
            td,
            river_threshold=river_threshold,
            coast_warp=coast_warp,
            reuse_height=reuse_height,
        )
        console.print(
            f"  refined-out/: res {td_info['res']}² · lakes {td_info['lakes_pct']}% of land · "
            f"{td_info['river_segments']} river segments"
        )
        return
    if method == "spl":
        from typing import cast

        from dreamulator.map.prog_erosion import erode_region_pack

        threshold = river_threshold if river_threshold is not None else RIVER_THRESHOLD_CELLS
        console.print(f"Eroding {pack} (steps={steps}, dt={dt_yr:.0e} yr, K={k_spl:.0e})")
        info: dict[str, object] = erode_region_pack(
            pack, steps=steps, dt_yr=dt_yr, k_spl=k_spl, river_threshold=threshold
        )
        rng = cast("list[float]", info["height_range_m"])
        console.print(
            f"  prog-out/: rivers {info['river_pct_of_land']}% of land · "
            f"height [{rng[0]:.0f}, {rng[1]:.0f}] m"
        )
        return
    console.print(f"[red]Unknown method '{method}' — use td | spl[/red]")
    raise typer.Exit(code=2) from None


@export_app.command("render")
def export_render(
    pack: Path = typer.Argument(
        help="Region pack ROOT dir (with input/ subdir), e.g. "
        "data/worlds/nacrea/packs/nacrea-15_-100_550km"
    ),
    style: str = typer.Option(
        "satellite",
        "--style",
        help="satellite | survey | hand | medieval | biome | relief | all "
        "(all = the three user-facing HD sheets: survey topo + relief + biome)",
    ),
    gaea: Path | None = typer.Option(
        None, "--gaea", "-g", help="Build dir (default: <pack>/gaea-out; also refined-out/prog-out)"
    ),
    output: Path | None = typer.Option(
        None, "--output", "-o", help="Output dir (default: <pack>/color or <pack>/carto)"
    ),
    texture: bool = typer.Option(
        True,
        "--texture/--no-texture",
        help="satellite only: per-biome vegetation/surface grain",
    ),
    title: str | None = typer.Option(None, "--title", help="Sheet title override (sheets)"),
    res: int = typer.Option(2048, "--res", help="Sheet grid resolution"),
    dpi: int = typer.Option(300, "--dpi", help="PNG output DPI"),
    data_dir: Path | None = typer.Option(
        None, "--data-dir", help="Worlds data dir (catalog body name in sheet titles)"
    ),
    contour_labels: bool = typer.Option(
        False, "--contour-labels", help="Inline elevation labels on index contours"
    ),
    contours: bool = typer.Option(
        False, "--contours/--no-contours", help="Draw contour lines (sheets)"
    ),
    biome_legend: bool = typer.Option(
        False, "--biome-legend/--no-biome-legend", help="relief only: append biome swatches"
    ),
    svg: bool = typer.Option(False, "--svg/--no-svg", help="Also write the vector SVG sheet"),
) -> None:
    """Render a region pack: satellite true colour or a cartographic sheet."""
    if style == "all":
        for each in ("survey", "relief", "biome"):
            export_render(
                pack=pack,
                style=each,
                gaea=gaea,
                output=output,
                texture=texture,
                title=title,
                res=res,
                dpi=dpi,
                data_dir=data_dir,
                contour_labels=contour_labels,
                contours=contours,
                biome_legend=biome_legend,
                svg=svg,
            )
        return
    if not (pack / "input" / "meta.json").exists():
        console.print(f"[red]No input/meta.json in {pack} — is this a pack root?[/red]")
        raise typer.Exit(code=2) from None
    build_dir = gaea or (pack / "gaea-out")
    if style == "satellite":
        from dreamulator.media.satellite_color import colorize_region

        if not build_dir.is_dir():
            console.print(f"[red]Build dir not found: {build_dir}[/red]")
            raise typer.Exit(code=2) from None
        out_dir = output or (pack / "color")
        console.print(f"Colorizing {pack}/input + {build_dir} → {out_dir}")
        try:
            paths = colorize_region(pack, build_dir, out_dir, texture=texture)
        except RuntimeError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(code=1) from None
        for name, path in paths.items():
            console.print(f"  [green]{name}[/green] → {path} ({path.stat().st_size / 1024:.0f} KB)")
        return
    if style in ("survey", "hand", "medieval", "biome", "relief"):
        from dreamulator.media.biome_render import biome_region
        from dreamulator.media.carto_render import carto_region
        from dreamulator.media.medieval_render import medieval_region
        from dreamulator.media.relief_render import relief_region

        out_dir = output or (pack / "carto")
        if style in ("biome", "relief"):
            fn = biome_region if style == "biome" else relief_region
            info = fn(
                pack,
                out_dir,
                gaea_dir=gaea,
                res=res,
                dpi=dpi,
                data_dir=data_dir,
                title=title,
                svg=svg,
            )
            name = f"{style}.png"
            path = out_dir / name
            console.print(f"  [green]{name}[/green] → {path} ({path.stat().st_size / 1024:.0f} KB)")
            console.print(f"  classes: {info['classes']}")
            return
        if not build_dir.is_dir():
            console.print(f"[red]Build dir not found: {build_dir}[/red]")
            raise typer.Exit(code=2) from None
        console.print(f'Rendering "{style}" sheet {pack} ({build_dir.name}) → {out_dir}')
        if style == "medieval":
            medieval_region(pack, out_dir, res=res, dpi=dpi, title=title, gaea_dir=gaea)
        else:
            carto_region(
                pack,
                out_dir,
                gaea_dir=gaea,
                res=res,
                dpi=dpi,
                data_dir=data_dir,
                contour_labels=contour_labels,
                contours=contours,
                hand=style == "hand",
                svg=svg,
                title=title,
            )
        exts = ("hand.png",) if style == "hand" else ("png", "svg") if svg else ("png",)
        for ext in exts:
            path = out_dir / f"topo.{ext}"
            console.print(
                f"  [green]topo.{ext}[/green] → {path} ({path.stat().st_size / 1024:.0f} KB)"
            )
        return
    console.print(
        f"[red]Unknown style '{style}' — use satellite | survey | hand | medieval | "
        "biome | relief | all[/red]"
    )
    raise typer.Exit(code=2) from None


def _host_star_temperature(
    stellar: dict[str, object], planet: dict[str, object] | None
) -> float | None:
    """Walk planet → host planet → star and return the star's effective temperature."""
    stars = stellar.get("stars")
    orbits = stellar.get("orbits")
    star_entries = stars if isinstance(stars, list) else []
    orbit_entries = orbits if isinstance(orbits, list) else []
    by_body = {
        str(entry.get("body_id")): entry for entry in orbit_entries if isinstance(entry, dict)
    }
    node = str(planet.get("orbits")) if planet and planet.get("orbits") else None
    seen: set[str] = set()
    while node is not None and node in by_body and node not in seen:
        seen.add(node)
        parent = by_body[node].get("parent_id")
        node = str(parent) if parent else None
    star = next(
        (entry for entry in star_entries if isinstance(entry, dict) and entry.get("id") == node),
        None,
    )
    if star is None and star_entries and isinstance(star_entries[0], dict):
        star = star_entries[0]
    if star is None:
        return None
    temperature = star.get("temperature")
    return float(temperature) if isinstance(temperature, (int, float)) else None


def _atmosphere_from_world(
    world_dir: Path,
    branch: str | None,
    planet_id: str,
    radius_km: float,
    cfg: AtmosphereSettings,
) -> AtmosphereModel:
    """Build the L5 atmosphere model from the world's stellar and planet inputs.

    Missing inputs fall back to Earth values; the star temperature and surface
    pressure can be overridden in the YAML block (QA and worlds without inputs).
    """
    from dreamulator.media.atmosphere_render import (
        EARTH_GRAVITY,
        AtmosphereModel,
        mean_molar_mass_kg_mol,
    )
    from dreamulator.resolver import LayerResolver

    resolver = LayerResolver(world_dir, branch)
    planets_data = resolver.load_layer_yaml("geological", "planets.yaml")
    stellar_data = resolver.load_layer_yaml("astronomy", "stellar.yaml")

    planet: dict[str, object] | None = None
    if isinstance(planets_data, dict):
        entries = planets_data.get("planets")
        candidates = entries if isinstance(entries, list) else []
        planet = next(
            (
                entry
                for entry in candidates
                if isinstance(entry, dict) and entry.get("id") == planet_id
            ),
            None,
        )
        if planet is None and candidates and isinstance(candidates[0], dict):
            planet = candidates[0]

    star_temperature = cfg.star_temperature_k
    if star_temperature is None and isinstance(stellar_data, dict):
        star_temperature = _host_star_temperature(stellar_data, planet)
    if star_temperature is None:
        star_temperature = 5772.0

    atmosphere_data: dict[str, object] = {}
    composition: dict[str, float] | None = None
    mass_earth: float | None = None
    radius_earth: float | None = None
    if planet is not None:
        atmosphere = planet.get("atmosphere")
        if isinstance(atmosphere, dict):
            atmosphere_data = atmosphere
            raw_composition = atmosphere.get("composition")
            if isinstance(raw_composition, dict):
                composition = {
                    str(key): float(value)
                    for key, value in raw_composition.items()
                    if isinstance(value, (int, float))
                }
        mass = planet.get("mass")
        radius = planet.get("radius")
        mass_earth = float(mass) if isinstance(mass, (int, float)) else None
        radius_earth = float(radius) if isinstance(radius, (int, float)) else None

    surface_pressure = cfg.surface_pressure_atm
    if surface_pressure is None:
        raw_pressure = atmosphere_data.get("surface_pressure_atm")
        surface_pressure = float(raw_pressure) if isinstance(raw_pressure, (int, float)) else 1.0

    gravity = EARTH_GRAVITY
    if mass_earth is not None and radius_earth is not None and radius_earth > 0.0:
        gravity = mass_earth / (radius_earth * radius_earth) * EARTH_GRAVITY

    ground_albedo = 0.3
    if planet is not None:
        raw_albedo = planet.get("albedo")
        if isinstance(raw_albedo, (int, float)):
            ground_albedo = float(raw_albedo)

    return AtmosphereModel(
        planet_radius_km=radius_km,
        gravity_m_s2=gravity,
        surface_pressure_atm=surface_pressure,
        atmosphere_temperature_k=cfg.atmosphere_temperature_k,
        mean_molar_mass_kg_mol=mean_molar_mass_kg_mol(composition),
        star_temperature_k=star_temperature,
        mie_scale=cfg.mie_scale,
        ozone_scale=cfg.ozone_scale,
        ground_albedo=ground_albedo,
    )


@export_app.command("clouds")
def export_clouds(
    ctx: typer.Context,
    world: str = typer.Argument(help="World name"),
    planet: str | None = typer.Option(None, "--planet", "-p", help="Planet ID"),
    branch: str | None = typer.Option(None, "--branch", "-b", help="Branch name"),
    config: Path | None = typer.Option(
        None,
        "--config",
        help="YAML settings file (see cli.md); explicit CLI flags override it",
    ),
    grid: str = typer.Option(
        "8192x4096",
        "--grid",
        "-g",
        help="Equirect cloud texture resolution WxH (16K×8K = 4K full-disk per the spec)",
    ),
    seed: int = typer.Option(7, "--seed", help="Noise seed (same fields + seed = same image)"),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Output dir (default: <export-dir>/clouds/<world>[-<branch>]/; "
        "export-dir = $DREAMULATOR_EXPORT_DIR or ./exports)",
    ),
    globe_res: int = typer.Option(1600, "--globe-res", help="Globe preview resolution"),
    center_lon: float = typer.Option(90.0, "--center-lon", help="Globe view centre longitude"),
    center_lat: float = typer.Option(15.0, "--center-lat", help="Globe view centre latitude"),
    sun_lon: float | None = typer.Option(
        None, "--sun-lon", help="Sub-solar longitude (default: centre − 25°)"
    ),
    sun_lat: float = typer.Option(20.0, "--sun-lat", help="Sub-solar latitude"),
    cover_scale: float = typer.Option(
        1.0,
        "--cover-scale",
        help="Multiplier on the conditioning cover field; 0 skips texture "
        "synthesis entirely (surface/biome QA: surface.png + cloud-free globe)",
    ),
    cyclones: bool = typer.Option(
        False,
        "--cyclones",
        help="Overlay L3 synthetic cyclone templates (placeholder until the L1 track table lands)",
    ),
    cyclone_seed: int = typer.Option(31, "--cyclone-seed", help="Synthetic cyclone track seed"),
    atmosphere: bool = typer.Option(
        True,
        "--atmosphere/--no-atmosphere",
        help="L5 physical atmosphere shell (Rayleigh/Mie/ozone, star spectrum); "
        "disable for the legacy limb-glow preview",
    ),
    data_dir: Path | None = typer.Option(None, "--data-dir", help="Worlds data directory"),
) -> None:
    """L2 procedural cloud texture prototype: clouds.png + cover + globe preview.

    The large-scale cover field is a placeholder (precipitation + SLP-anomaly
    proxy) until the GCM layer pack lands; the noise/warp/streak machinery is
    the permanent part.  ``--cyclones`` adds L3 parametric templates from a
    synthetic track set, for visual QA before real tracks exist.  Needs the
    'media' extra (numba noise kernel).
    """
    _set_data_dir(data_dir)

    # Precedence: explicit CLI flag > YAML config > built-in default.
    from dreamulator.media.cloud_config import CloudRenderConfig

    cfg = CloudRenderConfig.from_yaml(config) if config is not None else CloudRenderConfig()
    T = TypeVar("T")

    def _pick(name: str, cli_value: T, cfg_value: T) -> T:
        source = ctx.get_parameter_source(name)
        if source is not None and source.name == "COMMANDLINE":
            return cli_value
        return cfg_value

    grid = _pick("grid", grid, cfg.grid)
    seed = _pick("seed", seed, cfg.seed)
    globe_res = _pick("globe_res", globe_res, cfg.globe_res)
    center_lon = _pick("center_lon", center_lon, cfg.center_lon)
    center_lat = _pick("center_lat", center_lat, cfg.center_lat)
    sun_lon = _pick("sun_lon", sun_lon, cfg.sun_lon)
    sun_lat = _pick("sun_lat", sun_lat, cfg.sun_lat)
    cover_scale = _pick("cover_scale", cover_scale, cfg.cover_scale)
    cyclones = _pick("cyclones", cyclones, cfg.cyclones.enabled)
    cyclone_seed = _pick("cyclone_seed", cyclone_seed, cfg.cyclones.seed)
    atmosphere = _pick("atmosphere", atmosphere, cfg.atmosphere.enabled)

    try:
        w_str, h_str = grid.lower().split("x")
        width, height = int(w_str), int(h_str)
    except ValueError:
        console.print(f"[red]Invalid --grid '{grid}' (expected WxH, e.g. 8192x4096)[/red]")
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

    from dreamulator.map.export import find_mesh_file, load_cvt_mesh_model

    map_dir = mm._maps_dir(planet_id)
    mesh_file = find_mesh_file(map_dir) if map_dir is not None else None
    if map_dir is None or mesh_file is None:
        console.print(f"[red]No mesh file found for planet '{planet_id}'.[/red]")
        raise typer.Exit(code=1) from None
    mesh = load_cvt_mesh_model(mesh_file)

    meta = mm.get_map_metadata(planet_id)
    sea_level = meta.sea_level_m if meta else 0.0
    radius_km = read_radius_km(map_dir, world_dir)

    import os

    export_root = Path(os.environ.get("DREAMULATOR_EXPORT_DIR", "exports"))
    out_dir = output or (export_root / "clouds" / (world + (f"-{branch}" if branch else "")))
    console.print(
        f"Synthesising cloud texture for {world}/{planet_id} "
        f"({width}×{height}, branch={branch or 'root'}, seed={seed})…"
    )
    start = time.perf_counter()

    from dreamulator.media.cloud_render import clouds_globe
    from dreamulator.media.cyclone_render import Cyclone, synthetic_cyclones

    if cfg.cyclones.tracks:
        cyclone_set: list[Cyclone] | None = [
            Cyclone(**track.model_dump()) for track in cfg.cyclones.tracks
        ]
    elif cyclones:
        cyclone_set = synthetic_cyclones(
            cyclone_seed,
            tropical_per_hemisphere=cfg.cyclones.tropical_per_hemisphere,
            extratropical_per_hemisphere=cfg.cyclones.extratropical_per_hemisphere,
            tropical_scale=cfg.cyclones.tropical_scale,
            extratropical_scale=cfg.cyclones.extratropical_scale,
        )
    else:
        cyclone_set = None

    atmosphere_model = (
        _atmosphere_from_world(world_dir, branch, planet_id, radius_km, cfg.atmosphere)
        if atmosphere
        else None
    )
    if atmosphere_model is not None:
        console.print(
            f"  atmosphere: star {atmosphere_model.star_temperature_k:.0f} K, "
            f"p {atmosphere_model.surface_pressure_atm:g} atm, "
            f"H {atmosphere_model.scale_height_km:.1f} km, "
            f"{cfg.atmosphere.exposure}"
        )
    paths = clouds_globe(
        mesh,
        out_dir,
        radius_km=radius_km,
        sea_level_m=sea_level,
        width=width,
        height=height,
        seed=seed,
        globe_res=globe_res,
        center_lon_deg=center_lon,
        center_lat_deg=center_lat,
        sun_lon_deg=sun_lon,
        sun_lat_deg=sun_lat,
        cover_scale=cover_scale,
        cyclones=cyclone_set,
        cyclone_seed=cyclone_seed,
        atmosphere=atmosphere_model,
        cloud_altitude_km=cfg.atmosphere.cloud_altitude_km,
        cloud_shadows=cfg.atmosphere.cloud_shadows,
        sun_glint=cfg.atmosphere.sun_glint,
        water_roughness=cfg.atmosphere.water_roughness,
        multiple_scattering=cfg.atmosphere.multiple_scattering,
        atmosphere_exposure=cfg.atmosphere.exposure,
        provenance={
            "world": world,
            "branch": branch or "root",
            "planet": planet_id,
            "mesh": str(mesh_file),
        },
    )
    elapsed = time.perf_counter() - start
    for name, path in paths.items():
        console.print(f"  [green]{name}[/green] → {path} ({path.stat().st_size / 1024:.0f} KB)")
    console.print(f"  done in {elapsed:.1f}s")


@export_app.command("canvas")
def export_canvas(
    canvas: Path = typer.Argument(help="S1 canvas directory (canvas.json + chunks/ + climate/)"),
    lat: float | None = typer.Option(None, "--lat", help="Window centre latitude (degrees)"),
    lon: float | None = typer.Option(None, "--lon", help="Window centre longitude (degrees)"),
    span_km: float = typer.Option(550.0, "--span-km", help="Square window side (km)"),
    out_res: int = typer.Option(2048, "--out-res", help="Window raster resolution (square N×N)"),
    stage: str = typer.Option(
        "all", "--stage", help="all | hydrology | window (all = hydrology then window)"
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Output pack dir (default: <canvas>/windows/<canvas>-<lat>_<lon>_<span>km)",
    ),
    resume: bool = typer.Option(
        True, "--resume/--no-resume", help="Resume from checksummed work files"
    ),
    force: bool = typer.Option(
        False, "--force", help="Re-run hydrology even when finished work files exist"
    ),
    threshold_cells: int = typer.Option(
        27000,
        "--threshold-cells",
        help="Channel onset in runoff-weighted cells (27000 ≈ 2.1 m³/s mean "
        "discharge at 90 m — the region chain's calibrated onset; lower values "
        "give a denser network)",
    ),
) -> None:
    """Canvas chain: out-of-core hydrology, then crop a region window.

    One command for the user-facing action (a window pack ready for
    `export render`); `--stage hydrology` exposes the intermediate result.
    """
    if stage not in ("all", "hydrology", "window"):
        console.print(f"[red]Unknown stage '{stage}' — use all | hydrology | window[/red]")
        raise typer.Exit(code=2) from None
    if not (canvas / "canvas.json").is_file():
        console.print(f"[red]No canvas.json in {canvas} — is this a canvas dir?[/red]")
        raise typer.Exit(code=2) from None

    if stage in ("all", "hydrology"):
        from dreamulator.media.canvas_pipeline import (
            CanvasStore,
            run_canvas_fill,
            run_canvas_rivers,
        )

        store = CanvasStore.load(canvas)
        finals = list((store.work / "final").glob("r*_c*.npy"))
        if force or len(finals) < len(store.chunks):
            console.print(f"Running hydrology on {canvas.name} ({len(store.chunks)} chunks)")
            stats = run_canvas_fill(store, resume=resume)
            console.print(
                f"  {int(stats['watersheds'])} watersheds · {stats['stages_seconds']:.1f} s"
            )
        else:
            console.print(f"Hydrology already complete under {store.work}")
        if force or not (canvas / "hydro" / "rivers.line.npy").exists():
            run_canvas_rivers(store, threshold_cells=threshold_cells)

    if stage == "hydrology":
        return

    if lat is None or lon is None:
        if stage == "window":
            console.print("[red]--lat and --lon are required for --stage window[/red]")
            raise typer.Exit(code=2) from None
        console.print("[yellow]No --lat/--lon given: hydrology only (window skipped)[/yellow]")
        return

    from typing import cast

    from dreamulator.media.canvas_window import CanvasSource, crop_canvas_window

    out_dir = output or (canvas / "windows" / f"{canvas.name}-{lat:g}_{lon:g}_{span_km:g}km")
    source = CanvasSource.load(canvas)
    meta = crop_canvas_window(
        source,
        center_lat=lat,
        center_lon=lon,
        span_km=span_km,
        out_res=out_res,
        out_dir=out_dir,
    )
    grid = cast("dict[str, int]", meta["grid"])
    elev = cast("dict[str, float]", meta["elevation_m"])
    ocean = float(cast("float", meta["ocean_fraction"]))
    console.print(
        f"Cropped {canvas.name} → {out_dir} · grid {grid['w']}×{grid['h']}"
        f" · elev {elev['min']:.0f}…{elev['max']:.0f} m · ocean {ocean * 100:.1f}%"
    )
