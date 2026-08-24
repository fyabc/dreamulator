"""Seed explorer CLI — batch-generate terrain for multiple seeds and catalog them.

Addresses roadmap §八 #16 (Cortial-2019 seed sensitivity): different seeds are
genuinely different planets, so a seed explorer + catalog is the toolchain to
pick a seed before committing it to a world.

Usage:
    dreamulator explore-seeds nacrea --seeds 42,123,456
    dreamulator explore-seeds nacrea --count 10 --nodes 50000 --raw

The heavy imports are deferred to keep `dreamulator --help` fast; the command
is registered on the root app in `cli.py` via `app.command(...)`.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import typer
from rich.console import Console
from rich.table import Table

from dreamulator.seed_explorer import compute_seed_stats, render_seed_thumbnail

console = Console()

_STAGES = ["mesh", "plates", "tectonics", "boundaries", "terrain"]


def _set_data_dir(data_dir: Path | None) -> None:
    import os

    if data_dir is not None:
        os.environ["DREAMULATOR_DATA_DIR"] = str(data_dir.resolve())


def _resolve_seeds(seeds: str | None, count: int) -> list[int]:
    """Explicit ``--seeds`` list, else ``count`` reproducible random seeds."""
    if seeds is not None:
        return [int(s.strip()) for s in seeds.split(",") if s.strip()]
    rng = np.random.default_rng(0)  # fixed so repeated runs are reproducible
    return [int(x) for x in rng.integers(0, 2**31 - 1, size=count)]


def explore_seeds(
    world: str = typer.Argument(help="World name"),
    seeds: str | None = typer.Option(
        None, "--seeds", "-s", help="Comma-separated seeds (e.g. 42,123,456)"
    ),
    count: int = typer.Option(
        5, "--count", "-n", help="Number of random seeds (ignored if --seeds given)"
    ),
    nodes: int = typer.Option(50_000, "--nodes", help="Resolution (num_nodes)"),
    raw: bool = typer.Option(False, "--raw", help="Skip geography anchoring (pure seed)"),
    width: int = typer.Option(512, "--width", help="Thumbnail width in pixels"),
    output: Path | None = typer.Option(
        None, "--output", "-o", help="Catalog dir (default <world>/seed_catalog/)"
    ),
    data_dir: Path | None = typer.Option(None, "--data-dir", help="Worlds data directory"),
) -> None:
    """Generate terrain for multiple seeds; compare stats + write a catalog."""
    from dreamulator.world_manager import WorldManager

    _set_data_dir(data_dir)

    mgr = WorldManager()
    try:
        world_dir = mgr.world_dir(world)
    except FileNotFoundError:
        console.print(f"[red]World '{world}' not found[/red]")
        raise typer.Exit(code=1) from None

    # Lazy import: avoids a cli.py ↔ cli_explore_seeds.py circular import.
    from dreamulator.cli import _load_geography_raster, _load_terrain_config  # noqa: PLC0415

    cfg, _, _ = _load_terrain_config(world_dir, None, None, None)
    cfg.num_nodes = nodes
    cfg.seed = 0  # overwritten per seed below

    geography_raster = None if raw else _load_geography_raster(world_dir, None)

    seed_list = _resolve_seeds(seeds, count)
    if not seed_list:
        console.print("[red]No seeds to explore.[/red]")
        raise typer.Exit(code=2) from None

    output_dir = output or (world_dir / "seed_catalog")
    thumb_dir = output_dir / "thumbnails"
    thumb_dir.mkdir(parents=True, exist_ok=True)

    from dreamulator.map.export import save_rgba_png
    from dreamulator.map.terrain_pipeline import run_terrain_pipeline

    sea_level = float(getattr(cfg, "sea_level_offset_m", 0.0))
    entries: list[dict[str, Any]] = []
    console.print(
        f"Exploring {len(seed_list)} seed(s) for '{world}' "
        f"({nodes:,} nodes, geography {'off' if raw else 'on'})…"
    )

    for seed in seed_list:
        start = time.perf_counter()
        cfg.seed = seed
        result = run_terrain_pipeline(
            cfg,
            output_dir=None,
            stages=_STAGES,
            geography_raster=geography_raster,
        )
        if result.mesh is None:
            console.print(f"[yellow]  seed {seed}: generation produced no mesh — skipped[/yellow]")
            continue

        stats = compute_seed_stats(result.mesh, sea_level=sea_level)
        thumb = render_seed_thumbnail(result.mesh, width, width // 2, sea_level=sea_level)
        save_rgba_png(thumb, thumb_dir / f"{seed}.png")
        entries.append({"seed": seed, "thumbnail": f"thumbnails/{seed}.png", **stats})
        console.print(f"  seed {seed}: {time.perf_counter() - start:.1f}s")

    catalog = {"world": world, "num_nodes": nodes, "seeds": entries}
    catalog_path = output_dir / "seed-catalog.json"
    with catalog_path.open("w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False)

    _print_table(catalog_path, entries)
    console.print(f"[green]Catalog written to {catalog_path}[/green]")


def _print_table(catalog_path: Path, entries: list[dict[str, Any]]) -> None:
    table = Table(title=f"Seed exploration — {catalog_path.parent.name}")
    table.add_column("Seed", style="cyan")
    for col in ("Ocean%", "Land%", "MeanLand", "MaxElev", "MaxDepth", "Cont.", "Plates"):
        table.add_column(col, justify="right")
    for e in entries:
        table.add_row(
            str(e["seed"]),
            f"{e['ocean_fraction'] * 100:.1f}",
            f"{e['land_fraction'] * 100:.1f}",
            _fmt_m(e["mean_land_elevation_m"]),
            _fmt_m(e["max_elevation_m"]),
            _fmt_m(e["max_ocean_depth_m"]),
            str(e["num_continents"]),
            str(e["num_plates"]),
        )
    console.print(table)


def _fmt_m(value: object) -> str:
    return f"{value:.0f}m" if isinstance(value, (int, float)) else "—"
