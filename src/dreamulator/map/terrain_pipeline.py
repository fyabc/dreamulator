"""Terrain generation pipeline orchestrator.

Runs the complete CVT terrain generation pipeline:
    1. CVT mesh generation (Fibonacci + Lloyd + SphericalVoronoi)
    2. Plate tectonics (Poisson-disc + Voronoi partition)
    3. Tectonic time evolution (Cortial et al. 2019: centroid rotation +
       subduction + collision + erosion)
    4. Boundary detection (velocity decomposition + classification)
    5. Terrain synthesis (bimodal base + boundary effects + fBm noise)
    6. Climate simulation (TODO)
    7. River generation (TODO)
    8. Erosion (TODO)
    9. Export (equirectangular raster + PNG + JSON)

See ``docs/design/terrain-pipeline.md`` for complete algorithm reference.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from rich.console import Console

from .boundary_detector import detect_boundaries
from .cvt_mesh import generate_cvt_mesh
from .export import export_equirectangular, save_outputs
from .models import CVTMesh, TectonicPlate
from .pipeline_types import TerrainPipelineConfig
from .plate_generator import generate_plates
from .terrain_synthesizer import synthesize_terrain

logger = logging.getLogger(__name__)
_console = Console(highlight=False)

# Valid stage names for partial pipeline execution
VALID_STAGES = frozenset({
    "mesh",
    "plates",
    "tectonics",
    "boundaries",
    "terrain",
    "climate",
    "rivers",
    "erosion",
    "export",
})

# Stage display names for stdout
_STAGE_NAMES: dict[str, str] = {
    "mesh":       "1/9  CVT Mesh",
    "plates":     "2/9  Plate Tectonics",
    "tectonics":  "3/9  Tectonic Evolution",
    "boundaries": "4/9  Boundary Detection",
    "terrain":    "5/9  Terrain Synthesis",
    "climate":    "6/9  Climate Simulation",
    "rivers":     "7/9  River Generation",
    "erosion":    "8/9  Erosion",
    "export":     "9/9  Export",
}


def _stage_begin(stage: str) -> None:
    """Print a user-facing stage header."""
    name = _STAGE_NAMES.get(stage, stage)
    _console.print(f"[bold bright_cyan]>>[/] [bold]{name}[/]")


def _stage_end(elapsed: float) -> None:
    """Print elapsed time for the just-completed stage."""
    if elapsed < 1.0:
        timing = f"{elapsed * 1000:.0f}ms"
    elif elapsed < 60:
        timing = f"{elapsed:.1f}s"
    else:
        mins = int(elapsed // 60)
        secs = elapsed % 60
        timing = f"{mins}m {secs:.0f}s"
    _console.print(f"  [bold green]done[/] [dim italic]({timing})[/]")


@dataclass
class TerrainPipelineResult:
    """Result of a terrain pipeline run."""

    mesh: CVTMesh | None = None
    plates: list[TectonicPlate] = field(default_factory=list)
    boundary_cell_ids: list[int] = field(default_factory=list)
    elevation_grid: np.ndarray | None = None
    stages_completed: list[str] = field(default_factory=list)
    stage_timings: dict[str, float] = field(default_factory=dict)
    elapsed_seconds: float = 0.0
    output_dir: Path | None = None


def _resolve_stages(requested: list[str] | None) -> list[str]:
    """Resolve requested stages to an ordered list.

    If ``requested`` is None, returns all stages in order.
    Otherwise validates and returns the requested stages in pipeline order.
    """
    all_stages = [
        "mesh",
        "plates",
        "tectonics",
        "boundaries",
        "terrain",
        "climate",
        "rivers",
        "erosion",
        "export",
    ]

    if requested is None:
        return all_stages

    # Validate
    for s in requested:
        if s not in VALID_STAGES:
            raise ValueError(
                f"Unknown stage '{s}'. Valid stages: {sorted(VALID_STAGES)}"
            )

    # Return in pipeline order, only including requested
    return [s for s in all_stages if s in requested]


def run_terrain_pipeline(
    config: TerrainPipelineConfig,
    output_dir: Path | None = None,
    *,
    stages: list[str] | None = None,
) -> TerrainPipelineResult:
    """Run the terrain generation pipeline.

    Args:
        config: Pipeline configuration.
        output_dir: Directory for output files. If None, no files are saved.
        stages: Optional list of stages to run. If None, runs all stages.
            Valid stages: mesh, plates, boundaries, terrain, climate, rivers,
            erosion, export.

    Returns:
        TerrainPipelineResult with generated data.
    """
    t_start = time.time()
    result = TerrainPipelineResult()

    ordered = _resolve_stages(stages)
    logger.info(
        "Starting terrain pipeline: %s (seed=%d, nodes=%d)",
        " → ".join(ordered), config.seed, config.num_nodes,
    )

    # ---- Stage 1: CVT Mesh ----
    if "mesh" in ordered:
        _stage_begin("mesh")
        t = time.time()
        result.mesh = generate_cvt_mesh(config)
        result.stages_completed.append("mesh")
        result.stage_timings["mesh"] = time.time() - t
        _stage_end(result.stage_timings["mesh"])

    if result.mesh is None:
        raise RuntimeError("CVT mesh is required for subsequent stages. Run 'mesh' stage first.")

    # ---- Stage 2: Plate Tectonics ----
    if "plates" in ordered:
        _stage_begin("plates")
        t = time.time()
        result.plates, cell_plate_map = generate_plates(result.mesh, config)
        result.stages_completed.append("plates")
        result.stage_timings["plates"] = time.time() - t
        _stage_end(result.stage_timings["plates"])
    else:
        # Reconstruct cell_plate_map from existing plate data
        cell_plate_map = {}
        for cell in result.mesh.cells:
            if cell.plate_id:
                cell_plate_map[cell.id] = cell.plate_id

    # ---- Stage 3: Tectonic Time Evolution (Cortial 2019) ----
    if "tectonics" in ordered:
        if not result.plates:
            raise RuntimeError(
                "Plates are required for tectonic evolution. "
                "Run 'plates' stage first."
            )

        _stage_begin("tectonics")
        t = time.time()
        from .tectonic_simulator import run_tectonic_evolution

        # Rich progress bar for long-running tectonic steps
        progress_cb = None
        _progress = None
        try:
            from rich.progress import Progress, BarColumn, TextColumn, TimeRemainingColumn
            _progress = Progress(
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("[dim]{task.percentage:>3.0f}%[/]"),
                TimeRemainingColumn(),
                transient=True,
            )
            task_id = _progress.add_task(
                "  Tectonic steps",
                total=config.tectonic_steps,
            )
            _progress.start()

            def _cb(step: int, _total: int) -> None:
                if _progress is not None:
                    _progress.update(task_id, completed=step)
            progress_cb = _cb
        except ImportError:
            pass

        result.plates, cell_plate_map = run_tectonic_evolution(
            result.mesh, result.plates, config,
            progress_callback=progress_cb,
        )
        if _progress is not None:
            _progress.stop()

        # Re-anchor crust to authored geography: tectonics moves plates (crust
        # sticks to cells and drifts), so continents would wander off their
        # authored anchors.  Re-stamp from the same seed-deterministic field —
        # boundary/mountain data (boundary_type, distance_to_boundary_km,
        # convergence_rate) is stored independently and is preserved.
        if config.geography is not None and config.geography.reapply_after_tectonics:
            from .geography import apply_geography_crust

            apply_geography_crust(result.mesh, config)

        result.stages_completed.append("tectonics")
        result.stage_timings["tectonics"] = time.time() - t
        _stage_end(result.stage_timings["tectonics"])

    # ---- Stage 4: Boundary Detection ----
    if "boundaries" in ordered:
        if not result.plates:
            raise RuntimeError("Plates are required for boundary detection. Run 'plates' stage first.")

        _stage_begin("boundaries")
        t = time.time()
        result.boundary_cell_ids = detect_boundaries(
            result.mesh, result.plates, cell_plate_map, config
        )
        result.stages_completed.append("boundaries")
        result.stage_timings["boundaries"] = time.time() - t
        _stage_end(result.stage_timings["boundaries"])

    # ---- Stage 5: Terrain Synthesis ----
    if "terrain" in ordered:
        if not result.plates:
            raise RuntimeError("Plates are required for terrain synthesis. Run 'plates' stage first.")

        _stage_begin("terrain")
        t = time.time()
        synthesize_terrain(result.mesh, result.plates, config)
        result.stages_completed.append("terrain")
        result.stage_timings["terrain"] = time.time() - t
        _stage_end(result.stage_timings["terrain"])

    # ---- Stage 6: Climate (TODO) ----
    if "climate" in ordered:
        _stage_begin("climate")
        try:
            from .climate_simulator import simulate_climate

            t = time.time()
            simulate_climate(result.mesh, config)
            result.stages_completed.append("climate")
            result.stage_timings["climate"] = time.time() - t
            _stage_end(result.stage_timings["climate"])
        except NotImplementedError as e:
            _console.print(f"  [dim]skipped: {type(e).__name__}[/]")
            logger.info("  skipped: %s", str(e).split("\n")[0])

    # ---- Stage 7: Rivers (TODO) ----
    if "rivers" in ordered:
        _stage_begin("rivers")
        try:
            from .river_generator import generate_rivers

            t = time.time()
            generate_rivers(result.mesh, config)
            result.stages_completed.append("rivers")
            result.stage_timings["rivers"] = time.time() - t
            _stage_end(result.stage_timings["rivers"])
        except NotImplementedError as e:
            _console.print(f"  [dim]skipped: {type(e).__name__}[/]")
            logger.info("  skipped: %s", str(e).split("\n")[0])

    # ---- Stage 8: Erosion (TODO) ----
    if "erosion" in ordered:
        _stage_begin("erosion")
        try:
            from .erosion import apply_erosion

            t = time.time()
            apply_erosion(result.mesh, config)
            result.stages_completed.append("erosion")
            result.stage_timings["erosion"] = time.time() - t
            _stage_end(result.stage_timings["erosion"])
        except NotImplementedError as e:
            _console.print(f"  [dim]skipped: {type(e).__name__}[/]")
            logger.info("  skipped: %s", str(e).split("\n")[0])

    # ---- Stage 9: Export ----
    if "export" in ordered:
        _stage_begin("export")
        t = time.time()
        result.elevation_grid = export_equirectangular(
            result.mesh,
            config.export_width,
            config.export_height,
            field="elevation",
        )

        if output_dir is not None:
            save_outputs(
                result.mesh,
                result.plates,
                result.elevation_grid,
                output_dir,
                config,
            )
            result.output_dir = output_dir

        result.stages_completed.append("export")
        result.stage_timings["export"] = time.time() - t
        _stage_end(result.stage_timings["export"])

    result.elapsed_seconds = time.time() - t_start
    if result.elapsed_seconds < 60:
        total_timing = f"{result.elapsed_seconds:.1f}s"
    else:
        mins = int(result.elapsed_seconds // 60)
        secs = result.elapsed_seconds % 60
        total_timing = f"{mins}m {secs:.0f}s"
    _console.print(
        f"[bold green]Pipeline complete[/] "
        f"({' -> '.join(result.stages_completed)}) "
        f"[dim italic](total {total_timing})[/]",
    )

    return result
