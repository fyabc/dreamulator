"""Tests for the export clouds YAML configuration."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from dreamulator.media.cloud_config import CloudRenderConfig

if TYPE_CHECKING:
    from pathlib import Path


def test_defaults() -> None:
    cfg = CloudRenderConfig()
    assert cfg.grid == "8192x4096"
    assert cfg.seed == 7
    assert cfg.cyclones.enabled is False
    assert cfg.cyclones.tropical_per_hemisphere == 1
    assert cfg.atmosphere.enabled is True
    assert cfg.atmosphere.cloud_altitude_km == 4.0
    assert cfg.atmosphere.exposure == "white_balance"
    assert cfg.atmosphere.sun_glint is True
    assert cfg.atmosphere.water_roughness == 0.08
    assert cfg.atmosphere.multiple_scattering is True


def test_yaml_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "cloud.yaml"
    path.write_text(
        "grid: 2048x1024\n"
        "seed: 11\n"
        "globe_res: 900\n"
        "cover_scale: 0.8\n"
        "cyclones:\n"
        "  enabled: true\n"
        "  seed: 5\n"
        "  tropical_per_hemisphere: 1\n"
        "  extratropical_per_hemisphere: 2\n"
        "  extratropical_scale: 1.5\n"
        "  tracks:\n"
        "    - lat_deg: 10\n"
        "      lon_deg: 20\n"
        "      outer_radius_km: 2000\n"
        "atmosphere:\n"
        "  enabled: true\n"
        "  exposure: physical\n"
        "  cloud_altitude_km: 6\n"
        "  star_temperature_k: 4365\n"
        "  sun_glint: false\n"
        "  water_roughness: 0.05\n"
        "  multiple_scattering: false\n",
        encoding="utf-8",
    )
    cfg = CloudRenderConfig.from_yaml(path)
    assert cfg.grid == "2048x1024"
    assert cfg.seed == 11
    assert cfg.globe_res == 900
    assert cfg.cover_scale == 0.8
    assert cfg.cyclones.enabled is True
    assert cfg.cyclones.seed == 5
    assert cfg.cyclones.extratropical_per_hemisphere == 2
    assert cfg.cyclones.extratropical_scale == 1.5
    assert len(cfg.cyclones.tracks) == 1
    assert cfg.cyclones.tracks[0].outer_radius_km == 2000.0
    assert cfg.atmosphere.exposure == "physical"
    assert cfg.atmosphere.cloud_altitude_km == 6.0
    assert cfg.atmosphere.star_temperature_k == 4365.0
    assert cfg.atmosphere.sun_glint is False
    assert cfg.atmosphere.water_roughness == 0.05
    assert cfg.atmosphere.multiple_scattering is False


def test_unknown_key_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("grid: 1024x512\nbogus: 1\n", encoding="utf-8")
    with pytest.raises(ValueError):
        CloudRenderConfig.from_yaml(path)
