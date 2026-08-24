"""天空现象几何原语（harness.md §6 修订 / harness-p2-queries.md）。

潮汐锁定卫星上母行星/卫星的视位置、视直径、凌掩分类等纯几何。全部**纯函数、
实体参数化、无 RNG**，可单测——与 `stellar_physics.py` 同风格，是所有世界的
「共享物理」。

**关键原则**：这里是「原语」而非「命名查询」。具体拷问答案（「巨眼崇拜是否成立」
= `sky_position(...).altitude_deg > 0 且 angular_size_deg > 阈值`）由调用方组合，
不为每个拷问写一个函数。禁止 `aegis_`/`boreal_` 这类世界绑定命名。
"""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel

from dreamulator.query_registry import query

__all__ = [
    "AU_KM",
    "SkyPosition",
    "angular_size",
    "apparent_illuminance",
    "hill_radius",
    "sky_position",
    "tidal_amplitude",
    "transit_classification",
]

# 天文单位（km）。
AU_KM = 149_597_870.7

# 潮汐锁定卫星上，母行星固定在天空的「正下点」——约定本初子午线（lon=0, lat=0）
# 正对母行星。轴向倾角会把正下点的纬度按季节在 ±tilt 摆动，这里取「平均位置」
# （lat=0）；tilt 的季节修正留待后续原语（P2e）。
_SUB_PLANET_LON_DEG = 0.0
_SUB_PLANET_LAT_DEG = 0.0


class AngularSizeParams(BaseModel):
    """``angular_size`` 的入参。"""

    radius_km: float
    distance_km: float


@query(
    name="angular_size",
    description="天体视直径（角直径，度）：θ = 2·arctan(R / Δ)。纯几何，与具体世界无关",
    dimension="sky",
    params_model=AngularSizeParams,
)
def angular_size(radius_km: float, distance_km: float) -> float:
    """天体视直径（角直径，度）：θ = 2·arctan(R / Δ)。

    纯几何，与具体世界无关。锚定值：Aegis = ``angular_size(71355, 739013) ≈ 11.0°``。
    """
    return math.degrees(2.0 * math.atan(radius_km / distance_km))


def _angular_distance_deg(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """球面两点角距（度），haversine 公式。"""
    lon1, lat1, lon2, lat2 = map(math.radians, (lon1, lat1, lon2, lat2))
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = math.sin(dlat / 2.0) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2.0) ** 2
    return math.degrees(2.0 * math.asin(math.sqrt(a)))


def _bearing_deg(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """从点 1 到点 2 的方位角（度，0 = 北，顺时针）。"""
    lon1, lat1, lon2, lat2 = map(math.radians, (lon1, lat1, lon2, lat2))
    dlon = lon2 - lon1
    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


class SkyPosition(BaseModel):
    """母行星在潮汐锁定卫星地表某点的天空位置。"""

    altitude_deg: float
    azimuth_deg: float
    angular_size_deg: float
    visible: bool


class SkyPositionParams(BaseModel):
    """``sky_position`` 的入参（``entities`` 由分发器注入）。"""

    observer_id: str
    target_id: str
    lon_deg: float
    lat_deg: float


@query(
    name="sky_position",
    description="母行星在潮汐锁定卫星地表某点的天空位置（仰角/方位/视直径）",
    dimension="sky",
    context="entities",
    params_model=SkyPositionParams,
    result_model=SkyPosition,
)
def sky_position(
    entities: dict[str, dict[str, Any]],
    observer_id: str,
    target_id: str,
    lon_deg: float,
    lat_deg: float,
) -> SkyPosition:
    """母行星（target）在潮汐锁定卫星（observer）地表 (lon, lat) 的天空位置。

    observer 必须潮汐锁定到 target（母行星固定在天空）。母行星固定在「正下点」
    （lon=0, lat=0），地表点看它的仰角 = 90° − 角距；视直径用轨道距离。锚定值：
    ``sky_position(entities, "satellite_nacrea", "planet_aegis", 0.5, -0.8).altitude_deg ≈ 89``。
    """
    observer = entities[observer_id]
    target = entities[target_id]

    distance_km = float(observer["semi_major_axis_au"]) * AU_KM
    size = angular_size(float(target["radius_km"]), distance_km)

    angular_distance = _angular_distance_deg(
        lon_deg, lat_deg, _SUB_PLANET_LON_DEG, _SUB_PLANET_LAT_DEG
    )
    altitude = 90.0 - angular_distance

    return SkyPosition(
        altitude_deg=altitude,
        azimuth_deg=_bearing_deg(lon_deg, lat_deg, _SUB_PLANET_LON_DEG, _SUB_PLANET_LAT_DEG),
        angular_size_deg=size,
        visible=altitude > 0.0,
    )


class TransitParams(BaseModel):
    """``transit_classification`` 的入参（``entities`` 由分发器注入）。"""

    observer_id: str
    sat_id: str


@query(
    name="transit_classification",
    description="卫星相对观察者（同绕一行星）是「凌」（盘面前）还是「掩」（盘面后）",
    dimension="sky",
    context="entities",
    params_model=TransitParams,
)
def transit_classification(
    entities: dict[str, dict[str, Any]],
    observer_id: str,
    sat_id: str,
) -> Literal["transit", "occultation", "neither"]:
    """卫星（sat）相对观察者（observer，同绕一行星）是「凌」还是「掩」。

    轨道半径在观察者内侧（sat_r < observer_r）→ 凌（盘面前方，transit）；
    外侧（sat_r > observer_r）→ 掩（盘面后方，occultation）。不同母行星 → neither。
    """
    observer = entities[observer_id]
    sat = entities[sat_id]
    if observer.get("parent_id") != sat.get("parent_id"):
        return "neither"

    observer_r = float(observer["semi_major_axis_au"])
    sat_r = float(sat["semi_major_axis_au"])
    if sat_r < observer_r:
        return "transit"
    if sat_r > observer_r:
        return "occultation"
    return "neither"


# ---------------------------------------------------------------------------
# 次要原语（P2e）：Hill 球 / 视亮度 / 潮汐
# ---------------------------------------------------------------------------


class HillRadiusParams(BaseModel):
    m_parent_kg: float
    m_sat_kg: float
    a_m: float


@query(
    name="hill_radius",
    description="Hill 球半径（m）：R_H ≈ a·(m_sat / 3·m_parent)^(1/3)",
    dimension="sky",
    params_model=HillRadiusParams,
)
def hill_radius(m_parent_kg: float, m_sat_kg: float, a_m: float) -> float:
    """Hill 球半径（m）。锚定值：月球 ≈ 6.15e7 m（``hill_radius(5.972e24, 7.35e22, 3.844e8)``）。"""
    return a_m * math.pow(m_sat_kg / (3.0 * m_parent_kg), 1.0 / 3.0)


class ApparentIlluminanceParams(BaseModel):
    observer_id: str
    target_id: str


@query(
    name="apparent_illuminance",
    description="满相反射光照度（W/m²）：F = F_star·p·(R/Δ)²（Lambert 相位 α=0）",
    dimension="sky",
    context="entities",
    params_model=ApparentIlluminanceParams,
)
def apparent_illuminance(
    entities: dict[str, dict[str, Any]], observer_id: str, target_id: str
) -> float:
    """满相反射光照度（W/m²），用于「天体亮度 / 光污染」拷问。

    锚定值：Aegis 满相 ≈ 1.91 W/m²（见 sky_phenomena.md）。
    """
    observer = entities[observer_id]
    target = entities[target_id]
    flux = float(observer["instellation_w_m2"])
    p = (2.0 / 3.0) * float(target["albedo"])  # 几何反照率（Lambert 假设）
    r = float(target["radius_km"])
    d = float(observer["semi_major_axis_au"]) * AU_KM
    return flux * p * (r / d) ** 2


class TidalAmplitudeParams(BaseModel):
    m_parent_kg: float
    m_sat_kg: float
    a_m: float
    r_sat_m: float


@query(
    name="tidal_amplitude",
    description="卫星平衡潮差（m）：h ≈ (3/2)·(M_parent/m_sat)·(r_sat/a)³·r_sat",
    dimension="sky",
    params_model=TidalAmplitudeParams,
)
def tidal_amplitude(m_parent_kg: float, m_sat_kg: float, a_m: float, r_sat_m: float) -> float:
    """卫星平衡潮差（m）——潮汐锁定卫星的静态潮汐隆起高度（Murray & Dermott 1999）。"""
    return 1.5 * (m_parent_kg / m_sat_kg) * (r_sat_m / a_m) ** 3 * r_sat_m
