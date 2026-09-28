---
title: "潮汐效应"
type: tidal
tags: [tidal, heating, plate-tectonics, phase-drift, tidal-rhythm]
---

# 潮汐效应

> **2026-09-28 重构版**：偏心率历元 **{{ entities.satellite_nacrea.eccentricity }}**（认证轨迹
> 纪元平移态的受迫带冷谷快照；t₁ 见 stellar.yaml 纪元约定）；耗散因子取 `physical_params.md`（k₂=0.3, Q=300）→
> k₂/Q = **1×10⁻³**（「非共振大洋 + 窄陆架」组合，选值依据见 physical_params.md）。
> 加热系数 **F = 2.6×10⁴·e² W/m²**；泵浦归因为**双源**：恒星四极矩本底
> （~0.004–0.006）+ 双珠长期摄动（coef=1.35×10⁻³）。

## 自变量

无新增。本节所有因变量由 `physical_params.md`（质量、半径、洛夫数）与 `stellar.yaml`
（轨道根数、偏心率）既有参数推导，关键值列于下表：

| 参数 | 值 | 来源 |
|------|-----|------|
| 中心天体质量 M_Aegis | 508.5 M⊕ = 3.037×10²⁷ kg | stellar.yaml |
| 卫星质量 M_Nacrea | 1.20 M⊕ = 7.166×10²⁴ kg | physical_params.md |
| 卫星半径 R | 6817 km | physical_params.md |
| 轨道半长轴 a | {{ (entities.satellite_nacrea.semi_major_axis_au * 149597870.7) | round0 }} km | stellar.yaml |
| 轨道周期 P | {{ entities.satellite_nacrea.period_days | round(3) }} d（{{ entities.satellite_nacrea.period_days | hours | round1 }} h），n = 2.311×10⁻⁵ rad/s | stellar.yaml |
| 偏心率 e | **{{ entities.satellite_nacrea.eccentricity }}**（历元值，受迫带冷谷快照） | stellar.yaml |
| 洛夫数 h₂ / k₂ | 0.6 / 0.3 | physical_params.md |
| 潮汐耗散因子 Q | 300（→ k₂/Q = 1×10⁻³） | physical_params.md |
| 表面重力 g | 10.28 m/s² | physical_params.md |
| 海洋平均深度 H | 4000 m（覆盖 72%） | physical_params.md |

## 因变量 — 潮汐势高度标度

$$Z = \frac{M_p}{M_m}\frac{R_m^4}{a^3} = 423.75 \times \frac{(6.817\times10^6)^4}{(7.24\times10^8)^3} = 2411\ \text{m}$$

`Z` 是后续所有潮汐形变量的长度标度（潮汐势 ÷ 表面重力）。

## 因变量 — 静态拉伸（与偏心率无关）

| 参数 | 值 | 推导依据 |
|------|-----|---------|
| 固体地壳隆起（子行星点） | **1447 m** | h₂·Z = 0.6 × 2411 |
| 固体全球峰谷差 | **2170 m** | 1.5·h₂·Z（子行星点 +1447 m，侧点 −723 m） |
| 海洋静态"水山" | **1688 m** | (1+k₂−h₂)·Z = 0.7 × 2411 |

> 静态隆起是**永久形变**——Nacrea 已被潮汐锁定，这个巨大隆起"冻结"在星球表面，
> **不产生潮汐加热**。地球固体潮仅 ~0.5 m，Nacrea 因 508.5 M⊕ 巨行星 + 近距轨道
> （10.36 R_p）而放大数千倍。真正的加热来自下节「动态潮」（∝ e）。

## 因变量 — 动态潮（∝ e，历元 e={{ entities.satellite_nacrea.eccentricity }}）

| 参数 | 值 | 推导依据 |
|------|-----|---------|
| 固体潮振幅（峰谷差） | **{{ (1447*3*entities.satellite_nacrea.eccentricity) | round(1) }} m（{{ (2*1447*3*entities.satellite_nacrea.eccentricity) | round(1) }} m）** | h₂·Z·3e = 1447 × {{ (3*entities.satellite_nacrea.eccentricity) | round(5) }} |
| 海洋平衡潮振幅（峰谷差） | **{{ (1688*3*entities.satellite_nacrea.eccentricity) | round(1) }} m（{{ (2*1688*3*entities.satellite_nacrea.eccentricity) | round(1) }} m）** | (1+k₂−h₂)·Z·3e = 1688 × {{ (3*entities.satellite_nacrea.eccentricity) | round(5) }} |
| 海洋固有周期 | 58.7 h | 2πR/√(gH) = 2π·6.817e6 / 202.8 |
| 共振放大系数 | **2.5×** | 1/(1−(58.7/75.5)²)，弱阻尼 |
| **共振潮差（峰谷差）** | **~{{ (2*1688*3*entities.satellite_nacrea.eccentricity*2.5) | round0 }} m** | 峰谷平衡潮 × 2.5 |

> **3e 因子的物理含义**：径向潮（bulge "呼吸"）幅度 ∝ r⁻³，r = a(1±e) → 分数变化 3e，
> 峰谷差 6e。表值是**历元冷谷的平衡潮理论上限**（完美流体球 + 全球共振）；受迫带
> 内潮差随 e 同步呼吸（e 达 max 0.0084 时 ~3.5×，即 ~210 m 上限——百年级「大潮纪元」）。
> 实际海岸潮差由地形决定：开阔大洋 4–12 m，普通海岸 10–25 m，喇叭形海湾共振放大
> 可达 40–80 m，封闭内海 <5 m（见 §潮汐对生态与文明的影响）。

## 因变量 — 潮汐加热与阻尼

| 参数 | 值 | 推导依据 |
|------|-----|---------|
| 潮汐加热功率 Ė | **{{ (1.52e19 * entities.satellite_nacrea.eccentricity * entities.satellite_nacrea.eccentricity / 1e12) | round0 }} TW**（历元冷谷） | Peale & Cassen (1978)：Ė = (21/2)(k₂/Q)(GM_p²R⁵/a⁶)·n·e² = 1.52×10¹⁹·e² |
| 潮汐热流密度 | **{{ (2.607e4 * entities.satellite_nacrea.eccentricity * entities.satellite_nacrea.eccentricity) | round(3) }} W/m²**（历元）；**受迫带均值 0.36 W/m²**（210 TW） | Ė / 4πR² |
| 对比 | 地球内热流 0.087 W/m²、Io 2.2–2.5（潮汐） | 带均值 = 4.1× 地球内热流 |
| 偏心率阻尼时标 τ_e | **{{ (entities.satellite_nacrea.tidal_e_damping_timescale_yr / 1e6) | round1 }} Myr** | (2/21)(Q/k₂)(M_m/M_p)(a/R)⁵(1/n) |

> 历元 {{ (1.52e19 * entities.satellite_nacrea.eccentricity * entities.satellite_nacrea.eccentricity / 1e12) | round0 }} TW ≈ {{ (1.52e19 * entities.satellite_nacrea.eccentricity * entities.satellite_nacrea.eccentricity / 4.7e13) | round(2) }}× 地球总热流（47 TW）——历元值是受迫带的**冷谷快照**；
> 带均值 0.36 W/m²（210 TW ≈ 4.5× 地球总热流）才是地质时间上的常态热源，
> 为 Nacrea 主导热源（~85%），驱动板块构造与碳-硅酸盐循环。瞬时极值
> 1.85 W/m²（0.79×Io）为百年级短暂尖峰，500-yr 平滑持续脉冲占空 0%
> （平滑 p95 仅 0.78）——「活跃但不至岩浆海」。τ_e = {{ (entities.satellite_nacrea.tidal_e_damping_timescale_yr / 1e6) | round1 }} Myr 意味着**泵浦一旦移除，e 在百万年尺度内归零**——
> 泵浦为**双源**：恒星四极矩本底（0.35 AU 强场，~0.004–0.006）+ 韵珠/守珠
> 长期摄动（coef=1.35×10⁻³，韵珠占 98.3%）；当代段认证带 rms 0.0037 / max 0.0084
> （详见 `satellite_architecture.md` 与 design-notes/0009 重构版 §3）。

## 因变量 — Q 敏感性

潮汐加热 Ė ∝ k₂/Q，而 Q 是唯一缺乏实测锚定的自由参数（洛夫数 k₂/h₂ 取地球实测值）。
下表展示受迫带固定（当代段 rms 0.0037）、Q 取不同值时潮汐加热的变化范围：

| Q | k₂/Q | 带均值热流 | 历元热流（e={{ entities.satellite_nacrea.eccentricity }}） | 相对地球内热流（带均值） | 地质状态 |
|---|------|---------|---------|---------------|---------|
| 150 | 2×10⁻³ | 0.72 W/m² | {{ (5.21e4 * entities.satellite_nacrea.eccentricity * entities.satellite_nacrea.eccentricity) | round(3) }} W/m² | 8.3× | 正典带内活跃端 |
| **300（本设定）** | **1×10⁻³** | **0.36 W/m²** | **{{ (2.607e4 * entities.satellite_nacrea.eccentricity * entities.satellite_nacrea.eccentricity) | round(3) }} W/m²** | **4.1×** | 活跃健康（正典带，板块构造旺盛） |
| 500（近月球刚性） | 6×10⁻⁴ | 0.22 W/m² | {{ (1.564e4 * entities.satellite_nacrea.eccentricity * entities.satellite_nacrea.eccentricity) | round(3) }} W/m² | 2.5× | 增强板块构造 |

> **结论**：Q 在 150–500 之间浮动时，带均值加热在 2.5–8× 地球内热流之间变化，
> 始终处于"活跃但不失控"区间（Io 的 2.2–2.5 W/m² 岩浆海量级之下）。Q=300 为
> 裁决值（「非共振大洋 + 窄陆架」组合，选值依据见 physical_params.md）；
> 加热 ∝ 1/Q 线性，文献带内取值属设定判断，可随未来约束折算。

## 因变量 — 大潮相位漂移

Nacrea 的潮汐周期与昼夜周期**并不完全同步**，二者相位差**随时间持续漂移**（此前文档
误认为"潮汐周期 = 昼夜周期 = 3.147 d 且相位可固定"，已更正）：

| 参数 | 值 | 推导依据 |
|------|-----|---------|
| 恒星日 | {{ entities.satellite_nacrea.period_days | round(3) }} d（{{ entities.satellite_nacrea.period_days | hours | round1 }} h） | = 自转周期 = 公转周期（潮汐锁定） |
| 太阳日（一昼夜） | **{{ (1/(1/entities.satellite_nacrea.period_days - 1/entities.planet_aegis.period_days)) | round(2) }} d（{{ (1/(1/entities.satellite_nacrea.period_days - 1/entities.planet_aegis.period_days)) | hours | round0 }} h）** | 1/(1/P_sid − 1/P_year)，自转与 Aegis 周年运动同向 |
| Aegis 公转周期（年） | {{ entities.planet_aegis.period_days | round(2) }} d | 开普勒第三定律，a={{ entities.planet_aegis.semi_major_axis_au }} AU |
| 相位漂移速率 | **11.5°/潮汐周期** | (P_sol − P_sid)/P_sol × 360° |
| 相位完整循环 | **{{ entities.planet_aegis.period_days | round0 }} d（一个 Aegis 年）** | 潮汐峰 vs 正午的拍频 |

**物理含义**：大潮时刻与"正午"的相位差**无法静态指定**——它在一个 Aegis 年内连续扫过
"正午 → 黄昏 → 午夜 → 黎明 → 正午"。`argument_of_periapsis` 只决定某个参考历元的初始相位，
不能"冻结"相位。

**后果**：潮间带在一个 Aegis 年内经历全部四种热环境（暴晒 / 温和 / 冻结 / 温和）并取平均，
无固定的"正午暴晒"或"午夜冻结"潮间带。这对生态是**利好**——潮间带热应力被时间平均稀释，
生态建模无需纠结相位自由度。

## 因变量 — 多体叠加潮汐规律

以动态潮汐加速度变化 Δa = 2GM_pR(1/r_min³ − 1/r_max³) 为代理，各天体的动态潮汐贡献：

| 天体 | 周期 | Δa (m/s²) | 相对主潮 |
|------|------|-----------|---------|
| **Aegis**（偏心率潮） | {{ entities.satellite_nacrea.period_days | round(3) }} d | 8.2×10⁻⁵ | 100% |
| 韵珠 Cadence（会合） | {{ (1/(1/entities.satellite_nacrea.period_days - 1/entities.satellite_cadence.period_days)) | round(2) }} d | 3.0×10⁻⁷ | 0.37% |
| 守珠 Vigil（会合） | {{ (1/(1/entities.satellite_nacrea.period_days - 1/entities.satellite_vigil.period_days)) | round(2) }} d | 1.5×10⁻⁹ | ~0% |
| Ignis（恒星） | {{ entities.planet_aegis.period_days | round0 }} d | 1.90×10⁻⁶ | 2.3% |

**整体潮汐规律**：

1. **主潮**：Aegis 偏心率潮，周期 3.147 d，占 ~97% 动态潮汐。
2. **极弱 spring/neap（大潮/小潮）**：外天体叠加仅 ±3.0% 调制，潮高 spring/neap 比 ≈ 1.06。
   与地球不同（太阳≈月球 46%，spring/neap 可达 ~2.7×），Nacrea 的大潮/小潮差异**极弱**。
3. **相位漂移拍**：潮汐峰 vs 正午以 100 d 周期缓慢漂移（见上节）。
4. **关键周期**：{{ entities.satellite_nacrea.period_days | round(3) }} d（主潮）、{{ (1/(1/entities.satellite_nacrea.period_days - 1/entities.satellite_cadence.period_days)) | round(2) }} d（韵珠会合）、{{ (1/(1/entities.satellite_nacrea.period_days - 1/entities.satellite_vigil.period_days)) | round(2) }} d（守珠会合）、
   {{ entities.planet_aegis.period_days | round0 }} d（Aegis 年 + 相位漂移拍）四重嵌套，构成"潮汐历"的骨架。

## 潮汐效应 — 地质结果

- **板块运动速度**：10–15 cm/yr（地球 5 cm/yr 的 2–3 倍，带均值 0.36 W/m² 潮汐加热驱动）
- **超大陆旋回周期**：~2 亿年（地球 3–5 亿年）
- **地震规律**：每 {{ entities.satellite_nacrea.period_days | hours | round1 }} h 触发一次里氏 4–5 级周期性微震；大规模地震（≥8 级）频率比地球低 ~60%
- **海岸线进退**：{{ (2*1688*3*entities.satellite_nacrea.eccentricity*2.5) | round0 }} m 历元潮差（受迫带内随 e 呼吸至 ~210 m 上限）+ 0.1° 大陆架坡度 → 每 38 h 理论最大进退 ~35 km（实际海岸 10–25 m 潮差 → 6–14 km）

## 潮汐对生态与文明的影响（伏笔）

> 本节为后续生态层（3B.5）与文明层（3C）设计预留的推演方向，非当前引擎输出。
> 对应 roadmap P2 待办：潮汐加热显式化、海岸侵蚀·潮汐冲刷主导、生态层海洋模块。

### 生态层

| 影响 | 机制 | 待办关联 |
|------|------|---------|
| 潮间带宽度 | {{ (2*1688*3*entities.satellite_nacrea.eccentricity*2.5) | round0 }} m 历元潮差 + 缓坡（0.02–0.1°）→ 数 km 宽潮间带，地球上不存在的大规模生态位 | 生态层海洋模块 |
| 海洋初级生产力 | 潮汐混合将深海营养盐带上表层，沿海 NPP 提升 2–5× | 同上 |
| 深海热泉 | 潮汐加热（带均值 210 TW）→ 洋中脊热泉密集，化能合成生态（独立于太阳） | 同上 |
| 相位漂移稀释热应力 | 潮间带在一个 Aegis 年内经历全部热环境并平均（无固定暴晒/冻结） | 简化生态建模 |

### 文明层

| 影响 | 机制 | 待办关联 |
|------|------|---------|
| 潮汐历 | {{ entities.satellite_nacrea.period_days | round(2) }} / {{ (1/(1/entities.satellite_nacrea.period_days - 1/entities.satellite_cadence.period_days)) | round(2) }} / {{ (1/(1/entities.satellite_nacrea.period_days - 1/entities.satellite_vigil.period_days)) | round(2) }} / {{ entities.planet_aegis.period_days | round0 }} d 四重周期是历法、宗教、农业的核心节律 | 文明种子设计 |
| 潮汐能 | {{ (2*1688*3*entities.satellite_nacrea.eccentricity*2.5) | round0 }} m 历元潮差 = 巨大势能（E=mgh），文明可能极早掌握潮汐发电 | 文明能源叙事 |
| 沿海城市形态 | 悬崖城 / 浮动城 / 内海城三分；弱 spring/neap 使港口工程压力低于地球强 spring/neap 场景 | 文明地理锚点 |
| 海岸侵蚀 | 潮汐冲刷（tidal scour）主导，河口被反复冲刷成潮汐峡谷 | 海岸侵蚀·潮汐冲刷主导 |

## 变更记录

| 日期 | 变更 | 潮汐加热 | 共振潮差 | 阻尼时标 |
|------|------|---------|---------|---------|
| 旧（e=0.0025, k₂/Q=10⁻³） | 初版 | 52–82 TW | 78 m | ~5.6 Myr |
| 旧（e=0.0018, k₂/Q=3×10⁻³） | 2026-08 重算 | 148 TW | ~46 m | 1.4 Myr |
| **现行（e=0.00242, k₂/Q=1×10⁻³）** | 2026-09-29 E3 历元 | **89 TW 历元 / 210 TW 带均值** | **~61 m** | **4.2 Myr** |

> 现行值与 `physical_params.md`（k₂=0.3, Q=300）一致；全部因变量按同一 3e 标度
> 与 F = 2.6×10⁴·e² 系数统一重算。
