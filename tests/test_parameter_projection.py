"""Tests for per-layer input projections and projection-based freshness."""

from __future__ import annotations

from typing import TYPE_CHECKING

import yaml

from dreamulator.models.layers import Layer
from dreamulator.parameter_projection import (
    build_layer_engine,
    compute_input_projection,
    load_input_projection,
    write_input_projection,
)
from dreamulator.world_layer_status import compute_layer_status

if TYPE_CHECKING:
    from pathlib import Path

_PLANET = {
    "id": "planet_x",
    "name": "X",
    "mass": 1.0,
    "radius": 1.0,
    "rotation_period_days": 5.56,
    "axial_tilt_deg": 23.4,
    "albedo": 0.3,
    "atmosphere": {"greenhouse_factor": 33.0},
    "hydrosphere": {"water_coverage": 0.7},
}
_STELLAR = {
    "name": "Test",
    "stars": [{"id": "star_a", "name": "A", "spectral_class": "G", "mass": 1.0}],
    "orbits": [],
    "bodies": [],
}


def _write_world(tmp_path: Path) -> Path:
    world = tmp_path / "w"
    stellar = world / "layers/astronomy/input/stellar.yaml"
    planets = world / "layers/geological/input/planets.yaml"
    stellar.parent.mkdir(parents=True)
    planets.parent.mkdir(parents=True)
    stellar.write_text(yaml.safe_dump(_STELLAR, sort_keys=False), encoding="utf-8")
    planets.write_text(yaml.safe_dump({"planets": [_PLANET]}, sort_keys=False), encoding="utf-8")
    return world


def _projection(world: Path, layer: Layer):
    engine = build_layer_engine(world, layer, None, 42)
    assert engine is not None
    return compute_input_projection(engine)


def _edit_planet(world: Path, **changes: object) -> None:
    path = world / "layers/geological/input/planets.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["planets"][0].update(changes)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def test_albedo_change_only_affects_its_consumers(tmp_path: Path) -> None:
    world = _write_world(tmp_path)
    geology = _projection(world, Layer.GEOLOGICAL)
    climate = _projection(world, Layer.CLIMATE)
    astronomy = _projection(world, Layer.ASTRONOMY)

    _edit_planet(world, albedo=0.5)

    assert _projection(world, Layer.GEOLOGICAL) == geology
    assert _projection(world, Layer.CLIMATE) != climate
    assert _projection(world, Layer.ASTRONOMY) != astronomy


def test_tilt_change_affects_all_three_consumers(tmp_path: Path) -> None:
    world = _write_world(tmp_path)
    before = {
        layer: _projection(world, layer)
        for layer in (Layer.GEOLOGICAL, Layer.CLIMATE, Layer.ASTRONOMY)
    }
    _edit_planet(world, axial_tilt_deg=30.0)
    for layer, projection in before.items():
        assert _projection(world, layer) != projection


def test_unregistered_field_change_is_conservative(tmp_path: Path) -> None:
    world = _write_world(tmp_path)
    before = {
        layer: _projection(world, layer)
        for layer in (Layer.GEOLOGICAL, Layer.CLIMATE, Layer.ASTRONOMY)
    }
    path = world / "layers/geological/input/planets.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["planets"][0]["hydrosphere"]["water_coverage"] = 0.5
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    for layer, projection in before.items():
        assert _projection(world, layer) != projection


def test_comment_edit_does_not_change_projection(tmp_path: Path) -> None:
    world = _write_world(tmp_path)
    before = _projection(world, Layer.CLIMATE)
    path = world / "layers/geological/input/planets.yaml"
    path.write_text(f"# narrative comment\n{path.read_text(encoding='utf-8')}", encoding="utf-8")
    assert _projection(world, Layer.CLIMATE) == before


def test_status_compares_recorded_projection(tmp_path: Path) -> None:
    world = _write_world(tmp_path)
    for layer in (Layer.GEOLOGICAL, Layer.CLIMATE):
        engine = build_layer_engine(world, layer, None, 42)
        assert engine is not None
        write_input_projection(engine)
    assert load_input_projection(world / "layers/geological/derived") is not None

    assert compute_layer_status(world, "geological", seed=42)["derived_fresh"] == "fresh"
    assert compute_layer_status(world, "climate", seed=42)["derived_fresh"] == "fresh"

    _edit_planet(world, albedo=0.5)
    assert compute_layer_status(world, "geological", seed=42)["derived_fresh"] == "fresh"
    assert compute_layer_status(world, "climate", seed=42)["derived_fresh"] == "stale"

    _edit_planet(world, axial_tilt_deg=30.0)
    assert compute_layer_status(world, "geological", seed=42)["derived_fresh"] == "stale"
