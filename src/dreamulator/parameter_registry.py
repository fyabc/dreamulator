"""Declarative registry of authored world parameters.

Each registry entry separates three concepts that are easy to conflate:

- ``group``: the UI grouping (astronomy, climate, geology, ...);
- ``storage``: the single authored location of the value;
- ``consumers``: engine layers whose output or metadata reads the value.

The registry is the shared contract for the parameter lab, validation and the
per-layer input projections described in
``docs/design/proposals/parameter-ownership.md``.  It is a checked-in JSON file
so the frontend can import the same data without a second copy.

This first slice covers the four planet physical parameters edited by the
climate lab and world-parameters panel.  Grid size and water coverage need a
storage resolver for their alternative files; they join in a later slice.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Pydantic resolves Layer at class-creation time, so this import is runtime.
from dreamulator.models.layers import Layer  # noqa: TC001

REGISTRY_FILENAME = "parameter_registry.json"
REGISTRY_PATH = Path(__file__).with_name(REGISTRY_FILENAME)


class StorageSpec(BaseModel):
    """The single authored location of a parameter."""

    model_config = ConfigDict(extra="forbid")

    file: str = Field(description="Input file relative to the world root")
    path: list[str | int] = Field(
        description="YAML path inside the file; '*' iterates a list of mappings"
    )

    @field_validator("file")
    @classmethod
    def _check_file(cls, value: str) -> str:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("storage file must stay inside the world directory")
        return value

    @field_validator("path")
    @classmethod
    def _check_path(cls, value: list[str | int]) -> list[str | int]:
        if not value:
            raise ValueError("storage path must not be empty")
        return value


class RangeSpec(BaseModel):
    """Numeric bounds shown by the editor and checked before saving."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    minimum: float | None = None
    maximum: float | None = None
    exclusive_minimum: float | None = Field(default=None, alias="exclusiveMinimum")

    @model_validator(mode="after")
    def _check_bounds(self) -> RangeSpec:
        if self.minimum is None and self.maximum is None and self.exclusive_minimum is None:
            raise ValueError("range needs at least one bound")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("minimum must not exceed maximum")
        return self


class ParameterSpec(BaseModel):
    """One editable parameter."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="Stable identifier, e.g. planet.axial_tilt_deg")
    group: Layer = Field(description="UI grouping layer")
    storage: StorageSpec
    type: Literal["number", "enum", "boolean"] = "number"
    unit: str | None = None
    range: RangeSpec | None = None
    consumers: list[Layer] = Field(min_length=1)
    note: str | None = None

    @field_validator("consumers")
    @classmethod
    def _check_consumers(cls, value: list[Layer]) -> list[Layer]:
        if len(value) != len(set(value)):
            raise ValueError("consumers must be unique")
        return value

    @field_validator("id")
    @classmethod
    def _check_id(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("parameter id must be a non-empty trimmed string")
        return value


class ParameterRegistry(BaseModel):
    """The whole registry document."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: int = Field(alias="schema", ge=1)
    parameters: list[ParameterSpec]

    @model_validator(mode="after")
    def _check_unique_ids(self) -> ParameterRegistry:
        ids = [parameter.id for parameter in self.parameters]
        if len(ids) != len(set(ids)):
            raise ValueError("parameter ids must be unique")
        return self


@lru_cache(maxsize=4)
def load_registry(path: Path | None = None) -> ParameterRegistry:
    """Load and validate the registry.

    Args:
        path: Optional registry path; defaults to the packaged JSON file.
    """
    source = path or REGISTRY_PATH
    data = json.loads(source.read_text(encoding="utf-8"))
    return ParameterRegistry.model_validate(data)


def registry_by_id(registry: ParameterRegistry | None = None) -> dict[str, ParameterSpec]:
    """Index the registry by parameter id."""
    document = registry or load_registry()
    return {parameter.id: parameter for parameter in document.parameters}


def consumers_of(parameter_id: str, registry: ParameterRegistry | None = None) -> frozenset[Layer]:
    """Return the engine layers that read a parameter."""
    parameter = registry_by_id(registry).get(parameter_id)
    if parameter is None:
        raise KeyError(f"Unknown parameter id: {parameter_id}")
    return frozenset(parameter.consumers)


def parameters_for_group(
    group: Layer, registry: ParameterRegistry | None = None
) -> tuple[ParameterSpec, ...]:
    """Return the parameters grouped under one UI layer, in registry order."""
    document = registry or load_registry()
    return tuple(parameter for parameter in document.parameters if parameter.group is group)


def storage_values(document: Any, path: list[str | int]) -> list[Any]:
    """Collect every value matching a storage path.

    ``"*"`` iterates a list of mappings; integer segments index lists.  Missing
    branches are skipped, so the caller can decide whether an empty result is
    valid for its context.
    """
    current: list[Any] = [document]
    for segment in path:
        next_values: list[Any] = []
        for value in current:
            if segment == "*":
                if isinstance(value, list):
                    next_values.extend(value)
            elif isinstance(segment, int):
                if isinstance(value, list) and -len(value) <= segment < len(value):
                    next_values.append(value[segment])
            elif isinstance(value, dict) and segment in value:
                next_values.append(value[segment])
        current = next_values
        if not current:
            break
    return current
