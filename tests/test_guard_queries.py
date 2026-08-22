"""Tests for dreamulator.guard.queries — the query dispatcher (P2d)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import yaml

from dreamulator.guard.queries import run_query

if TYPE_CHECKING:
    from pathlib import Path


def _make_world(tmp_path: Path, catalog: dict) -> Path:
    world = tmp_path / "test-world"
    (world / "layers" / "astronomy" / "input").mkdir(parents=True, exist_ok=True)
    (world / "layers" / "astronomy" / "derived").mkdir(parents=True, exist_ok=True)
    with (world / "layers" / "astronomy" / "input" / "stellar.yaml").open(
        "w", encoding="utf-8"
    ) as f:
        yaml.safe_dump({"stars": []}, f)
    with (world / "layers" / "astronomy" / "derived" / "system_catalog.yaml").open(
        "w", encoding="utf-8"
    ) as f:
        yaml.safe_dump(catalog, f, allow_unicode=True)
    return world


def test_run_query_none_context(tmp_path: Path) -> None:
    world = tmp_path / "unused"
    world.mkdir()
    result = run_query(world, None, "angular_size", {"radius_km": 71355.2, "distance_km": 739013.0})
    assert result["value"] == pytest.approx(11.03, abs=0.05)


def test_run_query_entities_context(tmp_path: Path) -> None:
    catalog = {
        "stars": [],
        "bodies": [
            {"id": "planet_aegis", "physical": {"radius_km": 71355.2, "albedo": 0.343}},
            {
                "id": "satellite_gaiam",
                "parent_id": "planet_aegis",
                "orbit": {"semi_major_axis_au": 0.00494},
                "physical": {"radius_km": 6817.0},
                "derived": {"instellation_w_m2": 898.73},
            },
        ],
    }
    world = _make_world(tmp_path, catalog)
    result = run_query(
        world,
        None,
        "sky_position",
        {
            "observer_id": "satellite_gaiam",
            "target_id": "planet_aegis",
            "lon_deg": 0.5,
            "lat_deg": -0.8,
        },
    )
    assert result["altitude_deg"] == pytest.approx(89.0, abs=1.0)
    assert result["visible"] is True


def test_run_query_unknown_name(tmp_path: Path) -> None:
    world = tmp_path / "unused"
    world.mkdir()
    with pytest.raises(KeyError):
        run_query(world, None, "nope", {})
