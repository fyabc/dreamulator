"""River network generation — pipeline entry point.

The routing implementation (depression fill, D8, accumulation, river ids) lives
in :mod:`dreamulator.map.hydrology` so the erosion loop (§10) can reuse the pure
routing functions without importing the pipeline glue here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import CVTMesh
    from .pipeline_types import TerrainPipelineConfig


def generate_rivers(mesh: CVTMesh, config: TerrainPipelineConfig) -> None:
    """Generate river networks on the CVT mesh.

    Fills ``flow_direction`` / ``flow_accumulation`` / ``river_id`` /
    ``river_order`` on each ``VoronoiCell``. See
    ``docs/design/terrain-pipeline.md`` §9 for the algorithm design.

    Args:
        mesh: The CVT mesh with elevation data (hydrology fields modified in place).
        config: Pipeline configuration.
    """
    from .hydrology import generate_rivers as _generate

    _generate(mesh, config)
