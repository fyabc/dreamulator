"""Noise sampling benchmarks — historical hotspot #1.

Stage 1.1 landed the Numba JIT kernel (map/noise_kernels.py):
scalar opensimplex.noise3 cost ~44 µs/call (~1.4M calls on gaia-m);
the kernel costs ~10 ns/call (~4000x). Both variants kept here as
permanent before/after records.
"""

from __future__ import annotations

import numpy as np
import opensimplex
import pytest

from dreamulator.map.noise_kernels import fbm_on_points, noise_on_points

pytestmark = pytest.mark.benchmark


def _scalar_noise(n: int, seed: int = 42) -> np.ndarray:
    """Pre-Stage-1 pattern: per-cell scalar opensimplex calls."""
    rng = np.random.default_rng(seed)
    pts = rng.random((n, 3))
    opensimplex.seed(seed)
    out = np.empty(n, dtype=np.float64)
    for i in range(n):
        out[i] = opensimplex.noise3(float(pts[i, 0]), float(pts[i, 1]), float(pts[i, 2]))
    return out


def test_scalar_noise_50k(benchmark):
    """Historical baseline (~44 µs/call) — kept for the record."""
    benchmark.pedantic(lambda: _scalar_noise(50_000), rounds=3, iterations=1)


def test_kernel_noise_100k(benchmark):
    rng = np.random.default_rng(0)
    pts = rng.random((100_000, 3))
    x, y, z = pts[:, 0], pts[:, 1], pts[:, 2]
    benchmark.pedantic(lambda: noise_on_points(x, y, z, 42), rounds=5, iterations=1)


def test_kernel_fbm_100k_6oct(benchmark):
    rng = np.random.default_rng(0)
    pts = rng.random((100_000, 3))
    x, y, z = pts[:, 0], pts[:, 1], pts[:, 2]
    benchmark.pedantic(
        lambda: fbm_on_points(x, y, z, 42, 6, lacunarity=2.0, persistence=0.5),
        rounds=5,
        iterations=1,
    )
