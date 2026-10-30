"""Conservative, isothermal shallow-ice redistribution on a fixed bed.

This local trial uses the existing ice inventory, zero mass balance and a
closed frame. It evolves H_t = -div(q), q = -2A/5 (rho*g)^3 H^5 |grad(s)|^2
grad(s), with s = bed + H and Glen exponent n=3. Sliding and bed evolution
are separate processes. The fixed bed is an explicit input, not inferred here.

References: Cuffey & Paterson (2010), The Physics of Glaciers, ch. 8;
Bueler (2016), Stable finite volume element schemes for the shallow-ice
approximation; PISM documentation, modeling-choices/dynamics/sia.html.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numba import njit
from scipy.ndimage import uniform_filter

from .ice_sheets import RHO_ICE_KG_M3

SECONDS_PER_YEAR = 365.25 * 86400.0
# Isothermal temperate-ice reference; observational fit, not a polar bed temperature.
TEMPERATE_RATE_FACTOR_PA3_S = 2.4e-24


def subgrid_ice_surface_level(bed_samples_m: np.ndarray, mean_ice_m: np.ndarray) -> np.ndarray:
    """Recover a cell's level surface from its bed hypsometry and mean ice.

    Samples on the last axis have equal area. Solve mean(max(s - b, 0)) = H:
    peaks above s remain exposed, while thicker ice covers the full bed.
    This geometric prolongation preserves the resolved ice volume. Dynamics
    determines the cell inventory; this closure resolves partial coverage.
    At zero inventory the level equals the lowest sampled bed elevation.
    """
    bed = np.sort(np.asarray(bed_samples_m, dtype=float), axis=-1)
    ice = np.asarray(mean_ice_m, dtype=float)
    if bed.shape[:-1] != ice.shape or bed.shape[-1] == 0 or np.any(ice < 0):
        raise ValueError("equal-area bed samples must align with nonnegative cell ice")
    count = np.arange(1, bed.shape[-1] + 1)
    cumulative = np.cumsum(bed, axis=-1)
    target = ice * bed.shape[-1]
    wet = np.maximum(np.sum(bed * count - cumulative <= target[..., None], axis=-1), 1)
    total_bed = np.take_along_axis(cumulative, (wet - 1)[..., None], axis=-1)[..., 0]
    return np.asarray((target + total_bed) / wet)


def subgrid_ice_relaxation_fraction(
    mean_ice_m: np.ndarray,
    surface_std_m: np.ndarray,
    *,
    spacing_m: float,
    elapsed_yr: float,
    gravity_m_s2: float,
) -> np.ndarray:
    """Single-mode SIA estimate of unresolved surface relaxation.

    For s = a cos(k x), the fundamental of div(C H^5 |grad(s)|^2 grad(s))
    gives da/dt = -3 C H^5 k^4 a^3 / 4. With a^2 = 2 variance, its retained
    amplitude is (1 + 3 C H^5 k^4 variance t)^(-1/2). The longest unresolved
    wavelength is the solver's Nyquist wavelength 2*spacing. This local
    closure keeps thin, slowly deforming ice close to its supplied surface;
    thick ice approaches the resolved surface. Sliding and higher modes
    need corresponding dynamics. No glacier age is inferred from this time.
    """
    coefficient = 2.0 / 5.0 * TEMPERATE_RATE_FACTOR_PA3_S * (RHO_ICE_KG_M3 * gravity_m_s2) ** 3
    response = (
        3
        * coefficient
        * np.asarray(mean_ice_m) ** 5
        * (np.pi / spacing_m) ** 4
        * np.asarray(surface_std_m) ** 2
        * elapsed_yr
        * SECONDS_PER_YEAR
    )
    return np.asarray(1 - 1 / np.sqrt(1 + response))


@dataclass(frozen=True)
class IceSurfaceBudget:
    initial_volume_m3: float
    final_volume_m3: float
    residual_m3: float
    elapsed_yr: float
    substeps: int


def source_ice_bed(
    td_surface_m: np.ndarray,
    surface_condition_m: np.ndarray,
    ice_m: np.ndarray,
    relief_std_m: np.ndarray,
    *,
    spacing_m: float,
    source_spacing_m: float,
    ice_fraction: np.ndarray | None = None,
    texture_mean_m: float | None = None,
) -> np.ndarray:
    """Construct a trial ice bed from native means and subcell relief statistics.

    The native contained-ice surface minus H supplies the loaded bed mean.
    TD supplies only a standardized texture. Its moving-window mean and RMS
    are measured at the native source spacing, then the native geological
    relief standard deviation sets its amplitude. This is a statistical bed
    prior, not an observed subglacial DEM. Interpolated native ice-presence
    fractions provide the boundary support. Dry terrain retains its TD surface.
    A supplied texture mean lets streaming chunks use one shared normalization.
    """
    td = np.asarray(td_surface_m, dtype=np.float64)
    condition = np.asarray(surface_condition_m, dtype=np.float64)
    ice = np.asarray(ice_m, dtype=np.float64)
    relief = np.asarray(relief_std_m, dtype=np.float64)
    fraction = (ice > 0).astype(float) if ice_fraction is None else np.asarray(ice_fraction)
    if (
        td.ndim != 2
        or any(a.shape != td.shape for a in (condition, ice, relief, fraction))
        or not all(np.isfinite(a).all() for a in (td, condition, ice, relief, fraction))
        or np.any(ice < 0)
        or np.any(relief < 0)
        or np.any((fraction < 0) | (fraction > 1))
        or min(spacing_m, source_spacing_m) <= 0
    ):
        raise ValueError("ice bed needs aligned finite fields and nonnegative source statistics")
    width = max(1, round(source_spacing_m / spacing_m)) | 1
    residual = td - condition
    mean = uniform_filter(residual, width, mode="reflect")
    variance = np.maximum(uniform_filter(residual**2, width, mode="reflect") - mean**2, 0)
    unit = np.divide(residual - mean, np.sqrt(variance), out=np.zeros_like(td), where=variance > 0)
    texture = unit * relief
    fraction = np.where(ice > 0, fraction, 0.0)
    if texture_mean_m is None:
        weight = float(fraction.sum())
        texture_mean_m = float(np.sum(fraction * texture) / weight) if weight else 0.0
    texture -= texture_mean_m
    return np.asarray(td - ice + fraction * (condition - td + texture))


@njit(cache=True, nogil=True)
def _redistribute(
    bed: np.ndarray,
    ice: np.ndarray,
    land: np.ndarray,
    fraction: np.ndarray,
    spacing: float,
    duration: float,
    coefficient: float,
    max_substeps: int,
) -> tuple[np.ndarray, int]:
    nr, nc = bed.shape
    h = ice.copy()
    surface = np.empty_like(h)
    gx, gy = np.empty_like(h), np.empty_like(h)
    fx = np.zeros((nr, nc - 1))
    fy = np.zeros((nr - 1, nc))
    outgoing, diffusion = np.empty_like(h), np.empty_like(h)
    time = 0.0
    steps = 0
    while time < duration:
        if steps >= max_substeps:
            raise RuntimeError("shallow-ice redistribution exceeded the substep budget")
        for i in range(nr):
            for j in range(nc):
                surface[i, j] = bed[i, j] + h[i, j] / fraction[i, j] if land[i, j] else bed[i, j]
                outgoing[i, j] = diffusion[i, j] = 0.0
        for i in range(nr):
            for j in range(nc):
                i0 = i - 1 if i > 0 and land[i - 1, j] else i
                i1 = i + 1 if i < nr - 1 and land[i + 1, j] else i
                j0 = j - 1 if j > 0 and land[i, j - 1] else j
                j1 = j + 1 if j < nc - 1 and land[i, j + 1] else j
                gx[i, j] = (
                    (surface[i, j1] - surface[i, j0]) / ((j1 - j0) * spacing) if j1 > j0 else 0
                )
                gy[i, j] = (
                    (surface[i1, j] - surface[i0, j]) / ((i1 - i0) * spacing) if i1 > i0 else 0
                )
        for i in range(nr):
            for j in range(nc - 1):
                flux, diffusivity = 0.0, 0.0
                if land[i, j] and land[i, j + 1]:
                    slope = (surface[i, j] - surface[i, j + 1]) / spacing
                    transverse = 0.5 * (gy[i, j] + gy[i, j + 1])
                    donor = (
                        h[i, j] / fraction[i, j] if slope > 0 else h[i, j + 1] / fraction[i, j + 1]
                    )
                    diffusivity = coefficient * donor**5 * (slope**2 + transverse**2)
                    flux = diffusivity * slope * min(fraction[i, j], fraction[i, j + 1])
                fx[i, j] = flux
                diffusion[i, j] += diffusivity
                diffusion[i, j + 1] += diffusivity
                outgoing[i, j] += max(flux, 0.0)
                outgoing[i, j + 1] += max(-flux, 0.0)
        for i in range(nr - 1):
            for j in range(nc):
                flux, diffusivity = 0.0, 0.0
                if land[i, j] and land[i + 1, j]:
                    slope = (surface[i, j] - surface[i + 1, j]) / spacing
                    transverse = 0.5 * (gx[i, j] + gx[i + 1, j])
                    donor = (
                        h[i, j] / fraction[i, j] if slope > 0 else h[i + 1, j] / fraction[i + 1, j]
                    )
                    diffusivity = coefficient * donor**5 * (slope**2 + transverse**2)
                    flux = diffusivity * slope * min(fraction[i, j], fraction[i + 1, j])
                fy[i, j] = flux
                diffusion[i, j] += diffusivity
                diffusion[i + 1, j] += diffusivity
                outgoing[i, j] += max(flux, 0.0)
                outgoing[i + 1, j] += max(-flux, 0.0)
        dt = duration - time
        for i in range(nr):
            for j in range(nc):
                if diffusion[i, j] > 0:
                    # Nonlinear diffusion CFL; this factor is numerical stabilization.
                    dt = min(dt, 0.1 * spacing**2 / diffusion[i, j])
                if outgoing[i, j] > 0:
                    dt = min(dt, 0.9 * h[i, j] * spacing / outgoing[i, j])
        for i in range(nr):
            for j in range(nc - 1):
                exchange = dt * fx[i, j] / spacing
                h[i, j] -= exchange
                h[i, j + 1] += exchange
        for i in range(nr - 1):
            for j in range(nc):
                exchange = dt * fy[i, j] / spacing
                h[i, j] -= exchange
                h[i + 1, j] += exchange
        time += dt
        steps += 1
    return h, steps


def redistribute_ice(
    bed_m: np.ndarray,
    ice_m: np.ndarray,
    land_mask: np.ndarray,
    *,
    spacing_m: float,
    elapsed_yr: float,
    gravity_m_s2: float,
    rate_factor_pa3_s: float = TEMPERATE_RATE_FACTOR_PA3_S,
    max_substeps: int = 500_000,
    support_fraction: np.ndarray | None = None,
) -> tuple[np.ndarray, IceSurfaceBudget]:
    """Redistribute an initial ice inventory, keeping bed and frame fixed.

    Return the final thickness and a volume budget. Ice can enter initially
    dry land; ocean faces are closed. Donor thickness at each face allows dry
    cells to receive ice without exporting a nonexistent inventory. A stable
    forward step removes at most 90% of any cell's thickness, without clipping.
    Elapsed time is physical model time, not an inferred glacier age.

    ``support_fraction`` treats partial cells by area (cut cells): ice is a
    cell-mean volume spread over the fraction f that can hold it, the bed is
    the mean over that part, and each face passes flux in proportion to the
    smaller fraction of its two cells. Full cells (f = 1) reduce to the
    standard scheme; sea portions stay closed.
    """
    bed = np.asarray(bed_m, dtype=np.float64)
    ice = np.asarray(ice_m, dtype=np.float64)
    land = np.asarray(land_mask, dtype=bool)
    fraction = (
        np.ones(bed.shape) if support_fraction is None else np.asarray(support_fraction, float)
    )
    if (
        bed.ndim != 2
        or min(bed.shape) < 2
        or ice.shape != bed.shape
        or land.shape != bed.shape
        or fraction.shape != bed.shape
        or np.any(land & ((fraction <= 0) | (fraction > 1)))
        or not np.isfinite(bed).all()
        or not np.isfinite(ice).all()
        or np.any(ice < 0)
        or np.any(ice[~land] != 0)
    ):
        raise ValueError("bed, nonnegative ice and land mask must share a finite 2D grid")
    if (
        not np.isfinite([spacing_m, elapsed_yr, gravity_m_s2, rate_factor_pa3_s]).all()
        or min(spacing_m, gravity_m_s2, rate_factor_pa3_s) <= 0
        or elapsed_yr < 0
        or max_substeps < 1
    ):
        raise ValueError("spacing, gravity, rate factor and substep budget must be positive")
    initial = float(ice.sum() * spacing_m**2)
    coefficient = 2.0 / 5.0 * rate_factor_pa3_s * (RHO_ICE_KG_M3 * gravity_m_s2) ** 3
    final, steps = _redistribute(
        bed,
        ice,
        land,
        np.where(land, fraction, 1.0),
        spacing_m,
        elapsed_yr * SECONDS_PER_YEAR,
        coefficient,
        max_substeps,
    )
    volume = float(final.sum() * spacing_m**2)
    residual = volume - initial
    if np.any(final < 0) or abs(residual) > 5e-12 * max(initial, volume, 1.0):
        raise ArithmeticError("shallow-ice redistribution failed its nonnegative volume budget")
    return final, IceSurfaceBudget(initial, volume, residual, elapsed_yr, steps)
