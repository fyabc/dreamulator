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
