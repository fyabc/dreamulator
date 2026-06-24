"""Stellar physics — pure computation functions for mass-luminosity-radius relations,
habitable zones, instellation, and condensation lines.

All functions are pure (no IO, no RNG) and independently testable.

References:
    - Kippenhahn, R., Weigert, A., & Weiss, A. (2012). Stellar Structure and Evolution.
      Springer-Verlag. (Classical four-segment MLR)
    - Demircan, O., & Kahraman, G. (1991). Ap&SS, 181(2), 313-322. (MRR)
    - Gough, D. O. (1981). Solar Physics, 74(1), 21-34. (Solar age evolution)
    - Eker, Z., et al. (2018). MNRAS, 479(4), 5491-5504. (Metallicity effects)
    - Kopparapu, R. K., et al. (2013). ApJ, 765(2), 131. (Habitable zones)
    - Prša, A., et al. (2016). AJ, 151(5), 123. (IAU 2015 solar constants)
    - Carroll, B. W., & Ostlie, D. A. (2017). An Introduction to Modern Astrophysics.
      Cambridge University Press. (Main-sequence lifetime)
"""

from __future__ import annotations

import math

# ---------------------------------------------------------------------------
# IAU 2015 Resolution B3 solar reference constants
# Ref: Prša et al. (2016), AJ, 151(5), 123
# ---------------------------------------------------------------------------
T_SUN_K: float = 5772.0  # Nominal solar effective temperature (K)
L_SUN_W: float = 3.828e26  # Nominal solar luminosity (W)
S_EARTH_W_M2: float = 1361.0  # Solar constant at 1 AU (W/m²)
AU_M: float = 1.496e11  # 1 AU in metres
SIGMA_SB: float = 5.670374419e-8  # Stefan-Boltzmann constant (W m⁻² K⁻⁴)

# Solar age for normalisation (Gyr)
_TAU_SUN: float = 0.46  # Sun's evolution progress at 4.6 Gyr

# Age correction denominators (ensure M=1, t=4.6 → L=1, R=1)
_L_AGE_DENOM: float = 1.0 + 0.4 * _TAU_SUN  # = 1.184
_R_AGE_DENOM: float = 1.0 + 0.3 * _TAU_SUN  # = 1.138


# ===================================================================
# Mass–Luminosity Relation (ZAMS)
# Ref: Kippenhahn & Weigert (2012), Stellar Structure and Evolution
# ===================================================================


def mass_luminosity_zams(mass: float) -> float:
    """Zero-age main-sequence luminosity from mass (Kippenhahn four-segment MLR).

    Args:
        mass: Stellar mass in solar masses (M☉).

    Returns:
        Luminosity in solar luminosities (L☉).
    """
    if mass < 0.43:
        return 0.23 * math.pow(mass, 2.3)
    elif mass < 2.0:
        return math.pow(mass, 4.0)
    elif mass < 55.0:
        return 1.4 * math.pow(mass, 3.5)
    else:
        return 32000.0 * mass


# ===================================================================
# Mass–Radius Relation (ZAMS)
# Ref: Demircan & Kahraman (1991), Ap&SS, 181(2), 313-322
# Modified: removed statistical inflation coefficient so M=1 → R=1
# ===================================================================


def mass_radius_zams(mass: float) -> float:
    """Zero-age main-sequence radius from mass (modified Demircan & Kahraman 1991).

    Args:
        mass: Stellar mass in solar masses (M☉).

    Returns:
        Radius in solar radii (R☉).
    """
    if mass < 1.66:
        return math.pow(mass, 0.945)
    else:
        return 1.25 * math.pow(mass, 0.555)


# ===================================================================
# Main-sequence lifetime & evolution progress
# Ref: Carroll & Ostlie (2017)
# ===================================================================


def main_sequence_lifetime(mass: float) -> float:
    """Main-sequence lifetime in gigayears.

    Args:
        mass: Stellar mass in solar masses (M☉).

    Returns:
        Main-sequence lifetime in Gyr.
    """
    return 10.0 * math.pow(mass, -2.5)


def evolution_progress(age_gyr: float, mass: float) -> float:
    """Evolution progress τ ∈ [0, 1].

    0 = zero-age (just born), 1 = core hydrogen exhausted.

    Args:
        age_gyr: Stellar age in Gyr.
        mass: Stellar mass in solar masses (M☉).

    Returns:
        Evolution progress, clamped to [0, 1].
    """
    t_ms = main_sequence_lifetime(mass)
    return min(age_gyr / t_ms, 1.0)


# ===================================================================
# Age & metallicity corrections
# Ref: Gough (1981), Solar Physics, 74(1), 21-34 (age)
# Ref: Eker et al. (2018), MNRAS, 479(4), 5491 (metallicity)
# ===================================================================


def apply_age_metallicity(
    l_zams: float,
    r_zams: float,
    tau: float,
    z: float,
) -> tuple[float, float]:
    """Apply age evolution and metallicity corrections to ZAMS values.

    Age correction uses Gough (1981) linear evolution model, normalised to
    the Sun's current state (4.6 Gyr, τ=0.46) so that M=1 → L=1, R=1.

    Metallicity correction from stellar homology relations:
    low-Z stars are slightly hotter and smaller.

    Args:
        l_zams: Zero-age luminosity (L☉).
        r_zams: Zero-age radius (R☉).
        tau: Evolution progress [0, 1].
        z: Relative metallicity Z/Z☉ (1.0 = solar).

    Returns:
        (luminosity, radius) in solar units after corrections.
    """
    # Age correction (solar-normalised)
    l_age = l_zams * (1.0 + 0.4 * tau) / _L_AGE_DENOM
    r_age = r_zams * (1.0 + 0.3 * tau) / _R_AGE_DENOM

    # Metallicity correction
    l_final = l_age * math.pow(z, -0.1)
    r_final = r_age * math.pow(z, 0.05)

    return l_final, r_final


# ===================================================================
# Stefan-Boltzmann effective temperature
# Ref: Prša et al. (2016), IAU 2015 Resolution B3
# ===================================================================


def effective_temperature(luminosity: float, radius: float) -> float:
    """Compute effective surface temperature from luminosity and radius.

    T_eff = T☉ × (L / R²)^0.25

    Args:
        luminosity: Luminosity in solar luminosities (L☉).
        radius: Radius in solar radii (R☉).

    Returns:
        Effective temperature in Kelvin.
    """
    return T_SUN_K * math.pow(luminosity / math.pow(radius, 2), 0.25)


# ===================================================================
# Luminosity → Mass inversion (hybrid mode)
# Inverts the Kippenhahn four-segment MLR
# ===================================================================


def invert_mass_from_luminosity(
    luminosity: float,
    age_gyr: float = 4.6,
    metallicity_dex: float = 0.0,
) -> float:
    """Derive stellar mass from luminosity, age, and metallicity via numerical root-finding.

    The forward relation L(M, age, Z) includes age-evolution and metallicity
    corrections that make analytic inversion impractical (the equation
    a·M^b·(1 + c·M^2.5) = target has no closed-form solution).

    Instead, we solve f(M) = L_forward(M) - L_target = 0 using Brent's method,
    which is guaranteed to converge for monotonic functions on a bracketed
    interval.  L(M) is monotonically increasing, so this is safe.

    Args:
        luminosity: Target luminosity in solar luminosities (L☉).
        age_gyr: Stellar age in Gyr (default 4.6).
        metallicity_dex: Metallicity [Fe/H] in dex (default 0.0 = solar).

    Returns:
        Estimated mass in solar masses (M☉).
    """
    from scipy.optimize import brentq  # type: ignore[import-untyped]

    z = math.pow(10.0, metallicity_dex)

    def forward_l(mass: float) -> float:
        l_z = mass_luminosity_zams(mass)
        tau = min(age_gyr / main_sequence_lifetime(mass), 1.0)
        l_out, _ = apply_age_metallicity(l_z, 1.0, tau, z)
        return l_out

    def f(mass: float) -> float:
        return forward_l(mass) - luminosity

    # Bracket: [0.08 M☉ (hydrogen-burning limit), 120 M☉ (upper MS)]
    return float(brentq(f, 0.08, 120.0, xtol=1e-8, rtol=1e-10))


# ===================================================================
# Comprehensive stellar parameter computation (hybrid entry point)
# ===================================================================


def compute_stellar_parameters(
    mass: float | None = None,
    luminosity: float | None = None,
    age_gyr: float = 4.6,
    metallicity_dex: float = 0.0,
) -> dict[str, float | str]:
    """Compute full stellar parameters using hybrid input mode.

    Provide mass, luminosity, or both:
    - mass only: forward computation of L, R, T_eff.
    - luminosity only: invert to get mass, then compute R, T_eff.
    - both: mass takes priority; reported input_mode is "both".

    Args:
        mass: Stellar mass (M☉), or None.
        luminosity: Stellar luminosity (L☉), or None.
        age_gyr: Age in gigayears (default 4.6).
        metallicity_dex: Metallicity [Fe/H] in dex (default 0.0 = solar).

    Returns:
        Dict with keys: mass, luminosity, radius, temperature,
        ms_lifetime_gyr, evolution_progress, metallicity_z, input_mode.

    Raises:
        ValueError: If neither mass nor luminosity is provided.
    """
    if mass is None and luminosity is None:
        raise ValueError("At least one of mass or luminosity must be provided")

    # Determine input mode and resolve mass
    if mass is not None and luminosity is not None:
        input_mode = "both"
    elif mass is not None:
        input_mode = "mass"
    else:
        input_mode = "luminosity"
        assert luminosity is not None
        mass = invert_mass_from_luminosity(luminosity, age_gyr, metallicity_dex)

    # Convert [Fe/H] to relative metallicity
    z = math.pow(10.0, metallicity_dex)

    # ZAMS base values
    l_zams = mass_luminosity_zams(mass)
    r_zams = mass_radius_zams(mass)

    # Evolution progress
    tau = evolution_progress(age_gyr, mass)

    # Apply corrections
    l_final, r_final = apply_age_metallicity(l_zams, r_zams, tau, z)

    # If user provided luminosity as override (both mode), use it
    if input_mode == "both" and luminosity is not None:
        l_final = luminosity
        # Recompute temperature with overridden luminosity
        t_eff = effective_temperature(l_final, r_final)
    else:
        t_eff = effective_temperature(l_final, r_final)

    t_ms = main_sequence_lifetime(mass)

    return {
        "mass": round(mass, 6),
        "luminosity": round(l_final, 6),
        "radius": round(r_final, 6),
        "temperature": round(t_eff, 1),
        "ms_lifetime_gyr": round(t_ms, 4),
        "evolution_progress": round(tau, 4),
        "metallicity_z": round(z, 6),
        "input_mode": input_mode,
    }


# ===================================================================
# Habitable Zone (Kopparapu et al. 2013)
# ===================================================================

# Polynomial coefficients: (S_eff_sun, a, b, c, d)
# Ref: Kopparapu et al. (2013), ApJ, 765(2), 131, Table 3
# T* = T_eff - 5780 K (note: 5780, not 5772 — per Kopparapu convention)
HABITABLE_ZONE_COEFFICIENTS: dict[str, tuple[float, float, float, float, float]] = {
    "recent_venus": (1.776, 1.4335e-4, 2.9811e-9, -7.5702e-12, -1.1634e-15),
    "runaway_greenhouse": (1.0512, 1.3322e-4, 1.5802e-8, -8.3085e-13, -1.9314e-15),
    "max_greenhouse": (0.3438, 5.8942e-5, 1.6538e-9, -3.0045e-12, -5.1919e-16),
    "early_mars": (0.32, 5.5467e-5, 1.5261e-9, -2.7633e-12, -4.7609e-16),
}

# Kopparapu uses T_ref = 5780 K (not IAU 5772 K)
_T_KOPPARAPU_REF: float = 5780.0


def habitable_zone_boundaries(luminosity: float, t_eff: float) -> dict[str, float]:
    """Compute habitable zone boundaries (Kopparapu et al. 2013).

    Args:
        luminosity: Stellar luminosity in L☉.
        t_eff: Stellar effective temperature in K.

    Returns:
        Dict mapping boundary name to distance in AU.
        Keys: recent_venus_au, runaway_greenhouse_au,
              max_greenhouse_au, early_mars_au.
    """
    t_star = t_eff - _T_KOPPARAPU_REF
    result: dict[str, float] = {}

    for name, (s0, a, b, c, d) in HABITABLE_ZONE_COEFFICIENTS.items():
        s_eff = s0 + a * t_star + b * t_star**2 + c * t_star**3 + d * t_star**4
        d_au = math.sqrt(luminosity / s_eff)
        result[f"{name}_au"] = round(d_au, 6)

    return result


# ===================================================================
# Instellation & equilibrium temperature
# Ref: Seager, S. (2010). Exoplanet Atmospheres. Princeton University Press.
# ===================================================================


def instellation(luminosity: float, distance_au: float) -> float:
    """Compute stellar flux (instellation) at a given distance.

    Args:
        luminosity: Stellar luminosity in L☉.
        distance_au: Distance from star in AU.

    Returns:
        Flux in W/m².
    """
    l_watts = luminosity * L_SUN_W
    d_m = distance_au * AU_M
    return l_watts / (4.0 * math.pi * d_m * d_m)


def instellation_earth_units(luminosity: float, distance_au: float) -> float:
    """Compute instellation relative to Earth's solar constant.

    Args:
        luminosity: Stellar luminosity in L☉.
        distance_au: Distance from star in AU.

    Returns:
        Flux in units of S☉ (Earth's solar constant ≈ 1361 W/m²).
    """
    return luminosity / distance_au**2


def equilibrium_temperature(
    luminosity: float,
    distance_au: float,
    albedo: float = 0.3,
    f_redist: float = 16.0,
) -> float:
    """Compute planetary equilibrium temperature.

    T_eq = (L(1-A) / (f π σ d²))^0.25

    The redistribution factor f accounts for how absorbed stellar energy is
    distributed across the planetary surface before re-radiation:
    - f = 16: full redistribution (uniform temperature, emission from 4πR²).
      Equivalent to T_eq = [S(1-A)/(16σ)]^0.25.
    - f = 8: no redistribution (dayside only, emission from 2πR²).
      Equivalent to T_eq = [S(1-A)/(8σ)]^0.25.

    Ref: Seager, S. (2010). Exoplanet Atmospheres. Princeton University Press.

    Args:
        luminosity: Stellar luminosity in L☉.
        distance_au: Distance from star in AU.
        albedo: Bond albedo (0–1, default 0.3 ≈ Earth).
        f_redist: Heat redistribution factor (16 = full, 8 = dayside only).

    Returns:
        Equilibrium temperature in Kelvin.
    """
    l_watts = luminosity * L_SUN_W
    d_m = distance_au * AU_M
    return math.pow(l_watts * (1.0 - albedo) / (f_redist * math.pi * SIGMA_SB * d_m * d_m), 0.25)


# ===================================================================
# Condensation lines (passive irradiated disk model)
# Ref: Hayashi et al. (1981); Lecar et al. (2006)
# ===================================================================

# Condensation temperatures for common volatiles (K)
CONDENSATION_TEMPS: dict[str, float] = {
    "rock_line": 1500.0,  # Silicates / iron
    "water_snow_line": 170.0,  # H₂O ice
    "co2_ice_line": 70.0,  # CO₂ ice
    "co_snow_line": 20.0,  # CO ice
}

# Base disk temperature at 1 AU for L=1 L☉ (Hayashi et al. 1981)
_T_DISK_1AU: float = 280.0  # K


def condensation_lines(luminosity: float) -> dict[str, float]:
    """Compute condensation line distances for common volatiles.

    d_cond = (280 K / T_cond)² × √(L/L☉)  AU

    Based on passive irradiated protoplanetary disk model.

    Args:
        luminosity: Stellar luminosity in L☉.

    Returns:
        Dict mapping substance name to distance in AU.
    """
    sqrt_l = math.sqrt(luminosity)
    result: dict[str, float] = {}
    for name, t_cond in CONDENSATION_TEMPS.items():
        d = math.pow(_T_DISK_1AU / t_cond, 2) * sqrt_l
        result[f"{name}_au"] = round(d, 6)
    return result
