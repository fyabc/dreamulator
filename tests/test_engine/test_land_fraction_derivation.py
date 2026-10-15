"""Sea-level calibration target derives from the canonical hydrosphere.

Unless ``terrain_config.yaml`` (or the planet's ``terrain:`` overrides) sets
``target_land_fraction`` explicitly, the geological engine takes it as
``1 - water_coverage`` from ``planets.yaml`` so the declarative hydrosphere
and the generated terrain can never drift apart.  An explicitly authored
value is kept; it only earns a consistency warning beyond a 20% divergence
from the canonical value (the manual-override + consistency-check pattern).
"""

from pathlib import Path

import pytest
import yaml

from dreamulator.engine.geological import GeologicalEngine
from dreamulator.models.layers import Layer


def _make_engine(world: Path) -> GeologicalEngine:
    return GeologicalEngine(
        world,
        seed=42,
        layer_input_dirs={
            Layer.ASTRONOMY.value: world / "layers" / "astronomy" / "input",
            Layer.GEOLOGICAL.value: world / "layers" / "geological" / "input",
        },
        layer_derived_dirs={},
        layer_output_dir=world / "layers" / "geological" / "derived",
        maps_output_dir=world / "maps",
    )


def _write_planets_yaml(world: Path, water_coverage: float | None = None) -> None:
    geo_dir = world / "layers" / "geological" / "input"
    geo_dir.mkdir(parents=True, exist_ok=True)
    planet: dict = {
        "id": "planet_test",
        "name": "planet_test",
        "orbits": "star_test",
        "mass": 1.0,
        "radius": 1.0,
        "rotation_period_days": 0.997,
        "axial_tilt_deg": 23.44,
        "albedo": 0.3,
    }
    if water_coverage is not None:
        planet["hydrosphere"] = {"water_coverage": water_coverage}
    with (geo_dir / "planets.yaml").open("w", encoding="utf-8") as f:
        yaml.dump({"planets": [planet]}, f, encoding="utf-8")


def _write_terrain_config(world: Path, data: dict) -> None:
    geo_dir = world / "layers" / "geological" / "input"
    geo_dir.mkdir(parents=True, exist_ok=True)
    with (geo_dir / "terrain_config.yaml").open("w", encoding="utf-8") as f:
        yaml.dump(data, f, encoding="utf-8")


def test_land_fraction_derives_from_water_coverage(tmp_path: Path) -> None:
    world = tmp_path / "world"
    _write_planets_yaml(world, water_coverage=0.55)

    cfg, warnings = _make_engine(world)._load_config({})

    assert cfg is not None
    assert cfg.target_land_fraction == pytest.approx(0.45)


def test_terrain_config_without_land_fraction_still_derives(tmp_path: Path) -> None:
    world = tmp_path / "world"
    _write_planets_yaml(world, water_coverage=0.55)
    _write_terrain_config(world, {"terrain": {"num_nodes": 50000}})

    cfg, _ = _make_engine(world)._load_config({})

    assert cfg is not None
    assert cfg.target_land_fraction == pytest.approx(0.45)


def test_authored_land_fraction_is_kept(tmp_path: Path) -> None:
    world = tmp_path / "world"
    _write_planets_yaml(world, water_coverage=0.722)
    _write_terrain_config(world, {"terrain": {"target_land_fraction": 0.278}})

    cfg, warnings = _make_engine(world)._load_config({})

    assert cfg is not None
    assert cfg.target_land_fraction == 0.278
    assert not any("target_land_fraction" in w for w in warnings)


def test_divergent_authored_land_fraction_warns_but_is_kept(tmp_path: Path) -> None:
    world = tmp_path / "world"
    _write_planets_yaml(world, water_coverage=0.55)
    _write_terrain_config(world, {"terrain": {"target_land_fraction": 0.2}})

    cfg, warnings = _make_engine(world)._load_config({})

    assert cfg is not None
    assert cfg.target_land_fraction == 0.2
    assert any("target_land_fraction" in w for w in warnings)


def test_no_hydrosphere_keeps_default(tmp_path: Path) -> None:
    world = tmp_path / "world"
    _write_planets_yaml(world, water_coverage=None)

    cfg, _ = _make_engine(world)._load_config({})

    assert cfg is not None
    assert cfg.target_land_fraction == 0.29
