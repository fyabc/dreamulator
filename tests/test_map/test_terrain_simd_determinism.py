"""Terrain synthesis must not amplify CPU-dependent float noise into different terrain.

numpy dispatches some kernels to AVX-512 code paths when the CPU has them, which changes
results in the last bits.  The terrain stage used to draw random numbers inside loops gated by
float thresholds, so one cell crossing a threshold shifted the shared rng stream and re-rolled
the terrain downstream: the same inputs produced a different nacrea on another machine
(2026-10-15).  This test runs the pipeline in two subprocesses, one with numpy's AVX-512
dispatch disabled, and requires (almost) identical elevations.  Before the fix a 5000-node
mesh differed by more than 1 m in about 1200 cells.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

_SCRIPT = """
import sys
import numpy as np
from dreamulator.map.pipeline_types import TerrainPipelineConfig
from dreamulator.map.terrain_pipeline import run_terrain_pipeline

cfg = TerrainPipelineConfig(
    num_nodes=5000, seed=7, lloyd_iterations=3, num_plates=10, export_width=64, export_height=32
)
r = run_terrain_pipeline(cfg, stages=["mesh", "plates", "tectonics", "terrain"])
np.save(sys.argv[1], np.array([c.elevation for c in r.mesh.cells]))
"""

_DISABLE = "AVX512_SPR AVX512_ICL X86_V4 AVX512F AVX512CD AVX512_SKX AVX512_CLX AVX512_CNL"


def _has_avx512() -> bool:
    try:
        from numpy._core._multiarray_umath import __cpu_features__
    except ImportError:  # pragma: no cover - numpy layout changed
        return False
    return any(v for k, v in __cpu_features__.items() if k.startswith(("AVX512", "X86_V4")))


def _run(out: Path, disable: str | None) -> np.ndarray:
    env = dict(os.environ)
    src = str(Path(__file__).resolve().parents[2] / "src")
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    if disable:
        env["NPY_DISABLE_CPU_FEATURES"] = disable
    subprocess.run([sys.executable, "-c", _SCRIPT, str(out)], check=True, env=env)
    return np.load(out)


@pytest.mark.skipif(not _has_avx512(), reason="needs a CPU where numpy dispatches AVX-512 kernels")
def test_terrain_identical_with_and_without_avx512(tmp_path: Path) -> None:
    a = _run(tmp_path / "default.npy", None)
    b = _run(tmp_path / "no_avx512.npy", _DISABLE)
    diff = np.abs(a - b)
    # Isolated coastline cells may still flip across sea level and move by a few metres;
    # the failure mode this guards against changed over a fifth of the mesh.
    assert int((diff > 1.0).sum()) <= 5, f"{int((diff > 1.0).sum())} cells differ by > 1 m"
