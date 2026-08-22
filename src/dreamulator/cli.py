"""Typer CLI entry point for dreamulator."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from dreamulator import __version__
from dreamulator.world_manager import WorldManager

if TYPE_CHECKING:
    import numpy as np

    from dreamulator.map.pipeline_types import TerrainPipelineConfig


def _set_data_dir(data_dir: Path | None) -> None:
    """Override the worlds data directory via environment variable."""
    if data_dir is not None:
        os.environ["DREAMULATOR_DATA_DIR"] = str(data_dir.resolve())


app = typer.Typer(
    name="dreamulator",
    help="Fantasy world building and simulation tool grounded in real science.",
    no_args_is_help=True,
)
console = Console()

# Branch subcommand group
branch_app = typer.Typer(help="Manage world branches.")
app.add_typer(branch_app, name="branch")

# Conlang subcommand group
conlang_app = typer.Typer(help="Conlang tools for language design and sound change simulation.")
app.add_typer(conlang_app, name="conlang")

# Terrain subcommand group
terrain_app = typer.Typer(
    help="Terrain inspection and export utilities. Use `build --only geological` to generate.",
)
app.add_typer(terrain_app, name="terrain")

# Guard (harness) subcommand group — stale detection + decision-record management
guard_app = typer.Typer(
    help="Guard (harness): stale detection and decision-record (ADR) management.",
)
app.add_typer(guard_app, name="guard")


@guard_app.command("check")
def guard_check(
    world: str = typer.Argument(help="World name"),
    branch: str | None = typer.Option(None, "--branch", "-b", help="Branch to check"),
    data_dir: Path | None = typer.Option(None, "--data-dir", help="Worlds data directory"),
) -> None:
    """Check a world/branch for stale facts (① broken refs + ② input drift)."""
    _set_data_dir(data_dir)
    from dreamulator.guard import check_broken_refs, check_decision_records

    mgr = WorldManager()
    try:
        world_dir = mgr.world_dir(world)
    except FileNotFoundError:
        console.print(f"[red]World '{world}' not found[/red]")
        raise typer.Exit(code=1) from None

    findings = [*check_broken_refs(world_dir, branch), *check_decision_records(world_dir, branch)]
    if not findings:
        console.print("[green]No stale findings — all facts up-to-date.[/green]")
        return

    table = Table(title=f"guard check: {world}" + (f" (branch {branch})" if branch else ""))
    table.add_column("kind")
    table.add_column("path")
    table.add_column("layer")
    table.add_column("detail")
    for f in findings:
        table.add_row(f.kind, f.path, f.layer or "-", f.detail)
    console.print(table)
    console.print(f"[bold]{len(findings)} finding(s)[/bold]")


def _guard_resolve_world(world: str) -> Path:
    """Resolve a world name to its directory, exiting on failure."""
    mgr = WorldManager()
    try:
        return mgr.world_dir(world)
    except FileNotFoundError:
        console.print(f"[red]World '{world}' not found[/red]")
        raise typer.Exit(code=1) from None


@guard_app.command("accept")
def guard_accept(
    world: str = typer.Argument(help="World name"),
    adr: str = typer.Argument(help="ADR id or filename, e.g. 0001 or 0001-stellar-parameters"),
    branch: str | None = typer.Option(None, "--branch", "-b", help="Branch to fingerprint"),
    limit: int = typer.Option(20, "--limit", help="Max accepted records (reject beyond)"),
    data_dir: Path | None = typer.Option(None, "--data-dir", help="Worlds data directory"),
) -> None:
    """Accept a decision record: proposed → accepted (stamps checked_against + baseline)."""
    _set_data_dir(data_dir)
    from dreamulator.guard.adr import accept

    world_dir = _guard_resolve_world(world)
    try:
        path = accept(world_dir, branch, adr, limit=limit)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1) from None
    console.print(f"[green]accepted: {path.name}[/green]")


@guard_app.command("supersede")
def guard_supersede(
    world: str = typer.Argument(help="World name"),
    adr: str = typer.Argument(help="ADR id to supersede"),
    by: str = typer.Option(..., "--by", help="Newer ADR id that supersedes it"),
    data_dir: Path | None = typer.Option(None, "--data-dir", help="Worlds data directory"),
) -> None:
    """Mark a decision record as superseded by a newer one (conclusion body untouched)."""
    _set_data_dir(data_dir)
    from dreamulator.guard.adr import supersede

    world_dir = _guard_resolve_world(world)
    try:
        path = supersede(world_dir, adr, by)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1) from None
    console.print(f"[green]superseded: {path.name} → {by}[/green]")


@guard_app.command("deprecate")
def guard_deprecate(
    world: str = typer.Argument(help="World name"),
    adr: str = typer.Argument(help="ADR id to deprecate"),
    data_dir: Path | None = typer.Option(None, "--data-dir", help="Worlds data directory"),
) -> None:
    """Deprecate a decision record whose premise no longer holds."""
    _set_data_dir(data_dir)
    from dreamulator.guard.adr import deprecate

    world_dir = _guard_resolve_world(world)
    try:
        path = deprecate(world_dir, adr)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1) from None
    console.print(f"[green]deprecated: {path.name}[/green]")


@guard_app.command("archive")
def guard_archive(
    world: str = typer.Argument(help="World name"),
    limit: int = typer.Option(20, "--limit", help="Max accepted records (archive oldest beyond)"),
    data_dir: Path | None = typer.Option(None, "--data-dir", help="Worlds data directory"),
) -> None:
    """Force-archive the oldest accepted records until count ≤ limit (harness.md §8.2)."""
    _set_data_dir(data_dir)
    from dreamulator.guard.adr import archive

    world_dir = _guard_resolve_world(world)
    archived = archive(world_dir, limit)
    if not archived:
        console.print("[green]Nothing to archive — count already within limit.[/green]")
        return
    for p in archived:
        console.print(f"[dim]  archived: {p.name}[/dim]")
    console.print(f"[green]{len(archived)} record(s) archived (→ deprecated).[/green]")


# Climate subcommand group — imported late to avoid a circular import
# (cli_climate registers commands on this module's `app`).
from datetime import UTC  # noqa: E402

from dreamulator.cli_climate import climate_app  # noqa: E402

app.add_typer(climate_app, name="climate")

# Export subcommand group — imported late to avoid a circular import
# (cli_export registers commands on this module's `app`).
from dreamulator.cli_export import export_app  # noqa: E402

app.add_typer(export_app, name="export")

# Seed explorer — top-level command, imported late to avoid a circular import
# (cli_explore_seeds imports the terrain-config loader from this module lazily).
from dreamulator.cli_explore_seeds import explore_seeds  # noqa: E402

app.command(name="explore-seeds")(explore_seeds)


@app.command()
def version() -> None:
    """Show dreamulator version."""
    console.print(f"dreamulator v{__version__}")


@app.command()
def init(
    name: str = typer.Argument(help="World name (used as directory name)"),
    seed: int | None = typer.Option(None, help="RNG seed (random if omitted)"),
    template: str = typer.Option("minimal", help="Starting template: minimal, earthlike"),
    data_dir: Path | None = typer.Option(None, "--data-dir", help="Worlds data directory"),
) -> None:
    """Create a new world with template configuration files."""
    _set_data_dir(data_dir)
    mgr = WorldManager()
    try:
        world_dir = mgr.create_world(name, seed=seed, template=template)
        console.print(f"[green]Created world '{name}' at {world_dir}[/green]")
    except FileExistsError as e:
        console.print(f"[red]Error: {e}[/red]", style="bold")
        raise typer.Exit(code=1) from None
    except FileNotFoundError as e:
        console.print(f"[red]Error: {e}[/red]", style="bold")
        raise typer.Exit(code=1) from None


@app.command(name="list")
def list_worlds(
    data_dir: Path | None = typer.Option(None, "--data-dir", help="Worlds data directory"),
) -> None:
    """List all available worlds."""
    _set_data_dir(data_dir)
    from dreamulator.branch_manager import BranchManager

    mgr = WorldManager()
    worlds = mgr.list_worlds()
    if not worlds:
        console.print("[dim]No worlds found. Create one with:[/dim] dreamulator init <name>")
        return

    table = Table(title="Worlds")
    table.add_column("Name", style="cyan")
    table.add_column("Description")
    table.add_column("Branches")
    table.add_column("Created")

    for name in worlds:
        try:
            config = mgr.load_world(name)
            branch_mgr = BranchManager(mgr.world_dir(name))
            branch_count = len(branch_mgr.list_branches())
            branch_str = str(branch_count) if branch_count > 0 else "[dim]0[/dim]"
            table.add_row(
                name,
                config.metadata.description or "[dim]-[/dim]",
                branch_str,
                config.metadata.created[:10] if config.metadata.created else "[dim]-[/dim]",
            )
        except Exception:
            table.add_row(name, "[red]load error[/red]", "[dim]-[/dim]", "[dim]-[/dim]")

    console.print(table)


@app.command()
def info(
    world: str = typer.Argument(help="World name"),
    branch: str | None = typer.Option(None, "--branch", "-b", help="Branch name"),
    data_dir: Path | None = typer.Option(None, "--data-dir", help="Worlds data directory"),
) -> None:
    """Show detailed information about a world or branch."""
    _set_data_dir(data_dir)
    from dreamulator.branch_manager import BranchManager
    from dreamulator.io.loader import load_layer_input
    from dreamulator.models.stellar import StellarSystem

    mgr = WorldManager()
    try:
        world_dir = mgr.world_dir(world)
        config = mgr.load_world(world)
    except FileNotFoundError:
        console.print(f"[red]World '{world}' not found[/red]")
        raise typer.Exit(code=1) from None

    meta = config.metadata
    console.print(f"\n[bold cyan]{meta.name}[/bold cyan]")
    if meta.description:
        console.print(f"  {meta.description}")
    console.print()

    # Try to load stellar data from layer file
    try:
        stellar = load_layer_input(
            world_dir, "astronomy", "stellar.yaml", StellarSystem, branch=branch
        )
        star_table = Table(title="Stars")
        star_table.add_column("ID")
        star_table.add_column("Name")
        star_table.add_column("Type")
        star_table.add_column("Mass (M_sun)")
        for star in stellar.stars:
            mass_str = f"{star.mass:.2f}" if star.mass is not None else "—"
            star_table.add_row(
                star.id,
                star.name,
                f"{star.spectral_class}{star.luminosity_class.value}",
                mass_str,
            )
        console.print(star_table)
    except (FileNotFoundError, ValidationError):
        console.print("[dim]No astronomy data configured[/dim]")

    # Layer summary
    if config.layers:
        layer_table = Table(title="Layers")
        layer_table.add_column("Layer")
        layer_table.add_column("Configured")
        layer_table.add_column("Engine")

        for layer_name, summary in config.layers.items():
            configured = "[green]yes[/green]" if summary.configured else "[dim]-[/dim]"
            engine = summary.engine or "[dim]-[/dim]"
            layer_table.add_row(layer_name, configured, engine)
        console.print(layer_table)

    # Branches
    branch_mgr = BranchManager(world_dir)
    branches = branch_mgr.list_branches()
    if branches:
        branch_table = Table(title="Branches")
        branch_table.add_column("Name", style="cyan")
        branch_table.add_column("Fork Layer")
        branch_table.add_column("Description")
        for b in branches:
            branch_table.add_row(
                b.name,
                b.fork_layer.value if b.fork_layer else "[dim]-[/dim]",
                b.description or "[dim]-[/dim]",
            )
        console.print(branch_table)

    # Seed
    console.print(f"\n  Seed: [yellow]{config.seed.seed}[/yellow]")
    console.print(f"  Created: {meta.created}")
    console.print(f"  Version: {meta.dreamulator_version}")


@app.command()
def build(
    world: str = typer.Argument(help="World name"),
    branch: str | None = typer.Option(None, "--branch", "-b", help="Branch to build"),
    layer: str | None = typer.Option(None, "--layer", "-l", help="Start building from this layer"),
    force: bool = typer.Option(
        False, "--force", "-f", help="Re-run even if outputs exist; disables per-stage caching"
    ),
    only: str | None = typer.Option(
        None, "--only", help="Run only this engine and its dependencies"
    ),
    seed: int | None = typer.Option(None, help="Override RNG seed"),
    data_dir: Path | None = typer.Option(None, "--data-dir", help="Worlds data directory"),
) -> None:
    """Run the simulation pipeline for a world or branch."""
    _set_data_dir(data_dir)
    from dreamulator.engine.pipeline import run_pipeline
    from dreamulator.models.layers import Layer

    mgr = WorldManager()
    try:
        world_dir = mgr.world_dir(world)
        config = mgr.load_world(world)
    except FileNotFoundError:
        console.print(f"[red]World '{world}' not found[/red]")
        raise typer.Exit(code=1) from None

    effective_seed = seed if seed is not None else config.seed.seed

    # Discover available engines
    from dreamulator.engine import get_all_engines

    engines = get_all_engines()
    if not engines:
        console.print("[yellow]No engines registered. Nothing to build.[/yellow]")
        return

    # Validate layer if specified
    if layer is not None:
        try:
            Layer(layer)
        except ValueError:
            valid = [L.value for L in Layer]
            console.print(f"[red]Unknown layer '{layer}'. Valid layers: {valid}[/red]")
            raise typer.Exit(code=1) from None

    console.print(
        f"[cyan]Building '{world}'"
        + (f" branch '{branch}'" if branch else "")
        + (f" from layer '{layer}'" if layer else "")
        + f" with seed {effective_seed}[/cyan]"
    )

    results = run_pipeline(
        engines,
        world_dir,
        effective_seed,
        force=force,
        only_engine=only,
        branch=branch,
        start_layer=layer,
    )

    # Report results
    success_count = sum(1 for r in results if r.success)
    fail_count = sum(1 for r in results if not r.success)
    skipped = len(engines) - len(results)

    for r in results:
        if r.success:
            console.print(f"  [green]+[/green] {r.engine_name}")
        else:
            console.print(f"  [red]x[/red] {r.engine_name}")
            for w in r.warnings:
                console.print(f"      [red]{w}[/red]")

    console.print(
        f"\n[bold]Results:[/bold] "
        f"[green]{success_count} succeeded[/green], "
        f"[red]{fail_count} failed[/red], "
        f"[dim]{skipped} skipped[/dim]"
    )

    if fail_count > 0:
        raise typer.Exit(code=1) from None


@app.command()
def narrate(
    world: str = typer.Argument(help="World name"),
    branch: str | None = typer.Option(None, "--branch", "-b", help="Branch to narrate"),
    model: str | None = typer.Option(
        None,
        "--model",
        "-m",
        help="Claude model ID (default: resolved from env / settings.json)",
    ),
    max_tokens: int = typer.Option(
        32768,
        "--max-tokens",
        help="Maximum number of output tokens",
    ),
    no_stream: bool = typer.Option(False, "--no-stream", help="Disable streaming output"),
    data_dir: Path | None = typer.Option(None, "--data-dir", help="Worlds data directory"),
) -> None:
    """Generate a conversational description of a world using Claude."""
    _set_data_dir(data_dir)
    from rich.markdown import Markdown

    try:
        from dreamulator.narrator import narrate as generate_narration
    except ImportError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(code=1) from None

    console.print("[yellow]WARNING:[/yellow] 此命令将调用大语言模型 API，会消耗 token。")

    model_label = model or "auto"
    console.print(
        f"[cyan]Generating narration for '{world}'"
        + (f" branch '{branch}'" if branch else "")
        + f" using model={model_label}, max_tokens={max_tokens}...[/cyan]"
    )

    result = None
    if no_stream:
        # Non-streaming mode
        try:
            result = generate_narration(world, branch=branch, model=model, max_tokens=max_tokens)
        except FileNotFoundError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(code=1) from None
        except ImportError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(code=1) from None
        except RuntimeError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(code=1) from None
        except Exception as e:
            console.print(f"[red]API error: {e}[/red]")
            raise typer.Exit(code=1) from None

        console.print()
        console.print(Markdown(result.text))
    else:
        # Streaming mode — print text as it arrives
        import sys
        from io import TextIOWrapper

        # Ensure UTF-8 output (Windows defaults to GBK)
        if isinstance(sys.stdout, TextIOWrapper):
            sys.stdout.reconfigure(encoding="utf-8")

        def on_text_delta(delta: str) -> None:
            sys.stdout.write(delta)
            sys.stdout.flush()

        try:
            sys.stdout.write("\n")
            result = generate_narration(
                world,
                branch=branch,
                model=model,
                max_tokens=max_tokens,
                stream_callback=on_text_delta,
            )
        except FileNotFoundError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(code=1) from None
        except ImportError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(code=1) from None
        except RuntimeError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(code=1) from None
        except Exception as e:
            console.print(f"[red]API error: {e}[/red]")
            raise typer.Exit(code=1) from None

        sys.stdout.write("\n")

    # Print token usage statistics
    if result:
        console.print(
            f"\n[dim]Token 用量: input={result.input_tokens}, "
            f"output={result.output_tokens}, total={result.total_tokens}[/dim]"
        )


@app.command()
def validate(
    world: str = typer.Argument(help="World name"),
    branch: str | None = typer.Option(None, "--branch", "-b", help="Validate a specific branch"),
    data_dir: Path | None = typer.Option(None, "--data-dir", help="Worlds data directory"),
) -> None:
    """Validate a world's files against expected structure and schemas."""
    _set_data_dir(data_dir)
    from dreamulator.branch_manager import BranchManager
    from dreamulator.resolver import LayerResolver

    mgr = WorldManager()
    try:
        errors = mgr.validate_world(world)
    except FileNotFoundError:
        console.print(f"[red]World '{world}' not found[/red]")
        raise typer.Exit(code=1) from None

    # Additional branch validation
    if branch is not None:
        try:
            world_dir = mgr.world_dir(world)
            branch_mgr = BranchManager(world_dir)
            branch_mgr.get_branch(branch)  # Raises if not found

            # Validate layer chain
            resolver = LayerResolver(world_dir, branch)
            resolver.resolve_all_layers()  # Raises on broken chain
        except FileNotFoundError as e:
            errors.append(str(e))
        except Exception as e:
            errors.append(f"Branch validation error: {e}")

    if errors:
        console.print(f"[red]Validation failed with {len(errors)} error(s):[/red]")
        for err in errors:
            console.print(f"  [red]x[/red] {err}")
        raise typer.Exit(code=1) from None
    else:
        target = f"'{world}' branch '{branch}'" if branch else f"'{world}'"
        console.print(f"[green]√[/green] World {target} is valid")


@app.command()
def schema(
    output: Path = typer.Option(
        Path("schemas"),
        help="Output directory for JSON Schema files",
    ),
) -> None:
    """Generate JSON Schema files from Pydantic models."""
    from dreamulator.io.schema_gen import generate_schemas

    generated = generate_schemas(output)
    console.print(f"[green]Generated {len(generated)} schema(s) in {output}[/green]")
    for path in generated:
        console.print(f"  {path.name}")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Host to bind to"),
    port: int = typer.Option(8000, help="Port to listen on"),
    reload: bool = typer.Option(False, "--reload", help="Enable auto-reload for development"),
    open_browser: bool = typer.Option(False, "--open", help="Open browser on start"),
    data_dir: Path | None = typer.Option(None, "--data-dir", help="Worlds data directory"),
) -> None:
    """Start the server (API + frontend)."""
    _set_data_dir(data_dir)
    import threading
    import webbrowser

    import uvicorn

    from dreamulator.world_manager import _data_dir

    resolved = _data_dir()
    source = "[cyan]env[/cyan]" if os.environ.get("DREAMULATOR_DATA_DIR") else "[dim]default[/dim]"
    console.print(f"[dim]data dir: {resolved} ({source})[/dim]")

    url = f"http://{host}:{port}"
    console.print(f"[cyan]Starting dreamulator server at {url}[/cyan]")

    if open_browser:
        # Delay slightly so the server is ready when the browser opens
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    uvicorn.run(
        "dreamulator.api:app",
        host=host,
        port=port,
        reload=reload,
    )


@app.command()
def delete(
    world: str = typer.Argument(help="World name"),
    branch: str | None = typer.Option(None, "--branch", "-b", help="Delete a branch instead"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
    data_dir: Path | None = typer.Option(None, "--data-dir", help="Worlds data directory"),
) -> None:
    """Delete a world or branch."""
    _set_data_dir(data_dir)
    mgr = WorldManager()
    try:
        if branch is not None:
            from dreamulator.branch_manager import BranchManager

            world_dir = mgr.world_dir(world)
            branch_mgr = BranchManager(world_dir)
            if not yes:
                confirm = typer.confirm(f"Delete branch '{branch}' from '{world}'?")
                if not confirm:
                    raise typer.Abort()
            branch_mgr.delete_branch(branch)
            console.print(f"[green]Deleted branch '{branch}' from '{world}'[/green]")
        else:
            if not yes:
                confirm = typer.confirm(f"Delete world '{world}'? This cannot be undone")
                if not confirm:
                    raise typer.Abort()
            mgr.delete_world(world)
            console.print(f"[green]Deleted world '{world}'[/green]")
    except FileNotFoundError:
        console.print(f"[red]World '{world}' not found[/red]")
        raise typer.Exit(code=1) from None


# --- Branch subcommands ---


@branch_app.command("create")
def branch_create(
    world: str = typer.Argument(help="World name"),
    name: str = typer.Argument(help="Branch name"),
    at: str = typer.Option(..., "--at", help="Layer to fork at"),
    description: str = typer.Option("", "--description", "-d", help="Branch description"),
    data_dir: Path | None = typer.Option(None, "--data-dir", help="Worlds data directory"),
) -> None:
    """Create a new branch at the specified layer."""
    _set_data_dir(data_dir)
    from dreamulator.branch_manager import BranchManager
    from dreamulator.models.layers import Layer

    mgr = WorldManager()
    try:
        world_dir = mgr.world_dir(world)
    except FileNotFoundError:
        console.print(f"[red]World '{world}' not found[/red]")
        raise typer.Exit(code=1) from None

    try:
        fork_layer = Layer(at)
    except ValueError:
        valid = [L.value for L in Layer]
        console.print(f"[red]Unknown layer '{at}'. Valid layers: {valid}[/red]")
        raise typer.Exit(code=1) from None

    try:
        branch_mgr = BranchManager(world_dir)
        branch_dir = branch_mgr.create_branch(name, fork_layer, description=description)
        console.print(f"[green]Created branch '{name}' at layer '{at}' in {branch_dir}[/green]")
    except FileExistsError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(code=1) from None


@branch_app.command("list")
def branch_list(
    world: str = typer.Argument(help="World name"),
    data_dir: Path | None = typer.Option(None, "--data-dir", help="Worlds data directory"),
) -> None:
    """List all branches for a world."""
    _set_data_dir(data_dir)
    from dreamulator.branch_manager import BranchManager

    mgr = WorldManager()
    try:
        world_dir = mgr.world_dir(world)
    except FileNotFoundError:
        console.print(f"[red]World '{world}' not found[/red]")
        raise typer.Exit(code=1) from None

    branch_mgr = BranchManager(world_dir)
    branches = branch_mgr.list_branches()

    if not branches:
        console.print(f"[dim]No branches found for '{world}'.[/dim]")
        return

    table = Table(title=f"Branches of {world}")
    table.add_column("Name", style="cyan")
    table.add_column("Fork Layer")
    table.add_column("Parent")
    table.add_column("Description")
    table.add_column("Tags")

    for b in branches:
        table.add_row(
            b.name,
            b.fork_layer.value if b.fork_layer else "[dim]-[/dim]",
            b.parent or "[dim]root[/dim]",
            b.description or "[dim]-[/dim]",
            ", ".join(b.tags) if b.tags else "[dim]-[/dim]",
        )

    console.print(table)


@branch_app.command("info")
def branch_info(
    world: str = typer.Argument(help="World name"),
    name: str = typer.Argument(help="Branch name"),
    data_dir: Path | None = typer.Option(None, "--data-dir", help="Worlds data directory"),
) -> None:
    """Show detailed information about a branch."""
    _set_data_dir(data_dir)
    from dreamulator.branch_manager import BranchManager
    from dreamulator.resolver import LayerResolver

    mgr = WorldManager()
    try:
        world_dir = mgr.world_dir(world)
    except FileNotFoundError:
        console.print(f"[red]World '{world}' not found[/red]")
        raise typer.Exit(code=1) from None

    try:
        branch_mgr = BranchManager(world_dir)
        metadata = branch_mgr.get_branch(name)
    except FileNotFoundError:
        console.print(f"[red]Branch '{name}' not found in '{world}'[/red]")
        raise typer.Exit(code=1) from None

    console.print(f"\n[bold cyan]{metadata.name}[/bold cyan] (branch of {world})")
    if metadata.description:
        console.print(f"  {metadata.description}")
    console.print()
    fork_val = metadata.fork_layer.value if metadata.fork_layer else "-"
    console.print(f"  Fork layer: [yellow]{fork_val}[/yellow]")
    console.print(f"  Parent: {metadata.parent or 'root world'}")
    console.print(f"  Created: {metadata.created.isoformat() if metadata.created else '-'}")
    if metadata.tags:
        console.print(f"  Tags: {', '.join(metadata.tags)}")

    # Show layer resolution
    resolver = LayerResolver(world_dir, name)
    layer_table = Table(title="Layer Sources")
    layer_table.add_column("Layer")
    layer_table.add_column("Source")
    layer_table.add_column("Input Dir")

    for layer, source in resolver.resolve_all_layers().items():
        input_str = str(source.input_dir) if source.input_dir else "[dim]-[/dim]"
        layer_table.add_row(layer.value, source.source, input_str)

    console.print(layer_table)


@branch_app.command("delete")
def branch_delete(
    world: str = typer.Argument(help="World name"),
    name: str = typer.Argument(help="Branch name"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
    data_dir: Path | None = typer.Option(None, "--data-dir", help="Worlds data directory"),
) -> None:
    """Delete a branch."""
    _set_data_dir(data_dir)
    from dreamulator.branch_manager import BranchManager

    mgr = WorldManager()
    try:
        world_dir = mgr.world_dir(world)
    except FileNotFoundError:
        console.print(f"[red]World '{world}' not found[/red]")
        raise typer.Exit(code=1) from None

    try:
        branch_mgr = BranchManager(world_dir)
        if not yes:
            confirm = typer.confirm(f"Delete branch '{name}' from '{world}'?")
            if not confirm:
                raise typer.Abort()
        branch_mgr.delete_branch(name)
        console.print(f"[green]Deleted branch '{name}' from '{world}'[/green]")
    except FileNotFoundError:
        console.print(f"[red]Branch '{name}' not found[/red]")
        raise typer.Exit(code=1) from None


@branch_app.command("promote")
def branch_promote(
    world: str = typer.Argument(help="World name"),
    name: str = typer.Argument(help="Branch name"),
    new_name: str | None = typer.Option(
        None, "--as", help="New world name (defaults to branch name)"
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
    data_dir: Path | None = typer.Option(None, "--data-dir", help="Worlds data directory"),
) -> None:
    """Promote a branch to a standalone world."""
    _set_data_dir(data_dir)
    from dreamulator.branch_manager import BranchManager

    mgr = WorldManager()
    try:
        world_dir = mgr.world_dir(world)
    except FileNotFoundError:
        console.print(f"[red]World '{world}' not found[/red]")
        raise typer.Exit(code=1) from None

    try:
        branch_mgr = BranchManager(world_dir)
        target = new_name or name
        if not yes:
            confirm = typer.confirm(f"Promote branch '{name}' to world '{target}'?")
            if not confirm:
                raise typer.Abort()
        new_dir = branch_mgr.promote_branch(name, new_name)
        console.print(f"[green]Promoted branch '{name}' to world at {new_dir}[/green]")
    except FileNotFoundError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(code=1) from None
    except FileExistsError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(code=1) from None


# --- Conlang subcommands ---


@conlang_app.command("evolve")
def conlang_evolve(
    world: str = typer.Argument(help="World name"),
    language: str = typer.Argument(help="Language ID (directory name under languages/)"),
    generations: int = typer.Option(5, "--generations", "-g", help="Number of generations"),
    seed: int | None = typer.Option(None, help="Override RNG seed"),
    data_dir: Path | None = typer.Option(None, "--data-dir", help="Worlds data directory"),
) -> None:
    """Run SCA sound change on a language's lexicon."""
    _set_data_dir(data_dir)
    from conlang.phonology.sca import SCAEngine

    mgr = WorldManager()
    try:
        world_dir = mgr.world_dir(world)
    except FileNotFoundError:
        console.print(f"[red]World '{world}' not found[/red]")
        raise typer.Exit(code=1) from None

    lang_dir = world_dir / "layers" / "civilization" / "input" / "languages" / language
    rules_file = lang_dir / "sca_rules.sca"
    lexicon_file = lang_dir / "lexicon.yaml"

    if not rules_file.exists():
        console.print(f"[red]SCA rules file not found: {rules_file}[/red]")
        raise typer.Exit(code=1) from None
    if not lexicon_file.exists():
        console.print(f"[red]Lexicon file not found: {lexicon_file}[/red]")
        raise typer.Exit(code=1) from None

    engine = SCAEngine(seed=seed)
    engine.load_rules_file(rules_file)
    engine.load_lexicon_file(lexicon_file)

    console.print(
        f"[cyan]Evolving language '{language}' in '{world}' "
        f"for {generations} generation(s)...[/cyan]"
    )

    history = engine.simulate_generations(generations)

    table = Table(title=f"Sound Change: {language}")
    table.add_column("Proto", style="cyan")
    for gen in range(generations + 1):
        table.add_column(f"Gen {gen}")

    for proto, forms in history.items():
        table.add_row(proto, *forms)

    console.print(table)


@conlang_app.command("tokenize")
def conlang_tokenize(
    word: str = typer.Argument(help="ASCIIPA word to tokenize"),
) -> None:
    """Show the token breakdown of an ASCIIPA word."""
    from conlang.phonology.asciipa import ASCIIPATokenizer

    tokenizer = ASCIIPATokenizer()
    tokens = tokenizer.tokenize(word)
    console.print(f"[cyan]ASCIIPA:[/cyan] {word}")
    console.print(f"[cyan]Tokens ({len(tokens)}):[/cyan]")
    for tok in tokens:
        console.print(f"  {tok.raw!r}  base={tok.base!r}  mods={tok.modifiers}")


# --- Terrain subcommands ---


def _load_terrain_config(
    world_dir: Path,
    planet: str | None,
    branch: str | None,
    config_path: Path | None,
) -> tuple[TerrainPipelineConfig, str, Path]:
    """Load terrain pipeline config from YAML or planet data.

    Returns (TerrainPipelineConfig, planet_id, output_dir).
    """
    import yaml as _yaml

    from dreamulator.map.pipeline_types import TerrainPipelineConfig
    from dreamulator.resolver import LayerResolver

    resolver = LayerResolver(world_dir, branch)

    # Find planet ID
    planet_id = planet
    if planet_id is None:
        # Auto-detect from planets.yaml
        geological_dir = resolver.get_input_dir("geological")
        if geological_dir:
            planets_file = geological_dir / "planets.yaml"
            if planets_file.exists():
                with open(planets_file, encoding="utf-8") as f:
                    data = _yaml.safe_load(f) or {}
                bodies = data.get("bodies", [])
                for body in bodies:
                    if body.get("type") == "planet":
                        planet_id = body["id"]
                        break
        if planet_id is None:
            planet_id = "earth"

    # Load config
    if config_path and config_path.exists():
        cfg = TerrainPipelineConfig.from_yaml(config_path)
    else:
        # Try to find terrain config in geological layer
        geological_input = resolver.get_input_dir("geological")
        cfg = TerrainPipelineConfig()
        if geological_input:
            # Check for terrain config YAML
            terrain_cfg_path = geological_input / "terrain_config.yaml"
            if terrain_cfg_path.exists():
                cfg = TerrainPipelineConfig.from_yaml(terrain_cfg_path)
            else:
                # Try to load from planets.yaml
                planets_file = geological_input / "planets.yaml"
                if planets_file.exists():
                    with open(planets_file, encoding="utf-8") as f:
                        data = _yaml.safe_load(f) or {}
                    for body in data.get("bodies", []):
                        if body.get("id") == planet_id:
                            cfg = TerrainPipelineConfig.from_planet_config(body)
                            break

    # Authored geography (continent anchoring) — same lookup as the geological
    # engine (engine/geological.py).  Without this `build --only geological`
    # silently ignores geography.yaml and falls back to random per-plate continents,
    # losing all named landmasses (regression of 2026-08-06).
    from dreamulator.map.geography import load_geography_spec

    geo_input_dir = resolver.get_input_dir("geological")
    cfg.geography = load_geography_spec(
        (geo_input_dir / "geography.yaml") if geo_input_dir is not None else None
    )

    # Determine output directory — the canonical map registry (world maps/),
    # the same location the geological engine and MapManager read/write.
    # (Previously the legacy layers/geological/input/maps/, which the
    # frontend/API never consulted, so generated maps appeared to vanish.)
    if branch:
        output_dir = world_dir / "branches" / branch / "maps" / planet_id
    else:
        output_dir = world_dir / "maps" / planet_id

    return cfg, planet_id, output_dir


def _load_geography_raster(world_dir: Path, branch: str | None) -> np.ndarray | None:
    """Load the optional dense bias raster (geography_raster.png), if present."""
    from dreamulator.map.geography import load_geography_raster
    from dreamulator.resolver import LayerResolver

    geo_input_dir = LayerResolver(world_dir, branch).get_input_dir("geological")
    if geo_input_dir is None:
        return None
    return load_geography_raster(geo_input_dir / "geography_raster.png")


# terrain_generate removed (v0.25+): use `dreamulator build <world> --only geological`
# instead. The terrain subcommand group is now purely for inspection/export utilities.
# See docs/design/roadmap.md §七 (P2 "CLI 精简").


def _save_benchmark(
    result: object,  # TerrainPipelineResult
    config: object,  # TerrainPipelineConfig
    output_dir: Path,
) -> None:
    """Save a benchmark.json for regression testing."""
    import json

    import numpy as np

    # Collect elevation stats from mesh cells (same source as validate uses)
    mesh = getattr(result, "mesh", None)
    elev_stats = {}
    if mesh is not None:
        elevs = np.array([c.elevation for c in mesh.cells])
        sea = 0.0
        elev_stats = {
            "min_m": float(np.min(elevs)),
            "max_m": float(np.max(elevs)),
            "mean_m": round(float(np.mean(elevs)), 1),
            "land_pct": round(float(np.sum(elevs > sea) / elevs.size * 100), 1),
        }

    # Collect plate stats
    plates = getattr(result, "plates", [])
    plate_sizes = sorted([len(p.cell_ids) for p in plates], reverse=True)

    benchmark = {
        "seed": getattr(config, "seed", 0),
        "num_nodes": getattr(config, "num_nodes", 0),
        "num_plates": len(plates),
        "terrain_algorithm": getattr(config, "terrain_algorithm", ""),
        "tectonic_algorithm": getattr(config, "tectonic_algorithm", ""),
        "tectonic_steps": getattr(config, "tectonic_steps", 0),
        "elevation": elev_stats,
        "plate_sizes": plate_sizes,
        "stages_completed": getattr(result, "stages_completed", []),
        "elapsed_seconds": round(getattr(result, "elapsed_seconds", 0.0), 1),
    }

    bench_path = output_dir / "benchmark.json"
    bench_path.write_text(
        json.dumps(benchmark, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    console.print(f"  [dim]Benchmark saved: {bench_path.name}[/dim]")


def _save_command_record(
    output_dir: Path,
    argv: list[str],
    *,
    world: str,
    planet_id: str,
    branch: str | None,
    data_dir: Path | None,
) -> None:
    """Save a small JSON recording the exact CLI command for reproducibility."""
    import json
    from datetime import datetime

    # Reconstruct a portable command (strip venv prefix)
    cmd_parts = []
    skip = True
    for a in argv:
        if skip and (
            "dreamulator" in a or a.endswith("/dreamulator") or a.endswith("\\dreamulator")
        ):
            cmd_parts.append("dreamulator")
            skip = False
        elif not skip:
            cmd_parts.append(a)
        elif a == "terrain":
            cmd_parts.append(a)
            skip = False
    record = {
        "generated_at": datetime.now(UTC).isoformat(),
        "world": world,
        "planet": planet_id,
        "branch": branch,
        "data_dir": str(data_dir.resolve()) if data_dir else "(default)",
        "command": " ".join(cmd_parts) if cmd_parts else " ".join(argv),
    }
    path = output_dir / "generation_command.json"
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    console.print(f"  [dim]Command saved: {path.name}[/dim]")


@terrain_app.command("validate")
def terrain_validate(
    world: str = typer.Argument(help="World name"),
    planet: str | None = typer.Option(None, "--planet", "-p", help="Planet ID"),
    branch: str | None = typer.Option(None, "--branch", "-b", help="Branch name"),
    reference: Path | None = typer.Option(
        None,
        "--reference",
        help="Path to reference benchmark.json (auto-detect if omitted)",
    ),
    data_dir: Path | None = typer.Option(None, "--data-dir", help="Worlds data directory"),
) -> None:
    """Validate terrain output against a benchmark reference.

    Re-generates terrain with the parameters from the reference benchmark,
    then compares elevation stats and plate distribution.  Exits non-zero
    if the deviation exceeds tolerance.
    """
    import json

    _set_data_dir(data_dir)

    # Auto-detect reference benchmark
    if reference is None:
        mgr = WorldManager()
        try:
            world_dir = mgr.world_dir(world)
        except FileNotFoundError:
            console.print(f"[red]World '{world}' not found[/red]")
            raise typer.Exit(code=1) from None
        cfg, planet_id, output_dir = _load_terrain_config(world_dir, planet, branch, None)
        bench_path = output_dir / "benchmark.json"
    else:
        bench_path = reference

    if not bench_path.exists():
        console.print(
            f"[red]No benchmark found at {bench_path}[/red]\n"
            f"  Run [cyan]dreamulator build {world} --only geological[/cyan] first."
        )
        raise typer.Exit(code=1) from None

    ref = json.loads(bench_path.read_text(encoding="utf-8"))

    # Re-generate with same params
    from dreamulator.map.pipeline_types import TerrainPipelineConfig
    from dreamulator.map.terrain_pipeline import run_terrain_pipeline

    cfg = TerrainPipelineConfig(
        seed=ref["seed"],
        num_nodes=ref["num_nodes"],
        num_plates=ref["num_plates"],
        terrain_algorithm=ref.get("terrain_algorithm", "cortial2019_asymmetric"),
        tectonic_algorithm=ref.get("tectonic_algorithm", ""),
        tectonic_steps=ref.get("tectonic_steps", 0),
    )

    console.print(f"Validating against [cyan]{bench_path.name}[/cyan]...")
    console.print(f"  seed={cfg.seed}, nodes={cfg.num_nodes}, plates={cfg.num_plates}")

    result = run_terrain_pipeline(
        cfg,
        output_dir=None,
        stages=["mesh", "plates", "tectonics", "boundaries", "terrain"],
        geography_raster=_load_geography_raster(world_dir, branch),
    )

    # Compare — read from mesh cells (no export needed)
    import numpy as np

    if result.mesh is None:
        console.print("[red]Pipeline produced no mesh[/red]")
        raise typer.Exit(code=1) from None

    elevs = np.array([c.elevation for c in result.mesh.cells])
    cur = {
        "min_m": float(np.min(elevs)),
        "max_m": float(np.max(elevs)),
        "mean_m": float(np.mean(elevs)),
        "land_pct": round(float(np.sum(elevs > 0) / elevs.size * 100), 1),
    }
    ref_elev = ref.get("elevation", {})
    cur_plates = sorted(
        [len(p.cell_ids) for p in getattr(result, "plates", [])],
        reverse=True,
    )
    ref_plates = ref.get("plate_sizes", [])

    def _delta(label: str, ref_val: float, cur_val: float, tol_pct: float) -> bool:
        delta = abs(cur_val - ref_val) / max(abs(ref_val), 1.0) * 100
        ok = delta <= tol_pct
        status = "[green]OK[/green]" if ok else "[red]FAIL[/red]"
        console.print(f"  {status} {label}: ref={ref_val:.1f} cur={cur_val:.1f} ({delta:+.1f}%)")
        return ok

    all_ok = True
    all_ok &= _delta("elev_min", ref_elev.get("min_m", 0), cur["min_m"], 15)
    all_ok &= _delta("elev_max", ref_elev.get("max_m", 0), cur["max_m"], 15)
    all_ok &= _delta("elev_mean", ref_elev.get("mean_m", 0), cur["mean_m"], 10)
    all_ok &= _delta("land_pct", ref_elev.get("land_pct", 0), cur["land_pct"], 20)

    if len(cur_plates) == len(ref_plates):
        for i, (rc, cc) in enumerate(zip(ref_plates, cur_plates, strict=True)):
            delta = abs(cc - rc) / max(rc, 1) * 100
            if delta > 30:
                all_ok = False
                console.print(
                    f"  [red]FAIL[/red] plate_{i:02d} size: ref={rc} cur={cc} ({delta:+.0f}%)"
                )
        console.print(f"  Plate sizes: ref={ref_plates[:5]}..., cur={cur_plates[:5]}...")
    else:
        console.print(f"  [red]FAIL[/red] plate count: ref={len(ref_plates)} cur={len(cur_plates)}")
        all_ok = False

    if all_ok:
        console.print("\n[bold green]Validation passed[/bold green]")
    else:
        console.print("\n[bold red]Validation failed — see details above[/bold red]")
        raise typer.Exit(code=1) from None


@terrain_app.command("open")
def terrain_open(
    world: str = typer.Argument(help="World name"),
    planet: str | None = typer.Option(None, "--planet", "-p", help="Planet ID"),
    branch: str | None = typer.Option(None, "--branch", "-b", help="Branch name"),
    data_dir: Path | None = typer.Option(None, "--data-dir", help="Worlds data directory"),
) -> None:
    """Open the terrain output directory in the file explorer."""
    import subprocess

    _set_data_dir(data_dir)
    mgr = WorldManager()
    try:
        world_dir = mgr.world_dir(world)
    except FileNotFoundError:
        console.print(f"[red]World '{world}' not found[/red]")
        raise typer.Exit(code=1) from None

    cfg, planet_id, output_dir = _load_terrain_config(world_dir, planet, branch, None)

    if not output_dir.exists():
        console.print("[yellow]Output directory does not exist yet.[/yellow]")
        console.print(f"  Run [cyan]dreamulator build {world} --only geological[/cyan] first.")
        raise typer.Exit(code=1) from None

    console.print(f"Opening [cyan]{output_dir}[/cyan]")
    if sys.platform == "win32":
        subprocess.run(["explorer", str(output_dir)])
    elif sys.platform == "darwin":
        subprocess.run(["open", str(output_dir)])
    else:
        subprocess.run(["xdg-open", str(output_dir)])


def _write_branch_readme(
    output_dir: Path,
    world: str,
    planet_id: str,
    branch: str | None,
) -> None:
    """Auto-generate a README in the branch root explaining the layout."""
    # Walk up to find the branch root
    # output_dir = .../layers/geological/input/maps/earth
    # branch_root = output_dir.parents[4]  (= layers -> geological -> input -> maps -> earth)
    # Actually: .../branches/terrain-dev/layers/geological/input/maps/earth
    p = output_dir
    # Walk up to the branch directory (contains branch.yaml)
    branch_root = None
    for _ in range(10):
        if (p / "branch.yaml").exists():
            branch_root = p
            break
        p = p.parent

    if branch_root is None:
        return

    readme = branch_root / "README.md"
    existing = ""
    if readme.exists():
        existing = readme.read_text(encoding="utf-8")

    # Only write if the terrain section isn't already there
    marker = "## 🗺️ Terrain Data"
    if marker in existing:
        return

    branch_name = branch or "main"

    new_section = f"""
{marker}

Terrain generation output for **{world}** · planet `{planet_id}` · branch `{branch_name}`.

```
{branch_root.name}/
└── layers/geological/input/maps/{planet_id}/
    ├── elevation.png      ← heightmap (16-bit PNG)
    ├── cvt_mesh.json      ← spherical Voronoi mesh
    ├── plates.json        ← tectonic plate definitions
    ├── metadata.json      ← pipeline parameters
    └── timeline/          ← time-evolution snapshots (when enabled)
```

### Quick access

```bash
# Open in file explorer
dreamulator terrain open {world} --planet {planet_id} --branch {branch_name}

# View info
dreamulator terrain info {world} --planet {planet_id} --branch {branch_name}
```
"""
    new_content = existing.rstrip() + "\n" + new_section
    readme.write_text(new_content, encoding="utf-8")
    logger = logging.getLogger("cli")
    logger.info("  Auto-generated README: %s", readme)


@terrain_app.command("info")
def terrain_info(
    world: str = typer.Argument(help="World name"),
    planet: str | None = typer.Option(None, "--planet", "-p", help="Planet ID"),
    branch: str | None = typer.Option(None, "--branch", "-b", help="Branch name"),
    data_dir: Path | None = typer.Option(None, "--data-dir", help="Worlds data directory"),
) -> None:
    """Show summary of generated terrain data."""
    import json

    _set_data_dir(data_dir)
    mgr = WorldManager()
    try:
        world_dir = mgr.world_dir(world)
    except FileNotFoundError:
        console.print(f"[red]World '{world}' not found[/red]")
        raise typer.Exit(code=1) from None

    from dreamulator.resolver import LayerResolver

    resolver = LayerResolver(world_dir, branch)

    planet_id = planet or "earth"

    # Check input first, then derived
    map_dir = None
    for get_dir in (resolver.get_input_dir, resolver.get_derived_dir):
        base_dir = get_dir("geological")
        if base_dir is not None:
            candidate = base_dir / "maps" / planet_id
            if candidate.exists():
                map_dir = candidate
                break

    if map_dir is None:
        console.print(f"[yellow]No terrain data for planet '{planet_id}'[/yellow]")
        raise typer.Exit(code=1) from None

    # Read metadata from map.yaml (with fallback to legacy metadata.json)
    import yaml as _yaml_info

    map_yaml_file = map_dir / "map.yaml"
    meta: dict[str, Any] = {}
    if map_yaml_file.exists():
        with open(map_yaml_file, encoding="utf-8") as f:
            meta = _yaml_info.safe_load(f) or {}
    else:
        meta_file = map_dir / "metadata.json"
        if meta_file.exists():
            with open(meta_file, encoding="utf-8") as f:
                meta = json.load(f)

    if meta:
        console.print(f"[bold]Terrain Data: {world} / {planet_id}[/bold]")
        console.print(f"  Seed: {meta.get('voronoi_seed', meta.get('seed', 'N/A'))}")
        console.print(f"  Nodes: {meta.get('voronoi_num_cells', meta.get('num_nodes', 'N/A')):,}")
        console.print(f"  Plates: {meta.get('num_plates', 'N/A')}")
        console.print(f"  Pipeline: {meta.get('pipeline_version', 'unknown')}")
        elev_range = meta.get("elevation_range_m", [])
        if elev_range:
            console.print(f"  Elevation: [{elev_range[0]:.0f}, {elev_range[1]:.0f}] m")
        w = meta.get("width", "")
        h = meta.get("height", "")
        if w and h:
            console.print(f"  Resolution: {w}x{h}")
    else:
        console.print("[yellow]No map.yaml or metadata.json found[/yellow]")

    # List files
    table = Table(title="Output Files")
    table.add_column("File", style="cyan")
    table.add_column("Size", justify="right")

    import os

    for fname in sorted(os.listdir(map_dir)):
        size = os.path.getsize(map_dir / fname)
        if size > 1_000_000:
            size_str = f"{size / 1_000_000:.1f} MB"
        elif size > 1_000:
            size_str = f"{size / 1_000:.1f} KB"
        else:
            size_str = f"{size} B"
        table.add_row(fname, size_str)

    console.print(table)

    # ---- Land / sea ratio (from cvt_mesh.json) ----
    mesh_file = map_dir / "cvt_mesh.json"
    if mesh_file.exists():
        from dreamulator.map.export import decompress_mesh_bytes

        console.print("[bold]Land / Sea Ratio[/bold]")
        mesh = json.loads(decompress_mesh_bytes(mesh_file.read_bytes()))
        cells = mesh.get("cells", [])
        if cells:
            total = len(cells)
            total_area = 0.0
            land_area = 0.0
            continental_area = 0.0
            elevs = []
            for c in cells:
                elev = c.get("elevation", 0)
                area = c.get("area_km2", 0)
                elevs.append(elev)
                total_area += area
                if elev > 0:
                    land_area += area
                if c.get("crust_type") == "continental":
                    continental_area += area

            land_pct = land_area / total_area * 100
            crust_pct = continental_area / total_area * 100
            elev_min = min(elevs)
            elev_max = max(elevs)

            console.print(f"  Total cells:         {total:,}")
            console.print(f"  Total surface area:  {total_area:,.0f} km2")
            console.print(f"  Emergent land:       {land_area:,.0f} km2 ({land_pct:.1f}%)")
            console.print(
                f"  Ocean (<=0 m):       {total_area - land_area:,.0f} km2 ({100 - land_pct:.1f}%)"
            )
            console.print(f"  Continental crust:   {continental_area:,.0f} km2 ({crust_pct:.1f}%)")
            oceanic_area = total_area - continental_area
            console.print(
                f"  Oceanic crust:       {oceanic_area:,.0f} km2 ({100 - crust_pct:.1f}%)"
            )
            console.print(f"  Elevation range:     [{elev_min:.0f}, {elev_max:.0f}] m")

            # Quality metrics
            sea_level = 0.0
            peak_prominence = elev_max - sea_level
            abyss_depth = sea_level - elev_min
            console.print(f"  Peak prominence:     {peak_prominence:.0f} m above sea level")
            console.print(f"  Max ocean depth:     {abyss_depth:.0f} m below sea level")


@terrain_app.command("export")
def terrain_export(
    world: str = typer.Argument(help="World name"),
    planet: str | None = typer.Option(None, "--planet", "-p", help="Planet ID"),
    output: Path = typer.Option(Path("export/"), "--output", "-o", help="Output directory"),
    branch: str | None = typer.Option(None, "--branch", "-b", help="Branch name"),
    data_dir: Path | None = typer.Option(None, "--data-dir", help="Worlds data directory"),
) -> None:
    """Export terrain data to standard formats (PNG, JSON)."""
    import shutil

    _set_data_dir(data_dir)
    mgr = WorldManager()
    try:
        world_dir = mgr.world_dir(world)
    except FileNotFoundError:
        console.print(f"[red]World '{world}' not found[/red]")
        raise typer.Exit(code=1) from None

    from dreamulator.resolver import LayerResolver

    resolver = LayerResolver(world_dir, branch)

    planet_id = planet or "earth"

    # Check input first, then derived
    map_dir = None
    for get_dir in (resolver.get_input_dir, resolver.get_derived_dir):
        base_dir = get_dir("geological")
        if base_dir is not None:
            candidate = base_dir / "maps" / planet_id
            if candidate.exists():
                map_dir = candidate
                break

    if map_dir is None:
        console.print(f"[red]No terrain data for planet '{planet_id}'[/red]")
        console.print("Run 'dreamulator build <world> --only geological' first.")
        raise typer.Exit(code=1) from None

    # Copy all files to output directory
    output.mkdir(parents=True, exist_ok=True)
    for f in map_dir.iterdir():
        if f.is_file():
            shutil.copy2(f, output / f.name)

    console.print(f"[green]Exported terrain data to {output}[/green]")
    for f in sorted(output.iterdir()):
        console.print(f"  {f.name}")


if __name__ == "__main__":
    app()
