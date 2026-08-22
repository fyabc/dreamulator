"""Reproducibility regression: terrain must not depend on PYTHONHASHSEED.

Historical bug (fixed 2026-08): ``terrain_synthesizer`` derived per-plate
belt noise seeds from the built-in ``hash(pid)``; string hashing is salted
per process, so every build produced slightly different terrain. The fix
uses ``zlib.crc32``. This test runs the terrain pipeline in two subprocesses
with different hash seeds and requires identical output.

Marked ``slow`` (~40 s): excluded from the default suite via pyproject
``addopts``; run explicitly with ``uv run pytest -m slow``.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.slow

_DRIVER = r"""
import hashlib
from dreamulator.map.pipeline_types import TerrainPipelineConfig
from dreamulator.map.terrain_pipeline import run_terrain_pipeline

cfg = TerrainPipelineConfig()
cfg.num_nodes = 4096
cfg.num_plates = 15
cfg.lloyd_iterations = 3
cfg.tectonic_steps = 0
res = run_terrain_pipeline(cfg, None, stages=["mesh", "plates", "boundaries", "terrain"])
cells = res.mesh.cells
crust = "".join((c.crust_type or "?")[0] for c in cells)
land = "".join((c.landform or "-")[:1] for c in cells)
elev = sum(c.elevation for c in cells)
print(hashlib.md5(crust.encode()).hexdigest())
print(hashlib.md5(land.encode()).hexdigest())
print(repr(elev))
"""


def _run_driver(hash_seed: str) -> str:
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = hash_seed
    proc = subprocess.run(
        [sys.executable, "-c", _DRIVER],
        capture_output=True,
        text=True,
        env=env,
        timeout=600,
        check=True,
    )
    # The driver prints its three fingerprints last (pipeline logs precede).
    return "\n".join(proc.stdout.strip().splitlines()[-3:])


def test_terrain_reproducible_across_hash_seeds():
    out_a = _run_driver("1")
    out_b = _run_driver("7")
    assert out_a == out_b, (
        "Terrain output varies with PYTHONHASHSEED — a process-salted "
        f"hash() is leaking into deterministic state:\n{out_a}\n---\n{out_b}"
    )
