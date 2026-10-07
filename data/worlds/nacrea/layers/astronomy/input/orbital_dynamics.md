---
title: "Nacrea 轨道动力学"
type: orbital
tags: [orbit, eclipse, seasons, resonance, laplace-plane]
---

# 卫星 Nacrea — 轨道动力学

### 自变量

| 参数 | 值 | 备注 |
|------|-----|------|
| 有效季节倾角 | {{ entities.satellite_nacrea.axial_tilt_deg }}° | 这个值取的是轨道面绕拉普拉斯面锥摆的长期均值（构型推导见 design-notes/0009 §5）。Nacrea 被潮汐锁定，自转轴垂直于轨道面，因此轨道面的摆动直接等价于季节倾角的摆动：瞬时黄道倾角在当代段介于 10.9–18.3° 之间，摆动周期约 10 年。这个周期远短于气候系统的响应时间，所以气候层读长期均值、并登记摆动带。Aegis 的自转轴倾角 ε=18° |
| 轨道偏心率 e | **{{ entities.satellite_nacrea.eccentricity }}**（历元值） | Nacrea 的偏心率不会自由衰减，而是由两个泵浦源持续维持：一是恒星四极矩提供的本底（约 0.004–0.006，0.365 AU 强场下的测试粒子效应），二是韵珠与守珠的长期摄动（线性系数 1.35×10⁻³）。两者叠加给出当代段（0–12 kyr）长期摆动带：rms 0.0036、最大 0.0098（10-07 定版数值审计）。潮汐加热按 F = 2.6×10⁴·e² W/m² 换算（对应 k₂/Q = 1×10⁻³），平均热流 0.34 W/m²，瞬时极值 2.50 W/m²（百年级短暂尖峰）。长期动力学数值审计见 design-notes/0009 §2–3 |
| 1:2:4 行星共振 | 三颗巨行星构成周期通约链（共振邻接，φ_L 循环） | 链处于 β+ 安静长期模态：Aegis 的偏心率带 0.065–0.081（振幅呼吸周期约 2.85 kyr），ϖ_A 循环周期约 44 年；Boreal e ≤0.11、Glacis e ≤0.14（链的内禀呼吸，百年尺度）；10 Myr N 体积分验证有界。**ϖ₀ 扇区红线**：初值 ϖ₀ 落在 90°/270° 附近的狂野扇区时，链在 8–15 kyr 内瓦解且卫星热流数倍恶化，禁止回改（见 0009 §7） |

### 因变量

| 参数 | 值 | 推导依据 |
|------|------|---------|
| 黄赤交角 | {{ entities.satellite_nacrea.axial_tilt_deg }}° | 卫星被巨行星潮汐锁定，自转轴垂直于轨道面；数值取锥摆的长期均值 |
| 回归线 | 南北纬 {{ entities.satellite_nacrea.axial_tilt_deg | round0 }}° | |
| 极圈（极昼极夜界限） | 南北纬 {{ entities.satellite_nacrea.polar_circle_latitude_deg | round0 }}° | 极点处极昼与极夜各约 **{{ entities.satellite_nacrea.polar_day_at_pole_days | round1 }} 天**（各占半年） |
| 季节周期 | **{{ entities.planet_aegis.period_days | round0 }} 天** | 等于巨行星的公转周期；每季约 **{{ entities.satellite_nacrea.season_length_days | round2 }} 天** |
| 太阳日 | **{{ entities.satellite_nacrea.solar_day_days | round(2) }} 天（{{ entities.satellite_nacrea.solar_day_days | hours | round1 }} 小时）** | 1/(1/{{ entities.satellite_nacrea.rotation_period_days }} − 1/{{ entities.planet_aegis.period_days | round0 }})；自转与周年运动同向 |
| 一年太阳日数 | **{{ entities.satellite_nacrea.days_per_year | round1 }} 个** | 季节嵌在"天气尺度"上：昼夜 {{ entities.satellite_nacrea.solar_day_days | round1 }} 天、每季 {{ entities.satellite_nacrea.season_length_days | round2 }} 天、全年 {{ entities.planet_aegis.period_days | round0 }} 天，三重嵌套 |
| 视差摆动 | ±{{ sky.parallax_deg | round2 }}°（视太阳时 ±{{ (sky.parallax_deg / 360 * entities.satellite_nacrea.period_days * 24 * 60) | round0 }} 分钟） | 绕 Aegis 公转的半径（{{ sky.planet_aegis.distance_km | round0 }} km）对恒星方向的调制，周期 {{ entities.satellite_nacrea.period_days | round2 }} 天 |
| 最大垂直偏移 | {{ sky.eclipse.max_vertical_offset_km | round0 }} km | 历元倾角（13.6°）下轨道最高点距黄道面的垂直距离；锥摆带上界 18.3° 对应约 227,000 km |
| 当地 Laplace 面 | 偏赤道面 ψ_L ≈ 15.6°（即偏黄道约 2.4°） | r_L = [2J₂(M_p/M_*)R_p²a_h³]^(1/5) ≈ 5.0×10⁵ km（J₂=0.008）。Nacrea 位于 1.45 r_L 之外，此处恒星扭矩约为行星四极矩的 6 倍，平衡面因此靠近黄道面：ψ_L = atan2(sinε, (r_L/r)⁵+cosε) |
| 轨道面锥摆 | **i_eq 0.2–31.4°、i_ecl 10.9–18.3°（当代段），周期 ~10 yr** | 轨道面初始贴近 Aegis 赤道（ε=18°），随后绕拉普拉斯面法线做锥摆；i_ecl 的长期均值理论上 ≈ ψ_L = 15.6°，当代段实测 14.9°。RK4 长期理论与 N 体积分双重验证（design-notes/0009 §2） |
| 自由倾角潮汐阻尼 | **~150–300 Gyr**（P-B 弱耗散包，k₂p/Qp≈7×10⁻⁸） | 阻尼率公式 t_i=(2/13)(Q/k₂)(M_p/m)(a/R_p)⁵/n。该时标远大于系统年龄 5.9 Gyr，因此 ε=18° 是早期巨撞击留下的化石（该撞击同时减速了自转），不需要任何维持机制 |
| Aegis 自转轴进动 | 自由进动 ~550–605 年；处于 Cassini 态（随轨道面进动、倾角恒定 18°） | 由恒星作用于行星四极矩的扭矩驱动 |
| Aegis 近日点进动 | **ϖ_A 循环 ~44 yr**（β+ 安静模态实测 8.2°/yr） | 近共振链的长期耦合（共振放大）。该周期对采样率敏感，必须用 ≤2 年的采样加偏心率矢量法直测 |
| 气候岁差 = 近日点大年 | **~13 yr**（ϖ_A 的 44 年循环与 Nacrea 节点进动的 ~10 年周期合成的相位循环） | Nacrea 的自转轴垂直于轨道面，它的"转轴进动"就是轨道节点进动（约 10 年）。近日点与季节的相位在一代人之内走完全循环："北半球强季年"与"南半球强季年"以约 22 年的半周期交替，树轮、冰芯与纹泥都能分辨。当前历元 φ=82.7°，近日点领先北夏至约 2.0 天 |
| 日食季节律 | 食季 = 交点进动周期（~10 yr）的 {{ sky.eclipse.season_fraction | pct }} | 食季内每 {{ entities.satellite_nacrea.solar_day_days | round(2) }} 天（会合拍）发生一次食，全食最长 {{ sky.eclipse.max_total_eclipse_hours | round1 }} 小时，全向星半球同时入夜；食季在年中的位置随节点进动以约 10 年为周期轮转 |
| 外侧行星 2 轨道 | 通约设计值 ≈0.579 AU；历元 osculating 快照 0.5777 | 共振邻接链的 osculating 值随链呼吸漂移约 ±1%（历元快照见 stellar.yaml） |
| 外侧行星 3 轨道 | 通约设计值 ≈0.919 AU；历元 osculating 快照 0.9296 | 同上 |
| 卫星轨道外迁速率 | ~{{ entities.satellite_nacrea.tidal_migration_rate_m_yr | round(4) }} m/年 | 角动量正向传递（Aegis 自转约 10 小时，快于卫星公转的 75.3 小时）；速率由 Aegis 的 k₂/Q ≈ 7×10⁻⁸ 设定，与 Nacrea 自身的 Q 无关；自形成以来累计外迁约 10% |

---
