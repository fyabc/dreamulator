"""Pydantic data models for dreamulator world data."""

from .branch import BranchMetadata
from .civilization import Civilization, Culture, Government, Settlement
from .common import (
    AU,
    Day,
    EarthMass,
    EarthRadius,
    Kelvin,
    SolarLuminosity,
    SolarMass,
    Vec3,
    Year,
)
from .ecology import BiomeType, Ecosystem, FoodWeb, Species, TrophicLevel
from .layers import (
    LAYER_DEPENDENCIES,
    LAYER_ENGINES,
    LAYER_ORDER,
    Layer,
    LayerSummary,
    get_layer_dependencies,
    get_layer_index,
    get_layers_before,
    validate_layer_order,
)
from .planet import Atmosphere, Hydrosphere, Lithosphere, Planet, PlanetType
from .simulation import ComputationManifest, EngineInfo, SimulationRun, SimulationSeed, StepRecord
from .stellar import LuminosityClass, OrbitalElements, OrbitingBody, Star, StellarSystem
from .world import WorldConfig, WorldMetadata

__all__ = [
    # common
    "AU",
    "Day",
    "EarthMass",
    "EarthRadius",
    "Kelvin",
    "SolarLuminosity",
    "SolarMass",
    "Vec3",
    "Year",
    # stellar
    "LuminosityClass",
    "OrbitalElements",
    "OrbitingBody",
    "Star",
    "StellarSystem",
    # planet
    "Atmosphere",
    "Hydrosphere",
    "Lithosphere",
    "Planet",
    "PlanetType",
    # ecology
    "BiomeType",
    "Ecosystem",
    "FoodWeb",
    "Species",
    "TrophicLevel",
    # civilization
    "Civilization",
    "Culture",
    "Government",
    "Settlement",
    # simulation
    "ComputationManifest",
    "EngineInfo",
    "SimulationRun",
    "SimulationSeed",
    "StepRecord",
    # world
    "WorldConfig",
    "WorldMetadata",
    # layers
    "LAYER_DEPENDENCIES",
    "LAYER_ENGINES",
    "LAYER_ORDER",
    "Layer",
    "LayerSummary",
    "get_layer_dependencies",
    "get_layer_index",
    "get_layers_before",
    "validate_layer_order",
    # branch
    "BranchMetadata",
]
