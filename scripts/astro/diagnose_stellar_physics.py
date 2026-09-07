#!/usr/bin/env python3
"""Diagnose stellar-engine relations against real main-sequence data.

Checks three things for the dreamulator stellar engine
(`src/dreamulator/engine/stellar_physics.py`):

1. Self-consistency: M=1, age=4.6 Gyr, [Fe/H]=0 -> L=1, R=1, T=5778.
2. Age evolution: the Sun's L/R/T at ZAMS (tau=0) vs current (tau=0.46).
   Real Sun: L 0.70->1.0, R 0.88->1.0, T 5630->5778 (T *increases* with age).
3. Mass-L/Mass-R/Mass-T relations vs Mamajek-style reference values.

Run::

    uv run python scripts/astro/diagnose_stellar_physics.py
"""

from __future__ import annotations

from dreamulator.engine import stellar_physics as sp

# (M, L, R, T, spectral) — Mamajek-style main-sequence reference (rough).
_REF = [
    (0.40, 0.020, 0.42, 3400, "M2"),
    (0.50, 0.060, 0.53, 3750, "M0"),
    (0.54, 0.060, 0.55, 3800, "M0/K9"),
    (0.60, 0.100, 0.62, 3950, "K8"),
    (0.65, 0.140, 0.66, 4150, "K7"),
    (0.70, 0.200, 0.70, 4250, "K6"),
    (0.80, 0.400, 0.80, 4550, "K3"),
    (1.00, 1.000, 1.00, 5778, "G2"),
]


def _engine_at(mass: float, tau: float = sp._TAU_SUN, z: float = 1.0) -> tuple[float, float, float]:
    lum_z = sp.mass_luminosity_zams(mass)
    r_z = sp.mass_radius_zams(mass)
    lum, r = sp.apply_age_metallicity(lum_z, r_z, tau, z)
    t = sp.effective_temperature(lum, r)
    return lum, r, t


def main() -> None:
    print("=" * 68)
    print("1. Self-consistency (Sun: M=1, tau=0.46, [Fe/H]=0)")
    lum, r, t = _engine_at(1.0)
    print(f"   L={lum:.4f}  R={r:.4f}  T={t:.1f} K   (expect 1.0, 1.0, 5778)")

    print("=" * 68)
    print("2. Age evolution of the Sun (tau=0 vs tau=0.46)")
    lum0, r0, t0 = _engine_at(1.0, tau=0.0)
    lum46, r46, t46 = _engine_at(1.0, tau=0.46)
    print(f"   engine  tau=0 : L={lum0:.3f}  R={r0:.3f}  T={t0:.0f} K")
    print(f"   engine  tau=.46: L={lum46:.3f}  R={r46:.3f}  T={t46:.0f} K")
    print("   real    tau=0 : L=0.70   R=0.88   T=5630 K   (ZAMS)")
    print("   real    tau=.46: L=1.00   R=1.00   T=5778 K")
    print(f"   -> engine T drifts {t46 - t0:+.0f} K with age; real Sun drifts +148 K "
          f"(engine sign is {'WRONG' if (t46 - t0) < 0 else 'right'})")

    print("=" * 68)
    print("3. Mass relations vs reference (tau=0.46, [Fe/H]=0)")
    print(f"   {'M':>5} {'L_eng':>6} {'L_ref':>6} {'R_eng':>6} {'R_ref':>6} "
          f"{'T_eng':>6} {'T_ref':>6} {'sp_ref':>7}")
    for m, lr, rr, tr, sptype in _REF:
        lum, r, t = _engine_at(m)
        print(f"   {m:5.2f} {lum:6.3f} {lr:6.3f} {r:6.3f} {rr:6.3f} {t:6.0f} {tr:6.0f} {sptype:>7}")

    print("=" * 68)
    print("4. Nacrea Ignis (M from L=0.0745 inversion) at age 5.9 Gyr")
    m_ignis = sp.invert_mass_from_luminosity(0.0745, age_gyr=5.9)
    tau_ignis = sp.evolution_progress(5.9, m_ignis)
    lum, r, t = _engine_at(m_ignis, tau=tau_ignis)
    print(f"   M={m_ignis:.4f}  tau={tau_ignis:.3f}  L={lum:.4f}  R={r:.4f}  T={t:.1f} K")
    print(f"   ref for M={m_ignis:.2f}: T~3800-3900 K (M0/K9), not {t:.0f} K")


if __name__ == "__main__":
    main()
