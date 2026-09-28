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
| 潮汐耗散因子 Q | 300 | 见下方选值依据（k₂/Q = 1×10⁻³） |

> **Q=300 选值依据（「非共振大洋 + 窄陆架」组合）**：Q 是潮汐加热参数中唯一缺乏
> 实测锚定的自由参数——洛夫数 h₂=0.6、k₂=0.3 均直接取地球实测值（h₂≈0.61、
> k₂≈0.30）。岩质固态天体的 Q 文献带 100–500：
>
> | 天体 | Q | 备注 |
> |------|---|---------|
> | 地球（整体有效） | ~12 | **浅海边缘海共振主导**：~70% 耗散发生在 <200 m 陆架 |
> | 地球（固体潮本体） | ~280 | 自由振荡约束 |
> | 火星 | ~80–100 | Phobos 轨道衰减约束 |
> | 月球 | ~200–500 | 干燥刚性、无海洋 |
> | 木卫一 Io | 36–100 | 近熔融 |
> | **Nacrea（本设定）** | **300** | 见下 |
>
> Nacrea 虽有 72% 海洋，但其潮汐周期 3.147 d 对应开阔大洋潮波长 ~5×10⁴ km
> （√(gH)·P，H=4 km），主要洋盆宽仅 1–3×10³ km ≪ 半波长——**洋盆远离共振**；
> 且大陆边缘以窄陆架为主，地球式的主耗散区（宽浅陆架海）不发育。固态本体
> （含软流圈）耗散对应 Q ~280–500 档，取 **Q=300** = 岩质文献带中段。
> 自洽性：τ_e = 4.2 Myr ≪ 系统年龄 5.9 Gyr（受迫偏心率平衡论证不变）；潮汐锁定
> 史不变；Aegis 外迁叙事不受影响（外迁由 Aegis 自身 k₂/Q=7×10⁻⁸ 驱动）。
> 认识论类别 = 观测拟合参数（标定域 = 岩质潮汐 Q 文献带）；加热 ∝ 1/Q 线性，
> 敏感性见 tidal_effects.md §Q 敏感性。

### 因变量

| 参数 | 值 | 推导依据 |
|------|-----|---------|
| 表面重力 g | {{ entities.satellite_nacrea.gravity_m_s2 | round2 }} m/s²（≈{{ (entities.satellite_nacrea.gravity_m_s2 / 9.80665) | round2 }}g） | G·{{ "%.2f" | format(entities.satellite_nacrea.mass_earth) }}M⊕ / ({{ entities.satellite_nacrea.radius_earth | round2 }}R⊕)² |
| 轨道半长轴 | {{ sky.planet_aegis.distance_km | round0 }} km | 开普勒第三定律 |
| 系统稳定性 | 0.2 R_H 处 | 长期绝对稳定区 |
| 昼夜交替周期（太阳日） | **{{ entities.satellite_nacrea.solar_day_days | round2 }} 地球日（{{ entities.satellite_nacrea.solar_day_days | hours | round1 }} 小时）** | 恒星自转 {{ entities.satellite_nacrea.period_days | hours | round0 }}h（=绕 Aegis 公转）+ Aegis 公转 {{ entities.planet_aegis.period_days | round0 }} 天 → 1/(1/{{ entities.satellite_nacrea.rotation_period_days }} − 1/{{ entities.planet_aegis.period_days | round0 }}) |
| 年（季节周期） | **{{ entities.planet_aegis.period_days | round0 }} 地球日** | = Aegis 绕恒星公转周期（{{ entities.planet_aegis.semi_major_axis_au }} AU）；一年 = {{ entities.satellite_nacrea.days_per_year | round1 }} 个太阳日 |
| 有效倾角 / 极圈 | {{ entities.satellite_nacrea.axial_tilt_deg | round0 }}° / ±{{ entities.satellite_nacrea.polar_circle_latitude_deg | round0 }}° | 有效倾角 = 轨道面锥摆的长期均值（瞬时黄道倾角带 11.7–17.8°、~10 yr 周期，拉普拉斯面平衡物理见 design-notes/0009）；极点极昼极夜各 ~{{ entities.satellite_nacrea.polar_day_at_pole_days | round1 }} 天 |
| 浅水重力波速 | 202.8 m/s | √(gH) |

---
