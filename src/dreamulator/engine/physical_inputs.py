"""Shared resolution of physical forcing parameters for engines.

Both the geological engine (terrain pipeline) and the climate engine need
the same physical parameters: stellar luminosity, orbital distance, planet
radius / axial tilt / rotation, and greenhouse warming.  Historically each
engine resolved these independently, so the two climate passes could diverge
(the geological engine silently ran with Earth defaults while the climate
engine read ``planets.yaml``).  This module is the single resolution path
used by both engines.

Satellite handling
------------------
A body whose ``orbits`` field points at a planet rather than a star (e.g.
the habitable moon nacrea, which orbits the gas giant Aegis) is walked up
the ``orbits`` table in ``stellar.yaml`` until the host star is found.

For the received stellar flux we use the **host planet's heliocentric
distance**, ignoring the satellite's own orbit around the planet.  With
``eps = a_moon / a_planet``, the time-averaged insolation correction is
``1/(1 - eps**2) - 1 ~ eps**2`` and the instantaneous extremes are
``~ +/-2*eps`` (both from averaging ``1/d^2`` over the moon's orbit).
For nacrea (eps = 0.00494/0.2795 = 0.0177) the mean error is +0.03% and the
78-hour oscillation is +/-3.5% — far below climate-model and
geomorphic-erosion resolution, and smaller than the host planet's own
eccentricity modulation.  Moon orbits are Hill-sphere bounded (stable orbits
< ~0.4 R_H), so eps stays < ~0.05 and the mean approximation keeps < 0.25%
error for every physically plausible moon.
"""

from __future__ import annotations

import logging
from contextlib import suppress
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import yaml

from dreamulator.engine.stellar_physics import (
    EARTH_MASS_SOL,
    equilibrium_temperature,
    habitable_zone_boundaries,
    habitable_zone_center,
    instellation,
    instellation_earth_units,
    kepler_orbital_period,
    main_sequence_lifetime,
    polar_circle_latitude_deg,
    solar_day_days,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from dreamulator.engine.base import BaseEngine
    from dreamulator.map.pipeline_types import TerrainPipelineConfig
    from dreamulator.models.planet import Planet

logger = logging.getLogger(__name__)

# Maximum parent-chain depth when walking body -> ... -> star.
_MAX_PARENT_DEPTH = 8

# Fallbacks when stellar/orbital data is unavailable (Earth-like).
DEFAULT_LUMINOSITY_SOL = 1.0
DEFAULT_ORBITAL_DISTANCE_AU = 1.0

# Config fields that carry physical (planet/stellar) parameters, as opposed
# to terrain-generation knobs.  Used by the geological engine to detect
# terrain_config values overridden by canonical layer inputs.
PHYSICAL_CONFIG_FIELDS = (
    "stellar_luminosity_sol",
    "orbital_distance_au",
    "orbital_period_days",
    "axial_tilt_deg",
    "rotation_period_days",
    "radius_km",
    "gravity_m_s2",
    "surface_pressure_hpa",
    "albedo",
    "greenhouse_warming_K",
    "eccentricity",
)

# Standard gravity used to convert (mass, radius) in Earth units to m/s².
_G_EARTH_M_S2 = 9.81
# Reference surface pressure for 1 atm, in hPa.
_ONE_ATM_HPA = 1013.25
# Earth's orbital period (days); fallback when the host star's mass is
# unknown and Kepler's third law cannot be applied.
_EARTH_ORBITAL_PERIOD_DAYS = 365.25


def load_planets(path: Path) -> tuple[list[Planet], list[str]]:
    """Load planets from a ``planets.yaml`` file.

    Args:
        path: Path to the YAML file.

    Returns:
        (planets, warnings); malformed entries are skipped with a warning.
    """
    from dreamulator.models.planet import Planet

    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    planets_raw = data.get("planets", []) if isinstance(data, dict) else []
    planets: list[Planet] = []
    warnings: list[str] = []
    for pdata in planets_raw:
        if not isinstance(pdata, dict):
            continue
        try:
            planets.append(Planet(**pdata))
        except Exception as e:
            warnings.append(f"Failed to parse planet {pdata.get('id', '?')}: {e}")

    return planets, warnings


def load_planet_for_engine(
    engine: BaseEngine,
    planet_id: str | None = None,
) -> tuple[Planet | None, list[str]]:
    """Locate ``planets.yaml`` through the engine's layer search path.

    Args:
        engine: Engine whose ``find_input`` resolves layer files.
        planet_id: Preferred planet; falls back to the first planet when
            absent or unmatched.

    Returns:
        (planet, warnings); ``(None, [])`` when planets.yaml is absent.
    """
    path = engine.find_input("planets.yaml")
    if path is None:
        return None, []
    planets, warnings = load_planets(path)
    if not planets:
        return None, warnings
    if planet_id is not None:
        for planet in planets:
            if planet.id == planet_id:
                return planet, warnings
    return planets[0], warnings


@dataclass
class _StellarIndex:
    """Parsed lookup tables over stellar.yaml / stellar_derived.yaml."""

    luminosities: dict[str, float] = field(default_factory=dict)  # star id -> L/L_sun
    masses: dict[str, float] = field(default_factory=dict)  # star id -> M/M_sun
    ages: dict[str, float] = field(default_factory=dict)  # star id -> age/Gyr
    radii: dict[str, float] = field(default_factory=dict)  # star id -> R/R_sun
    temperatures: dict[str, float] = field(default_factory=dict)  # star id -> T_eff/K
    ms_lifetimes: dict[str, float] = field(default_factory=dict)  # star id -> Gyr
    evolution_progresses: dict[str, float] = field(default_factory=dict)  # star id -> [0,1]
    body_masses: dict[str, float] = field(default_factory=dict)  # body id -> M/M_earth
    orbits: dict[str, dict[str, Any]] = field(default_factory=dict)  # body id -> entry
    star_ids: set[str] = field(default_factory=set)


def _read_mapping(engine: BaseEngine, relative_path: str) -> dict[str, Any] | None:
    path = engine.find_input(relative_path)
    if path is None:
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as e:
        logger.warning("Failed to read %s: %s", path, e)
        return None
    return data if isinstance(data, dict) else None


def _first_float(star: dict[str, Any], *keys: str) -> float | None:
    """First numeric value among *keys* of a star mapping, else None."""
    for key in keys:
        value = star.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            logger.warning("Non-numeric %s for star %s", key, star.get("id"))
    return None


def _index_stellar_data(engine: BaseEngine) -> _StellarIndex:
    """Index star parameters and orbit entries from the astronomy layer.

    ``stellar_derived.yaml`` (engine-computed) overrides ``stellar.yaml``
    (authored) for all star fields; orbit elements come from ``stellar.yaml``.
    """
    input_data = _read_mapping(engine, "stellar.yaml")
    derived_data = _read_mapping(engine, "stellar_derived.yaml")

    index = _StellarIndex()
    for source in (input_data, derived_data):
        if source is None:
            continue
        for star in source.get("stars") or []:
            if not isinstance(star, dict) or star.get("id") is None:
                continue
            star_id = str(star["id"])
            index.star_ids.add(star_id)
            luminosity = _first_float(star, "computed_luminosity", "luminosity")
            if luminosity is not None:
                index.luminosities[star_id] = luminosity
            mass = _first_float(star, "computed_mass", "mass")
            if mass is not None:
                index.masses[star_id] = mass
            age = _first_float(star, "age_gyr")
            if age is not None:
                index.ages[star_id] = age
            radius = _first_float(star, "computed_radius", "radius")
            if radius is not None:
                index.radii[star_id] = radius
            temperature = _first_float(star, "computed_temperature", "temperature")
            if temperature is not None:
                index.temperatures[star_id] = temperature
            lifetime = _first_float(star, "ms_lifetime_gyr")
            if lifetime is not None:
                index.ms_lifetimes[star_id] = lifetime
            progress = _first_float(star, "evolution_progress")
            if progress is not None:
                index.evolution_progresses[star_id] = progress
        for body in source.get("bodies") or []:
            if not isinstance(body, dict) or body.get("id") is None:
                continue
            mass_earth = _first_float(body, "mass_earth")
            if mass_earth is not None:
                index.body_masses[str(body["id"])] = mass_earth

    if input_data is not None:
        for entry in input_data.get("orbits") or []:
            if isinstance(entry, dict) and entry.get("body_id") is not None:
                index.orbits[str(entry["body_id"])] = entry
    return index


def _walk_to_star(body_id: str, index: _StellarIndex) -> str | None:
    """Return the star id reached by following parent links from *body_id*."""
    current = body_id
    seen = {current}
    for _ in range(_MAX_PARENT_DEPTH):
        if current in index.star_ids:
            return current
        entry = index.orbits.get(current)
        parent_raw = entry.get("parent_id") if entry is not None else None
        if parent_raw is None:
            return None
        parent = str(parent_raw)
        if parent in index.star_ids:
            return parent
        if parent in seen:
            return None
        seen.add(parent)
        current = parent
    return None


def _heliocentric_distance_au(body_id: str, index: _StellarIndex) -> float | None:
    """Heliocentric distance of *body_id* from the orbits table.

    Returns the semi-major axis of the chain member that directly orbits the
    star.  A satellite's own orbit around its planet averages out (see the
    module docstring for the error analysis), so satellite links contribute
    nothing to the heliocentric distance.
    """
    current = body_id
    seen = {current}
    for _ in range(_MAX_PARENT_DEPTH):
        if current in index.star_ids:
            return None  # the body is itself a star; distance is undefined
        entry = index.orbits.get(current)
        if entry is None:
            return None
        parent_raw = entry.get("parent_id")
        if parent_raw is None:
            return None
        parent = str(parent_raw)
        if parent in index.star_ids:
            try:
                return float(entry["semi_major_axis_au"])
            except (KeyError, TypeError, ValueError):
                return None
        if parent in seen:
            return None
        seen.add(parent)
        current = parent
    return None


def _heliocentric_eccentricity(body_id: str, index: _StellarIndex) -> float | None:
    """Heliocentric-orbit eccentricity of *body_id* from the orbits table.

    Returns the eccentricity of the chain member that directly orbits the star.
    A satellite's own orbit around its planet drives only tidal heating (see
    ``resolve_tidal_heating``), NOT the seasonal insolation cycle — so it must
    be ignored here.  Mirrors ``_heliocentric_distance_au``.
    """
    current = body_id
    seen = {current}
    for _ in range(_MAX_PARENT_DEPTH):
        if current in index.star_ids:
            return None  # the body is itself a star; eccentricity is undefined
        entry = index.orbits.get(current)
        if entry is None:
            return None
        parent_raw = entry.get("parent_id")
        if parent_raw is None:
            return None
        parent = str(parent_raw)
        if parent in index.star_ids:
            try:
                return float(entry["eccentricity"])
            except (KeyError, TypeError, ValueError):
                return None
        if parent in seen:
            return None
        seen.add(parent)
        current = parent
    return None


def resolve_orbital_elements(
    engine: BaseEngine,
    planet: Planet | None,
) -> tuple[float | None, bool, list[str]]:
    """Resolve the heliocentric eccentricity and satellite status.

    The seasonal insolation cycle follows the heliocentric orbit, so its
    eccentricity (of the chain member directly orbiting the star) — not the
    satellite's own orbit eccentricity — drives the annual insolation
    variation.  ``is_satellite`` is informational: it is returned for a future
    compound-obliquity convention check, but this pass does **not** auto-apply
    any compound obliquity (``config.axial_tilt_deg`` is already the effective
    obliquity; see ``climate_seasonality.compute_effective_obliquity``).

    Args:
        engine: Engine whose ``find_input`` resolves layer files.
        planet: Target body (may orbit a star or a planet).

    Returns:
        ``(eccentricity, is_satellite, warnings)``.  ``eccentricity`` is None
        when no heliocentric orbit entry carries one (treated as circular).
    """
    warnings: list[str] = []
    if planet is None:
        return None, False, warnings

    index = _index_stellar_data(engine)
    if not index.star_ids and not index.orbits:
        return None, False, warnings

    eccentricity = _heliocentric_eccentricity(planet.id, index)
    if eccentricity is None and _heliocentric_distance_au(planet.id, index) is not None:
        warnings.append(f"Orbit of '{planet.id}' has no eccentricity; treating as circular (e=0)")

    entry = index.orbits.get(planet.id)
    parent = str(entry.get("parent_id")) if entry and entry.get("parent_id") is not None else None
    is_satellite = parent is not None and parent not in index.star_ids

    return eccentricity, is_satellite, warnings


def resolve_stellar_forcing(
    engine: BaseEngine,
    planet: Planet | None,
) -> tuple[float | None, float | None, float | None, list[str]]:
    """Resolve stellar luminosity, heliocentric distance, and year length.

    The orbital period follows from Kepler's third law
    ``P = 365.25 d × sqrt(a³/M)`` (a in AU, M in solar masses) using the
    resolved distance and the host star's mass.

    Args:
        engine: Engine whose ``find_input`` resolves layer files.
        planet: Target body (may orbit a star or a planet).

    Returns:
        ``(luminosity_sol, distance_au, period_days, warnings)``.
        Luminosity and distance are None together when the data is
        insufficient; callers must then keep coherent Earth-like defaults
        for **both** rather than mixing a resolved luminosity with a default
        distance (a physically incoherent forcing combination).  The period
        is None when the host star's mass is unknown even though luminosity
        and distance resolved.
    """
    warnings: list[str] = []
    if planet is None:
        return None, None, None, warnings

    index = _index_stellar_data(engine)
    if not index.star_ids and not index.orbits:
        # No stellar data at all — silent Earth-like defaults.
        return None, None, None, warnings

    star_id = _walk_to_star(planet.id, index)
    if star_id is None and planet.orbits in index.star_ids:
        # Legacy layout: planet.orbits names the star directly, with no
        # orbit-table entry for the planet itself.
        star_id = planet.orbits

    luminosity: float | None = None
    if star_id is not None:
        luminosity = index.luminosities.get(star_id)
        if luminosity is None:
            warnings.append(
                f"No luminosity for host star '{star_id}' of '{planet.id}'; "
                f"keeping default {DEFAULT_LUMINOSITY_SOL} L_sun"
            )
    else:
        warnings.append(
            f"Could not resolve host star for '{planet.id}'; "
            f"keeping default {DEFAULT_LUMINOSITY_SOL} L_sun"
        )

    distance = _heliocentric_distance_au(planet.id, index)
    if distance is None:
        warnings.append(
            f"No orbital elements for '{planet.id}'; "
            f"keeping default {DEFAULT_ORBITAL_DISTANCE_AU} AU"
        )

    if luminosity is None or distance is None:
        return None, None, None, warnings

    period: float | None = None
    mass = index.masses.get(star_id) if star_id is not None else None
    if mass is not None and mass > 0:
        period = _EARTH_ORBITAL_PERIOD_DAYS * (distance**3 / mass) ** 0.5
    else:
        warnings.append(
            f"No mass for host star '{star_id}' of '{planet.id}'; "
            f"keeping default {_EARTH_ORBITAL_PERIOD_DAYS}-day orbital period"
        )
    return luminosity, distance, period, warnings


def resolve_stellar_temperature(
    engine: BaseEngine,
    planet: Planet | None,
) -> float | None:
    """Resolve the host star's effective temperature (K) for the spectral ice albedo.

    Ice/snow albedo is spectrally dependent (high in the visible, low in the
    near-IR), so the effective ice albedo depends on the host star's spectral
    energy distribution (Shields et al. 2012).  Returns None when the stellar
    temperature is unavailable — callers keep the Sun-like default.

    Args:
        engine: Engine whose ``find_input`` resolves the stellar-derived layer.
        planet: Target body (may orbit a star or a planet).

    Returns:
        Host star effective temperature (K), or None if unresolved.
    """
    if planet is None:
        return None
    index = _index_stellar_data(engine)
    if not index.star_ids and not index.orbits:
        return None
    star_id = _walk_to_star(planet.id, index)
    if star_id is None and planet.orbits in index.star_ids:
        star_id = planet.orbits
    if star_id is None:
        return None
    return index.temperatures.get(star_id)


def apply_physical_parameters(
    config: TerrainPipelineConfig,
    planet: Planet | None,
    stellar_luminosity_sol: float | None = None,
    orbital_distance_au: float | None = None,
    orbital_period_days: float | None = None,
    eccentricity: float | None = None,
    stellar_temperature_k: float | None = None,
) -> None:
    """Write resolved physical parameters onto *config* in place.

    None values leave the corresponding config field untouched.
    """
    if stellar_luminosity_sol is not None:
        config.stellar_luminosity_sol = stellar_luminosity_sol
    if stellar_temperature_k is not None:
        config.stellar_temperature_k = stellar_temperature_k
    if orbital_distance_au is not None:
        config.orbital_distance_au = orbital_distance_au
    if orbital_period_days is not None:
        config.orbital_period_days = orbital_period_days
    if eccentricity is not None:
        config.eccentricity = eccentricity
    if planet is None:
        return
    # The `is not None` guards only cover Optional model variants; an explicit
    # 0.0 (e.g. a tidally locked body's axial tilt) must NOT be replaced with
    # an Earth-like fallback.
    if planet.axial_tilt_deg is not None:
        config.axial_tilt_deg = planet.axial_tilt_deg
    if planet.rotation_period_days is not None:
        config.rotation_period_days = planet.rotation_period_days
    config.radius_km = float(planet.radius) * 6371.0
    config.gravity_m_s2 = _G_EARTH_M_S2 * float(planet.mass) / float(planet.radius) ** 2
    config.albedo = planet.albedo
    if planet.atmosphere is not None:
        config.greenhouse_warming_K = planet.atmosphere.greenhouse_factor
        config.surface_pressure_hpa = planet.atmosphere.surface_pressure_atm * _ONE_ATM_HPA


def resolve_and_apply_physical_parameters(
    engine: BaseEngine,
    config: TerrainPipelineConfig,
    planet: Planet | None = None,
    planet_id: str | None = None,
) -> list[str]:
    """One-call physical-parameter resolution for engines.

    Loads ``planets.yaml`` / ``stellar.yaml`` / ``stellar_derived.yaml``
    through the engine's layer search path and applies luminosity, orbital
    distance, axial tilt, rotation, radius, and greenhouse warming onto
    *config*.  Satellite bodies resolve against their host star (module
    docstring).

    Args:
        engine: Engine whose ``find_input`` resolves layer files.
        config: Configuration to update in place.
        planet: Pre-loaded planet; looked up via *planet_id* when omitted.
        planet_id: Preferred planet id when *planet* is omitted.

    Returns:
        Warnings suitable for ``EngineResult.warnings``.
    """
    warnings: list[str] = []
    if planet is None:
        planet, planet_warnings = load_planet_for_engine(engine, planet_id)
        warnings.extend(planet_warnings)

    luminosity, distance, period, stellar_warnings = resolve_stellar_forcing(engine, planet)
    warnings.extend(stellar_warnings)

    stellar_temperature_k = resolve_stellar_temperature(engine, planet)

    eccentricity, _is_satellite, orbital_warnings = resolve_orbital_elements(engine, planet)
    warnings.extend(orbital_warnings)

    apply_physical_parameters(
        config,
        planet,
        luminosity,
        distance,
        period,
        eccentricity,
        stellar_temperature_k=stellar_temperature_k,
    )
    return warnings


def _as_float(value: Any) -> float | None:
    """Coerce a raw YAML value to float, or None when absent/non-numeric."""
    if value is None:
        return None
    with suppress(TypeError, ValueError):
        return float(value)
    return None


def check_body_field_consistency(
    bodies: Sequence[Mapping[str, Any]],
    planets: Sequence[Planet],
    *,
    rel_tol: float = 1e-3,
) -> list[str]:
    """Cross-check fields duplicated between stellar.yaml ``bodies`` and planets.yaml.

    planets.yaml is the authoritative source for shared physical fields (the
    engines consume it via ``apply_physical_parameters``); the ``bodies``
    section only supplements narrative and classification.  Divergences beyond
    *rel_tol* are reported so authors reconcile them — three such drifts were
    found and fixed in nacrea when this check was introduced (2026-08).

    Args:
        bodies: Raw ``bodies`` entries from stellar.yaml.
        planets: Parsed Planet models from planets.yaml.
        rel_tol: Relative tolerance for the float comparison.

    Returns:
        One warning string per divergent field (empty when consistent).
    """
    warnings: list[str] = []
    planets_by_id = {p.id: p for p in planets}

    def close(a: float, b: float) -> bool:
        return abs(a - b) <= rel_tol * max(abs(a), abs(b), 1e-12)

    for body in bodies:
        body_id = body.get("id")
        if body_id is None:
            continue
        planet = planets_by_id.get(str(body_id))
        if planet is None:
            continue
        pairs = [
            ("mass_earth", _as_float(body.get("mass_earth")), float(planet.mass)),
            ("radius_km", _as_float(body.get("radius_km")), float(planet.radius) * 6371.0),
            (
                "rotation_period_days",
                _as_float(body.get("rotation_period_days")),
                float(planet.rotation_period_days),
            ),
            ("axial_tilt_deg", _as_float(body.get("axial_tilt_deg")), float(planet.axial_tilt_deg)),
            ("albedo", _as_float(body.get("albedo")), float(planet.albedo)),
        ]
        for field_name, body_value, planet_value in pairs:
            if body_value is None or close(body_value, planet_value):
                continue
            warnings.append(
                f"body '{body_id}': {field_name} differs between stellar.yaml bodies "
                f"({body_value}) and planets.yaml ({planet_value}); planets.yaml is "
                f"authoritative for engine runs"
            )
    return warnings


def build_system_catalog(
    engine: BaseEngine,
    computed_stars: Mapping[str, Mapping[str, float]] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Merge stellar.yaml + planets.yaml into one machine-generated catalog.

    The authored celestial-body data is split across two layer inputs
    (astronomy ``stellar.yaml``: stars / orbits / narrative bodies; geological
    ``planets.yaml``: authoritative physical parameters + atmosphere /
    hydrosphere).  This catalog joins them per body — planets.yaml wins for
    shared fields, divergences are warned via ``check_body_field_consistency``
    — and attaches derived quantities (orbital periods, instellation, solar
    day, tidal-lock state, habitable-zone membership).  Consumers (frontend
    3D viewer, body-encyclopedia UI) read this single derived file instead of
    merging the two inputs themselves.

    Args:
        engine: Engine whose ``find_input`` resolves layer files.
        computed_stars: Optional in-memory stellar parameters from the
            astronomy engine (same shape the astronomy engine passes).

    Returns:
        ``(catalog, warnings)``.  Keys are omitted when the input data cannot
        support them.
    """
    warnings: list[str] = []
    input_data = _read_mapping(engine, "stellar.yaml")
    if input_data is None:
        warnings.append("stellar.yaml not found; system catalog is empty")
        return {}, warnings

    index = _index_stellar_data(engine)

    planets: list[Planet] = []
    planets_path = engine.find_input("planets.yaml")
    if planets_path is not None:
        planets, planet_warnings = load_planets(planets_path)
        warnings.extend(planet_warnings)
    else:
        warnings.append("planets.yaml not found; catalog has no planet-layer bodies")

    raw_bodies: list[dict[str, Any]] = [
        b for b in (input_data.get("bodies") or []) if isinstance(b, dict)
    ]
    warnings.extend(check_body_field_consistency(raw_bodies, planets))

    catalog: dict[str, Any] = {
        "stars": _catalog_stars(input_data, index, computed_stars),
        # Raw orbital elements pass through verbatim so consumers (3D viewer
        # position solving) need no other input; per-body derived periods are
        # in each body's ``orbit`` block.
        "orbits": [o for o in (input_data.get("orbits") or []) if isinstance(o, dict)],
        "bodies": _catalog_bodies(input_data, raw_bodies, planets, index, computed_stars),
    }
    if planets:
        # The target body is the focus planet of this world (frontend 3D viewer
        # highlights it). Its per-body entry in ``bodies`` already carries all
        # derived physics; no role-flattened ``target_parameters`` duplicate.
        catalog["target_body_id"] = planets[0].id
    if warnings:
        catalog["warnings"] = warnings
    return catalog, warnings


def _catalog_stars(
    input_data: dict[str, Any],
    index: _StellarIndex,
    computed_stars: Mapping[str, Mapping[str, float]] | None,
) -> list[dict[str, Any]]:
    """Star entries: authored identity + resolved/computed physics + HZ."""
    stars_out: list[dict[str, Any]] = []
    for star in input_data.get("stars") or []:
        if not isinstance(star, dict) or star.get("id") is None:
            continue
        star_id = str(star["id"])
        cs = (computed_stars or {}).get(star_id, {})

        entry: dict[str, Any] = {"id": star_id}
        if star.get("name") is not None:
            entry["name"] = star["name"]
        if star.get("spectral_class") is not None:
            entry["spectral_class"] = str(star["spectral_class"])
        if star.get("luminosity_class") is not None:
            entry["luminosity_class"] = str(star["luminosity_class"])
        if star.get("position") is not None:
            entry["position"] = star["position"]

        luminosity = cs.get("luminosity")
        if luminosity is None:
            luminosity = index.luminosities.get(star_id)
        mass = cs.get("mass")
        if mass is None:
            mass = index.masses.get(star_id)
        temperature = cs.get("temperature")
        if temperature is None:
            temperature = index.temperatures.get(star_id)
        radius = cs.get("radius")
        if radius is None:
            radius = index.radii.get(star_id)
        age = cs.get("age_gyr")
        if age is None:
            age = index.ages.get(star_id)
        lifetime = cs.get("ms_lifetime_gyr")
        if lifetime is None:
            lifetime = index.ms_lifetimes.get(star_id)
        if lifetime is None and mass is not None and mass > 0:
            lifetime = main_sequence_lifetime(mass)
        progress = cs.get("evolution_progress")
        if progress is None:
            progress = index.evolution_progresses.get(star_id)
        if progress is None and lifetime and age is not None and lifetime > 0:
            progress = min(age / lifetime, 1.0)

        if luminosity is not None:
            entry["luminosity_sol"] = round(luminosity, 6)
        if mass is not None:
            entry["mass_sol"] = round(mass, 6)
        if radius is not None:
            entry["radius_sol"] = round(radius, 6)
        if temperature is not None:
            entry["temperature_k"] = round(temperature, 1)
        if age is not None:
            entry["age_gyr"] = round(age, 3)
        if lifetime is not None:
            entry["ms_lifetime_gyr"] = round(lifetime, 4)
        if progress is not None:
            entry["evolution_progress"] = round(progress, 4)
        if luminosity is not None and temperature is not None:
            entry["habitable_zone"] = habitable_zone_boundaries(luminosity, temperature)
            entry["habitable_zone_center_au"] = habitable_zone_center(luminosity, temperature)
        stars_out.append(entry)
    return stars_out


def _catalog_bodies(
    input_data: dict[str, Any],
    raw_bodies: list[dict[str, Any]],
    planets: Sequence[Planet],
    index: _StellarIndex,
    computed_stars: Mapping[str, Mapping[str, float]] | None,
) -> list[dict[str, Any]]:
    """One merged entry per body (union of stellar bodies and planets.yaml)."""
    bodies_by_id: dict[str, dict[str, Any]] = {}
    for body in raw_bodies:
        if body.get("id") is not None:
            bodies_by_id[str(body["id"])] = body
    planets_by_id = {p.id: p for p in planets}

    all_ids = list(bodies_by_id)
    all_ids.extend(pid for pid in planets_by_id if pid not in bodies_by_id)

    star_masses: dict[str, float] = dict(index.masses)
    for star_id, cs in (computed_stars or {}).items():
        if cs.get("mass") is not None:
            star_masses[star_id] = cs["mass"]

    entries: list[dict[str, Any]] = []
    for body_id in all_ids:
        entries.append(
            _catalog_body_entry(
                body_id,
                bodies_by_id.get(body_id),
                planets_by_id.get(body_id),
                index,
                star_masses,
            )
        )
    return entries


def _catalog_body_entry(
    body_id: str,
    raw: dict[str, Any] | None,
    planet: Planet | None,
    index: _StellarIndex,
    star_masses: dict[str, float],
) -> dict[str, Any]:
    """Merge one body's authored data and attach derived orbital quantities."""
    raw = raw or {}
    entry: dict[str, Any] = {"id": body_id}

    name = raw.get("name")
    if name is None and planet is not None:
        name = planet.name
    if name is not None:
        entry["name"] = name
    body_type = raw.get("body_type")
    if body_type is None and planet is not None:
        body_type = str(planet.planet_type)
    if body_type is not None:
        entry["body_type"] = str(body_type)
    entry["in_planets_yaml"] = planet is not None

    # ---- Orbit (elements from stellar.yaml; period via Kepler) ----
    orbit_raw = index.orbits.get(body_id)
    parent_id: str | None = None
    if orbit_raw is not None and orbit_raw.get("parent_id") is not None:
        parent_id = str(orbit_raw["parent_id"])
        entry["parent_id"] = parent_id

    orbit: dict[str, Any] = {}
    a_au = _as_float(orbit_raw.get("semi_major_axis_au")) if orbit_raw else None
    ecc = _as_float(orbit_raw.get("eccentricity")) if orbit_raw else None
    inc = _as_float(orbit_raw.get("inclination_deg")) if orbit_raw else None
    if a_au is not None:
        orbit["semi_major_axis_au"] = round(a_au, 6)
    if ecc is not None:
        orbit["eccentricity"] = round(ecc, 6)
    if inc is not None:
        orbit["inclination_deg"] = round(inc, 2)

    parent_mass_sol: float | None = None
    if parent_id is not None:
        if parent_id in star_masses:
            parent_mass_sol = star_masses[parent_id]
        elif parent_id in index.body_masses:
            parent_mass_sol = index.body_masses[parent_id] * EARTH_MASS_SOL
    orbital_period: float | None = None
    if a_au is not None and parent_mass_sol is not None and parent_mass_sol > 0:
        orbital_period = kepler_orbital_period(a_au, parent_mass_sol)
        orbit["period_days"] = round(orbital_period, 4)
    if orbit:
        entry["orbit"] = orbit

    # ---- Physical parameters (planets.yaml authoritative; bodies fallback) ----
    mass_earth = float(planet.mass) if planet is not None else _as_float(raw.get("mass_earth"))
    radius_km = (
        float(planet.radius) * 6371.0 if planet is not None else _as_float(raw.get("radius_km"))
    )
    rotation = (
        float(planet.rotation_period_days)
        if planet is not None
        else _as_float(raw.get("rotation_period_days"))
    )
    tilt = (
        float(planet.axial_tilt_deg) if planet is not None else _as_float(raw.get("axial_tilt_deg"))
    )
    albedo = float(planet.albedo) if planet is not None else _as_float(raw.get("albedo"))

    physical: dict[str, Any] = {}
    if mass_earth is not None:
        # 有效数字（.6g），保留极小质量（如 1.8e-9 M⊕）不被四舍五入为 0
        physical["mass_earth"] = float(f"{mass_earth:.6g}")
    if radius_km is not None:
        physical["radius_km"] = round(radius_km, 1)
        physical["radius_earth"] = round(radius_km / 6371.0, 4)
    if mass_earth is not None and radius_km is not None and radius_km > 0:
        radius_earth = radius_km / 6371.0
        physical["gravity_m_s2"] = round(_G_EARTH_M_S2 * mass_earth / radius_earth**2, 3)
    if rotation is not None:
        physical["rotation_period_days"] = round(rotation, 4)
    if tilt is not None:
        physical["axial_tilt_deg"] = round(tilt, 2)
    if albedo is not None:
        physical["albedo"] = round(albedo, 4)
    if physical:
        entry["physical"] = physical

    # ---- Layered subsystems and narrative (only where authored) ----
    if planet is not None:
        if planet.atmosphere is not None:
            entry["atmosphere"] = planet.atmosphere.model_dump(exclude_none=True)
        if planet.hydrosphere is not None:
            entry["hydrosphere"] = planet.hydrosphere.model_dump(exclude_none=True)
        if planet.lithosphere is not None:
            entry["lithosphere"] = planet.lithosphere.model_dump(exclude_none=True)
        if planet.magnetic_field_strength is not None:
            entry["magnetic_field_strength_ut"] = planet.magnetic_field_strength
    if raw.get("description") is not None:
        entry["description"] = raw["description"]

    # ---- Derived: lock state, instellation, solar day, HZ membership ----
    derived: dict[str, Any] = {}
    if rotation is not None and orbital_period is not None and orbital_period > 0:
        derived["tidally_locked"] = abs(rotation - orbital_period) <= 0.02 * orbital_period

    helio_distance = _heliocentric_distance_au(body_id, index)
    star_id = _walk_to_star(body_id, index)
    luminosity: float | None = None
    if star_id is not None:
        luminosity = index.luminosities.get(star_id)
    if helio_distance is not None and luminosity is not None:
        derived["instellation_w_m2"] = round(instellation(luminosity, helio_distance), 2)
        derived["instellation_earth_ratio"] = round(
            instellation_earth_units(luminosity, helio_distance), 4
        )
        if albedo is not None:
            derived["equilibrium_temperature_k"] = round(
                equilibrium_temperature(luminosity, helio_distance, albedo), 1
            )
    star_mass = star_masses.get(star_id) if star_id is not None else None
    year: float | None = None
    if helio_distance is not None and star_mass is not None and star_mass > 0:
        year = kepler_orbital_period(helio_distance, star_mass)
    if rotation is not None and year is not None:
        solar_day = solar_day_days(rotation, year)
        derived["solar_day_days"] = round(solar_day, 4) if solar_day is not None else None
        if solar_day is not None:
            derived["days_per_year"] = round(year / solar_day, 2)
    # Calendar facts (season length / polar circle): the "year" is the
    # heliocentric period, so a tidally-locked satellite's seasons follow its
    # parent planet's orbit. These make system_catalog the complete single
    # source for entity-addressed facts (guard/facts.py).
    if year is not None:
        derived["season_length_days"] = round(year / 4.0, 2)  # mean, circular orbit
        if tilt is not None:
            derived["polar_circle_latitude_deg"] = round(polar_circle_latitude_deg(tilt), 2)
            if tilt > 0:
                derived["polar_day_at_pole_days"] = round(year / 2.0, 2)
    temperature = index.temperatures.get(star_id) if star_id is not None else None
    if luminosity is not None and temperature is not None and helio_distance is not None:
        hz = habitable_zone_boundaries(luminosity, temperature)
        derived["in_conservative_habitable_zone"] = bool(
            hz["runaway_greenhouse_au"] <= helio_distance <= hz["max_greenhouse_au"]
        )
    if derived:
        entry["derived"] = derived
    return entry


def resolve_tidal_heating(
    engine: BaseEngine,
    config: TerrainPipelineConfig,
    planet_id: str | None = None,
) -> list[str]:
    """Derive plate speed from tidal heating for a satellite (optional coupling).

    When ``config.tidal_plate_speed_enabled`` and *planet_id* resolves to a
    satellite whose orbit (eccentricity, semi-major axis) and parent mass are
    available in ``stellar.yaml``, compute the Peale & Cassen tidal heat flux
    and overwrite ``plate_speed_range_cm_yr`` and ``ocean_spreading_rate_cm_yr``
    via the empirical power law ``v ∝ q^β`` (see ``map/tidal_physics.py`` and
    ``docs/knowledge/geology/tidal_plate_speed.md``).

    The fastest-plate speed is rounded to 0.5 cm/yr — the meaningful granularity
    given the ±50% empirical uncertainty of the scaling — which keeps nacrea's
    authored 15 cm/yr unchanged (the raw computed value is ~14.9 cm/yr).

    Args:
        engine: Engine whose ``find_input`` resolves ``stellar.yaml``.
        config: Configuration to update in place.
        planet_id: Target body id; resolved from ``planets.yaml`` when omitted.

    Returns:
        Warnings suitable for ``EngineResult.warnings``.
    """
    warnings: list[str] = []
    if not config.tidal_plate_speed_enabled:
        return warnings

    if planet_id is None:
        planet, planet_warnings = load_planet_for_engine(engine, None)
        warnings.extend(planet_warnings)
        if planet is None:
            warnings.append(
                "tidal_plate_speed enabled but no planet resolved; keeping authored plate speed"
            )
            return warnings
        planet_id = planet.id

    input_data = _read_mapping(engine, "stellar.yaml")
    if input_data is None:
        warnings.append(
            "tidal_plate_speed enabled but stellar.yaml not found; keeping authored plate speed"
        )
        return warnings

    # Index body masses (id -> M⊕) from the ``bodies`` section.
    body_mass_earth: dict[str, float] = {}
    for body in input_data.get("bodies") or []:
        if not isinstance(body, dict):
            continue
        bid = body.get("id")
        mass = body.get("mass_earth")
        if bid is not None and mass is not None:
            with suppress(TypeError, ValueError):
                body_mass_earth[str(bid)] = float(mass)

    orbit: dict[str, Any] | None = None
    for entry in input_data.get("orbits") or []:
        if isinstance(entry, dict) and str(entry.get("body_id")) == planet_id:
            orbit = entry
            break
    if orbit is None:
        warnings.append(f"no orbit entry for '{planet_id}'; keeping authored plate speed")
        return warnings

    parent_id = orbit.get("parent_id")
    eccentricity = orbit.get("eccentricity")
    semi_major_axis_au = orbit.get("semi_major_axis_au")
    parent_mass_earth = body_mass_earth.get(str(parent_id)) if parent_id is not None else None
    if eccentricity is None or semi_major_axis_au is None or parent_mass_earth is None:
        warnings.append(
            f"incomplete orbit/body data for '{planet_id}'; keeping authored plate speed"
        )
        return warnings

    from dreamulator.engine.tidal_physics import (
        AU_M,
        EARTH_MASS_KG,
        mean_motion_rad_s,
        plate_speed_cm_yr,
        tidal_heat_flux_w_m2,
        tidal_heating_power_w,
    )

    radius_m = config.radius_km * 1000.0
    a_m = float(semi_major_axis_au) * AU_M
    mp_kg = float(parent_mass_earth) * EARTH_MASS_KG
    n = mean_motion_rad_s(mp_kg, a_m)

    heating_w = tidal_heating_power_w(
        mass_primary_kg=mp_kg,
        radius_m=radius_m,
        semi_major_axis_m=a_m,
        eccentricity=float(eccentricity),
        mean_motion_rad_s=n,
        k2_over_q=config.tidal_k2_over_q,
    )
    flux = tidal_heat_flux_w_m2(heating_w, radius_m)
    v_max = plate_speed_cm_yr(
        flux,
        v_ref_cm_yr=config.tidal_plate_speed_v_ref_cm_yr,
        q_ref_w_m2=config.tidal_plate_speed_q_ref_w_m2,
        beta=config.tidal_plate_speed_beta,
    )
    v_max = round(v_max * 2.0) / 2.0  # round to 0.5 cm/yr
    v_min = config.plate_speed_range_cm_yr[0]
    config.plate_speed_range_cm_yr = (v_min, v_max)
    config.ocean_spreading_rate_cm_yr = round(config.tidal_spreading_ratio * v_max * 2.0) / 2.0

    warnings.append(
        f"tidal heating {heating_w:.3e} W ({flux:.3f} W/m2) -> plate speed max "
        f"{v_max:.1f} cm/yr, half-spreading {config.ocean_spreading_rate_cm_yr:.1f} cm/yr"
    )
    return warnings
