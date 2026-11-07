"""Zero-mean mesoscale relief on orogen-supported cells (terrain-morphology-gap.md §5 item 2).

The orogen profile is a smooth wedge whose top is flat at the force-balance cap, and the
texture noise has one amplitude on all land, so high plateaus and their flanks miss the
100–400 km ranges and basins of real orogens: on the 200k grid, Earth's 150 km-scale
relief above 3 km mean elevation is 250–500 m, against 40–130 m before this stage.
At grid scale Tibet's interior ranges and basins are spread over the whole plateau rather
than concentrated on its paleo-sutures (a Bangong–Nujiang or Jinsha line is no more
prominent than control lines between them), so the structure is distributed.

The stage adds ``δ = k · (h_orogen / 1 km) · f``: ``h_orogen`` is the cell's combined orogen
relief above the continental base (crustal thickening, active and old belts), and ``f`` a
seeded white-noise field band-passed by a difference of Gaussians (σ 40 km and 120 km,
wavelengths of about 100–400 km) and normalised to unit standard deviation over the
supported cells.  The field is zero-mean, so the plateau mean the cap sets stays unchanged;
the stage therefore runs after the cap.  Land cells are kept above the sea surface, so the
coastline does not move.

Epistemic class: ``k`` is an observation fit, 75 m per km of orogen relief (fit range
50–100), which brings the interior 150 km-scale relief of nacrea's two main plateaus to
260–290 m against Tibet 240 m and the Altiplano 304 m.  The band and the field's isotropy
are numerical closures; strike-aligned structure is left to the canvas stage.
"""

from __future__ import annotations

import numpy as np
from scipy.spatial import cKDTree

#: Difference-of-Gaussians band (km): the scales measured on Earth (150 km detrend,
#: 400 km mean); numerical closure.
BAND_SIGMA_KM: tuple[float, float] = (40.0, 120.0)


def mesoscale_relief_field(
    xyz: np.ndarray, support: np.ndarray, radius_km: float, seed: int
) -> np.ndarray:
    """Unit-std band-passed white noise on the supported cells, zero elsewhere.

    Args:
        xyz: Cell centres, shape ``(n, 3)``; normalised here.
        support: Boolean mask of the cells that receive the field.
        radius_km: Planet radius.
        seed: RNG seed (reproducible field).

    Returns:
        Field of shape ``(n,)`` with mean ≈ 0 and unit standard deviation on ``support``.
    """
    points = np.asarray(xyz, dtype=np.float64)
    points = points / np.linalg.norm(points, axis=1, keepdims=True)
    mask = np.asarray(support, dtype=bool)
    if mask.shape != (len(points),):
        raise ValueError("support must be one boolean per cell")
    if not np.isfinite(radius_km) or radius_km <= 0:
        raise ValueError("radius must be positive and finite")
    out = np.zeros(len(points), dtype=np.float64)
    idx = np.flatnonzero(mask)
    if len(idx) < 2:
        return out
    s1, s2 = BAND_SIGMA_KM
    white = np.random.default_rng(seed).standard_normal(len(points))
    tree = cKDTree(points)
    for i, near in zip(idx, tree.query_ball_point(points[idx], 3.0 * s2 / radius_km), strict=True):
        js = np.asarray(near, dtype=np.int64)
        d = np.arccos(np.clip(points[js] @ points[i], -1.0, 1.0)) * radius_km
        g1 = np.exp(-0.5 * (d / s1) ** 2)
        g2 = np.exp(-0.5 * (d / s2) ** 2)
        out[i] = float(g1 @ white[js]) / float(g1.sum()) - float(g2 @ white[js]) / float(g2.sum())
    values = out[idx] - out[idx].mean()
    std = float(values.std())
    out[idx] = values / std if std > 0 else 0.0
    return out


def apply_orogen_mesoscale_relief(
    elevation_m: np.ndarray,
    orogen_relief_m: np.ndarray,
    field: np.ndarray,
    k_m_per_km: float,
    sea_level_m: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Add ``k · (h_orogen / 1 km) · field`` to land cells, keeping them above the sea.

    Returns ``(elevation, delta)``; ocean cells and cells without orogen relief are unchanged.
    """
    h = np.asarray(elevation_m, dtype=np.float64)
    orogen = np.maximum(np.asarray(orogen_relief_m, dtype=np.float64), 0.0)
    f = np.asarray(field, dtype=np.float64)
    if not (h.shape == orogen.shape == f.shape):
        raise ValueError("elevation, orogen relief and field must share one shape")
    if not np.isfinite(k_m_per_km) or k_m_per_km < 0:
        raise ValueError("k must be finite and nonnegative")
    land = h > sea_level_m
    new = h.copy()
    new[land] = np.maximum(
        h[land] + k_m_per_km * orogen[land] / 1000.0 * f[land], sea_level_m + 1.0
    )
    return new, new - h
