#!/usr/bin/env python3
"""N-body verification of the LANDED Nacrea system (REBOUND).

Reads the authoritative ``stellar.yaml`` (orbits + body masses in one file) and
integrates the exact landed configuration — no hardcoded elements, no phase
parameterisation.  The astronomy setting is final (period cascade 3.147,
Nacrea e=0.0018, Aegis e=0.03, Vigil M=270° Galilean phase); this script's job
is now *verification and quantification*, not exploration:

  1. dynamical stability of the locked 1:2:4 chains over Myr timescales,
  2. eccentricity pumping ranges vs the landed equilibrium values,
  3. Vigil's Hill-radius safety margin (landed at 0.37 r_H, prograde limit
     ~0.4–0.49 r_H, Hamilton & Burns 1991 / Domingos et al. 2006),
  4. Laplace-angle behaviour (libration centre/amplitude vs circulation),
  5. apsidal/nodal precession periods for the long-cycle narrative numbers
     (Aegis periapsis ~1.3 kyr design value, roadmap tech debt 22).

Scope limits (pure gravitational point-mass N-body):
  - no tides — the forced-eccentricity *equilibrium* (resonance pumping vs
    tidal damping) cannot be closed here; this script measures the pumping
    side, tidal_physics.py the damping side;
  - no planetary J2 — the 4.7-yr Laplace-plane wobble of the satellite orbits
    needs Aegis's quadrupole; point-mass runs only capture the stellar-torque
    part of the nodal precession;
  - no spin axes — the Cassini-state claim stays theoretical
    (orbital_dynamics.md);
  - minor satellites (Boreal/Glacis/Crucible/Sentinel moons) excluded — local
    Hill-sphere questions whose ~0.3–8 d periods would shrink dt ~20×.

Integrator: **IAS15 only** while satellites are included — WHFast/MERCURIUS
solve Kepler steps around the central star (Wisdom–Holman mapping), but the
satellites orbit Aegis; WHFast diverges within ~250 yr here (verified
2026-09-08, vigil e → 10³ while IAS15 stays clean).  Long horizons are
therefore IAS15-throughput-bound (~tens of kyr per hour, benchmark below).

J2 & tides (``--j2`` / ``--tides``): both effects are secular (74–1879 yr vs
orbital 3–13 d), so they enter as exact analytic kicks between ≤1-yr IAS15
point-mass chunks (Lie splitting) — see the operator functions for the rates,
constants and provenance, and for why ``additional_forces`` is not used.

Modes::

    uv run python scripts/astro/rebound_nbody.py                 # landed: IAS15 20 kyr + MEGNO
    uv run python scripts/astro/rebound_nbody.py --t-end 1e5     # longer horizon (hours)
    uv run python scripts/astro/rebound_nbody.py --with-extras   # + Ember/Crucible/Sentinel
    uv run python scripts/astro/rebound_nbody.py --j2 0.008 --tides  # + secular J2 & tides
    uv run python scripts/astro/rebound_nbody.py --baseline      # 10 yr IAS15 sanity run
    uv run python scripts/astro/rebound_nbody.py --sat-scan      # θ1×θ2 satellite phase sweep
    uv run python scripts/astro/rebound_nbody.py --scan          # legacy Laplace-phase scan

Units: REBOUND with ``sim.units = ("yr", "AU", "Msun")`` sets G=4π², so
``integrate(N)`` advances N sidereal years.  Time series are saved to
``private/tmp/rebound_landed.npz`` (gitignored) for follow-up analysis.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np
import rebound

MEARTH_MSUN = 3.003e-6  # Earth mass in solar masses

_STAR = "star"
_CHAIN = ("planet_aegis", "planet_boreal", "planet_glacis")
_SATS = ("satellite_nacrea", "satellite_cadence", "satellite_vigil")
_EXTRAS = ("planet_ember", "planet_crucible", "planet_sentinel")

_STELLAR_YAML_RELPATH = "data/worlds/nacrea/layers/astronomy/input/stellar.yaml"

# Instability guards (abort long runs early instead of integrating garbage).
_VIGIL_E_MAX = 0.6
_VIGIL_RH_MAX = 0.55
_ANY_E_MAX = 0.9

# ── J2 & tides (secular operator splitting) ──────────────────────────
#: Aegis J2 — Darwin–Radau estimate from the landed spin (P=0.4167 d → q=0.055):
#: J2 ≈ (0.10–0.17)·q for a centrally-condensed 1.6 M_J body (Jupiter reference:
#: J2/q = 0.165, less condensed).  Nominal 0.008; experiments sweep 0.006–0.010.
_J2_NOMINAL = 0.008

# Constant-Q tidal dissipation (Murray & Dermott 1999 ch. 4).  Provenance:
#   Aegis  — gas-giant analogue: k2p = 0.35 (Jupiter 0.379), Qp = 1e5 (measured
#            lower bound; plausible range 1e4–1e6 → τ_e uncertain by ×10).
#   Nacrea — landed setting: k2 = 0.30, Q = 100 (physical_params.md, Earth values).
#   Cadence/Vigil — icy moons: k2 = 0.25, Q = 100 (Europa/Enceladus-like;
#            NOT in the yaml — assumption to revisit at adjudication).
_K2Q_AEGIS = 0.35 / 1.0e5
_SAT_K2Q = {
    "satellite_nacrea": 0.30 / 100.0,
    "satellite_cadence": 0.25 / 100.0,
    "satellite_vigil": 0.25 / 100.0,
}
_AU_KM = 1.496e8


def _find_project_root() -> Path:
    d = Path(__file__).resolve().parent
    while d != d.parent:
        if (d / "pyproject.toml").exists():
            return d
        d = d.parent
    return Path.cwd()


# ---------------------------------------------------------------------------
# stellar.yaml → system description
# ---------------------------------------------------------------------------


def load_system(yaml_path: Path | None = None) -> dict:
    """Parse stellar.yaml into {'star_m': M☉, 'bodies': {id: elements+mass}}.

    Joins the ``orbits`` list (elements, keyed by body_id) with the ``bodies``
    list (``mass_earth``, keyed by id).  Angles converted to radians.
    """
    import yaml

    path = yaml_path or (_find_project_root() / _STELLAR_YAML_RELPATH)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    star_m = float(data["stars"][0]["mass"])
    masses = {b["id"]: float(b.get("mass_earth", 0.0)) for b in data["bodies"]}
    radii = {b["id"]: float(b.get("radius_km", 0.0)) for b in data["bodies"]}
    tilts = {b["id"]: float(b.get("axial_tilt_deg", 0.0)) for b in data["bodies"]}
    bodies: dict[str, dict] = {}
    for o in data["orbits"]:
        bid = o["body_id"]
        bodies[bid] = {
            "parent": o["parent_id"],
            "m_earth": masses.get(bid, 0.0),
            "radius_km": radii.get(bid, 0.0),
            "axial_tilt_deg": tilts.get(bid, 0.0),
            "a": float(o["semi_major_axis_au"]),
            "e": float(o["eccentricity"]),
            "inc": np.radians(float(o.get("inclination_deg", 0.0))),
            "Omega": np.radians(float(o.get("longitude_ascending_node_deg", 0.0))),
            "omega": np.radians(float(o.get("argument_of_periapsis_deg", 0.0))),
            "M": np.radians(float(o.get("mean_anomaly_epoch_deg", 0.0))),
        }
    return {"star_m": star_m, "bodies": bodies}


def _add_body(sim: rebound.Simulation, b: dict, primary: rebound.Particle | None = None) -> None:
    kwargs = dict(
        m=b["m_earth"] * MEARTH_MSUN,
        a=b["a"],
        e=b["e"],
        inc=b["inc"],
        Omega=b["Omega"],
        omega=b["omega"],
        M=b["M"],
    )
    if primary is not None:
        kwargs["primary"] = primary
    sim.add(**kwargs)


def build_landed_system(
    sysdata: dict, with_extras: bool = False
) -> tuple[rebound.Simulation, dict[str, int]]:
    """The exact stellar.yaml configuration: star + chain planets + Aegis satellites.

    ``with_extras`` adds Ember/Crucible/Sentinel (star-orbiting, well separated
    — a robustness check, not part of the resonance question).
    """
    sim = rebound.Simulation()
    sim.units = ("yr", "AU", "Msun")
    sim.add(m=sysdata["star_m"])
    idx = {_STAR: 0}

    bodies = sysdata["bodies"]
    planet_order: list[str] = []
    if with_extras:
        planet_order += [_EXTRAS[0], _EXTRAS[1]]  # Ember, Crucible (inner)
    planet_order += list(_CHAIN)
    if with_extras:
        planet_order.append(_EXTRAS[2])  # Sentinel (outer)

    for bid in planet_order:
        _add_body(sim, bodies[bid])
        idx[bid] = len(sim.particles) - 1

    aegis = sim.particles[idx["planet_aegis"]]
    for bid in _SATS:
        _add_body(sim, bodies[bid], primary=aegis)
        idx[bid] = len(sim.particles) - 1

    sim.move_to_com()
    return sim, idx


def build_sat_phase_system(
    sysdata: dict, m_nacrea: float, m_cadence: float, m_vigil: float
) -> rebound.Simulation:
    """Landed planets (M from yaml) + satellites at prescribed mean anomalies (rad).

    For the θ1×θ2 resonant-phase sweep: θ1 = λ_N − 2λ_C, θ2 = λ_C − 2λ_V are
    realised by M_N = θ1, M_C = 0, M_V = −θ2/2 (ϖ = Ω = 0, so λ = M).
    """
    sim = rebound.Simulation()
    sim.units = ("yr", "AU", "Msun")
    sim.add(m=sysdata["star_m"])
    bodies = sysdata["bodies"]
    for bid in _CHAIN:
        _add_body(sim, bodies[bid])
    aegis = sim.particles[len(sim.particles) - 3]
    for bid, m_val in zip(_SATS, (m_nacrea, m_cadence, m_vigil), strict=True):
        b = dict(bodies[bid])
        b["M"] = m_val
        _add_body(sim, b, primary=aegis)
    sim.move_to_com()
    return sim


def sat_phase_scan(sysdata: dict, t_end: float = 300.0, grid: int = 6) -> None:
    """Sweep satellite-chain resonant phases (θ1, θ2) — planets stay landed.

    Per grid point: survive/die, death time, max satellite e, final Vigil a/r_H,
    φ_L(sat) libration class.  The landed configuration is (θ1, θ2) = (0°, 180°).
    """
    print(f"=== Satellite-chain phase scan (T={t_end:g} yr, {grid}×{grid} in θ1×θ2) ===")
    print(f"{'θ1':>5} {'θ2':>5}  {'outcome':>14}  {'max e_sat':>9}  {'Vigil a/r_H':>11}  φ_L(sat)")
    print("-" * 78)
    step = 360.0 / grid
    results: list[tuple] = []
    for i1 in range(grid):
        th1 = i1 * step
        for i2 in range(grid):
            th2 = i2 * step
            sim = build_sat_phase_system(sysdata, np.radians(th1), 0.0, np.radians(-th2 / 2.0))
            sim.integrator = "ias15"
            max_e = 0.0
            death_t = None
            phi_series: list[float] = []
            n_chunks = int(t_end / 25.0)
            for k in range(1, n_chunks + 1):
                sim.integrate(k * (t_end / n_chunks))
                star, aegis = sim.particles[0], sim.particles[1]

                def _lam(p, prim):
                    o = p.orbit(primary=prim)
                    return (o.Omega + o.omega + o.M) % (2 * np.pi)

                phi_series.append(
                    _lam(sim.particles[4], aegis)
                    - 3 * _lam(sim.particles[5], aegis)
                    + 2 * _lam(sim.particles[6], aegis)
                )
                es = []
                rh = float("nan")
                o_a = aegis.orbit(primary=star)
                r_hill = o_a.a * (1 - o_a.e) * (aegis.m / (3.0 * star.m)) ** (1.0 / 3.0)
                for i in (4, 5, 6):
                    o = sim.particles[i].orbit(primary=aegis)
                    es.append(o.e)
                    if i == 6:
                        rh = o.a / r_hill
                e_max_k = max(es)
                max_e = max(max_e, e_max_k)
                if not np.isfinite(e_max_k) or e_max_k > _ANY_E_MAX:
                    death_t = k * (t_end / n_chunks)
                    break
            circ, centre, amp = _libration_stats(np.asarray(phi_series))
            phi_desc = "circulates" if circ else f"librate {centre:.0f}°±{amp:.0f}°"
            outcome = f"DIED @{death_t:.0f}yr" if death_t is not None else "survived"
            print(f"{th1:5.0f} {th2:5.0f}  {outcome:>14}  {max_e:9.3f}  {rh:11.3f}  {phi_desc}")
            results.append((th1, th2, death_t, max_e, rh))

    survivors = [r for r in results if r[2] is None and r[3] < 0.3]
    print(f"\nsurvivors with max e < 0.3: {len(survivors)}/{len(results)}")
    for th1, th2, _d, me, rh in sorted(survivors, key=lambda r: r[3])[:8]:
        marker = "  <-- LANDED" if (th1 == 0.0 and th2 == 180.0) else ""
        print(f"  θ1={th1:5.1f}° θ2={th2:5.1f}°  max_e={me:.3f}  a/r_H={rh:.3f}{marker}")


def build_scan_system(
    sysdata: dict, phi_planets_deg: float, phi_satellites_deg: float
) -> rebound.Simulation:
    """Legacy parametric builder for --scan: each chain's inner body carries the
    phase (M=φ), the rest start at conjunction (M=0), so φ_L = φ at t=0."""
    sim = rebound.Simulation()
    sim.units = ("yr", "AU", "Msun")
    sim.add(m=sysdata["star_m"])

    bodies = sysdata["bodies"]
    for j, bid in enumerate(_CHAIN):
        b = dict(bodies[bid])
        b["M"] = np.radians(phi_planets_deg) if j == 0 else 0.0
        _add_body(sim, b)
    aegis = sim.particles[1]
    for j, bid in enumerate(_SATS):
        b = dict(bodies[bid])
        b["M"] = np.radians(phi_satellites_deg) if j == 0 else 0.0
        _add_body(sim, b, primary=aegis)
    sim.move_to_com()
    return sim


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


def _orb(sim: rebound.Simulation, idx: dict[str, int], bid: str):
    prim = sim.particles[idx["planet_aegis"]] if bid in _SATS else sim.particles[idx[_STAR]]
    return sim.particles[idx[bid]].orbit(primary=prim)


def sample_state(sim: rebound.Simulation, idx: dict[str, int]) -> dict:
    """Osculating state + resonance/geometry diagnostics at the current time."""
    lam: dict[str, float] = {}
    state: dict[str, tuple] = {}
    for bid in idx:
        if bid == _STAR:
            continue
        o = _orb(sim, idx, bid)
        state[bid] = (o.a, o.e, o.inc, o.Omega, o.omega)
        lam[bid] = (o.Omega + o.omega + o.M) % (2 * np.pi)

    phi_p = (lam["planet_aegis"] - 3 * lam["planet_boreal"] + 2 * lam["planet_glacis"]) % (
        2 * np.pi
    )
    phi_s = (
        lam["satellite_nacrea"] - 3 * lam["satellite_cadence"] + 2 * lam["satellite_vigil"]
    ) % (2 * np.pi)

    o_a = _orb(sim, idx, "planet_aegis")
    m_ratio = sim.particles[idx["planet_aegis"]].m / (3.0 * sim.particles[idx[_STAR]].m)
    r_hill = o_a.a * (1.0 - o_a.e) * m_ratio ** (1.0 / 3.0)
    o_v = _orb(sim, idx, "satellite_vigil")

    return {
        "state": state,
        "phi_planets": phi_p,
        "phi_sats": phi_s,
        "vigil_rh_ratio": o_v.a / r_hill,
        "vigil_e": o_v.e,
    }


def _libration_stats(series_rad: np.ndarray) -> tuple[bool, float, float]:
    """Classify a resonance-angle series: (circulates, centre°, half-amplitude°)."""
    unwrapped = np.unwrap(np.asarray(series_rad))
    excursion = float(np.ptp(unwrapped))
    if excursion > np.radians(300.0):
        return True, 0.0, 0.0
    centre = float(np.mean(unwrapped)) % (2 * np.pi)
    return False, float(np.degrees(centre)), float(np.degrees(excursion)) / 2.0


def _periods_yr(sysdata: dict, with_extras: bool) -> list[float]:
    """Keplerian periods (yr) of every integrated body, for the dt choice."""
    bodies = sysdata["bodies"]
    star_m = sysdata["star_m"]
    order = list(_CHAIN) + list(_SATS)
    if with_extras:
        order += list(_EXTRAS)
    out = []
    for bid in order:
        b = bodies[bid]
        m_central = star_m if b["parent"] == "star_ignis" else bodies["planet_aegis"]["m_earth"]
        m_central_msun = m_central if b["parent"] == "star_ignis" else m_central * MEARTH_MSUN
        out.append(float(b["a"] ** 1.5 / np.sqrt(m_central_msun + b["m_earth"] * MEARTH_MSUN)))
    return out


def report(sim: rebound.Simulation, idx: dict[str, int], label: str) -> None:
    print(f"--- {label} ---")
    s = sample_state(sim, idx)
    print(
        f"  φ_L planets = {np.degrees(s['phi_planets']):6.1f}°   "
        f"φ_L satellites = {np.degrees(s['phi_sats']):6.1f}°   "
        f"Vigil a/r_H = {s['vigil_rh_ratio']:.3f}"
    )
    for bid, i in idx.items():
        p = sim.particles[i]
        if bid == _STAR:
            print(f"  {'Ignis':12s} m={p.m:.4f} M☉")
            continue
        a, e, inc, _node, _peri = s["state"][bid]
        print(f"  {bid:18s} a={a:.6f} AU  e={e:.5f}  inc={np.degrees(inc):5.2f}°")


# ---------------------------------------------------------------------------
# Secular operators (J2 apsidal precession + constant-Q tidal e-damping)
# ---------------------------------------------------------------------------
#
# Why operator splitting instead of ``additional_forces``: REBOUND 5.x calls
# the Python force callback ~8.7× per nominal dt under IAS15 and the v += dt·a
# convention mis-applies it (calibrated 2026-09-08: Δvx off by −4.5× with a
# sign flip).  Both effects are *secular* (timescales 74–1879 yr vs orbital
# 3–13 d), so Lie splitting — IAS15 point-mass chunks of ≤1 yr between exact
# analytic kicks — is cleaner AND verifiable against closed-form rates.


def _apply_j2_secular(
    sim: rebound.Simulation,
    idx: dict[str, int],
    j2: float,
    r_prim_au: float,
    dt: float,
    eq_normal: tuple[float, float, float] | None = None,
) -> None:
    """Advance each satellite's argument of periapsis by the secular J2 rate.

    dϖ/dt = (3/4)·J2·(R_p/a)²·n·(4 − 5 sin²i_eq − 2 cos i_eq)·(1−e²)⁻²
    (Vallado, combined dΩ/dt + dω/dt), with i_eq the inclination relative to
    the primary's EQUATOR.  Equatorial prograde (i_eq=0) recovers the classic
    (3/2)J2(R/a)²n; equatorial retrograde (i_eq≈180°) precesses ~3× faster in
    the same inertial sense.  *eq_normal* None ⇒ assume equatorial prograde.
    (a, e, i, M) are preserved; the point-mass orbital energy depends on a
    alone, so dE/E stays a valid integrator-health check (up to the barycentric
    cross-term bookkeeping noted in run_landed).
    """
    aegis = sim.particles[idx["planet_aegis"]]
    for bid in _SATS:
        if bid not in idx:
            continue  # subsystem tests may carry fewer satellites
        i = idx[bid]
        p = sim.particles[i]
        o = p.orbit(primary=aegis)
        if not np.isfinite(o.a) or o.a <= 0.0 or o.e >= 1.0:
            continue
        n = 2.0 * np.pi / o.P
        if eq_normal is None:
            fac = 2.0  # 4 − 5·0 − 2·1 (equatorial prograde)
        else:
            h = np.array(
                [
                    np.sin(o.inc) * np.sin(o.Omega),
                    -np.sin(o.inc) * np.cos(o.Omega),
                    np.cos(o.inc),
                ]
            )
            cos_ieq = float(np.clip(np.dot(h, np.asarray(eq_normal)), -1.0, 1.0))
            fac = 4.0 - 5.0 * (1.0 - cos_ieq**2) - 2.0 * cos_ieq
        dvarpi = 0.75 * j2 * (r_prim_au / o.a) ** 2 * n * dt * fac / (1.0 - o.e**2) ** 2
        sim.particles[i] = rebound.Particle(
            simulation=sim,
            primary=aegis,
            m=p.m,
            a=o.a,
            e=o.e,
            inc=o.inc,
            Omega=o.Omega,
            omega=o.omega + dvarpi,
            M=o.M,
        )


def _apply_tidal_edamp(
    sim: rebound.Simulation,
    idx: dict[str, int],
    dt: float,
    boost: float,
    r_prim_au: float,
    sat_radii_au: dict[str, float],
) -> None:
    """Damp satellite eccentricities by the constant-Q tidal rates over one chunk.

    ė/e = −(21/2)·n·[ (k2p/Qp)·(m_s/M_p)·(R_p/a)⁵ + (k2s/Qs)·(M_p/m_s)·(R_s/a)⁵ ]

    (planet-raised + satellite-raised tides, circular-orbit leading order —
    adequate at e ≲ 0.1; the O(e²) eccentricity functions are omitted, which
    *underestimates* damping at high e, i.e. stays conservative for survival
    verdicts).  Semi-major axes are NOT migrated: ȧ timescales (~Gyr at
    Qp = 1e5) far exceed the experiment horizon; e-damping alone captures the
    pumping-vs-damping balance that sets the forced eccentricity.
    """
    aegis = sim.particles[idx["planet_aegis"]]
    m_a = aegis.m
    for bid in _SATS:
        if bid not in idx or bid not in sat_radii_au:
            continue  # subsystem tests may carry fewer satellites
        i = idx[bid]
        p = sim.particles[i]
        o = p.orbit(primary=aegis)
        if not np.isfinite(o.a) or o.a <= 0.0 or not (0.0 < o.e < 1.0):
            continue
        n = 2.0 * np.pi / o.P
        rate = (
            10.5
            * n
            * (
                _K2Q_AEGIS * (p.m / m_a) * (r_prim_au / o.a) ** 5
                + _SAT_K2Q[bid] * (m_a / p.m) * (sat_radii_au[bid] / o.a) ** 5
            )
        )
        e_new = o.e * float(np.exp(-boost * rate * dt))
        sim.particles[i] = rebound.Particle(
            simulation=sim,
            primary=aegis,
            m=p.m,
            a=o.a,
            e=e_new,
            inc=o.inc,
            Omega=o.Omega,
            omega=o.omega,
            M=o.M,
        )


# ---------------------------------------------------------------------------
# Run modes
# ---------------------------------------------------------------------------


def run_baseline(sysdata: dict, t_end: float = 10.0) -> None:
    """10 yr IAS15 sanity run — compares against the 2026-09-07 skeleton record
    (no ejection, max_e ≈ 0.20, φ_L drift sat ≈ 47° / planets ≈ 94°)."""
    sim, idx = build_landed_system(sysdata)
    sim.integrator = "ias15"
    report(sim, idx, "baseline t=0 (exact yaml configuration)")
    phi_p0, phi_s0 = sample_state(sim, idx)["phi_planets"], sample_state(sim, idx)["phi_sats"]
    max_e = 0.0
    for k in range(1, 101):
        sim.integrate(t_end * k / 100.0)
        s = sample_state(sim, idx)
        max_e = max(max_e, s["vigil_e"], *(st[1] for st in s["state"].values()))
    s = sample_state(sim, idx)
    dp = np.degrees((s["phi_planets"] - phi_p0 + np.pi) % (2 * np.pi) - np.pi)
    ds = np.degrees((s["phi_sats"] - phi_s0 + np.pi) % (2 * np.pi) - np.pi)
    report(sim, idx, f"baseline t={t_end:g} yr (IAS15)")
    print(f"  max e over run = {max_e:.3f}   Δφ_L planets = {dp:+.1f}°   Δφ_L sats = {ds:+.1f}°")


def run_landed(
    sysdata: dict,
    t_end: float,
    with_extras: bool,
    use_megno: bool,
    sample_every: float,
    integrator: str,
    out_npz: Path,
    j2: float = 0.0,
    tides: bool = False,
    tide_boost: float = 1.0,
) -> None:
    sim, idx = build_landed_system(sysdata, with_extras)
    sim.integrator = integrator
    p_min = min(_periods_yr(sysdata, with_extras))
    if integrator == "whfast":
        # WARNING — WHFast is INVALID for this system: its Kepler step assumes
        # every body orbits the central star (Wisdom-Holman Jacobi mapping),
        # but the satellites orbit Aegis.  Verified 2026-09-08: WHFast diverges
        # within ~250 yr (vigil e → 10³) while IAS15 tracks the same state for
        # 10+ yr cleanly.  Kept only for hypothetical pure-planet experiments.
        sim.dt = p_min / 20.0
    if use_megno:
        sim.init_megno()  # REBOUND 5.x API (was add_megno in 3.x/4.x)

    r_prim_au = sysdata["bodies"]["planet_aegis"]["radius_km"] / _AU_KM
    sat_radii_au = {bid: sysdata["bodies"][bid]["radius_km"] / _AU_KM for bid in _SATS}
    # Aegis equator normal in the sim frame: axial tilt from yaml, node at Ω=0
    # (the landed satellites all sit at inc=tilt, Ω=0 — i.e. in the equator).
    _tilt = np.radians(sysdata["bodies"]["planet_aegis"]["axial_tilt_deg"])
    eq_normal = (0.0, -float(np.sin(_tilt)), float(np.cos(_tilt)))

    print(
        f"Landed configuration: {len(idx) - 1} bodies"
        f"{' (+Ember/Crucible/Sentinel)' if with_extras else ''}, "
        f"integrator={integrator} (P_min={p_min * 365.25:.2f} d), "
        f"t_end={t_end:g} yr, MEGNO={'on' if use_megno else 'off'}"
    )
    if j2 > 0.0:
        print(f"  J2 secular splitting: J2={j2:g} (R_A={r_prim_au * _AU_KM:.0f} km)")
    if tides:
        print(f"  tidal e-damping: constant-Q, boost={tide_boost:g}")

    e0 = sim.energy()
    t_wall0 = time.time()
    n_samples = int(t_end / sample_every)

    t_s: list[float] = []
    series: dict[str, dict[str, list[float]]] = {
        bid: {"a": [], "e": [], "inc": []} for bid in idx if bid != _STAR
    }
    phi_p_s: list[float] = []
    phi_s_s: list[float] = []
    rh_s: list[float] = []
    varpi_aegis_s: list[float] = []
    omega_node_nacrea_s: list[float] = []
    megno_s: list[float] = []
    de_s: list[float] = []

    verdict = "STABLE"
    use_ops = j2 > 0.0 or tides
    dt_op = min(sample_every, 1.0) if use_ops else sample_every
    n_ops = max(1, int(round(sample_every / dt_op)))
    t_cur = 0.0
    for k in range(1, n_samples + 1):
        for _j in range(n_ops):
            sim.integrate(t_cur + dt_op)
            t_cur += dt_op
            if j2 > 0.0:
                _apply_j2_secular(sim, idx, j2, r_prim_au, dt_op, eq_normal)
            if tides:
                _apply_tidal_edamp(sim, idx, dt_op, tide_boost, r_prim_au, sat_radii_au)
        s = sample_state(sim, idx)
        v_e, v_rh = s["vigil_e"], s["vigil_rh_ratio"]
        any_e_max = max(st[1] for st in s["state"].values())

        # Record first, then guard — a breaking sample still lands in the series
        # so the post-mortem table/npz shows the runaway itself.
        t_s.append(t_cur)
        for bid, st in s["state"].items():
            series[bid]["a"].append(st[0])
            series[bid]["e"].append(st[1])
            series[bid]["inc"].append(st[2])
        phi_p_s.append(s["phi_planets"])
        phi_s_s.append(s["phi_sats"])
        rh_s.append(v_rh)
        _om_aeg = s["state"]["planet_aegis"]
        varpi_aegis_s.append((_om_aeg[3] + _om_aeg[4]) % (2 * np.pi))
        omega_node_nacrea_s.append(s["state"]["satellite_nacrea"][3])
        if use_megno:
            megno_s.append(sim.megno())
        de_s.append((sim.energy() - e0) / abs(e0))

        broken = (
            not np.isfinite(v_e)
            or not np.isfinite(any_e_max)
            or v_e > _VIGIL_E_MAX
            or v_rh > _VIGIL_RH_MAX
            or any_e_max > _ANY_E_MAX
        )
        if broken:
            verdict = (
                f"UNSTABLE at t={t_cur:g} yr "
                f"(vigil e={v_e:.3f}, a/r_H={v_rh:.3f}, max e={any_e_max:.3f})"
            )
            print(f"\n  !! {verdict}")
            break

        if k % max(1, n_samples // 10) == 0:
            wall = time.time() - t_wall0
            speed = t_cur / wall if wall > 0 else float("nan")
            eta_min = (t_end - t_cur) / speed / 60.0 if speed > 0 else float("nan")
            meg = megno_s[-1] if use_megno else float("nan")
            print(
                f"  t={k * sample_every:>10.0f} yr  wall={wall:6.0f}s  dE/E={de_s[-1]:+.2e}  "
                f"vigil e={v_e:.4f} a/r_H={v_rh:.3f}  megno={meg:.3f}  "
                f"({speed:.1f} yr/s, ETA {eta_min:.0f} min)"
            )

    wall = time.time() - t_wall0
    print()
    print(f"=== VERDICT: {verdict} ({wall:.0f}s wall, t_end={t_end:g} yr, {integrator}) ===")

    print(f"\n{'body':18s} {'e init':>8} {'e min':>8} {'e max':>8} {'a drift %':>10}")
    for bid in series:
        e_arr = np.asarray(series[bid]["e"])
        a_arr = np.asarray(series[bid]["a"])
        e_init = sysdata["bodies"].get(bid, {}).get("e", float("nan"))
        print(
            f"{bid:18s} {e_init:8.4f} {e_arr.min():8.4f} {e_arr.max():8.4f} "
            f"{100.0 * (a_arr[-1] / a_arr[0] - 1.0):+10.4f}"
        )

    for label, arr in (("planets", phi_p_s), ("satellites", phi_s_s)):
        circ, centre, amp = _libration_stats(np.asarray(arr))
        desc = "CIRCULATES" if circ else f"librates @ {centre:.0f}° ± {amp:.0f}°"
        print(f"φ_L {label:11s}: {desc}")

    rh_arr = np.asarray(rh_s)
    print(f"Vigil a/r_H: init {rh_arr[0]:.3f}  max {rh_arr.max():.3f}  (limit ~0.49 prograde)")
    if use_megno and megno_s:
        print(f"MEGNO ⟨Y⟩ final = {megno_s[-1]:.3f}  (≈2 regular, ≳4 chaotic)")
    print(f"energy drift |dE/E| max = {max(abs(d) for d in de_s):.2e}")

    out_npz.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        out_npz,
        t=np.asarray(t_s),
        phi_planets=np.asarray(phi_p_s),
        phi_sats=np.asarray(phi_s_s),
        vigil_rh=rh_arr,
        varpi_aegis=np.asarray(varpi_aegis_s),
        omega_node_nacrea=np.asarray(omega_node_nacrea_s),
        megno=np.asarray(megno_s),
        dE=np.asarray(de_s),
        **{f"{kind}_{bid}": np.asarray(v[kind]) for bid, v in series.items() for kind in v},
    )
    print(f"time series saved: {out_npz}")


def scan_laplace(sysdata: dict, total_years: float = 100.0, step_deg: float = 30.0) -> None:
    """Legacy exploration: sweep the parametric φ_L of both chains (100 yr each)."""
    print(f"\n=== Laplace resonance scan (T={total_years} yr, φ₀ step {step_deg:.0f}°) ===\n")
    print(f"{'φ₀':>6}  {'planet chain φ_L':>24}  {'satellite chain φ_L':>27}  {'max e':>7}")
    print("-" * 74)
    n_out = 200
    dt = total_years / n_out
    for phi0 in range(0, 360, int(step_deg)):
        sim = build_scan_system(sysdata, phi0, phi0)
        sim.integrator = "ias15"
        phi_p: list[float] = []
        phi_s: list[float] = []
        max_e = 0.0
        for k in range(1, n_out + 1):
            sim.integrate(k * dt)
            # legacy scan: recompute φ_L from the parametric particle order
            star, aegis = sim.particles[0], sim.particles[1]

            def _lam(p, prim):
                o = p.orbit(primary=prim)
                return (o.Omega + o.omega + o.M) % (2 * np.pi)

            phi_p.append(
                _lam(sim.particles[1], star)
                - 3 * _lam(sim.particles[2], star)
                + 2 * _lam(sim.particles[3], star)
            )
            phi_s.append(
                _lam(sim.particles[4], aegis)
                - 3 * _lam(sim.particles[5], aegis)
                + 2 * _lam(sim.particles[6], aegis)
            )
            for i in range(1, 7):
                o = sim.particles[i].orbit(primary=aegis if i >= 4 else star)
                max_e = max(max_e, o.e)
        p_circ, p_c, p_a = _libration_stats(np.asarray(phi_p))
        s_circ, s_c, s_a = _libration_stats(np.asarray(phi_s))
        p_lab = "circulates" if p_circ else f"librate @ {p_c:5.0f}° ± {p_a:4.0f}°"
        s_lab = "circulates" if s_circ else f"librate @ {s_c:5.0f}° ± {s_a:4.0f}°"
        print(f"{phi0:5d}°  {p_lab:>24}  {s_lab:>27}  {max_e:7.3f}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--t-end", type=float, default=2e4, help="integration horizon (yr)")
    parser.add_argument("--sample-every", type=float, default=10.0, help="sampling interval (yr)")
    parser.add_argument("--with-extras", action="store_true", help="add Ember/Crucible/Sentinel")
    parser.add_argument("--no-megno", action="store_true", help="disable the MEGNO chaos indicator")
    parser.add_argument(
        "--integrator",
        default="ias15",
        choices=("ias15", "whfast", "mercurius"),
        help="ias15 is the only valid choice while satellites are included "
        "(whfast/mercurius assume star-centred Kepler steps)",
    )
    parser.add_argument(
        "--j2",
        type=float,
        default=0.0,
        help="Aegis J2 for secular apsidal splitting (0=off; Darwin-Radau est. 0.006-0.010)",
    )
    parser.add_argument(
        "--tides", action="store_true", help="constant-Q tidal e-damping operator (see _K2Q_*)"
    )
    parser.add_argument(
        "--tide-boost",
        type=float,
        default=1.0,
        help="nonphysical tidal-strength multiplier (equilibrium-capture probe)",
    )
    parser.add_argument("--baseline", action="store_true", help="10 yr IAS15 sanity run only")
    parser.add_argument("--scan", action="store_true", help="legacy Laplace-phase scan only")
    parser.add_argument(
        "--sat-scan", action="store_true", help="θ1×θ2 satellite-chain phase sweep (planets landed)"
    )
    parser.add_argument("--scan-t-end", type=float, default=300.0, help="--sat-scan horizon (yr)")
    parser.add_argument("--scan-grid", type=int, default=6, help="--sat-scan grid per angle")
    parser.add_argument(
        "--out", default="private/tmp/rebound_landed.npz", help="npz output for the landed run"
    )
    args = parser.parse_args()

    sysdata = load_system()
    if args.baseline:
        run_baseline(sysdata)
        return
    if args.scan:
        scan_laplace(sysdata)
        return
    if args.sat_scan:
        sat_phase_scan(sysdata, t_end=args.scan_t_end, grid=args.scan_grid)
        return
    run_landed(
        sysdata,
        t_end=args.t_end,
        with_extras=args.with_extras,
        use_megno=not args.no_megno,
        sample_every=args.sample_every,
        integrator=args.integrator,
        out_npz=_find_project_root() / args.out,
        j2=args.j2,
        tides=args.tides,
        tide_boost=args.tide_boost,
    )


if __name__ == "__main__":
    main()
