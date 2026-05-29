"""World root model — top-level world configuration."""

from pydantic import BaseModel, Field

from .branch import BranchMetadata
from .layers import LayerSummary
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

    # Branch metadata: None for root world, populated for branches
    branch: BranchMetadata | None = Field(
        default=None,
        description="Branch metadata. None for root world.",
    )

    # stellar_system is optional for backward compatibility.
    # In the new layer-based structure, stellar data lives in layers/stellar/input/stellar.yaml
    stellar_system: StellarSystem | None = Field(
        default=None,
        description="Stellar system data (legacy; prefer layers/stellar/input/stellar.yaml)",
    )

    # Layer configuration summary
    layers: dict[str, LayerSummary] = Field(
        default_factory=dict,
        description="Summary of each layer's configuration status",
    )

    planet_ids: list[str] = Field(
        default_factory=list,
        description="IDs of planets defined in separate planets.yaml file",
    )
