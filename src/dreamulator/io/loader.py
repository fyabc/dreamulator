"""Load YAML/JSON files into Pydantic models."""

from pathlib import Path
from typing import TypeVar

import yaml
from pydantic import BaseModel

from dreamulator.models.world import WorldConfig

T = TypeVar("T", bound=BaseModel)


def load_yaml_model(path: Path, model_class: type[T]) -> T:
    """Load a YAML file and validate it against a Pydantic model.

    Args:
        path: Path to the YAML file.
        model_class: Pydantic model class to validate against.

    Returns:
        Validated model instance.

    Raises:
        FileNotFoundError: If the file does not exist.
        yaml.YAMLError: If the file is not valid YAML.
    """
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if data is None:
        data = {}

    return model_class.model_validate(data)


def load_world(world_dir: Path) -> WorldConfig:
    """Load a world's root configuration from world.yaml.

    Args:
        world_dir: Path to the world directory.

    Returns:
        Validated WorldConfig instance.
    """
    return load_yaml_model(world_dir / "world.yaml", WorldConfig)


def load_layer_input(
    world_dir: Path,
    layer: str,
    filename: str,
    model_class: type[T],
    *,
    branch: str | None = None,
) -> T:
    """Load a YAML file from a layer's input directory.

    Searches the branch inheritance chain if branch is specified.

    Args:
        world_dir: Path to the world directory.
        layer: Layer name (e.g., 'stellar', 'geological').
        filename: YAML filename within the input directory.
        model_class: Pydantic model class for validation.
        branch: Optional branch name to search from.

    Returns:
        Validated model instance.

    Raises:
        FileNotFoundError: If the file cannot be found in the layer chain.
    """
    from dreamulator.resolver import LayerResolver

    resolver = LayerResolver(world_dir, branch)
    input_dir = resolver.get_input_dir(layer)

    if input_dir is None:
        raise FileNotFoundError(
            f"No input directory found for layer '{layer}'"
            + (f" in branch '{branch}'" if branch else "")
        )

    path = input_dir / filename
    return load_yaml_model(path, model_class)
