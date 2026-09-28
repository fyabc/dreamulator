---
title: "Nacrea 轨道动力学"
type: orbital
tags: [orbit, eclipse, seasons, resonance, laplace-plane]
---

# 卫星 Nacrea — 轨道动力学

### 自变量

| 参数 | 值 | 备注 |
|------|-----|------|
| 有效季节倾角 | {{ entities.satellite_nacrea.axial_tilt_deg }}° | **= i_ecl 锥摆长期均值**（出路 b 裁决 2026-09-28）：轨道面绕拉普拉斯面 ~10 yr 锥摆，瞬时黄道倾角带 11.7–17.8°（当代段）；10 yr ≪ 气候响应时间 → 气候层读均值 + 登记摆动带。自转轴 ⊥ 轨道面（潮汐锁定），ε(Aegis)=18° |
| 轨道偏心率 e | **{{ entities.satellite_nacrea.eccentricity }}**（历元值） | 双源泵浦：恒星四极矩本底（~0.004–0.006）+ 韵珠/守珠长期摄动（coef=1.35×10⁻³）；当代段认证带 rms 0.0037 / max 0.0084；潮汐加热 F=2.6×10⁴·e²（k₂/Q=1×10⁻³）→ 均值 0.36 W/m²、瞬时极值 1.85（百年级）。轨迹级认证与硬度豁免见 design-notes/0009 §2–3 |
| 1:2:4 行星共振 | 三颗巨行星构成周期通约链（共振邻接，φ_L 循环） | β+ 安静长期模态：Aegis e 带 0.065–0.081（振幅呼吸 ~2.85 kyr）、ϖ_A 循环 ~44 yr；Boreal e ≤0.11、Glacis e ≤0.14（链内禀呼吸，百年尺度）；10 Myr N 体有界验证。**ϖ₀ 扇区红线**：90°/270° 狂野扇区 8–15 kyr 即死，禁止回改（见 0009 §7） |

### 因变量

| 参数 | 值 | 推导依据 |
|------|------|---------|
| 黄赤交角 | {{ entities.satellite_nacrea.axial_tilt_deg }}° | 卫星被巨行星潮汐锁定 → 自转轴垂直于轨道面；数值 = 锥摆长期均值 |
| 回归线 | 南北纬 {{ entities.satellite_nacrea.axial_tilt_deg | round0 }}° | |
| 极圈（极昼极夜界限） | 南北纬 {{ entities.satellite_nacrea.polar_circle_latitude_deg | round0 }}° | 极点极昼/极夜各约 **{{ entities.satellite_nacrea.polar_day_at_pole_days | round1 }} 天**（半年各半） |
| 季节周期 | **{{ entities.planet_aegis.period_days | round0 }} 天** | 等于巨行星公转周期；每季约 **{{ entities.satellite_nacrea.season_length_days | round2 }} 天** |
| 太阳日 | **{{ entities.satellite_nacrea.solar_day_days | round2 }} 天（{{ entities.satellite_nacrea.solar_day_days | hours | round1 }} 小时）** | 1/(1/{{ entities.satellite_nacrea.rotation_period_days }} − 1/{{ entities.planet_aegis.period_days | round0 }})；自转与周年运动同向 |
| 一年太阳日数 | **{{ entities.satellite_nacrea.days_per_year | round1 }} 个** | 季节嵌在"天气尺度"：昼夜 {{ entities.satellite_nacrea.solar_day_days | round1 }} 天 / 季节 {{ entities.satellite_nacrea.season_length_days | round2 }} 天 / 年 {{ entities.planet_aegis.period_days | round0 }} 天三重嵌套 |
| 视差摆动 | ±{{ sky.parallax_deg | round2 }}°（视太阳时 ±{{ (sky.parallax_deg / 360 * entities.satellite_nacrea.period_days * 24 * 60) | round0 }} 分钟） | 绕 Aegis 公转半径 {{ sky.planet_aegis.distance_km | round0 }} km 对恒星方向的调制，周期 {{ entities.satellite_nacrea.period_days | round2 }} 天 |
| 最大垂直偏移 | {{ sky.eclipse.max_vertical_offset_km | round0 }} km | 锥摆带（11.7–17.8°）上界对应的轨道最高点距黄道面垂直距离 |
| 当地 Laplace 面 | 偏赤道面 ψ_L ≈ 15.6°（即偏黄道 ~2.4°） | r_L = [2J₂(M_p/M_*)R_p²a_h³]^(1/5) ≈ 5.0×10⁵ km（J₂=0.008）；Nacrea 在 **1.45 r_L** 外侧，恒星扭矩 ~6× 行星四极矩 → 平衡面近黄道。ψ_L = atan2(sinε, (r_L/r)⁵+cosε) |
| 轨道面锥摆（出路 b） | **i_eq 0.6–31°、i_ecl 11.7–17.8°（当代段），周期 ~10 yr** | 轨道面初始贴赤道（ε=18°），绕拉普拉斯面法线锥摆；i_ecl 长期均值 ≈ ψ_L = 15.6°（E3 当代段实测 14.9°）。RK4 长期理论 + N 体双验证（design-notes/0009 §2、private 台账） |
| 自由倾角潮汐阻尼 | **~150–300 Gyr**（P-B 弱耗散包 k₂p/Qp≈7×10⁻⁸） | 阻尼率公式 t_i=(2/13)(Q/k2)(M_p/m)(a/R_p)⁵/n。时标 ≫ 系统年龄 5.9 Gyr → ε=18° 为**早期巨撞击化石**（金星式撞击减速类比），无需维持机制 |
| Aegis 自转轴进动 | 自由进动 ~550–605 年；Cassini 态（随轨道面进动、倾角恒定 18°） | 恒星对行星四极矩的扭矩驱动；土星同类比 |
| Aegis 近日点进动 | **ϖ_A 循环 ~44 yr**（β+ 安静模态实测 8.2°/yr） | 近共振链的长期耦合（共振放大）；旧「24–60 kyr」为采样混叠伪影，作废 |
| 气候岁差 = 近日点大年 | **~13 yr**（ϖ_A 44 yr 与 Nacrea 节点进动 ~10 yr 的合成相位循环） | Nacrea 自转轴 ⊥ 轨道面 → 其「转轴进动」= 轨道节点进动（~10 yr）。近日点-季节相位一代人内走完全循环：「北半球强季年 ↔ 南半球强季年」~22 yr 半周期交替（树轮/冰芯/纹泥可辨）；历元恰逢 φ=82.1°（近日点领先北夏至 2.2 d） |
| 日食季节律 | 食季 = 交点进动周期（~10 yr）的 {{ sky.eclipse.season_fraction | pct }} | 食季内每 {{ entities.satellite_nacrea.period_days | hours | round0 }}h 穿过本影一次全食，每次最长 {{ sky.eclipse.max_total_eclipse_hours | round1 }}h（全向星半球同时入夜）；食季在年中的位置随节点进动 ~10 yr 轮转（旧 ~4.7 yr 随 9° 构型作废） |
| 外侧行星 2 轨道 | 设计通约值 0.5614 AU（= 0.3536 × 2^(2/3)）；osculating 快照 0.5684 | 共振邻接链的 osculating 值随链呼吸漂移 ±1%（历元快照见 stellar.yaml） |
| 外侧行星 3 轨道 | 设计通约值 0.8911 AU（= 0.3536 × 4^(2/3)）；osculating 快照 0.9105 | 同上 |
| 卫星轨道外迁速率 | ~{{ entities.satellite_nacrea.tidal_migration_rate_m_yr | round(4) }} m/年 | 角动量正向传递（Aegis 自转 10h 快于卫星公转 75.5h）；由 Aegis k₂/Q ≈ 7×10⁻⁸ 设定（与 Nacrea 自身 Q 无关）；自形成累计外迁 ~10% |

---
