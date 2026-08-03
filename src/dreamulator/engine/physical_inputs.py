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
the habitable moon gaia-m, which orbits the gas giant Aegis) is walked up
the ``orbits`` table in ``stellar.yaml`` until the host star is found.

For the received stellar flux we use the **host planet's heliocentric
distance**, ignoring the satellite's own orbit around the planet.  With
``eps = a_moon / a_planet``, the time-averaged insolation correction is
``1/(1 - eps**2) - 1 ~ eps**2`` and the instantaneous extremes are
``~ +/-2*eps`` (both from averaging ``1/d^2`` over the moon's orbit).
For gaia-m (eps = 0.00494/0.2795 = 0.0177) the mean error is +0.03% and the
78-hour oscillation is +/-3.5% — far below climate-model and
geomorphic-erosion resolution, and smaller than the host planet's own
eccentricity modulation.  Moon orbits are Hill-sphere bounded (stable orbits
< ~0.4 R_H), so eps stays < ~0.05 and the mean approximation keeps < 0.25%
error for every physically plausible moon.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import yaml  # type: ignore[import-untyped]

if TYPE_CHECKING:
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


def _index_stellar_data(engine: BaseEngine) -> _StellarIndex:
    """Index star luminosities and orbit entries from the astronomy layer.

    ``stellar_derived.yaml`` (engine-computed) overrides ``stellar.yaml``
    (authored) for luminosities; orbit elements come from ``stellar.yaml``.
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
            luminosity = star.get("computed_luminosity")
            if luminosity is None:
                luminosity = star.get("luminosity")
            if luminosity is not None:
                try:
                    index.luminosities[star_id] = float(luminosity)
                except (TypeError, ValueError):
                    logger.warning("Non-numeric luminosity for star %s", star_id)
            mass = star.get("computed_mass")
            if mass is None:
                mass = star.get("mass")
            if mass is not None:
                try:
                    index.masses[star_id] = float(mass)
                except (TypeError, ValueError):
                    logger.warning("Non-numeric mass for star %s", star_id)

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


def apply_physical_parameters(
    config: TerrainPipelineConfig,
    planet: Planet | None,
    stellar_luminosity_sol: float | None = None,
    orbital_distance_au: float | None = None,
    orbital_period_days: float | None = None,
) -> None:
    """Write resolved physical parameters onto *config* in place.

    None values leave the corresponding config field untouched.
    """
    if stellar_luminosity_sol is not None:
        config.stellar_luminosity_sol = stellar_luminosity_sol
    if orbital_distance_au is not None:
        config.orbital_distance_au = orbital_distance_au
    if orbital_period_days is not None:
        config.orbital_period_days = orbital_period_days
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

    apply_physical_parameters(config, planet, luminosity, distance, period)
    return warnings
