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
