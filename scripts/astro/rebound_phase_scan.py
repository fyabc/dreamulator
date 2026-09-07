#!/usr/bin/env python3
"""Phase scan for the Nacrea 1:2:4 satellite resonance (REBOUND).

Sweeps the two resonant angles θ1 = λ1 − 2λ2 and θ2 = λ2 − 2λ3 (the 2:1 inner /
outer angles of the Laplace chain, periapsis set to 0) to find which mean-anomaly
configuration keeps Vigil bound — i.e. the stable libration centre.

Parameterisation (mean longitude λ = M with ϖ=0):
    M1 = θ1,  M2 = 0,  M3 = −θ2/2.

Usage::

    uv run python scripts/astro/rebound_phase_scan.py
"""

from __future__ import annotations

import numpy as np
import rebound

MEARTH_MSUN = 3.003e-6
_T_END_YR = 20.0


def _run(a_aegis_au: float, scale: float, theta1_deg: float, theta2_deg: float) -> float:
    """Return Vigil's final eccentricity for one phase point."""
    sim = rebound.Simulation()
    sim.units = ("yr", "AU", "Msun")
    sim.add(m=0.4665)

    # Planet chain M=0 (kept out of the phase sweep for now — its own phase is a
    # separate question).
    sim.add(m=508.5 * MEARTH_MSUN, a=a_aegis_au, e=0.005)
    sim.add(m=159.3 * MEARTH_MSUN, a=a_aegis_au * 2 ** (2 / 3), e=0.010)
    sim.add(m=17.1 * MEARTH_MSUN, a=a_aegis_au * 4 ** (2 / 3), e=0.015)

    m1 = np.radians(theta1_deg)
    m2 = 0.0
    m3 = -np.radians(theta2_deg) / 2.0
    inc = np.radians(9.0)
    for m_earth, a, e, mean_anom in [
        (1.2, 0.00494, 0.002, m1),
        (0.05, 0.007842, 0.005, m2),
        (0.03, 0.012448, 0.008, m3),
    ]:
        sim.add(
            m=m_earth * MEARTH_MSUN,
            a=a * scale,
            e=e,
            inc=inc,
            M=mean_anom,
            primary=sim.particles[1],
        )

    sim.move_to_com()
    sim.integrate(_T_END_YR)
    return float(sim.particles[6].orbit(primary=sim.particles[1]).e)


def _grid(a_aegis_au: float, scale: float) -> None:
    thetas = [0.0, 90.0, 180.0, 270.0]
    print(f"\n=== a_Aegis={a_aegis_au:.3f} AU, scale={scale:.2f} (Vigil/r_H="
          f"{0.012448 * scale / (a_aegis_au * 0.10296):.2f}) ===")
    header = "    θ1 \\ θ2  " + "".join(f"{t:>9.0f}" for t in thetas)
    print(header)
    for t1 in thetas:
        row = []
        for t2 in thetas:
            e = _run(a_aegis_au, scale, t1, t2)
            mark = "!" if e >= 1.0 else " "
            row.append(f"{e:8.2f}{mark}")
        print(f"    {t1:>6.0f}   " + "".join(row))


def main() -> None:
    print(f"Vigil final eccentricity (t={_T_END_YR:.0f} yr); '!' = escaped (e≥1)")
    _grid(0.2504, 1.00)  # current configuration (Vigil 0.48 r_H)
    _grid(0.288, 0.88)   # 0007 tentative plan (Aegis +15%, satellites −12%)


if __name__ == "__main__":
    main()
