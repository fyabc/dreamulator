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


#: Smoothing (km) of the orogen relief before its contour direction is taken, and the
#: radius (km) over which the gradient structure tensor is averaged, so plateau interiors
#: inherit the strike of their flanks; numerical closures.
STRIKE_SMOOTH_KM = 150.0
STRIKE_TENSOR_KM = 300.0


def orogen_strike_frame(
    xyz: np.ndarray, orogen_relief_m: np.ndarray, support: np.ndarray, radius_km: float
) -> tuple[np.ndarray, np.ndarray]:
    """Strike (unit tangent along the orogen contours) and its coherence on supported cells.

    The orogen relief is smoothed by a Gaussian of ``STRIKE_SMOOTH_KM``; each cell's gradient is
    a least-squares fit over its neighbours in the local tangent plane; the 3-D outer products
    ``g gᵀ`` are averaged with a Gaussian of ``STRIKE_TENSOR_KM`` and projected back onto the
    tangent plane. The strike is perpendicular to the dominant gradient; the coherence
    ``(λ₁ − λ₂)/(λ₁ + λ₂)`` is 0 where no direction dominates. Unsupported cells get zeros.
    """
    points = np.asarray(xyz, dtype=np.float64)
    points = points / np.linalg.norm(points, axis=1, keepdims=True)
    relief = np.maximum(np.asarray(orogen_relief_m, dtype=np.float64), 0.0)
    mask = np.asarray(support, dtype=bool)
    n = len(points)
    strike = np.zeros((n, 3))
    coherence = np.zeros(n)
    idx = np.flatnonzero(mask)
    if len(idx) < 3:
        return strike, coherence
    tree = cKDTree(points)
    # cells near the support carry the smoothed field and its gradient
    near_support = np.zeros(n, dtype=bool)
    for js in tree.query_ball_point(
        points[idx], (STRIKE_TENSOR_KM + 3 * STRIKE_SMOOTH_KM) / radius_km
    ):
        near_support[js] = True
    work = np.flatnonzero(near_support)
    smooth = np.zeros(n)
    for i, js in zip(
        work, tree.query_ball_point(points[work], 3 * STRIKE_SMOOTH_KM / radius_km), strict=True
    ):
        jj = np.asarray(js, dtype=np.int64)
        d = np.arccos(np.clip(points[jj] @ points[i], -1.0, 1.0)) * radius_km
        w = np.exp(-0.5 * (d / STRIKE_SMOOTH_KM) ** 2)
        smooth[i] = float(w @ relief[jj]) / float(w.sum())
    spacing = float(np.sqrt(4 * np.pi / n)) * radius_km
    grad = np.zeros((n, 3))
    for i, js in zip(
        work, tree.query_ball_point(points[work], 1.6 * spacing / radius_km), strict=True
    ):
        jj = np.asarray([j for j in js if j != i], dtype=np.int64)
        if len(jj) < 3:
            continue
        p = points[i]
        e = np.cross([0.0, 0.0, 1.0], p) if abs(p[2]) < 0.99 else np.cross([1.0, 0.0, 0.0], p)
        e /= np.linalg.norm(e)
        nrt = np.cross(p, e)
        dv = (points[jj] - p) * radius_km
        a = np.c_[dv @ e, dv @ nrt]
        coef, *_ = np.linalg.lstsq(a, smooth[jj] - smooth[i], rcond=None)
        grad[i] = coef[0] * e + coef[1] * nrt
    outer = grad[:, :, None] * grad[:, None, :]
    for i, js in zip(
        idx, tree.query_ball_point(points[idx], 3 * STRIKE_TENSOR_KM / radius_km), strict=True
    ):
        jj = np.asarray(js, dtype=np.int64)
        d = np.arccos(np.clip(points[jj] @ points[i], -1.0, 1.0)) * radius_km
        w = np.exp(-0.5 * (d / STRIKE_TENSOR_KM) ** 2)
        tensor = np.tensordot(w, outer[jj], axes=1)
        p = points[i]
        proj = np.eye(3) - np.outer(p, p)
        tensor = proj @ tensor @ proj
        vals, vecs = np.linalg.eigh(tensor)
        l1, l2 = vals[2], vals[1]
        if l1 <= 0:
            continue
        g_dir = vecs[:, 2]
        s_dir = np.cross(p, g_dir)
        strike[i] = s_dir / np.linalg.norm(s_dir)
        coherence[i] = float((l1 - l2) / (l1 + l2)) if l1 + l2 > 0 else 0.0
    return strike, coherence


def mesoscale_relief_field(
    xyz: np.ndarray,
    support: np.ndarray,
    radius_km: float,
    seed: int,
    *,
    strike: np.ndarray | None = None,
    coherence: np.ndarray | None = None,
    anisotropy: float = 1.0,
) -> np.ndarray:
    """Unit-std band-passed white noise on the supported cells, zero elsewhere.

    With ``strike`` (unit tangents) and ``coherence`` the band-pass kernels are elongated along
    strike: the along-strike width is ``σ · (1 + (anisotropy − 1) · coherence)`` and the
    cross-strike width ``σ``, so ranges and basins run parallel to the belt where it has a
    direction and the field stays isotropic where it has none.

    Args:
        xyz: Cell centres, shape ``(n, 3)``; normalised here.
        support: Boolean mask of the cells that receive the field.
        radius_km: Planet radius.
        seed: RNG seed (reproducible field).
        strike: Optional strike unit vectors, shape ``(n, 3)``.
        coherence: Optional strike coherence in [0, 1], shape ``(n,)``.
        anisotropy: Along/cross-strike width ratio at full coherence (>= 1).

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
    if not np.isfinite(anisotropy) or anisotropy < 1.0:
        raise ValueError("anisotropy must be finite and at least 1")
    oriented = strike is not None and coherence is not None and anisotropy > 1.0
    out = np.zeros(len(points), dtype=np.float64)
    idx = np.flatnonzero(mask)
    if len(idx) < 2:
        return out
    s1, s2 = BAND_SIGMA_KM
    white = np.random.default_rng(seed).standard_normal(len(points))
    tree = cKDTree(points)
    reach = 3.0 * s2 * (anisotropy if oriented else 1.0) / radius_km
    for i, near in zip(idx, tree.query_ball_point(points[idx], reach), strict=True):
        js = np.asarray(near, dtype=np.int64)
        if oriented:
            assert strike is not None and coherence is not None
            dv = (points[js] - points[i]) * radius_km
            along = dv @ strike[i]
            across2 = np.maximum((dv * dv).sum(axis=1) - along**2, 0.0)
            stretch = 1.0 + (anisotropy - 1.0) * float(np.clip(coherence[i], 0.0, 1.0))
            q1 = across2 / s1**2 + (along / (s1 * stretch)) ** 2
            q2 = across2 / s2**2 + (along / (s2 * stretch)) ** 2
        else:
            d = np.arccos(np.clip(points[js] @ points[i], -1.0, 1.0)) * radius_km
            q1, q2 = (d / s1) ** 2, (d / s2) ** 2
        g1 = np.exp(-0.5 * q1)
        g2 = np.exp(-0.5 * q2)
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
