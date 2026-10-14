"""Branch metadata model for world variant management.

Branches allow creating variants of a world that fork at a specific layer.
Layers before the fork point are inherited from the parent, while layers
from the fork point onwards can have custom data.
"""

from datetime import datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, Field, model_validator

from .layers import Layer


class ClimateSource(StrEnum):
    """Where a branch's climate layer comes from.

    - ``engine``: the climate engine simulates it (default).
    - ``gcm``: the climate is pinned to an imported ExoPlaSim result
      (``layers/climate/input/gcm_fields.msgpack.gz``).  The engine never
      simulates such a branch, ``--force`` included; it only writes the pinned
      fields onto the inherited mesh so the downstream layers can build.
    """

    ENGINE = "engine"
    GCM = "gcm"


class BranchMetadata(BaseModel):
    """Metadata for a world branch.

    A branch represents a variant of a world that diverges at a specific layer.
    - parent: None means this is the root world (not a branch)
    - fork_layer: The layer where this branch diverges from its parent
    """

    name: str = Field(description="Branch name (unique within a world)")
    parent: str | None = Field(
        default=None,
        description="Parent world or branch name. None for root world.",
    )
    fork_layer: Layer | None = Field(
        default=None,
        description="Layer where this branch forks from parent. None for root world.",
    )
    description: str = Field(default="", description="Human-readable description")
    created: datetime = Field(
        default_factory=datetime.now,
        description="Creation timestamp",
    )
    tags: list[str] = Field(default_factory=list, description="Tags for categorization")
    climate_source: ClimateSource = Field(
        default=ClimateSource.ENGINE,
        description="engine = simulated climate; gcm = climate pinned to an imported GCM "
        "result (requires fork_layer == climate)",
    )

    @model_validator(mode="after")
    def _gcm_climate_forks_at_climate(self) -> Self:
        # A pinned GCM climate only makes sense on a branch that owns the climate
        # layer but inherits geology: forking earlier would rebuild the terrain the
        # GCM was run on, forking later would inherit someone else's climate.
        if self.climate_source is ClimateSource.GCM and self.fork_layer is not Layer.CLIMATE:
            raise ValueError("climate_source 'gcm' requires fork_layer 'climate'")
        return self

    def is_root(self) -> bool:
        """Check if this is a root world (not a branch)."""
        return self.parent is None and self.fork_layer is None

    def is_branch(self) -> bool:
        """Check if this is a branch (has a parent)."""
        return self.parent is not None or self.fork_layer is not None
