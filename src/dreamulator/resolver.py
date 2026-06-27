"""Layer resolver — resolves effective layer data by walking branch inheritance chains."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from .models.branch import BranchMetadata
from .models.layers import LAYER_ORDER, Layer


# ---------------------------------------------------------------------------
# Merge helpers for _inherit: true branch data
# ---------------------------------------------------------------------------

_ID_KEYS = ("id", "body_id")


def _merge_list_by_id(base: list, override: list) -> list:
    """Merge two lists, matching items by 'id' or 'body_id' field.

    - Items with matching IDs: override replaces base item
    - New IDs in override: appended to result
    - Items without ID keys: appended unconditionally
    """
    merged = list(base)
    for item in override:
        item_id = next((item.get(k) for k in _ID_KEYS if k in item), None)
        if item_id is not None:
            for i, existing in enumerate(merged):
                if any(existing.get(k) == item_id for k in _ID_KEYS):
                    merged[i] = item
                    break
            else:
                merged.append(item)
        else:
            merged.append(item)
    return merged


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override dict into base dict.

    - Dicts: recursive merge
    - Lists: merge by ID (via _merge_list_by_id)
    - Scalars: override wins
    """
    result = dict(base)
    for key, value in override.items():
        if key in result:
            if isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = _deep_merge(result[key], value)
            elif isinstance(result[key], list) and isinstance(value, list):
                result[key] = _merge_list_by_id(result[key], value)
            else:
                result[key] = value
        else:
            result[key] = value
    return result


@dataclass
class LayerSource:
    """Information about where a layer's data comes from."""

    layer: Layer
    input_dir: Path | None  # Path to input directory (None if layer not configured)
    derived_dir: Path | None  # Path to derived directory (None if not computed)
    source: str  # Description of where this came from (e.g., "root", "branch:pangea")


class LayerResolver:
    """Resolves effective layer data for a world or branch by walking inheritance chains.

    For a branch at layer L:
    - Layers before L: inherited from parent chain
    - Layer L and after: from branch's own data (or inherited if not overridden)
    """

    def __init__(self, world_dir: Path, branch_name: str | None = None):
        """Initialize resolver.

        Args:
            world_dir: Path to the root world directory.
            branch_name: Name of the branch to resolve (None for root world).
        """
        self.world_dir = world_dir
        self.branch_name = branch_name
        self._branch_chain: list[tuple[BranchMetadata | None, Path]] | None = None

    def _get_branch_chain(self) -> list[tuple[BranchMetadata | None, Path]]:
        """Get the inheritance chain from current branch up to root world.

        Returns:
            List of (BranchMetadata | None, dir_path) tuples.
            First element is the current branch (or root if no branch).
            Last element is always the root world.
        """
        if self._branch_chain is not None:
            return self._branch_chain

        chain: list[tuple[BranchMetadata | None, Path]] = []

        if self.branch_name is None:
            # Start from root world
            chain.append((None, self.world_dir))
        else:
            # Start from branch and walk up
            current_branch = self.branch_name
            current_dir = self.world_dir / "branches" / current_branch

            while current_branch is not None:
                branch_yaml = current_dir / "branch.yaml"
                if not branch_yaml.exists():
                    raise FileNotFoundError(f"Branch '{current_branch}' not found at {current_dir}")

                with branch_yaml.open("r", encoding="utf-8") as f:
                    metadata = BranchMetadata.model_validate_json(f.read())

                chain.append((metadata, current_dir))

                # Walk up to parent
                if metadata.parent is not None:
                    # Parent is another branch or the root world
                    # For now, we only support parent = None (root world)
                    # Future: support nested branches
                    current_branch = metadata.parent
                    current_dir = self.world_dir / "branches" / current_branch
                else:
                    # Parent is root world
                    chain.append((None, self.world_dir))
                    break

        self._branch_chain = chain
        return chain

    def resolve_layer(self, layer: Layer | str) -> LayerSource:
        """Resolve the effective source for a layer.

        Walks the inheritance chain and returns the first location that has
        input data for this layer.

        Args:
            layer: Layer to resolve.

        Returns:
            LayerSource describing where the layer data comes from.
        """
        if isinstance(layer, str):
            layer = Layer(layer)

        chain = self._get_branch_chain()

        # Walk chain from current (most specific) to root (most general)
        for metadata, dir_path in chain:
            layer_dir = dir_path / "layers" / layer.value
            input_dir = layer_dir / "input"
            derived_dir = layer_dir / "derived"

            # Check if this level has input data
            if input_dir.exists() and any(input_dir.iterdir()):
                source = "root" if metadata is None else f"branch:{metadata.name}"
                return LayerSource(
                    layer=layer,
                    input_dir=input_dir,
                    derived_dir=derived_dir if derived_dir.exists() else None,
                    source=source,
                )

        # No input data found anywhere
        return LayerSource(
            layer=layer,
            input_dir=None,
            derived_dir=None,
            source="not configured",
        )

    def resolve_all_layers(self) -> dict[Layer, LayerSource]:
        """Resolve all layers.

        Returns:
            Dictionary mapping each layer to its LayerSource.
        """
        return {layer: self.resolve_layer(layer) for layer in LAYER_ORDER}

    def get_input_dir(self, layer: Layer | str) -> Path | None:
        """Get the effective input directory for a layer.

        Args:
            layer: Layer to query.

        Returns:
            Path to input directory, or None if not configured.
        """
        source = self.resolve_layer(layer)
        return source.input_dir

    def get_derived_dir(self, layer: Layer | str) -> Path | None:
        """Get the effective derived directory for a layer.

        Args:
            layer: Layer to query.

        Returns:
            Path to derived directory, or None if not computed.
        """
        source = self.resolve_layer(layer)
        return source.derived_dir

    def get_branch_metadata(self) -> BranchMetadata | None:
        """Get metadata for the current branch.

        Returns:
            BranchMetadata if resolving a branch, None for root world.
        """
        if self.branch_name is None:
            return None

        chain = self._get_branch_chain()
        if chain and chain[0][0] is not None:
            return chain[0][0]
        return None

    def get_fork_layer(self) -> Layer | None:
        """Get the fork layer for the current branch.

        Returns:
            Layer where the current branch forks, or None for root world.
        """
        metadata = self.get_branch_metadata()
        return metadata.fork_layer if metadata else None

    # -------------------------------------------------------------------
    # Inheritance-aware YAML loading
    # -------------------------------------------------------------------

    def load_layer_yaml(self, layer: Layer | str, filename: str) -> dict | list | None:
        """Load a YAML file with ``_inherit: true`` merge support.

        Walks the inheritance chain (branch → … → root).  If a level's file
        contains ``_inherit: true``, its data is merged on top of the parent
        level's data (lists merged by ``id``/``body_id``, dicts merged
        recursively, scalars overridden).  The ``_inherit`` key is stripped
        from the result.

        If no level contains ``_inherit``, the first file found in the chain
        is returned as-is (current behaviour).

        Args:
            layer: Layer to load.
            filename: YAML file name inside the layer's ``input/`` directory.

        Returns:
            Merged data dict/list, or ``None`` if no file found.
        """
        if isinstance(layer, str):
            layer = Layer(layer)

        chain = self._get_branch_chain()

        # Collect (dir_path, yaml_path) pairs from most-specific to root
        levels: list[tuple[Path, Path]] = []
        for _meta, dir_path in chain:
            yaml_path = dir_path / "layers" / layer.value / "input" / filename
            if yaml_path.exists():
                levels.append((dir_path, yaml_path))

        if not levels:
            return None

        # Walk from root (most general) → most specific, merging as we go.
        # levels[0] is most specific, levels[-1] is root → reverse for bottom-up.
        result: Any = None
        for _dir, yaml_path in reversed(levels):
            with yaml_path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f)

            if data is None:
                continue

            if result is None:
                # First (root-most) file — use as base
                if isinstance(data, dict):
                    data.pop("_inherit", None)
                result = data
                continue

            # Parent data already in `result`.  Does this level request merge?
            if isinstance(data, dict) and data.pop("_inherit", False):
                result = _deep_merge(result, data)
            else:
                # No _inherit → this level fully replaces parent
                result = data

        return result
