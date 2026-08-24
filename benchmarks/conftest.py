"""Shared fixtures for performance benchmarks.

Run:  uv run pytest benchmarks -m benchmark
See docs/usage/profiling.md §6 and private/plans/perf-profiling-and-optimization.md.

Benchmarks are marked ``benchmark`` and excluded from the default test run
(pyproject addopts). Size-parametrized micro-benchmarks expose accidental
O(n²) regressions via log-log slope.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Reuse the band-mesh builder from the validation suite
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.validation.conftest import build_validation_mesh  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
NACREAESH_JSON = (
    REPO_ROOT / "data" / "worlds" / "nacrea" / "maps" / "satellite_nacrea" / "cvt_mesh.json"
)

__all__ = ["build_validation_mesh", "REPO_ROOT", "NACREAESH_JSON"]
