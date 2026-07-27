"""Seasonal climate model — driven by stellar insolation.

Computes monthly temperature and precipitation from first principles:
  1. Stellar insolation Q(lat, month) from luminosity + distance + incidence angle
  2. Monthly temperature from radiative equilibrium + greenhouse + lapse rate
  3. ITCZ migration tracking the thermal equator
  4. Monthly precipitation distribution from ITCZ + monsoon logic

Handles three seasonal regimes:
  - Axial tilt driven (Earth: ε=23.44°)
  - Eccentricity driven (Mars-like: e>0.05)
  - Moon compound obliquity (Gaia-M: inclination + parent tilt)

All functions are pure (no I/O, no RNG) and operate on numpy arrays.
"""

from __future__ import annotations

import math

import numpy as np

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Stefan-Boltzmann constant (W m⁻² K⁻⁴)
_SIGMA_SB = 5.670374419e-8

# Solar constant at 1 AU (W m⁻²)
_SOLAR_CONSTANT_1AU = 1361.0

# Days per month (simplified: 12 equal months)
_DAYS_PER_MONTH = 365.25 / 12.0


# ---------------------------------------------------------------------------
# 1. Effective obliquity computation
# ---------------------------------------------------------------------------


def compute_effective_obliquity(
    axial_tilt_deg: float,
    orbital_inclination_deg: float = 0.0,
    parent_axial_tilt_deg: float = 0.0,
    is_satellite: bool = False,
) -> float:
    """Compute effective obliquity relative to the star.

    For planets: effective = axial_tilt_deg
    For satellites: effective = sqrt(inclination² + parent_tilt²)
        (RMS approximation; actual value oscillates over precession cycle)

    Args:
        axial_tilt_deg: Body's axial tilt relative to its own orbital plane.
        orbital_inclination_deg: Orbital inclination (for moons: relative to
            parent's equator; for planets: relative to stellar equator).
        parent_axial_tilt_deg: Parent planet's axial tilt (satellites only).
        is_satellite: Whether this body is a moon.

    Returns:
        Effective obliquity in degrees.
    """
    if is_satellite:
        # Compound obliquity: moon's orbital inclination to parent's equator
        # combined with parent's axial tilt to the ecliptic.
        # RMS approximation (precession averages the relative orientation).
        inc_rad = math.radians(orbital_inclination_deg)
        parent_rad = math.radians(parent_axial_tilt_deg)
        effective = math.sqrt(inc_rad**2 + parent_rad**2)
        return math.degrees(effective)
    else:
        return axial_tilt_deg


# ---------------------------------------------------------------------------
# 2. Solar geometry
# ---------------------------------------------------------------------------


def solar_declination(
    day_of_year: float,
    obliquity_deg: float,
    orbital_period_days: float = 365.25,
    eccentricity: float = 0.0,
    perihelion_day: float = 0.0,
) -> float:
    """Solar declination angle for a given day.

    For circular orbits: δ = ε × sin(2π d / T)
    For eccentric orbits: adds equation-of-center correction.

    Args:
        day_of_year: Day number (0 = vernal equinox reference).
        obliquity_deg: Effective obliquity in degrees.
        orbital_period_days: Length of year in days.
        eccentricity: Orbital eccentricity (0 = circular).
        perihelion_day: Day of perihelion passage.

    Returns:
        Solar declination in radians.
    """
    eps = math.radians(obliquity_deg)
    # Mean anomaly
    M = 2.0 * math.pi * (day_of_year - 80.0) / orbital_period_days

    # Equation of center (first-order correction for eccentricity)
    e = eccentricity
    nu = M + 2.0 * e * math.sin(M) + 1.25 * e * e * math.sin(2.0 * M)

    # Declination from ecliptic longitude
    # sin(δ) = sin(ε) × sin(ν + ω)
    # For simplicity, assume argument of perihelion ω = 0
    declination = math.asin(
        max(-1.0, min(1.0, math.sin(eps) * math.sin(nu)))
    )
    return declination


def daily_mean_insolation(
    lat_rad: np.ndarray,
    declination: float,
    solar_constant: float,
) -> np.ndarray:
    """Daily-mean insolation at given latitude and solar declination.

    Formula (Hartmann 2016, eq. 3.7):
        Q = (S₀/π) × [H₀ sin(φ)sin(δ) + cos(φ)cos(δ)sin(H₀)]

    Where H₀ = arccos(-tan(φ)tan(δ)) is the sunset hour angle.

    Args:
        lat_rad: Latitude in radians, shape (N,).
        declination: Solar declination in radians.
        solar_constant: S₀ in W/m² at the planet's distance.

    Returns:
        Daily-mean insolation in W/m², shape (N,).
    """
    phi = lat_rad
    delta = declination

    # Sunset hour angle
    cos_H0 = -np.tan(phi) * np.tan(delta)
    # Clip to handle polar day/night
    cos_H0 = np.clip(cos_H0, -1.0, 1.0)
    H0 = np.arccos(cos_H0)

    # Handle polar day (H0 = π) and polar night (H0 = 0)
    # For polar day: cos_H0 < -1 → H0 = π
    polar_day = cos_H0 <= -1.0
    polar_night = cos_H0 >= 1.0

    # Daily mean insolation
    Q = (solar_constant / math.pi) * (
        H0 * np.sin(phi) * np.sin(delta)
        + np.cos(phi) * np.cos(delta) * np.sin(H0)
    )

    # Fix polar cases
    Q[polar_day] = solar_constant * np.sin(phi[polar_day]) * np.sin(delta)
    Q[polar_night] = 0.0

    return np.maximum(Q, 0.0)


def orbital_distance_factor(
    day_of_year: float,
    eccentricity: float,
    orbital_period_days: float = 365.25,
    perihelion_day: float = 0.0,
) -> float:
    """Ratio of current distance to semi-major axis: (a/d)².

    Insolation scales as (a/d)². For circular orbit, this is 1.0.

    Args:
        day_of_year: Day number.
        eccentricity: Orbital eccentricity.
        orbital_period_days: Year length.
        perihelion_day: Day of perihelion.

    Returns:
        (a/d)² factor (>1 near perihelion, <1 near aphelion).
    """
    if eccentricity < 1e-6:
        return 1.0
    M = 2.0 * math.pi * (day_of_year - perihelion_day) / orbital_period_days
    # True anomaly (first-order)
    nu = M + 2.0 * eccentricity * math.sin(M)
    # Distance ratio: d/a = (1-e²)/(1+e·cos(ν))
    r_ratio = (1.0 - eccentricity**2) / (1.0 + eccentricity * math.cos(nu))
    # Insolation factor: (a/d)² = 1/r_ratio²
    return 1.0 / (r_ratio**2)


# ---------------------------------------------------------------------------
# 3. Monthly insolation and temperature
# ---------------------------------------------------------------------------


def monthly_insolation(
    lat_rad: np.ndarray,
    obliquity_deg: float,
    solar_constant: float,
    orbital_period_days: float = 365.25,
    eccentricity: float = 0.0,
    perihelion_day: float = 0.0,
) -> np.ndarray:
    """Compute 12-month mean daily insolation for each latitude.

    Args:
        lat_rad: Latitude in radians, shape (N,).
        obliquity_deg: Effective obliquity in degrees.
        solar_constant: S₀ at semi-major axis (W/m²).
        orbital_period_days: Year length in days.
        eccentricity: Orbital eccentricity.
        perihelion_day: Day of perihelion.

    Returns:
        Shape (N, 12) — monthly mean daily insolation in W/m².
    """
    n = len(lat_rad)
    Q_monthly = np.zeros((n, 12), dtype=np.float64)

    for month in range(12):
        # Mid-month day
        day = (month + 0.5) * _DAYS_PER_MONTH
        # Adjust for non-Earth year lengths
        day_scaled = day * orbital_period_days / 365.25

        # Solar declination at mid-month
        delta = solar_declination(
            day_scaled, obliquity_deg, orbital_period_days, eccentricity, perihelion_day
        )

        # Distance factor (eccentricity effect)
        dist_factor = orbital_distance_factor(
            day_scaled, eccentricity, orbital_period_days, perihelion_day
        )

        # Daily mean insolation
        Q_monthly[:, month] = daily_mean_insolation(
            lat_rad, delta, solar_constant * dist_factor
        )

    return Q_monthly


def monthly_temperature(
    Q_monthly: np.ndarray,
    t_mean_c: np.ndarray,
    is_ocean: np.ndarray,
    seasonal_amplitude_c: float = 35.0,
) -> np.ndarray:
    """Compute monthly temperature from mean climate + insolation-driven seasonality.

    The absolute temperature comes from the pre-calibrated mean model
    (latitude gradient + greenhouse + lapse rate). Insolation determines
    only the seasonal SHAPE and relative AMPLITUDE.

    Seasonal amplitude at each latitude is proportional to the fractional
    insolation variation: (Q_max - Q_min) / Q_mean. This naturally gives:
      - Zero amplitude at equator (uniform insolation)
      - Maximum amplitude at poles (midnight sun / polar night)
      - Reduced amplitude for high obliquity vs low obliquity

    Ocean cells have 60% amplitude damping (thermal inertia).

    Args:
        Q_monthly: Monthly insolation, shape (N, 12).
        t_mean_c: Pre-computed annual mean temperature, shape (N,).
        is_ocean: Boolean ocean mask, shape (N,).
        seasonal_amplitude_c: Global amplitude scaling factor (°C).

    Returns:
        Monthly temperature in °C, shape (N, 12).
    """
    # Fractional insolation variation at each latitude
    Q_max = Q_monthly.max(axis=1)
    Q_min = Q_monthly.min(axis=1)
    Q_mean = Q_monthly.mean(axis=1)

    # Normalized seasonal amplitude (0 at equator, ~1 at poles for Earth)
    # Capped at 2.0 to prevent polar amplification blowup (polar night → Q_min=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        frac_variation = np.where(Q_mean > 1.0, (Q_max - Q_min) / Q_mean, 0.0)
    frac_variation = np.minimum(frac_variation, 2.0)

    # Scale to temperature amplitude.
    # Atmospheric/oceanic heat transport damps the insolation-driven variation.
    # Empirical factor 0.25 calibrated to Earth:
    #   45°N: frac_var≈1.0 → amplitude≈8.75°C → range≈17.5°C
    #   60°N: frac_var≈2.0 (capped) → amplitude≈17.5°C → range≈35°C
    amplitude = seasonal_amplitude_c * frac_variation * 0.25

    # Ocean damping: 60% reduction over water
    amplitude[is_ocean] *= 0.4

    # Determine phase: which month is hottest (from insolation maximum)
    month_hot = Q_monthly.argmax(axis=1)  # shape (N,), values 0-11

    # Sinusoidal seasonal curve (bounded ±1)
    months = np.arange(12, dtype=np.float64)
    T_monthly = np.zeros((len(t_mean_c), 12), dtype=np.float64)
    for i in range(len(t_mean_c)):
        # Cosine curve peaking at month_hot
        curve = np.cos(2.0 * np.pi * (months - month_hot[i]) / 12.0)
        T_monthly[i, :] = t_mean_c[i] + amplitude[i] * curve

    return T_monthly


# ---------------------------------------------------------------------------
# 4. ITCZ migration and precipitation seasonality
# ---------------------------------------------------------------------------


def itcz_latitude_monthly(
    Q_monthly: np.ndarray,
    lat_rad: np.ndarray,
) -> np.ndarray:
    """Compute ITCZ latitude for each month from insolation maximum.

    The ITCZ follows the latitude of maximum insolation (thermal equator),
    with a ~30-day lag due to ocean thermal inertia.

    Args:
        Q_monthly: Monthly insolation, shape (N, 12).
        lat_rad: Latitude in radians, shape (N,).

    Returns:
        ITCZ latitude in degrees for each month, shape (12,).
    """
    itcz_lat = np.zeros(12, dtype=np.float64)

    for month in range(12):
        # Find latitude of maximum insolation
        Q = Q_monthly[:, month]
        idx_max = np.argmax(Q)
        itcz_lat[month] = np.degrees(lat_rad[idx_max])

    # Apply 30-day lag (~1 month shift)
    itcz_lat_lagged = np.roll(itcz_lat, 1)

    return itcz_lat_lagged


def monthly_precipitation_factor(
    lat_deg: np.ndarray,
    itcz_lat_monthly: np.ndarray,
    is_land: np.ndarray,
) -> np.ndarray:
    """Compute monthly precipitation distribution factor.

    P(month) = P_annual × factor(lat, month)
    Where factor is a Gaussian centered on the ITCZ position.

    Sum of factors over 12 months = 1.0 (conservation of annual total).

    Args:
        lat_deg: Latitude in degrees, shape (N,).
        itcz_lat_monthly: ITCZ position per month in degrees, shape (12,).
        is_land: Land mask, shape (N,).

    Returns:
        Monthly precipitation factors, shape (N, 12). Sum along axis=1 ≈ 1.
    """
    n = len(lat_deg)
    factors = np.zeros((n, 12), dtype=np.float64)

    # ITCZ influence width (degrees latitude)
    sigma = 15.0

    for month in range(12):
        itcz = itcz_lat_monthly[month]
        # Gaussian weight: peaks at ITCZ, decays away
        factors[:, month] = np.exp(-0.5 * ((lat_deg - itcz) / sigma) ** 2)

    # Add baseline (uniform) component: 30% of rain is non-ITCZ
    # (orographic, frontal, convective from local heating)
    baseline_fraction = 0.3
    factors = (1.0 - baseline_fraction) * factors + baseline_fraction / 12.0

    # Normalize so monthly factors sum to 1.0
    row_sums = factors.sum(axis=1, keepdims=True)
    row_sums = np.maximum(row_sums, 1e-10)
    factors /= row_sums

    return factors


# ---------------------------------------------------------------------------
# 5. High-level API
# ---------------------------------------------------------------------------


def compute_seasonal_climate(
    lat_rad: np.ndarray,
    t_mean_c: np.ndarray,
    is_land: np.ndarray,
    *,
    obliquity_deg: float = 23.44,
    solar_constant: float = _SOLAR_CONSTANT_1AU,
    orbital_period_days: float = 365.25,
    eccentricity: float = 0.0,
    perihelion_day: float = 0.0,
    seasonal_amplitude_c: float = 35.0,
) -> dict[str, np.ndarray]:
    """Compute full seasonal climate: 12-month T and P factors.

    This is the main entry point for the seasonality system.
    Requires pre-computed annual mean temperature (from the latitude
    gradient + greenhouse + lapse rate model).

    Args:
        lat_rad: Latitude in radians, shape (N,).
        t_mean_c: Pre-computed annual mean temperature °C, shape (N,).
        is_land: Boolean land mask, shape (N,).
        obliquity_deg: Effective obliquity (degrees).
        solar_constant: S₀ at planet's distance (W/m²).
        orbital_period_days: Year length (days).
        eccentricity: Orbital eccentricity.
        perihelion_day: Day of perihelion.
        seasonal_amplitude_c: Amplitude scaling factor.

    Returns:
        Dict with:
            'T_monthly': shape (N, 12), monthly temperature °C
            'T_mean': shape (N,), annual mean temperature °C (same as input)
            'T_cold': shape (N,), coldest month °C
            'T_hot': shape (N,), hottest month °C
            'P_factor': shape (N, 12), monthly precipitation fraction
            'itcz_lat': shape (12,), ITCZ latitude per month (degrees)
    """
    is_ocean = ~is_land

    # 1. Monthly insolation
    Q_monthly = monthly_insolation(
        lat_rad, obliquity_deg, solar_constant,
        orbital_period_days, eccentricity, perihelion_day,
    )

    # 2. Monthly temperature (mean + insolation-driven seasonality)
    T_monthly = monthly_temperature(
        Q_monthly, t_mean_c, is_ocean, seasonal_amplitude_c,
    )

    # 3. Temperature statistics
    T_mean = t_mean_c  # preserve the calibrated mean
    T_cold = T_monthly.min(axis=1)
    T_hot = T_monthly.max(axis=1)

    # 4. ITCZ migration
    itcz_lat = itcz_latitude_monthly(Q_monthly, lat_rad)

    # 5. Precipitation seasonality factors
    lat_deg = np.degrees(lat_rad)
    P_factor = monthly_precipitation_factor(lat_deg, itcz_lat, is_land)

    return {
        "T_monthly": T_monthly,
        "T_mean": T_mean,
        "T_cold": T_cold,
        "T_hot": T_hot,
        "P_factor": P_factor,
        "itcz_lat": itcz_lat,
    }
