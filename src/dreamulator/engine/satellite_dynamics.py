"""Pure satellite-system dynamics functions — no IO, no RNG.

Stability criteria, J2 secular rates, and constant-Q tidal timescales for
planet–satellite systems.  Distilled from the 2026-09 REBOUND adjudication of
the Nacrea satellite chain; physics, provenance and case-study numbers live in
``docs/knowledge/astrophysics/satellite_system_stability.md`` (criteria) and
``docs/knowledge/astrophysics/orbital-stability.md`` (numerical tooling).

All functions take plain floats in the units named by their suffixes
(``_km``, ``_au``, ``_days``, ``_yr``, ``_m_yr``) and return floats — the
engine layer (``physical_inputs.derive_world_parameters``) is responsible for
unit conversion at the boundary.

References: Gladman (1993) Icarus 106:247; Chambers et al. (1996) Icarus
119:261; Domingos et al. (2006) MNRAS 373:1227; Hamilton & Burns (1991)
Icarus 92:118; Goldreich (1966) Rev. Geophys. 4:411; Lainey et al. (2009)
Nature 459:957; Murray & Dermott (1999) Solar System Dynamics ch.4–6;
Vallado, Fundamentals of Astrodynamics (J2 rates).
"""

from __future__ import annotations

import math

# ---------------------------------------------------------------------------
# Stability criteria
# ---------------------------------------------------------------------------

#: Critical satellite orbit radius in planetary Hill radii (Domingos et al.
#: 2006, restricted elliptic three-body problem).  Planetary eccentricity
#: shrinks both limits (polynomial derating in their paper); the engineering
#: safety lines validated on the Nacrea case are tighter still — prograde
#: ≤0.38 (fast-chaos zone measured below the 0.48 nominal limit: 0.37 r_H
#: survived ≥6000 yr, 0.41 r_H died within 25 yr), retrograde ≤0.5.
PROGRADE_STABILITY_LIMIT_RH: float = 0.48
RETROGRADE_STABILITY_LIMIT_RH: float = 0.93
PROGRADE_SAFETY_LINE_RH: float = 0.38
RETROGRADE_SAFETY_LINE_RH: float = 0.50

#: Minimum separation of an *unlocked* co-orbiting pair in mutual Hill radii
#: (Gladman 1993: 2√3 for circular orbits; e>0 widens the requirement —
#: Chambers et al. 1996).  Resonantly *locked* pairs can sit far tighter
#: (GJ 876's 2:1 pair lives at ~3.2), but locking cannot be assumed for a
#: cold system without a migration/tidal history.
MIN_SEPARATION_MUTUAL_HILL: float = 2.0 * math.sqrt(3.0)
SAFE_SEPARATION_MUTUAL_HILL: float = 10.0


def hill_radius_km(a_p_km: float, m_p_earth: float, m_star_solar: float, e_p: float = 0.0) -> float:
    """Planetary Hill radius r_H = a_p (m_p / 3 M*)^(1/3), at periapsis if e_p>0.

    Masses: planet in M⊕, star in M☉ (converted via M⊕ = 3.003e-6 M☉).
    """
    m_p_solar = m_p_earth * 3.003e-6
    return float(a_p_km * (1.0 - e_p) * (m_p_solar / (3.0 * m_star_solar)) ** (1.0 / 3.0))


def mutual_hill_separation(
    a_inner_km: float,
    a_outer_km: float,
    m_inner_earth: float,
    m_outer_earth: float,
    m_primary_earth: float,
) -> float:
    """Pair separation Δa in mutual Hill radii (compare against the criteria above)."""
    mean_mass_solar = (m_inner_earth + m_outer_earth) * 3.003e-6
    primary_solar = m_primary_earth * 3.003e-6
    r_hm = (
        ((mean_mass_solar) / (3.0 * primary_solar)) ** (1.0 / 3.0) * 0.5 * (a_inner_km + a_outer_km)
    )
    return float((a_outer_km - a_inner_km) / r_hm)


def stability_limit_km(
    a_p_km: float,
    m_p_earth: float,
    m_star_solar: float,
    e_p: float = 0.0,
    retrograde: bool = False,
) -> float:
    """Critical satellite semi-major axis (km) beyond which stellar tides unbind it."""
    limit = RETROGRADE_STABILITY_LIMIT_RH if retrograde else PROGRADE_STABILITY_LIMIT_RH
    return limit * hill_radius_km(a_p_km, m_p_earth, m_star_solar, e_p)


# ---------------------------------------------------------------------------
# Constant-Q tides (planet-side migration + combined e-damping)
# ---------------------------------------------------------------------------

#: Tidal-frequency convention factor f for the constant-Q formulas: cited
#: rates differ by whether Q is defined at the principal tidal frequency or
#: includes the (Ω_p−n)/n enhancement — the honest band is f ∈ [1, 6.5]
#: (see knowledge doc §5).  Mid value used unless stated.
TIDAL_CONVENTION_FACTOR: float = 3.0


def tidal_migration_rate_m_yr(
    k2_over_q: float,
    m_sat_earth: float,
    m_primary_earth: float,
    r_primary_km: float,
    a_sat_km: float,
    period_days: float,
    convention_factor: float = TIDAL_CONVENTION_FACTOR,
) -> float:
    """da/dt (m/yr) from planet-side tides in the super-synchronous regime.

    ȧ/a = 3 (k₂p/Qp)(m_s/M_p)(R_p/a)⁵ n × f (Murray & Dermott 1999 ch.4,
    constant-Q leading order; ω_p > n ⇒ outward).  Always state which f a
    quoted number used — the band spans ×6.5.
    """
    n = 2.0 * math.pi / (period_days / 365.25)  # rad/yr
    rate_per_yr = (
        3.0
        * k2_over_q
        * (m_sat_earth / m_primary_earth)
        * (r_primary_km / a_sat_km) ** 5
        * n
        * convention_factor
    )
    return rate_per_yr * a_sat_km * 1000.0  # km/yr → m/yr


def tidal_e_damping_timescale_yr(
    k2_over_q_primary: float,
    k2_over_q_sat: float,
    m_sat_earth: float,
    m_primary_earth: float,
    r_primary_km: float,
    r_sat_km: float,
    a_sat_km: float,
    period_days: float,
) -> float:
    """τ_e = e/|ė| (yr), planet-side + satellite-side constant-Q tides combined.

    ė/e = −(21/2) n [(k₂p/Qp)(m_s/M_p)(R_p/a)⁵ + (k₂s/Qs)(M_p/m_s)(R_s/a)⁵]
    (circular-orbit leading order; adequate at e ≲ 0.1 — it *underestimates*
    damping at high e, i.e. stays conservative for survival verdicts).
    """
    n = 2.0 * math.pi / (period_days / 365.25)  # rad/yr
    rate = (
        10.5
        * n
        * (
            k2_over_q_primary * (m_sat_earth / m_primary_earth) * (r_primary_km / a_sat_km) ** 5
            + k2_over_q_sat * (m_primary_earth / m_sat_earth) * (r_sat_km / a_sat_km) ** 5
        )
    )
    return 1.0 / rate if rate > 0.0 else float("inf")


# ---------------------------------------------------------------------------
# J2 secular rates and the Laplace plane
# ---------------------------------------------------------------------------


def j2_apsidal_precession_period_yr(
    j2: float,
    r_primary_km: float,
    a_sat_km: float,
    period_days: float,
    e: float = 0.0,
    i_eq_deg: float = 0.0,
) -> float:
    """Period (yr) of the J2-driven apsidal precession ϖ = Ω + ω.

    Vallado combined rate for inclination i_eq relative to the primary's
    equator:  ϖ̇ = (3/4) J2 (R/p)² n (4 − 5 sin²i_eq − 2 cos i_eq),
    p = a(1−e²).  Equatorial prograde (i_eq=0) gives the classic
    (3/2) J2 (R/a)² n; equatorial retrograde (i_eq=180°) is 3× faster.
    """
    n_per_yr = 365.25 / period_days * 2.0 * math.pi
    p_km = a_sat_km * (1.0 - e * e)
    i = math.radians(i_eq_deg)
    fac = 4.0 - 5.0 * math.sin(i) ** 2 - 2.0 * math.cos(i)
    rate = 0.75 * j2 * (r_primary_km / p_km) ** 2 * n_per_yr * fac
    return 2.0 * math.pi / abs(rate)


def laplace_radius_km(
    j2: float, r_primary_km: float, a_p_km: float, m_p_earth: float, m_star_solar: float
) -> float:
    """Laplace radius r_L = (2 J2 R_p² a_p³ m_p/M*)^(1/5).

    Inside r_L the planetary quadrupole dominates and satellite orbits relax
    onto the equatorial plane; outside, the stellar torque wins and the
    equatorial configuration is a forced state (free-inclination wobble that
    tides damp toward the ecliptic).
    """
    m_ratio = (m_p_earth * 3.003e-6) / m_star_solar
    return float((2.0 * j2 * r_primary_km**2 * a_p_km**3 * m_ratio) ** 0.2)


def spin_precession_period_yr(
    j2: float,
    c_over_mr2: float,
    spin_period_days: float,
    obliquity_deg: float,
    m_primary_earth: float,
    satellites: list[tuple[float, float]],
) -> float:
    """Planetary spin-axis precession period driven by its satellites (yr).

    α = (3/2) Σ_s n_s² (m_s/(M_p+m_s)) ((C−A)/C) cos θ / ω_p, with the
    quadrupole coefficient (C−A)/C = J2 / (C/MR²) and θ the obliquity
    (Murray & Dermott 1999 §5.9).  For Nacrea-on-Aegis (J2=0.008, C/MR²=0.26,
    spin 0.4167 d) this gives ~604 yr — the ~550 yr design value sits inside
    the J2 uncertainty band (J2 0.006–0.010 → 806–645... i.e. 490–816 yr
    across the full Darwin–Radau range).  ``satellites``: (m_earth,
    period_days) pairs; the stellar torque on the bulge (~Myr-scale term at
    these distances) is omitted.
    """
    omega_p = 2.0 * math.pi / (spin_period_days / 365.25)  # rad/yr
    ca_over_c = j2 / c_over_mr2
    alpha = 0.0  # rad/yr
    for m_s_earth, period_days in satellites:
        n = 2.0 * math.pi * 365.25 / period_days  # rad/yr
        alpha += 1.5 * n * n * (m_s_earth / (m_primary_earth + m_s_earth)) * ca_over_c
    alpha *= math.cos(math.radians(obliquity_deg)) / omega_p
    return 2.0 * math.pi / alpha if alpha > 0.0 else float("inf")
