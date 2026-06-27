"""Engine pipeline — DAG-based dependency resolution and execution."""

from __future__ import annotations

from pathlib import Path

from dreamulator.models.layers import LAYER_ORDER, Layer, get_layer_index
from dreamulator.resolver import LayerResolver
from dreamulator.utils.logging import setup_logging

from .base import BaseEngine, EngineResult

logger = setup_logging()


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
    sorted_engines = topological_sort(engines)

    # Determine the effective start layer
    if start_layer is not None:
        if isinstance(start_layer, str):
            start_layer = Layer(start_layer)
        effective_start = start_layer
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

    results: list[EngineResult] = []
    for engine_cls in sorted_engines:
        # Determine output directory for this engine's layer
        if branch is not None:
            branch_dir = world_dir / "branches" / branch
            layer_output_dir = branch_dir / "layers" / engine_cls.layer.value / "derived"
        else:
            layer_output_dir = world_dir / "layers" / engine_cls.layer.value / "derived"

        # Ensure output directory exists
        layer_output_dir.mkdir(parents=True, exist_ok=True)

        engine = engine_cls(
            world_dir,
            seed,
            layer_input_dirs=layer_input_dirs,
            layer_derived_dirs=layer_derived_dirs,
            layer_output_dir=layer_output_dir,
        )

        # Skip if all outputs exist and force is False
        if not force and _outputs_exist(engine):
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
            "Running engine: %s v%s (layer: %s)",
            engine.name,
            engine.version,
            engine.layer.value,
        )
        result = engine.run()
        results.append(result)

        if not result.success:
            logger.error("Engine %s failed", engine.name)
            break

        logger.info("Engine %s completed successfully", engine.name)

        # Register this engine's output as a derived source for subsequent engines
        layer_derived_dirs[engine_cls.layer.value] = layer_output_dir

    return results


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
    """Check if all declared output files already exist."""
    return all(engine.output_path(f).exists() for f in engine.output_files)
