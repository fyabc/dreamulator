#!/usr/bin/env python3
"""Minimal N-body skeleton for the Nacrea system (REBOUND).

Sets up Ignis + the 1:2:4 giant-planet Laplace resonance chain
(Aegis/Boreal/Glacis) + the 1:2:4 satellite chain (Nacrea/Cadence/Vigil) and
integrates briefly to verify the system is well-posed — orbits stay bounded and
the resonance holds.  This is the first step of the spin-orbit / Cassini
calibration (today.md 穿插小活); precession-cycle and spin-axis parts are added
later, and the full stability scan (e_Aegis 0.03–0.05) comes after this runs.

Units: REBOUND defaults (G=1, AU / M☉ / yr).

Usage::

    uv run python scripts/rebound_nbody.py
"""

from __future__ import annotations

import numpy as np
import rebound

MEARTH_MSUN = 3.003e-6  # Earth mass in solar masses


def build_nacrea_system() -> rebound.Simulation:
    """Ignis + 1:2:4 giant-planet chain + 1:2:4 satellite chain."""
    sim = rebound.Simulation()
    sim.units = ("yr", "AU", "Msun")

    # Star Ignis — M≈0.4665 M☉ (derived from luminosity 0.0414 L☉).
    sim.add(m=0.4665)

    # Giant planets — 1:2:4 Laplace resonance chain.
    sim.add(m=508.5 * MEARTH_MSUN, a=0.2504, e=0.005)  # Aegis (1.6 M_J)
    sim.add(m=159.3 * MEARTH_MSUN, a=0.3975, e=0.010)  # Boreal (0.5 M_J)
    sim.add(m=17.1 * MEARTH_MSUN, a=0.6310, e=0.015)   # Glacis (~0.054 M_J)

    # Satellites — 1:2:4 Laplace resonance chain around Aegis (index 1).
    inc_rad = 9.0 * np.pi / 180.0
    sim.add(m=1.2 * MEARTH_MSUN, a=0.00494, e=0.002, inc=inc_rad, primary=sim.particles[1])
    sim.add(m=0.05 * MEARTH_MSUN, a=0.007842, e=0.005, inc=inc_rad, primary=sim.particles[1])
    sim.add(m=0.03 * MEARTH_MSUN, a=0.012448, e=0.008, inc=inc_rad, primary=sim.particles[1])

    sim.move_to_com()
    return sim


def report(sim: rebound.Simulation, label: str) -> None:
    names = ["Ignis", "Aegis", "Boreal", "Glacis", "Nacrea", "Cadence", "Vigil"]
    star = sim.particles[0]
    aegis = sim.particles[1]
    print(f"--- {label} ---")
    for i, p in enumerate(sim.particles):
        if i == 0:
            print(f"  {names[i]:8s} m={p.m:.4f} M☉")
            continue
        # Planets (indices 1–3) orbit the star; satellites (4–6) orbit Aegis.
        primary = aegis if i >= 4 else star
        o = p.orbit(primary=primary)
        print(f"  {names[i]:8s} a={o.a:.5f} AU  e={o.e:.4f}  inc={np.degrees(o.inc):5.1f}°")


def main() -> None:
    sim = build_nacrea_system()
    report(sim, "initial")

    # Integrate ~10 yr (≈ 54 Aegis orbits; the satellite chain completes hundreds
    # of orbits) — enough to see whether the resonance holds or blows up.
    sim.integrate(10.0)
    report(sim, f"t={sim.t:.1f} yr")


if __name__ == "__main__":
    main()
