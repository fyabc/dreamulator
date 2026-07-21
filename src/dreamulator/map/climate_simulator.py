"""Climate simulation on the spherical CVT mesh.

**Status: NOT YET IMPLEMENTED**

Planned features (see ``docs/usage/terrain-pipeline.md`` §8):
    - Temperature: solar radiation + latitude + altitude correction
    - Wind field: geostrophic wind approximation (Gleba-style)
    - Precipitation: BFS moisture transport + orographic rainfall
    - Ocean currents: surface current advection (simplified)
    - Köppen classification: annual mean temperature + precipitation → climate type

These will fill the following fields on each VoronoiCell:
    - temperature_C (float)
    - precipitation_mm (float)
    - koppen_class (str)
"""

from __future__ import annotations

from .models import CVTMesh
from .pipeline_types import TerrainPipelineConfig


def simulate_climate(mesh: CVTMesh, config: TerrainPipelineConfig) -> None:
    """Run climate simulation on the CVT mesh.

    Args:
        mesh: The CVT mesh with elevation data (modified in-place).
        config: Pipeline configuration.

    Raises:
        NotImplementedError: Always — this module is not yet implemented.
    """
    raise NotImplementedError(
        "Climate simulation is not yet implemented.\n"
        "Planned algorithm: geostrophic wind approximation + BFS moisture transport "
        "+ orographic rainfall + Köppen classification.\n"
        "See docs/usage/terrain-pipeline.md §8 for the complete algorithm design."
    )
