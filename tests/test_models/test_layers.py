"""Tests for layer models and utilities."""

import pytest

from dreamulator.models.layers import (
    LAYER_ORDER,
    Layer,
    LayerSummary,
    get_layer_dependencies,
    get_layer_index,
    get_layers_before,
    get_layers_from,
    validate_layer_order,
)


class TestLayerEnum:
    def test_all_layers_in_order(self):
        assert len(LAYER_ORDER) == len(Layer)
        for layer in Layer:
            assert layer in LAYER_ORDER

    def test_layer_values(self):
        assert Layer.PHYSICS.value == "physics"
        assert Layer.CIVILIZATION.value == "civilization"


class TestLayerFunctions:
    def test_get_layer_index(self):
        assert get_layer_index(Layer.PHYSICS) == 0
        assert get_layer_index(Layer.CIVILIZATION) == len(LAYER_ORDER) - 1

    def test_get_layer_index_from_string(self):
        assert get_layer_index("stellar") == 2

    def test_get_layer_index_invalid(self):
        with pytest.raises(ValueError, match="Unknown layer"):
            get_layer_index("invalid_layer")

    def test_get_layers_from(self):
        layers = get_layers_from(Layer.GEOLOGICAL)
        assert Layer.GEOLOGICAL in layers
        assert Layer.CLIMATE in layers
        assert Layer.ECOLOGY in layers
        assert Layer.CIVILIZATION in layers
        assert Layer.STELLAR not in layers

    def test_get_layers_before(self):
        layers = get_layers_before(Layer.GEOLOGICAL)
        assert Layer.PHYSICS in layers
        assert Layer.STELLAR in layers
        assert Layer.ORBITAL in layers
        assert Layer.GEOLOGICAL not in layers

    def test_get_layer_dependencies(self):
        deps = get_layer_dependencies(Layer.CLIMATE)
        assert Layer.ORBITAL in deps
        assert Layer.GEOLOGICAL in deps

    def test_get_layer_dependencies_root(self):
        deps = get_layer_dependencies(Layer.PHYSICS)
        assert deps == []

    def test_validate_layer_order_valid(self):
        assert validate_layer_order([Layer.PHYSICS, Layer.STELLAR, Layer.GEOLOGICAL])

    def test_validate_layer_order_invalid(self):
        assert not validate_layer_order([Layer.GEOLOGICAL, Layer.PHYSICS])


class TestLayerSummary:
    def test_default_values(self):
        summary = LayerSummary()
        assert summary.configured is False
        assert summary.engine == ""
        assert summary.inherited_from is None
        assert summary.layer is None

    def test_with_values(self):
        summary = LayerSummary(
            layer=Layer.STELLAR,
            configured=True,
            engine="stellar",
        )
        assert summary.layer == Layer.STELLAR
        assert summary.configured is True
