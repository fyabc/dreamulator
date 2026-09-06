---
title: "天象全景：从珠母星仰望"
type: orbital
tags: [sky, apparent-magnitude, angular-diameter, eclipse, transit, phenomena]
---

# 天象全景 — 从珠母星（Nacrea）表面仰望

本文推演从宜居卫星**珠母星**（Nacrea）表面观测时，各天体的**视直径、视星等**
与可展示的**天象**，供视频系列一（【绛渊纪元】）的视觉设计参考。所有计算基于
`stellar.yaml` / `planets.yaml` 的真实参数，公式与输入/输出逐项列出。

> **时间单位约定**：除非注明，本文所有时间均为**地球时**（地球日 / 地球年 / 地球时），
> 与轨道根数所用单位一致。本地时间换算：**1 珠母星年 = {{ entities.planet_aegis.period_days | round0 }} 地球日**
> （≈ {{ entities.satellite_nacrea.days_per_year | round1 }} 个太阳日）；**1 太阳日 = {{ entities.satellite_nacrea.solar_day_days | round2 }} 地球日 =
> {{ entities.satellite_nacrea.solar_day_days | hours | round1 }} 地球时**；卫星公转周期 = {{ entities.satellite_nacrea.period_days | hours | round0 }} 地球时。
> 涉及"年"的天象频率，下文均明确标注是**珠母星年**还是**地球年**。

> **反照率约定**：各天体物理参数采用 `planets.yaml` 设定的 **Bond 反照率**；
> 视星等计算需要**几何反照率** $p$，按 Lambert 球假设换算
> $p = \tfrac{2}{3}\,A_{\mathrm{Bond}}$。真实后向散射天体（气态巨行星）的 $p$
> 会更高，满相亮度相应再亮 0.3–0.5 等，下文以 Lambert 值为保守基准。

## 方法与公式

**视直径**（天体半径 $R$、观测距离 $\Delta$）：

$$\theta = 2\arctan\frac{R}{\Delta}$$

**反射光视星等**（观测者在珠母星；$p$ 几何反照率，$\Phi(\alpha)$ 相位函数，
$\Delta$ 天体–观测者距离，$a$ 天体–烬星距离，$D_\star$ 烬星–观测者距离）：

$$m = m_\star - 2.5\log_{10}\!\Big[\,p\,\Phi(\alpha)\,\big(\tfrac{R}{\Delta}\big)^2 \big(\tfrac{D_\star}{a}\big)^2\Big]$$

**Lambert 相位函数**（$\Phi(0)=1$）：

$$\Phi(\alpha) = \frac{\sin\alpha + (\pi-\alpha)\cos\alpha}{\pi}$$

**恒星视星等**（光度 $L$、距离 $d$，以太阳在 1 AU 处 $-26.74$ 等为基准）：

$$m_\star = -26.74 - 2.5\log_{10} L + 5\log_{10} d_{[\mathrm{AU}]}$$

> **公式校验**：代入满月（$p=0.12$，$\Delta=384{,}400$ km，$R=1{,}737$ km）得
> $m=-12.71$，与实测满月亮度 $-12.74$ 一致，公式正确。

---

## 1. 烬星（Ignis，主恒星）

输入：$L={{ entities.star_ignis.luminosity_sol }}\,L_\odot$；半径取**引擎反演值**
$R={{ entities.star_ignis.radius_sol | round(3) }}\,R_\odot={{ sky.star_ignis.radius_km | round0 }}$ km（`stellar_derived.yaml`）；
距离 $d={{ entities.planet_aegis.semi_major_axis_au }}$ AU $={{ sky.star_ignis.distance_km | round0 }}$ km。

| 物理量 | 结果 | 对比 |
|------|------|------|
| **视直径** | **{{ sky.star_ignis.angular_diameter_deg | round2 }}°（{{ (sky.star_ignis.angular_diameter_deg * 60) | round0 }} 角分）** | 地球看太阳 0.53°；烬星**宽约 {{ (sky.star_ignis.angular_diameter_deg / 0.53) | round1 }} 倍** |
| **视星等** | **{{ sky.star_ignis.apparent_magnitude | round2 }}** | 地球看太阳 −26.74；仅暗 {{ (sky.star_ignis.apparent_magnitude + 26.74) | round2 }} 等 |

直观感受：烬星是一枚橙红色的大圆盘，面积约太阳 {{ ((sky.star_ignis.angular_diameter_deg / 0.53) ** 2) | round1 }} 倍，但因 K8 表面亮度低，
总视觉亮度与地球的太阳几乎相当。

## 2. 巨神星（Aegis，气态巨行星）

输入：$R={{ entities.planet_aegis.radius_km | round0 }}$ km；Bond 反照率 $0.343\to p=\tfrac23\times0.343=0.229$；
观测距离 $\Delta={{ sky.planet_aegis.distance_km | round0 }}$ km（珠母星轨道半径）；
天体–烬星距离 $a\approx D_\star={{ entities.planet_aegis.semi_major_axis_au }}$ AU（比值≈1）。

| 物理量 | 结果 | 对比 |
|------|------|------|
| **视直径** | **{{ sky.planet_aegis.angular_diameter_deg | round2 }}°** | 满月 0.52°；**宽 {{ (sky.planet_aegis.angular_diameter_deg / 0.52) | round0 }} 倍、面积 {{ ((sky.planet_aegis.angular_diameter_deg / 0.52) ** 2) | round0 }} 倍** |
| **满相视星等** | **{{ sky.planet_aegis.apparent_magnitude_full | round1 }}** | 满月 −12.74；**总亮度约 {{ (sky.planet_aegis.illuminance_full_w_m2 / 0.0034) | round0 }} 倍** |
| **面亮度** | **满月的 1.25 倍** | 每平方度比满月更刺眼 |

**不同相位下的视星等**（Lambert 相位函数，$m_\star={{ sky.star_ignis.apparent_magnitude | round2 }}$）：

| 相位 | 相位角 $\alpha$ | $\Phi(\alpha)$ | 视星等 | 满月亮度比 |
|------|:---:|:---:|:---:|:---:|
| 盈满 Full | 0° | 1.000 | **{{ sky.planet_aegis.apparent_magnitude_full | round1 }}** | {{ (sky.planet_aegis.illuminance_full_w_m2 / 0.0034) | round0 }}× |
| 凸月 Gibbous | 45° | 0.755 | {{ (sky.planet_aegis.apparent_magnitude_full + 0.31) | round1 }} | {{ (sky.planet_aegis.illuminance_full_w_m2 / 0.0034 * 0.755) | round0 }}× |
| 半月 Half | 90° | 0.318 | {{ (sky.planet_aegis.apparent_magnitude_full + 1.24) | round1 }} | {{ (sky.planet_aegis.illuminance_full_w_m2 / 0.0034 * 0.318) | round0 }}× |
| 眉月 Crescent | 135° | 0.048 | {{ (sky.planet_aegis.apparent_magnitude_full + 3.29) | round1 }} | {{ (sky.planet_aegis.illuminance_full_w_m2 / 0.0034 * 0.048) | round0 }}× |
| 新相 New | 180° | 0.000 | 全暗 + **日食季** | — |

直观感受：满相巨神星是横跨 {{ (sky.planet_aegis.angular_diameter_deg / 0.52) | round0 }} 个满月宽度的金琥珀色巨盘，面亮度超过地球满月
——它不是"照亮黑夜"，而是**把黑夜本身变成白昼**。

**永悬天顶**：珠母星被巨神星潮汐锁定。从向星点附近的**永耀岛**
（`geography.yaml`：lon 0.5°、lat −0.8°，距正星下点仅 0.94°）望去，
巨神星中心高度角约 **89°**，**永不升起、永不落下**，只在原地以
{{ entities.satellite_nacrea.period_days | hours | round0 }} 地球时为周期盈亏。

## 3. 外卫星：韵珠星（Cadence）与守珠星（Vigil）

两者与珠母星构成 1:2:4 拉普拉斯共振链，从珠母星看是两颗会"游走"的月亮。

| 天体 | 半径 | 距珠母星 | 视直径 | 满相视星等（最近） |
|------|------|---------|--------|------|
| **韵珠星 Cadence**（2:1，岩质） | {{ entities.satellite_cadence.radius_km | round0 }} km | {{ sky.satellite_cadence.distance_km_near | round0 }} ~ {{ sky.satellite_cadence.distance_km_far | round0 }} km | **{{ sky.satellite_cadence.angular_diameter_deg_near | round2 }}°（近）~ {{ sky.satellite_cadence.angular_diameter_deg_far | round2 }}°（远）** | **约 {{ sky.satellite_cadence.apparent_magnitude_full | round1 }}**（比满月略亮） |
| **守珠星 Vigil**（4:1，冰岩） | {{ entities.satellite_vigil.radius_km | round0 }} km | {{ sky.satellite_vigil.distance_km_near | round0 }} ~ {{ sky.satellite_vigil.distance_km_far | round0 }} km | **{{ sky.satellite_vigil.angular_diameter_deg_near | round2 }}°（近）~ {{ sky.satellite_vigil.angular_diameter_deg_far | round2 }}°（远）** | **约 {{ sky.satellite_vigil.apparent_magnitude_full | round1 }}**（接近满月） |

直观感受：韵珠星最接近时约 1.5 个满月宽，是夜空中仅次于巨神星的天体；
守珠星约半个满月宽。二者与巨神星同框时，即"一串珍珠"的核心画面。

## 4. 其他行星

内行星只在**大距**附近（黎明/黄昏）可见，外行星在**冲日**最亮。

| 行星 | 位置 | 视直径 | 最大距角 / 冲日 | 视星等 | 特殊现象 |
|------|:---:|--------|----------------|:---:|------|
| **焦星 Ember** | 内 | {{ sky.planet_ember.angular_diameter_arcmin | round1 }} 角分 | 距角 {{ sky.planet_ember.elongation_deg | round1 }}° | **{{ sky.planet_ember.apparent_magnitude_elongation | round1 }}** | 类金星大距，仅晨昏可见 |
| **鼎星 Crucible** | 内 | {{ sky.planet_crucible.angular_diameter_arcmin | round1 }} 角分 | 距角 {{ sky.planet_crucible.elongation_deg | round1 }}° | **{{ sky.planet_crucible.apparent_magnitude_elongation | round1 }}** | 最亮的"晨星/昏星" |
| **沧星 Boreal** | 外 | {{ sky.planet_boreal.angular_diameter_arcmin | round1 }} 角分 | 冲日 {{ sky.planet_boreal.distance_au_opposition | round2 }} AU | **{{ sky.planet_boreal.apparent_magnitude_opposition | round1 }}** | 冰蓝巨盘，肉眼可见圆面 |
| **霰星 Glacis** | 外 | {{ sky.planet_glacis.angular_diameter_arcmin | round1 }} 角分 | 冲日 {{ sky.planet_glacis.distance_au_opposition | round2 }} AU | **{{ sky.planet_glacis.apparent_magnitude_opposition | round1 }}** | 深青色亮点 |
| **藩星 Sentinel** | 外 | {{ sky.planet_sentinel.angular_diameter_arcmin | round1 }} 角分 | 冲日 {{ sky.planet_sentinel.distance_au_opposition | round2 }} AU | **{{ sky.planet_sentinel.apparent_magnitude_opposition | round1 }}** | 肉眼勉强可见的暗弱"流浪星" |

## 5. 食季（巨神星遮蔽烬星）

**本影锥**：$L_{\mathrm{umbra}} = R_{\mathrm{Aegis}}\,d_\star/(R_\star-R_{\mathrm{Aegis}})$
$= {{ sky.eclipse.umbra_length_km | round0 }}$ km，远超珠母星轨道半径 {{ sky.planet_aegis.distance_km | round0 }} km → **全食完全可行**。

| 参数 | 结果 |
|------|------|
| 本影在珠母星轨道处的半径 | **{{ sky.eclipse.umbra_radius_at_orbit_km | round0 }} km**（≫ 珠母星半径 {{ entities.satellite_nacrea.radius_km | round0 }} km） |
| 轨道速度（公转周期 $P=$ {{ entities.satellite_nacrea.period_days | hours | round0 }} 地球时） | {{ sky.eclipse.orbit_speed_kmh | round0 }} km/h |
| **全食最长** | **约 {{ sky.eclipse.max_total_eclipse_hours | round1 }} 地球时**（穿越本影中心） |
| 偏食到偏食最长 | 约 2.4 地球时 |

**食季窗口**（轨道倾角 {{ entities.satellite_nacrea.axial_tilt_deg | round0 }}°）：珠母星最大黄纬
${{ sky.planet_aegis.distance_km | round0 }}\sin {{ entities.satellite_nacrea.axial_tilt_deg | round0 }}°={{ sky.eclipse.max_vertical_offset_km | round0 }}$ km；
食发生阈值 = 本影半径 + 珠母星半径 = {{ sky.eclipse.eclipse_threshold_km | round0 }} km。
当反烬星点（全相相位）落入本影竖直窗口（|黄纬| < 阈值）时发生全食——该窗口占交点进动周期的
$2\arcsin({{ sky.eclipse.eclipse_threshold_km | round0 }}/{{ sky.eclipse.max_vertical_offset_km | round0 }})/2\pi={{ sky.eclipse.season_fraction | pct }}$。
交点进动周期 ~4.7 年，故食季约持续其 {{ sky.eclipse.season_fraction | pct }}（≈1 地球年）；
食季内每 {{ entities.satellite_nacrea.period_days | hours | round0 }} 地球时一次食（全向星半球同时入夜）。

**食季漂移**：交点线以 ~4.7 yr 周期退行一周 → 食季在 67 天年中的位置 4.7 yr 遍历全年
（月球食季 18.6 yr 漂移的类比）；食季与季节的相位组合构成短周期辐照调制
（食季内每次食 ~2.2 h，平均直射辐照 ~−3%）。

## 6. 适合视频展示的天文现象

| # | 现象 | 频率（地球时制） | 视频潜力 |
|:---:|------|------|:---:|
| 1 | **巨神星相位周期**（完整盈亏） | 每 78 地球时（= 1 卫星公转周期） | ★★★★★ 系列一核心视觉 |
| 2 | **日全食**（烬星被巨神星遮蔽） | 食季内每个公转周期（{{ entities.satellite_nacrea.period_days | hours | round0 }} 地球时）一次，每次最长 {{ sky.eclipse.max_total_eclipse_hours | round1 }} 地球时 | ★★★★★ 全片高潮 |
| 3 | **外卫星被巨神星掩**（韵珠/守珠隐入巨神星盘面后方） | 每个公转周期 | ★★★★ 尺度远超水星凌日 |
| 4 | **外卫星互掩**（韵珠掩守珠） | 约每 13 地球日 | ★★★★ 三星系统独有 |
| 5 | **鼎星大距**（超金星星） | 约每 0.1 地球年（≈36.5 地球日） | ★★★ 晨昏"超金星" |
| 6 | **沧星冲日**（冰蓝巨盘子夜升起） | 约每 0.4 地球年 | ★★★★ |
| 7 | **三珠连珠**（韵珠+守珠+巨神星对齐） | 罕见 | ★★★★★ 命名体系核心画面 |
| 8 | **食季连食**（交点进动周期 ~4.7 年的 {{ sky.eclipse.season_fraction | pct }} 时段内每轨道连食） | 每食季 | ★★★★ 叙事节奏锚点 |
| 9 | **藩星冲日**（暗弱"回归"） | 约每 3.7 地球年 | ★★★ 可做文明历法 |
| 10 | **星环掩星**（若巨神星有环，环面遮挡烬星光） | 视几何 | ★★★ 远期扩展 |

> **两处几何修正**：
> 1. **外卫星只会「被掩」、不会「凌」巨神星**：珠母星是最内卫星（{{ sky.planet_aegis.distance_km | round0 }} km），韵珠/守珠轨道
>    更大（{{ entities.satellite_cadence.semi_major_axis_au }} / {{ entities.satellite_vigil.semi_major_axis_au }} AU），从珠母星看它们永远在巨神星盘面**后方**，只会被巨神星遮蔽
>    （掩），不会掠过盘面前方（凌）。只有轨道在珠母星**内侧**的牧羊犬卫星（<125,000 km）才会凌巨神星。
> 2. **「环食」非「日环食」**：巨神星视直径 {{ sky.planet_aegis.angular_diameter_deg | round2 }}° ≫ 烬星 {{ sky.star_ignis.angular_diameter_deg | round2 }}°，巨神星总是完全遮住烬星（日全食），
>    「日环食」不可能。若巨神星有环，环面可额外遮挡烬星光（星环掩星）——但现有环极暗、限于
>    <125,000 km 内圈，对珠母星可忽略；「过大环」延伸到珠母星轨道（{{ sky.planet_aegis.distance_km | round0 }} km）会被珠母星引力
>    清空（牧羊效应），动力学不稳定，故不构成陨石威胁。
