"""Planet models — planets, atmospheres, hydrospheres, lithospheres."""

from enum import Enum

from pydantic import BaseModel, Field, model_validator

from .common import Day, EarthMass, EarthRadius


class PlanetType(str, Enum):
    """Classification of planet types."""

    TERRESTRIAL = "terrestrial"
    GAS_GIANT = "gas_giant"
    ICE_GIANT = "ice_giant"
    OCEAN_WORLD = "ocean_world"
    DWARF = "dwarf"


class Atmosphere(BaseModel):
    """Planetary atmosphere properties."""

    surface_pressure_atm: float = Field(
        default=1.0, gt=0, description="Surface pressure in atmospheres"
    )
    composition: dict[str, float] = Field(
        default_factory=lambda: {"N2": 0.78, "O2": 0.21, "Ar": 0.01},
        description="Mole fractions of atmospheric gases",
    )
    scale_height_km: float | None = Field(
        default=None, gt=0, description="Atmospheric scale height in km (computed if omitted)"
    )
    greenhouse_factor: float = Field(
        default=0.0, ge=0, description="Additional greenhouse warming in Kelvin"
    )

    @model_validator(mode="after")
    def _check_composition_sums(self) -> "Atmosphere":
        total = sum(self.composition.values())
        if total > 0 and abs(total - 1.0) > 0.05:
            raise ValueError(
                f"Atmospheric composition mole fractions should sum to ~1.0, got {total:.3f}"
            )
        return self


class Hydrosphere(BaseModel):
    """Planetary hydrosphere properties."""

    water_coverage: float = Field(
        default=0.71, ge=0, le=1, description="Fraction of surface covered by water"
    )
    salinity_ppt: float = Field(
        default=35.0, ge=0, description="Average ocean salinity in parts per thousand"
    )
    ocean_depth_km: float = Field(default=3.7, gt=0, description="Average ocean depth in km")


class Lithosphere(BaseModel):
    """Planetary lithosphere / geological properties."""

    has_plate_tectonics: bool = True
    num_plates: int = Field(default=15, ge=1, le=50, description="Number of tectonic plates")
    crust_composition: dict[str, float] | None = Field(
        default=None, description="Crust composition as mass fractions"
    )
    volcanic_activity: float = Field(
        default=1.0, ge=0, description="Volcanic activity relative to Earth (1.0 = Earth-like)"
    )


class Planet(BaseModel):
    """A planet in the stellar system."""

    id: str = Field(description="Unique identifier, e.g. 'planet_terra'")
    name: str
    orbits: str = Field(description="ID of star or body this planet orbits")
    planet_type: PlanetType = PlanetType.TERRESTRIAL
    mass: EarthMass
    radius: EarthRadius

    rotation_period_days: Day = Field(default=1.0, description="Sidereal rotation period")
    axial_tilt_deg: float = Field(default=23.4, ge=0, le=90, description="Axial obliquity")
    albedo: float = Field(default=0.3, ge=0, le=1, description="Bond albedo")

    atmosphere: Atmosphere | None = None
    hydrosphere: Hydrosphere | None = None
    lithosphere: Lithosphere | None = None

    magnetic_field_strength: float | None = Field(
        default=None, ge=0, description="Surface magnetic field strength in microtesla"
    )

    satellite_ids: list[str] = Field(
        default_factory=list,
        description="IDs of natural satellites (defined in astronomy layer's stellar.yaml)",
    )
