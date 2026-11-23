"""Stellar and orbital models — stars, spectral types, orbital elements."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, FiniteFloat, field_validator, model_validator

from .common import AU, Day, EarthMass, Kelvin, SolarLuminosity, SolarMass, SolarRadius, Vec3

# Morgan–Keenan spectral type: letter (O B A F G K M) + optional numeric subtype (0–9)
_SPECTRAL_TYPE_RE = re.compile(r"^[OBAFGKM]\d?$")


class LuminosityClass(StrEnum):
    """Morgan–Keenan luminosity class."""

    Ia = "Ia"  # Bright supergiant
    Ib = "Ib"  # Supergiant
    II = "II"  # Bright giant
    III = "III"  # Giant
    IV = "IV"  # Subgiant
    V = "V"  # Main sequence


class Star(BaseModel):
    """A star in a stellar system.

    Supports hybrid input mode: provide either mass, luminosity, or both.
    - mass only: engine computes luminosity, radius, temperature.
    - luminosity only: engine inverts mass-luminosity relation to derive mass,
      then computes radius and temperature.
    - both: mass takes priority; luminosity is used as override with consistency
      warning if deviation > 20%.
    """

    id: str = Field(description="Unique identifier within the system, e.g. 'star_sol'")
    name: str = Field(description="Display name of the star")
    spectral_class: str = Field(
        description="Morgan–Keenan spectral type, e.g. 'G2', 'M1', or coarse 'G', 'M'"
    )
    luminosity_class: LuminosityClass = LuminosityClass.V

    @field_validator("spectral_class", mode="before")
    @classmethod
    def _validate_spectral_class(cls, v: object) -> str:
        if not isinstance(v, str) or not _SPECTRAL_TYPE_RE.match(v):
            raise ValueError(
                f"spectral_class must match pattern [OBAFGKM] with optional digit 0–9, got {v!r}"
            )
        return v

    mass: SolarMass | None = Field(
        default=None,
        description="Stellar mass in M_sun. Required unless luminosity is provided.",
    )

    # Optional authored fields — engines compute these if not provided
    luminosity: SolarLuminosity | None = Field(
        default=None,
        description="Bolometric luminosity in L_sun. "
        "Can be used as alternative input (instead of mass).",
    )
    temperature: Kelvin | None = Field(
        default=None, description="Effective surface temperature in K (computed if omitted)"
    )
    radius: SolarRadius | None = Field(
        default=None, description="Stellar radius in R_sun (computed if omitted)"
    )

    metallicity: float = Field(default=0.0, description="Metallicity [Fe/H] in dex")
    age_gyr: float = Field(default=4.6, gt=0, description="Age in gigayears")
    position: Vec3 = Field(
        default_factory=Vec3, description="Position in system barycentric frame (AU)"
    )

    @model_validator(mode="after")
    def _check_mass_or_luminosity(self) -> Star:
        if self.mass is None and self.luminosity is None:
            raise ValueError(
                "Star requires at least one of: mass, luminosity. "
                "Provide mass for forward computation, or luminosity to invert."
            )
        return self


class OrbitalElements(BaseModel):
    """Keplerian orbital elements for a body orbiting another body."""

    body_id: str = Field(description="ID of the orbiting body")
    parent_id: str = Field(description="ID of the central body being orbited")
    semi_major_axis_au: AU
    eccentricity: float = Field(ge=0, lt=1, description="Orbital eccentricity (0 = circle)")
    inclination_deg: float = Field(default=0, ge=0, le=180, description="Orbital inclination")
    longitude_ascending_node_deg: float = Field(
        default=0, ge=0, le=360, description="Longitude of ascending node"
    )
    argument_of_periapsis_deg: float = Field(
        default=0, ge=0, le=360, description="Argument of periapsis"
    )
    mean_anomaly_epoch_deg: float = Field(
        default=0, ge=0, le=360, description="Mean anomaly at epoch"
    )
    epoch_year: float = Field(default=0.0, description="Epoch of orbital elements")


class OrbitingBody(BaseModel):
    """A non-star body in the stellar system: moon, asteroid, comet, etc.

    Orbital elements live in StellarSystem.orbits (matched by id == body_id).
    Physical fields shared with planets.yaml (mass, radius, rotation, tilt,
    albedo) are authoritative in planets.yaml and may be omitted here;
    ``overlay_planet_physicals`` fills them for consumers that need the body
    record on its own.
    """

    id: str = Field(description="Unique identifier, e.g. 'satellite_moon'")
    name: str = Field(description="Display name")
    body_type: str = Field(
        default="natural_satellite",
        description="Classification: natural_satellite, asteroid, comet, dwarf_planet",
    )

    # Physical properties (units chosen for non-stellar-scale objects).
    # Optional when planets.yaml carries the authoritative value.
    mass_earth: EarthMass | None = Field(
        default=None, description="Mass in Earth masses (M⊕); planets.yaml wins when present"
    )
    radius_km: float | None = Field(
        default=None, gt=0, description="Mean radius in km; planets.yaml wins when present"
    )

    rotation_period_days: Day | None = Field(
        default=None, description="Sidereal rotation period in days"
    )
    axial_tilt_deg: float | None = Field(
        default=None, ge=0, le=180, description="Axial obliquity in degrees"
    )
    spin_axis_ecliptic_longitude_deg: float | None = Field(
        default=None, ge=0, lt=360, description="Spin pole longitude in the orbital reference frame"
    )
    prime_meridian_phase_at_epoch_deg: float | None = Field(
        default=None,
        ge=0,
        lt=360,
        description="Eastward angle along the body equator from its ascending node to longitude 0 "
        "at the orbital epoch; uses the reference frame's x-axis if the obliquity is zero",
    )
    albedo: float | None = Field(default=None, ge=0, le=1, description="Geometric albedo")

    # Rotational / tidal dynamics — optional, single-sourced in stellar.yaml
    # bodies (planets.yaml stays the authority for the five shared physical
    # fields).  These unlock the satellite-dynamics derived quantities in
    # system_catalog (tidal migration, e-damping, J2 precession, Laplace
    # radius, spin precession); absent values simply omit those fields.
    j2: float | None = Field(
        default=None, ge=0, lt=1, description="Gravitational quadrupole J2 (host planets)"
    )
    k2_over_q: float | None = Field(
        default=None, gt=0, description="Tidal Love number over quality factor k₂/Q"
    )
    c_over_mr2: float | None = Field(
        default=None,
        gt=0,
        le=0.4,
        description="Principal moment of inertia coefficient C/MR² (uniform sphere 0.4)",
    )
    love_k2: float | None = Field(
        default=None,
        gt=0,
        lt=1.5,
        description="Tidal Love number k₂ (gravitational potential); default Earth's 0.3",
    )
    love_h2: float | None = Field(
        default=None,
        gt=0,
        lt=2.5,
        description="Tidal Love number h₂ (solid-surface deformation); default Earth's 0.6",
    )

    # Extensible surface properties (composition, atmosphere presence, etc.)
    surface: dict[str, Any] | None = Field(
        default=None, description="Surface properties (composition, atmosphere, etc.)"
    )

    # Extensible narrative descriptions (surface, interior, history, etc.)
    description: dict[str, str] | None = Field(
        default=None,
        description="Free-form narrative keyed by aspect (e.g. 'surface', 'interior', 'history')",
    )

    @model_validator(mode="after")
    def _check_prime_meridian_phase(self) -> OrbitingBody:
        if (
            self.prime_meridian_phase_at_epoch_deg is not None
            and self.spin_axis_ecliptic_longitude_deg is None
        ):
            raise ValueError("prime_meridian_phase_at_epoch_deg requires an explicit spin pole")
        return self


class EpochTimeScale(StrEnum):
    TT = "TT"
    TDB = "TDB"
    TCB = "TCB"


class JulianEpochDate(BaseModel):
    value: FiniteFloat = Field(description="Julian date of the reference instant")
    scale: EpochTimeScale = Field(description="Time scale used for this Julian date")


class ReferenceEpoch(BaseModel):
    label: str = Field(min_length=1, description="Short name of the catalog's reference instant")
    julian_date: JulianEpochDate | None = Field(
        default=None, description="Absolute date, if the reference instant has one"
    )

    @field_validator("label", mode="before")
    @classmethod
    def _strip_label(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


class StellarSystem(BaseModel):
    """A system of one or more stars and their orbiting bodies."""

    name: str = Field(description="Name of the stellar system")
    description: str | None = Field(
        default=None,
        description="Free-form narrative: system description, formation history, lore, etc.",
    )
    reference_epoch: ReferenceEpoch | None = Field(
        default=None, description="Reference instant at zero elapsed catalog days"
    )
    stars: list[Star] = Field(min_length=1, description="Stars in the system")
    orbits: list[OrbitalElements] = Field(
        default_factory=list, description="Orbital elements for planets and other bodies"
    )
    bodies: list[OrbitingBody] = Field(
        default_factory=list,
        description="Non-star bodies (moons, asteroids, etc.) with physical properties. "
        "Orbital elements are in the orbits list, matched by id.",
    )

    @model_validator(mode="after")
    def _check_unique_star_ids(self) -> StellarSystem:
        ids = [s.id for s in self.stars]
        if len(ids) != len(set(ids)):
            raise ValueError("Star IDs must be unique within a system")
        return self


_KM_PER_EARTH_RADIUS = 6371.0


def overlay_planet_physicals(bodies: list[dict[str, Any]], planets: list[dict[str, Any]]) -> None:
    """Fill shared body physical fields from planets.yaml (authoritative).

    ``stellar.yaml`` bodies may omit mass, radius, rotation, tilt and albedo
    when the same body is defined in ``planets.yaml``.  This helper restores
    them for consumers that work on raw body dictionaries, such as the
    stellar-system API and the static exporter.  It overwrites any legacy
    duplicate with the authoritative value.
    """
    by_id = {
        str(planet["id"]): planet
        for planet in planets
        if isinstance(planet, dict) and planet.get("id") is not None
    }
    for body in bodies:
        if not isinstance(body, dict):
            continue
        planet = by_id.get(str(body.get("id")))
        if planet is None:
            continue
        if planet.get("mass") is not None:
            body["mass_earth"] = planet["mass"]
        if planet.get("radius") is not None:
            body["radius_km"] = float(planet["radius"]) * _KM_PER_EARTH_RADIUS
        for key in ("rotation_period_days", "axial_tilt_deg", "albedo"):
            if planet.get(key) is not None:
                body[key] = planet[key]
