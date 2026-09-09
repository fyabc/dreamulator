---
title: "长周期气候循环与变率谱"
type: cycles
tags: [milankovitch, laplace-resonance, tidal-heating, secular-evolution, climate-variability]
---

# 长周期气候循环与变率谱

Nacrea 是一颗**外侧邻近为双单体逆行捕获卫（韵珠、守珠）的巨行星卫星**——它的长周期气候强迫谱
与地球既相似（有"米兰科维奇式"轨道调制）又有本质不同（卫星特有的潮汐加热振荡、
行星-卫星几何效应）。本文档列举各强迫源的机制、时标、量级与当前引擎建模状态，
作为未来气候变率建模的世界设定依据。

基准日照：Ignis（{{ entities.star_ignis.luminosity_sol }} L☉）@ {{ entities.planet_aegis.semi_major_axis_au }} AU → **{{ entities.satellite_nacrea.instellation_earth_ratio | round2 }} S⊕**（方案2 校准后位于本系统
保守宜居带几何中心附近；参见 `habitable_zones.yaml`）。

## 强迫谱总览

| # | 机制 | 时标 | 日照/热通量调制量级 | 引擎状态 |
|---|------|------|---------------------|----------|
| 1 | 食与行星反照相位（几何效应） | 78–81 h + 食季（~每年两次） | 瞬时 ~3%（食）；年均 <0.1% | 未建模；量级可忽略 |
| 2 | 轨道面交点进动 → 季节相位漂移 | ~1–10 yr（J₂ 与太阳力矩同向叠加） | 黄赤交角恒定 9°（振幅不变），仅季节历法相位漂移 | 未建模；对年均气候无影响，移动食季与至点的历法对应 |
| 3 | 行星共振链摆动 → 偏心率调制 | **~45 kyr（1 Myr N 体积分确认）** | Aegis e 0.016–0.062 摆动 → 季节日照对比 ±3–12% | 未建模；**类米兰科维奇冰期旋回（地球 41 kyr 倾角旋回同量级）** |
| 4 | 潮汐加热振荡 ⭐**卫星特有**「万年活动周期」 | **~10⁴ yr**（韵珠/守珠长期摄动拍频） | e_m 受迫带 0.002–0.007（设计意图带，历元 0.0018；硬度豁免见 design-notes/0009）→ 地质热通量 0.25–3.3 W/m²（均值 ~0.5） | 未建模；经火山-CO₂ 通路影响气候；**设定特色节律** |
| 5 | 长期摄动与系统稳定性 | 10⁴–10⁶ yr | Sentinel（e=0.18, i=7°）远距摄动；韵珠/守珠均单体准可积（径向净空 28 r_H,m，Gyr 级，REBOUND 三层认证） | 未建模；生态/宜居窗口时标 |
| 6 | 潮汐演化长期漂移 | Gyr | 卫星外迁（已形成以来 +10%）；加热衰减 → 火山 3×⊕ 递减 → CO₂ 源衰减 | 未建模；碳-硅酸盐循环长期平衡 |
| 7 | 恒星演化 | Myr–Gyr | Ignis（K8）前主序阶段曾亮数倍（~1 Gyr）；主序缓慢增亮 | 天文层已有恒星演化模型（evolution_progress={{ entities.star_ignis.evolution_progress | round2 }}）；未耦合气候 |

## 1. 短周期几何效应（78–81 h）

- **食**：Aegis 角直径 ~{{ sky.planet_aegis.angular_diameter_deg | round0 }}°（{{ entities.planet_aegis.radius_km | round0 }} km @ {{ sky.planet_aegis.distance_km | round0 }} km）远大于 Ignis 的 ~{{ sky.star_ignis.angular_diameter_deg | round1 }}°，
  对齐时全食。轨道倾角 9° → 每年两个食季，每次全食 ≤ ~2.4 h（轨道速度 ~16.5 km/s，
  影锥宽 ~2 R_Aegis）。年均能量损失 <0.1%——气候上可忽略，是大气/天气尺度的
  周期性事件（对生态节律、文化叙事有意义）。
- **行星反照与热辐射（经度不对称源）**：Aegis（Bond 反照率 0.343，R=71,355 km，
  距 {{ sky.planet_aegis.distance_km | round0 }} km）对次 Aegis 半球的附加通量：热红外 ~1.4 W/m²（全相位恒定）+
  反射光 ~2.0 W/m²（局地午夜满相位峰值），均远小于日照 {{ entities.satellite_nacrea.instellation_w_m2 | round0 }} W/m²
  （全球年均 <0.3%）。**但这是经度项而非全球项**：次 Aegis 半球均增温
  ~1°C（半球均值 ~1–1.5 W/m²），打破纬向对称 →
  Aegis 面大陆夜温较高、蒸发与大气持水能力较高 → 整体较同纬度反 Aegis
  大陆更湿润。结论：**全球平均气候中可忽略，区域气候格局中不可忽略**。
  当前引擎无此强迫（温度场 = 纬向平均 + 地形），属气候精度路线
  （`docs/design/climate-engine.md` Phase 3A.7）；温室预算已为此预留 +3 K。

## 2. 交点进动与季节相位漂移（~1–10 yr）

Nacrea 的有效黄赤交角恒为 **{{ entities.satellite_nacrea.axial_tilt_deg | round0 }}°**（= 轨道倾角；自转轴 ⊥ 绕 Aegis 轨道面，
随轨道面一起进动），因此存在稳定的 {{ entities.planet_aegis.period_days | round0 }} 天季节循环（直射点 ±{{ entities.satellite_nacrea.axial_tilt_deg | round0 }}° 摆动，
极圈 ±{{ entities.satellite_nacrea.polar_circle_latitude_deg | round0 }}°）。卫星轨道面在太阳力矩与 Aegis J₂ 作用下交点进动：

- 太阳力矩贡献：~2 yr 周期（(n_P/n_m)² 标度）
- Aegis J₂ 贡献：~9 yr 周期（J₂≈0.02 估计，(R_P/a_m)² 标度）
- 两者同向叠加 → 合成 ~1–2 yr

效应：进动改变的是自转轴在黄道面上的指向（分点岁差），**季节振幅不变**，
但至点在轨道上的相位缓慢漂移——食季与季节的历法对应关系以年-十年尺度
移动（食季出现在"历法"中的位置不固定）。Aegis 轨道 e≈{{ entities.planet_aegis.eccentricity }} 近圆，
岁差×偏心率耦合的气候效应可忽略。进动周期已由 N 体实测确认：Aegis 自转自由进动
~550 yr、气候岁差拍频 ~540–560 yr（orbital_dynamics.md）。

## 3. 行星共振链摆动（~45 kyr，数值积分确认）

Aegis–Boreal–Glacis 1:2:4 拉普拉斯共振链的共振角存在周期摆动（libration），
交换偏心率与近日点经度。1 Myr N 体积分（REBOUND）实测：

- Aegis e 在 **0.016–0.062 摆动，周期 ~45 kyr**；近日点进动 ϖ 24–60 kyr
- 日照效应：季节对比度调制 ±2e ≈ **±3–12%**——与地球 41 kyr 倾角旋回同量级，
  天然的「压缩版米兰科维奇旋回」，驱动万年-数万年尺度的冰期/间冰期交替
- 文明层叙事锚点：气候「好坏期」的主节律为 **~45 kyr**；文明时标（千年）落在
  单个半周期内——「气候在历史中缓慢变好/变坏」的集体经验有明确天文归因，
  但完整旋回超出任何文字记录，只能靠地质/冰芯代用资料重建

## 4. 潮汐加热振荡（卫星特有，~10⁵ yr）⭐

Nacrea 的 e_m 为**受迫偏心率**——韵珠（贡献 99.6%）与守珠的长期摄动维持
0.002–0.007 受迫带（设计意图带，线性标定 e_rms≈0.0026；历元值 0.0018
为带下缘快照，机制与硬度豁免详见 design-notes/0009）。这正是 Io 机制
（Io e=0.0041 → 太阳系火山最活跃天体）。潮汐耗散 ∝ e²：

- 地质热通量在 0.25–3.3 W/m² 带内振荡（均值 ~0.5 W/m²），火山活动
  （当前设定 3×⊕）随之波动，调制周期 **~10⁴ yr（「万年活动周期」，设定
  特色节律**：火山-地热-CO₂ 的脉冲呼吸，与 §3 的 45 kyr 日照旋回构成
  双频气候节拍）
- 气候通路：火山 CO₂ 释放率振荡 → 大气温室浓度振荡 → 冰期/暖期旋回
  （与 §3 的 45 kyr 日照旋回叠加，构成双频气候节拍）
- 直接热通量（W/m² 量级）相对日照 {{ entities.satellite_nacrea.instellation_w_m2 | round0 }} W/m² 可忽略——重要的是**碳循环通路**

physical_params.md 的洛夫数（k₂=0.3, h₂=0.6）与 Q=100 即为此计算预埋的参数。

## 5. 长期摄动与系统稳定性（10⁴–10⁶ yr）

- Sentinel（3.68 AU, e=0.18, i=7°）作为远距散射体提供长期摄动
- 行星共振链 1 Myr 积分稳定；韵珠、守珠为单体远距逆行轨道（径向净空
  28 r_H,m、恒星潮汐仅有界摆动）；其 >25 kyr 长期动力学按硬度豁免处理
  （判决与豁免记录见 design-notes/0009 §2、附录 §6.7）
- Aegis e 实测峰值 0.062：§3 的 45 kyr 冰期旋回是**进行中的现实**，
  而非假设性风险；Nacrea 文明层应把「当前处于旋回哪个相位」作为设定输入

## 6. 潮汐演化长期漂移（Gyr）

Aegis 弱潮汐耗散（k₂/Q ≈ 7×10⁻⁸，Q ≈ 5×10⁶）的持续角动量正传递 → 卫星缓慢外迁
（Nacrea 形成以来 +10%，当前 ~0.8 cm/年；韵珠/守珠均 ≤7 μm/年，
泵浦源频率 Gyr 级冻结）、Aegis 自转减慢极微（<1%，10h 自转主要由早期巨撞击设定）：

- 潮汐加热率随 a_m⁻⁶ 衰减 → 火山活动 3×⊕ 将逐渐下降
- CO₂ 火山源衰减 → 碳-硅酸盐循环长期平衡点漂移 → 气候长期变冷趋势
- 与 Ignis 主序增亮（K 型橙矮星极慢）部分抵消——**宜居窗口的起止时间**是深层设定问题

## 7. 恒星演化（Myr–Gyr）

Ignis 为 K8（0.59 M☉），前主序阶段（~1 Gyr）光度可达当前数倍：

- 早期 nacrea 承受远超 runaway greenhouse 极限（0.834 S⊕）的日照
  → **早期湿温室风险**：原始水库存是否部分散失？当前 72% 海洋覆盖是幸存结果
  还是需要设定更大的初始水量？
- 天文引擎已计算 evolution_progress={{ entities.star_ignis.evolution_progress }}（主序寿命 {{ entities.star_ignis.ms_lifetime_gyr | round1 }} Gyr 的 {{ entities.star_ignis.evolution_progress | pct }}）——
  未来可将恒星亮度时间序列耦合进气候层

## 业界参照与引擎接口

- **GCM/地球系统模型（CESM、MPAS 等）**：不自行积分轨道动力学；古气候模式
  （PMIP 协议）把偏心率/倾角/进动作为**边界条件输入**（来自 Berger 1978 /
  Laskar La2004 天文解），按组跑快照。米兰科维奇动力学是天体力学求解器的职责。
- **世界生成引擎（Gleba、Azgaar 等）**：均只生成静态"当前态"气候，无人建模
  长周期循环。
- **本引擎路线**：天文层是轨道动力学的 UV 理论——未来可在其 derived 中增加
  "长期摄动谱"（拉普拉斯-拉格朗日线性长期解，纯 numpy 线性代数，毫秒级）：
  各天体 e/i 调制时标 + 振幅。下游层消费**积分掉的统计量**（气候变率包络、
  火山活动调制幅度、气候稳定性指数），而非振荡本身——与引擎"层级 = 有效场论"
  的架构纪律一致（各层积掉下层快自由度，在下游相关可观测量上匹配）。
- **不适用的粒度**：章动级细节（地球 18.6 yr / 9 角秒量级）在任何层均无关，
  不建模。

## 参考

- Berger, A. (1978). Long-term variations of daily insolation and Quaternary climatic changes. *J. Atmos. Sci.* 35, 2362–2367.
- Laskar, J. et al. (2004). A long-term numerical solution for the insolation quantities of the Earth. *A&A* 428, 261–285.
- Heller, R. & Barnes, R. (2013). Exomoon habitability constrained by illumination and tidal heating. *Astrobiology* 13, 18–46.
- Rosing, M. T. et al. (2010). The rise of continents—testing and predictions in the New Supercontinent Cycle. *Palaeogeogr. Palaeoclimatol. Palaeoecol.* 294, 174–192.
- Izidoro, A. et al. (2017). Formation of the TRAPPIST-1 system by migration （本星系共振链形成机制）.
