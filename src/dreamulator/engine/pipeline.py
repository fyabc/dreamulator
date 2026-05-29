"""Engine pipeline — DAG-based dependency resolution and execution."""

from __future__ import annotations

from pathlib import Path

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
) -> list[EngineResult]:
    """Run the engine pipeline in dependency order.

    Args:
        engines: List of engine classes to run.
        world_dir: Path to the world directory.
        seed: RNG seed for reproducibility.
        force: Re-run even if outputs already exist.
        only_engine: If set, run only this engine and its dependencies.

    Returns:
        List of EngineResults from each engine run.
    """
    sorted_engines = topological_sort(engines)

    if only_engine:
        # Find the target engine and all its transitive dependencies
        needed = _collect_dependencies(only_engine, sorted_engines)
        sorted_engines = [e for e in sorted_engines if e.name in needed]

    results: list[EngineResult] = []
    for engine_cls in sorted_engines:
        engine = engine_cls(world_dir, seed)

        # Skip if all outputs exist and force is False
        if not force and _outputs_exist(engine, world_dir):
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

        logger.info("Running engine: %s v%s", engine.name, engine.version)
        result = engine.run()
        results.append(result)

        if not result.success:
            logger.error("Engine %s failed", engine.name)
            break

        logger.info("Engine %s completed successfully", engine.name)

    return results


def _collect_dependencies(
    engine_name: str, sorted_engines: list[type[BaseEngine]]
) -> set[str]:
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


def _outputs_exist(engine: BaseEngine, world_dir: Path) -> bool:
    """Check if all declared output files already exist."""
    return all((world_dir / f).exists() for f in engine.output_files)
