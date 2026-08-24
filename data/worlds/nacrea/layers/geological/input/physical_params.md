---
title: "Nacrea 物理参数"
type: physical
tags: [mass, radius, gravity, love-numbers]
---

# 卫星 Nacrea — 物理参数

### 自变量

| 参数 | 值 | 备注 |
|------|-----|------|
| 质量 | {{ "%.2f" | format(entities.satellite_nacrea.mass_earth) }} M⊕ | |
| 半径 | {{ entities.satellite_nacrea.radius_earth | round2 }} R⊕（{{ entities.satellite_nacrea.radius_km | round0 }} km） | |
| 潮汐状态 | 被巨行星 Aegis 潮汐锁定 | 公转周期 = 自转周期 |
| 绕巨行星公转周期 | {{ entities.satellite_nacrea.period_days | hours | round0 }} 小时 | |
| 海洋平均深度 | 4000 m | |
| 海洋覆盖率 | 72%（陆地 28%） | |
| 洛夫数 h₂ | 0.6 | 固体形变 |
| 洛夫数 k₂ | 0.3 | 引力势形变 |
| 潮汐耗散因子 Q | 100 | 见下方选值依据 |

> **Q=100 选值依据**：Q 是潮汐加热参数中**唯一缺乏实测锚定的自由参数**——洛夫数 h₂=0.6、
> k₂=0.3 均直接取地球实测值（h₂≈0.61、k₂≈0.30），而 Q 的量级反映耗散效率（Q=100 意为
> 每周期耗散 ~1% 潮汐能），文献跨 1–2 个数量级：
>
> | 天体 | Q | 潮汐热流 |
> |------|---|---------|
> | 地球（固体潮） | 10–280（海洋耗散主导，量级争议大） | 0.09 W/m²（放射性） |
> | 火星 | ~80–100（Phobos 轨道衰减约束） | — |
> | 木卫二 Europa | ~100 | 冰壳活动 |
> | 木卫一 Io | 36–100（近熔融） | 2.4 W/m² |
> | **Nacrea（本设定）** | **100** | **0.27 W/m²** |
>
> Q=100 对应"存在海洋与软流圈的活跃地质体"，介于刚性火星与近熔融 Io 之间。Q 的 ±50%
> 不确定会线性传导到潮汐加热（Ė ∝ k₂/Q），敏感性见 tidal_effects.md §Q 敏感性。

### 因变量

| 参数 | 值 | 推导依据 |
|------|-----|---------|
| 表面重力 g | {{ entities.satellite_nacrea.gravity_m_s2 | round2 }} m/s²（≈{{ (entities.satellite_nacrea.gravity_m_s2 / 9.80665) | round2 }}g） | G·{{ "%.2f" | format(entities.satellite_nacrea.mass_earth) }}M⊕ / ({{ entities.satellite_nacrea.radius_earth | round2 }}R⊕)² |
| 轨道半长轴 | 740,332 km（≈10.35 R_J） | 开普勒第三定律 |
| 系统稳定性 | 0.2 R_H 处 | 长期绝对稳定区 |
| 昼夜交替周期（太阳日） | **{{ entities.satellite_nacrea.solar_day_days | round2 }} 地球日（{{ entities.satellite_nacrea.solar_day_days | hours | round1 }} 小时）** | 恒星自转 {{ entities.satellite_nacrea.period_days | hours | round0 }}h（=绕 Aegis 公转）+ Aegis 公转 {{ entities.planet_aegis.period_days | round0 }} 天 → 1/(1/{{ entities.satellite_nacrea.rotation_period_days }} − 1/{{ entities.planet_aegis.period_days | round0 }}) |
| 年（季节周期） | **{{ entities.planet_aegis.period_days | round0 }} 地球日** | = Aegis 绕恒星公转周期（{{ entities.planet_aegis.semi_major_axis_au }} AU）；一年 = {{ entities.satellite_nacrea.days_per_year | round1 }} 个太阳日 |
| 有效倾角 / 极圈 | {{ entities.satellite_nacrea.axial_tilt_deg | round0 }}° / ±{{ entities.satellite_nacrea.polar_circle_latitude_deg | round0 }}° | 轨道倾角即黄赤交角；极点极昼极夜各 ~{{ entities.satellite_nacrea.polar_day_at_pole_days | round1 }} 天 |
| 浅水重力波速 | 202.8 m/s | √(gH) |

---
