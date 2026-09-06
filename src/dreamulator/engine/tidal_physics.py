"""Tidal heating and its geodynamic consequence (plate speed) — pure physics.

Implements the Peale & Cassen (1978) equilibrium-tide dissipation power for a
synchronously rotating satellite, plus an empirical scaling from tidal heat
flux to plate speed.  No I/O, no RNG — independently unit-testable.

The plate-speed scaling ``v ∝ q^β`` is an *order-of-magnitude estimate*, not a
precise law: the exponent spans β ∈ [0.5, 1.5] across the literature and the
mapping from heat flux to plate speed is regime-dependent — heat flux alone
does not even guarantee plate tectonics (the Venus paradox).  See
``docs/knowledge/geology/tidal_plate_speed.md`` for the Valencia vs
O'Neill & Lenardic debate and the full reference list.

Defaults anchor on Earth (v=5 cm/yr at q=0.09 W/m² total surface heat flux)
and reproduce ~15 cm/yr for nacrea's ~3× tidal flux with β=1.
"""

from __future__ import annotations

import math

# Physical constants
GRAVITATIONAL_CONSTANT = 6.67430e-11  # m^3 kg^-1 s^-2
EARTH_MASS_KG = 5.972e24  # kg
AU_M = 1.495978707e11  # m

# Solid-body Love numbers (Earth measured values, h₂ ≈ 0.61, k₂ ≈ 0.30).  These
# describe the *material* response to a tidal potential, so they are shared by
# every rocky/icy world (the "same physics" discipline), not tuned per body.
LOVE_NUMBER_H2 = 0.6  # solid-surface deformation
LOVE_NUMBER_K2 = 0.3  # gravitational-potential deformation


def mean_motion_rad_s(mass_primary_kg: float, semi_major_axis_m: float) -> float:
    """Kepler's third law mean motion ``n = sqrt(G M / a³)`` in rad/s."""
    return math.sqrt(GRAVITATIONAL_CONSTANT * mass_primary_kg / semi_major_axis_m**3)


def tidal_heating_power_w(
    *,
    mass_primary_kg: float,
    radius_m: float,
    semi_major_axis_m: float,
    eccentricity: float,
    mean_motion_rad_s: float,
    k2_over_q: float,
) -> float:
    """Tidal dissipation power for a synchronous eccentric satellite.

    Peale & Cassen (1978):
        ``Ė = (21/2) · (k₂/Q) · (G M_p² R⁵ / a⁶) · n · e²``

    Args:
        mass_primary_kg: Host (primary) mass in kg.
        radius_m: Satellite radius in metres.
        semi_major_axis_m: Orbital semi-major axis in metres.
        eccentricity: Orbital eccentricity (dimensionless).
        mean_motion_rad_s: Mean motion ``n = 2π/P`` in rad/s.
        k2_over_q: Tidal dissipation factor ``k₂/Q`` (dimensionless).

    Returns:
        Tidal heating power in watts.
    """
    return (
        (21.0 / 2.0)
        * k2_over_q
        * GRAVITATIONAL_CONSTANT
        * mass_primary_kg**2
        * radius_m**5
        / semi_major_axis_m**6
        * mean_motion_rad_s
        * eccentricity**2
    )


def tidal_heat_flux_w_m2(tidal_heating_w: float, radius_m: float) -> float:
    """Global mean tidal heat flux (power per unit surface area), W/m²."""
    return tidal_heating_w / (4.0 * math.pi * radius_m**2)


def plate_speed_cm_yr(
    tidal_flux_w_m2: float,
    *,
    v_ref_cm_yr: float,
    q_ref_w_m2: float,
    beta: float,
) -> float:
    """Empirical power-law from tidal heat flux to plate speed.

    ``v = v_ref · (q / q_ref)^β``.  See ``docs/knowledge/geology/tidal_plate_speed.md``
    for the literature range (β ∈ [0.5, 1.5]) and the caveats.
    """
    return v_ref_cm_yr * math.pow(tidal_flux_w_m2 / q_ref_w_m2, beta)


def tidal_potential_scale_m(
    mass_primary_kg: float,
    mass_satellite_kg: float,
    radius_m: float,
    semi_major_axis_m: float,
) -> float:
    """Tidal potential length scale ``Z = (M_p / M_m) · R⁴ / a³`` (metres).

    The tidal potential divided by surface gravity is the length scale of every
    tidal deformation (bulge height, ocean equilibrium tide).  See nacrea's
    ``tidal_effects.md`` (Z = 2267 m for Nacrea).
    """
    return (mass_primary_kg / mass_satellite_kg) * radius_m**4 / semi_major_axis_m**3


def ocean_equilibrium_tide_range_m(
    scale_z_m: float,
    eccentricity: float,
    *,
    k2: float = LOVE_NUMBER_K2,
    h2: float = LOVE_NUMBER_H2,
) -> float:
    """Ocean equilibrium-tide peak-to-trough height (metres).

    The ocean's radial response factor is ``(1 + k₂ − h₂)`` (fluid equilibrium;
    tidal_effects.md).  The eccentricity tide breathes radially ∝ r⁻³ with
    r = a(1±e), so the fractional change is ``3e`` and the peak-to-trough ``6e``:

        range = (1 + k₂ − h₂) · Z · 6e
    """
    return (1.0 + k2 - h2) * scale_z_m * 6.0 * eccentricity


def ocean_natural_period_h(radius_m: float, gravity_m_s2: float, ocean_depth_m: float) -> float:
    """Ocean shallow-water natural period ``T = 2πR / √(gH)`` in hours.

    ``H`` is the mean ocean depth; the result is the fundamental seiche/resonance
    period of a global ocean (tidal_effects.md gives Nacrea 58.7 h).
    """
    return 2.0 * math.pi * radius_m / math.sqrt(gravity_m_s2 * ocean_depth_m) / 3600.0


def resonance_factor(natural_period_h: float, tidal_period_h: float) -> float:
    """Resonance amplification ``1 / (1 − (T_nat / T_tide)²)`` for a weakly-damped
    ocean.  Only physical for ``T_nat < T_tide`` (sub-resonant); at or above
    resonance the undamped factor is singular and the caller must not use it.
    """
    ratio = natural_period_h / tidal_period_h
    return 1.0 / (1.0 - ratio**2)


def resonant_tidal_range_m(
    *,
    mass_primary_kg: float,
    mass_satellite_kg: float,
    radius_m: float,
    semi_major_axis_m: float,
    eccentricity: float,
    gravity_m_s2: float,
    ocean_depth_m: float,
    tidal_period_h: float,
    k2: float = LOVE_NUMBER_K2,
    h2: float = LOVE_NUMBER_H2,
) -> float:
    """Resonant tidal range (peak-to-trough, metres) — the equilibrium-tide
    theoretical upper bound amplified by the ocean's shallow-water resonance.

    This is the ~44 m value for Nacrea (tidal_effects.md): a perfect-fluid
    sphere with global resonance.  Actual coastal ranges are topography-limited
    (open ocean 4–12 m, ordinary coasts 10–25 m, funnel estuaries 40–80 m), so
    the fact renders the theoretical bound, not a per-coast value.
    """
    z = tidal_potential_scale_m(mass_primary_kg, mass_satellite_kg, radius_m, semi_major_axis_m)
    equilibrium_range = ocean_equilibrium_tide_range_m(z, eccentricity, k2=k2, h2=h2)
    nat_period = ocean_natural_period_h(radius_m, gravity_m_s2, ocean_depth_m)
    return equilibrium_range * resonance_factor(nat_period, tidal_period_h)
