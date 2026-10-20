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
| 海洋覆盖率 | ~70%（陆地 ~30%；构建实测陆地 29.9% = 目标 27.8% + overlay 净增陆） | |
| 洛夫数 h₂ | 0.40 | 固体形变 |
| 洛夫数 k₂ | 0.20 | 引力势形变 |
| 潮汐耗散因子 Q | ≈445 | 见下方选值依据（k₂/Q = 4.5×10⁻⁴） |

> **洛夫数与 Q 的选值依据**：潮汐加热与轨道阻尼只取决于 k₂ 与 Q 的比值。轨道推算确定的
> 耗散强度为地球参考值的 0.45 倍（design-notes/0014），这一比例在洛夫数与 Q 之间对数平分：
> Nacrea 的本体比地球略刚，k₂ = 0.20、h₂ = 0.40（地球实测 k₂≈0.30、h₂≈0.61，h₂/k₂ 保持
> 约 2；岩质行星的 k₂ 常见 0.15–0.35）；Q 约 445，落在岩质固态天体的文献带 100–500 内：
>
> | 天体 | Q | 备注 |
> |------|---|---------|
> | 地球（整体有效） | ~12 | **浅海边缘海共振主导**：~70% 耗散发生在 <200 m 陆架 |
> | 地球（固体潮本体） | ~280 | 自由振荡约束 |
> | 火星 | ~80–100 | Phobos 轨道衰减约束 |
> | 月球 | ~200–500 | 干燥刚性、无海洋 |
> | 木卫一 Io | 36–100 | 近熔融 |
> | **Nacrea（本设定）** | **≈445** | 见下 |
>
> Nacrea 虽有 ~70% 海洋，但其潮汐周期 3.138 d 对应开阔大洋潮波长 ~5×10⁴ km
> （√(gH)·P，H=4 km），主要洋盆宽仅 1–3×10³ km，远小于半波长，所以**洋盆远离共振**，
> 海洋潮汐耗散弱，有效 Q 由固体本体（含软流圈）的耗散主导，对应 Q ~280–500 档。
> 大陆边缘以窄陆架为主，宽浅陆架海的耗散只起次要作用；少数地方陆架较宽时，陆架耗散会
> 使有效 Q 略有下降，取 **Q≈445** 在文献带内为此留有余地。
> 自洽性：τ_e ≈ {{ (entities.satellite_nacrea.tidal_e_damping_timescale_yr / 1e6) | round1 }} Myr ≪ 系统年龄 5.9 Gyr（受迫偏心率平衡论证不变）；潮汐锁定
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
| 有效倾角 / 极圈 | {{ entities.satellite_nacrea.axial_tilt_deg | round0 }}° / ±{{ entities.satellite_nacrea.polar_circle_latitude_deg | round0 }}° | 恒星季节角长期时权均（19.85°，静息期带 16.0–23.5°、潮汐期带 12.1–26.2°，主谱峰 ~8.39 地球年「季幅潮」）；极点极昼极夜各 ~{{ entities.satellite_nacrea.polar_day_at_pole_days | round1 }} 天 |
| 浅水重力波速 | 202.8 m/s | √(gH) |

### 放射性生热独立预算

类地化学库存模型（McDonough、Šrámek、Wipperfurth 2020 全文表 3：地球当代
硅酸盐平均 U=20 ppb、Th=75.4 ppb、K=280 ppm，另计微量 Rb、Sm；热系数已扣
中微子能量）按 Nacrea 硅酸盐份额 67.5%（4.84×10²⁴ kg，类地内部分层假设）
回推形成库存再演化到系统年龄。**5.9 Gyr 当代生热 ≈ 18.8 TW，折合全球面积
0.032 W/m²**（全球面积 5.84×10¹⁴ m²，1 W/m² = 584 TW）。这是内部释放功率，
不含潮汐、吸积、分异与长期冷却，也与潮汐热（design-notes/0009 §3）分账。

| 自形成以来年龄 | 生热 (TW) | 折合 (W/m²) |
|---:|---:|---:|
| 0.5 Gyr | 94.0 | 0.161 |
| 2.5 Gyr | 40.8 | 0.070 |
| 4.5 Gyr | 24.2 | 0.041 |
| 5.9 Gyr | 18.8 | 0.0323 |

5.9 Gyr 时 ²³²Th 约占 48%、²³⁸U 39%、⁴⁰K 12%。较宽创作情景（初始库存
×0.5–2、硅酸盐份额 0.60–0.80）为 8–44 TW（0.014–0.075 W/m²），不是测量
误差带。最初数 Myr 的 ²⁶Al/⁶⁰Fe 短寿命核素另算（形成早期功率可高数千倍），
不据此延长到 0.5 Gyr。参照：地球类地模型当代 19.9±3.0 TW（0.039 W/m²）、
观测总地表散热 47±2 TW（0.092 W/m²，含长期冷却）——不能把总散热全当核素
产热。恒星 [Fe/H]=−0.19 不唯一确定 U/Th/K 含量，上表按类地比例假设。

---
