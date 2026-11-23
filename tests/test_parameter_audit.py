"""Tests for the duplicate-parameter audit."""

from __future__ import annotations

from typing import TYPE_CHECKING

import yaml

from dreamulator.parameter_audit import audit_body_field_duplicates
from dreamulator.world_manager import WorldManager

if TYPE_CHECKING:
    from pathlib import Path


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _world_with_duplicates(tmp_path: Path) -> Path:
    world = tmp_path / "w"
    _write(
        world / "layers/astronomy/input/stellar.yaml",
        yaml.safe_dump(
            {
                "bodies": [
                    {
                        "id": "planet_x",
                        "mass_earth": 1.0,
                        "radius_km": 6371.0,
                        "rotation_period_days": 5.56,
                        "axial_tilt_deg": 0.0,
                        "albedo": 0.3,
                    }
                ]
            }
        ),
    )
    _write(
        world / "layers/geological/input/planets.yaml",
        yaml.safe_dump(
            {
                "planets": [
                    {
                        "id": "planet_x",
                        "mass": 1.0,
                        "radius": 1.0,
                        "rotation_period_days": 5.56,
                        "axial_tilt_deg": 0.0,
                        "albedo": 0.25,
                    }
                ]
            }
        ),
    )
    return world


def test_audit_reports_equal_and_divergent_duplicates(tmp_path: Path) -> None:
    messages = audit_body_field_duplicates(_world_with_duplicates(tmp_path))
    assert len(messages) == 5
    assert any("field albedo" in message and "different values" in message for message in messages)
    assert any(
        "field rotation_period_days" in message and "equal values" in message
        for message in messages
    )


def test_audit_is_empty_without_overlapping_bodies(tmp_path: Path) -> None:
    world = tmp_path / "w"
    _write(
        world / "layers/astronomy/input/stellar.yaml",
        yaml.safe_dump({"bodies": [{"id": "star_x", "mass_earth": 1.0, "radius_km": 6371.0}]}),
    )
    _write(
        world / "layers/geological/input/planets.yaml",
        yaml.safe_dump({"planets": [{"id": "planet_x", "mass": 1.0}]}),
    )
    assert audit_body_field_duplicates(world) == []


def test_audit_reports_missing_physicals_outside_planets(tmp_path: Path) -> None:
    world = tmp_path / "w"
    _write(
        world / "layers/astronomy/input/stellar.yaml",
        yaml.safe_dump({"bodies": [{"id": "dwarf_x"}]}),
    )
    _write(world / "layers/geological/input/planets.yaml", yaml.safe_dump({"planets": []}))
    messages = audit_body_field_duplicates(world)
    assert any(
        "dwarf_x" in message and "not defined in planets.yaml" in message for message in messages
    )


def test_validate_world_reports_duplicate_parameters(tmp_path: Path) -> None:
    manager = WorldManager(tmp_path / "worlds")
    manager.create_world("sample", seed=42)
    world = manager.world_dir("sample")
    stellar_path = world / "layers/astronomy/input/stellar.yaml"
    stellar = yaml.safe_load(stellar_path.read_text(encoding="utf-8")) or {}
    stellar.setdefault("bodies", []).append(
        {"id": "planet_terra", "mass_earth": 1.0, "albedo": 0.3}
    )
    stellar_path.write_text(yaml.safe_dump(stellar), encoding="utf-8")
    errors = manager.validate_world("sample")
    assert any("duplicates planets.yaml" in error for error in errors)
