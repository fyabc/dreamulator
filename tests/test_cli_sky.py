"""Tests for the `dreamulator sky` CLI — table and JSON modes."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
import typer
import yaml
from typer.testing import CliRunner

from dreamulator.cli_sky import sky

# Registered like cli.py does: a bare command on the app, no group.
_test_app = typer.Typer()
_test_app.command()(sky)

if TYPE_CHECKING:
    from pathlib import Path

# Rich reads COLUMNS; the default 80 mangles long body ids in the table.
runner = CliRunner(env={"COLUMNS": "180"})

# A minimal two-level catalog (star → planet → locked satellite) with full
# elements: enough for the query and the target_body_id default.
_CATALOG: dict = {
    "stars": [
        {
            "id": "star_sol",
            "name": "Sol",
            "luminosity_sol": 1.0,
            "radius_sol": 1.0,
            "position": {"x": 0.0, "y": 0.0, "z": 0.0},
        }
    ],
    "orbits": [
        {
            "body_id": "planet_terra",
            "parent_id": "star_sol",
            "semi_major_axis_au": 1.0,
            "eccentricity": 0.0167,
            "inclination_deg": 0.0,
            "longitude_ascending_node_deg": 0.0,
            "argument_of_periapsis_deg": 0.0,
            "mean_anomaly_epoch_deg": 0.0,
            "epoch_year": 0.0,
        },
        {
            "body_id": "satellite_luna",
            "parent_id": "planet_terra",
            "semi_major_axis_au": 0.00257,
            "eccentricity": 0.0549,
            "inclination_deg": 5.145,
            "longitude_ascending_node_deg": 125.08,
            "argument_of_periapsis_deg": 318.15,
            "mean_anomaly_epoch_deg": 135.27,
            "epoch_year": 0.0,
        },
    ],
    "bodies": [
        {
            "id": "planet_terra",
            "name": "Terra",
            "body_type": "planet",
            "parent_id": "star_sol",
            "orbit": {"semi_major_axis_au": 1.0, "period_days": 365.25},
            "physical": {"radius_km": 6371.0, "albedo": 0.3},
            "derived": {"tidally_locked": False},
        },
        {
            "id": "satellite_luna",
            "name": "Luna",
            "body_type": "natural_satellite",
            "parent_id": "planet_terra",
            "orbit": {"semi_major_axis_au": 0.00257, "period_days": 27.3},
            "physical": {"radius_km": 1737.0, "rotation_period_days": 27.3, "axial_tilt_deg": 0.0},
            "derived": {"tidally_locked": True, "solar_day_days": 29.5},
        },
    ],
    "target_body_id": "satellite_luna",
}


def _make_world(root: Path) -> Path:
    world = root / "cli-world"
    (world / "layers" / "astronomy" / "input").mkdir(parents=True)
    (world / "layers" / "astronomy" / "derived").mkdir(parents=True)
    with (world / "layers" / "astronomy" / "input" / "stellar.yaml").open(
        "w", encoding="utf-8"
    ) as fh:
        yaml.safe_dump({"stars": []}, fh)
    with (world / "layers" / "astronomy" / "derived" / "system_catalog.yaml").open(
        "w", encoding="utf-8"
    ) as fh:
        yaml.safe_dump(_CATALOG, fh, allow_unicode=True)
    return root


def test_sky_show_table(tmp_path: Path) -> None:
    data_root = _make_world(tmp_path)
    result = runner.invoke(
        _test_app,
        ["cli-world", "--from", "satellite_luna", "--data-dir", str(data_root)],
    )
    assert result.exit_code == 0, result.output
    assert "Luna（satellite_luna）" in result.output  # observer header: name + id
    assert "Terra" in result.output  # a target row shows the catalog name
    assert "Sol" in result.output
    assert "方位" in result.output  # the legend line explains the columns
    assert "永不落下" in result.output  # the locked parent's rise/set state


def test_angular_size_stepped_units() -> None:
    # Degree decimals swallowed the dwarf planets (0.000); the table steps
    # ° → arcmin → arcsec at the thresholds planetaria use.
    from dreamulator.cli_sky import _angular_size_text

    assert _angular_size_text(11.4025) == "11.40°"
    assert _angular_size_text(0.892) == "0.89°"  # Sun-Moon scale stays degrees
    assert _angular_size_text(0.08835) == "5.3′"  # Cadence
    assert _angular_size_text(0.00066) == "2.4″"  # dwarf planets
    assert _angular_size_text(4e-05) == "0.1″"  # never rounds to nothing


def test_encoding_guard() -> None:
    # GBK-family consoles render every glyph the table uses; single-byte
    # Western code pages cannot and are rejected with an ASCII error.
    from dreamulator.cli_sky import _encoding_ok

    assert _encoding_ok("utf-8")
    assert _encoding_ok("gbk")
    assert _encoding_ok("cp936")
    assert not _encoding_ok("cp1252")
    assert not _encoding_ok("latin-1")
    assert _encoding_ok(None)


def test_sky_show_json(tmp_path: Path) -> None:
    data_root = _make_world(tmp_path)
    result = runner.invoke(
        _test_app,
        [
            "cli-world",
            "--from",
            "satellite_luna",
            "--at",
            "10.0",
            "--targets",
            "planet_terra",
            "--data-dir",
            str(data_root),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["observer_id"] == "satellite_luna"
    assert payload["at_days"] == 10.0
    assert payload["spin_source"] == "locked_to_parent"
    (row,) = payload["targets"]
    assert row["body_id"] == "planet_terra"
    assert row["altitude_deg"] == pytest.approx(90.0)  # the locked parent at zenith
    assert row["rise_state"] == "never_sets"


def test_sky_show_unknown_world_exits_1(tmp_path: Path) -> None:
    result = runner.invoke(_test_app, ["no-such-world", "--data-dir", str(tmp_path)])
    assert result.exit_code == 1
    assert "not found" in result.output


def test_sky_show_unbuilt_world_exits_1(tmp_path: Path) -> None:
    world = tmp_path / "empty-world"
    (world / "layers" / "astronomy" / "input").mkdir(parents=True)
    result = runner.invoke(_test_app, ["empty-world", "--data-dir", str(tmp_path)])
    assert result.exit_code == 1
    assert "build" in result.output
