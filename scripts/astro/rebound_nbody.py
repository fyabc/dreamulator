#!/usr/bin/env python3
"""N-body stability scan for the Nacrea 1:2:4 Laplace resonance chains (REBOUND).

Synced to the current ``stellar.yaml`` (K8 Ignis 0.59 M☉, Aegis a=0.3536 AU,
Nacrea a=724,000 km post "0007 微内移").  Scans the initial Laplace resonance
angle

    φ_L = λ_inner − 3·λ_middle + 2·λ_outer

of both the planet chain (Aegis:Boreal:Glacis = 1:2:4 in period) and the
satellite chain (Nacrea:Cadence:Vigil = 1:2:4) to find the stable libration
configuration.  The prior skeleton hardcoded mean anomaly M=0 for every body,
which places φ_L=0 — the unstable saddle of the Laplace resonance — and Vigil
was ejected within ~10 yr while Cadence's eccentricity was pumped ×35.  The
Galilean analogue (Io:Europa:Ganymede) librates around φ_L≈180°, so the scan
checks whether that centre holds here too.

Units: REBOUND with ``sim.units = ("yr", "AU", "Msun")`` sets G=4π², so
``integrate(N)`` advances N sidereal years.

Usage::

    uv run python scripts/astro/rebound_nbody.py
"""

from __future__ import annotations

import numpy as np
import rebound

MEARTH_MSUN = 3.003e-6  # Earth mass in solar masses
M_SUN = 0.59            # Ignis mass (K8), stellar.yaml

# Orbital elements from stellar.yaml — (name, mass/M⊕, a/AU, eccentricity).
PLANETS = [
    ("Aegis", 508.5, 0.3536, 0.030),
    ("Boreal", 159.3, 0.5614, 0.010),
    ("Glacis", 17.1, 0.8911, 0.015),
]
SATELLITES = [
    ("Nacrea", 1.2, 0.00484, 0.0019),
    ("Cadence", 0.05, 0.00769, 0.005),
    ("Vigil", 0.03, 0.01220, 0.008),
]
INC_RAD = np.radians(9.0)  # satellite inclination (Aegis equatorial plane)


def build_nacrea_system(
    phi_planets_deg: float = 180.0,
    phi_satellites_deg: float = 180.0,
) -> rebound.Simulation:
    """Ignis + 1:2:4 planet chain + 1:2:4 satellite chain.

    The inner body of each chain carries the initial phase (M=φ); the middle and
    outer bodies start at conjunction (M=0), so φ_L = φ exactly at t=0.  With
    Ω = ω = 0 everywhere, mean anomaly M equals the mean longitude λ.
    """
    sim = rebound.Simulation()
    sim.units = ("yr", "AU", "Msun")

    sim.add(m=M_SUN)  # Ignis

    # Planets — Aegis carries the phase, Boreal/Glacis start at conjunction.
    sim.add(
        m=PLANETS[0][1] * MEARTH_MSUN, a=PLANETS[0][2], e=PLANETS[0][3],
        Omega=0.0, omega=0.0, M=np.radians(phi_planets_deg),
    )
    for _name, mass, a, e in PLANETS[1:]:
        sim.add(m=mass * MEARTH_MSUN, a=a, e=e, Omega=0.0, omega=0.0, M=0.0)

    aegis = sim.particles[1]
    # Satellites — Nacrea carries the phase, Cadence/Vigil at conjunction.
    sim.add(
        m=SATELLITES[0][1] * MEARTH_MSUN, a=SATELLITES[0][2], e=SATELLITES[0][3],
        inc=INC_RAD, Omega=0.0, omega=0.0, M=np.radians(phi_satellites_deg), primary=aegis,
    )
    for _name, mass, a, e in SATELLITES[1:]:
        sim.add(
            m=mass * MEARTH_MSUN, a=a, e=e, inc=INC_RAD, Omega=0.0, omega=0.0, M=0.0,
            primary=aegis,
        )

    sim.move_to_com()
    return sim


def _mean_longitude(p: rebound.Particle, primary: rebound.Particle) -> float:
    o = p.orbit(primary=primary)
    return (o.Omega + o.omega + o.M) % (2 * np.pi)


def laplace_angles(sim: rebound.Simulation) -> tuple[float, float]:
    """Laplace resonance angle (radians, [0, 2π)) of each 1:2:4 chain.

    Returns ``(φ_planets, φ_satellites)`` =
    ``(λ_Aegis − 3λ_Boreal + 2λ_Glacis, λ_Nacrea − 3λ_Cadence + 2λ_Vigil)``.
    """
    star = sim.particles[0]
    aegis = sim.particles[1]
    lp = [_mean_longitude(sim.particles[i], star) for i in (1, 2, 3)]
    ls = [_mean_longitude(sim.particles[i], aegis) for i in (4, 5, 6)]
    phi_p = (lp[0] - 3 * lp[1] + 2 * lp[2]) % (2 * np.pi)
    phi_s = (ls[0] - 3 * ls[1] + 2 * ls[2]) % (2 * np.pi)
    return phi_p, phi_s


def _libration_stats(series_deg: list[float]) -> tuple[bool, float, float]:
    """Classify a φ_L time series: (circulates, centre°, half-amplitude°).

    Unwraps the angle and reports whether it swept past ~300° (circulation) or
    stayed bounded (libration) around a centre.
    """
    unwrapped = np.unwrap(np.radians(np.asarray(series_deg)))
    excursion = float(np.ptp(unwrapped))
    if excursion > np.radians(300.0):
        return True, 0.0, 0.0
    centre = float(np.mean(unwrapped)) % (2 * np.pi)
    return False, np.degrees(centre), np.degrees(excursion) / 2.0


def report(sim: rebound.Simulation, label: str) -> None:
    names = ["Ignis", "Aegis", "Boreal", "Glacis", "Nacrea", "Cadence", "Vigil"]
    star = sim.particles[0]
    aegis = sim.particles[1]
    phi_p, phi_s = laplace_angles(sim)
    print(f"--- {label} ---")
    print(f"  φ_L planets = {np.degrees(phi_p):6.1f}°   φ_L satellites = {np.degrees(phi_s):6.1f}°")
    for i, p in enumerate(sim.particles):
        if i == 0:
            print(f"  {names[i]:8s} m={p.m:.4f} M☉")
            continue
        primary = aegis if i >= 4 else star
        o = p.orbit(primary=primary)
        print(f"  {names[i]:8s} a={o.a:.5f} AU  e={o.e:.4f}  inc={np.degrees(o.inc):5.1f}°")


def scan_laplace(total_years: float = 100.0, step_deg: float = 30.0, n_out: int = 200) -> None:
    print(f"\n=== Laplace resonance scan (T={total_years} yr, φ₀ step {step_deg:.0f}°) ===\n")
    header = (
        f"{'φ₀':>6}  {'planet chain φ_L':>24}  {'satellite chain φ_L':>27}  "
        f"{'max e':>7}  {'max a_sat(AU)':>13}"
    )
    print(header)
    print("-" * 92)
    dt = total_years / n_out
    for phi0 in range(0, 360, int(step_deg)):
        sim = build_nacrea_system(phi0, phi0)
        star = sim.particles[0]
        aegis = sim.particles[1]
        phi_p: list[float] = []
        phi_s: list[float] = []
        max_e = 0.0
        max_a_sat = 0.0
        for k in range(1, n_out + 1):
            sim.integrate(k * dt)
            pp, ps = laplace_angles(sim)
            phi_p.append(np.degrees(pp))
            phi_s.append(np.degrees(ps))
            for i in range(1, 7):
                o = sim.particles[i].orbit(primary=aegis if i >= 4 else star)
                max_e = max(max_e, o.e)
                if i >= 4:
                    max_a_sat = max(max_a_sat, o.a)
        p_circ, p_centre, p_amp = _libration_stats(phi_p)
        s_circ, s_centre, s_amp = _libration_stats(phi_s)
        p_lab = "circulates" if p_circ else f"librate @ {p_centre:5.0f}° ± {p_amp:4.0f}°"
        s_lab = "circulates" if s_circ else f"librate @ {s_centre:5.0f}° ± {s_amp:4.0f}°"
        print(f"{phi0:5d}°  {p_lab:>24}  {s_lab:>27}  {max_e:7.3f}  {max_a_sat:13.5f}")


def main() -> None:
    # Baseline: the Galilean stable centre φ_L = 180° should librate, not blow up.
    sim = build_nacrea_system(180.0, 180.0)
    report(sim, "t=0 (φ_L=180°)")
    sim.integrate(10.0)
    report(sim, "t=10 yr (φ_L=180°)")

    scan_laplace()


if __name__ == "__main__":
    main()
