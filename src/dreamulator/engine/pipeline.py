"""Engine pipeline — DAG-based dependency resolution and execution."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.console import Console

from dreamulator.models.layers import LAYER_ORDER, Layer, get_layer_index
from dreamulator.resolver import LayerResolver
from dreamulator.utils.logging import setup_logging

from .base import BaseEngine, EngineResult

if TYPE_CHECKING:
    from pathlib import Path

logger = setup_logging()

_console = Console()


def topological_sort(engines: list[type[BaseEngine]]) -> list[type[BaseEngine]]:
    """Sort engines by dependency order (topological sort).

    Args:
        engines: List of engine classes to sort.

    Returns:
        Engines sorted so that dependencies come before dependents.

    Raises:
        ValueError: If there is a circular dependency.
    """
    by_name = {e.name: e for e in engines}
    visited: set[str] = set()
    visiting: set[str] = set()
    result: list[type[BaseEngine]] = []

    def visit(name: str) -> None:
        if name in visited:
            return
        if name in visiting:
            raise ValueError(f"Circular dependency detected involving engine: {name}")
        visiting.add(name)
        engine_cls = by_name.get(name)
        if engine_cls is None:
            raise ValueError(f"Unknown engine dependency: {name}")
        for dep in engine_cls.requires:
            visit(dep)
        visiting.discard(name)
        visited.add(name)
        result.append(engine_cls)

    for engine_cls in engines:
        visit(engine_cls.name)

    return result


def run_pipeline(
    engines: list[type[BaseEngine]],
    world_dir: Path,
    seed: int,
    *,
    force: bool = False,
    only_engine: str | None = None,
    branch: str | None = None,
    start_layer: Layer | str | None = None,
) -> list[EngineResult]:
    """Run the engine pipeline in dependency order.

    Args:
        engines: List of engine classes to run.
        world_dir: Path to the world directory.
        seed: RNG seed for reproducibility.
        force: Re-run even if outputs already exist.
        only_engine: If set, run only this engine and its dependencies.
        branch: Branch name to build (None for root world).
        start_layer: Start building from this layer (skip earlier layers).

    Returns:
        List of EngineResults from each engine run.
    """
    all_sorted = topological_sort(engines)
    sorted_engines = all_sorted

    # Determine the effective start layer
    if start_layer is not None:
        if isinstance(start_layer, str):
            start_layer = Layer(start_layer)
        effective_start: Layer | None = start_layer
    elif branch is not None:
        # For branches, start from the fork layer
        resolver = LayerResolver(world_dir, branch)
        fork_layer = resolver.get_fork_layer()
        effective_start = fork_layer  # None means start from beginning
    else:
        effective_start = None

    # Filter engines to only include those at or after the start layer
    if effective_start is not None:
        start_idx = get_layer_index(effective_start)
        valid_layers = set(LAYER_ORDER[start_idx:])
        sorted_engines = [e for e in sorted_engines if e.layer in valid_layers]

    if only_engine:
        # Find the target engine and all its transitive dependencies
        needed = _collect_dependencies(only_engine, sorted_engines)
        sorted_engines = [e for e in sorted_engines if e.name in needed]

    # Create resolver for layer-aware path resolution
    resolver = LayerResolver(world_dir, branch)
    layer_sources = resolver.resolve_all_layers()

    # Build layer_input_dirs map
    layer_input_dirs: dict[str, Path] = {}
    layer_derived_dirs: dict[str, Path] = {}
    for layer, source in layer_sources.items():
        if source.input_dir is not None:
            layer_input_dirs[layer.value] = source.input_dir
        if source.derived_dir is not None:
            layer_derived_dirs[layer.value] = source.derived_dir

    # Auto-prepare derived inputs whose producing engines were filtered out
    # (build bootstrap M1-P0): a climate fork excludes astronomy, but the
    # climate engine still requires astronomy-derived inputs from the source
    # (parent) context.  Fresh checkouts have no gitignored derived files, so
    # build them in the parent context instead of failing opaquely.
    excluded_engines = [e for e in all_sorted if e.name not in {x.name for x in sorted_engines}]
    if excluded_engines:
        _bootstrap_missing_upstream(
            sorted_engines,
            excluded_engines,
            world_dir,
            seed,
            layer_input_dirs=layer_input_dirs,
            layer_derived_dirs=layer_derived_dirs,
            resolver=resolver,
        )

    results: list[EngineResult] = []
    profile_records: list[dict[str, Any]] = []
    import time as _time

    t_build_start = _time.time()
    upstream_ran = False  # when an upstream engine executes, downstream must re-run
    for engine_cls in sorted_engines:
        # Determine output directory for this engine's layer
        if branch is not None:
            branch_dir = world_dir / "branches" / branch
            layer_output_dir = branch_dir / "layers" / engine_cls.layer.value / "derived"
            maps_output_dir = branch_dir / "maps"
        else:
            layer_output_dir = world_dir / "layers" / engine_cls.layer.value / "derived"
            maps_output_dir = world_dir / "maps"

        # Ensure output directory exists
        layer_output_dir.mkdir(parents=True, exist_ok=True)

        engine = engine_cls(
            world_dir,
            seed,
            layer_input_dirs=layer_input_dirs,
            layer_derived_dirs=layer_derived_dirs,
            layer_output_dir=layer_output_dir,
            maps_output_dir=maps_output_dir,
        )

        # Skip if outputs exist and engine was neither forced nor stale.
        # --force bypasses everything; stale means an upstream engine
        # actually executed, so this engine's outputs are likely outdated.
        # When --only is specified, only force the target engine;
        # dependencies still use cache (avoid re-running geological
        # when user only wants to re-run climate).
        should_force = force and (only_engine is None or engine.name == only_engine)
        if (
            not should_force
            and not upstream_ran
            and _outputs_exist(engine)
            and not _is_dirty(engine)
        ):
            _console.print(f"  [dim]{engine.layer.value}: up-to-date, skipped[/dim]")
            logger.info("Skipping %s (outputs up-to-date)", engine.name)
            continue

        errors = engine.validate_inputs()
        if errors:
            logger.error("Engine %s input validation failed:", engine.name)
            for err in errors:
                logger.error("  %s", err)
            results.append(
                EngineResult(
                    engine_name=engine.name,
                    success=False,
                    warnings=errors,
                )
            )
            break

        logger.info(
            "Running engine: %s (layer: %s)",
            engine.name,
            engine.layer.value,
        )

        # Rich progress output
        _console.print(
            f"\n[bold cyan]>> {engine.layer.value}[/bold cyan]  [dim]({engine.name})[/dim]"
        )
        _t0 = _time.time()
        result = engine.run(force=should_force)
        _elapsed = _time.time() - _t0
        upstream_ran = True
        results.append(result)

        record: dict[str, Any] = {
            "engine": engine.name,
            "layer": engine.layer.value,
            "wall_seconds": round(_elapsed, 3),
            "success": bool(result.success),
        }
        metadata = getattr(result, "metadata", None) or {}
        stages = metadata.get("stage_timings") or metadata.get("phase_timings")
        if isinstance(stages, dict):
            record["stages"] = {k: round(float(v), 3) for k, v in stages.items()}

        if not result.success:
            _console.print(f"  [red]FAILED[/red] ({_elapsed:.1f}s)")
            logger.error("Engine %s failed", engine.name)
            profile_records.append(record)
            break

        _console.print(f"  [green]done[/green] [dim]({_elapsed:.1f}s)[/dim]")
        logger.info("Engine %s completed successfully", engine.name)
        profile_records.append(record)

        # Register this engine's output as a derived source for subsequent engines
        layer_derived_dirs[engine_cls.layer.value] = layer_output_dir

    # ---- Build profile (M0 instrumentation) ----
    total = _time.time() - t_build_start
    profile = {
        "world": world_dir.name,
        "branch": branch,
        "seed": seed,
        "total_wall_seconds": round(total, 3),
        "engines": profile_records,
    }
    try:
        import json

        profile_path = world_dir / "build_profile.json"
        with profile_path.open("w", encoding="utf-8") as f:
            json.dump(profile, f, indent=2, ensure_ascii=False)
        logger.info("Build profile written: %s", profile_path)
    except OSError as e:
        logger.warning("Failed to write build profile: %s", e)

    _console.print(
        f"\n[bold]Build profile[/bold] (total {total:.1f}s, saved to build_profile.json)"
    )
    for rec in profile_records:
        share = rec["wall_seconds"] / max(total, 1e-9)
        status = "[green]ok[/green]" if rec["success"] else "[red]FAILED[/red]"
        _console.print(f"  {rec['engine']:<12} {rec['wall_seconds']:6.1f}s  {share:4.0%}  {status}")
        for name, secs in sorted((rec.get("stages") or {}).items(), key=lambda kv: -kv[1]):
            if secs >= 0.05 * total:
                _console.print(f"    [dim]{name:<22} {secs:6.1f}s[/dim]")

    return results


# Engines allowed to run automatically to prepare missing derived inputs.
# Astronomy is seconds-cheap, pure layer-derived YAML, and required by every
# downstream engine.  Map-producing engines (geological) must NEVER auto-run:
# imported terrain needs an explicit documented import (network + data deps),
# and generated terrain is minutes of compute that belongs to an explicit
# geological build — both fail with recovery instructions instead.
_BOOTSTRAP_ENGINES = {"astronomy"}


def _bootstrap_missing_upstream(
    included: list[type[BaseEngine]],
    excluded: list[type[BaseEngine]],
    world_dir: Path,
    seed: int,
    *,
    layer_input_dirs: dict[str, Path],
    layer_derived_dirs: dict[str, Path],
    resolver: LayerResolver,
) -> None:
    """Build missing derived inputs from engines the fork filter excluded.

    A branch that forks at layer L runs only engines for L and after; required
    inputs produced by pre-fork engines come from the source (parent) context.
    When such a derived file is missing — typically a fresh checkout, where
    gitignored derived products do not exist — the producing engine is run
    once against its resolved source directories, writing to the source
    context (e.g. the root world's ``layers/astronomy/derived/``), never the
    branch.  Only engines in ``_BOOTSTRAP_ENGINES`` are auto-run; anything
    else falls through to the regular input validation error.

    Args:
        included: Engines the pipeline is about to run (post-filter).
        excluded: Engines removed by the fork/start/only filters.
        world_dir: Root world directory.
        seed: RNG seed (passed through to the bootstrap run).
        layer_input_dirs: Resolved effective input dirs (branch-aware).
        layer_derived_dirs: Resolved derived dirs; updated in place on success.
        resolver: Layer resolver for the current build context.
    """
    # Which required inputs of the engines we are about to run are missing?
    missing: set[str] = set()
    for engine_cls in included:
        probe = engine_cls(
            world_dir,
            seed,
            layer_input_dirs=layer_input_dirs,
            layer_derived_dirs=layer_derived_dirs,
        )
        missing.update(f for f in engine_cls.input_files if probe.find_input(f) is None)
    if not missing:
        return

    producers: dict[str, type[BaseEngine]] = {}
    for engine_cls in excluded:
        for out in engine_cls.output_files:
            producers.setdefault(out, engine_cls)

    for filename in sorted(missing):
        producer = producers.get(filename)
        if producer is None or producer.name not in _BOOTSTRAP_ENGINES:
            continue  # regular validation will report it with the usual error

        source = resolver.resolve_layer(producer.layer)
        if source.input_dir is None:
            continue
        output_dir = source.input_dir.parent / "derived"

        _console.print(
            f"  [yellow]{producer.layer.value}[/yellow]: derived '{filename}' missing "
            f"→ building in source context ({source.source})"
        )
        logger.info(
            "Bootstrapping %s for missing %s (source: %s, output: %s)",
            producer.name,
            filename,
            source.source,
            output_dir,
        )
        engine = producer(
            world_dir,
            seed,
            layer_input_dirs=layer_input_dirs,
            layer_derived_dirs=layer_derived_dirs,
            layer_output_dir=output_dir,
            maps_output_dir=world_dir / "maps",
        )
        result = engine.run()
        if result.success:
            # Make the freshly built derived files visible to find_input()
            # for every engine constructed later in the main loop.
            layer_derived_dirs[producer.layer.value] = output_dir
        else:
            logger.error(
                "Bootstrap of %s failed (input validation will report the "
                "original missing file): %s",
                producer.name,
                result.warnings,
            )


def _collect_dependencies(engine_name: str, sorted_engines: list[type[BaseEngine]]) -> set[str]:
    """Collect transitive dependencies for an engine."""
    by_name = {e.name: e for e in sorted_engines}
    needed: set[str] = set()

    def collect(name: str) -> None:
        if name in needed:
            return
        needed.add(name)
        engine_cls = by_name.get(name)
        if engine_cls:
            for dep in engine_cls.requires:
                collect(dep)

    collect(engine_name)
    return needed


def _outputs_exist(engine: BaseEngine) -> bool:
    """Check if all declared output files already exist.

    Uses the engine's custom outputs_exist() method if defined,
    otherwise checks output_files relative to layer_output_dir.
    """
    if hasattr(engine, "outputs_exist"):
        return bool(engine.outputs_exist())
    return all(engine.output_path(f).exists() for f in engine.output_files)


def _input_paths(engine: BaseEngine) -> list[Path]:
    """Resolve all existing input files (required + optional) to their paths."""
    paths: list[Path] = []
    for f in [*engine.input_files, *engine.optional_input_files]:
        p = engine.find_input(f)
        if p is not None:
            paths.append(p)
    return paths


def _is_dirty(engine: BaseEngine) -> bool:
    """Whether the engine should re-run because an input changed.

    mtime comparison: re-run when the newest input is newer than the oldest
    output (or when outputs are missing). Stateless and simpler than content
    hashing; the limitations (clock rollback / mtime-preserving copies can
    misjudge) are acceptable — a content-hash upgrade via ComputationManifest
    can follow if needed.
    """
    outputs = [p for p in engine.output_paths() if p.exists()]
    if not outputs:
        return True
    newest_input = max((p.stat().st_mtime for p in _input_paths(engine)), default=0.0)
    oldest_output = min(p.stat().st_mtime for p in outputs)
    return newest_input > oldest_output
