"""Macro benchmark: full terrain pipeline at 4096 nodes.

Marked ``slow`` (~20 s per round) — excluded from the CI benchmark run
(``-m "benchmark and not slow"``); run locally before releases.
"""

from __future__ import annotations

import pytest

from dreamulator.map.pipeline_types import TerrainPipelineConfig
from dreamulator.map.terrain_pipeline import run_terrain_pipeline

pytestmark = [pytest.mark.benchmark, pytest.mark.slow]


def _run() -> None:
    cfg = TerrainPipelineConfig()
    cfg.num_nodes = 4096
    cfg.tectonic_steps = 0
    cfg.export_width = 1024
    cfg.export_height = 512
    run_terrain_pipeline(
        cfg,
        None,
        stages=["mesh", "plates", "boundaries", "terrain", "export"],
    )


def test_full_terrain_4096(benchmark):
    benchmark.pedantic(_run, rounds=2, iterations=1)
