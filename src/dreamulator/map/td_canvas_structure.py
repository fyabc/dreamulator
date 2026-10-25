"""td_canvas_structure — zero-mean tectonic structure for the TD height conditioning.

Design: ``docs/design/proposals/canvas-conditioning-structure.md`` §4 step 2.  The mesh
stores each cell's mean elevation plus its sub-grid relief ``relief_std_m`` (μ); the plain
conditioning carries only the mean, so TD sees smooth tents and plateaus.  This module adds the
part of μ that lives at the conditioning scale back in, as an oriented pattern, while keeping
every mesh cell's mean elevation (the canon) unchanged:

* **Amplitude.**  The pattern's standard deviation is ``SCALE_FRACTION`` × μ: on Earth
  (Copernicus GLO-90, 107 mountain boxes of 54 km) the 23 km low-pass carries a median 0.52 of
  the within-box height deviation (quartiles 0.38–0.63) — observation fit.
* **Orientation.**  Transverse drainage: the wave vector runs along strike, i.e. along the
  contours of the smoothed cell-mean surface, so valleys and spurs run down the flanks.
* **Wavelength.**  Hovius (1996): linear mountain belts have main outlets spaced at about half
  the belt half-width (half-width / spacing = 1.91–2.23).  The half-width is the largest
  distance to the belt edge (μ < ``BELT_MU_M``) within ``HALF_WIDTH_SEARCH_KM``; the
  wavelength is clipped to what TD keeps at the 23 km conditioning scale (``WAVELENGTH_KM``).
* **Pattern.**  Steerable band-pass noise: white noise filtered in the Fourier domain into
  orientation and wavelength bins, normalised, and blended per pixel by the local orientation
  and wavelength — a seeded, deterministic oriented random field (no global phase field needed
  on curved belts).
* **Conservation.**  The per-cell mean of the pattern is removed with a smooth correction
  (cell residuals spread by a Gaussian of one cell spacing, iterated), so the cell means are
  kept to within ``CONSERVE_TOL`` of μ without imprinting cell outlines.

Pure functions on the canvas's ``OVERSAMPLE``-times finer grid; no IO.
"""

from __future__ import annotations

import hashlib
import math

import numpy as np

from . import td_canvas as tc

#: Share of the within-cell deviation carried by >= 23 km scales (Earth, observation fit).
SCALE_FRACTION = 0.52
#: Hovius (1996) half-width / outlet spacing (observation fit, range 1.91–2.23).
HOVIUS_RATIO = 2.07
#: Belt edge: sub-grid relief below this counts as outside a mountain belt (m).
BELT_MU_M = 150.0
#: Search radius for the belt half-width (km).
HALF_WIDTH_SEARCH_KM = 400.0
#: Wavelength range (km): below ~70 km TD keeps little of a 23 km-scale pattern (step 1);
#: above ~250 km the pattern is the belt itself.
WAVELENGTH_KM = (69.0, 250.0)
#: Orientation smoothing of the cell-mean surface (km) and orientation/wavelength bins.
ORIENT_SMOOTH_KM = 60.0
N_ORIENT = 12
N_WAVELENGTH = 4
#: Angular half-width (deg) and log-wavelength half-width of each Fourier bin.
ORIENT_SPREAD_DEG = 12.0
LOG_WL_SPREAD = 0.25
#: Conservation: iterations of the smooth per-cell correction and the target residual (× μ).
CONSERVE_ITER = 16
CONSERVE_TOL = 0.05


def _seed(canvas_id: str) -> int:
    return int.from_bytes(
        hashlib.sha256(f"td-structure:{canvas_id}".encode()).digest()[:8], "little"
    )


def _bank(shape: tuple[int, int], px_km: float, rng: np.random.Generator) -> np.ndarray:
    """Unit-std oriented band-pass noise fields, shape (N_ORIENT, N_WAVELENGTH, ny, nx).

    Bin (a, w) passes wave vectors at angle a·π/N_ORIENT (from the +x axis, modulo π) and
    wavelength WAVELENGTH_KM geometrically spaced; one white-noise draw feeds every bin.
    """
    ny, nx = shape
    white = np.fft.rfft2(rng.standard_normal(shape))
    ky = np.fft.fftfreq(ny, d=px_km)[:, None]
    kx = np.fft.rfftfreq(nx, d=px_km)[None, :]
    k = np.hypot(kx, ky)
    ang = np.arctan2(ky, kx)  # wave-vector angle
    lo, hi = WAVELENGTH_KM
    wls = np.geomspace(lo, hi, N_WAVELENGTH)
    out = np.empty((N_ORIENT, N_WAVELENGTH, ny, nx), np.float32)
    sig_a = math.radians(ORIENT_SPREAD_DEG)
    with np.errstate(divide="ignore"):
        logk = np.log(np.where(k > 0, k, 1e-12))
    for a in range(N_ORIENT):
        a0 = a * math.pi / N_ORIENT
        da = np.angle(np.exp(2j * (ang - a0))) / 2  # signed distance modulo π
        wa = np.exp(-0.5 * (da / sig_a) ** 2)
        for w, wl in enumerate(wls):
            wk = np.exp(-0.5 * ((logk - math.log(1.0 / wl)) / LOG_WL_SPREAD) ** 2)
            f = np.fft.irfft2(white * wa * wk, s=shape)
            out[a, w] = f / max(float(f.std()), 1e-12)
    return out


def _blend(bank: np.ndarray, theta: np.ndarray, wl_km: np.ndarray) -> np.ndarray:
    """Per-pixel blend of the bank at wave-vector angle ``theta`` (rad) and wavelength (km)."""
    fa = (np.mod(theta, math.pi) / math.pi) * N_ORIENT
    a0 = np.floor(fa).astype(int) % N_ORIENT
    a1 = (a0 + 1) % N_ORIENT
    ta = fa - np.floor(fa)
    lo, hi = WAVELENGTH_KM
    fw = np.log(np.clip(wl_km, lo, hi) / lo) / math.log(hi / lo) * (N_WAVELENGTH - 1)
    w0 = np.clip(np.floor(fw).astype(int), 0, N_WAVELENGTH - 2)
    tw = fw - w0
    yy, xx = np.indices(theta.shape)
    out = np.zeros(theta.shape)
    for ai, aw in ((a0, 1 - ta), (a1, ta)):
        for wi, ww in ((w0, 1 - tw), (w0 + 1, tw)):
            out += aw * ww * bank[ai, wi, yy, xx]
    # bilinear mixing of independent-ish fields lowers the variance; restore unit std locally
    norm = np.sqrt((1 - ta) ** 2 + ta**2) * np.sqrt((1 - tw) ** 2 + tw**2)
    return np.asarray(out / np.maximum(norm, 1e-6))


def structure_anomaly(
    geom: tc.CanvasGeometry,
    canvas_id: str,
    cell_xyz: np.ndarray,
    elevation_m: np.ndarray,
    relief_std_m: np.ndarray,
    *,
    oversample: int = tc.OVERSAMPLE,
) -> tuple[np.ndarray, dict[str, float]]:
    """Height anomaly (m) on the coarse grid (ncell, ncell), zero-mean per mesh cell, and stats.

    ``relief_std_m`` is NaN or 0 off land / on flat land (no structure there).
    """
    from scipy import ndimage as ndi
    from scipy.spatial import cKDTree

    n = geom.ncell * oversample
    px_km = tc.TD_COARSE_KM / oversample
    la, lo = geom.coarse_centres_latlon(oversample)
    _, idx = cKDTree(cell_xyz).query(tc.unit_vectors(la, lo).reshape(-1, 3))
    idx = idx.reshape(n, n)
    h = np.asarray(elevation_m, np.float64)[idx]
    mu = np.nan_to_num(np.asarray(relief_std_m, np.float64)[idx], nan=0.0)
    land = h > 0
    mu = np.where(land, mu, 0.0)

    # orientation: wave vector along the contours of the smoothed cell-mean surface
    hs = ndi.gaussian_filter(np.where(land, h, 0.0), ORIENT_SMOOTH_KM / px_km)
    gy, gx = np.gradient(hs)
    # structure tensor of the gradient, averaged, gives a stable axis on noisy flanks
    s = ORIENT_SMOOTH_KM / px_km / 2
    jxx, jyy, jxy = (ndi.gaussian_filter(a, s) for a in (gx * gx, gy * gy, gx * gy))
    grad_axis = 0.5 * np.arctan2(2 * jxy, jxx - jyy)  # dominant gradient direction
    theta = grad_axis + math.pi / 2  # rows run south, so this is the contour direction

    # belt half-width and Hovius wavelength
    belt = mu >= BELT_MU_M
    dist = ndi.distance_transform_edt(belt) * px_km
    half_width = ndi.maximum_filter(dist, size=int(2 * HALF_WIDTH_SEARCH_KM / px_km) | 1)
    wl = np.clip(half_width / HOVIUS_RATIO, *WAVELENGTH_KM)

    rng = np.random.default_rng(_seed(canvas_id))
    noise = _blend(_bank((n, n), px_km, rng), theta, wl)
    anomaly = SCALE_FRACTION * mu * noise
    # keep land as land: the pattern may not cut a lowland below sea level
    anomaly = np.where(land, np.maximum(anomaly, 1.0 - h), 0.0)

    # conservation: remove each mesh cell's mean with a smooth correction
    cells, inv = np.unique(idx, return_inverse=True)
    inv = inv.reshape(n, n)
    count = np.bincount(inv.ravel(), minlength=len(cells))
    mu_c = np.bincount(inv.ravel(), weights=mu.ravel(), minlength=len(cells)) / count
    spacing_px = max(1.0, math.sqrt(count.mean()))
    for _ in range(CONSERVE_ITER):
        resid = np.bincount(inv.ravel(), weights=anomaly.ravel(), minlength=len(cells)) / count
        corr = ndi.gaussian_filter(resid[inv], spacing_px / 3)
        anomaly = np.where(land, anomaly - corr, 0.0)
    # the correction may push a few lowland pixels back below sea level; keep land as land
    anomaly = np.where(land, np.maximum(anomaly, 1.0 - h), 0.0)
    resid = np.bincount(inv.ravel(), weights=anomaly.ravel(), minlength=len(cells)) / count
    hot = mu_c > BELT_MU_M
    stats = {
        "resid_over_mu_p95": float(np.percentile(np.abs(resid[hot]) / mu_c[hot], 95))
        if hot.any()
        else 0.0,
        "anomaly_std_land_m": float(anomaly[land].std()) if land.any() else 0.0,
        "wavelength_km_median_belt": float(np.median(wl[belt])) if belt.any() else 0.0,
    }
    coarse = anomaly.reshape(geom.ncell, oversample, geom.ncell, oversample).mean(axis=(1, 3))
    return np.asarray(coarse), stats
