"""Write Pydantic models to YAML/JSON files."""

import json
from pathlib import Path

import yaml
from pydantic import BaseModel


def _model_to_dict(model: BaseModel) -> dict:
    """Convert a Pydantic model to a plain dict for serialization."""
    return model.model_dump(mode="json", exclude_none=True)


def write_yaml(model: BaseModel, path: Path) -> None:
    """Write a Pydantic model to a YAML file.

    Args:
        model: Pydantic model instance.
        path: Output file path.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _model_to_dict(model)
    with path.open("w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def write_json(model: BaseModel, path: Path, *, indent: int = 2) -> None:
    """Write a Pydantic model to a JSON file.

    Args:
        model: Pydantic model instance.
        path: Output file path.
        indent: JSON indentation level.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _model_to_dict(model)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=indent, ensure_ascii=False)
        f.write("\n")
