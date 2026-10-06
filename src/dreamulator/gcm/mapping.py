"""World-input → ExoPlaSim ``Model.configure`` parameter mapping (pure functions).

Why this module exists
----------------------
The 2026-09-07 "dead wind field" mystery was caused by a unit mismatch:
ExoPlaSim's ``configure(radius=...)`` expects **Earth radii**, not metres
(``exoplasim/__init__.py`` writes ``PLARAD = radius*6371220.0``).  Passing
metres creates a planet 6.4e6 times too large, which suppresses thermal-wind
and baroclinic growth by the same factor (``ua`` ~ 1e-5 m/s, ``zeta`` ~ 1e-18)
while column physics (temperature) stays normal.  Centralising every unit
conversion here, with regression tests, is the structural fix.

ExoPlaSim unit conventions (verified against 3.4.2 source, 2026-10-05):

======================  =============================  =====================
``configure`` keyword   meaning                       source in world data
======================  =============================  =====================
``radius``              Earth radii (**not metres**)  ``planets.radius`` (R⊕)
``gravity``             m/s²                          derived from mass+radius
``rotationperiod``      days                          ``rotation_period_days``
``obliquity``           degrees                       ``axial_tilt_deg``
``eccentricity``        –                             host orbit (epoch value)
``flux``                W/m² at semi-major axis       star luminosity / a²
``year``                number of **24-hour days**    Kepler from a, M_star
``pressure``            bar                           ``surface_pressure_atm``
``pN2``/``pO2``/…       bar (partial pressures)       atmosphere composition
``startemp``            stellar effective temp (K)    star entry (if present)
======================  =============================  =====================

Greenhouse handling: dreamulator's ``greenhouse_factor`` (e.g. Nacrea's 62 K)
has no direct ExoPlaSim equivalent — its radiative identity (prescribed
boundary vs. composition-driven) is a pending author decision (设定待裁决).
This mapping therefore never invents one: with ``greenhouse_mode="none"``
(default) nothing is compensated and a warning is recorded in the manifest;
``"flux_boost"`` applies an explicit, user-supplied factor (the historical PoC
hack — discouraged); ``"pco2"`` passes an explicit CO₂ partial pressure.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

import yaml

# --- ExoPlaSim reference constants (match exoplasim/__init__.py exactly) -----
R_EARTH_EXOPLASIM_M = 6_371_220.0  # metres per "Earth radius" in PLARAD
G_EARTH_MS2 = 9.80665  # standard surface gravity for the ratio formula
SOLAR_CONSTANT_WM2 = 1361.0  # dreamulator flux convention (PoC-era, kept)
DAYS_PER_YEAR = 365.25  # sidereal-year unit behind Kepler's third law
ATM_TO_BAR = 1.01325

_PLANET_FILE = "layers/geological/input/planets.yaml"
_STELLAR_FILE = "layers/astronomy/input/stellar.yaml"


class MappingError(ValueError):
    """World input cannot be mapped to ExoPlaSim parameters."""


@dataclass(frozen=True)
class ExoPlaSimParams:
    """ExoPlaSim ``Model.configure`` keyword arguments.

    All quantities already carry ExoPlaSim's (sometimes unusual) units; see
    the module docstring table.  ``extras`` holds additional kwargs (e.g.
    ``aquaplanet=True``, ``landmap=...``) that are policy rather than physics.
    """

    radius: float  # R⊕ (Earth radii — NOT metres)
    gravity: float  # m/s²
    rotationperiod: float  # days
    obliquity: float  # degrees
    eccentricity: float  # dimensionless
    flux: float  # W/m² at orbital semi-major axis
    year: float  # sidereal year in 24-hour days
    pressure: float  # bar
    startemp: float | None = None  # stellar effective temperature, K
    pn2: float | None = None  # bar
    po2: float | None = None
    par: float | None = None
    pco2: float | None = None
    extras: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    def to_configure_kwargs(self) -> dict[str, Any]:
        """Return the plain ``configure(**kwargs)`` mapping."""
        kwargs: dict[str, Any] = {
            "radius": self.radius,
            "gravity": self.gravity,
            "rotationperiod": self.rotationperiod,
            "obliquity": self.obliquity,
            "eccentricity": self.eccentricity,
            "flux": self.flux,
            "year": self.year,
            "pressure": self.pressure,
            **self.extras,
        }
        if self.startemp is not None:
            kwargs["startemp"] = self.startemp
        for key, value in (
            ("pN2", self.pn2),
            ("pO2", self.po2),
            ("pAr", self.par),
            ("pCO2", self.pco2),
        ):
            if value is not None:
                kwargs[key] = value
        return kwargs


def gravity_from_mass_radius(mass_earth: float, radius_earth: float) -> float:
    """Surface gravity in m/s² from mass/radius in Earth units.

    Uses the ratio form ``g = g_Earth · (M/M⊕) / (R/R⊕)²`` so the result
    matches the engine-side convention (Nacrea: 1.20 / 1.07² · 9.81 ≈ 10.28).
    """
    if mass_earth <= 0 or radius_earth <= 0:
        raise MappingError(f"mass/radius must be positive, got {mass_earth}/{radius_earth}")
    return G_EARTH_MS2 * mass_earth / radius_earth**2


def flux_from_star(luminosity_solar: float, semi_major_axis_au: float) -> float:
    """Incident stellar flux in W/m² at the orbital semi-major axis.

    ExoPlaSim varies insolation with eccentricity internally, so the flux is
    specified at ``a`` (not perihelion), consistent with the dreamulator
    insolation convention.
    """
    if semi_major_axis_au <= 0:
        raise MappingError(f"semi-major axis must be positive, got {semi_major_axis_au}")
    return SOLAR_CONSTANT_WM2 * luminosity_solar / semi_major_axis_au**2


def year_days_from_kepler(semi_major_axis_au: float, star_mass_solar: float) -> float:
    """Sidereal orbital period in 24-hour days via Kepler's third law.

    ExoPlaSim's ``year`` counts 24-hour days regardless of the planet's actual
    day length, so no rescaling by ``rotationperiod`` is needed here.
    """
    return DAYS_PER_YEAR * math.sqrt(semi_major_axis_au**3 / star_mass_solar)


def _find_entry(entries: list[dict[str, Any]] | None, entry_id: str) -> dict[str, Any]:
    if not entries:
        raise MappingError("input file has no entries")
    for entry in entries:
        # planets use "id"; stellar.yaml orbit entries use "body_id"
        if entry.get("id") == entry_id or entry.get("body_id") == entry_id:
            return entry
    known = [str(e.get("id") or e.get("body_id")) for e in entries]
    raise MappingError(f"entry {entry_id!r} not found; available: {', '.join(known)}")


def map_planet(
    planet: Mapping[str, Any],
    star: Mapping[str, Any],
    host_orbit: Mapping[str, Any],
    *,
    greenhouse_mode: str = "none",
    flux_boost_factor: float | None = None,
    pco2_bar: float | None = None,
    overrides: Mapping[str, float] | None = None,
    extras: Mapping[str, Any] | None = None,
) -> ExoPlaSimParams:
    """Map one planet entry (+ star + host orbit) to ExoPlaSim parameters.

    ``greenhouse_mode``:
      - ``"none"`` (default): no compensation; a warning is recorded.
      - ``"flux_boost"``: multiply stellar flux by ``flux_boost_factor``
        (explicit, discouraged — the PoC-era hack; overshoots in the tropics).
      - ``"pco2"``: pass ``pco2_bar`` as the CO₂ partial pressure
        (composition-driven; requires an author decision on the radiative
        identity of dreamulator's ``greenhouse_factor``).

    ``overrides`` replaces any computed scalar after mapping (keys use the
    :class:`ExoPlaSimParams` field names, e.g. ``{"year": 99.7}``).
    """
    warnings: list[str] = []

    radius_earth = float(planet["radius"])  # already R⊕ in world data
    if radius_earth <= 0 or radius_earth > 20:
        raise MappingError(
            f"radius {radius_earth} R⊕ out of plausible range — world data is "
            "expected in Earth radii, never metres "
            "(the 2026-09-07 dead-wind bug)"
        )
    gravity = gravity_from_mass_radius(float(planet["mass"]), radius_earth)

    luminosity = float(star["luminosity"])
    a_au = float(host_orbit["semi_major_axis_au"])
    flux = flux_from_star(luminosity, a_au)
    if greenhouse_mode == "flux_boost":
        if flux_boost_factor is None or flux_boost_factor <= 0:
            raise MappingError("flux_boost mode requires a positive flux_boost_factor")
        flux *= flux_boost_factor
        warnings.append(
            f"greenhouse_mode=flux_boost ×{flux_boost_factor}: PoC-era hack, "
            "prefer pco2 after the radiative-identity adjudication"
        )
    elif greenhouse_mode == "pco2":
        if pco2_bar is None or pco2_bar < 0:
            raise MappingError("pco2 mode requires a non-negative pco2_bar")
    elif greenhouse_mode != "none":
        raise MappingError(f"unknown greenhouse_mode {greenhouse_mode!r}")
    if greenhouse_mode == "none" and "greenhouse_factor" in planet.get("atmosphere", {}):
        warnings.append(
            f"greenhouse_factor {planet['atmosphere']['greenhouse_factor']} K not "
            "compensated (radiative identity pending author decision)"
        )

    year = year_days_from_kepler(a_au, float(star["mass"]))

    atmosphere = dict(planet.get("atmosphere", {}))
    # surface_pressure_atm is the *background* (non-CO2) atmosphere; an explicit
    # pCO2 sits ON TOP of it, so the total passed to ExoPlaSim must include it
    # (partial pressures must sum to the total — the 2026-10-06 scan bug).
    pressure_bar = float(atmosphere.get("surface_pressure_atm", 1.0)) * ATM_TO_BAR
    if greenhouse_mode == "pco2" and pco2_bar:
        pressure_bar += pco2_bar  # total = background + CO2 (composition closure)
    composition = dict(atmosphere.get("composition", {}))
    # Partial pressures in bar; keys follow exoplasim spelling (pN2/pO2/pAr).
    pn2 = pressure_bar * float(composition["N2"]) if "N2" in composition else None
    po2 = pressure_bar * float(composition["O2"]) if "O2" in composition else None
    par = pressure_bar * float(composition["Ar"]) if "Ar" in composition else None
    if greenhouse_mode == "pco2":
        pco2 = pco2_bar
    else:
        pco2 = pressure_bar * float(composition["CO2"]) if "CO2" in composition else None
    if greenhouse_mode == "none" and "CO2" not in composition:
        warnings.append(
            "atmosphere composition carries no CO2: the GCM arm has no carbon "
            "greenhouse and will collapse to a snowball unless pCO2/flux is "
            "supplied explicitly (earth ≈ 2.8e-4 bar; nacrea pending the "
            "radiative-identity adjudication)"
        )

    star_temp = (
        star.get("effective_temperature_k")
        or star.get("teff_k")
        or star.get("temperature")  # common alternative key (earth stellar.yaml)
    )
    params = ExoPlaSimParams(
        radius=radius_earth,
        gravity=gravity,
        rotationperiod=float(planet["rotation_period_days"]),
        obliquity=float(planet["axial_tilt_deg"]),
        eccentricity=float(host_orbit["eccentricity"]),
        flux=flux,
        year=year,
        pressure=pressure_bar,
        startemp=float(star_temp) if star_temp is not None else None,
        pn2=pn2,
        po2=po2,
        par=par,
        pco2=pco2,
        extras=dict(extras or {}),
        warnings=tuple(warnings),
    )
    if overrides:
        frozen = {f: getattr(params, f) for f in params.__dataclass_fields__}
        for key, value in overrides.items():
            if key not in frozen:
                raise MappingError(f"unknown override field {key!r}")
            object.__setattr__(params, key, float(value))  # noqa: PLW0642
    return params


def map_world(
    world_dir: str | Path,
    planet_id: str,
    *,
    host_body_id: str | None = None,
    **kwargs: Any,
) -> ExoPlaSimParams:
    """Load a world's input YAMLs and map ``planet_id`` to ExoPlaSim parameters.

    ``host_body_id`` names the body whose orbit around the star defines the
    insolation (for satellites: the host planet; defaults to ``planet_id``).
    """
    world = Path(world_dir)
    with (world / _PLANET_FILE).open(encoding="utf-8") as f:
        planets_doc = yaml.safe_load(f) or {}
    with (world / _STELLAR_FILE).open(encoding="utf-8") as f:
        stellar_doc = yaml.safe_load(f) or {}

    planet = _find_entry(planets_doc.get("planets"), planet_id)
    stars = stellar_doc.get("stars") or []
    if len(stars) != 1:
        # Multi-star systems are out of scope for the GCM oracle for now.
        raise MappingError(
            f"expected exactly one star, found {len(stars)}: {[s.get('id') for s in stars]}"
        )
    star = stars[0]
    star_ids = {s.get("id") for s in stars}
    orbit_ref = host_body_id or planet.get("orbits") or planet_id
    if orbit_ref in star_ids:
        # A planet orbiting the star: insolation is set by its OWN orbit entry
        # (earth's planets.yaml says ``orbits: star_sol``, which is not a member
        # of the orbits list).
        host_orbit = _find_entry(stellar_doc.get("orbits"), planet_id)
    else:
        # A satellite: insolation is set by the host planet's orbit.
        host_orbit = _find_entry(stellar_doc.get("orbits"), orbit_ref)
    return map_planet(planet, star, host_orbit, **kwargs)
