"""Numba-JIT noise kernels (Stage 1.1).

Replaces the per-cell scalar ``opensimplex.noise3`` calls (~44 µs each,
~1.4M of them on a gaia-m build) with compiled 3D Perlin gradient noise
(~0.1 µs each). The noise field is statistically similar to OpenSimplex
(smooth, zero-mean, fractal via fBm composition) but **not bit-identical**
— swapping the backend changes terrain detail on rebuild (documented,
same treatment as the crc32 determinism fix).

Determinism: every point is evaluated independently, so ``parallel=True``
never reorders results; permutation tables derive from explicit seeds via
``numpy.random.default_rng`` (tables cached per seed).
"""

from __future__ import annotations

import numpy as np
from numba import njit, prange

# 12 gradient directions (cube edges) — classic Perlin 3D.
_GRADS = np.array(
    [
        [1, 1, 0],
        [-1, 1, 0],
        [1, -1, 0],
        [-1, -1, 0],
        [1, 0, 1],
        [-1, 0, 1],
        [1, 0, -1],
        [-1, 0, -1],
        [0, 1, 1],
        [0, -1, 1],
        [0, 1, -1],
        [0, -1, -1],
    ],
    dtype=np.float64,
)

_perm_cache: dict[int, np.ndarray] = {}


def _get_perm(seed: int) -> np.ndarray:
    """Cached 512-entry permutation table for *seed*."""
    key = int(seed) & 0x7FFFFFFF
    table = _perm_cache.get(key)
    if table is None:
        rng = np.random.default_rng(key)
        p = rng.permutation(256).astype(np.int64)
        table = np.ascontiguousarray(np.concatenate((p, p)))
        _perm_cache[key] = table
    return table


@njit(cache=True)
def _fade(t: float) -> float:
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


@njit(cache=True)
def _lerp(a: float, b: float, t: float) -> float:
    return a + t * (b - a)


@njit(cache=True)
def _grad(h: int, x: float, y: float, z: float) -> float:
    g = _GRADS[h & 11]
    return g[0] * x + g[1] * y + g[2] * z


@njit(cache=True)
def perlin3(x: float, y: float, z: float, perm: np.ndarray) -> float:
    """Single 3D Perlin gradient-noise sample, ≈ [-1, 1]."""
    fx = np.floor(x)
    fy = np.floor(y)
    fz = np.floor(z)
    xi = int(fx) & 255
    yi = int(fy) & 255
    zi = int(fz) & 255
    xf = x - fx
    yf = y - fy
    zf = z - fz
    u = _fade(xf)
    v = _fade(yf)
    w = _fade(zf)

    aaa = perm[perm[perm[xi] + yi] + zi]
    aba = perm[perm[perm[xi] + yi + 1] + zi]
    aab = perm[perm[perm[xi] + yi] + zi + 1]
    abb = perm[perm[perm[xi] + yi + 1] + zi + 1]
    baa = perm[perm[perm[xi + 1] + yi] + zi]
    bba = perm[perm[perm[xi + 1] + yi + 1] + zi]
    bab = perm[perm[perm[xi + 1] + yi] + zi + 1]
    bbb = perm[perm[perm[xi + 1] + yi + 1] + zi + 1]

    x1 = _lerp(_grad(aaa, xf, yf, zf), _grad(baa, xf - 1.0, yf, zf), u)
    x2 = _lerp(_grad(aba, xf, yf - 1.0, zf), _grad(bba, xf - 1.0, yf - 1.0, zf), u)
    y1 = _lerp(x1, x2, v)
    x1 = _lerp(_grad(aab, xf, yf, zf - 1.0), _grad(bab, xf - 1.0, yf, zf - 1.0), u)
    x2 = _lerp(_grad(abb, xf, yf - 1.0, zf - 1.0), _grad(bbb, xf - 1.0, yf - 1.0, zf - 1.0), u)
    y2 = _lerp(x1, x2, v)
    return _lerp(y1, y2, w)


@njit(cache=True, parallel=True, fastmath=True)
def _noise_points(xs: np.ndarray, ys: np.ndarray, zs: np.ndarray, perm: np.ndarray) -> np.ndarray:
    n = len(xs)
    out = np.empty(n, dtype=np.float64)
    for i in prange(n):
        out[i] = perlin3(xs[i], ys[i], zs[i], perm)
    return out


@njit(cache=True, parallel=True, fastmath=True)
def _fbm_points(
    xs: np.ndarray,
    ys: np.ndarray,
    zs: np.ndarray,
    perm: np.ndarray,
    octaves: int,
    lacunarity: float,
    persistence: float,
    base_freq: float,
) -> np.ndarray:
    n = len(xs)
    out = np.empty(n, dtype=np.float64)
    for i in prange(n):
        total = 0.0
        norm = 0.0
        amp = 1.0
        freq = base_freq
        for _o in range(octaves):
            total += amp * perlin3(xs[i] * freq, ys[i] * freq, zs[i] * freq, perm)
            norm += amp
            amp *= persistence
            freq *= lacunarity
        out[i] = total / norm
    return out


def noise_on_points(x: np.ndarray, y: np.ndarray, z: np.ndarray, seed: int) -> np.ndarray:
    """Single-octave noise at scattered 3D points, ≈ [-1, 1]."""
    return _noise_points(
        np.ascontiguousarray(x, dtype=np.float64),
        np.ascontiguousarray(y, dtype=np.float64),
        np.ascontiguousarray(z, dtype=np.float64),
        _get_perm(seed),
    )


def fbm_on_points(
    x: np.ndarray,
    y: np.ndarray,
    z: np.ndarray,
    seed: int,
    octaves: int,
    lacunarity: float = 2.0,
    persistence: float = 0.5,
    base_freq: float = 1.0,
) -> np.ndarray:
    """Normalized fBm at scattered 3D points, ≈ [-1, 1]."""
    return _fbm_points(
        np.ascontiguousarray(x, dtype=np.float64),
        np.ascontiguousarray(y, dtype=np.float64),
        np.ascontiguousarray(z, dtype=np.float64),
        _get_perm(seed),
        int(octaves),
        float(lacunarity),
        float(persistence),
        float(base_freq),
    )
