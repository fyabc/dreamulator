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
    "SOLAR_RADIUS_KM",
    "SkyPosition",
    "angular_size",
    "apparent_illuminance",
    "eclipse_season_fraction",
    "geometric_albedo_from_bond",
    "hill_radius",
    "lambert_phase",
    "reflected_apparent_magnitude",
    "reflected_illuminance_w_m2",
    "sky_position",
    "stellar_apparent_magnitude",
    "stellar_parallax_deg",
    "tidal_amplitude",
    "transit_classification",
    "umbra_length_km",
    "umbra_radius_at_distance_km",
]

# 天文单位（km）。
AU_KM = 149_597_870.7

# 太阳半径（km）。
SOLAR_RADIUS_KM = 695_700.0

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
    p = geometric_albedo_from_bond(float(target["albedo"]))
    r = float(target["radius_km"])
    d = float(observer["semi_major_axis_au"]) * AU_KM
    return reflected_illuminance_w_m2(
        star_flux_w_m2=flux, geometric_albedo=p, radius_km=r, observer_distance_km=d
    )


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


# ---------------------------------------------------------------------------
# 光度 / 本影 / 食季 / 视差原语（方案 A：天象派生量进 derived catalog）
# ---------------------------------------------------------------------------
#
# 这些是「天空可视量」的纯计算：视星等、反照率、本影几何、食季、恒星视差。
# 与上面的「拷问原语」不同，它们直接服务 build_system_catalog 的 derived sky 段
# （模板渲染 sky_phenomena.md / giant_brightness.md 等），故不做 @query 注册
# （不是守护轴「有哪些查询」的索引项）。公式与锚定值均出自 nacrea 的
# sky_phenomena.md / giant_brightness.md / orbital_dynamics.md。


def geometric_albedo_from_bond(bond_albedo: float) -> float:
    """Lambert 球几何反照率 ``p = (2/3)·A_Bond``。

    视星等/照度计算需要几何反照率；Bond 反照率（``planets.yaml`` 设定值）按 Lambert
    散射假设换算（sky_phenomena.md 反照率约定）。真实后向散射天体（气态巨行星）的 p
    更高，满相亮度相应再亮 0.3–0.5 等，Lambert 值为保守基准。
    """
    return (2.0 / 3.0) * bond_albedo


def lambert_phase(phase_angle_rad: float) -> float:
    """Lambert 相位函数 ``Φ(α) = [sin α + (π−α)cos α] / π``（Φ(0)=1）。

    α=0 满相、α=π/2 半相（Φ=1/π≈0.318）、α=π 新相（Φ=0）。
    """
    return (
        math.sin(phase_angle_rad) + (math.pi - phase_angle_rad) * math.cos(phase_angle_rad)
    ) / math.pi


def stellar_apparent_magnitude(luminosity_sol: float, distance_au: float) -> float:
    """恒星视星等（以太阳在 1 AU 处 −26.74 等为基准）。

    ``m = −26.74 − 2.5·log10(L) + 5·log10(d_AU)``（sky_phenomena.md）。锚定值：
    Ignis（L=0.0761, d=0.3536 AU）→ ≈ −26.20。
    """
    return -26.74 - 2.5 * math.log10(luminosity_sol) + 5.0 * math.log10(distance_au)


def reflected_apparent_magnitude(
    *,
    star_magnitude: float,
    geometric_albedo: float,
    radius_km: float,
    observer_distance_km: float,
    star_body_distance_au: float,
    star_observer_distance_au: float,
    phase_angle_rad: float = 0.0,
) -> float:
    """反射光视星等（满相 α=0 默认）。

    ``m = m★ − 2.5·log10[ p·Φ(α)·(R/Δ)²·(D★/a)² ]``（sky_phenomena.md），其中 Δ 为
    天体–观测者距离、a 为天体–恒星距离、D★ 为恒星–观测者距离。锚定值：Aegis 满相
    ≈ −19.6（sky_phenomena.md §2）。
    """
    term = (
        geometric_albedo
        * lambert_phase(phase_angle_rad)
        * (radius_km / observer_distance_km) ** 2
        * (star_observer_distance_au / star_body_distance_au) ** 2
    )
    return star_magnitude - 2.5 * math.log10(term)


def reflected_illuminance_w_m2(
    *,
    star_flux_w_m2: float,
    geometric_albedo: float,
    radius_km: float,
    observer_distance_km: float,
    phase_angle_rad: float = 0.0,
) -> float:
    """满相反射光照度（W/m²，满相 α=0 默认）。

    ``F = F★·p·Φ(α)·(R/Δ)²``（giant_brightness.md）。锚定值：Aegis 满相 ≈ 1.9 W/m²。
    """
    return (
        star_flux_w_m2
        * geometric_albedo
        * lambert_phase(phase_angle_rad)
        * (radius_km / observer_distance_km) ** 2
    )


def umbra_length_km(
    radius_occulting_km: float, radius_star_km: float, star_distance_km: float
) -> float:
    """本影锥长度（km）：``L = R_occ·d★ / (R★ − R_occ)``（sky_phenomena.md §5）。

    掩蔽体半径须小于恒星半径（否则无本影锥）。
    """
    return radius_occulting_km * star_distance_km / (radius_star_km - radius_occulting_km)


def umbra_radius_at_distance_km(
    radius_occulting_km: float, umbra_length_km: float, distance_from_occulting_km: float
) -> float:
    """距掩蔽体 ``d`` 处的本影半径（km）：``r = R_occ·(L − d)/L``。

    ``d < L`` 时为正（本影内），``d > L`` 时本影已收束（仅半影）。
    """
    return radius_occulting_km * (umbra_length_km - distance_from_occulting_km) / umbra_length_km


def eclipse_season_fraction(
    inclination_rad: float,
    umbra_radius_at_orbit_km: float,
    satellite_radius_km: float,
    semi_major_axis_km: float,
) -> float:
    """每个升/降交点食季占全轨道周期的比例（0–1）。

    卫星最大黄纬 ``a·sin(i)``；食发生阈值 = 本影半径 + 卫星半径；
    ``fraction = arcsin(threshold / max_offset) / π``（sky_phenomena.md §5）。低倾角
    （max_offset ≤ threshold）→ 恒食，返回 1.0。
    """
    max_offset_km = semi_major_axis_km * math.sin(inclination_rad)
    threshold_km = umbra_radius_at_orbit_km + satellite_radius_km
    if max_offset_km <= threshold_km:
        return 1.0
    return math.asin(threshold_km / max_offset_km) / math.pi


def stellar_parallax_deg(orbit_radius_km: float, star_distance_km: float) -> float:
    """卫星绕行星公转引起的恒星视差角（度，半幅）：``atan(a_moon / d★)``。

    orbital_dynamics.md「视差摆动」：绕行星公转半径对恒星方向的调制。
    """
    return math.degrees(math.atan(orbit_radius_km / star_distance_km))
