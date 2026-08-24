"""Tests for dreamulator.engine.sky_geometry — sky phenomenon primitives.

Anchor values from nacrea's sky_phenomena.md (Aegis 11°, 永耀岛 89°, 外卫星掩).
"""

from __future__ import annotations

import pytest

from dreamulator.engine.sky_geometry import (
    angular_size,
    apparent_illuminance,
    hill_radius,
    sky_position,
    tidal_amplitude,
    transit_classification,
)

# Minimal entity table (flattened system_catalog bodies) with nacrea anchor values.
ENTITIES: dict[str, dict[str, object]] = {
    "planet_aegis": {
        "id": "planet_aegis",
        "radius_km": 71355.2,
        "semi_major_axis_au": 0.2504,
        "albedo": 0.343,
    },
    "satellite_nacrea": {
        "id": "satellite_nacrea",
        "parent_id": "planet_aegis",
        "semi_major_axis_au": 0.00494,
        "radius_km": 6817.0,
        "instellation_w_m2": 898.73,
    },
    "satellite_cadence": {
        "id": "satellite_cadence",
        "parent_id": "planet_aegis",
        "semi_major_axis_au": 0.007842,
    },
    "satellite_vigil": {
        "id": "satellite_vigil",
        "parent_id": "planet_aegis",
        "semi_major_axis_au": 0.012448,
    },
}


def test_angular_size_aegis() -> None:
    assert angular_size(71355.2, 0.00494 * 149_597_870.7) == pytest.approx(11.0, abs=0.1)


def test_angular_size_ignis() -> None:
    assert angular_size(305222.0, 0.2504 * 149_597_870.7) == pytest.approx(0.93, abs=0.05)


def test_sky_position_yongyao_island() -> None:
    """金丝雀：永耀岛（lon 0.5°, lat −0.8°）看 Aegis 仰角 ≈ 89°（sky_phenomena.md）。"""
    pos = sky_position(ENTITIES, "satellite_nacrea", "planet_aegis", 0.5, -0.8)
    assert pos.altitude_deg == pytest.approx(89.0, abs=1.0)
    assert pos.angular_size_deg == pytest.approx(11.0, abs=0.1)
    assert pos.visible is True


def test_sky_position_sub_planet_overhead() -> None:
    """正下点（lon 0, lat 0）看母行星应近天顶。"""
    pos = sky_position(ENTITIES, "satellite_nacrea", "planet_aegis", 0.0, 0.0)
    assert pos.altitude_deg == pytest.approx(90.0, abs=0.01)


def test_sky_position_antipodal_not_visible() -> None:
    """反下点（lon 180, lat 0）看母行星应不可见（仰角 −90°）。"""
    pos = sky_position(ENTITIES, "satellite_nacrea", "planet_aegis", 180.0, 0.0)
    assert pos.visible is False
    assert pos.altitude_deg < 0.0


def test_transit_classification_outer_satellite_occulted() -> None:
    """外卫星（Cadence/Vigil）轨道半径更大 → 被掩（sky_phenomena.md §6 修正）。"""
    assert (
        transit_classification(ENTITIES, "satellite_nacrea", "satellite_cadence")
        == "occultation"
    )
    assert transit_classification(ENTITIES, "satellite_nacrea", "satellite_vigil") == "occultation"


def test_transit_classification_different_parent_neither() -> None:
    entities = {
        **ENTITIES,
        "planet_other": {"id": "planet_other"},
        "satellite_other": {
            "id": "satellite_other",
            "parent_id": "planet_other",
            "semi_major_axis_au": 0.003,
        },
    }
    assert transit_classification(entities, "satellite_nacrea", "satellite_other") == "neither"


# ---------------------------------------------------------------------------
# 次要原语（P2e）
# ---------------------------------------------------------------------------


def test_hill_radius_moon() -> None:
    # 月球 Hill 球半径 ≈ 61,500 km（已知参考值）。
    assert hill_radius(5.972e24, 7.35e22, 3.844e8) == pytest.approx(6.15e7, rel=0.05)


def test_apparent_illuminance_aegis_full_phase() -> None:
    # sky_phenomena.md / giant_brightness.md：Aegis 满相照度 1.91 W/m²。
    assert apparent_illuminance(ENTITIES, "satellite_nacrea", "planet_aegis") == pytest.approx(
        1.91, abs=0.05
    )


def test_tidal_amplitude_formula() -> None:
    # 平衡潮差（流体极限）：月球相对地球 ≈ 19.55 m（公式检查，非实际潮差）。
    h = tidal_amplitude(5.972e24, 7.35e22, 3.844e8, 1.7374e6)
    assert h == pytest.approx(19.55, rel=0.05)
