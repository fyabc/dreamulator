"""Typer CLI entry point for dreamulator."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from dreamulator import __version__
from dreamulator.world_manager import WorldManager

app = typer.Typer(
    name="dreamulator",
    help="Fantasy world building and simulation tool grounded in real science.",
    no_args_is_help=True,
)
console = Console()

# Branch subcommand group
branch_app = typer.Typer(help="Manage world branches.")
app.add_typer(branch_app, name="branch")


@app.command()
def version() -> None:
    """Show dreamulator version."""
    console.print(f"dreamulator v{__version__}")


@app.command()
def init(
    name: str = typer.Argument(help="World name (used as directory name)"),
    seed: int | None = typer.Option(None, help="RNG seed (random if omitted)"),
    template: str = typer.Option("minimal", help="Starting template: minimal, earthlike"),
) -> None:
    """Create a new world with template configuration files."""
    mgr = WorldManager()
    try:
        world_dir = mgr.create_world(name, seed=seed, template=template)
        console.print(f"[green]Created world '{name}' at {world_dir}[/green]")
    except FileExistsError as e:
        console.print(f"[red]Error: {e}[/red]", style="bold")
        raise typer.Exit(code=1)
    except FileNotFoundError as e:
        console.print(f"[red]Error: {e}[/red]", style="bold")
        raise typer.Exit(code=1)


@app.command(name="list")
def list_worlds() -> None:
    """List all available worlds."""
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
) -> None:
    """Show detailed information about a world or branch."""
    from dreamulator.branch_manager import BranchManager
    from dreamulator.io.loader import load_layer_input
    from dreamulator.models.stellar import StellarSystem

    mgr = WorldManager()
    try:
        world_dir = mgr.world_dir(world)
        config = mgr.load_world(world)
    except FileNotFoundError:
        console.print(f"[red]World '{world}' not found[/red]")
        raise typer.Exit(code=1)

    meta = config.metadata
    console.print(f"\n[bold cyan]{meta.name}[/bold cyan]")
    if meta.description:
        console.print(f"  {meta.description}")
    console.print()

    # Try to load stellar data from layer file
    try:
        stellar = load_layer_input(
            world_dir, "stellar", "stellar.yaml", StellarSystem, branch=branch
        )
        star_table = Table(title="Stars")
        star_table.add_column("ID")
        star_table.add_column("Name")
        star_table.add_column("Type")
        star_table.add_column("Mass (M_sun)")
        for star in stellar.stars:
            star_table.add_row(
                star.id,
                star.name,
                f"{star.spectral_class.value}{star.luminosity_class.value}",
                f"{star.mass:.2f}",
            )
        console.print(star_table)
    except FileNotFoundError:
        console.print("[dim]No stellar data configured[/dim]")

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
    layer: str | None = typer.Option(
        None, "--layer", "-l", help="Start building from this layer"
    ),
    force: bool = typer.Option(False, "--force", "-f", help="Re-run even if outputs exist"),
    only: str | None = typer.Option(
        None, "--only", help="Run only this engine and its dependencies"
    ),
    seed: int | None = typer.Option(None, help="Override RNG seed"),
) -> None:
    """Run the simulation pipeline for a world or branch."""
    from dreamulator.engine.pipeline import run_pipeline
    from dreamulator.models.layers import Layer

    mgr = WorldManager()
    try:
        world_dir = mgr.world_dir(world)
        config = mgr.load_world(world)
    except FileNotFoundError:
        console.print(f"[red]World '{world}' not found[/red]")
        raise typer.Exit(code=1)

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
            raise typer.Exit(code=1)

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
        raise typer.Exit(code=1)


@app.command()
def validate(
    world: str = typer.Argument(help="World name"),
    branch: str | None = typer.Option(None, "--branch", "-b", help="Validate a specific branch"),
) -> None:
    """Validate a world's files against expected structure and schemas."""
    from dreamulator.branch_manager import BranchManager
    from dreamulator.resolver import LayerResolver

    mgr = WorldManager()
    try:
        errors = mgr.validate_world(world)
    except FileNotFoundError:
        console.print(f"[red]World '{world}' not found[/red]")
        raise typer.Exit(code=1)

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
        raise typer.Exit(code=1)
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
) -> None:
    """Start the server (API + frontend)."""
    import threading
    import webbrowser

    import uvicorn

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
) -> None:
    """Delete a world or branch."""
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
        raise typer.Exit(code=1)


# --- Branch subcommands ---


@branch_app.command("create")
def branch_create(
    world: str = typer.Argument(help="World name"),
    name: str = typer.Argument(help="Branch name"),
    at: str = typer.Option(..., "--at", help="Layer to fork at"),
    description: str = typer.Option("", "--description", "-d", help="Branch description"),
) -> None:
    """Create a new branch at the specified layer."""
    from dreamulator.branch_manager import BranchManager
    from dreamulator.models.layers import Layer

    mgr = WorldManager()
    try:
        world_dir = mgr.world_dir(world)
    except FileNotFoundError:
        console.print(f"[red]World '{world}' not found[/red]")
        raise typer.Exit(code=1)

    try:
        fork_layer = Layer(at)
    except ValueError:
        valid = [L.value for L in Layer]
        console.print(f"[red]Unknown layer '{at}'. Valid layers: {valid}[/red]")
        raise typer.Exit(code=1)

    try:
        branch_mgr = BranchManager(world_dir)
        branch_dir = branch_mgr.create_branch(name, fork_layer, description=description)
        console.print(f"[green]Created branch '{name}' at layer '{at}' in {branch_dir}[/green]")
    except FileExistsError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(code=1)


@branch_app.command("list")
def branch_list(
    world: str = typer.Argument(help="World name"),
) -> None:
    """List all branches for a world."""
    from dreamulator.branch_manager import BranchManager

    mgr = WorldManager()
    try:
        world_dir = mgr.world_dir(world)
    except FileNotFoundError:
        console.print(f"[red]World '{world}' not found[/red]")
        raise typer.Exit(code=1)

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
) -> None:
    """Show detailed information about a branch."""
    from dreamulator.branch_manager import BranchManager
    from dreamulator.resolver import LayerResolver

    mgr = WorldManager()
    try:
        world_dir = mgr.world_dir(world)
    except FileNotFoundError:
        console.print(f"[red]World '{world}' not found[/red]")
        raise typer.Exit(code=1)

    try:
        branch_mgr = BranchManager(world_dir)
        metadata = branch_mgr.get_branch(name)
    except FileNotFoundError:
        console.print(f"[red]Branch '{name}' not found in '{world}'[/red]")
        raise typer.Exit(code=1)

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
) -> None:
    """Delete a branch."""
    from dreamulator.branch_manager import BranchManager

    mgr = WorldManager()
    try:
        world_dir = mgr.world_dir(world)
    except FileNotFoundError:
        console.print(f"[red]World '{world}' not found[/red]")
        raise typer.Exit(code=1)

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
        raise typer.Exit(code=1)


@branch_app.command("promote")
def branch_promote(
    world: str = typer.Argument(help="World name"),
    name: str = typer.Argument(help="Branch name"),
    new_name: str | None = typer.Option(
        None, "--as", help="New world name (defaults to branch name)"
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
) -> None:
    """Promote a branch to a standalone world."""
    from dreamulator.branch_manager import BranchManager

    mgr = WorldManager()
    try:
        world_dir = mgr.world_dir(world)
    except FileNotFoundError:
        console.print(f"[red]World '{world}' not found[/red]")
        raise typer.Exit(code=1)

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
        raise typer.Exit(code=1)
    except FileExistsError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
