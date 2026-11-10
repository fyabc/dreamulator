"""Open-water (lake surface) evaporation from the surface energy budget.

Annual evaporation from a lake is set by the energy the water absorbs, not by
the air temperature alone: a cold high plateau under a clear sky evaporates
several times what a temperature-only law gives (Hamon puts the inner Tibetan
Plateau at about 200 mm/yr; Nam Co evaporates 635 mm/yr, Ma et al. 2016).
This module follows the Priestley–Taylor form, the standard energy-limited
estimate when humidity and wind are not trustworthy:

    E = α · Δ / (Δ + γ) · max(Rn, 0) / λ

* ``Rn`` is the net radiation of the water surface, built from the monthly
  top-of-atmosphere insolation, the cloud cover and the air temperature
  with the FAO-56 relations (Allen et al. 1998, eqs. 35–39): shortwave
  ``Rs = (a + b · n/N) · Q_toa`` with the sunshine fraction n/N taken as
  ``1 − cloud``, clear-sky ``Rso = (0.75 + 2·10⁻⁵ z) · Q_toa``, and the net
  longwave loss ``σT⁴ (0.34 − 0.14 √e_a)(1.35 Rs/Rso − 0.35)``.
* ``γ`` falls with the surface pressure, so a high lake turns a larger
  share of the same energy into evaporation.
* Months whose mean air temperature is below freezing count as ice-covered
  and evaporate nothing (Ma et al. 2016 find sublimation from Tibetan lake
  ice negligible); heat storage only shifts evaporation between open-water
  months and is not modelled.

Earth check (14 lakes from 4724 m to −210 m, tropical to cold and arid; ERA5
temperature, NCEP cloud and top-of-atmosphere shortwave): the median ratio to
the observed annual evaporation is 1.06 (quartiles 0.92–1.19), correlation
0.94, 11 of 14 within ±25 %; the Hamon law with the lake factor scores 0.60.
Strongly advective desert reservoirs (Lake Nasser) come out about 10 % low,
the known limit of the Priestley–Taylor coefficient.

Pure functions: no IO, no RNG.
"""

from __future__ import annotations

import numpy as np

#: Stefan–Boltzmann constant (W m⁻² K⁻⁴).
SIGMA_W_M2_K4 = 5.670374419e-8
#: Latent heat of vaporisation (J/kg), FAO-56 value at 20 °C.
LATENT_HEAT_J_KG = 2.45e6
#: FAO-56 Ångström–Prescott coefficients, with the sunshine fraction read as
#: one minus the total cloud cover.  Observational fit; the pairing with
#: total cloud is what the 14-lake check calibrates (the Kasten–Czeplak cloud
#: law, closer to reanalysis shortwave over land, overestimates lake
#: evaporation 1.5-fold with the same longwave).
ANGSTROM_A = 0.25
ANGSTROM_B = 0.50
#: Shortwave albedo of open water (Finch & Calver 2008: 0.08 is the common
#: value; turbidity, waves and low sun raise it).  Observational.
WATER_ALBEDO = 0.08
#: Priestley–Taylor coefficient for saturated surfaces (Priestley & Taylor
#: 1972).  Observational fit; calibration domain humid to semi-arid open
#: water, low by ~10 % over strongly advective desert reservoirs.
PRIESTLEY_TAYLOR_ALPHA = 1.26
#: Near-surface relative humidity for the longwave vapour term.  The engine
#: carries no humidity; the longwave changes by ~4 % between 0.5 and 0.85 and
#: the evaporation less (Ma et al. 2016: 10 % in humidity moves lake
#: evaporation by 1 %).  Approximation.
ASSUMED_RELATIVE_HUMIDITY = 0.7
#: Monthly-mean air temperature below which the lake is ice-covered (°C).
#: Approximation: freeze-up and break-up lags are not modelled.
ICE_COVER_THRESHOLD_C = 0.0
#: Cloud cover used when the climate carries none (engine worlds without a
#: GCM): Earth's land-mean total cloud, NCEP 1991–2020 climatology excluding
#: Antarctica — the same source the coefficients above were checked with.
#: Observational; an uncloudy or overcast world departs from it.
EARTH_LAND_MEAN_CLOUD = 0.43
#: Reference month (days): annual sums are on the 365.25-day basis of the
#: moisture budget, the same as the Hamon PET they replace.
REFERENCE_MONTH_DAYS = 365.25 / 12.0


def saturation_vapour_pressure_kpa(t_c: np.ndarray) -> np.ndarray:
    """Tetens/Magnus saturation vapour pressure over water (kPa), FAO-56 eq. 11."""
    t = np.asarray(t_c, dtype=np.float64)
    return np.asarray(0.6108 * np.exp(17.27 * t / (t + 237.3)))


def saturation_slope_kpa_k(t_c: np.ndarray) -> np.ndarray:
    """Slope Δ of the saturation curve (kPa/K), FAO-56 eq. 13."""
    t = np.asarray(t_c, dtype=np.float64)
    return np.asarray(4098.0 * saturation_vapour_pressure_kpa(t) / (t + 237.3) ** 2)


def surface_pressure_kpa(elevation_m: np.ndarray) -> np.ndarray:
    """Standard-atmosphere surface pressure (kPa), FAO-56 eq. 7."""
    z = np.maximum(np.asarray(elevation_m, dtype=np.float64), -500.0)
    return np.asarray(101.3 * ((293.0 - 0.0065 * z) / 293.0) ** 5.26)


def water_net_radiation(
    t_c: np.ndarray,
    q_toa_w_m2: np.ndarray,
    cloud: np.ndarray,
    elevation_m: np.ndarray,
    *,
    relative_humidity: float = ASSUMED_RELATIVE_HUMIDITY,
) -> np.ndarray:
    """Net radiation of an open-water surface (W/m²), FAO-56 relations.

    Arguments broadcast; ``cloud`` is the total cloud fraction (0–1).
    """
    t = np.asarray(t_c, dtype=np.float64)
    q = np.asarray(q_toa_w_m2, dtype=np.float64)
    c = np.clip(np.asarray(cloud, dtype=np.float64), 0.0, 1.0)
    z = np.asarray(elevation_m, dtype=np.float64)
    rs = q * (ANGSTROM_A + ANGSTROM_B * (1.0 - c))
    rso = (0.75 + 2e-5 * z) * q
    ratio = np.clip(np.divide(rs, rso, out=np.ones_like(rs * rso), where=rso > 1.0), 0.3, 1.0)
    ea = relative_humidity * saturation_vapour_pressure_kpa(t)
    rnl = SIGMA_W_M2_K4 * (t + 273.15) ** 4 * (0.34 - 0.14 * np.sqrt(ea)) * (1.35 * ratio - 0.35)
    return np.asarray((1.0 - WATER_ALBEDO) * rs - rnl)


def open_water_evaporation_monthly(
    t_monthly_c: np.ndarray,
    q_toa_monthly_w_m2: np.ndarray,
    cloud: np.ndarray,
    elevation_m: np.ndarray,
) -> np.ndarray:
    """Monthly open-water evaporation (mm per reference month), shape (N, 12).

    Args:
        t_monthly_c: Monthly-mean air temperature (°C), (N, 12).
        q_toa_monthly_w_m2: Monthly-mean top-of-atmosphere insolation (W/m²), (N, 12).
        cloud: Total cloud fraction, (N,) or (N, 12).
        elevation_m: Surface elevation (m), (N,).
    """
    t = np.asarray(t_monthly_c, dtype=np.float64)
    c = np.asarray(cloud, dtype=np.float64)
    if c.ndim == 1:
        c = c[:, None]
    z = np.asarray(elevation_m, dtype=np.float64)[:, None]
    rn = water_net_radiation(t, q_toa_monthly_w_m2, c, z)
    delta = saturation_slope_kpa_k(t)
    gamma = 0.665e-3 * surface_pressure_kpa(z)
    seconds = REFERENCE_MONTH_DAYS * 86400.0
    e = (
        PRIESTLEY_TAYLOR_ALPHA
        * delta
        / (delta + gamma)
        * np.maximum(rn, 0.0)
        / LATENT_HEAT_J_KG
        * seconds
    )
    return np.asarray(np.where(t < ICE_COVER_THRESHOLD_C, 0.0, e))


def open_water_evaporation(
    t_monthly_c: np.ndarray,
    q_toa_monthly_w_m2: np.ndarray,
    cloud: np.ndarray,
    elevation_m: np.ndarray,
) -> np.ndarray:
    """Annual open-water evaporation (mm/yr on the 365.25-day basis), shape (N,)."""
    return np.asarray(
        open_water_evaporation_monthly(t_monthly_c, q_toa_monthly_w_m2, cloud, elevation_m).sum(
            axis=-1
        )
    )
