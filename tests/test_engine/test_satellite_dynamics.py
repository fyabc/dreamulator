"""Unit tests for engine/satellite_dynamics.py — pure-function analytics.

Every anchor value was cross-validated during the 2026-09 REBOUND adjudication
of the Nacrea satellite chain (numerical integration and/or hand calculation;
see docs/knowledge/astrophysics/satellite_system_stability.md for provenance):

- Hill radius / separations: Aegis system values and the Io–Europa reference.
- J2 precession periods: match the Lie-splitting operator in
  scripts/astro/rebound_nbody.py to 0.00% (prograde 73.9 yr, retrograde 24.6 yr).
- Laplace radius: hand-derived 5.0e5 km for Aegis (stellar torque ~13× the
  quadrupole at Nacrea's distance).
- Spin precession: ~604 yr for Nacrea-on-Aegis at J2=0.008 — the ~550 yr
  design value sits inside the J2 uncertainty band.
- Tidal migration/damping: 0.0073 m/yr and τ_e ≈ 1.4 Myr at the P-B package
  parameters (Q_p = 5e6, satellite k2/Q = 0.003).
"""

from __future__ import annotations

import math

from dreamulator.engine.satellite_dynamics import (
    hill_radius_km,
    j2_apsidal_precession_period_yr,
    laplace_radius_km,
    mutual_hill_separation,
    spin_precession_period_yr,
    stability_limit_km,
    tidal_e_damping_timescale_yr,
    tidal_migration_rate_m_yr,
)

# Aegis system constants (landed stellar.yaml)
AU_KM = 1.496e8
A_AEGIS_KM = 0.3536 * AU_KM
M_AEGIS = 508.5
M_IGNIS = 0.59
R_AEGIS = 71355.0
A_NACREA = 724000.0
P_NACREA = 3.147
M_NACREA = 1.2
R_NACREA = 6817.0


class TestHillGeometry:
    def test_aegis_hill_radius(self) -> None:
        # Hand calc: 0.03266 AU = 4.886e6 km (with e_p=0.03)
        r_h = hill_radius_km(A_AEGIS_KM, M_AEGIS, M_IGNIS, e_p=0.03)
        assert abs(r_h / 4.886e6 - 1.0) < 0.01

    def test_aegis_hill_radius_circular(self) -> None:
        r_h = hill_radius_km(A_AEGIS_KM, M_AEGIS, M_IGNIS)
        assert abs(r_h / 5.037e6 - 1.0) < 0.01

    def test_nacrea_cadence_separation_marginal(self) -> None:
        # The architecture-killer number: 2:1 pair at only ~4.9 mutual Hill radii
        sep = mutual_hill_separation(724000.0, 1150000.0, M_NACREA, 0.05, M_AEGIS)
        assert abs(sep / 4.86 - 1.0) < 0.02

    def test_io_europa_separation_safe(self) -> None:
        # Galilean reference: ~15.8 mutual Hill radii
        sep = mutual_hill_separation(421800.0, 671100.0, 0.0150, 0.0080, 317.8)
        assert abs(sep / 15.8 - 1.0) < 0.02

    def test_stability_limits(self) -> None:
        # Domingos et al. 2006: prograde 0.48, retrograde 0.93 (circular planet)
        pro = stability_limit_km(A_AEGIS_KM, M_AEGIS, M_IGNIS, retrograde=False)
        ret = stability_limit_km(A_AEGIS_KM, M_AEGIS, M_IGNIS, retrograde=True)
        assert abs(pro / 2.418e6 - 1.0) < 0.01
        assert abs(ret / 4.684e6 - 1.0) < 0.01
        assert ret > pro


class TestJ2Secular:
    def test_nacrea_prograde_precession(self) -> None:
        # REBOUND Lie-splitting operator validation: 73.9 yr (0.00% deviation)
        t = j2_apsidal_precession_period_yr(0.008, R_AEGIS, A_NACREA, P_NACREA)
        assert abs(t / 73.9 - 1.0) < 0.01

    def test_retrograde_three_times_faster(self) -> None:
        # Vallado equatorial retrograde: factor 4.5 vs 1.5 → 24.6 yr
        t = j2_apsidal_precession_period_yr(
            0.008, R_AEGIS, A_NACREA, P_NACREA, e=0.0, i_eq_deg=180.0
        )
        assert abs(t / 24.6 - 1.0) < 0.01

    def test_laplace_radius(self) -> None:
        # Hand calc: 5.0e5 km — Nacrea at 1.44 r_L (stellar torque dominates)
        r_l = laplace_radius_km(0.008, R_AEGIS, A_AEGIS_KM, M_AEGIS, M_IGNIS)
        assert abs(r_l / 5.0e5 - 1.0) < 0.05
        assert r_l < A_NACREA  # Nacrea is outside: forced 9° configuration


class TestSpinPrecession:
    def test_aegis_spin_precession_from_nacrea(self) -> None:
        # Hand-verified M&D §5.9 formula: ~604 yr at J2=0.008
        t = spin_precession_period_yr(
            j2=0.008,
            c_over_mr2=0.26,
            spin_period_days=0.4167,
            obliquity_deg=9.0,
            m_primary_earth=M_AEGIS,
            satellites=[(M_NACREA, P_NACREA)],
        )
        assert abs(t / 604.0 - 1.0) < 0.05

    def test_design_value_550yr_inside_j2_band(self) -> None:
        # The ~550 yr design claim must sit inside the Darwin–Radau J2 range
        periods = [
            spin_precession_period_yr(
                j2=j2,
                c_over_mr2=0.26,
                spin_period_days=0.4167,
                obliquity_deg=9.0,
                m_primary_earth=M_AEGIS,
                satellites=[(M_NACREA, P_NACREA), (0.05, 6.29), (0.03, 12.59)],
            )
            for j2 in (0.006, 0.008, 0.010)
        ]
        assert min(periods) < 550.0 < max(periods)
        # Nacrea dominates the torque (outer moons add <2%)
        assert all(math.isfinite(p) for p in periods)


class TestConstantQTides:
    def test_migration_rate_pb_package(self) -> None:
        # Q_p=5e6 (k2/Q=7e-8), f=3: 0.0073 m/yr — the revised doc value ~0.8 cm/yr
        rate = tidal_migration_rate_m_yr(7.0e-8, M_NACREA, M_AEGIS, R_AEGIS, A_NACREA, P_NACREA)
        assert abs(rate / 0.0073 - 1.0) < 0.1

    def test_migration_convention_band(self) -> None:
        # f ∈ [1, 6.5] spans ×6.5 — quoted numbers must state the convention
        lo = tidal_migration_rate_m_yr(
            7.0e-8, M_NACREA, M_AEGIS, R_AEGIS, A_NACREA, P_NACREA, convention_factor=1.0
        )
        hi = tidal_migration_rate_m_yr(
            7.0e-8, M_NACREA, M_AEGIS, R_AEGIS, A_NACREA, P_NACREA, convention_factor=6.5
        )
        assert abs(hi / lo - 6.5) < 0.01

    def test_e_damping_satellite_side_dominates(self) -> None:
        # τ_e ≈ 1.4 Myr for Nacrea (Q_s=100 side dominates at Q_p=5e6)
        tau = tidal_e_damping_timescale_yr(
            7.0e-8, 0.003, M_NACREA, M_AEGIS, R_AEGIS, R_NACREA, A_NACREA, P_NACREA
        )
        assert 1.0e6 < tau < 2.0e6
        # planet-side alone is negligible at weak dissipation (>10 Gyr)
        tau_p = tidal_e_damping_timescale_yr(
            7.0e-8, 0.0, M_NACREA, M_AEGIS, R_AEGIS, R_NACREA, A_NACREA, P_NACREA
        )
        assert tau_p > 1.0e10
