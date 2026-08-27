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
| 轨道偏心率 e | **0.002** | 由 Cadence/Vigil 卫星拉普拉斯共振链泵浦维持（受迫偏心率，见 satellite_architecture.md） |
| 1:2:4 行星共振 | 三颗巨行星构成拉普拉斯共振 | 防止巨行星坠入主星，维持巨行星偏心率不衰减 |

### 因变量

| 参数 | 值 | 推导依据 |
|------|-----|---------|
| 黄赤交角 | {{ entities.satellite_nacrea.axial_tilt_deg }}° | 卫星被巨行星潮汐锁定 → 自转轴垂直于轨道面 |
| 回归线 | 南北纬 {{ entities.satellite_nacrea.axial_tilt_deg | round0 }}° | |
| 极圈（极昼极夜界限） | 南北纬 {{ entities.satellite_nacrea.polar_circle_latitude_deg | round0 }}° | 极点极昼/极夜各约 **{{ entities.satellite_nacrea.polar_day_at_pole_days | round1 }} 天**（半年各半） |
| 季节周期 | **{{ entities.planet_aegis.period_days | round0 }} 天** | 等于巨行星公转周期（轨道内移至 {{ entities.planet_aegis.semi_major_axis_au }} AU 后）；每季约 **{{ entities.satellite_nacrea.season_length_days | round2 }} 天** |
| 太阳日 | **{{ entities.satellite_nacrea.solar_day_days | round2 }} 天（{{ entities.satellite_nacrea.solar_day_days | hours | round1 }} 小时）** | 1/(1/{{ entities.satellite_nacrea.rotation_period_days }} − 1/{{ entities.planet_aegis.period_days | round0 }})；自转与周年运动同向 |
| 一年太阳日数 | **{{ entities.satellite_nacrea.days_per_year | round1 }} 个** | 季节嵌在"天气尺度"：昼夜 {{ entities.satellite_nacrea.solar_day_days | round1 }} 天 / 季节 {{ entities.satellite_nacrea.season_length_days | round2 }} 天 / 年 {{ entities.planet_aegis.period_days | round0 }} 天三重嵌套 |
| 视差摆动 | ±1.04°（视太阳时 ±14 分钟） | 绕 Aegis 公转半径 74 万 km 对恒星方向的调制，周期 {{ entities.satellite_nacrea.rotation_period_days }} 天 |
| 最大垂直偏移 | 115,722 km | 倾角导致卫星在轨道最高点距黄道面的垂直距离 |
| 当地 Laplace 面 | 偏黄道 ~0.65° | Laplace 面是卫星轨道长期来看会「躺平」到的平衡面。过渡半径 r_L≈4.4×10⁵ km（取 J2≈0.009），Nacrea 在 1.7 r_L 处，恒星扭矩已是行星四极矩扭矩的约 14 倍，所以平衡面几乎贴黄道 |
| 轨道面摆动 | **±0.65°，周期 ~4.7 年** | 赤道面构型相对平衡面有 8.35° 自由倾角，绕平衡面进动，周期约 4.7 年。表现为相对黄道倾角在 7.7°↔9° 之间呼吸：季节幅度被 ±7% 调制，食季在一年中的位置也随之每 4.7 年轮转一圈（类比月球交点 18.6 年漂移） |
| 自由倾角潮汐阻尼 | ~1–2 Gyr（取木星级 Q_p/k2p） | 阻尼率公式 t_i=(2/13)(Q/k2)(M_p/m)(a/R_p)⁵/n。系统年龄 5.9 Gyr 长于该时标，因此 9° 构型需要维持机制：1:2:4 共振链的倾角型共振泵浦（土卫一–土卫三 Mimas–Tethys 类比），或声明 Aegis 潮汐耗散更弱；见 satellite_architecture.md |
| Aegis 自转轴进动 | 自由进动 ~550 年；若被捕获进 Cassini 态则随轨道面 ~1.2–1.3 千年 | 恒星对行星四极矩的扭矩驱动。自由进动周期与轨道面交点进动同量级，满足 Cassini 态捕获条件（土星即处于 Cassini 态），捕获后自转轴随轨道面同进动、倾角恒定 9° |
| Aegis 近日点进动 | **~1.3 千年** | 主要来自 Boreal 的长期摄动（Laplace–Lagrange 一阶量级；共振链对系数的修正需 N 体积分确认） |
| 气候岁差拍频 | **~390–640 年**（半球优势反转半周期 ~200–300 年） | 至点方向进动与近日点进动方向相反、速率相加，得到「哪个半球的夏季对上近日点」的扫掠周期。这是千年尺度季节格局轮回的叙事锚点，见 roadmap #22 |
| 日食遮蔽率 | 2.1% | 全年 {{ entities.planet_aegis.period_days | round0 }} 天中约 48 天无日食 |
| 日全食季 | 每年 2 次，每次 ~11 天 | 每 {{ entities.satellite_nacrea.period_days | hours | round0 }}h 穿过本影一次，约 3–4 次日全食（每次~2.3h，全向星半球同时入夜） |
| 日偏食季 | 每年约 2 次 | |
| 外侧行星 2 轨道 | **0.3975 AU** | 共振 2:1 → 0.2504 × 2^(2/3) |
| 外侧行星 3 轨道 | **0.631 AU** | 共振 4:1 → 0.2504 × 4^(2/3) |
| 卫星轨道外迁速率 | ~1.7 m/年 | 角动量正向传递（巨行星自转快于卫星公转） |

---
