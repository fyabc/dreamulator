"""River network generation via graph-based flow accumulation.

**Status: NOT YET IMPLEMENTED**

Planned features (see ``docs/usage/terrain-pipeline.md`` §9):
    - Flow direction: steepest descent on CVT adjacency graph
    - Flow accumulation: topological sort + upstream area accumulation
    - River thresholding: cells with accumulation > threshold → river
    - Endorheic basin detection: closed drainage basins (Gleba-style)
    - River width/flow mapping

These will fill the following fields on each VoronoiCell:
    - flow_accumulation (float)
    - river_id (str | None)
"""

from __future__ import annotations

from .models import CVTMesh
from .pipeline_types import TerrainPipelineConfig


def generate_rivers(mesh: CVTMesh, config: TerrainPipelineConfig) -> None:
    """Generate river networks on the CVT mesh.

    Args:
        mesh: The CVT mesh with elevation data (modified in-place).
        config: Pipeline configuration.

    Raises:
        NotImplementedError: Always — this module is not yet implemented.
    """
    raise NotImplementedError(
        "River generation is not yet implemented.\n"
        "Planned algorithm: topological sort on CVT adjacency graph + "
        "steepest-descent flow direction + flow accumulation + "
        "endorheic basin detection.\n"
        "See docs/usage/terrain-pipeline.md §9 for the complete algorithm design."
    )
