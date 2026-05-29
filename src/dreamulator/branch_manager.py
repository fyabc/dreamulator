"""Branch manager — CRUD operations for world branches."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from .models.branch import BranchMetadata
from .models.layers import Layer, get_layers_from


class BranchManager:
    """Manages branches within a world directory."""

    def __init__(self, world_dir: Path):
        """Initialize branch manager.

        Args:
            world_dir: Path to the root world directory.
        """
        self.world_dir = world_dir
        self.branches_dir = world_dir / "branches"

    def create_branch(
        self,
        name: str,
        fork_layer: Layer | str,
        *,
        parent: str | None = None,
        description: str = "",
        tags: list[str] | None = None,
    ) -> Path:
        """Create a new branch at the specified layer.

        Args:
            name: Branch name (unique within the world).
            fork_layer: Layer where this branch diverges from parent.
            parent: Parent world/branch name (None means root world).
            description: Human-readable description.
            tags: Tags for categorization.

        Returns:
            Path to the created branch directory.

        Raises:
            FileExistsError: If branch with this name already exists.
            ValueError: If fork_layer is invalid.
        """
        if isinstance(fork_layer, str):
            fork_layer = Layer(fork_layer)

        branch_dir = self.branches_dir / name
        if branch_dir.exists():
            raise FileExistsError(f"Branch '{name}' already exists at {branch_dir}")

        # Create branch directory structure
        branch_dir.mkdir(parents=True, exist_ok=True)

        # Create layers from fork_layer onwards
        layers_to_create = get_layers_from(fork_layer)
        for layer in layers_to_create:
            layer_dir = branch_dir / "layers" / layer.value
            (layer_dir / "input").mkdir(parents=True, exist_ok=True)
            (layer_dir / "derived").mkdir(parents=True, exist_ok=True)

        # Write branch.yaml
        metadata = BranchMetadata(
            name=name,
            parent=parent,
            fork_layer=fork_layer,
            description=description,
            created=datetime.now(),
            tags=tags or [],
        )
        branch_yaml = branch_dir / "branch.yaml"
        with branch_yaml.open("w", encoding="utf-8") as f:
            f.write(metadata.model_dump_json(indent=2))

        return branch_dir

    def list_branches(self) -> list[BranchMetadata]:
        """List all branches in the world.

        Returns:
            List of BranchMetadata for each branch.
        """
        if not self.branches_dir.exists():
            return []

        branches = []
        for branch_dir in sorted(self.branches_dir.iterdir()):
            if not branch_dir.is_dir():
                continue

            branch_yaml = branch_dir / "branch.yaml"
            if not branch_yaml.exists():
                continue

            with branch_yaml.open("r", encoding="utf-8") as f:
                metadata = BranchMetadata.model_validate_json(f.read())
                branches.append(metadata)

        return branches

    def get_branch(self, name: str) -> BranchMetadata:
        """Get metadata for a specific branch.

        Args:
            name: Branch name.

        Returns:
            BranchMetadata for the branch.

        Raises:
            FileNotFoundError: If branch does not exist.
        """
        branch_dir = self.branches_dir / name
        branch_yaml = branch_dir / "branch.yaml"

        if not branch_yaml.exists():
            raise FileNotFoundError(f"Branch '{name}' not found")

        with branch_yaml.open("r", encoding="utf-8") as f:
            return BranchMetadata.model_validate_json(f.read())

    def branch_dir(self, name: str) -> Path:
        """Get the directory path for a branch.

        Args:
            name: Branch name.

        Returns:
            Path to the branch directory.

        Raises:
            FileNotFoundError: If branch does not exist.
        """
        branch_dir = self.branches_dir / name
        if not branch_dir.exists():
            raise FileNotFoundError(f"Branch '{name}' not found")
        return branch_dir

    def delete_branch(self, name: str) -> None:
        """Delete a branch.

        Args:
            name: Branch name.

        Raises:
            FileNotFoundError: If branch does not exist.
        """
        branch_dir = self.branch_dir(name)
        shutil.rmtree(branch_dir)

    def promote_branch(self, name: str, new_name: str | None = None) -> Path:
        """Promote a branch to a standalone world.

        This moves the branch from branches/{name} to a top-level world directory.

        Args:
            name: Branch name to promote.
            new_name: New name for the world (defaults to branch name).

        Returns:
            Path to the new world directory.

        Raises:
            FileNotFoundError: If branch does not exist.
            FileExistsError: If target world already exists.
        """
        branch_dir = self.branch_dir(name)
        target_name = new_name or name
        target_dir = self.world_dir.parent / target_name

        if target_dir.exists():
            raise FileExistsError(f"World '{target_name}' already exists at {target_dir}")

        # Move branch to top-level
        shutil.move(str(branch_dir), str(target_dir))

        # Update branch.yaml to reflect promotion
        branch_yaml = target_dir / "branch.yaml"
        if branch_yaml.exists():
            with branch_yaml.open("r", encoding="utf-8") as f:
                metadata = BranchMetadata.model_validate_json(f.read())

            # Clear parent since it's now a standalone world
            metadata.parent = None

            with branch_yaml.open("w", encoding="utf-8") as f:
                f.write(metadata.model_dump_json(indent=2))

        return target_dir
