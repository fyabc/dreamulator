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

直观感受：烬星是一枚橙红色的大圆盘，面积约太阳 {{ ((sky.star_ignis.angular_diameter_deg / 0.53) ** 2) | round1 }} 倍，但因 K6 表面亮度低，
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

**亮度与照度参数表**（几何反照率 A_g = 0.228，Sudarsky et al. 2000
Class II/III 过渡区；碱金属蒸气在可见光波段强吸收。地球满月参考照度
0.0034 W/m²，由满月 −12.74 等、太阳 −26.74 等与太阳常数 1361 W/m² 反推）：

| 参数 | 值 | 推导依据 |
|------|-----|---------|
| 恒星在 Aegis 处的辐照度 | **{{ entities.satellite_nacrea.instellation_w_m2 | round0 }} W/m²** | L_star / (4πa_p²)；L={{ entities.star_ignis.luminosity_sol }} L☉, a={{ entities.planet_aegis.semi_major_axis_au }} AU |
| Aegis 满相照度（Nacrea 表面） | **{{ sky.planet_aegis.illuminance_full_w_m2 | round2 }} W/m²** | F_star × A_g × (R_p/a_m)² |
| 满相 = 地球满月倍数 | **约 {{ (sky.planet_aegis.illuminance_full_w_m2 / 0.0034) | round0 }} 倍** | {{ sky.planet_aegis.illuminance_full_w_m2 | round2 }} / 0.0034 |
| 半相（90°）= 地球满月倍数 | **约 {{ (sky.planet_aegis.illuminance_full_w_m2 / 0.0034 * 0.318) | round0 }} 倍** | × 朗伯相位函数 Φ(90°)=0.318 |
| 极细相（170°）= 地球满月倍数 | **约 {{ (sky.planet_aegis.illuminance_full_w_m2 / 0.0034 * 5.7e-4) | round(1) }} 倍** | × Φ(170°)≈5.7×10⁻⁴ |
| 满相可见光照度（估算） | **~111 lux** | 民用暮光 ~10 lux；足以投射清晰阴影，支持微弱光合作用 |

**永悬天顶**：珠母星被巨神星潮汐锁定。从向星点附近的**永耀岛**
（`geography.yaml`：lon 0.4°、lat −0.6°，距正星下点仅 0.72°）望去，
巨神星中心高度角约 **89°**，**永不升起、永不落下**，只在原地以
{{ entities.satellite_nacrea.period_days | hours | round0 }} 地球时为周期盈亏。

## 3. 外卫星：韵珠星（Cadence）与守珠星（Vigil）

两者为**互相独立的单体逆行捕获卫**（非共振、非绑定——动力学依据见
satellite_architecture.md 与 design-notes/0009），从珠母星看是两颗一暗红
一灰蓝、会"游走"的月亮。**两珠轨道面不共面**：双双绕各自的**逆行拉普拉斯面**
有界进动（r_L 外侧平衡面 = 拉普拉斯面而非赤道面；i_ecl 为准不变量——韵珠 i_ecl
长期范围 166.2–174.5°、守珠 168.1–171.2°，i_eq 大幅锥摆），互倾角 0.2–23.9°（均 12.7°）
慢拍频——两珠在天球上沿**不同的行迹带**游走，大部分时间彼此远离（会合事件
口径 p50 相距 7.9°，仅 1% 达盘缘相切）。二者恒近满相：同轨共转天体互看的
相位角 ≤3.4°（Λ 满相亮度即实际亮度）。

| 天体 | 半径 | 距珠母星 | 视直径 | 满相视星等（最近） |
|------|------|---------|--------|------|
| **韵珠星 Cadence**（逆行 @{{ (entities.satellite_cadence.semi_major_axis_au * 149.5978707) | round(3) }}e6 km，岩质，红褐托林 A=0.13） | {{ entities.satellite_cadence.radius_km | round0 }} km | {{ sky.satellite_cadence.distance_km_near | round0 }} ~ {{ sky.satellite_cadence.distance_km_far | round0 }} km | **{{ sky.satellite_cadence.angular_diameter_deg_near | round2 }}°（近）~ {{ sky.satellite_cadence.angular_diameter_deg_far | round2 }}°（远）** | **约 {{ sky.satellite_cadence.apparent_magnitude_full | round1 }}**（≈ 本地满月的 {{ (10 ** ((-12.65 - sky.satellite_cadence.apparent_magnitude_full) / 2.5)) | round(1) }} 倍亮；近合宽 {{ (sky.satellite_cadence.angular_diameter_deg_near / 0.52) | round(2) }}× 满月） |
| **守珠星 Vigil**（逆行 @{{ (entities.satellite_vigil.semi_major_axis_au * 149.5978707) | round(2) }}e6 km，Charon 级冰岩，中灰微蓝 A=0.313） | {{ entities.satellite_vigil.radius_km | round0 }} km | {{ sky.satellite_vigil.distance_km_near | round0 }} ~ {{ sky.satellite_vigil.distance_km_far | round0 }} km | **{{ sky.satellite_vigil.angular_diameter_deg_near | round2 }}°（近）~ {{ sky.satellite_vigil.angular_diameter_deg_far | round2 }}°（远）** | **约 {{ sky.satellite_vigil.apparent_magnitude_full | round1 }}**（近合亮于金星 ~{{ (10 ** ((-4.9 - sky.satellite_vigil.apparent_magnitude_full) / 2.5)) | round0 }} 倍，{{ (sky.satellite_vigil.angular_diameter_deg_near * 60) | round(1) }}′ 小圆盘） |

直观感受：韵珠星最接近时约 {{ (sky.satellite_cadence.angular_diameter_deg_near / 0.52) | round(2) }} 个满月宽、{{ (10 ** ((-12.65 - sky.satellite_cadence.apparent_magnitude_full) / 2.5)) | round(1) }} 倍本地满月亮度的**暗红巨珠**（{{ sky.satellite_cadence.apparent_magnitude_full | round1 }} 等），
是夜空中仅次于巨神星的天体；守珠星是 {{ (sky.satellite_vigil.angular_diameter_deg_near * 60) | round(1) }} 角分、全轨道亮于金星数倍至数十倍的
**中灰微蓝小珠**（{{ sky.satellite_vigil.apparent_magnitude_full | round1 }} 等）。二者会合周期 {{ (1/(1/entities.satellite_cadence.period_days - 1/entities.satellite_vigil.period_days)) | round(1) }} 天，但因轨道面互倾 0.2–23.9°
（均 12.7°），**多数会合只是"同天区不同路"**（相距数度至十几度）；只有会合恰逢
两轨道面交线时才构成**连珠**——掩食级 ~4 年一遇、5′ 级紧合 ~6 年一遇，四体
共线的**双掩大连珠 ~1500 年一遇**（1500 地球年 N 体 MC 判决，方法与统计见
design-notes/0009 附录 §9.5；见 §6 #4/#7）。

> **本地满月球等**：烬星只比太阳暗 0.09 等，故珠母星的"本地满月"参照
> ≈ −12.65（与地球满月 −12.74 几乎相同）；表内星等为绝对视星等，可与
> 金星 −4.9 直接比较。

## 4. 其他行星

内行星只在**大距**附近（黎明/黄昏）可见，外行星在**冲日**最亮。

| 行星 | 位置 | 视直径 | 最大距角 / 冲日 | 视星等 | 特殊现象 |
|------|:---:|--------|----------------|:---:|------|
| **焦星 Ember** | 内 | {{ sky.planet_ember.angular_diameter_arcmin | round1 }} 角分 | 距角 {{ sky.planet_ember.elongation_deg | round1 }}° | **{{ sky.planet_ember.apparent_magnitude_elongation | round1 }}** | 内行星大距，仅晨昏可见 |
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
交点进动 = Nacrea 轨道面绕拉普拉斯面的锥摆进动，周期 **~10 年**，故食季约
持续其 {{ sky.eclipse.season_fraction | pct }}（几何窗口口径）。观测口径（MC/解析重算）：**食季间隔
~48 d（每 Aegis 年 ~2 季）、每季 ~10 d**；季内每 {{ entities.satellite_nacrea.solar_day_days | round(2) }} 地球日（会合拍，
非恒星周期）一次食（全向星半球同时入夜）；**全食 ~6 次/Aegis 年**（锥摆带内
5–9 次、~10 yr 轮转），全食最长 ~{{ sky.eclipse.max_total_eclipse_hours | round(1) }} h、初亏至复圆全程 ~2.45 h。

**食季漂移**：交点线以 ~10 yr 周期退行一周 → 食季在 {{ entities.planet_aegis.period_days | round0 }} 天年中的位置
10 yr 遍历全年（月球食季 18.6 yr 漂移的类比）；食季与季节的相位组合构成短周期
辐照调制（食季内每次全食最长 ~2.0 h、全程 ~2.45 h，平均直射辐照 ~−3%）。**食夜现墟带**：食季的全食
窗口是向星区唯一能同时摆脱 Aegis 满相天光（~345 lux）与烬星直射的时段——墟带光
（μ_V≈23.4 的黄道 16° 宽幽带）与完整星空仅在食夜显现（极光幕布间隙）。

**日食可见性的地理隔离**：Nacrea 被 Aegis 潮汐锁定，Aegis 在天空中的位置
由经度**绝对固定**，日食因此是严格的地理特权：

| 区域 | 经度范围 | Aegis 天空位置 | 日食可见性 |
|------|---------|---------------|-----------|
| **向星区 (Sub-Jovian)** | −45° ~ 45° | 天顶附近 | ✅ 食季内每个公转周期一次全食（每次最长 ~{{ sky.eclipse.max_total_eclipse_hours | round1 }}h） |
| **边缘区 (Limb)** | 45° ~ 90° / −45° ~ −90° | 贴近地平线 | ✅ 带食日出/日落 |
| **背星区 (Anti-Jovian)** | 90° ~ 180° / −90° ~ −180° | 永远在天底 | ❌ **物理上绝对无日食**（Aegis 永远在观测者背面） |

## 6. 适合视频展示的天文现象

| # | 现象 | 频率（地球时制） | 视频潜力 |
|:---:|------|------|:---:|
| 1 | **巨神星相位周期**（完整盈亏） | 每 {{ entities.satellite_nacrea.period_days | hours | round0 }} 地球时（= 1 卫星公转周期） | ★★★★★ 系列一核心视觉 |
| 2 | **日全食**（烬星被巨神星遮蔽） | 每年 ~6 次（锥摆十年轮转 5–9 次；每岁 ~2 季、食季间隔 ~48 d，季内每 {{ entities.satellite_nacrea.solar_day_days | round(2) }} 地球日会合拍一次），全食最长 {{ sky.eclipse.max_total_eclipse_hours | round1 }} 地球时（全程 ~2.45 h） | ★★★★★ 全片高潮 |
| 3 | **外卫星被巨神星掩**（韵珠/守珠隐入巨神星盘面后方） | 韵珠每 {{ (1/(1/entities.satellite_nacrea.period_days - 1/entities.satellite_cadence.period_days)) | round(2) }} 地球日、守珠每 {{ (1/(1/entities.satellite_nacrea.period_days - 1/entities.satellite_vigil.period_days)) | round(2) }} 地球日（会合周期，掩食还需交线对齐） | ★★★★ 尺度远超水星凌日 |
| 4 | **韵珠掩守珠 / 韵珠影食守珠**（会合落在两轨道面交线附近才成对上演） | 掩食级（盘缘相切）~4.1 年一遇（15′ 级 ~2.1 年）；5′ 级紧合 ~6.4 年一遇——互倾角 0.2–23.9° 慢拍频调制出"连珠季"（1500 yr MC 判决，见 0009 附录 §9.5） | ★★★★ 三星系统独有 |
| 5 | **鼎星大距**（超金星星） | 约每 0.1 地球年（≈36.5 地球日） | ★★★ 晨昏"超金星" |
| 6 | **沧星冲日**（冰蓝巨盘子夜升起） | 约每 0.4 地球年 | ★★★★ |
| 7 | **连珠**（分级）：宽松会合（两珠同天区）→ 严格连珠（Aegis-韵珠-守珠中心共线、从大到小排列）→ **双掩**（双珠同瞬全掩入巨盘盘后，不入影）→ **双掩大连珠**（四体共线：双珠相继滑至巨盘边缘排成一线、先后掩入盘后并双双没入巨行星本影） | 宽松会合每 {{ (1/(1/entities.satellite_cadence.period_days - 1/entities.satellite_vigil.period_days)) | round(1) }} 地球日（会合事件 38% 相距 >10°、仅 1% 达盘缘相切）；严格连珠 = 掩食级 ~4.1 地球年；双掩 ~2.7 次/年、成季聚簇（间隔中位 43 d）；**双掩大连珠 ~1500 地球年一遇（"一文明一次"；Poisson 带 ~450–7500 yr）**；严格四体共线且入影 1500 年样本内未见。**相位注**：双掩大连珠发生在**新巨行星相**（暗盘冲日、向星区地方子夜），非食夜——食季时影锥指向 Nacrea 自身、双珠不可能入影（两者相位差 ~1.6 d）。视觉：不可见暗盘横亘中天，双珠近满相滑向盘缘、相继没入影中熄灭（单珠中央穿影 ~2.7 h） | ★★★★★ 命名体系核心画面 |
| 8 | **食季连食**（交点进动周期 ~10 年的 {{ sky.eclipse.season_fraction | pct }} 时段内每轨道连食） | 每食季 | ★★★★ 叙事节奏锚点 |
| 9 | **藩星冲日**（暗弱"回归"） | 约每 3.7 地球年 | ★★★ 可做文明历法 |
| 10 | **星环掩星**（若巨神星有环，环面遮挡烬星光） | 视几何 | ★★★ 远期扩展 |
| 11 | **墟带光**（Glacis 外碎片带的黄道漫射光带，16° 宽绕天一周；最贴烬星处也有 72° 距角 → 整夜可见不被晨昏淹没） | 常驻（基线 μ_V≈23.4 幽带，背星区极暗夜肉眼边缘可辨）；**墟带觉醒**（带内矮行星级碰撞 → f≈1×10⁻⁷，μ_V≈22.0 肉眼清晰带，持续几十年~百年）一代人一次 | ★★★★ |
| 12 | **食夜现墟带**（向星区唯一暗夜窗口：全食中烬星与满相 Aegis 双灭，墟带光与完整星空在极光幕布间隙显现） | 食季内每 {{ entities.satellite_nacrea.solar_day_days | round(2) }} 地球日（会合拍） | ★★★★ 仪式级天象 |
| 13 | **珠行墟带**（韵珠/守珠穿行于墟带光带上——暗红/灰蓝珠饰嵌入幽带） | 常驻：两珠距巨神星角距 ≤1.3°，始终嵌于光带内；双珠同框每 {{ (1/(1/entities.satellite_cadence.period_days - 1/entities.satellite_vigil.period_days)) | round(1) }} 地球日会合 | ★★★ 构图素材 |
| 14 | **双节点流星增强**（墟带尘经 P-R 拖曳内迁至 0.365 AU 黄道面；Nacrea 轨道每 {{ entities.satellite_nacrea.period_days | round(3) }} d 两次穿越） | **{{ (entities.satellite_nacrea.period_days / 2) | round(2) }} 地球日节拍**的常态流星雨 | ★★★ |

> **两处几何修正**：
> 1. **外卫星只会「被掩」、不会「凌」巨神星**：珠母星是最内卫星（{{ sky.planet_aegis.distance_km | round0 }} km），韵珠/守珠轨道
>    更大（{{ entities.satellite_cadence.semi_major_axis_au }} / {{ entities.satellite_vigil.semi_major_axis_au }} AU），从珠母星看它们永远在巨神星盘面**后方**，只会被巨神星遮蔽
>    （掩），不会掠过盘面前方（凌）。只有轨道在珠母星**内侧**的牧羊犬卫星（<125,000 km）才会凌巨神星。
> 2. **「环食」非「日环食」**：巨神星视直径 {{ sky.planet_aegis.angular_diameter_deg | round2 }}° ≫ 烬星 {{ sky.star_ignis.angular_diameter_deg | round2 }}°，巨神星总是完全遮住烬星（日全食），
>    「日环食」不可能。若巨神星有环，环面可额外遮挡烬星光（星环掩星）——但现有环极暗、限于
>    <125,000 km 内圈，对珠母星可忽略；「过大环」延伸到珠母星轨道（{{ sky.planet_aegis.distance_km | round0 }} km）会被珠母星引力
>    清空（牧羊效应），动力学不稳定，故不构成陨石威胁。
