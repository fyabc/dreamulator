"""Tests for dreamulator.engine.sky_geometry — sky phenomenon primitives.

Anchor values from nacrea's sky_phenomena.md (10-07 route-1 canon: Aegis 11.3°,
Ignis −26.65, Aegis full −20.0 / 2.79 W/m², 永耀岛 89°, 外卫星掩).
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
        "semi_major_axis_au": 0.3648,
        "albedo": 0.343,
    },
    "satellite_nacrea": {
        "id": "satellite_nacrea",
        "parent_id": "planet_aegis",
        "semi_major_axis_au": 0.0048348095,
        "radius_km": 6817.0,
        "instellation_w_m2": 1254.97,
    },
    "satellite_cadence": {
        "id": "satellite_cadence",
        "parent_id": "planet_aegis",
        "semi_major_axis_au": 0.0078845945,
    },
    "satellite_vigil": {
        "id": "satellite_vigil",
        "parent_id": "planet_aegis",
        "semi_major_axis_au": 0.0116769194,
    },
}


def test_angular_size_aegis() -> None:
    assert angular_size(71355.2, 0.0048348095 * 149_597_870.7) == pytest.approx(11.27, abs=0.1)


def test_angular_size_ignis() -> None:
    assert angular_size(426116.0, 0.3648 * 149_597_870.7) == pytest.approx(0.89, abs=0.05)


def test_sky_position_yongyao_island() -> None:
    """金丝雀：永耀岛（lon 0.4°, lat −0.6°）看 Aegis 仰角 ≈ 89°（sky_phenomena.md）。"""
    pos = sky_position(ENTITIES, "satellite_nacrea", "planet_aegis", 0.4, -0.6)
    assert pos.altitude_deg == pytest.approx(89.3, abs=1.0)
    assert pos.angular_size_deg == pytest.approx(11.27, abs=0.1)
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
    # sky_phenomena.md：Aegis 满相照度 2.79 W/m²（引擎目录 illuminance_full_w_m2）。
    assert apparent_illuminance(ENTITIES, "satellite_nacrea", "planet_aegis") == pytest.approx(
        2.79, abs=0.05
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
    # Ignis（L=0.1227, d=0.3648 AU）→ −26.65（sky_phenomena.md §1）。
    assert stellar_apparent_magnitude(0.1227, 0.3648) == pytest.approx(-26.65, abs=0.02)


def test_reflected_apparent_magnitude_aegis_full() -> None:
    # Aegis 满相 ≈ −20.0（sky_phenomena.md §2；引擎目录 apparent_magnitude_full）。
    m_star = stellar_apparent_magnitude(0.1227, 0.3648)
    m = reflected_apparent_magnitude(
        star_magnitude=m_star,
        geometric_albedo=geometric_albedo_from_bond(0.343),
        radius_km=71355.0,
        observer_distance_km=723_277.0,
        star_body_distance_au=0.3648,
        star_observer_distance_au=0.3648,
    )
    assert m == pytest.approx(-20.02, abs=0.05)


def test_reflected_illuminance_aegis_full() -> None:
    # Aegis 满相照度 ≈ 2.79 W/m²（sky_phenomena.md §2 亮度参数表）。
    flux = 1361.0 * 0.1227 / 0.3648**2
    f = reflected_illuminance_w_m2(
        star_flux_w_m2=flux,
        geometric_albedo=geometric_albedo_from_bond(0.343),
        radius_km=71355.0,
        observer_distance_km=723_277.0,
    )
    assert f == pytest.approx(2.79, abs=0.02)


def test_umbra_length_aegis() -> None:
    # 本影锥 ≈ 10.98M km，远超珠母星轨道（sky_phenomena.md §5）。
    length = umbra_length_km(71355.0, 426_116.0, 54_573_303.0)
    assert length == pytest.approx(10_976_653.0, rel=1e-3)


def test_umbra_radius_at_orbit_aegis() -> None:
    # 本影在珠母星轨道处的半径 ≈ 66,653 km。
    length = umbra_length_km(71355.0, 426_116.0, 54_573_303.0)
    radius = umbra_radius_at_distance_km(71355.0, length, 723_277.0)
    assert radius == pytest.approx(66_653.0, rel=1e-3)


def test_eclipse_season_fraction_nacrea() -> None:
    # 食季窗口 ≈ 14.2%（sky_phenomena.md §5；历元倾角 13.64°，引擎目录 season_fraction）。
    fraction = eclipse_season_fraction(math.radians(13.637092), 66_653.0, 6817.0, 723_277.0)
    assert fraction == pytest.approx(0.142, abs=0.005)


def test_stellar_parallax_nacrea() -> None:
    # 视差摆动 ≈ ±0.76°（orbital_dynamics.md；引擎目录 parallax_deg）。
    assert stellar_parallax_deg(723_277.0, 54_573_303.0) == pytest.approx(0.76, abs=0.01)
