"""Erosion simulation on the spherical CVT mesh.

**Status: NOT YET IMPLEMENTED**

Planned features (see ``docs/usage/terrain-pipeline.md`` §10):
    - Thermal erosion: talus angle iterative smoothing
    - Water erosion textures: flow accumulation → normal perturbation (visual)
    - Sediment transport: erosion amount → downstream deposition
    - Temperature-driven surface weathering

Note: Fine-scale erosion is intended for Gaea local refinement
(docs/usage/terrain-pipeline.md §12). This module handles global
simplified erosion only.
"""

from __future__ import annotations

from .models import CVTMesh
from .pipeline_types import TerrainPipelineConfig


def apply_erosion(mesh: CVTMesh, config: TerrainPipelineConfig) -> None:
    """Apply simplified global erosion to the CVT mesh.

    Args:
        mesh: The CVT mesh with elevation data (modified in-place).
        config: Pipeline configuration.

    Raises:
        NotImplementedError: Always — this module is not yet implemented.
    """
    raise NotImplementedError(
        "Erosion simulation is not yet implemented.\n"
        "Planned algorithm: talus angle thermal erosion + "
        "visual water erosion textures + sediment transport.\n"
        "See docs/usage/terrain-pipeline.md §10 for the complete algorithm design."
    )
