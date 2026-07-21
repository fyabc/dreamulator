"""Terrain generation pipeline orchestrator.

Runs the complete CVT terrain generation pipeline:
    1. CVT mesh generation (Fibonacci + Lloyd + SphericalVoronoi)
    2. Plate tectonics (flood-fill + Euler poles)
    3. Boundary detection (velocity decomposition + classification)
    4. Terrain synthesis (bimodal base + boundary effects + fBm noise)
    5. Climate simulation (TODO — not yet implemented)
    6. River generation (TODO — not yet implemented)
    7. Erosion (TODO — not yet implemented)
    8. Export (equirectangular raster + PNG + JSON)

See ``docs/usage/terrain-pipeline.md`` for complete algorithm reference.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .boundary_detector import detect_boundaries
from .cvt_mesh import generate_cvt_mesh
from .export import export_equirectangular, save_outputs
from .models import CVTMesh, TectonicPlate
from .pipeline_types import TerrainPipelineConfig
from .plate_generator import generate_plates
from .terrain_synthesizer import synthesize_terrain

logger = logging.getLogger(__name__)

# Valid stage names for partial pipeline execution
VALID_STAGES = frozenset({
    "mesh",
    "plates",
    "boundaries",
    "terrain",
    "climate",
    "rivers",
    "erosion",
    "export",
})


@dataclass
class TerrainPipelineResult:
    """Result of a terrain pipeline run."""

    mesh: CVTMesh | None = None
    plates: list[TectonicPlate] = field(default_factory=list)
    boundary_cell_ids: list[int] = field(default_factory=list)
    elevation_grid: np.ndarray | None = None
    stages_completed: list[str] = field(default_factory=list)
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
        " → ".join(ordered),
        config.seed,
        config.num_nodes,
    )

    # ---- Stage 1: CVT Mesh ----
    if "mesh" in ordered:
        logger.info("═══ Stage 1: CVT Mesh Generation ═══")
        t = time.time()
        result.mesh = generate_cvt_mesh(config)
        result.stages_completed.append("mesh")
        logger.info("  Mesh generation: %.1fs", time.time() - t)

    if result.mesh is None:
        raise RuntimeError("CVT mesh is required for subsequent stages. Run 'mesh' stage first.")

    # ---- Stage 2: Plate Tectonics ----
    if "plates" in ordered:
        logger.info("═══ Stage 2: Plate Tectonics ═══")
        t = time.time()
        result.plates, cell_plate_map = generate_plates(result.mesh, config)
        result.stages_completed.append("plates")
        logger.info("  Plate generation: %.1fs", time.time() - t)
    else:
        # Reconstruct cell_plate_map from existing plate data
        cell_plate_map = {}
        for cell in result.mesh.cells:
            if cell.plate_id:
                cell_plate_map[cell.id] = cell.plate_id

    # ---- Stage 3: Boundary Detection ----
    if "boundaries" in ordered:
        if not result.plates:
            raise RuntimeError("Plates are required for boundary detection. Run 'plates' stage first.")

        logger.info("═══ Stage 3: Boundary Detection ═══")
        t = time.time()
        result.boundary_cell_ids = detect_boundaries(
            result.mesh, result.plates, cell_plate_map, config
        )
        result.stages_completed.append("boundaries")
        logger.info("  Boundary detection: %.1fs", time.time() - t)

    # ---- Stage 4: Terrain Synthesis ----
    if "terrain" in ordered:
        if not result.plates:
            raise RuntimeError("Plates are required for terrain synthesis. Run 'plates' stage first.")

        logger.info("═══ Stage 4: Terrain Synthesis ═══")
        t = time.time()
        synthesize_terrain(result.mesh, result.plates, config)
        result.stages_completed.append("terrain")
        logger.info("  Terrain synthesis: %.1fs", time.time() - t)

    # ---- Stage 5: Climate (TODO) ----
    if "climate" in ordered:
        logger.info("═══ Stage 5: Climate Simulation ═══")
        try:
            from .climate_simulator import simulate_climate

            t = time.time()
            simulate_climate(result.mesh, config)
            result.stages_completed.append("climate")
            logger.info("  Climate simulation: %.1fs", time.time() - t)
        except NotImplementedError as e:
            logger.warning("  SKIPPED: %s", e)

    # ---- Stage 6: Rivers (TODO) ----
    if "rivers" in ordered:
        logger.info("═══ Stage 6: River Generation ═══")
        try:
            from .river_generator import generate_rivers

            t = time.time()
            generate_rivers(result.mesh, config)
            result.stages_completed.append("rivers")
            logger.info("  River generation: %.1fs", time.time() - t)
        except NotImplementedError as e:
            logger.warning("  SKIPPED: %s", e)

    # ---- Stage 7: Erosion (TODO) ----
    if "erosion" in ordered:
        logger.info("═══ Stage 7: Erosion ═══")
        try:
            from .erosion import apply_erosion

            t = time.time()
            apply_erosion(result.mesh, config)
            result.stages_completed.append("erosion")
            logger.info("  Erosion: %.1fs", time.time() - t)
        except NotImplementedError as e:
            logger.warning("  SKIPPED: %s", e)

    # ---- Stage 8: Export ----
    if "export" in ordered:
        logger.info("═══ Stage 8: Export ═══")
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
        logger.info("  Export: %.1fs", time.time() - t)

    result.elapsed_seconds = time.time() - t_start
    logger.info(
        "Pipeline complete: %s in %.1fs",
        " → ".join(result.stages_completed),
        result.elapsed_seconds,
    )

    return result
