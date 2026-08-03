"""Noise sampling benchmarks — historical hotspot #1.

Baseline for the Stage 1 Numba JIT noise kernel (perf plan §四):
scalar opensimplex.noise3 costs ~44 µs/call (~1.4M calls on gaia-m).
After the kernel lands, these benchmarks quantify the speedup.
"""

from __future__ import annotations

import numpy as np
import opensimplex
import pytest

pytestmark = pytest.mark.benchmark


def _scalar_noise(n: int, seed: int = 42) -> np.ndarray:
    """Current production pattern: per-cell scalar opensimplex calls."""
    rng = np.random.default_rng(seed)
    pts = rng.random((n, 3))
    opensimplex.seed(seed)
    out = np.empty(n, dtype=np.float64)
    for i in range(n):
        out[i] = opensimplex.noise3(float(pts[i, 0]), float(pts[i, 1]), float(pts[i, 2]))
    return out


def test_scalar_noise_50k(benchmark):
    benchmark.pedantic(lambda: _scalar_noise(50_000), rounds=3, iterations=1)
