"""Layer definitions and utilities for the hierarchical world building system.

Layers are ordered from most fundamental to most derived. Each layer represents
a scientific discipline that builds upon the layers below it.

The layer hierarchy:
    physics → chemistry → stellar → orbital → geological → climate → ecology → civilization
"""

from enum import Enum
from typing import TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Layer(str, Enum):
    """World building layers, ordered from fundamental to derived."""

    PHYSICS = "physics"
    CHEMISTRY = "chemistry"
    STELLAR = "stellar"
    ORBITAL = "orbital"
    GEOLOGICAL = "geological"
    CLIMATE = "climate"
    ECOLOGY = "ecology"
    CIVILIZATION = "civilization"


# Ordered list from most fundamental to most derived
LAYER_ORDER: list[Layer] = [
    Layer.PHYSICS,
    Layer.CHEMISTRY,
    Layer.STELLAR,
    Layer.ORBITAL,
    Layer.GEOLOGICAL,
    Layer.CLIMATE,
    Layer.ECOLOGY,
    Layer.CIVILIZATION,
]

# Map each layer to its corresponding engine(s) (Phase 2 implementation)
LAYER_ENGINES: dict[Layer, list[str]] = {
    Layer.PHYSICS: [],
    Layer.CHEMISTRY: [],
    Layer.STELLAR: ["stellar"],
    Layer.ORBITAL: ["orbital"],
    Layer.GEOLOGICAL: ["geological"],
    Layer.CLIMATE: ["climate"],
    Layer.ECOLOGY: ["ecology"],
    Layer.CIVILIZATION: ["civilization"],
}

# Layer dependencies: which layers must be resolved before this one
LAYER_DEPENDENCIES: dict[Layer, list[Layer]] = {
    Layer.PHYSICS: [],
    Layer.CHEMISTRY: [Layer.PHYSICS],
    Layer.STELLAR: [Layer.PHYSICS, Layer.CHEMISTRY],
    Layer.ORBITAL: [Layer.STELLAR],
    Layer.GEOLOGICAL: [Layer.ORBITAL],
    Layer.CLIMATE: [Layer.ORBITAL, Layer.GEOLOGICAL],
    Layer.ECOLOGY: [Layer.CLIMATE, Layer.GEOLOGICAL],
    Layer.CIVILIZATION: [Layer.ECOLOGY, Layer.GEOLOGICAL, Layer.CLIMATE],
}


def get_layer_index(layer: Layer | str) -> int:
    """Get the index of a layer in the ordered list.

    Args:
        layer: Layer enum or string name.

    Returns:
        Index (0-based) in LAYER_ORDER.

    Raises:
        ValueError: If layer is not valid.
    """
    if isinstance(layer, str):
        try:
            layer = Layer(layer)
        except ValueError:
            valid = [L.value for L in Layer]
            raise ValueError(f"Unknown layer '{layer}'. Valid layers: {valid}")
    return LAYER_ORDER.index(layer)


def get_layers_from(layer: Layer | str) -> list[Layer]:
    """Get all layers from the specified layer to the end (inclusive).

    Args:
        layer: Starting layer.

    Returns:
        List of layers from the specified layer onwards.
    """
    idx = get_layer_index(layer)
    return LAYER_ORDER[idx:]


def get_layers_before(layer: Layer | str) -> list[Layer]:
    """Get all layers before the specified layer (exclusive).

    Args:
        layer: Reference layer.

    Returns:
        List of layers before the specified layer.
    """
    idx = get_layer_index(layer)
    return LAYER_ORDER[:idx]


def get_layer_dependencies(layer: Layer | str) -> list[Layer]:
    """Get direct dependencies of a layer.

    Args:
        layer: Target layer.

    Returns:
        List of layers that must be resolved before this layer.
    """
    if isinstance(layer, str):
        layer = Layer(layer)
    return LAYER_DEPENDENCIES.get(layer, [])


def validate_layer_order(layers: list[Layer | str]) -> bool:
    """Check if a list of layers is in valid order.

    Args:
        layers: List of layers to validate.

    Returns:
        True if layers are in valid order (no layer appears before its dependencies).
    """
    seen_indices = []
    for layer in layers:
        idx = get_layer_index(layer)
        seen_indices.append(idx)

    # Check if indices are non-decreasing
    return all(seen_indices[i] <= seen_indices[i + 1] for i in range(len(seen_indices) - 1))


class LayerSummary(BaseModel):
    """Summary information about a layer in a world.

    The layer name is the dict key in WorldConfig.layers, so the 'layer'
    field here is optional — it can be populated from the key at load time.
    """

    layer: Layer | None = Field(default=None, description="Layer identifier (from dict key)")
    configured: bool = Field(
        default=False, description="Whether this layer has custom input data"
    )
    engine: str = Field(default="", description="Engine that processes this layer")
    inherited_from: str | None = Field(
        default=None, description="Parent world/branch this layer is inherited from"
    )
