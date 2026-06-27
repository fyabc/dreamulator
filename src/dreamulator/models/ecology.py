"""Ecology models — species, ecosystems, biomes, food webs."""

from enum import Enum

from pydantic import BaseModel, Field


class BiomeType(str, Enum):
    """Whittaker biome classification."""

    TROPICAL_RAINFOREST = "tropical_rainforest"
    TROPICAL_SEASONAL_FOREST = "tropical_seasonal_forest"
    TEMPERATE_RAINFOREST = "temperate_rainforest"
    TEMPERATE_SEASONAL_FOREST = "temperate_seasonal_forest"
    TEMPERATE_GRASSLAND = "temperate_grassland"
    BOREAL_FOREST = "boreal_forest"
    TUNDRA = "tundra"
    SAVANNA = "savanna"
    DESERT = "desert"
    MEDITERRANEAN = "mediterranean"
    POLAR_ICE = "polar_ice"


class TrophicLevel(str, Enum):
    """Trophic level in a food web."""

    PRODUCER = "producer"
    PRIMARY_CONSUMER = "primary_consumer"
    SECONDARY_CONSUMER = "secondary_consumer"
    TERTIARY_CONSUMER = "tertiary_consumer"
    DECOMPOSER = "decomposer"


class Species(BaseModel):
    """A species in the world."""

    id: str = Field(description="Unique identifier, e.g. 'species_oak_tree'")
    name: str = Field(description="Common name")
    scientific_name: str = Field(default="", description="Binomial nomenclature")
    trophic_level: TrophicLevel
    biomes: list[BiomeType] = Field(
        default_factory=list, description="Biomes this species inhabits"
    )
    description: str = ""
    traits: dict[str, str] = Field(default_factory=dict, description="Key biological traits")


class FoodWeb(BaseModel):
    """A food web connecting species in an ecosystem."""

    biome: BiomeType
    predator_prey: list[tuple[str, str]] = Field(
        default_factory=list,
        description="Pairs of (predator_species_id, prey_species_id)",
    )


class Ecosystem(BaseModel):
    """An ecosystem within a region."""

    id: str
    biome: BiomeType
    species_ids: list[str] = Field(default_factory=list)
    food_web: FoodWeb | None = None
    productivity: float = Field(
        default=1.0, ge=0, description="Net primary productivity relative to Earth average"
    )
