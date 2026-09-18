"""``data`` command group — versioned development data packages (M1-P1).

``data fetch`` resolves a world/branch's effective terrain-import recipe, finds
the matching published package in the git-committed index, verifies it and
atomically installs the base terrain.  This is the one-command entry point for
new machines that lack the gitignored, imported base terrain.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import typer
import yaml
from rich.console import Console

if TYPE_CHECKING:
    from dreamulator.map.pipeline_types import TerrainPipelineConfig

from dreamulator.datapkg import (
    DevDataIndex,
    InstallError,
    default_index_path,
    recipe_fingerprint,
)
from dreamulator.datapkg.install import install_files, verify_package

data_app = typer.Typer(
    help="Versioned development data packages: download and install base terrain.",
    no_args_is_help=True,
)
console = Console()


def _set_data_dir(data_dir: Path | None) -> None:
    if data_dir is not None:
        os.environ["DREAMULATOR_DATA_DIR"] = str(data_dir.resolve())


def _detect_planet_id(resolver: object) -> str:
    """First planet id from planets.yaml (matches the climate engine's ``planets[0]``)."""
    geo_dir = resolver.get_input_dir("geological")  # type: ignore[attr-defined]
    if geo_dir is not None:
        pf = geo_dir / "planets.yaml"
        if pf.exists():
            data = yaml.safe_load(pf.read_text(encoding="utf-8")) or {}
            planets = data.get("planets", []) if isinstance(data, dict) else []
            if planets:
                return str(planets[0].get("id", "planet_earth"))
    return "planet_earth"


def _resolve_terrain(world_dir: Path, branch: str | None) -> tuple[TerrainPipelineConfig, str]:
    """Return (config, planet_id) for the effective terrain config."""
    from dreamulator.map.pipeline_types import TerrainPipelineConfig
    from dreamulator.resolver import LayerResolver

    resolver = LayerResolver(world_dir, branch)
    cfg = TerrainPipelineConfig()
    tcfg = resolver.find_input_file("geological", "terrain_config.yaml")
    if tcfg is not None:
        cfg = TerrainPipelineConfig.from_yaml(tcfg)
    return cfg, _detect_planet_id(resolver)


def _install_target(world_dir: Path, planet_id: str) -> Path:
    # The base terrain is root-scoped (the branch inherits it); the branch build
    # materializes a writable copy via _materialize_writable_mesh.
    return world_dir / "maps" / planet_id


def _import_recovery_commands(world_dir: Path, planet_id: str) -> str:
    out = world_dir / "maps" / planet_id
    return (
        f"  uv run python scripts/earth/import_earth_elevation.py "
        f"--output-dir {out} --resolution 4096x2048 --mesh-nodes 200000 --seed 42 --skip-download\n"
        f"  uv run python scripts/earth/import_earth_tectonics.py --output-dir {out}\n"
        f"  uv run python scripts/earth/import_earth_watermask.py --output-dir {out}"
    )


@data_app.command("fetch")
def fetch(
    world: str = typer.Argument(help="World name"),
    branch: str | None = typer.Option(None, "--branch", "-b", help="Branch to fetch terrain for"),
    data_dir: Path | None = typer.Option(None, "--data-dir", help="Worlds data directory"),
    from_path: Path | None = typer.Option(
        None, "--from", help="Install from a local package tarball (no download)"
    ),
) -> None:
    """Download and install the base terrain for a world/branch."""
    _set_data_dir(data_dir)

    from dreamulator.world_manager import WorldManager

    try:
        world_dir = WorldManager().world_dir(world)
    except FileNotFoundError:
        console.print(f"[red]World '{world}' not found[/red]")
        raise typer.Exit(code=1) from None

    cfg, planet_id = _resolve_terrain(world_dir, branch)
    recipe = cfg.terrain_import

    if cfg.elevation_source != "imported" or recipe is None:
        console.print(
            f"[yellow]'{world}' generates terrain procedurally "
            "(no terrain_import recipe); nothing to fetch.[/yellow]"
        )
        raise typer.Exit(code=1)

    fingerprint = recipe_fingerprint(recipe)
    index = DevDataIndex.load(default_index_path())
    entry = index.find(world=world, planet_id=planet_id, input_fingerprint=fingerprint)

    target = _install_target(world_dir, planet_id)
    console.print(f"[dim]world:[/dim] {world}  [dim]planet:[/dim] {planet_id}")
    console.print(
        f"[dim]recipe:[/dim] {recipe.resolution} / {recipe.mesh_nodes} nodes / seed {recipe.seed}"
    )
    console.print(f"[dim]fingerprint:[/dim] {fingerprint[:16]}…")
    console.print(f"[dim]target:[/dim] {target}")

    if entry is None:
        console.print("[red]No matching development data package in the index.[/red]")
        console.print(
            "Restore the base terrain with the real-data importers instead:\n"
            + _import_recovery_commands(world_dir, planet_id)
        )
        raise typer.Exit(code=1)

    already = (target / "cvt_mesh.json").exists()
    console.print(
        f"[dim]package:[/dim] {entry.asset_name} ({entry.size_bytes / (1024 * 1024):.1f} MB) "
        f"[dim]cached:[/dim] {'yes' if already else 'no'}"
    )

    with tempfile.TemporaryDirectory(prefix="dreamulator-datapkg-") as tmp:
        tmpdir = Path(tmp)
        if from_path is not None:
            tarball = from_path.resolve()
            if not tarball.exists():
                console.print(f"[red]Local package not found: {tarball}[/red]")
                raise typer.Exit(code=1)
        else:
            tarball = tmpdir / entry.asset_name
            console.print(f"[dim]downloading {entry.asset_name} …[/dim]")
            try:
                subprocess.run(
                    [
                        "gh",
                        "release",
                        "download",
                        entry.tag,
                        "--pattern",
                        entry.asset_name,
                        "--dir",
                        str(tmpdir),
                        "--clobber",
                    ],
                    check=True,
                )
            except subprocess.CalledProcessError as e:
                console.print(f"[red]Download failed: {e}[/red]")
                raise typer.Exit(code=1) from e

        extract_dir = tmpdir / "extract"
        try:
            manifest = verify_package(
                tarball,
                extract_dir,
                package_sha256=entry.package_sha256,
                fingerprint=fingerprint,
                world=world,
                planet_id=planet_id,
            )
            install_files(extract_dir, manifest, target, recipe)
        except InstallError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(code=1) from e

    console.print(
        f"[green]Installed base terrain {entry.asset_name} "
        f"({fingerprint[:12]}…) into {target}[/green]"
    )
    next_cmd = f"uv run dreamulator build {world}" + (f" --branch {branch}" if branch else "")
    console.print(f"Next: {next_cmd}")
