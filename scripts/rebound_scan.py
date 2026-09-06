#!/usr/bin/env python3
"""2-D stability scan for the Nacrea system (REBOUND).

Sweeps Aegis semi-major axis × satellite-chain scale (with the Galilean resonant
phase fixed: θ1≈0°, θ2≈180° → M1=0, M2=0, M3=270°) and reports, for each grid
point, whether Vigil stays bound — i.e. whether the satellite chain is stable.

The stable boundary is set by Vigil's Hill distance: Vigil/r_H ≲ 0.37 (prograde
stability limit ~0.4 r_H, Hamilton & Burns 1991).  This scan maps the actual
numerical boundary so the 0007 lever values can be pinned.

Usage::

    uv run python scripts/rebound_scan.py
"""

from __future__ import annotations

import numpy as np
import rebound

MEARTH_MSUN = 3.003e-6
_T_END_YR = 20.0  # ~ hundreds of satellite orbits — enough to see escape


def _run_one(a_aegis_au: float, scale: float) -> tuple[float, float]:
    """Return (vigil_over_rH, vigil_e_final) for one (a_aegis, scale) point."""
    sim = rebound.Simulation()
    sim.units = ("yr", "AU", "Msun")

    sim.add(m=0.4665)  # Ignis

    # Giant planets — 1:2:4 Laplace chain; Boreal/Glacis track Aegis outward.
    gal = [0.0, 0.0, np.radians(270.0)]
    sim.add(m=508.5 * MEARTH_MSUN, a=a_aegis_au, e=0.005, M=gal[0])                 # Aegis
    sim.add(m=159.3 * MEARTH_MSUN, a=a_aegis_au * 2 ** (2 / 3), e=0.010, M=gal[1])  # Boreal
    sim.add(m=17.1 * MEARTH_MSUN, a=a_aegis_au * 4 ** (2 / 3), e=0.015, M=gal[2])   # Glacis

    # Satellites — 1:2:4 chain around Aegis, Galilean phase, scaled by `scale`.
    inc = np.radians(9.0)
    sat = [(1.2, 0.00494, 0.002), (0.05, 0.007842, 0.005), (0.03, 0.012448, 0.008)]
    for m_earth, a, e in sat:
        sim.add(
            m=m_earth * MEARTH_MSUN,
            a=a * scale,
            e=e,
            inc=inc,
            M=gal[2] if m_earth == 0.03 else gal[0],  # Vigil gets M3=270°, others M=0
            primary=sim.particles[1],
        )

    sim.move_to_com()
    sim.integrate(_T_END_YR)

    vigil = sim.particles[6]
    e_final = vigil.orbit(primary=sim.particles[1]).e

    # Hill distance: r_H = a_Aegis (M_Aegis / 3 M_star)^(1/3).
    m_aegis_sol = 508.5 * MEARTH_MSUN
    r_h_au = a_aegis_au * (m_aegis_sol / (3.0 * 0.4665)) ** (1 / 3)
    vigil_over_rh = 0.012448 * scale / r_h_au
    return vigil_over_rh, float(e_final)


def main() -> None:
    a_vals = [0.25, 0.26, 0.27, 0.28, 0.29, 0.30, 0.31, 0.32, 0.33]
    scale_vals = [1.00, 0.96, 0.92, 0.88, 0.84, 0.80]

    print(f"Vigil stability grid (t={_T_END_YR:.0f} yr, Galilean phase); cell = final e")
    print(f"  {'a_Aegis ↓ / scale →':<22}" + "".join(f"{s:>9.2f}" for s in scale_vals))
    for a in a_vals:
        row = []
        for scale in scale_vals:
            rh, e = _run_one(a, scale)
            mark = " " if e < 1.0 else "!"
            row.append(f"{e:8.2f}{mark}")
        print(f"  {a:>18.3f} AU ({'rh':<3})" + "".join(row))

    print("\nLegend: cell = Vigil final eccentricity; '!' = escaped (e ≥ 1).")
    print("        scale 1.00 = current satellite radii; 0.88 ≈ Vigil 0.011 AU.")


if __name__ == "__main__":
    main()
