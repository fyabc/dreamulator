"""Climate CLI subcommand group — non-build operations for the climate layer.

Build operations (running the climate simulation) are handled by:
    dreamulator build <world> --only climate

This module provides:
    dreamulator climate validate       — validate against Earth observations
    dreamulator climate import-elevation — import real Earth elevation data
    dreamulator climate info           — show climate simulation status
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from dreamulator.world_manager import WorldManager

climate_app = typer.Typer(
    help="Climate layer tools: validation, data import, status.",
    no_args_is_help=True,
)
console = Console()


def _set_data_dir(data_dir: Path | None) -> None:
    import os

    if data_dir is not None:
        os.environ["DREAMULATOR_DATA_DIR"] = str(data_dir.resolve())


def _detect_planet_id(
    world: str,
    branch: str | None = None,
    data_dir: Path | None = None,
) -> str | None:
    """Auto-detect the first terrestrial planet ID from the world config."""
    import yaml

    base = data_dir or Path("data/worlds")
    world_dir = base / world
    if not world_dir.exists():
        return None
    wdata = yaml.safe_load((world_dir / "world.yaml").read_text(encoding="utf-8")) or {}
    pids = wdata.get("planet_ids", [])
    return pids[0] if pids else None


# ---------------------------------------------------------------------------
# climate info
# ---------------------------------------------------------------------------


@climate_app.command("info")
def climate_info(
    world: str = typer.Argument(help="World name"),
    branch: str | None = typer.Option(None, "--branch", "-b", help="Branch name"),
    planet: str = typer.Option("earth", "--planet", "-p", help="Planet ID"),
    data_dir: Path | None = typer.Option(None, "--data-dir", help="Worlds data directory"),
) -> None:
    """Show climate simulation status and summary for a world/branch."""
    _set_data_dir(data_dir)
    from dreamulator.resolver import LayerResolver

    mgr = WorldManager()
    try:
        world_dir = mgr.world_dir(world)
    except FileNotFoundError:
        console.print(f"[red]World '{world}' not found[/red]")
        raise typer.Exit(code=1) from None

    resolver = LayerResolver(world_dir, branch)
    derived_dir = resolver.get_derived_dir("climate")

    if derived_dir is None:
        console.print("[yellow]Climate layer has not been built yet.[/yellow]")
        console.print("  Run: [cyan]dreamulator build " + world + " --only climate[/cyan]")
        return

    # Look for climate outputs
    maps_dir = derived_dir / "maps" / planet
    summary_path = derived_dir / "climate_summary.yaml"

    console.print(
        f"[bold]Climate layer status[/bold] — {world}" + (f" / {branch}" if branch else "")
    )
    console.print(f"  Derived dir: {derived_dir}")

    if summary_path.exists():
        import yaml

        with summary_path.open("r", encoding="utf-8") as f:
            summary = yaml.safe_load(f) or {}

        temp = summary.get("temperature_C", {}).get("global", {})
        precip = summary.get("precipitation_mm", {}).get("global", {})
        koppen = summary.get("koppen_classes", {})

        table = Table(title="Climate Summary")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")

        if temp:
            table.add_row("Mean Temperature", f"{temp.get('mean', '?'):.1f} C")
            table.add_row(
                "Temperature Range", f"{temp.get('min', '?'):.0f} to {temp.get('max', '?'):.0f} C"
            )
        if precip:
            table.add_row("Mean Precipitation", f"{precip.get('mean', '?'):.0f} mm/yr")
            table.add_row(
                "Precipitation Range",
                f"{precip.get('min', '?'):.0f} to {precip.get('max', '?'):.0f} mm/yr",
            )
        if koppen:
            table.add_row("Koppen Classes", f"{len(koppen)} types")
            top3 = sorted(koppen.items(), key=lambda x: -x[1])[:3]
            for code, count in top3:
                table.add_row(f"  {code}", str(count))

        console.print(table)
    else:
        console.print("  [dim]No climate_summary.yaml found.[/dim]")

    # Check raster outputs
    if maps_dir.exists():
        files = list(maps_dir.iterdir())
        console.print(f"\n  Output files ({maps_dir}):")
        for rf in sorted(files):
            size = rf.stat().st_size
            if size > 1024 * 1024:
                console.print(f"    {rf.name} ({size / (1024 * 1024):.1f} MB)")
            else:
                console.print(f"    {rf.name} ({size / 1024:.0f} KB)")
    else:
        console.print(f"\n  [dim]No map outputs at {maps_dir}[/dim]")


# ---------------------------------------------------------------------------
# climate validate
# ---------------------------------------------------------------------------


@climate_app.command("validate")
def climate_validate(
    world: str = typer.Argument(help="World name"),
    branch: str | None = typer.Option(None, "--branch", "-b", help="Branch name"),
    planet: str = typer.Option("earth", "--planet", "-p", help="Planet ID"),
    spatial: bool = typer.Option(
        False, "--spatial", help="Include cell-by-cell spatial comparison"
    ),
    dataset: str = typer.Option(
        "all",
        "--dataset",
        "-d",
        help="Reference dataset to validate against: all, era5, gpcp, beck2018",
    ),
    output_dir: Path | None = typer.Option(None, "--output-dir", "-o", help="Save report JSON"),
    data_dir: Path | None = typer.Option(None, "--data-dir", help="Worlds data directory"),
) -> None:
    """Validate climate simulation against real Earth observations.

    Runs the climate engine on the world's elevation data and compares
    temperature, precipitation, and Koppen classification against
    ERA5/GPCP/Beck et al. reference data.

    Examples:
        dreamulator climate validate earth                    # all datasets
        dreamulator climate validate earth --dataset era5     # temperature only
        dreamulator climate validate earth --dataset beck2018 --spatial  # Koppen cell-by-cell
    """
    _set_data_dir(data_dir)

    # Auto-detect planet ID if not explicitly specified.
    # The default "earth" matches legacy naming; real Earth worlds use
    # "planet_earth" per planets.yaml convention.
    if planet == "earth":
        detected = _detect_planet_id(world, branch, data_dir)
        if detected is not None:
            planet = detected

    from dreamulator.validate_climate import run_validation

    report = run_validation(
        world_name=world,
        planet_id=planet,
        branch=branch,
        output_dir=output_dir,
        spatial=spatial,
        data_dir=str(data_dir) if data_dir else None,
        datasets=dataset,  # type: ignore[arg-type]
    )

    if "error" in report:
        console.print(f"[red]ERROR: {report['error']}[/red]")
        raise typer.Exit(code=1) from None

    if not report.get("overall_passed", False):
        raise typer.Exit(code=2)


# ---------------------------------------------------------------------------
# climate import-elevation
# ---------------------------------------------------------------------------


@climate_app.command("import-elevation")
def climate_import_elevation(
    world: str = typer.Argument(help="World name"),
    branch: str | None = typer.Option(None, "--branch", "-b", help="Branch name"),
    planet: str = typer.Option("earth", "--planet", "-p", help="Planet ID"),
    source: str = typer.Option("etopo1", "--source", "-s", help="Data source: etopo1"),
    resolution: str = typer.Option("2048x1024", "--resolution", "-r", help="Output WxH"),
    mesh_nodes: int = typer.Option(32768, "--mesh-nodes", "-n", help="CVT mesh node count"),
    skip_download: bool = typer.Option(False, "--skip-download", help="Use cached data"),
    skip_mesh: bool = typer.Option(False, "--skip-mesh", help="Skip CVT mesh generation"),
    seed: int = typer.Option(42, "--seed", help="RNG seed for mesh"),
    data_dir: Path | None = typer.Option(None, "--data-dir", help="Worlds data directory"),
) -> None:
    """Import real Earth elevation data (ETOPO1) into a world branch.

    Downloads ETOPO1 global DEM, resamples to equirectangular grid,
    generates a CVT mesh, and saves to the branch's geological input.
    """
    _set_data_dir(data_dir)

    mgr = WorldManager()
    try:
        world_dir = mgr.world_dir(world)
    except FileNotFoundError:
        console.print(f"[red]World '{world}' not found[/red]")
        raise typer.Exit(code=1) from None

    # Determine output directory
    if branch:
        output_dir = (
            world_dir / "branches" / branch / "layers" / "geological" / "input" / "maps" / planet
        )
    else:
        output_dir = world_dir / "layers" / "geological" / "input" / "maps" / planet

    output_dir.mkdir(parents=True, exist_ok=True)

    res_w, res_h = map(int, resolution.split("x"))

    console.print(
        f"[cyan]Importing {source} elevation for '{world}'"
        + (f" branch '{branch}'" if branch else "")
        + f"\n  Resolution: {res_w}x{res_h}  Mesh: {mesh_nodes:,} nodes  Seed: {seed}"
    )

    # Call the import logic
    import tempfile

    from dreamulator.import_earth_elevation import (
        build_cvt_mesh_from_grid,
        download_etopo1,
        extract_etopo1_to_raster,
        save_elevation_png,
        save_yaml_map,
    )

    # Download
    tmp_dir = Path(tempfile.gettempdir()) / "dreamulator_etopo1"
    tmp_dir.mkdir(exist_ok=True)
    etopo1_gz = tmp_dir / "ETOPO1_Ice_g_gmt4.grd.gz"

    if skip_download and etopo1_gz.exists():
        console.print(f"  Using cached: {etopo1_gz}")
    else:
        download_etopo1(etopo1_gz)

    # Extract and resample
    elevation, provenance = extract_etopo1_to_raster(etopo1_gz, res_w, res_h)
    elev_min = float(elevation.min())
    elev_max = float(elevation.max())

    # Save
    save_elevation_png(elevation, output_dir, elev_min, elev_max)
    save_yaml_map(output_dir, res_w, res_h, elev_min, elev_max, provenance)

    # CVT mesh
    if not skip_mesh:
        mesh = build_cvt_mesh_from_grid(elevation, mesh_nodes, seed)
        mesh_json = mesh.model_dump()
        mesh_path = output_dir / "cvt_mesh.json"
        from dreamulator.map.export import compress_mesh_bytes

        mesh_path.write_bytes(
            compress_mesh_bytes(json.dumps(mesh_json, indent=2, default=str).encode("utf-8"))
        )
        mesh_size_mb = mesh_path.stat().st_size / (1024 * 1024)
        console.print(f"  Saved CVT mesh: {mesh_path.name} ({mesh_size_mb:.1f} MB)")

    console.print(f"\n[green]Done![/green] Output: {output_dir}")
    console.print(
        f"  Next: [cyan]dreamulator build {world} --only climate --branch {branch or '...'}[/cyan]"
    )
