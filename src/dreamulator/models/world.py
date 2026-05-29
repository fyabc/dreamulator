"""World root model — top-level world configuration."""

from pydantic import BaseModel, Field

from .simulation import SimulationSeed
from .stellar import StellarSystem


class WorldMetadata(BaseModel):
    """Metadata about a world instance."""

    name: str = Field(description="World name (also used as directory name)")
    description: str = Field(default="", description="Brief description of the world")
    version: str = Field(default="0.1.0", description="World data format version")
    dreamulator_version: str = Field(
        default="0.1.0", description="Version of dreamulator that created this world"
    )
    created: str = Field(description="ISO 8601 creation timestamp")
    modified: str = Field(description="ISO 8601 last-modified timestamp")
    tags: list[str] = Field(default_factory=list, description="Freeform tags for categorization")


class WorldConfig(BaseModel):
    """Top-level world.yaml structure — the root of all world data."""

    metadata: WorldMetadata
    seed: SimulationSeed
    stellar_system: StellarSystem
    planet_ids: list[str] = Field(
        default_factory=list,
        description="IDs of planets defined in separate planets.yaml file",
    )
