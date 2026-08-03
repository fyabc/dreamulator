"""CVT mesh generation benchmark (Fibonacci + jitter + Lloyd + SphericalVoronoi)."""

from __future__ import annotations

import pytest

from dreamulator.map.cvt_mesh import generate_cvt_mesh
from dreamulator.map.pipeline_types import TerrainPipelineConfig

pytestmark = pytest.mark.benchmark


def _mesh_config(num_nodes: int, lloyd_iterations: int = 3) -> TerrainPipelineConfig:
    cfg = TerrainPipelineConfig()
    cfg.num_nodes = num_nodes
    cfg.lloyd_iterations = lloyd_iterations
    return cfg


def test_cvt_mesh_4096(benchmark):
    cfg = _mesh_config(4096)
    benchmark.pedantic(lambda: generate_cvt_mesh(cfg), rounds=2, iterations=1)
