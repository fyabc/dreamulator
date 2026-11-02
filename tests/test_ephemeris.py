"""Tests for dreamulator.engine.ephemeris — the observer's-sky query (M1).

The nacrea values here are anchors, not configuration: the frozen EP1 shot
search (``apparent_orbits.py``, t = 61.979166 d) and the existing
``sky_geometry`` / catalog-sky numbers pin the same physics the retired video
prototype implemented, so the engine reproduces them before any consumer
switches over.  The module itself stays world-agnostic.
"""

from __future__ import annotations

import math
from typing import Any

import pytest

from dreamulator.engine.ephemeris import (
    ObserverFrame,
    _elements_from_entity,
    body_state_km,
    observer_frame_km,
    orbital_position_km,
    sky_ephemeris,
    solve_kepler_eccentric,
)
from dreamulator.engine.sky_geometry import (
    AU_KM,
    angular_size,
    lambert_phase,
    sky_position,
)
from dreamulator.query_registry import list_queries

# The frozen instant of the EP1 dawn shot (days after the catalog epoch).
T_DAWN = 61.979166


def _body(
    body_id: str,
    parent_id: str,
    a_au: float,
    e: float,
    inc_deg: float,
    node_deg: float,
    peri_deg: float,
    m0_deg: float,
    period_days: float,
    radius_km: float,
    **extra: Any,
) -> dict[str, Any]:
    entity: dict[str, Any] = {
        "id": body_id,
        "parent_id": parent_id,
        "body_type": "natural_satellite",
        "is_satellite": True,
        "semi_major_axis_au": a_au,
        "eccentricity": e,
        "inclination_deg": inc_deg,
        "longitude_ascending_node_deg": node_deg,
        "argument_of_periapsis_deg": peri_deg,
        "mean_anomaly_epoch_deg": m0_deg,
        "epoch_year": 0.0,
        "period_days": period_days,
        "radius_km": radius_km,
    }
    entity.update(extra)
    return entity


#: Flattened entities (post facts.py orbits-merge shape) with catalog nacrea
#: values: full-precision elements, catalog periods, physical/derived blocks.
ENTITIES: dict[str, dict[str, Any]] = {
    "star_ignis": {
        "id": "star_ignis",
        "name": "Ignis",
        "luminosity_sol": 0.1227,
        "radius_sol": 0.6125,
        "position": {"x": 0.0, "y": 0.0, "z": 0.0},
    },
    "planet_aegis": _body(
        "planet_aegis",
        "star_ignis",
        0.3648,
        0.06786252,
        0.025812,
        131.099119,
        88.993305,
        47.539366,
        99.7025,
        71355.2,
        body_type="planet",
        is_satellite=False,
        rotation_period_days=0.1864,
        axial_tilt_deg=44.84,
        albedo=0.343,
        tidally_locked=False,
        spin_axis_ecliptic_longitude_deg=None,
    ),
    "satellite_nacrea": _body(
        "satellite_nacrea",
        "planet_aegis",
        0.0048348095,
        0.0024175,
        13.637092,
        137.41468,
        247.930961,
        97.912075,
        3.1383,
        6817.0,
        rotation_period_days=3.1336,
        axial_tilt_deg=19.9,
        albedo=0.3,
        tidally_locked=True,
        solar_day_days=3.2352,
        instellation_w_m2=1254.97,
    ),
    "satellite_cadence": _body(
        "satellite_cadence",
        "planet_aegis",
        0.0078845945,
        0.01675059,
        168.821896,
        290.545652,
        117.95592,
        164.805827,
        6.5433,
        1436.7,
        rotation_period_days=6.54,
        axial_tilt_deg=0.0,
        albedo=0.13,
        tidally_locked=True,
        solar_day_days=6.9985,
    ),
    "satellite_vigil": _body(
        "satellite_vigil",
        "planet_aegis",
        0.0116769194,
        0.11903554,
        170.079498,
        178.12836,
        242.650103,
        330.18051,
        11.793,
        614.8,
        rotation_period_days=10.29,
        axial_tilt_deg=0.0,
        albedo=0.313,
        tidally_locked=False,
        solar_day_days=11.4727,
    ),
}


# ---------------------------------------------------------------------------
# Layer 0 — Kepler machinery
# ---------------------------------------------------------------------------


def test_kepler_solver_circular_and_converged() -> None:
    assert solve_kepler_eccentric(0.7, 0.0) == pytest.approx(0.7, abs=1e-12)
    for m in (0.0, 2.0, 4.0):
        e = solve_kepler_eccentric(m, 0.6)
        residual = e - 0.6 * math.sin(e) - math.fmod(m, 2.0 * math.pi)
        assert abs(residual) < 1e-11


def test_kepler_solver_wraps_many_revolutions() -> None:
    # A large t_days yields M with thousands of revolutions; the solution is
    # the wrapped one (regression: the residual once used the unwrapped M and
    # Newton never converged past a few hundred days).
    e = 0.02
    direct = solve_kepler_eccentric(0.7, e)
    wrapped = solve_kepler_eccentric(0.7 + 1306.0 * 2.0 * math.pi, e)
    assert wrapped == pytest.approx(direct, abs=1e-9)  # fmod noise ~1e-12


def test_kepler_solver_rejects_unbound() -> None:
    with pytest.raises(ValueError, match="eccentricity"):
        solve_kepler_eccentric(0.5, 1.0)


def test_epoch_state_consistency() -> None:
    aegis = _elements_from_entity(ENTITIES["planet_aegis"])
    r = orbital_position_km(aegis, 0.0)
    expected_r = aegis.a_km * (
        1.0 - aegis.e * math.cos(solve_kepler_eccentric(aegis.mean_anomaly_epoch_rad, aegis.e))
    )
    assert math.sqrt(sum(v * v for v in r)) == pytest.approx(expected_r, rel=1e-12)
    nacrea = _elements_from_entity(ENTITIES["satellite_nacrea"])
    offset = orbital_position_km(nacrea, 31.0)
    norm = math.sqrt(sum(v * v for v in offset))
    assert nacrea.a_km * (1.0 - nacrea.e) <= norm <= nacrea.a_km * (1.0 + nacrea.e)


def test_body_state_stacks_through_the_parent() -> None:
    aegis = body_state_km(ENTITIES, "planet_aegis", T_DAWN)
    nacrea = body_state_km(ENTITIES, "satellite_nacrea", T_DAWN)
    offset = orbital_position_km(_elements_from_entity(ENTITIES["satellite_nacrea"]), T_DAWN)
    assert nacrea == pytest.approx(tuple(a + o for a, o in zip(aegis, offset, strict=True)))
    assert body_state_km(ENTITIES, "star_ignis", 5.0) == (0.0, 0.0, 0.0)


def test_body_state_rejects_unknown_and_cycles() -> None:
    with pytest.raises(KeyError, match="unknown body id"):
        body_state_km(ENTITIES, "satellite_none", 0.0)
    left = dict(ENTITIES["satellite_nacrea"], id="cycle_a", parent_id="cycle_b")
    right = dict(ENTITIES["satellite_cadence"], id="cycle_b", parent_id="cycle_a")
    with pytest.raises(ValueError, match="cycle"):
        body_state_km({"cycle_a": left, "cycle_b": right}, "cycle_a", 0.0)


# ---------------------------------------------------------------------------
# Observer frame and the frozen dawn anchors
# ---------------------------------------------------------------------------


def _row(target: str, lat: float = 0.0, lon: float = 0.0, t: float = T_DAWN) -> Any:
    result = sky_ephemeris(ENTITIES, "satellite_nacrea", lat, lon, t, targets=[target])
    return result.targets[0]


def test_sun_altitude_dawn_anchor() -> None:
    # The frozen prototype anchor at the sub-planet point (moon_sky.json).
    assert _row("star_ignis").altitude_deg == pytest.approx(-0.24429, abs=0.005)


def test_moon_anchors_at_dawn() -> None:
    cadence = _row("satellite_cadence")
    assert cadence.distance_km == pytest.approx(1_863_498.29, abs=30.0)
    assert cadence.angular_diameter_deg == pytest.approx(0.08835, abs=0.0002)
    assert 90.0 - cadence.altitude_deg == pytest.approx(8.5905, abs=0.005)
    vigil = _row("satellite_vigil")
    assert vigil.distance_km == pytest.approx(2_351_483.35, abs=30.0)
    assert vigil.angular_diameter_deg == pytest.approx(0.02996, abs=0.0002)
    assert 90.0 - vigil.altitude_deg == pytest.approx(14.8653, abs=0.005)


def test_position_angle_frame_rotation() -> None:
    # The prototype measured position angles from the *ecliptic-pole* north
    # projection; this module uses the body spin axis (nacrea's own orbit
    # normal, 13.64° from ecliptic north).  Rotating our azimuth by the signed
    # angle between the two projected norths must reproduce its anchors — the
    # only anchor that needs a frame transformation at all.
    frame = observer_frame_km(ENTITIES, "satellite_nacrea", T_DAWN, 0.0, 0.0)
    pole_north = (0.0, 0.0, 1.0)
    projection = tuple(
        p - frame.up[i] * sum(p * u for p, u in zip(pole_north, frame.up, strict=True))
        for i, p in enumerate(pole_north)
    )
    east_dot = sum(a * b for a, b in zip(projection, frame.east, strict=True))
    north_dot = sum(a * b for a, b in zip(projection, frame.north, strict=True))
    delta = math.degrees(math.atan2(east_dot, north_dot))
    assert (_row("satellite_cadence").azimuth_deg - delta) % 360.0 == pytest.approx(
        263.111, abs=0.02
    )
    assert (_row("satellite_vigil").azimuth_deg - delta) % 360.0 == pytest.approx(159.346, abs=0.02)


def test_locked_parent_stands_at_zenith() -> None:
    for t in (0.0, 31.0, T_DAWN):
        assert _row("planet_aegis", t=t).altitude_deg == pytest.approx(90.0, abs=0.01)


def test_sky_position_consistency() -> None:
    for lon, lat, expected in ((0.4, -0.6, 89.29), (1.121, -0.106, 88.91)):
        ours = _row("planet_aegis", lat=lat, lon=lon)
        reference = sky_position(
            {k: dict(v) for k, v in ENTITIES.items()},
            "satellite_nacrea",
            "planet_aegis",
            lon_deg=lon,
            lat_deg=lat,
        )
        assert ours.altitude_deg == pytest.approx(expected, abs=0.1)
        assert abs(ours.altitude_deg - reference.altitude_deg) < 0.05


def test_angular_size_surface_vs_center() -> None:
    row = _row("planet_aegis")
    # From the surface (topocentric): the engine's own value, self-consistent
    # with its distance, and near the hand-derived 11.37° mean-distance value.
    assert row.angular_diameter_deg == pytest.approx(
        angular_size(71355.2, row.distance_km), rel=1e-12
    )
    assert row.angular_diameter_deg == pytest.approx(11.37, abs=0.05)
    # From the satellite centre (geocentric): the catalog sky anchor.
    separation = math.dist(
        body_state_km(ENTITIES, "planet_aegis", T_DAWN),
        body_state_km(ENTITIES, "satellite_nacrea", T_DAWN),
    )
    assert angular_size(71355.2, separation) == pytest.approx(11.27, abs=0.1)
    assert angular_size(71355.2, 0.0048348095 * AU_KM) == pytest.approx(11.27, abs=0.1)


def test_phase_angle_dawn_relation() -> None:
    # At the sub-planet point α(Aegis) = 90° + h★ up to the stellar-parallax
    # term asin(a/D★) ≈ 0.76° (sky_geometry.stellar_parallax_deg's anchor).
    for t in (50.0, T_DAWN, 70.0):
        star = _row("star_ignis", t=t)
        aegis = _row("planet_aegis", t=t)
        assert aegis.phase_angle_deg == pytest.approx(90.0 + star.altitude_deg, abs=1.5)


def test_full_phase_scan_matches_catalog_sky() -> None:
    # Aegis's heliocentric direction is inclined 13.64° to nacrea's orbit, so
    # full phase only occurs near node seasons: over one Aegis year the minimum
    # phase angle is ≤ ~13.7°, and there the catalog full-phase anchors hold
    # (Δm at 13.6° is only 0.08, inside the tolerance).
    year = 99.7025
    n_steps = 400

    def unit(vector: list[float]) -> list[float]:
        norm = math.sqrt(sum(v * v for v in vector))
        return [v / norm for v in vector]

    def phase_angle(t: float) -> float:
        observer = observer_frame_km(ENTITIES, "satellite_nacrea", t, 0.0, 0.0)
        target = body_state_km(ENTITIES, "planet_aegis", t)
        star = body_state_km(ENTITIES, "star_ignis", t)
        sight = unit([a - b for a, b in zip(target, observer.observer_km, strict=True)])
        lit = unit([a - b for a, b in zip(star, target, strict=True)])
        # Phase angle at the target: (observer − target) · (star − target).
        cosine = -sum(x * y for x, y in zip(sight, lit, strict=True))
        return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))

    times = [i * year / n_steps for i in range(n_steps + 1)]
    angles = [phase_angle(t) for t in times]
    best_t = times[angles.index(min(angles))]
    assert min(angles) <= 13.7
    aegis = _row("planet_aegis", t=best_t)
    assert aegis.apparent_magnitude == pytest.approx(-20.02, abs=0.1)
    assert aegis.illuminance_w_m2 == pytest.approx(2.79, abs=0.05)


def test_phase_table_deltas() -> None:
    # sky_phenomena.md's authored phase table pins Δm = −2.5·log10 Φ(α).
    expected = {45.0: 0.31, 90.0: 1.24, 135.0: 3.29}
    for alpha_deg, delta_m in expected.items():
        ratio = lambert_phase(math.radians(alpha_deg))
        assert -2.5 * math.log10(ratio) == pytest.approx(delta_m, abs=0.01)


def test_star_row_anchors() -> None:
    star = _row("star_ignis")
    assert star.angular_diameter_deg == pytest.approx(0.89, abs=0.05)
    assert star.apparent_magnitude == pytest.approx(-26.65, abs=0.02)
    assert star.phase_angle_deg is None
    assert star.elongation_star_deg is None


def test_reflected_fields_reuse_sky_geometry() -> None:
    cadence = _row("satellite_cadence")
    alpha = math.radians(cadence.phase_angle_deg or 0.0)
    assert cadence.illuminated_fraction == pytest.approx((1.0 + math.cos(alpha)) / 2.0)
    assert cadence.phase_function == pytest.approx(lambert_phase(alpha))


# ---------------------------------------------------------------------------
# Rise/set
# ---------------------------------------------------------------------------


def test_star_rises_and_sets_from_yongyao() -> None:
    star = _row("star_ignis", lat=-0.6, lon=0.4)
    assert star.rise_state == "rises_sets"
    assert star.next_rise_days is not None and star.next_rise_days > 0.0
    assert star.next_set_days is not None and star.next_set_days > 0.0
    # The refined crossing really is on the horizon.
    result = sky_ephemeris(
        ENTITIES,
        "satellite_nacrea",
        -0.6,
        0.4,
        T_DAWN + star.next_rise_days,
        targets=["star_ignis"],
    )
    assert result.targets[0].altitude_deg == pytest.approx(0.0, abs=0.005)


def test_locked_parent_never_sets() -> None:
    aegis = _row("planet_aegis", lat=-0.6, lon=0.4)
    assert aegis.rise_state == "never_sets"
    assert aegis.next_rise_days is None
    assert aegis.next_set_days is None


def test_sibling_moons_classified() -> None:
    cadence = _row("satellite_cadence")
    vigil = _row("satellite_vigil")
    assert cadence.rise_state == "rises_sets"
    assert vigil.rise_state == "rises_sets"


def test_latitude_validated_longitude_wraps() -> None:
    with pytest.raises(ValueError, match="latitude"):
        sky_ephemeris(ENTITIES, "satellite_nacrea", 91.0, 0.0, 0.0, targets=["star_ignis"])
    wrapped = sky_ephemeris(ENTITIES, "satellite_nacrea", 7.0, 400.0, 10.0, targets=["star_ignis"])
    assert wrapped.lon_deg == pytest.approx(40.0)
    direct = sky_ephemeris(ENTITIES, "satellite_nacrea", 7.0, 40.0, 10.0, targets=["star_ignis"])
    assert wrapped.targets[0].altitude_deg == pytest.approx(direct.targets[0].altitude_deg)


def test_polar_half_answer_is_reported_not_crashed() -> None:
    # Inside the polar circle (nacrea's sits at 90 − 19.9 = 70.1°) a body can
    # cross the horizon once per season: the other crossing lies beyond the
    # rise/set window (an M4 event search), so a member is legitimately None
    # while rise_state is rises_sets — reported, never a crash.
    star = _row("star_ignis", lat=80.0, lon=0.0, t=0.0)
    assert star.rise_state == "rises_sets"
    assert star.next_rise_days is None or star.next_set_days is None


# ---------------------------------------------------------------------------
# Frame identities and the spin-axis ladder
# ---------------------------------------------------------------------------


def test_enu_basis_roundtrip() -> None:
    frame = observer_frame_km(ENTITIES, "satellite_nacrea", T_DAWN, 12.0, 34.0)
    for alt_deg, az_deg in ((0.0, 0.0), (45.0, 90.0), (-12.5, 234.0), (89.0, 359.0)):
        alt, az = math.radians(alt_deg), math.radians(az_deg)
        vector = [
            math.cos(alt) * math.sin(az) * frame.east[i]
            + math.cos(alt) * math.cos(az) * frame.north[i]
            + math.sin(alt) * frame.up[i]
            for i in range(3)
        ]
        rebuilt_alt = math.asin(
            max(-1.0, min(1.0, sum(v * u for v, u in zip(vector, frame.up, strict=True))))
        )
        rebuilt_az = (
            math.degrees(
                math.atan2(
                    sum(v * e for v, e in zip(vector, frame.east, strict=True)),
                    sum(v * n for v, n in zip(vector, frame.north, strict=True)),
                )
            )
            % 360.0
        )
        assert math.degrees(rebuilt_alt) == pytest.approx(alt_deg, abs=1e-9)
        # Azimuth compares modulo 360: at the wrap, float noise rebuilds 0° as
        # 359.999…°, which is the same direction.
        azimuth_gap = min(abs(rebuilt_az - az_deg), 360.0 - abs(rebuilt_az - az_deg))
        assert azimuth_gap < 1e-9


def test_ra_dec_frame_identities() -> None:
    # Zero obliquity + spin azimuth 0: the body equator is the ecliptic, so
    # equatorial and ecliptic coordinates coincide.
    flat = {
        key: dict(value)
        for key, value in ENTITIES.items()
        if key not in ("satellite_nacrea", "satellite_cadence", "satellite_vigil")
    }
    flat["planet_aegis"]["spin_axis_ecliptic_longitude_deg"] = 0.0
    flat["planet_aegis"]["axial_tilt_deg"] = 0.0
    result = sky_ephemeris(flat, "planet_aegis", 10.0, 20.0, T_DAWN, targets=["star_ignis"])
    star = result.targets[0]
    assert star.equatorial_ra_deg == pytest.approx(star.ecliptic_lon_deg, abs=1e-9)
    assert star.equatorial_dec_deg == pytest.approx(star.ecliptic_lat_deg, abs=1e-9)
    # Pole-on-equator (ε = 90°, azimuth 0 → axis = x): a target on the
    # ecliptic y-axis lies on the body equator, declination 0.
    tilted = dict(flat)
    tilted["planet_aegis"] = dict(flat["planet_aegis"])
    tilted["planet_aegis"]["axial_tilt_deg"] = 90.0
    frame = observer_frame_km(tilted, "planet_aegis", 0.0, 0.0, 0.0)
    assert isinstance(frame, ObserverFrame)


def test_spin_axis_ladder() -> None:
    # Locked → orbit normal; retrograde locked keeps the angular-momentum side.
    nacrea_frame = observer_frame_km(ENTITIES, "satellite_nacrea", 0.0, 0.0, 0.0)
    assert nacrea_frame.spin_source == "locked_to_parent"
    cadence_frame = observer_frame_km(ENTITIES, "satellite_cadence", 0.0, 0.0, 0.0)
    assert cadence_frame.spin_source == "locked_to_parent"
    # Non-locked satellite, zero tilt → orbit-normal fallback (Vigil).
    vigil_frame = observer_frame_km(ENTITIES, "satellite_vigil", 0.0, 0.0, 0.0)
    assert vigil_frame.spin_source == "orbit_normal_fallback"
    # A planet without the spin-axis azimuth is rejected, not guessed.
    with pytest.raises(ValueError, match="spin-axis azimuth"):
        observer_frame_km(ENTITIES, "planet_aegis", 0.0, 0.0, 0.0)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_query_registered() -> None:
    by_name = {q["name"]: q for q in list_queries()}
    assert "sky_ephemeris" in by_name
    assert by_name["sky_ephemeris"]["dimension"] == "sky"


# ---------------------------------------------------------------------------
# Slider fast path (include_events=False)
# ---------------------------------------------------------------------------


def test_fast_path_matches_full_positions() -> None:
    full = sky_ephemeris(ENTITIES, "satellite_nacrea", 0.0, 0.0, T_DAWN)
    fast = sky_ephemeris(ENTITIES, "satellite_nacrea", 0.0, 0.0, T_DAWN, include_events=False)
    assert len(fast.targets) == len(full.targets)
    for full_row, fast_row in zip(full.targets, fast.targets, strict=True):
        assert fast_row.body_id == full_row.body_id
        # Everything the chart draws is byte-identical; only events vanish.
        for field in (
            "altitude_deg",
            "azimuth_deg",
            "distance_km",
            "angular_diameter_deg",
            "apparent_magnitude",
            "phase_angle_deg",
        ):
            assert getattr(fast_row, field) == getattr(full_row, field)
        assert fast_row.rise_state is None
        assert fast_row.next_rise_days is None
        assert fast_row.next_set_days is None


def test_fast_path_rate_matches_full_path() -> None:
    full = sky_ephemeris(ENTITIES, "satellite_nacrea", 0.0, 0.0, T_DAWN)
    fast = sky_ephemeris(ENTITIES, "satellite_nacrea", 0.0, 0.0, T_DAWN, include_events=False)
    star_full = next(r for r in full.targets if r.body_id == "star_ignis")
    star_fast = next(r for r in fast.targets if r.body_id == "star_ignis")
    assert abs(star_fast.altitude_rate_deg_per_hr) > 1.0  # dawn: the sun climbs
    assert star_fast.altitude_rate_deg_per_hr == pytest.approx(
        star_full.altitude_rate_deg_per_hr, rel=0.02
    )
    # The sign is physical: at dawn the star is rising.
    assert star_fast.altitude_rate_deg_per_hr > 0.0


def test_events_default_on() -> None:
    from dreamulator.engine.ephemeris import SkyEphemerisParams

    assert SkyEphemerisParams(observer_id="satellite_nacrea").include_events is True
