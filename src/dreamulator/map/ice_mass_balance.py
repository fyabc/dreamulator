"""Climate-driven snow accumulation and degree-day ablation on a fixed surface.

The Gaussian positive-temperature expectation follows Calov & Greve (2005).
Temperature variability is an explicit climate input. Melt factors are the
EISMINT/PISM observational reference, expressed in liquid-water millimetres.
Monthly precipitation uses the existing 365.25-day reference-year convention.
Retained annual snow is reported as ice-equivalent storage, without a firn
density or ice-age inference. Meltwater leaves the local storage as runoff.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.special import ndtr

from .ice_sheets import RHO_ICE_KG_M3

REFERENCE_MONTH_DAYS = 365.25 / 12.0
SNOW_MELT_MM_PER_K_DAY = 3.0
ICE_MELT_MM_PER_K_DAY = 8.0
ICE_WATER_MM_PER_M = RHO_ICE_KG_M3


def annual_snow_storage_and_ice_melt(
    snowfall_monthly_mm: np.ndarray, positive_degree_days: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Return year-end snow and available bare-ice melt, in ice metres.

    Snow is accumulated and melted in the same monthly order as
    annual_ice_balance. Bare-ice melt is a potential, before limiting it to
    the available ice. Both use the existing degree-day factors.
    """
    snow = np.zeros_like(snowfall_monthly_mm[0], dtype=float)
    ice_melt = np.zeros_like(snow)
    for incoming, pdd in zip(snowfall_monthly_mm, positive_degree_days, strict=True):
        snow += incoming
        melt = np.minimum(snow, pdd * SNOW_MELT_MM_PER_K_DAY)
        snow -= melt
        ice_melt += np.maximum(pdd - melt / SNOW_MELT_MM_PER_K_DAY, 0)
    return snow / ICE_WATER_MM_PER_M, ice_melt * ICE_MELT_MM_PER_K_DAY / ICE_WATER_MM_PER_M


def fixed_climate_ice_minimum(
    initial_ice_m: np.ndarray, annual_snow_m: np.ndarray, annual_ice_melt_m: np.ndarray, years: int
) -> np.ndarray:
    """Annual minimum bare ice after repeating a fixed reference climate.

    The annual recurrence is H_next = max(H - D, 0) + G, where G is retained
    year-end snow and D is bare-ice melt potential. Its closed form avoids
    repeating identical monthly forcing. The last year's G remains separate
    from the exported minimum ice inventory. Surface-height feedback and
    firn evolution require time-dependent forcing instead of this closure.
    """
    if years < 1:
        raise ValueError("fixed climate response needs at least one year")
    return np.asarray(
        np.maximum(
            np.maximum(initial_ice_m - annual_ice_melt_m, 0)
            + (years - 1) * (annual_snow_m - annual_ice_melt_m),
            0,
        )
    )


@dataclass(frozen=True)
class IceMassBalance:
    ice_equivalent_m: np.ndarray
    snowfall_mm: np.ndarray
    snow_melt_mm: np.ndarray
    ice_melt_mm: np.ndarray
    residual_mm: np.ndarray


def monthly_snow_and_pdd(
    temperature_c: np.ndarray,
    precipitation_mm: np.ndarray,
    temperature_std_c: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Return snowfall water equivalent and positive degree days, month first.

    A normally distributed temperature anomaly gives the expected temperature
    above freezing and the fraction below freezing. The latter partitions the
    supplied precipitation, with snowfall plus rainfall equal to its input.
    This phase approximation assumes precipitation samples the temperature
    distribution uniformly; native GCM snowfall provides a separate check.
    """
    t, p = np.asarray(temperature_c, dtype=float), np.asarray(precipitation_mm, dtype=float)
    sd = np.broadcast_to(np.asarray(temperature_std_c, dtype=float), t.shape)
    if (
        t.shape != p.shape
        or t.shape[0] != 12
        or not all(np.isfinite(a).all() for a in (t, p, sd))
        or np.any(p < 0)
        or np.any(sd < 0)
    ):
        raise ValueError("snow balance needs twelve finite months and nonnegative rain/variability")
    z = np.divide(t, sd, out=np.zeros_like(t), where=sd > 0)
    positive = sd * np.exp(-0.5 * z**2) / np.sqrt(2 * np.pi) + t * ndtr(z)
    positive = np.where(sd > 0, np.maximum(positive, 0), np.maximum(t, 0))
    snow_fraction = np.where(sd > 0, ndtr(-z), t <= 0)
    return p * snow_fraction, positive * REFERENCE_MONTH_DAYS


def annual_ice_balance(
    ice_equivalent_m: np.ndarray,
    snowfall_monthly_mm: np.ndarray,
    positive_degree_days: np.ndarray,
    *,
    snow_factor_mm_per_k_day: float = SNOW_MELT_MM_PER_K_DAY,
    ice_factor_mm_per_k_day: float = ICE_MELT_MM_PER_K_DAY,
) -> IceMassBalance:
    """Apply one reference year, melting seasonal snow before exposed ice.

    Ablation is limited by available water-equivalent storage. Remaining melt
    capacity is retained in the degree-day accounting, not turned into a
    negative thickness. Snow remaining after the twelve-month cycle enters
    ice-equivalent storage. Rainfall is separate from this snow/ice budget.
    """
    initial = np.asarray(ice_equivalent_m, dtype=float) * ICE_WATER_MM_PER_M
    snowfall = np.asarray(snowfall_monthly_mm, dtype=float)
    pdd = np.asarray(positive_degree_days, dtype=float)
    if (
        snowfall.shape != (12, *initial.shape)
        or pdd.shape != snowfall.shape
        or not all(np.isfinite(a).all() for a in (initial, snowfall, pdd))
        or any(np.any(a < 0) for a in (initial, snowfall, pdd))
        or min(snow_factor_mm_per_k_day, ice_factor_mm_per_k_day) <= 0
    ):
        raise ValueError("ice storage and monthly snow/melt capacity must be nonnegative")
    ice, snow = initial.copy(), np.zeros_like(initial)
    melted_snow, melted_ice = np.zeros_like(initial), np.zeros_like(initial)
    for accumulation, capacity in zip(snowfall, pdd, strict=True):
        snow += accumulation
        melt = np.minimum(snow, capacity * snow_factor_mm_per_k_day)
        snow -= melt
        melted_snow += melt
        capacity = np.maximum(capacity - melt / snow_factor_mm_per_k_day, 0)
        melt = np.minimum(ice, capacity * ice_factor_mm_per_k_day)
        ice -= melt
        melted_ice += melt
    accumulation = snowfall.sum(axis=0)
    final = ice + snow
    residual = final - initial - accumulation + melted_snow + melted_ice
    return IceMassBalance(
        final / ICE_WATER_MM_PER_M, accumulation, melted_snow, melted_ice, residual
    )
