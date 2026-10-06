---
title: "Aegis 卫星系统架构与动力学清场"
type: satellite
tags: [satellite, impact-shield, CPD, retrograde-capture]
---

# Aegis 卫星系统架构与动力学清场

### 自变量

| 参数 | 值 | 备注 |
|------|-----|------|
| Aegis 几何反照率 A_g | 0.228 | Sudarsky et al. (2000) Class II/III 温巨行星；碱金属吸收压低可见光反照率 |
| Aegis 表面赤道磁场 | **400 μT** | ~8× 木星；planets.yaml 设定值 |
| Aegis 磁偶极轴倾角 | 18.0° | 与自转轴倾角一致（axial_tilt_deg） |

### 因变量 — Nacrea 轨道定位

| 参数 | 值 | 推导依据 |
|------|-----|---------|
| Nacrea 轨道位置 | {{ (entities.satellite_nacrea.semi_major_axis_au * 149597870.7) | group }} km（10.15 R_p） | YAML stellar.yaml |
| 占顺行稳定区 | **{{ (entities.satellite_nacrea.a_rh_ratio / 0.48 * 100) | round1 }}%** | a/R_H ÷ 顺行稳定极限 0.48（Domingos 2006） |
| Nacrea 外侧空间 | **~1,076,000 km**（标称） | 由韵珠（轨道 {{ (entities.satellite_cadence.semi_major_axis_au * 149597870.7) | round0 }} km）与守珠（轨道 {{ (entities.satellite_vigil.semi_major_axis_au * 149597870.7) | round0 }} km，内迁构型）两颗单体逆行捕获卫占据 |

### 因变量 — 三层卫星架构

基于星周盘（CPD）寡头吸积模型，Nacrea 作为 1.2 M⊕ 超级卫星充当了"系统清道夫"：

| 区域 | 距离范围 | 状态 | 成因 |
|------|---------|------|------|
| **Zone 1：内圈光环与牧羊犬区** | < 125,000 km（洛希极限内） | 极黯淡硅酸盐+冰质尘埃光环 + 数颗 <20 km 牧羊犬卫星 | 大型胚胎被潮汐力撕碎 |
| **Zone 2：绝对真空区** | 125,000 – 700,000 km | **死寂真空** | Nacrea 寡头吸积吞噬 99% 固态物质；60 亿年轨道外迁（形成以来 +10%）如"引力扫雪机"弹射/清除沿途所有竞争者 |
| **Zone 3：双单体逆行捕获卫 + 外圈捕获群** | 700,000 – 2,100,000 km | **韵珠 Cadence**（0.006 M⊕，Europa 大小 R=1437 km，轨道 {{ (entities.satellite_cadence.semi_major_axis_au * 149597870.7) | round0 }} km ≈ {{ entities.satellite_cadence.a_rh_ratio }} r_H）与**守珠 Vigil**（Charon 级 3×10⁻⁴ M⊕，轨道 {{ (entities.satellite_vigil.semi_major_axis_au * 149597870.7) | round0 }} km ≈ {{ entities.satellite_vigil.a_rh_ratio }} r_H，内迁构型）。两者是互相独立的单体捕获卫，径向净空约 {{ ((entities.satellite_vigil.semi_major_axis_au - entities.satellite_cadence.semi_major_axis_au) * 149597870.7) | round0 }} km，合 {{ entities.satellite_cadence.mutual_hill_separation_to_outer | round0 }} 个互希尔半径。双珠属 **FJ 近平衡族**（黄道系基准）：捕获后就停在各自逆行拉普拉斯面的近旁（韵珠初始 i=167.2°/Ω=180°，守珠 i=170°/Ω=180°；当前历元分别为 168.8° 与 170.1°）。由于 r_L 之外的平衡面是拉普拉斯面而不是赤道面，i_ecl 是准不变量，轨道面绕平衡面做有界进动；两个轨道面的互倾角在 0.3–23.6° 之间（均值 12.6°）缓慢拍动。此外还有约 30–50 颗 10–100 km 级的不规则捕获卫星 | 两颗珠都是晚期散射期（约 0.5 Gyr，本系统的晚期重轰炸类比）的逆行捕获天体，与海卫一同类比，与 Glacis 的逆石星 Rogue 同世代、同机制，与墟带雕塑属同一事件；不规则捕获群则是 60 亿年间偶然捕获的星际访客与彗星（类似木星的加尔尼群） |

**为什么是「双单体」而非共振链/双星/共轨对**：Nacrea 的质量比 μ = 2.4×10⁻³，
是木卫一的 50 倍。在这样的摄动源旁边，任何共动或绑定的外卫组合（1:2:4 链、
双珠成对、层级双星）都在 6–45 kyr 内瓦解——死于交叉遭遇扩散、洛希破裂，
或把 Nacrea 的偏心率泵过加热红线。参数空间搜索（累计 130 余次 REBOUND 积分，
记录见附录实验日志）进一步穷尽了其余选项：只留一颗韵珠的**单珠**方案在平衡位
与黄道锚定位都在 6–19 kyr 内死于自身 Kozai 翻转；双珠内迁到 0.2–0.3 r_H 的
**紧凑方案**热流反而升高（线性标定在该区失效）；0.3–0.5 r_H 带内不存在
100 kyr 级的长寿解（93 票的天花板是 35–60 kyr）。最终的双单体方案
（{{ entities.satellite_cadence.mutual_hill_separation_to_outer | round0 }} 个互希尔半径的径向净空）+ 内迁守珠（0.37 r_H）+ 减质量韵珠
（遭遇扩散速率 ∝ m_C²）是天空美学与动力学寿命之间的最优折衷。其长期动力学
按**叙事豁免**处理（用户 2026-10-07 裁决「draw 0 + 叙事豁免」，双珠长期存活）：
当代段（0–12 kyr）是生态、气候与文明的正典窗口；draw-0 落地实现的首失稳为
约 2.23 万年后的韵珠弹射，即可以提前预报的末世天象「韵珠远行」。判决与豁免
记录见 design-notes/0009 §2 与附录实验日志。

### 因变量 — 长期摄动：受迫偏心率的 60 亿年维持机制

Nacrea 被潮汐锁定后，巨行星潮汐以极强效率阻尼其轨道偏心率：

| 参数 | 值 | 推导依据 |
|------|-----|---------|
| 偏心率阻尼时标 τ_e | **~{{ (entities.satellite_nacrea.tidal_e_damping_timescale_yr / 1e6) | round1 }} Myr**（k₂/Q=1×10⁻³，Q=300） | (1/e)(de/dt) = (21/2)(k₂/Q)(M_p/M_m)(R_m/a_m)⁵n_m |
| 无泵浦时的结局 | e → 0，潮汐加热熄灭 | 板块构造与碳循环停摆 → 宜居性丧失 |
| 泵浦机制（双源） | **恒星四极矩本底（主项）+ 韵珠/守珠长期摄动（次项）** | 0.35 AU 的强恒星场经四极矩给出 ~0.004–0.006 的偏心率本底——这是测试粒子效应，与双珠质量一阶无关；双珠的受迫项线性系数 coef=Σmᵢ(a_N/aᵢ)³=1.35×10⁻³（韵珠贡献 98.3%）。三星周期比 {{ (entities.satellite_cadence.period_days / entities.satellite_nacrea.period_days) | round(2) }}/{{ (entities.satellite_vigil.period_days / entities.satellite_cadence.period_days) | round(2) }}/{{ (entities.satellite_vigil.period_days / entities.satellite_nacrea.period_days) | round(2) }}，全部脱离低阶共振或仅触及可忽略的高阶项。**当代段认证带 rms 0.0036 / max 0.0098**（draw-0 落地实现 30 kyr 认证，当代段取 0–12 kyr；叙事豁免见 design-notes/0009 §2） |
| 泵浦源稳定性 | 两珠均为单体远距逆行轨道（有界 e 摆动、迁移 ~μm/yr 冻结） | {{ entities.satellite_cadence.a_rh_ratio }}/{{ entities.satellite_vigil.a_rh_ratio }} r_H 逆行；径向净空 {{ entities.satellite_cadence.mutual_hill_separation_to_outer | round0 }} r_H,m；长期动力学判决与硬度豁免见 design-notes/0009 §2 |
| 巨行星潮汐耗散 | k₂p/Qp ≈ 7×10⁻⁸（Q_p ≈ 5×10⁶，弱耗散 P-B 包） | 两珠外迁均 ≤7 μm/yr（∝ m_s·a⁻⁵）→ 泵浦频率 5.9 Gyr 恒定 |
| 潮汐加热平衡 | 历元 e={{ entities.satellite_nacrea.eccentricity }} → {{ (1.52e19 * entities.satellite_nacrea.eccentricity * entities.satellite_nacrea.eccentricity / 1e12) | round0 }} TW（{{ (2.607e4 * entities.satellite_nacrea.eccentricity * entities.satellite_nacrea.eccentricity) | round(3) }} W/m²，冷谷快照）；当代段均值 **0.36 W/m²**（4.1× 地球内热流）、瞬时极值 1.85（0.79×Io，百年级）、500-yr 平滑持续脉冲占空 0% | 加热功率 ≈**2.6×10⁴**·e² W/m²（k₂/Q=1×10⁻³；见 tidal_effects.md）；带内主调制 **~20 kyr** =「万年火山脉冲」（long_term_cycles §4）；远期增温 = 失稳前兆（诊断律） |

> 注：k₂/Q 取 `physical_params.md`（k₂=0.3, Q=300，「非共振大洋+窄陆架」组合，
> 2026-09-28 裁决）→ 1×10⁻³，与 tidal_effects.md / geological_history.md 一致。

天空景观：Nacrea 向星半球永远悬着巨大的 Aegis（视直径 {{ sky.planet_aegis.angular_diameter_deg | round1 }}°、满相 {{ sky.planet_aegis.apparent_magnitude_full | round1 }} 等、
~230 lux 永暮级夜照）；韵珠以 {{ entities.satellite_cadence.period_days | round(2) }} 天、守珠以 {{ entities.satellite_vigil.period_days | round(2) }} 天周期巡天——韵珠近合是
一颗 {{ (sky.satellite_cadence.angular_diameter_deg_near * 60) | round0 }}′（{{ (sky.satellite_cadence.angular_diameter_deg_near / 0.52) | round(2) }}× 满月宽）、~{{ (10 ** ((-11.5 - sky.satellite_cadence.apparent_magnitude_full) / 2.5)) | round(1) }} 倍本地满月亮度的**暗红巨珠**（{{ sky.satellite_cadence.apparent_magnitude_full | round1 }} 等，稳居夜空
第二），守珠是 {{ (sky.satellite_vigil.angular_diameter_deg_near * 60) | round(1) }}′、亮于金星 ~{{ (10 ** ((-4.9 - sky.satellite_vigil.apparent_magnitude_full) / 2.5)) | round0 }} 倍的**中灰微蓝小珠**（{{ sky.satellite_vigil.apparent_magnitude_full | round1 }} 等）。黄道面上
另有 16° 宽的**墟带光**幽带（μ_V≈23.8，背星区极暗夜肉眼边缘可辨；食夜是向星区
唯一窗口）。两珠轨道面互倾 0.3–23.6°（均 12.6°，慢拍频），平时散落天球；会合
每 {{ (1/(1/entities.satellite_cadence.period_days - 1/entities.satellite_vigil.period_days)) | round(1) }} 天一次但多数相距数度至十几度，只有会合落在两轨道面交线附近才构成
**连珠**：掩食级（守珠隐入韵珠）~4 年一遇、5′ 级 ~6 年、双掩（不入影）~2.7 次/年
成季聚簇、**双掩大连珠**（Nacrea–Aegis–韵珠–守珠四体共线，双珠相继掩入巨盘
并双双入影）**~1500 年一遇**——「一文明一次」的历法与神话核心节律（1500 地球年
N 体 MC 判决，`private/research/2026-09-28-sky-recalc.md`）。详见 sky_phenomena.md。

### 因变量 — 60 亿年离心率演化简史（受迫振荡）

Nacrea 的偏心率**不是自由衰减的**，而是**受迫偏心率（forced eccentricity）**——
由韵珠/守珠的长期摄动持续维持。区分两个时间尺度至关重要：

- **潮汐阻尼时标 τ_e ≈ {{ (entities.satellite_nacrea.tidal_e_damping_timescale_yr / 1e6) | round1 }} Myr**：泵浦一旦消失，自由 e 在此尺度内归零。
- **泵浦源寿命 ~Gyr**：两珠轨道准可积、迁移 ~μm–cm/yr——受迫带 5.4 Gyr 恒定。

| 时代 | 时间 (Gyr) | e | 潮汐热流 (W/m²) | 机制 |
|------|-----------|-----|----------------|------|
| **冥古宙（捕获前）** | 0–0.5 | ~0.015（自由）→ 衰减 | （形成热主导 → 递减） | 自由偏心率潮汐阻尼快速衰减；四极矩本底泵浦此时已在（~0.004–0.006） |
| **晚期散射期（双珠捕获）** | ~0.5 | 受迫带接管 | — | 本系统的 LHB：韵珠、守珠先后逆行捕获（与墟带雕塑/散射盘/奥尔特供给同事件）；双珠摄动叠加四极矩本底 |
| **捕获后至今** | 0.5–5.9 | **当代段 0.0009–0.0084 振荡（rms 0.0037）** | 0.06–1.85（均值 ~0.36） | 泵浦源冻结（迁移 μm/yr）；主调制 ~20 kyr（长期摄动拍频）=「万年火山脉冲」 |
| **当前历元** | 5.9 | **{{ entities.satellite_nacrea.eccentricity }}**（带下缘冷谷快照） | **{{ (2.607e4 * entities.satellite_nacrea.eccentricity * entities.satellite_nacrea.eccentricity) | round(3) }}**（{{ (1.52e19 * entities.satellite_nacrea.eccentricity * entities.satellite_nacrea.eccentricity / 1e12) | round0 }} TW） | stellar.yaml 历元值（t₁=37.905 yr 平移态）；与 tidal_effects.md / geological_history.md 一致 |

> 热流 ∝ e²：地质叙事取「长期均值 ~4.1× 地球内热流（0.36 W/m²）、瞬时尖峰
> ~0.8× Io（百年级脉冲）」的活跃板块构造世界；历元值为冷谷快照。
> 加热系数 2.6×10⁴·e² 对应 Q=300（2026-09-28 裁决）。

### 因变量 — 三重撞击防护机制

| 机制 | 物理原理 | 生态效应 |
|------|---------|---------|
| **巨行星引力盾 (Jovian Shield)** | Aegis 引力截面（1.6 M_J）使穿越希尔球的彗星优先坠入 Aegis 大气 | 绝大多数危险天体在接触 Nacrea 前被拦截 |
| **轨道清空完毕** | Nacrea 的希尔球（{{ entities.satellite_nacrea.hill_radius_km | group }} km）在数十亿年前已彻底清空共轨区域碎石 | 系统已过晚期重轰炸期，进入动力学宁静期 |
| **古在共振过滤 (Kozai-Lidov)** | 外圈高倾角捕获卫星若与 Nacrea 强耦合 → 偏心率飙升 → 坠毁在 Aegis 上 | 仅约每 10 万年一次小型彗星碎片漏网撞击，为 Nacrea 持续补充微量挥发分（水、氮） |

### 其他行星的卫星系统

参考太阳系但刻意制造区分度、各具特点。设计依据（Hill 球、潮汐剥离）与命名词族见
`data/worlds/nacrea/design-notes/0004-satellite-systems.md`。

| 行星 | 架构 | 卫星（科学别名） | 太阳系类比 |
|------|------|------------------|-----------|
| **Ember** | 无卫星 | 无 | 水星 |
| **Crucible** | 捕获小卫星 | 焦砾星 Cinder（鼎卫一），~22 km | 火卫一 |
| **Boreal（0.5 M_J）** | 标准微型太阳系 | 凝冰星/玄冰星/霜冰星（沧卫一~三），冰下海洋 / 最大+磁场 / 陨石坑 | 伽利略卫星 |
| **Glacis（冰巨星）** | 规则内 + 逆行捕获外 | 玄石星 Shard（霰卫一）+ 逆石星 Rogue（霰卫二，逆行） | 海卫一 |
| **Sentinel（散射冰巨星）** | 散射遗孤 | 近客星 Vagrant（藩卫一）+ 远客星 Guest（藩卫二）+ 稳定特洛伊「伴行营」（L4/L5，数值判决 23/24 存活——太阳系无类比） | 阋神星 Dysnomia |

> Glacis/Aegis 无特洛伊（共振链行星的特洛伊不稳定，0.3 Myr 数值判决 1/24 与
> 0/24）；墟带（1.3–3.0 AU）+ 三颗矮行星（璞/皚/赭）见 design-notes/0011。

---
