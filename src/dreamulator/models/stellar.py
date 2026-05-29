"""Stellar and orbital models — stars, spectral types, orbital elements."""

from enum import Enum

from pydantic import BaseModel, Field, model_validator

from .common import AU, Kelvin, SolarLuminosity, SolarMass, SolarRadius, Vec3


class SpectralClass(str, Enum):
    """Morgan–Keenan spectral classification."""

    O = "O"
    B = "B"
    A = "A"
    F = "F"
    G = "G"
    K = "K"
    M = "M"


class LuminosityClass(str, Enum):
    """Morgan–Keenan luminosity class."""

    Ia = "Ia"  # Bright supergiant
    Ib = "Ib"  # Supergiant
    II = "II"  # Bright giant
    III = "III"  # Giant
    IV = "IV"  # Subgiant
    V = "V"  # Main sequence


class Star(BaseModel):
    """A star in a stellar system."""

    id: str = Field(description="Unique identifier within the system, e.g. 'star_sol'")
    name: str = Field(description="Display name of the star")
    spectral_class: SpectralClass
    luminosity_class: LuminosityClass = LuminosityClass.V
    mass: SolarMass

    # Optional authored fields — engines compute these if not provided
    luminosity: SolarLuminosity | None = Field(
        default=None, description="Bolometric luminosity in L_sun (computed if omitted)"
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


class StellarSystem(BaseModel):
    """A system of one or more stars and their orbiting bodies."""

    name: str = Field(description="Name of the stellar system")
    stars: list[Star] = Field(min_length=1, description="Stars in the system")
    orbits: list[OrbitalElements] = Field(
        default_factory=list, description="Orbital elements for planets and other bodies"
    )

    @model_validator(mode="after")
    def _check_unique_star_ids(self) -> "StellarSystem":
        ids = [s.id for s in self.stars]
        if len(ids) != len(set(ids)):
            raise ValueError("Star IDs must be unique within a system")
        return self
