"""Tests for dreamulator.engine.sky_geometry — sky phenomenon primitives.

Anchor values from nacrea's sky_phenomena.md (Aegis 11°, 永耀岛 89°, 外卫星掩).
"""

from __future__ import annotations

import math

import pytest

from dreamulator.engine.sky_geometry import (
    angular_size,
    apparent_illuminance,
    eclipse_season_fraction,
    geometric_albedo_from_bond,
    hill_radius,
    lambert_phase,
    reflected_apparent_magnitude,
    reflected_illuminance_w_m2,
    sky_position,
    stellar_apparent_magnitude,
    stellar_parallax_deg,
    tidal_amplitude,
    transit_classification,
    umbra_length_km,
    umbra_radius_at_distance_km,
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
        transit_classification(ENTITIES, "satellite_nacrea", "satellite_cadence") == "occultation"
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


# ---------------------------------------------------------------------------
# 方案 A 新增：视星等 / 本影 / 食季 / 视差（nacrea 当前参数锚定值）
# ---------------------------------------------------------------------------


def test_geometric_albedo_lambert() -> None:
    # Lambert 假设：p = 2/3 · A_Bond。Aegis A_Bond=0.343 → p≈0.2287。
    assert geometric_albedo_from_bond(0.343) == pytest.approx(0.2287, rel=1e-3)


def test_lambert_phase_half_moon() -> None:
    # Φ(π/2) = 1/π ≈ 0.318。
    assert lambert_phase(math.pi / 2.0) == pytest.approx(1.0 / math.pi, rel=1e-6)


def test_stellar_apparent_magnitude_ignis() -> None:
    # Ignis（L=0.0761, d=0.3536 AU）→ −26.20（sky_phenomena.md §1）。
    assert stellar_apparent_magnitude(0.0761, 0.3536) == pytest.approx(-26.20, abs=0.02)


def test_reflected_apparent_magnitude_aegis_full() -> None:
    # Aegis 满相 ≈ −19.6（sky_phenomena.md §2）。
    m_star = stellar_apparent_magnitude(0.0761, 0.3536)
    m = reflected_apparent_magnitude(
        star_magnitude=m_star,
        geometric_albedo=geometric_albedo_from_bond(0.343),
        radius_km=71355.0,
        observer_distance_km=724_054.0,
        star_body_distance_au=0.3536,
        star_observer_distance_au=0.3536,
    )
    assert m == pytest.approx(-19.57, abs=0.05)


def test_reflected_illuminance_aegis_full() -> None:
    # Aegis 满相照度 ≈ 1.84 W/m²（giant_brightness.md）。
    flux = 1361.0 * 0.0761 / 0.3536**2
    f = reflected_illuminance_w_m2(
        star_flux_w_m2=flux,
        geometric_albedo=geometric_albedo_from_bond(0.343),
        radius_km=71355.0,
        observer_distance_km=724_054.0,
    )
    assert f == pytest.approx(1.84, abs=0.02)


def test_umbra_length_aegis() -> None:
    # 本影锥 ≈ 11.9M km，远超珠母星轨道（sky_phenomena.md §5）。
    length = umbra_length_km(71355.0, 388_881.0, 52_897_807.0)
    assert length == pytest.approx(11_887_300.0, rel=1e-3)


def test_umbra_radius_at_orbit_aegis() -> None:
    # 本影在珠母星轨道处的半径 ≈ 67,009 km。
    length = umbra_length_km(71355.0, 388_881.0, 52_897_807.0)
    radius = umbra_radius_at_distance_km(71355.0, length, 724_054.0)
    assert radius == pytest.approx(67_009.0, rel=1e-3)


def test_eclipse_season_fraction_nacrea() -> None:
    # 食季窗口 ≈ 22.6%（sky_phenomena.md §5）。
    fraction = eclipse_season_fraction(math.radians(9.0), 67_009.0, 6817.0, 724_054.0)
    assert fraction == pytest.approx(0.226, abs=0.005)


def test_stellar_parallax_nacrea() -> None:
    # 视差摆动 ≈ ±0.78°（orbital_dynamics.md）。
    assert stellar_parallax_deg(724_054.0, 52_897_807.0) == pytest.approx(0.784, abs=0.01)
