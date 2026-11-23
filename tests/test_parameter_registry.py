"""Tests for the shared parameter registry."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from dreamulator.engine import get_all_engines
from dreamulator.models.layers import Layer
from dreamulator.parameter_registry import (
    consumers_of,
    load_registry,
    parameters_for_group,
    registry_by_id,
    storage_values,
)

_TEMPLATES = Path("data/templates")


def test_registry_loads_the_first_slice() -> None:
    registry = load_registry()
    by_id = registry_by_id(registry)
    assert set(by_id) == {
        "planet.axial_tilt_deg",
        "planet.rotation_period_days",
        "planet.albedo",
        "planet.greenhouse_warming_k",
    }
    assert by_id["planet.axial_tilt_deg"].group is Layer.ASTRONOMY
    assert by_id["planet.albedo"].group is Layer.CLIMATE
    assert consumers_of("planet.albedo", registry) == frozenset({Layer.ASTRONOMY, Layer.CLIMATE})


def test_parameters_for_group_keeps_registry_order() -> None:
    astronomy = parameters_for_group(Layer.ASTRONOMY)
    climate = parameters_for_group(Layer.CLIMATE)
    assert [parameter.id for parameter in astronomy] == [
        "planet.axial_tilt_deg",
        "planet.rotation_period_days",
    ]
    assert [parameter.id for parameter in climate] == [
        "planet.albedo",
        "planet.greenhouse_warming_k",
    ]


def test_engine_declarations_match_registry() -> None:
    declared: dict[str, set[Layer]] = {}
    for engine in get_all_engines():
        for parameter_id in engine.consumed_parameters:
            declared.setdefault(parameter_id, set()).add(engine.layer)
    registry = load_registry()
    by_id = registry_by_id(registry)
    for parameter in registry.parameters:
        assert set(parameter.consumers) == declared.get(parameter.id, set()), parameter.id
    assert set(declared) <= set(by_id)


def test_storage_paths_resolve_in_templates() -> None:
    registry = load_registry()
    for template in ("minimal", "earthlike"):
        world = _TEMPLATES / template
        for parameter in registry.parameters:
            data = yaml.safe_load((world / parameter.storage.file).read_text(encoding="utf-8"))
            values = storage_values(data, parameter.storage.path)
            assert values, f"{template} is missing {parameter.id}"
            bounds = parameter.range
            for value in values:
                assert isinstance(value, int | float), f"{parameter.id} is not numeric"
                if bounds is None:
                    continue
                if bounds.minimum is not None:
                    assert value >= bounds.minimum
                if bounds.maximum is not None:
                    assert value <= bounds.maximum
                if bounds.exclusive_minimum is not None:
                    assert value > bounds.exclusive_minimum


def test_unknown_parameter_raises() -> None:
    with pytest.raises(KeyError):
        consumers_of("planet.not_a_parameter")
