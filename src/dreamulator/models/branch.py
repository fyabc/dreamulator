"""Branch metadata model for world variant management.

Branches allow creating variants of a world that fork at a specific layer.
Layers before the fork point are inherited from the parent, while layers
from the fork point onwards can have custom data.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from .layers import Layer


class BranchMetadata(BaseModel):
    """Metadata for a world branch.

    A branch represents a variant of a world that diverges at a specific layer.
    - parent: None means this is the root world (not a branch)
    - fork_layer: The layer where this branch diverges from its parent
    """

    name: str = Field(description="Branch name (unique within a world)")
    parent: Optional[str] = Field(
        default=None,
        description="Parent world or branch name. None for root world.",
    )
    fork_layer: Optional[Layer] = Field(
        default=None,
        description="Layer where this branch forks from parent. None for root world.",
    )
    description: str = Field(default="", description="Human-readable description")
    created: datetime = Field(
        default_factory=datetime.now,
        description="Creation timestamp",
    )
    tags: list[str] = Field(default_factory=list, description="Tags for categorization")

    def is_root(self) -> bool:
        """Check if this is a root world (not a branch)."""
        return self.parent is None and self.fork_layer is None

    def is_branch(self) -> bool:
        """Check if this is a branch (has a parent)."""
        return self.parent is not None or self.fork_layer is not None
