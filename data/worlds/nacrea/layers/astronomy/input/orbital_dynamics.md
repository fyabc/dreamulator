---
title: "Nacrea 轨道动力学"
type: orbital
tags: [orbit, eclipse, seasons, resonance]
---

# 卫星 Nacrea — 轨道动力学

### 自变量

| 参数 | 值 | 备注 |
|------|-----|------|
| 卫星轨道倾角 i | {{ entities.satellite_nacrea.axial_tilt_deg }}° | 赤道面轨道：轨道面 = Aegis 赤道面；相对黄道夹角 = Aegis obliquity 9°（黄道面 = Aegis 绕恒星轨道面，系统参考平面） |
| 轨道偏心率 e | **0.0018**（历元值） | 受韵珠（99.6%）/守珠的长期摄动，在受迫带 0.002–0.007 内振荡（设计意图带；轨迹级实测与硬度豁免见 design-notes/0009 §2–3）；潮汐加热 0.25–3.3 W/m² 带内、均值 ~0.5。见 satellite_architecture.md |
| 1:2:4 行星共振 | 三颗巨行星构成拉普拉斯共振 | 防止巨行星坠入主星，维持巨行星偏心率不衰减；1 Myr N 体积分验证稳定，Aegis e 摆动 0.016–0.062 @ ~45 kyr（天然的类米兰科维奇旋回，见 long_term_cycles §3） |

### 因变量

| 参数 | 值 | 推导依据 |
|------|-----|---------|
| 黄赤交角 | {{ entities.satellite_nacrea.axial_tilt_deg }}° | 卫星被巨行星潮汐锁定 → 自转轴垂直于轨道面 |
| 回归线 | 南北纬 {{ entities.satellite_nacrea.axial_tilt_deg | round0 }}° | |
| 极圈（极昼极夜界限） | 南北纬 {{ entities.satellite_nacrea.polar_circle_latitude_deg | round0 }}° | 极点极昼/极夜各约 **{{ entities.satellite_nacrea.polar_day_at_pole_days | round1 }} 天**（半年各半） |
| 季节周期 | **{{ entities.planet_aegis.period_days | round0 }} 天** | 等于巨行星公转周期（轨道内移至 {{ entities.planet_aegis.semi_major_axis_au }} AU 后）；每季约 **{{ entities.satellite_nacrea.season_length_days | round2 }} 天** |
| 太阳日 | **{{ entities.satellite_nacrea.solar_day_days | round2 }} 天（{{ entities.satellite_nacrea.solar_day_days | hours | round1 }} 小时）** | 1/(1/{{ entities.satellite_nacrea.rotation_period_days }} − 1/{{ entities.planet_aegis.period_days | round0 }})；自转与周年运动同向 |
| 一年太阳日数 | **{{ entities.satellite_nacrea.days_per_year | round1 }} 个** | 季节嵌在"天气尺度"：昼夜 {{ entities.satellite_nacrea.solar_day_days | round1 }} 天 / 季节 {{ entities.satellite_nacrea.season_length_days | round2 }} 天 / 年 {{ entities.planet_aegis.period_days | round0 }} 天三重嵌套 |
| 视差摆动 | ±{{ sky.parallax_deg | round2 }}°（视太阳时 ±{{ (sky.parallax_deg / 360 * entities.satellite_nacrea.period_days * 24 * 60) | round0 }} 分钟） | 绕 Aegis 公转半径 {{ sky.planet_aegis.distance_km | round0 }} km 对恒星方向的调制，周期 {{ entities.satellite_nacrea.period_days | round2 }} 天 |
| 最大垂直偏移 | {{ sky.eclipse.max_vertical_offset_km | round0 }} km | 倾角导致卫星在轨道最高点距黄道面的垂直距离 |
| 当地 Laplace 面 | 偏黄道 ~0.65° | Laplace 面是卫星轨道长期来看会「躺平」到的平衡面。过渡半径 r_L≈4.4×10⁵ km（取 J2≈0.009），Nacrea 在 1.7 r_L 处，恒星扭矩已是行星四极矩扭矩的约 14 倍，所以平衡面几乎贴黄道 |
| 轨道面摆动 | **±0.65°，周期 ~4.7 年** | 赤道面构型相对平衡面有 8.35° 自由倾角，绕平衡面进动，周期约 4.7 年。表现为相对黄道倾角在 7.7°↔9° 之间呼吸：季节幅度被 ±7% 调制，食季在一年中的位置也随之每 4.7 年轮转一圈（类比月球交点 18.6 年漂移） |
| 自由倾角潮汐阻尼 | **~150–300 Gyr**（P-B 弱耗散包 k₂p/Qp≈7×10⁻⁸） | 阻尼率公式 t_i=(2/13)(Q/k2)(M_p/m)(a/R_p)⁵/n。弱耗散使时标 ≫ 系统年龄 5.9 Gyr → 9° 构型为**冻结化石**：早期巨撞击（Sentinel 散射期）撞出 9° 倾角并减速 Aegis 自转至 10h（金星式），此后无可观演化。见 stellar.yaml Aegis 注释与 design-notes/0009 |
| Aegis 自转轴进动 | 自由进动 ~550 年；若被捕获进 Cassini 态则随轨道面 ~1.2–1.3 千年 | 恒星对行星四极矩的扭矩驱动。自由进动周期与轨道面交点进动同量级，满足 Cassini 态捕获条件（土星即处于 Cassini 态），捕获后自转轴随轨道面同进动、倾角恒定 9° |
| Aegis 近日点进动 | **~24–60 千年**（N 体实测） | 1 Myr 行星链积分测定；Laplace–Lagrange 一阶估计（~1.3 千年）偏强一个量级，已被实测修正。伴随 Aegis e 摆动 0.016–0.062 @ ~45 kyr |
| 气候岁差拍频 | **~540–560 年**（N 体实测；处于发布带 390–640 年内） | 至点方向进动（Aegis 自转自由进动 ~550 yr）主导；近日点进动（~24–60 kyr）贡献小。「哪个半球的夏季对上近日点」的扫掠周期 = 千年尺度季节格局轮回的叙事锚点，见 roadmap #22 |
| 日食季节律 | 食季 = 交点进动周期（~4.7 年）的 {{ sky.eclipse.season_fraction | pct }} | 食季内每 {{ entities.satellite_nacrea.period_days | hours | round0 }}h 穿过本影一次全食，每次最长 {{ sky.eclipse.max_total_eclipse_hours | round1 }}h（全向星半球同时入夜）；食季外反烬星点黄纬超出本影竖直窗口（{{ sky.eclipse.eclipse_threshold_km | round0 }} km），无日食 |
| 外侧行星 2 轨道 | **0.5614 AU** | 共振 2:1 → 0.3536 × 2^(2/3) |
| 外侧行星 3 轨道 | **0.8911 AU** | 共振 4:1 → 0.3536 × 4^(2/3) |
| 卫星轨道外迁速率 | ~0.008 m/年（~0.8 cm/年） | 角动量正向传递（Aegis 自转 10h 快于卫星公转 75.5h）；对应 Aegis k₂/Q ≈ 7×10⁻⁸（Q ≈ 5×10⁶，弱耗散），自形成累计外迁 ~10% |

---
