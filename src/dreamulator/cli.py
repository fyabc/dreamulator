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
    mgr = WorldManager()
    worlds = mgr.list_worlds()
    if not worlds:
        console.print("[dim]No worlds found. Create one with:[/dim] dreamulator init <name>")
        return

    table = Table(title="Worlds")
    table.add_column("Name", style="cyan")
    table.add_column("Description")
    table.add_column("Created")

    for name in worlds:
        try:
            config = mgr.load_world(name)
            table.add_row(
                name,
                config.metadata.description or "[dim]—[/dim]",
                config.metadata.created[:10] if config.metadata.created else "[dim]—[/dim]",
            )
        except Exception:
            table.add_row(name, "[red]load error[/red]", "[dim]—[/dim]")

    console.print(table)


@app.command()
def info(
    world: str = typer.Argument(help="World name"),
) -> None:
    """Show detailed information about a world."""
    mgr = WorldManager()
    try:
        config = mgr.load_world(world)
    except FileNotFoundError:
        console.print(f"[red]World '{world}' not found[/red]")
        raise typer.Exit(code=1)

    meta = config.metadata
    console.print(f"\n[bold cyan]{meta.name}[/bold cyan]")
    if meta.description:
        console.print(f"  {meta.description}")
    console.print()

    # Stars
    table = Table(title="Stars")
    table.add_column("ID")
    table.add_column("Name")
    table.add_column("Type")
    table.add_column("Mass (M_sun)")
    for star in config.stellar_system.stars:
        table.add_row(
            star.id,
            star.name,
            f"{star.spectral_class.value}{star.luminosity_class.value}",
            f"{star.mass:.2f}",
        )
    console.print(table)

    # Seed
    console.print(f"\n  Seed: [yellow]{config.seed.seed}[/yellow]")
    console.print(f"  Created: {meta.created}")
    console.print(f"  Version: {meta.dreamulator_version}")


@app.command()
def validate(
    world: str = typer.Argument(help="World name"),
) -> None:
    """Validate a world's files against expected structure and schemas."""
    mgr = WorldManager()
    try:
        errors = mgr.validate_world(world)
    except FileNotFoundError:
        console.print(f"[red]World '{world}' not found[/red]")
        raise typer.Exit(code=1)

    if errors:
        console.print(f"[red]Validation failed with {len(errors)} error(s):[/red]")
        for err in errors:
            console.print(f"  [red]✗[/red] {err}")
        raise typer.Exit(code=1)
    else:
        console.print(f"[green]✓[/green] World '{world}' is valid")


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
) -> None:
    """Start the FastAPI development server."""
    import uvicorn

    console.print(f"[cyan]Starting dreamulator API server at http://{host}:{port}[/cyan]")
    uvicorn.run(
        "dreamulator.api:app",
        host=host,
        port=port,
        reload=reload,
    )


@app.command()
def delete(
    world: str = typer.Argument(help="World name"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
) -> None:
    """Delete a world."""
    mgr = WorldManager()
    try:
        if not yes:
            confirm = typer.confirm(f"Delete world '{world}'? This cannot be undone")
            if not confirm:
                raise typer.Abort()
        mgr.delete_world(world)
        console.print(f"[green]Deleted world '{world}'[/green]")
    except FileNotFoundError:
        console.print(f"[red]World '{world}' not found[/red]")
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
