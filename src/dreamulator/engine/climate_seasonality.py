"""Seasonal climate model — insolation-driven monthly temperature and precipitation.

This module reconstructs the full seasonality subsystem (roadmap 3A.2) that the
engine previously approximated with a crude ``A·|sin φ|·√sin ε`` sinusoid.  It
computes, from orbital geometry and the pre-calibrated annual-mean temperature:

  1. Monthly insolation from solar declination + daily-mean insolation
     (Hartmann 2016 eq. 3.7, with sunset hour angle and polar day/night).
  2. Monthly temperature, whose seasonal amplitude is modulated by surface heat
     capacity (land ~1×, ocean ~0.1–0.2×, coastal interpolation) — the
     "海陆热容量差" land-ocean contrast.
  3. ITCZ migration (latitude of maximum insolation) and a monthly precipitation
     distribution factor, replacing the fixed ``seasonality=0.4`` fake that
     previously dead-coded the Köppen third letter (s/w/f/m).

All functions are pure (no I/O, no RNG) and operate on numpy arrays.

References:
    - Hartmann, D.L. (2016). *Global Physical Climatology* (2nd ed.). Elsevier.
      Eq. 3.7 (daily-mean insolation), Ch. 6 (surface heat capacity / maritime
      vs continental climate).
"""

from __future__ import annotations

import math

import numpy as np

from dreamulator.engine.climate_physics import SOLAR_CONSTANT

# ---------------------------------------------------------------------------
# 1. Effective obliquity
# ---------------------------------------------------------------------------


def compute_effective_obliquity(
    axial_tilt_deg: float,
    orbital_inclination_deg: float = 0.0,
    parent_axial_tilt_deg: float = 0.0,
    is_satellite: bool = False,
) -> float:
    """Compute the effective obliquity relative to the star.

    For planets: effective = axial_tilt_deg.
    For satellites: effective = sqrt(inclination² + parent_tilt²) (RMS
    approximation; the actual value oscillates over the precession cycle).

    NOTE: this helper is **not wired into the pipeline**.  The convention in
    this project is that ``config.axial_tilt_deg`` is already the *effective*
    obliquity (gaia-m authors 9.0° = its orbital inclination), so auto-applying
    the RMS here would double-count the parent's tilt.  Keep this function for
    documentation and for future worlds that author the intrinsic spin tilt.

    Args:
        axial_tilt_deg: Body's axial tilt relative to its own orbital plane.
        orbital_inclination_deg: Orbital inclination (moons: to parent's
            equator; planets: to stellar equator).
        parent_axial_tilt_deg: Parent planet's axial tilt (satellites only).
        is_satellite: Whether this body is a moon.

    Returns:
        Effective obliquity in degrees.
    """
    if not is_satellite:
        return axial_tilt_deg
    inc_rad = math.radians(orbital_inclination_deg)
    parent_rad = math.radians(parent_axial_tilt_deg)
    return math.degrees(math.sqrt(inc_rad**2 + parent_rad**2))


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

    ``day_of_year = 0`` is the northern vernal equinox reference (declination 0,
    increasing toward northern summer).  For a circular orbit this gives
    ``δ = ε·sin(2π·day/T)``: day P/4 → +ε (N. summer solstice), day 3P/4 → −ε
    (N. winter solstice) — matching the frontend SunControl convention (0° =
    vernal equinox, 90° = N. summer solstice).

    For eccentric orbits an equation-of-center correction is applied, with the
    argument of perihelion assumed 0 (perihelion at the vernal-equinox
    reference).  ``perihelion_day`` is the day of perihelion passage relative to
    that reference.

    Args:
        day_of_year: Day number (0 = northern vernal equinox).
        obliquity_deg: Effective obliquity in degrees.
        orbital_period_days: Length of year in days.
        eccentricity: Orbital eccentricity (0 = circular).
        perihelion_day: Day of perihelion passage (relative to vernal equinox).

    Returns:
        Solar declination in radians.
    """
    eps = math.radians(obliquity_deg)

    # Mean anomaly measured from perihelion
    mean_anomaly = 2.0 * math.pi * (day_of_year - perihelion_day) / orbital_period_days

    # Equation of center (first-order eccentricity correction)
    e = eccentricity
    true_anomaly = (
        mean_anomaly
        + 2.0 * e * math.sin(mean_anomaly)
        + 1.25 * e * e * math.sin(2.0 * mean_anomaly)
    )

    # sin(δ) = sin(ε)·sin(λ_sun); λ_sun = ϖ + ν with ϖ = 0 (perihelion at equinox)
    return math.asin(max(-1.0, min(1.0, math.sin(eps) * math.sin(true_anomaly))))


def daily_mean_insolation(
    lat_rad: np.ndarray,
    declination: float,
    solar_constant: float,
) -> np.ndarray:
    """Daily-mean insolation at given latitude and solar declination.

    Formula (Hartmann 2016, eq. 3.7):
        Q = (S₀/π) × [H₀ sin φ sin δ + cos φ cos δ sin H₀]
    where H₀ = arccos(−tan φ tan δ) is the sunset hour angle.

    Args:
        lat_rad: Latitude in radians, shape (N,).
        declination: Solar declination in radians.
        solar_constant: S₀ in W/m² at the planet's distance.

    Returns:
        Daily-mean insolation in W/m², shape (N,).
    """
    phi = lat_rad
    delta = declination

    # Sunset hour angle; clip to handle polar day/night
    cos_h0 = np.clip(-np.tan(phi) * np.tan(delta), -1.0, 1.0)
    h0 = np.arccos(cos_h0)

    # Daily-mean insolation
    q = (solar_constant / math.pi) * (
        h0 * np.sin(phi) * np.sin(delta) + np.cos(phi) * np.cos(delta) * np.sin(h0)
    )

    # Polar day (sun never sets): h0 = π
    polar_day = cos_h0 <= -1.0
    # Polar night (sun never rises): h0 = 0
    polar_night = cos_h0 >= 1.0

    q[polar_day] = solar_constant * np.sin(phi[polar_day]) * np.sin(delta)
    q[polar_night] = 0.0

    return np.asarray(np.maximum(q, 0.0))


def orbital_distance_factor(
    day_of_year: float,
    eccentricity: float,
    orbital_period_days: float = 365.25,
    perihelion_day: float = 0.0,
) -> float:
    """Ratio of current insolation to semi-major-axis insolation: (a/d)².

    Args:
        day_of_year: Day number (0 = vernal equinox).
        eccentricity: Orbital eccentricity.
        orbital_period_days: Year length in days.
        perihelion_day: Day of perihelion passage.

    Returns:
        (a/d)² factor (>1 near perihelion, <1 near aphelion). 1.0 for circular.
    """
    if eccentricity < 1e-6:
        return 1.0
    mean_anomaly = 2.0 * math.pi * (day_of_year - perihelion_day) / orbital_period_days
    true_anomaly = mean_anomaly + 2.0 * eccentricity * math.sin(mean_anomaly)
    # d/a = (1−e²)/(1+e·cos ν)
    r_ratio = (1.0 - eccentricity**2) / (1.0 + eccentricity * math.cos(true_anomaly))
    return 1.0 / (r_ratio**2)


# ---------------------------------------------------------------------------
# 3. Monthly insolation
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
        perihelion_day: Day of perihelion passage.

    Returns:
        Shape (N, 12) — monthly mean daily insolation in W/m².
    """
    q_monthly = np.zeros((len(lat_rad), 12), dtype=np.float64)

    for month in range(12):
        # Mid-month day
        day = (month + 0.5) * orbital_period_days / 12.0

        declination = solar_declination(
            day, obliquity_deg, orbital_period_days, eccentricity, perihelion_day
        )
        dist_factor = orbital_distance_factor(
            day, eccentricity, orbital_period_days, perihelion_day
        )
        q_monthly[:, month] = daily_mean_insolation(
            lat_rad, declination, solar_constant * dist_factor
        )

    return q_monthly


# ---------------------------------------------------------------------------
# 3b. Annual-mean 1D Energy Balance Model
# ---------------------------------------------------------------------------


def solve_1d_ebm_temperature(
    lat_rad: np.ndarray,
    t_global_mean_c: float,
    *,
    albedo: float = 0.306,
    obliquity_deg: float = 23.44,
    solar_constant: float = SOLAR_CONSTANT,
    orbital_period_days: float = 365.25,
    eccentricity: float = 0.0,
    perihelion_day: float = 0.0,
    olr_b_wm2k: float = 2.0,
    diffusion_wm2k: float = 0.35,
    n_legendre: int = 8,
) -> np.ndarray:
    """Solve the steady-state 1D Energy Balance Model for the zonal-mean temperature.

    Solves (North 1975; Budyko 1969; climlab ``EBM``) for :math:`T(x)` with
    :math:`x=\\sin\\phi`:

        $$0 = D\\,\\frac{d}{dx}\\Big[(1-x^2)\\frac{dT}{dx}\\Big] + Q(x)(1-\\alpha) - (A + B\\,T)$$

    spectrally in Legendre polynomials.  The Legendre polynomials :math:`P_n(x)`
    are eigenfunctions of the diffusion operator with eigenvalue :math:`-n(n+1)`,
    so the equation decouples per mode:

        $$T_n = \\frac{Q_n(1-\\alpha) - A\\,\\delta_{n0}}{B + D\\,n(n+1)}$$

    where :math:`Q_n` is the n-th Legendre coefficient of the *annual-mean*
    insolation (the absorbed-shortwave flux).  The OLR intercept :math:`A` is
    **not** a free knob: it is calibrated so that :math:`T_0` — the Legendre
    n=0 mode, which equals the area-weighted global mean — reproduces
    ``t_global_mean_c`` exactly.  This keeps the global-mean temperature
    anchored to the equilibrium + greenhouse chain (``equilibrium_temperature``
    / ``surface_temperature``) while the 1D EBM redistributes heat meridionally.

    The diffusion coefficient :math:`D` controls the equator-pole contrast:
    larger :math:`D` flattens the profile.  The slow-rotator scaling
    (:math:`D \\propto \\Omega^{-0.3}`, Kaspi & Showman 2015) is applied by the
    caller so this function stays a single pure solver.

    Args:
        lat_rad: Latitude in radians, shape (N,) — output evaluation points.
        t_global_mean_c: Global-mean surface temperature (°C), anchors T_0.
        albedo: Bond albedo (0–1).
        obliquity_deg: Effective obliquity (degrees).
        solar_constant: S₀ at the planet's distance (W/m²).
        orbital_period_days: Year length (days).
        eccentricity: Orbit eccentricity.
        perihelion_day: Day of perihelion passage.
        olr_b_wm2k: Linear OLR coefficient B (W/m²/K).
        diffusion_wm2k: Meridional diffusion coefficient D (W/m²/K).
        n_legendre: Legendre truncation order.

    Returns:
        Zonal-mean temperature (°C) at each input latitude, shape (N,).
    """
    # 1. Annual-mean insolation Q(φ) on a fine 1° latitude grid.
    n_lat = 181
    lat_grid = np.linspace(-0.5 * np.pi, 0.5 * np.pi, n_lat)
    q_monthly = monthly_insolation(
        lat_grid,
        obliquity_deg,
        solar_constant,
        orbital_period_days,
        eccentricity,
        perihelion_day,
    )
    absorbed = q_monthly.mean(axis=1) * (1.0 - albedo)  # absorbed shortwave (W/m²)
    x_grid = np.sin(lat_grid)  # monotone increasing in [-1, 1]

    # 2. Legendre coefficients Q_n of the absorbed flux via Gauss–Legendre
    #    quadrature:  Q_n = (2n+1)/2 ∫_{−1}^{1} Q(x) P_n(x) dx.
    n_quad = max(2 * (n_legendre + 1), 32)
    xq, wq = np.polynomial.legendre.leggauss(n_quad)
    absorbed_q = np.interp(xq, x_grid, absorbed)

    q_n = np.zeros(n_legendre + 1)
    for n in range(n_legendre + 1):
        p_vals = np.polynomial.legendre.legval(xq, [0.0] * n + [1.0])
        q_n[n] = 0.5 * (2 * n + 1) * float(np.sum(wq * absorbed_q * p_vals))

    # 3. Calibrate A so T_0 = t_global_mean_c, then solve per mode.
    a = q_n[0] - olr_b_wm2k * t_global_mean_c

    t_n = np.zeros(n_legendre + 1)
    for n in range(n_legendre + 1):
        denom = olr_b_wm2k + diffusion_wm2k * n * (n + 1)
        num = q_n[n] - (a if n == 0 else 0.0)
        t_n[n] = num / denom

    # 4. Reconstruct T(x) at the cell latitudes.
    return np.asarray(np.polynomial.legendre.legval(np.sin(lat_rad), t_n))


def solve_held_hou_temperature(
    lat_rad: np.ndarray,
    t_global_mean_c: float,
    *,
    radius_km: float = 6371.0,
    gravity_m_s2: float = 9.81,
    rotation_period_days: float = 1.0,
    troposphere_height_m: float = 1.0e4,
) -> np.ndarray:
    """Zonal-mean surface temperature in the single-Hadley-cell regime (Held & Hou 1980).

    When the Hadley cell extends to the pole (slow rotators, P ≳ 3 days), the
    poleward heat transport is by direct overturning circulation (MOC), not
    baroclinic eddies — a *different* mechanism than the diffusive EBM's
    eddy-driven transport.  The overturning drives the temperature toward nearly
    constant potential temperature, which the angular-momentum-conserving
    solution captures as a **quartic** profile (not the EBM's Legendre-quadratic):

        θ(φ) = θ_eq − (Ω² a² θ₀ / (2 g H)) · sin⁴φ

    flat in the subtropics (sin⁴φ ≪ 1) and steep only near the pole — the
    distinguishing shape that keeps the subtropics warm (no cold deserts) while
    retaining a polar cap.  The equator-to-pole contrast

        ΔT = Ω² a² θ₀ / (2 g H)

    scales as Ω² (Held & Hou 1980), much flatter for slow rotators than the
    eddy-regime Ω^0.3 law (Kaspi & Showman 2015) — see energy_balance.md §3.

    θ_eq is calibrated (like the EBM's A) so the area-weighted global mean
    reproduces ``t_global_mean_c`` exactly, keeping the mean anchored to the
    equilibrium + greenhouse chain.  ⟨sin⁴φ⟩ = 1/5 over the sphere.

    Args:
        lat_rad: Latitude in radians, shape (N,) — output evaluation points.
        t_global_mean_c: Global-mean surface temperature (°C), anchors the mean.
        radius_km: Planet radius (km).
        gravity_m_s2: Surface gravity (m/s²).
        rotation_period_days: Sidereal rotation period (days).
        troposphere_height_m: Hadley-cell depth (troposphere height, m).

    Returns:
        Zonal-mean surface temperature (°C) at each input latitude, shape (N,).
    """
    omega = 2.0 * np.pi / (rotation_period_days * 86400.0)  # rad/s
    a = radius_km * 1000.0  # m
    theta0_k = t_global_mean_c + 273.15  # equatorial reference temperature (K)
    delta_t = omega**2 * a**2 * theta0_k / (2.0 * gravity_m_s2 * troposphere_height_m)
    # θ(φ) = θ_eq − ΔT·sin⁴φ; calibrate θ_eq so the mean equals t_global_mean_c
    # (⟨sin⁴φ⟩ = 1/5), giving T(φ) = T_mean + ΔT·(1/5 − sin⁴φ).
    return np.asarray(t_global_mean_c + delta_t * (0.2 - np.sin(lat_rad) ** 4))


# ---------------------------------------------------------------------------
# 4. Land-ocean heat capacity (seasonal amplitude modulation)
# ---------------------------------------------------------------------------


def seasonal_heat_capacity(
    is_land: np.ndarray,
    is_ocean: np.ndarray,
    distance_to_coast_km: np.ndarray,
    *,
    land_capacity: float = 2.0e7,
    ocean_capacity: float = 2.0e8,
    coastal_scale_km: float = 500.0,
) -> np.ndarray:
    """Per-cell surface heat capacity (J/m²/K) for the seasonal cycle.

    The ocean mixed layer (ρ_w·c_p·H_ml ≈ 2×10⁸ J/m²/K for H_ml = 50 m) has
    ~10× the land+atmosphere heat capacity (~2×10⁷ J/m²/K), so ocean seasonal
    amplitude is a small fraction of land's, decaying inland over a ~500 km
    maritime-moderation scale (energy_balance.md §5, Hartmann 2016).  This
    replaces the former f_ocean amplitude multiplier with the physical heat
    capacity (North & Coakley 1979).

    - Ocean: C = ocean_capacity.
    - Deep land (d ≫ coastal_scale_km): C = land_capacity.
    - Coastal land: C = ocean_capacity + (land_capacity − ocean_capacity)·(1 − e^{−d/L}).

    Args:
        is_land: Boolean land mask, shape (N,).
        is_ocean: Boolean ocean mask, shape (N,) (complement of is_land).
        distance_to_coast_km: Distance to nearest ocean in km, shape (N,)
            (ocean cells = 0).
        land_capacity: Land+atmosphere heat capacity (J/m²/K).
        ocean_capacity: Ocean mixed-layer heat capacity (J/m²/K).
        coastal_scale_km: Maritime-moderation e-folding length.

    Returns:
        Per-cell heat capacity in J/m²/K, shape (N,).
    """
    c = np.full(is_land.shape, land_capacity, dtype=np.float64)
    c[is_ocean] = ocean_capacity

    d = np.maximum(distance_to_coast_km[is_land], 0.0)
    c[is_land] = ocean_capacity + (land_capacity - ocean_capacity) * (
        1.0 - np.exp(-d / coastal_scale_km)
    )

    return c


# ---------------------------------------------------------------------------
# 5. Monthly temperature
# ---------------------------------------------------------------------------


def monthly_temperature(
    q_monthly: np.ndarray,
    t_mean_c: np.ndarray,
    heat_capacity: np.ndarray,
    *,
    olr_b_wm2k: float = 2.0,
    diffusion_wm2k: float = 0.35,
    orbital_period_days: float = 365.25,
    albedo: float = 0.306,
    ice_albedo: float = 0.7,
    ice_threshold_c: float = 0.0,
    ice_albedo_feedback: bool = True,
    n_iterations: int = 3,
) -> np.ndarray:
    """Compute monthly temperature from the seasonal energy-balance model.

    The seasonal temperature amplitude is the periodic solution of the 1-D EBM
    (North & Coakley 1979; Budyko 1969):

        T_amp = ΔQ_ω(1−α) / sqrt(B_eff² + (ωC)²)

    with an *explicit* meridional heat transport: the effective damping is
    ``B_eff = B_rad + D·n(n+1)`` evaluated at the dominant (quadrupole) seasonal
    mode n=2 → ``B_rad + 6D``.  This is the same diffusion D as the annual-mean
    1D EBM, so the seasonal and annual models share one transport coefficient —
    the former tuned constant ``damping_b=10`` (which over-damped the polar
    seasonal cycle) is gone.

    A seasonal ice-albedo feedback is applied by fixed-point iteration: a cell
    whose summer temperature stays below ``ice_threshold_c`` (never melts) keeps
    the snow/ice albedo and reflects the summer insolation, shrinking its
    seasonal amplitude — this keeps the ice cap (EF) cold in summer while the
    subarctic (Dfc) that melts each year warms up.

    Args:
        q_monthly: Monthly insolation, shape (N, 12).
        t_mean_c: Pre-computed annual mean temperature °C, shape (N,).
        heat_capacity: Per-cell surface heat capacity J/m²/K, shape (N,).
        olr_b_wm2k: Radiative damping B_rad (W/m²/K, Budyko 1969 ≈ 2).
        diffusion_wm2k: Meridional diffusion D (W/m²/K, same as the annual EBM).
        orbital_period_days: Year length in days.
        albedo: Snow-free surface albedo (the planet Bond albedo).
        ice_albedo: Snow/ice albedo for cells whose summer never melts.
        ice_threshold_c: Summer temperature below which a cell stays ice-covered.
        ice_albedo_feedback: Enable the seasonal ice-albedo fixed-point.
        n_iterations: Ice-albedo fixed-point iterations.

    Returns:
        Monthly temperature in °C, shape (N, 12).
    """
    months = np.arange(12, dtype=np.float64)

    # Annual Fourier amplitude of the insolation (absolute ΔQ_ω, W/m²).
    a1 = (2.0 / 12.0) * np.sum(q_monthly * np.cos(2.0 * np.pi * months / 12.0), axis=1)
    b1 = (2.0 / 12.0) * np.sum(q_monthly * np.sin(2.0 * np.pi * months / 12.0), axis=1)
    delta_q = np.sqrt(a1**2 + b1**2)

    # Effective damping with explicit meridional heat transport (quadrupole mode).
    b_eff = olr_b_wm2k + 6.0 * diffusion_wm2k
    omega = 2.0 * np.pi / (orbital_period_days * 86400.0)  # rad/s
    thermal_inertia = omega * heat_capacity  # W/m²/K

    # Snow-free amplitude (absorbed shortwave).
    amplitude_base = delta_q * (1.0 - albedo) / np.sqrt(b_eff**2 + thermal_inertia**2)
    amplitude = amplitude_base.copy()

    # Seasonal ice-albedo feedback: never-melting cells reflect the summer
    # insolation → smaller amplitude.  Fixed-point (the albedo depends on the
    # summer temperature, which depends on the albedo).
    if ice_albedo_feedback:
        for _ in range(n_iterations):
            t_hot = t_mean_c + amplitude
            frozen = t_hot < ice_threshold_c
            scale = np.where(frozen, (1.0 - ice_albedo) / (1.0 - albedo), 1.0)
            amplitude = amplitude_base * scale

    # Phase: insolation peak + thermal-inertia lag (tan φ_lag = ωC/B_eff).
    phi_q = np.arctan2(b1, a1)  # insolation peak phase (rad)
    phi_lag = np.arctan2(thermal_inertia, b_eff)  # lag (rad)
    month_hot = (phi_q + phi_lag) / (2.0 * np.pi) * 12.0  # months, 0–12

    t_monthly = t_mean_c[:, None] + amplitude[:, None] * np.cos(
        2.0 * np.pi * (months[None, :] - month_hot[:, None]) / 12.0
    )

    return np.asarray(t_monthly)


# ---------------------------------------------------------------------------
# 6. ITCZ migration and precipitation seasonality
# ---------------------------------------------------------------------------


def itcz_latitude_monthly(
    obliquity_deg: float,
    lag_months: int = 1,
    damping: float = 0.6,
    orbital_period_days: float = 365.25,
    eccentricity: float = 0.0,
    perihelion_day: float = 0.0,
) -> np.ndarray:
    """Compute ITCZ latitude for each month from the subsolar point (declination).

    The ITCZ follows the subsolar point — the latitude where the sun is directly
    overhead, i.e. the solar declination — **damped** by ocean thermal inertia.
    For Earth the declination swings ±23.44°, but the zonal-mean ITCZ only ~±14°
    (``damping ≈ 0.6``); the ~1-month ``lag_months`` captures the phase delay.

    Note (2026-08 fix): this previously took the ``argmax`` of the monthly
    insolation field, but the daily-mean insolation at the *summer pole* exceeds
    the subsolar point (24-hour daylight), so ``argmax`` snapped to ±90° and
    produced a discontinuous ITCZ of ±54° instead of ±14° — over-seasoning the
    precipitation factor.  Using the declination directly is the intended,
    first-principles definition (the thermal equator follows the subsolar point).

    Args:
        obliquity_deg: Effective obliquity in degrees.
        lag_months: Lag in whole months applied to the ITCZ position.
        damping: Fraction of the subsolar-point latitude reached by the ITCZ
            (ocean thermal-inertia damping; Earth ≈ 0.6).
        orbital_period_days: Length of year in days.
        eccentricity: Orbital eccentricity (0 = circular).
        perihelion_day: Day of perihelion passage (relative to vernal equinox).

    Returns:
        ITCZ latitude in degrees for each month, shape (12,).
    """
    itcz_lat = np.zeros(12, dtype=np.float64)
    for month in range(12):
        day = (month + 0.5) * orbital_period_days / 12.0
        decl = solar_declination(
            day, obliquity_deg, orbital_period_days, eccentricity, perihelion_day
        )
        itcz_lat[month] = np.degrees(decl) * damping
    return np.roll(itcz_lat, lag_months)


def monthly_precipitation_factor(
    lat_deg: np.ndarray,
    itcz_lat_monthly: np.ndarray,
    is_land: np.ndarray,
    *,
    sigma_deg: float = 15.0,
    baseline_fraction: float = 0.3,
) -> np.ndarray:
    """Compute monthly precipitation distribution factor.

    ``P(month) = P_annual × factor(lat, month)`` where factor is a Gaussian
    centered on the migrating ITCZ position, plus a uniform baseline.  Row sums
    are normalized to 1.0 so the annual total is conserved.

    Args:
        lat_deg: Latitude in degrees, shape (N,).
        itcz_lat_monthly: ITCZ position per month in degrees, shape (12,).
        is_land: Land mask, shape (N,).  (Reserved for future surface-type
            weighting; the factor currently applies uniformly.)
        sigma_deg: ITCZ influence width (degrees latitude).
        baseline_fraction: Fraction of rain that is non-ITCZ (orographic,
            frontal, local convective).

    Returns:
        Monthly precipitation factors, shape (N, 12); rows sum to 1.0.
    """
    del is_land  # reserved for future surface-type weighting
    n = len(lat_deg)
    factors = np.zeros((n, 12), dtype=np.float64)

    for month in range(12):
        itcz = itcz_lat_monthly[month]
        factors[:, month] = np.exp(-0.5 * ((lat_deg - itcz) / sigma_deg) ** 2)

    # Add uniform baseline component
    factors = (1.0 - baseline_fraction) * factors + baseline_fraction / 12.0

    # Normalize so monthly factors sum to 1.0
    row_sums = factors.sum(axis=1, keepdims=True)
    row_sums = np.maximum(row_sums, 1e-10)
    factors /= row_sums

    return factors


def warm_cold_half_precip(
    t_monthly: np.ndarray,
    p_monthly: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Split annual precipitation into warm-half and cold-half totals.

    Ranks the 12 months by temperature and sums precipitation over the 6 warmest
    (warm-half) and 6 coldest (cold-half) months.  Used by ``koppen_classify``
    for the B-group dryness-threshold offset (warm-season-wet vs cold-season-wet).

    Args:
        t_monthly: Monthly temperature °C, shape (N, 12).
        p_monthly: Monthly precipitation mm, shape (N, 12).

    Returns:
        Tuple ``(p_warm_mm, p_cold_mm)``, each shape (N,).
    """
    order = np.argsort(t_monthly, axis=1)  # ascending temperature
    n = t_monthly.shape[0]
    row_idx = np.arange(n)[:, None]
    p_cold = p_monthly[row_idx, order[:, :6]].sum(axis=1)
    p_warm = p_monthly[row_idx, order[:, 6:]].sum(axis=1)
    return p_warm, p_cold


def seasonal_precip_extremes(
    t_monthly: np.ndarray,
    p_monthly: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Per-half monthly precipitation extremes for the Köppen s/w third letter.

    Ranks the 12 months by temperature and splits into the 6 warmest (summer
    half) and 6 coldest (winter half) months, then returns the driest/wettest
    month in each half.  ``koppen_classify`` uses these to distinguish a dry
    **summer** (s, Mediterranean) from a dry **winter** (w, monsoon) — the
    distinction that a single wettest/driest-month pair cannot make.

    Args:
        t_monthly: Monthly temperature °C, shape (N, 12).
        p_monthly: Monthly precipitation mm, shape (N, 12).

    Returns:
        ``(p_dry_summer, p_wet_winter, p_dry_winter, p_wet_summer)`` — the
        driest warm-half month, wettest cold-half month, driest cold-half
        month, and wettest warm-half month, each shape (N,).
    """
    order = np.argsort(t_monthly, axis=1)  # ascending temperature
    n = t_monthly.shape[0]
    row_idx = np.arange(n)[:, None]
    p_summer = p_monthly[row_idx, order[:, 6:]]  # (N, 6) warmest months
    p_winter = p_monthly[row_idx, order[:, :6]]  # (N, 6) coldest months
    p_dry_summer = p_summer.min(axis=1)
    p_wet_winter = p_winter.max(axis=1)
    p_dry_winter = p_winter.min(axis=1)
    p_wet_summer = p_summer.max(axis=1)
    return p_dry_summer, p_wet_winter, p_dry_winter, p_wet_summer


# ---------------------------------------------------------------------------
# 7. High-level API
# ---------------------------------------------------------------------------


def compute_seasonal_climate(
    lat_rad: np.ndarray,
    t_mean_c: np.ndarray,
    is_land: np.ndarray,
    heat_capacity: np.ndarray,
    *,
    obliquity_deg: float = 23.44,
    solar_constant: float = SOLAR_CONSTANT,
    orbital_period_days: float = 365.25,
    eccentricity: float = 0.0,
    perihelion_day: float = 0.0,
    olr_b_wm2k: float = 2.0,
    diffusion_wm2k: float = 0.35,
    albedo: float = 0.306,
    ice_albedo: float = 0.7,
    ice_threshold_c: float = 0.0,
    ice_albedo_feedback: bool = True,
) -> dict[str, np.ndarray]:
    """Compute full seasonal climate: 12-month temperature and precipitation.

    Main entry point for the seasonality subsystem.  Requires the pre-computed
    annual-mean temperature (from the 1D EBM) and the per-cell surface heat
    capacity (land/ocean/coastal).

    Args:
        lat_rad: Latitude in radians, shape (N,).
        t_mean_c: Pre-computed annual mean temperature °C, shape (N,).
        is_land: Boolean land mask, shape (N,).
        heat_capacity: Per-cell surface heat capacity J/m²/K, shape (N,).
        obliquity_deg: Effective obliquity (degrees).
        solar_constant: S₀ at the planet's distance (W/m²).
        orbital_period_days: Year length (days).
        eccentricity: Heliocentric orbit eccentricity.
        perihelion_day: Day of perihelion passage.
        olr_b_wm2k: Radiative damping B_rad (W/m²/K).
        diffusion_wm2k: Meridional diffusion D (W/m²/K, same as the annual EBM).
        albedo: Snow-free surface albedo.
        ice_albedo: Snow/ice albedo for never-melting cells.
        ice_threshold_c: Summer temperature below which a cell stays ice-covered.
        ice_albedo_feedback: Enable the seasonal ice-albedo fixed-point.

    Returns:
        Dict with:
            'T_monthly': shape (N, 12), monthly temperature °C
            'T_cold': shape (N,), coldest month °C
            'T_hot': shape (N,), hottest month °C
            'P_factor': shape (N, 12), monthly precipitation fraction
            'itcz_lat': shape (12,), ITCZ latitude per month (degrees)
    """
    q_monthly = monthly_insolation(
        lat_rad,
        obliquity_deg,
        solar_constant,
        orbital_period_days,
        eccentricity,
        perihelion_day,
    )

    t_monthly = monthly_temperature(
        q_monthly,
        t_mean_c,
        heat_capacity,
        olr_b_wm2k=olr_b_wm2k,
        diffusion_wm2k=diffusion_wm2k,
        orbital_period_days=orbital_period_days,
        albedo=albedo,
        ice_albedo=ice_albedo,
        ice_threshold_c=ice_threshold_c,
        ice_albedo_feedback=ice_albedo_feedback,
    )

    t_cold = t_monthly.min(axis=1)
    t_hot = t_monthly.max(axis=1)

    itcz_lat = itcz_latitude_monthly(
        obliquity_deg=obliquity_deg,
        orbital_period_days=orbital_period_days,
        eccentricity=eccentricity,
        perihelion_day=perihelion_day,
    )

    lat_deg = np.degrees(lat_rad)
    p_factor = monthly_precipitation_factor(lat_deg, itcz_lat, is_land)

    return {
        "T_monthly": t_monthly,
        "T_cold": t_cold,
        "T_hot": t_hot,
        "P_factor": p_factor,
        "itcz_lat": itcz_lat,
    }
