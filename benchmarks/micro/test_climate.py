"""Climate simulation benchmark on a small synthetic mesh."""

from __future__ import annotations

import pytest

from benchmarks.conftest import build_validation_mesh
from dreamulator.map.climate_simulator import simulate_climate
from dreamulator.map.pipeline_types import TerrainPipelineConfig

pytestmark = pytest.mark.benchmark


def _run_once() -> None:
    mesh = build_validation_mesh(num_bands=16, cells_per_band=16)  # 256 cells
    config = TerrainPipelineConfig()
    simulate_climate(mesh, config)


def test_climate_256(benchmark):
    benchmark.pedantic(_run_once, rounds=5, iterations=1)
