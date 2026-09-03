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
from dreamulator.world_manager import WorldManager

export_app = typer.Typer(
    help="Headless map-layer export utilities (colour PNGs matching the frontend).",
    no_args_is_help=True,
)
console = Console()

_VALID_LAYERS = frozenset(
    {"terrain", "koppen", "biome", "agriculture", "habitability", "plate_motion"}
)


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
    raise ValueError(f"Unknown layer: {name}")


@export_app.command("layers")
def export_layers(
    world: str = typer.Argument(help="World name"),
    layers: str = typer.Option(
        "terrain,koppen,biome,agriculture,habitability",
        "--layers",
        "-l",
        help="Comma-separated layer names: terrain,koppen,biome,agriculture,habitability",
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
    invalid = [name for name in requested if name not in _VALID_LAYERS]
    if invalid:
        console.print(f"[red]Unknown layer(s): {', '.join(invalid)}[/red]")
        console.print(f"  Valid layers: {', '.join(sorted(_VALID_LAYERS))}")
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

    map_dir = mm._maps_dir(planet_id)
    if map_dir is None or not (map_dir / "cvt_mesh.json").exists():
        console.print(f"[red]No cvt_mesh.json found for planet '{planet_id}'.[/red]")
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

    from dreamulator.map.export import decompress_mesh_bytes

    mesh = TypeAdapter(CVTMesh).validate_json(
        decompress_mesh_bytes((map_dir / "cvt_mesh.json").read_bytes())
    )

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
        rgba = _render_layer(
            name, mesh, indices, elev_min, elev_max, sea_level, omega_by_plate, radius_km
        )
        path = output / f"{name}.png"
        save_rgba_png(rgba, path)
        elapsed = time.perf_counter() - start
        size_kb = path.stat().st_size / 1024
        table.add_row(name, str(path), f"{size_kb:.0f} KB · {elapsed:.1f}s")

    console.print(table)
