"""ephemeris — the observer's sky as an engine query (sky-ephemeris M1).

Everything the sky above one point of one body shows at one moment: for every
target body — the star(s), planets and sibling satellites — its altitude and
azimuth in the local horizon frame, ecliptic and equatorial coordinates, angular
diameter, phase and illumination, apparent magnitude, elongations, rise/set
state and instantaneous altitude rate.  Consumers (video shot planning, FUI
data cards, the frontend sky view, calendars) read this one result instead of
each carrying its own orbital propagation.

Frames and conventions (this module is the single authority for them):

* **Ecliptic frame** — the catalog's reference plane (``stellar.yaml``),
  right-handed, +z toward ecliptic north, the star at its catalog ``position``.
  All internal vectors are kilometres; the API surface reports degrees.
* **Lat/lon** — latitude in [−90, 90] north-positive from the body equator
  (outside is rejected), longitude east-positive from the prime meridian,
  wrapped into [−180, 180).  Azimuth is 0 at local true north, increasing
  clockwise toward east.
* **Spin axis** (resolved in this order):

  1. ``tidally_locked`` → the body's own orbit normal (the angular-momentum
     side is north, also for retrograde orbits), and the prime meridian points
     at the parent *instantaneously* (Cassini state 1 — same physics as
     ``physical_inputs._synchronous_satellite_pole`` and the same sub-planet
     convention as ``sky_geometry.sky_position``).  ``rotation_period_days`` is
     deliberately ignored for locked bodies: the catalog's rotation value can
     drift from the orbital period (nacrea: 3.1336 vs 3.1383 d) and the lock,
     not the tabulated spin, fixes the frame.  The parent then stands exactly
     at the zenith of (0, 0) at every instant — a declared convention matching
     the "eternal shine" canon, not an approximation claim.  A real damped
     lock spins uniformly, so the parent's disk would rock by the equation of
     centre (optical longitude libration, ±2e ≈ ±0.28° for nacrea) while the
     stars turned uniformly; this frame instead pins the parent and lets that
     ±2e oscillation appear in the other bodies' apparent motion.  The two
     views differ by a ±2e rotation of the whole sky about the spin axis —
     below every consumer's resolution to date (the uniform-spin convention is
     an M4 refinement; physical libration itself needs (B−A)/C, which the
     catalog does not carry, and stays at arcsecond level).
  2. ``spin_axis_ecliptic_longitude_deg`` present → axis tilted by
     ``axial_tilt_deg`` from +z toward that ecliptic longitude.  Rotation phase
     ``θ = 2π·t / rotation_period_days`` with the zero-parameter epoch
     convention: **at t = 0 the prime meridian points at the ascending node of
     the body equator on the ecliptic** (the body's own equinox direction).
     The catalog epoch carries no spin-phase information, so this is a declared
     convention, not a derivation.
  3. Otherwise: a non-locked *satellite* with ``axial_tilt_deg`` 0 or absent
     falls back to its orbit normal, rotating about it with the same
     node-anchored phase convention (the orbit's own ascending node as t = 0
     meridian).  Any other body without the spin-axis azimuth raises
     ``ValueError`` — the catalog itself flags these as "not derivable", and an
     error beats an invented azimuth (Aegis-surface observation is rejected
     rather than silently wrong).
* **Equatorial coordinates** — the observer body's true equator: z is the spin
  axis, x is the ascending node of that equator on the ecliptic (the
  terrestrial vernal-equinox convention generalised — RA 0 is the observer
  body's own equinox direction), y = z × x.  With zero obliquity the node is
  degenerate and the ecliptic x-axis is used (declination stays exact).
* **ENU** — up is the spherical radial at (lat, lon) (catalog bodies are
  spheres), north is the spin-axis projection on the tangent plane, east =
  north × up.  Near the zenith the azimuth is intrinsically unstable; consumers
  that need a position angle on the parent's disk use ``observer_frame_km``.

Photometry reuses :mod:`dreamulator.engine.sky_geometry` verbatim (Lambert
phase, reflected magnitude/illuminance, stellar magnitude) and
:func:`stellar_physics.instellation`.  One recorded deviation from the catalog
writer (``physical_inputs._sky_observation``): the reflected illuminance here
uses the stellar flux *at the target*, not at the observer — identical at the
nacrea anchor where the two distances coincide, and the first-principles choice
for cross-planet targets.

Rise/set samples the altitude over a window ``W = min(observer year,
max(solar-day term, sibling synodic term))`` (a star-locked observer without
either rotation field takes its orbital period), classifies rises_sets /
never_sets / never_rises from sign changes, and refines the first crossings by
bisection.  The parent seen from a locked observer has constant altitude and
falls out as never_sets.  Multi-year classifications (polar-night onset on slow
worlds) are deferred with M4's event search.

M1 defers: eclipse/transit events and their times (M4), analytic velocities
and disk position angles around the parent (derivable from the exported
observer frame in M2), horizon profiles, refraction and light-time (proposal
non-goals), and a background star catalogue (non-goal).

References:

* Murray & Dermott (1999), *Solar System Dynamics*, ch. 1–2 (Kepler's equation,
  element rotations, spin-orbit resonance states).
* *Explanatory Supplement to the Astronomical Supplement* (1992), ch. 4 (local
  horizon and equatorial frames, equinox/node conventions).
* Internal: ``engine/sky_geometry.py`` (photometry and the sub-planet
  convention), ``engine/stellar_physics.py`` (periods, instellation),
  ``engine/physical_inputs.py`` (catalog angle conventions: ϖ = Ω + ω, spin
  pole azimuth (Ω − 90) % 360, day-0-at-equinox anchoring).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from dreamulator.engine.sky_geometry import (
    AU_KM,
    SOLAR_RADIUS_KM,
    angular_size,
    geometric_albedo_from_bond,
    lambert_phase,
    reflected_apparent_magnitude,
    reflected_illuminance_w_m2,
    stellar_apparent_magnitude,
)
from dreamulator.engine.stellar_physics import instellation
from dreamulator.query_registry import query

__all__ = [
    "ObserverFrame",
    "OrbitalElementsState",
    "SkyEphemerisParams",
    "SkyEphemerisResult",
    "TargetPosition",
    "body_state_km",
    "observer_frame_km",
    "orbital_position_km",
    "sky_ephemeris",
    "solve_kepler_eccentric",
]

#: Newton iteration stops once the step falls below this (radians).
_KEPLER_TOL_RAD = 1e-12
#: Iteration cap for the Newton solver (divergence is a hard error).
_KEPLER_MAX_ITER = 50
#: Altitude samples over the rise/set window.
_RISE_SET_SAMPLES = 720
#: Bisection steps when refining a horizon crossing (~1e-12 of the window).
_RISE_SET_REFINE_STEPS = 40

#: Spin-axis provenance values, reported by ``ObserverFrame`` and the result:
#: "locked_to_parent" | "spin_axis_ecliptic_longitude" | "orbit_normal_fallback".

Vec3 = tuple[float, float, float]


# ---------------------------------------------------------------------------
# Vector helpers (math-module 3-tuples, matching satellite_dynamics' style)
# ---------------------------------------------------------------------------


def _add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _scale(a: Vec3, k: float) -> Vec3:
    return (a[0] * k, a[1] * k, a[2] * k)


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _norm(a: Vec3) -> float:
    return math.sqrt(_dot(a, a))


def _normalize(a: Vec3) -> Vec3:
    n = _norm(a)
    if n == 0.0:
        raise ValueError("cannot normalise a zero vector")
    return _scale(a, 1.0 / n)


def _angle_between_deg(a: Vec3, b: Vec3) -> float:
    """Angle between two vectors in degrees, clamped against float error."""
    cosine = max(-1.0, min(1.0, _dot(a, b) / (_norm(a) * _norm(b))))
    return math.degrees(math.acos(cosine))


# ---------------------------------------------------------------------------
# Layer 0 — Kepler machinery
# ---------------------------------------------------------------------------


def solve_kepler_eccentric(m_rad: float, e: float) -> float:
    """Eccentric anomaly of Kepler's equation ``E − e·sin E = M``.

    Newton–Raphson from ``E₀ = M`` (the same iteration the retired video-side
    prototype used, so anchor values transfer), quadratic for every catalog
    eccentricity; divergence is a hard error rather than a silent wrong answer.

    Args:
        m_rad: mean anomaly in radians (any range; wrapped internally).
        e: eccentricity, must satisfy ``0 ≤ e < 1``.

    Returns:
        Eccentric anomaly in radians, within 1e-12 of the root.

    Raises:
        ValueError: eccentricity outside ``[0, 1)`` (hyperbolic passes are out
            of scope — no catalog world carries one).
        RuntimeError: the iteration failed to converge.
    """
    if not 0.0 <= e < 1.0:
        raise ValueError(f"eccentricity must be in [0, 1), got {e}")
    # Kepler's equation is 2π-periodic: solve against the wrapped mean
    # anomaly.  The unwrapped value (many revolutions for a large ``t_days``)
    # can never be met by E in [0, 2π) and Newton would churn forever — this
    # was latent until queries went past a few hundred days.
    mean = math.fmod(m_rad, 2.0 * math.pi)
    if mean < 0.0:
        mean += 2.0 * math.pi
    eccentric = mean
    for _ in range(_KEPLER_MAX_ITER):
        step = (eccentric - e * math.sin(eccentric) - mean) / (1.0 - e * math.cos(eccentric))
        eccentric -= step
        if abs(step) < _KEPLER_TOL_RAD:
            return eccentric
    raise RuntimeError(f"Kepler solver did not converge (e={e}, M={m_rad} rad)")


@dataclass(frozen=True)
class OrbitalElementsState:
    """Two-body elements in the propagation form (angles in radians)."""

    body_id: str
    parent_id: str
    a_km: float
    e: float
    inclination_rad: float
    node_rad: float
    periapsis_rad: float
    mean_anomaly_epoch_rad: float
    period_days: float
    epoch_year: float


def _elements_from_entity(entity: dict[str, Any]) -> OrbitalElementsState:
    """Parse the propagation elements from one flattened catalog entity.

    Raises:
        KeyError: the entity lacks an element the ``orbits:`` merge provides.
    """
    required = (
        "semi_major_axis_au",
        "eccentricity",
        "inclination_deg",
        "longitude_ascending_node_deg",
        "argument_of_periapsis_deg",
        "mean_anomaly_epoch_deg",
        "period_days",
    )
    missing = [key for key in required if key not in entity]
    if missing:
        raise KeyError(
            f"body {entity.get('id', '?')} lacks orbital elements {missing}; the "
            "entities context must merge the catalog's orbits: section "
            "(guard.facts._load_entities)"
        )
    return OrbitalElementsState(
        body_id=str(entity["id"]),
        parent_id=str(entity["parent_id"]),
        a_km=float(entity["semi_major_axis_au"]) * AU_KM,
        e=float(entity["eccentricity"]),
        inclination_rad=math.radians(float(entity["inclination_deg"])),
        node_rad=math.radians(float(entity["longitude_ascending_node_deg"])),
        periapsis_rad=math.radians(float(entity["argument_of_periapsis_deg"])),
        mean_anomaly_epoch_rad=math.radians(float(entity["mean_anomaly_epoch_deg"])),
        period_days=float(entity["period_days"]),
        epoch_year=float(entity.get("epoch_year", 0.0)),
    )


def _orbit_normal(elements: OrbitalElementsState) -> Vec3:
    """Right-handed orbit normal ``(sin i · sin Ω, −sin i · cos Ω, cos i)``."""
    sin_i = math.sin(elements.inclination_rad)
    return (
        sin_i * math.sin(elements.node_rad),
        -sin_i * math.cos(elements.node_rad),
        math.cos(elements.inclination_rad),
    )


def orbital_position_km(elements: OrbitalElementsState, t_days: float) -> Vec3:
    """Body-centre position about its parent in the catalog ecliptic frame.

    ``t_days`` counts days from the catalog epoch (``epoch_year``, always 0.0
    in current worlds).  Mean anomaly advances by the catalog period
    (``bodies.orbit.period_days`` — the value the retired prototype and the
    catalog writer agree on), then the standard perifocal → ecliptic rotation
    by (Ω, i, ω) places the vector in the same frame as the star position.

    Args:
        elements: parsed propagation elements.
        t_days: days since the catalog epoch.

    Returns:
        Position in kilometres relative to the parent.
    """
    mean_anomaly = elements.mean_anomaly_epoch_rad + 2.0 * math.pi * t_days / elements.period_days
    eccentric = solve_kepler_eccentric(mean_anomaly, elements.e)
    e = elements.e
    true_anomaly = 2.0 * math.atan2(
        math.sqrt(1.0 + e) * math.sin(eccentric / 2.0),
        math.sqrt(1.0 - e) * math.cos(eccentric / 2.0),
    )
    radius = elements.a_km * (1.0 - e * math.cos(eccentric))
    x_peri = radius * math.cos(true_anomaly)
    y_peri = radius * math.sin(true_anomaly)
    cos_o, sin_o = math.cos(elements.node_rad), math.sin(elements.node_rad)
    cos_w, sin_w = math.cos(elements.periapsis_rad), math.sin(elements.periapsis_rad)
    cos_i, sin_i = math.cos(elements.inclination_rad), math.sin(elements.inclination_rad)
    x = x_peri * (cos_o * cos_w - sin_o * sin_w * cos_i) + y_peri * (
        -cos_o * sin_w - sin_o * cos_w * cos_i
    )
    y = x_peri * (sin_o * cos_w + cos_o * sin_w * cos_i) + y_peri * (
        -sin_o * sin_w + cos_o * cos_w * cos_i
    )
    z = x_peri * (sin_i * sin_w) + y_peri * (sin_i * cos_w)
    return (x, y, z)


def _is_star_entity(entity: dict[str, Any]) -> bool:
    return "parent_id" not in entity and "position" in entity


def _star_position_km(entity: dict[str, Any]) -> Vec3:
    position = entity["position"]
    if isinstance(position, dict):
        return (
            float(position.get("x", 0.0)) * AU_KM,
            float(position.get("y", 0.0)) * AU_KM,
            float(position.get("z", 0.0)) * AU_KM,
        )
    values = [float(v) for v in position]
    return (values[0] * AU_KM, values[1] * AU_KM, values[2] * AU_KM)


def body_state_km(entities: dict[str, dict[str, Any]], body_id: str, t_days: float) -> Vec3:
    """Position of a body or star in the shared ecliptic frame, star-anchored.

    Hierarchical two-body stacking: a star sits at its catalog position; a body
    sits at its parent's state plus its own Kepler offset.  The chain depth of
    catalog worlds is two (satellite → planet → star).

    Args:
        entities: flattened catalog entities (``guard.facts.build_fact_context``).
        body_id: stable body id (a star id is accepted).
        t_days: days since the catalog epoch.

    Returns:
        Ecliptic position in kilometres.

    Raises:
        KeyError: the id (or a parent along its chain) is unknown.
        ValueError: the parent chain contains a cycle or has no star at its root.
    """
    visited: set[str] = set()
    state: Vec3 = (0.0, 0.0, 0.0)
    current: str | None = body_id
    found_star = False
    while current is not None:
        if current in visited:
            raise ValueError(f"parent cycle in the orbit chain at {current}")
        visited.add(current)
        try:
            entity = entities[current]
        except KeyError:
            raise KeyError(f"unknown body id {current!r} (needed by {body_id!r})") from None
        if _is_star_entity(entity):
            state = _add(state, _star_position_km(entity))
            found_star = True
            break
        elements = _elements_from_entity(entity)
        state = _add(state, orbital_position_km(elements, t_days))
        current = elements.parent_id
    if not found_star:
        raise ValueError(f"orbit chain of {body_id!r} has no star at its root")
    return state


# ---------------------------------------------------------------------------
# Layer 1 — the observer's local frame
# ---------------------------------------------------------------------------


class ObserverFrame(BaseModel):
    """Ecliptic-frame vectors of one observer at one instant.

    ``east`` / ``north`` / ``up`` are the local ENU basis at (lat, lon);
    ``observer_km`` is the surface point (body centre + radius · up).
    ``spin_source`` records which rung of the spin-axis ladder was used.
    """

    observer_km: tuple[float, float, float]
    east: tuple[float, float, float]
    north: tuple[float, float, float]
    up: tuple[float, float, float]
    spin_source: str


def _spin_axis(entities: dict[str, dict[str, Any]], entity: dict[str, Any]) -> tuple[Vec3, str]:
    """Resolve the spin axis per the ladder in the module docstring."""
    if entity.get("tidally_locked"):
        return _orbit_normal(_elements_from_entity(entity)), "locked_to_parent"
    longitude = entity.get("spin_axis_ecliptic_longitude_deg")
    if longitude is not None:
        tilt = math.radians(float(entity.get("axial_tilt_deg", 0.0)))
        lam = math.radians(float(longitude))
        axis = (
            math.sin(tilt) * math.cos(lam),
            math.sin(tilt) * math.sin(lam),
            math.cos(tilt),
        )
        return axis, "spin_axis_ecliptic_longitude"
    tilt = float(entity.get("axial_tilt_deg", 0.0) or 0.0)
    is_satellite = entity.get("is_satellite", entity.get("body_type") == "natural_satellite")
    if is_satellite and tilt == 0.0:
        return _orbit_normal(_elements_from_entity(entity)), "orbit_normal_fallback"
    raise ValueError(
        f"body {entity.get('id', '?')} is not tidally locked and carries no "
        "spin_axis_ecliptic_longitude_deg, so its spin-axis azimuth is not "
        "determined (the catalog warns about exactly this case); observing from "
        "its surface is rejected rather than guessed"
    )


def _prime_meridian(
    entities: dict[str, dict[str, Any]],
    entity: dict[str, Any],
    axis: Vec3,
    spin_source: str,
    t_days: float,
) -> Vec3:
    """Body-fixed x̂ (the lon 0, lat 0 direction) at ``t_days``."""
    if spin_source == "locked_to_parent":
        # Instantaneous direction to the parent — the parent stands at the
        # zenith of (0, 0) at every instant (optical libration elsewhere).
        parent = _normalize(
            _sub(
                body_state_km(entities, str(entity["parent_id"]), t_days),
                body_state_km(entities, str(entity["id"]), t_days),
            )
        )
        return parent
    # Node-anchored rotation phase: at t = 0 the prime meridian points at the
    # ascending node — of the body equator when the spin azimuth is known,
    # of the orbit when the axis is the orbit-normal fallback.
    if spin_source == "spin_axis_ecliptic_longitude":
        node = _cross((0.0, 0.0, 1.0), axis)
        if _norm(node) < 1e-12:  # zero obliquity: the node is degenerate
            node = (1.0, 0.0, 0.0)
        node = _normalize(node)
    else:
        elements = _elements_from_entity(entity)
        node = (
            math.cos(elements.node_rad),
            math.sin(elements.node_rad),
            0.0,
        )
    theta = 2.0 * math.pi * t_days / float(entity["rotation_period_days"])
    west = _cross(axis, node)
    return _normalize(_add(_scale(node, math.cos(theta)), _scale(west, math.sin(theta))))


def _normalize_latlon(lat_deg: float, lon_deg: float) -> tuple[float, float]:
    """Validate latitude and wrap longitude into [−180, 180).

    Latitude beyond ±90° is a coordinate error, not a convention, and is
    rejected; any longitude is a well-defined point on the sphere and wraps
    modulo 360° (400° east is 40° east), so results report the wrapped value.

    Raises:
        ValueError: latitude outside [−90, 90].
    """
    if not -90.0 <= lat_deg <= 90.0:
        raise ValueError(f"latitude must be in [-90, 90] degrees, got {lat_deg}")
    wrapped = (lon_deg + 180.0) % 360.0 - 180.0
    return lat_deg, wrapped


def observer_frame_km(
    entities: dict[str, dict[str, Any]],
    observer_id: str,
    t_days: float,
    lat_deg: float,
    lon_deg: float,
) -> ObserverFrame:
    """ENU basis and surface position of one observer at one instant.

    Args:
        entities: flattened catalog entities.
        observer_id: stable id of the observing body.
        t_days: days since the catalog epoch.
        lat_deg: observer latitude, [−90, 90], north-positive.
        lon_deg: observer longitude, east-positive; wraps into [−180, 180).

    Returns:
        The ENU basis and surface point in ecliptic kilometres, with the
        spin-axis provenance.

    Raises:
        KeyError: the observer or a parent in its chain is unknown.
        ValueError: latitude outside [−90, 90], the spin axis cannot be
            resolved (see the ladder), or the parent chain contains a cycle.
    """
    lat_deg, lon_deg = _normalize_latlon(lat_deg, lon_deg)
    entity = entities[observer_id]
    axis, spin_source = _spin_axis(entities, entity)
    east_meridian = _prime_meridian(entities, entity, axis, spin_source, t_days)
    equator_east = _cross(axis, east_meridian)  # 90°E on the body equator

    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)
    cos_lat, sin_lat = math.cos(lat), math.sin(lat)
    cos_lon, sin_lon = math.cos(lon), math.sin(lon)
    up = _normalize(
        _add(
            _add(_scale(east_meridian, cos_lon * cos_lat), _scale(equator_east, sin_lon * cos_lat)),
            _scale(axis, sin_lat),
        )
    )
    north = _add(
        _add(
            _scale(east_meridian, -sin_lat * cos_lon),
            _scale(equator_east, -sin_lat * sin_lon),
        ),
        _scale(axis, cos_lat),
    )
    if _norm(north) < 1e-12:  # at the poles the tangent-plane north vanishes
        north = _scale(east_meridian, math.copysign(1.0, cos_lat or 1.0))
    north = _normalize(north)
    east = _cross(north, up)

    surface = _add(
        body_state_km(entities, observer_id, t_days),
        _scale(up, float(entity["radius_km"])),
    )
    return ObserverFrame(
        observer_km=surface,
        east=east,
        north=north,
        up=up,
        spin_source=spin_source,
    )


# ---------------------------------------------------------------------------
# Layer 2 — the registered query
# ---------------------------------------------------------------------------


class SkyEphemerisParams(BaseModel):
    """Parameters of the observer's-sky query."""

    observer_id: str
    lat_deg: float = 0.0
    lon_deg: float = 0.0
    at_days: float = 0.0
    targets: list[str] | None = None  # None → every entity except the observer
    include_events: bool = True  # False → skip rise/set (slider fast path)


class TargetPosition(BaseModel):
    """One target as seen from the observer at ``at_days``."""

    body_id: str
    name: str | None = None
    altitude_deg: float
    azimuth_deg: float
    ecliptic_lon_deg: float
    ecliptic_lat_deg: float
    equatorial_ra_deg: float
    equatorial_dec_deg: float
    distance_km: float
    angular_diameter_deg: float
    phase_angle_deg: float | None = None  # None for stars
    illuminated_fraction: float | None = None  # (1 + cos α)/2 — disk fraction
    phase_function: float | None = None  # Φ(α) — flux ratio
    apparent_magnitude: float
    illuminance_w_m2: float
    elongation_star_deg: float | None = None  # None for the star itself
    elongation_parent_deg: float | None = None
    altitude_rate_deg_per_hr: float
    # rises_sets | never_sets | never_rises; None when events not requested.
    rise_state: str | None = None
    next_rise_days: float | None = None  # offsets from at_days, > 0
    next_set_days: float | None = None


class SkyEphemerisResult(BaseModel):
    """The whole sky above one point of one body at one instant."""

    observer_id: str
    lat_deg: float
    lon_deg: float
    at_days: float
    solar_day_days: float | None = None
    spin_source: str | None = None
    targets: list[TargetPosition]


def _root_star(entities: dict[str, dict[str, Any]], body_id: str) -> str:
    """The star that illuminates a body (the root of its parent chain)."""
    current = body_id
    visited: set[str] = set()
    while True:
        if current in visited:
            raise ValueError(f"parent cycle in the orbit chain at {current}")
        visited.add(current)
        entity = entities[current]
        if _is_star_entity(entity):
            return current
        current = str(entity["parent_id"])


def _target_altitude_deg(
    entities: dict[str, dict[str, Any]],
    frame: ObserverFrame,
    target_id: str,
    t_days: float,
) -> float:
    """Target altitude above the ideal horizon at ``t_days`` (no photometry)."""
    direction = _sub(body_state_km(entities, target_id, t_days), frame.observer_km)
    cosine = max(-1.0, min(1.0, _dot(_normalize(direction), frame.up)))
    return math.degrees(math.asin(cosine))


def _rise_set(
    entities: dict[str, dict[str, Any]],
    observer_id: str,
    target_id: str,
    at_days: float,
    lat_deg: float,
    lon_deg: float,
) -> tuple[str, float | None, float | None]:
    """Classify rise/set and return (state, next_rise, next_set).

    The sampling window is ``min(observer year, max(solar-day term, sibling
    synodic term))`` — see the module docstring.  The altitude rate lives in
    ``sky_ephemeris`` (shared-frames central difference over all targets).
    """
    observer = entities[observer_id]
    target = entities[target_id]
    parent_id = observer.get("parent_id")
    year_days: float | None = None
    if parent_id is not None:
        parent = entities.get(str(parent_id))
        if parent is not None and "period_days" in parent:
            year_days = float(parent["period_days"])
    if year_days is None and "period_days" in observer:
        year_days = float(observer["period_days"])
    day_term: float | None = None
    for key in ("solar_day_days", "rotation_period_days"):
        if key in observer:
            day_term = float(observer[key])
            break
    synodic_term: float | None = None
    if (
        parent_id is not None
        and str(target.get("parent_id")) == str(parent_id)
        and "period_days" in observer
        and "period_days" in target
        and observer["period_days"] != target["period_days"]
    ):
        p_obs, p_target = float(observer["period_days"]), float(target["period_days"])
        synodic_term = abs(1.0 / p_obs - 1.0 / p_target) ** -1
    inner = max((term for term in (day_term, synodic_term) if term is not None), default=None)
    if inner is not None and year_days is not None:
        window = min(inner, year_days)
    else:
        window = inner if inner is not None else float(observer["period_days"])

    frame_cache: dict[float, ObserverFrame] = {}

    def altitude(t: float) -> float:
        frame = frame_cache.get(t)
        if frame is None:
            frame = observer_frame_km(entities, observer_id, t, lat_deg, lon_deg)
            frame_cache[t] = frame
        return _target_altitude_deg(entities, frame, target_id, t)

    step = window / _RISE_SET_SAMPLES
    # One step beyond the window: a crossing of each kind recurs within every
    # full period ≤ window, and the extra step catches the one that starts the
    # window just past an event.
    samples = [altitude(at_days + i * step) for i in range(_RISE_SET_SAMPLES + 2)]
    signs = [s >= 0.0 for s in samples]
    if all(signs):
        state, rise, setting = "never_sets", None, None
    elif not any(signs):
        state, rise, setting = "never_rises", None, None
    else:
        state = "rises_sets"

        def refine(t_lo: float, t_hi: float) -> float:
            a_lo = altitude(t_lo)
            for _ in range(_RISE_SET_REFINE_STEPS):
                t_mid = 0.5 * (t_lo + t_hi)
                a_mid = altitude(t_mid)
                if (a_mid >= 0.0) == (a_lo >= 0.0):
                    t_lo, a_lo = t_mid, a_mid
                else:
                    t_hi = t_mid
            return 0.5 * (t_lo + t_hi)

        rise = setting = None
        for i in range(len(samples) - 1):
            if signs[i] != signs[i + 1]:
                crossing = refine(at_days + i * step, at_days + (i + 1) * step)
                if samples[i] >= 0.0:  # above → below: a setting
                    if setting is None:
                        setting = crossing - at_days
                elif rise is None:  # below → above: a rising
                    rise = crossing - at_days
                if rise is not None and setting is not None:
                    break
    return state, rise, setting


@query(
    name="sky_ephemeris",
    description=(
        "The observer's sky at one instant: for every target body its alt/az, "
        "ecliptic and equatorial coordinates, angular diameter, phase and "
        "illumination, apparent magnitude, elongations, rise/set state and "
        "altitude rate, from any body's surface at (lat, lon)."
    ),
    dimension="sky",
    context="entities",
    params_model=SkyEphemerisParams,
    result_model=SkyEphemerisResult,
)
def sky_ephemeris(
    entities: dict[str, dict[str, Any]],
    observer_id: str,
    lat_deg: float = 0.0,
    lon_deg: float = 0.0,
    at_days: float = 0.0,
    targets: list[str] | None = None,
    include_events: bool = True,
) -> SkyEphemerisResult:
    """Everything the sky above one point of one body shows at one moment.

    Args:
        entities: flattened catalog entities (``guard.facts.build_fact_context``
            — the ``orbits:`` merge must have run so elements are full precision).
        observer_id: stable id of the observing body.
        lat_deg: observer latitude, north-positive.
        lon_deg: observer longitude, east of the prime meridian.
        at_days: days since the catalog epoch.
        targets: stable ids to report; ``None`` for every entity except the
            observer, in catalog order.
        include_events: keep the rise/set search (the O(period) part, ~50 ms
            per target).  ``False`` is the slider fast path — positions,
            photometry and altitude rate stay, rise_state and the next
            rise/set offsets become ``None``.

    Returns:
        The per-target sky table with the observer's context.

    Raises:
        KeyError: the observer, a target, or a parent in a chain is unknown.
        ValueError: the observer's spin axis is undetermined, or a parent
            chain contains a cycle.
    """
    lat_deg, lon_deg = _normalize_latlon(lat_deg, lon_deg)
    frame = observer_frame_km(entities, observer_id, at_days, lat_deg, lon_deg)
    observer_entity = entities[observer_id]

    # Altitude rate: one central difference shared by every target — two
    # observer frames at ±h and one body state per target per side.  The step
    # matches the rise/set sampling density; like the per-target difference it
    # replaced, it is an O(h²) approximation of the same derivative.
    rate_step: float | None = None
    for key in ("solar_day_days", "rotation_period_days"):
        if key in observer_entity:
            rate_step = float(observer_entity[key]) / _RISE_SET_SAMPLES
            break
    frames_pm: tuple[ObserverFrame, ObserverFrame] | None = None
    if rate_step is not None and rate_step > 0.0:
        frames_pm = (
            observer_frame_km(entities, observer_id, at_days - rate_step, lat_deg, lon_deg),
            observer_frame_km(entities, observer_id, at_days + rate_step, lat_deg, lon_deg),
        )

    # The observer body's equatorial frame (RA 0 = its own equinox direction).
    axis, _spin = _spin_axis(entities, observer_entity)
    ra_zero = _cross((0.0, 0.0, 1.0), axis)
    if _norm(ra_zero) < 1e-12:
        ra_zero = (1.0, 0.0, 0.0)
    ra_zero = _normalize(ra_zero)
    ra_ninety = _cross(axis, ra_zero)

    if targets is None:
        target_ids = [key for key in entities if key != observer_id]
    else:
        target_ids = list(targets)

    parent_id = observer_entity.get("parent_id")
    rows: list[TargetPosition] = []
    for target_id in target_ids:
        entity = entities[target_id]
        target_pos = body_state_km(entities, target_id, at_days)
        delta = _sub(target_pos, frame.observer_km)
        distance = _norm(delta)
        direction = _scale(delta, 1.0 / distance)

        cosine = max(-1.0, min(1.0, _dot(direction, frame.up)))
        altitude = math.degrees(math.asin(cosine))
        azimuth = (
            math.degrees(math.atan2(_dot(direction, frame.east), _dot(direction, frame.north)))
            % 360.0
        )
        ecliptic_lon = math.degrees(math.atan2(direction[1], direction[0])) % 360.0
        ecliptic_lat = math.degrees(math.asin(max(-1.0, min(1.0, direction[2]))))
        ra = math.degrees(math.atan2(_dot(direction, ra_ninety), _dot(direction, ra_zero))) % 360.0
        dec = math.degrees(math.asin(max(-1.0, min(1.0, _dot(direction, axis)))))

        is_star = _is_star_entity(entity)
        if is_star:
            radius_km = float(entity.get("radius_sol", 0.0) or 0.0) * SOLAR_RADIUS_KM
            luminosity = float(entity.get("luminosity_sol", 0.0) or 0.0)
            star_distance_au = distance / AU_KM
            magnitude = stellar_apparent_magnitude(luminosity, star_distance_au)
            illuminance = instellation(luminosity, star_distance_au)
            phase_angle = illuminated = phase_fn = elongation_star = None
            star_id = target_id
        else:
            radius_km = float(entity.get("radius_km", 0.0) or 0.0)
            star_id = _root_star(entities, target_id)
            star_entity = entities[star_id]
            luminosity = float(star_entity.get("luminosity_sol", 0.0) or 0.0)
            star_pos = body_state_km(entities, star_id, at_days)
            star_to_target = _normalize(_sub(star_pos, target_pos))
            observer_to_target = _scale(direction, -1.0)
            phase_angle = _angle_between_deg(star_to_target, observer_to_target)
            alpha_rad = math.radians(phase_angle)
            illuminated = (1.0 + math.cos(alpha_rad)) / 2.0
            phase_fn = lambert_phase(alpha_rad)
            star_observer_distance_au = _sub(star_pos, frame.observer_km)
            star_body_distance_au = _sub(star_pos, target_pos)
            magnitude = reflected_apparent_magnitude(
                star_magnitude=stellar_apparent_magnitude(
                    luminosity, _norm(star_observer_distance_au) / AU_KM
                ),
                geometric_albedo=geometric_albedo_from_bond(
                    float(entity.get("albedo", 0.3) or 0.3)
                ),
                radius_km=radius_km,
                observer_distance_km=distance,
                star_body_distance_au=_norm(star_body_distance_au) / AU_KM,
                star_observer_distance_au=_norm(star_observer_distance_au) / AU_KM,
                phase_angle_rad=alpha_rad,
            )
            # First principles: the flux that lights the disk is the star's
            # flux at the target (see the module docstring's deviation note).
            illuminance = reflected_illuminance_w_m2(
                star_flux_w_m2=instellation(luminosity, _norm(star_body_distance_au) / AU_KM),
                geometric_albedo=geometric_albedo_from_bond(
                    float(entity.get("albedo", 0.3) or 0.3)
                ),
                radius_km=radius_km,
                observer_distance_km=distance,
                phase_angle_rad=alpha_rad,
            )
            elongation_star = _angle_between_deg(_sub(star_pos, frame.observer_km), delta)

        elongation_parent = None
        if parent_id is not None and target_id != parent_id:
            parent_direction = _sub(
                body_state_km(entities, str(parent_id), at_days), frame.observer_km
            )
            elongation_parent = _angle_between_deg(parent_direction, delta)

        state: str | None
        next_rise: float | None
        next_set: float | None
        if include_events:
            state, next_rise, next_set = _rise_set(
                entities, observer_id, target_id, at_days, lat_deg, lon_deg
            )
        else:
            state = next_rise = next_set = None
        if frames_pm is not None and rate_step is not None:
            altitude_pm = (
                _target_altitude_deg(entities, frames_pm[0], target_id, at_days - rate_step),
                _target_altitude_deg(entities, frames_pm[1], target_id, at_days + rate_step),
            )
            # Central difference over ±rate_step DAYS: °/day = Δ/(2·step),
            # and °/h = °/day / 24 — i.e. Δ/(48·step).  (An earlier ×12/step
            # multiplied by 24 instead of dividing: a 576× overstatement.)
            rate = (altitude_pm[1] - altitude_pm[0]) / (48.0 * rate_step)
        else:
            # No rotation field at all (a star-locked observer): the horizon
            # does not turn, and the target's own motion sets the rate; the
            # single-instant query reports 0 rather than a second evaluation.
            rate = 0.0
        rows.append(
            TargetPosition(
                body_id=target_id,
                name=entity.get("name"),
                altitude_deg=altitude,
                azimuth_deg=azimuth,
                ecliptic_lon_deg=ecliptic_lon,
                ecliptic_lat_deg=ecliptic_lat,
                equatorial_ra_deg=ra,
                equatorial_dec_deg=dec,
                distance_km=distance,
                angular_diameter_deg=angular_size(radius_km, distance),
                phase_angle_deg=phase_angle,
                illuminated_fraction=illuminated,
                phase_function=phase_fn,
                apparent_magnitude=magnitude,
                illuminance_w_m2=illuminance,
                elongation_star_deg=elongation_star,
                elongation_parent_deg=elongation_parent,
                altitude_rate_deg_per_hr=rate,
                rise_state=state,
                next_rise_days=next_rise,
                next_set_days=next_set,
            )
        )

    solar_day = observer_entity.get("solar_day_days")
    return SkyEphemerisResult(
        observer_id=observer_id,
        lat_deg=lat_deg,
        lon_deg=lon_deg,
        at_days=at_days,
        solar_day_days=float(solar_day) if solar_day is not None else None,
        spin_source=frame.spin_source,
        targets=rows,
    )
