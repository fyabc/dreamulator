"""Common types and semantic unit aliases used across all models."""

from typing import Annotated

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Semantic unit aliases — these are plain floats at runtime, but the type
# alias documents the expected physical unit and enables static checking.
# ---------------------------------------------------------------------------
SolarMass = Annotated[float, Field(gt=0, description="Mass in solar masses (M_sun)")]
SolarLuminosity = Annotated[
    float, Field(gt=0, description="Luminosity in solar luminosities (L_sun)")
]
SolarRadius = Annotated[float, Field(gt=0, description="Radius in solar radii (R_sun)")]
Kelvin = Annotated[float, Field(gt=0, description="Temperature in Kelvin")]
AU = Annotated[float, Field(gt=0, description="Distance in astronomical units")]
EarthRadius = Annotated[float, Field(gt=0, description="Radius in Earth radii")]
EarthMass = Annotated[float, Field(gt=0, description="Mass in Earth masses")]
Year = Annotated[float, Field(gt=0, description="Time in Earth years")]
Day = Annotated[float, Field(gt=0, description="Time in Earth days")]
Kilometer = Annotated[float, Field(description="Distance in kilometers")]


class Vec3(BaseModel):
    """3D vector in Cartesian coordinates."""

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
