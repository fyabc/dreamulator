"""Typer CLI entry point for dreamulator."""

from __future__ import annotations

from pathlib import Path

import typer
from pydantic import ValidationError
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

# Conlang subcommand group
conlang_app = typer.Typer(help="Conlang tools for language design and sound change simulation.")
app.add_typer(conlang_app, name="conlang")


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
) -> None:
    """Generate a conversational description of a world using Claude."""
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


# --- Conlang subcommands ---


@conlang_app.command("evolve")
def conlang_evolve(
    world: str = typer.Argument(help="World name"),
    language: str = typer.Argument(help="Language ID (directory name under languages/)"),
    generations: int = typer.Option(5, "--generations", "-g", help="Number of generations"),
    seed: int | None = typer.Option(None, help="Override RNG seed"),
) -> None:
    """Run SCA sound change on a language's lexicon."""
    from conlang.phonology.sca import SCAEngine

    mgr = WorldManager()
    try:
        world_dir = mgr.world_dir(world)
    except FileNotFoundError:
        console.print(f"[red]World '{world}' not found[/red]")
        raise typer.Exit(code=1)

    lang_dir = world_dir / "layers" / "civilization" / "input" / "languages" / language
    rules_file = lang_dir / "sca_rules.sca"
    lexicon_file = lang_dir / "lexicon.yaml"

    if not rules_file.exists():
        console.print(f"[red]SCA rules file not found: {rules_file}[/red]")
        raise typer.Exit(code=1)
    if not lexicon_file.exists():
        console.print(f"[red]Lexicon file not found: {lexicon_file}[/red]")
        raise typer.Exit(code=1)

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


if __name__ == "__main__":
    app()
