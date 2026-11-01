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
from scipy.ndimage import label, maximum_filter, uniform_filter

from .ice_sheets import RHO_ICE_KG_M3

SECONDS_PER_YEAR = 365.25 * 86400.0
# Isothermal temperate-ice reference; observational fit, not a polar bed temperature.
TEMPERATE_RATE_FACTOR_PA3_S = 2.4e-24


#: Basal shear stress of a grounded ice sheet (Pa).  The perfectly plastic
#: closure's single parameter: a sheet adjusts its surface slope so that the
#: driving stress ρ·g·h·∇s stays at this yield value, which gives the parabolic
#: margin profile below.  Observed sheets span 50–100 kPa (Nye 1951's perfectly
#: plastic sheet; Vialov 1958's profile), and 80 kPa is the mid-range value.
#: Epistemic class: approximate derivation with an observational constraint,
#: calibration domain Earth's ice sheets; it carries over to other worlds
#: through ρ·g rather than being refitted.
BASAL_SHEAR_STRESS_PA: float = 8.0e4


def plastic_margin_thickness(
    distance_m: np.ndarray | float,
    *,
    gravity_m_s2: float,
    basal_shear_stress_pa: float = BASAL_SHEAR_STRESS_PA,
) -> np.ndarray:
    """Thickness a perfectly plastic sheet sustains at a distance from its margin.

    Balancing the driving stress against a constant yield stress τ₀ integrates to
    ``h(x) = √(2·τ₀·x/(ρ·g))`` — zero at the margin, rising as the square root of
    the distance inland.  It describes ice that has reached flow equilibrium, which
    a margin does and an interior whose thickness comes from the mass balance does
    not: this profile reaches 450 m only 12 km inland and 2000 m only 240 km inland,
    so a sheet thinner than that is *everywhere* below the profile and using it as
    an unrestricted cap replaces the whole sheet's shape rather than correcting its
    edge (measured on a 630 000 km² canvas sheet: binding over 56% of the area and
    shaving 20% of the volume).  Hence :func:`margin_taper` applies it in a band.

    Args:
        distance_m: Distance from the ice margin (m); negatives clip to zero.
        gravity_m_s2: Surface gravity of the world.
        basal_shear_stress_pa: Yield stress τ₀ (see the constant above).

    Returns:
        Maximum sustainable ice thickness (m), same shape as ``distance_m``.
    """
    distance = np.maximum(np.asarray(distance_m, dtype=np.float64), 0.0)
    return np.asarray(
        np.sqrt(2.0 * basal_shear_stress_pa * distance / (RHO_ICE_KG_M3 * gravity_m_s2)),
        dtype=np.float64,
    )


def descending_margin_mask(
    thickness_m: np.ndarray, surface_elevation_m: np.ndarray, *, ice_floor_m: float = 1.0
) -> np.ndarray:
    """Ice-free pixels where the ice surface has to descend to reach the ground.

    Not every ice-free pixel beside ice is a margin.  Where a mountain rises
    through a sheet, the level-surface reconstruction already ends the ice
    correctly: thickness is ``level − bed``, so it falls to zero as the bed rises
    to meet the level, with no wall left standing and nothing to taper.  Only
    where the ground lies *below* the neighbouring ice surface — a coast, a
    lowland, a lake — must the surface come down, and only there does the
    reconstruction leave a cliff.

    The test needs no threshold, because the reconstruction itself fixes the ice
    extent by comparing bed against level: the first ice-free pixel on a nunatak's
    flank is by construction at or above the level, while a coastal one is far
    below it.  Measured on two canvas sheets, 3.5% and 9.5% of the ice sat within
    a band of an interior ice-free patch, so taking every ice-free pixel as a
    margin thinned the ice in rings around the nunataks.

    Args:
        thickness_m: Pixel ice thickness (m).
        surface_elevation_m: Pixel surface elevation (m) — bed plus ice where
            there is ice, bare ground where there is none.
        ice_floor_m: Thickness above which a pixel counts as iced.

    Returns:
        Boolean mask of the pixels a margin distance should be measured from.
    """
    thickness = np.asarray(thickness_m)
    surface = np.asarray(surface_elevation_m, dtype=np.float64)
    if thickness.shape != surface.shape:
        raise ValueError(f"shape mismatch: thickness {thickness.shape} vs surface {surface.shape}")
    icy = thickness > ice_floor_m
    iced_surface = np.where(icy, surface, -np.inf)
    neighbouring_ice = maximum_filter(iced_surface, size=3, mode="nearest")
    return np.asarray(~icy & (surface < neighbouring_ice), dtype=bool)


def enclosed_ice_free_mask(icy: np.ndarray) -> np.ndarray:
    """Ice-free pixels in a region the ice encloses, which is not a margin either.

    A sheet does not end at a mountain it surrounds or at a hollow inside it: it
    flows around the one and fills the other, so neither is an edge where the
    plastic profile applies.  Treating them as margins carves a band into the
    sheet around every interior patch — measured on one canvas, a lake ringed by
    3.7 km of ice lost up to 3689 m in a twelve-kilometre crater, which is a worse
    artefact than the cliff it replaced.  (That cliff is itself a defect of the
    upstream ice-free lake, not something the taper should paper over.)

    An enclosed region is one whose ice-free component does not reach the array
    border.  Passed a whole-canvas mask, that border lies outside the data, so the
    sea and every coastal inlet connected to it count as exterior and keep their
    margins, while a nunatak or an interior lake does not.

    Args:
        icy: Boolean mask of pixels holding ice, covering a whole canvas.

    Returns:
        Boolean mask of the ice-free pixels that are enclosed by ice.
    """
    icy = np.asarray(icy, dtype=bool)
    if icy.ndim != 2:
        raise ValueError(f"icy must be a 2-D canvas mask, got {icy.ndim} dimensions")
    labels, count = label(~icy)
    if count == 0:
        return np.zeros(icy.shape, dtype=bool)
    outside = np.unique(np.concatenate([labels[0, :], labels[-1, :], labels[:, 0], labels[:, -1]]))
    return np.asarray((labels > 0) & ~np.isin(labels, outside), dtype=bool)


#: Width of the band in which the plastic margin profile is trusted (m).  Inside
#: a band this wide the ice has had time to reach flow equilibrium, so the profile
#: applies; beyond it the thickness is set by the mass balance and the profile is
#: the wrong statement (see :func:`plastic_margin_thickness`).  The value is the
#: distance at which the profile reaches the measured thickness of the outermost
#: pixel ring, ``L = ρ·g·h̄²/(2·τ₀)`` with h̄ = 451 m, so the band-mean effective
#: yield stress equals τ₀ instead of exceeding it — 5 km would imply 187 kPa,
#: outside the observed 50–100 kPa range.  Epistemic class: numerical shape
#: closure with a physical consistency anchor, calibration domain grounded
#: continental ice at a 90 m pixel.
MARGIN_BAND_LIMIT_M: float = 12.0e3


def margin_taper(
    thickness_m: np.ndarray,
    margin_distance_m: np.ndarray,
    *,
    gravity_m_s2: float,
    band_limit_m: float = MARGIN_BAND_LIMIT_M,
    basal_shear_stress_pa: float = BASAL_SHEAR_STRESS_PA,
) -> np.ndarray:
    """Bring a reconstructed thickness field down to the bed at the ice margin.

    The reconstruction gives each solver cell's pixels a shared level surface,
    which is right inside a sheet and wrong at its edge, where it leaves a wall of
    ice standing over bare ground — measured at 451 m mean and 1049 m at the 95th
    percentile along one canvas's margin, where real grounded cliffs are tens of
    metres.  This replaces that wall with

        h ← min(h, max(plastic(d), h·√(min(d/L, 1)))) ,

    whose two branches need no switch.  For ice thinner than
    ``√(2·τ₀·L/(ρ·g))`` the first branch wins and the result *is* the plastic
    profile, since ``h·√(d/L)`` with ``L = ρ·g·h²/(2·τ₀)`` cancels h exactly.  For
    thicker ice the second branch pins the taper to a band of width ``L``, which is
    what keeps the profile from reshaping an interior it does not describe: beyond
    the band the expression reduces to ``min(h, h) = h``, so interior pixels come
    out bit-identical rather than merely close.

    Volume is not conserved — the taper removes 1–5% of a sheet, which leaves at
    the margin, where ice calves and ablates.  Report it as an export; it is a
    one-off shape adjustment, not a calibrated calving flux.

    Args:
        thickness_m: Reconstructed pixel ice thickness (m).
        margin_distance_m: Distance from each pixel to the nearest ice-free pixel
            (m), measured at the same resolution as ``thickness_m``.
        gravity_m_s2: Surface gravity of the world.
        band_limit_m: Band width L (see :data:`MARGIN_BAND_LIMIT_M`).
        basal_shear_stress_pa: Yield stress τ₀.

    Returns:
        Tapered thickness (m), never above the input, same shape.
    """
    if band_limit_m <= 0.0:
        raise ValueError("band_limit_m must be positive")
    thickness = np.asarray(thickness_m, dtype=np.float64)
    distance = np.maximum(np.asarray(margin_distance_m, dtype=np.float64), 0.0)
    if thickness.shape != distance.shape:
        raise ValueError(
            f"shape mismatch: thickness {thickness.shape} vs distance {distance.shape}"
        )
    plastic = plastic_margin_thickness(
        distance, gravity_m_s2=gravity_m_s2, basal_shear_stress_pa=basal_shear_stress_pa
    )
    banded = thickness * np.sqrt(np.minimum(distance / band_limit_m, 1.0))
    return np.asarray(np.minimum(thickness, np.maximum(plastic, banded)), dtype=np.float64)


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
