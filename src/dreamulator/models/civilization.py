"""Civilization models — cultures, governments, settlements."""

from enum import Enum

from pydantic import BaseModel, Field

from .common import Vec3


class GovernmentType(str, Enum):
    """Forms of government."""

    TRIBAL = "tribal"
    MONARCHY = "monarchy"
    FEUDAL = "feudal"
    REPUBLIC = "republic"
    THEOCRACY = "theocracy"
    OLIGARCHY = "oligarchy"
    DEMOCRACY = "democracy"
    EMPIRE = "empire"


class TechLevel(str, Enum):
    """Technological development level."""

    STONE_AGE = "stone_age"
    BRONZE_AGE = "bronze_age"
    IRON_AGE = "iron_age"
    MEDIEVAL = "medieval"
    EARLY_INDUSTRIAL = "early_industrial"
    INDUSTRIAL = "industrial"
    MODERN = "modern"
    FUTURE = "future"


class SettlementType(str, Enum):
    """Size classification for settlements."""

    HAMLET = "hamlet"
    VILLAGE = "village"
    TOWN = "town"
    CITY = "city"
    METROPOLIS = "metropolis"
    CAPITAL = "capital"


class Culture(BaseModel):
    """A cultural group."""

    id: str = Field(description="Unique identifier, e.g. 'culture_northern_tribes'")
    name: str
    language_family: str = Field(default="", description="Language family grouping")
    language_id: str = Field(
        default="",
        description="Conlang language ID (references layers/civilization/input/languages/<id>/)",
    )
    religion: str = ""
    customs: list[str] = Field(default_factory=list)
    description: str = ""


class Government(BaseModel):
    """A political entity's government."""

    type: GovernmentType
    tech_level: TechLevel = TechLevel.IRON_AGE
    stability: float = Field(default=0.5, ge=0, le=1, description="Political stability index")
    description: str = ""


class Settlement(BaseModel):
    """A settlement (village, city, etc.)."""

    id: str
    name: str
    settlement_type: SettlementType = SettlementType.VILLAGE
    position: Vec3 = Field(default_factory=Vec3, description="Position on world map")
    population: int = Field(default=100, ge=0)
    culture_id: str = Field(default="", description="ID of the dominant culture")
    resources: list[str] = Field(default_factory=list, description="Key local resources")


class Civilization(BaseModel):
    """A civilization encompassing one or more settlements."""

    id: str = Field(description="Unique identifier, e.g. 'civ_river_kingdom'")
    name: str
    culture: Culture
    government: Government
    settlements: list[Settlement] = Field(default_factory=list)
    territory_description: str = ""
