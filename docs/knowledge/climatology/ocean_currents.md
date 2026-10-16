# 洋流物理学

表层洋流的两大驱动机制（风生与热盐）、海峡"闸门"动力学与年际变率。
本文是 roadmap 3A.3（洋流 + 温度精细化）的科学底座。

## 1. 风生环流

### 1.1 Ekman 层

风应力通过科氏力驱动表层流：表面流偏向风向 **45°**（北半球右偏、南半球左偏），
深度积分的 Ekman 输运偏风向 **90°**；表层流速约为风速的 **2%**。

```
u_surface ≈ 0.02 · |wind|,  direction = rotate(wind, ±45°·sign(φ))
```

源码：`engine/climate_physics.py:ekman_current_direction()`（已实现、当前零引用——
3A.3 的接入点）。

### 1.2 Sverdrup 平衡与西边界强化

大洋内部经向输运由风应力旋度控制（Sverdrup 1947）：

```
β · V = curl_z(τ) / ρ₀        β = df/dy（Rossby 参数）
```

Sverdrup 输运在西岸集中返回，形成**西边界强化**暖流（Gulf Stream / 黑潮型，
Stommel 1948 的 β 项 + 底摩擦机制；宽度 ~100 km、流速 ×3–10）。

**Stommel 边界层宽与亚网格急流（E4，2026-09-16 落地）**：摩擦边界层宽
δ = R/β——地球 β(30°) ≈ 1.6×10⁻¹¹ m⁻¹s⁻¹、R = 10⁻⁶ s⁻¹ → δ ≈ 62 km（~1 格）；
nacrea（Ω=0.318）δ ≈ 165 km（~3 格）。51 km CVT 网格 + 图拉普拉斯数值粘性把
ψ 梯度摊过数格，解出的核心流速系统性低估（观测 WBC 100–250 cm/s vs 解析
p90 ~1 cm/s）。引擎修法（`apply_subgrid_wbc_boost`）：从已解 ψ 解析恢复急流速度
u_jet = ψ_max/(R/β)，注入强化核（|ψ| ≥ 0.9·ψ_max，方向不变、封顶 25×），
Sverdrup 内区不动。

**极向海洋热输送（OHT）标定数（Trenberth & Caron 2001）**：地球峰值 OHT ≈
1.7–2.2 PW（±20–30°，NCEP/ECMWF 两套再分析的能量收支残差法；大西洋 26.5°N
RAPID 锚定 ~1.25 PW）；大气输送峰 ~3.4–5 PW → 洋柱总输送 ~2.9 PW 量级、
海洋份额 ~0.65。引擎的扩散型 OHT（`_OHT_COLUMN_WM2K` = 0.37 W/m²/K，
按地球开洋对比度 30 K 标定）隐含峰值柱输送 ~2.9 PW，与该份额分解一致；
世界间变化按「海洋份额（风驱，不随 Ω 标度）+ 大气份额（Ω^−0.3）」加权。

### 1.3 环流圈形态

副热带环流圈（信风 + 西风驱动）约以 ±30° 为中心；高纬为副极地环流。
慢自转行星（科氏力弱）环流圈尺度更大、西边界更宽——nacrea（Ω=0.31 Ω⊕）
的环流形态不应照地球五圈模板。

### 1.4 海气热交换与 SST 异常衰减

表层 SST 异常（偏离大气平衡温度）被海气热交换线性耗散（Haney 1971）：

```
Q = λ · (T_eq − T_sst)      λ ≈ 34 W/(m²·K)（≈ 70 ly day⁻¹ °C⁻¹，随纬度 ±20%）
```

λ 是**海气阻尼系数**，由纬向-时间平均的海气热通量数据标定。由此得 SST 异常的
e-folding 衰减时间：

```
τ = ρ_w · c_p · H_ml / λ
```

- ρ_w = 1025 kg/m³（海水密度）、c_p ≈ 4000 J/(kg·K)（海水比热）、
  H_ml ≈ 50 m（混合层深度）；
- 代入得 τ ≈ 60–70 天（Frankignoul & Hasselmann 1977 用 46 m 混合层得 ~40 天；
  副热带 λ 较弱时 τ 可达 200–400 天）。

**世界构建用途**：暖流（西边界流）把暖水向极地搬运的空间尺度
L = |u|·τ —— 这是洋流对气候影响的距离标度，也是引擎 SST 平流
（`ocean_circulation.py` 的 semi-Lagrangian 回溯距离）的物理依据。

## 2. 热盐环流（温盐环流）

密度差（温度 + 盐度）驱动的深层环流，时间尺度千年。对世界构建而言重要的不是
环流本身，而是它的**多稳态**：

### 2.1 Stommel 两盒模型

两个互通水盒（赤道暖盒 / 极地冷盒），温度与盐度对密度的贡献相反时，存在
**两个稳定分支**（温度主导的"强环流"与盐度主导的"弱/反转环流"），
 freshwater 微扰可触发跃迁（Stommel 1961；Cessi 1994 给出含噪声的跃迁阈值）。

**世界构建用途**：气候临界态的现成机制——海峡开合 / 冰盖融水 = 微扰源，
环流"开/关" = 两种气候态（年轻地球事件、Heinrich 事件的类比）。

## 3. 海峡"闸门"动力学

地形约束的通道能通过少量但关键的热/盐输送，且对几何与海平面高度敏感：

| 地球案例 | 机制 | 气候后果 |
|----------|------|----------|
| **印尼贯穿流（ITF）** | 太平洋→印度洋唯一低纬通道，~15 Sv 暖水；流量受海峡宽度/深度与两侧压差控制 | 调制两大洋 SST 梯度与 ENSO/IOD 耦合（Wijffels et al. 2008） |
| **巴拿马地峡闭合**（~3 Ma） | 切断太平洋-大西洋表层交换 | 湾流强化 → 北欧变暖加湿 + 北半球冰期启动的争论案例 |
| **德雷克海峡开启**（~34 Ma） | 环极通道 → 绕极流（ACC）隔离南极 | 南极冰盖形成 |
| **冰期海平面闸门** | 海平面 −120 m → 巽他陆架暴露、ITF 通道近乎关闭 | 通道截面积对海平面呈非线性响应 |

**临界性三要素**（构造"小因大果"剧情的检查单）：
1. 几何瓶颈——流量 ∝ 通道截面积，浅峡（<200 m）对海平面/沉积/火山岛敏感；
2. 双稳态背景——热盐或风生环流存在两种构型；
3. 微扰放大器——周期性强迫（潮汐、季节）或单事件（地震、岛弧火山）触发跃迁。

源码/设计接口：geography.yaml 的 `isthmus`/`shallow_sea` feature + 高程锚定

### 3.1 水力控制：输运随门槛水深的标度

门槛（sill）是海峡中最浅的截面。门槛之上的输运受水力控制，可以用三个公式估计：

- **窄海峡，非旋转溢流**：Q ≈ (2/3)^{3/2} · W · √g′ · h^{3/2} ≈ 0.54 · W · √g′ · h^{3/2}。W 是海峡宽度，g′ = g·Δρ/ρ 是
  两侧密度差对应的约化重力，h 是上游界面高出门槛的高度（Whitehead 1998 的综述）。
- **宽海峡，旋转限制**：Q_max = g′h² / (2f)，f 是科氏参数。这个上限与宽度无关（Whitehead, Leetmaa & Knox 1974）。
- **两层交换**：密度不同的两股水反向通过海峡时，存在最大交换流量，由门槛和收缩段共同控制（Farmer & Armi 1986）。

判断用哪个公式，比较宽度 W 与内 Rossby 半径 L_R = √(g′h) / f：W ≲ L_R 时旋转不限制流量，用溢流公式；W ≫ L_R
时用旋转上限；实际流量大约取两者中的较小值（Pratt 1991）。

两种情况下输运都随 h 的 1.5–2 次方变化，相对灵敏度 dQ/Q ≈ (1.5–2)·dh/h。海平面接近门槛时 h → 0，输运迅速归零，
所以门槛浅的海峡在海平面变化中是阈值开关；门槛深的海峡不会关闭，但输运随海平面单调调制。

**自转速率的影响。** 科氏参数 f = 2Ω sin φ 与自转角速度 Ω 成正比。自转越慢，L_R 越大，更多海峡落入「窄海峡」
区间；对宽海峡，旋转上限 g′h²/(2f) 与 Ω 成反比。例如自转角速度为地球 0.32 倍的行星，同样几何与密度差的宽海峡
可以通过约 3 倍的输运，海峡在热量和盐分输送中的份量相应变重。

### 3.2 地球上的海平面门控案例

| 海峡 | 门槛与宽度 | 现代输运 | 开合的气候效应 |
|---|---|---|---|
| 白令海峡 | 约 50 m 深、约 85 km 宽 | 约 0.8 Sv（1990 年代）增至约 1.0 Sv（2010 年代）（Woodgate 2018） | 海平面低于约 −50 m 时关闭。开着时北大西洋的低盐异常可以被冲入太平洋，翻转环流更稳定；关闭后异常被困在大西洋，翻转环流出现滞回（De Boer & Nof 2004；Hu et al. 2012）；海平面回升重开时较淡的水进入北大西洋（Hu et al. 2010） |
| 曼德海峡（红海出口） | 门槛约 137 m | 冬季交换不足 1 Sv | 冰期海平面约 −120 m 时门槛只剩数十米，红海停留时间暴增、盐度出现极值；Siddall et al. 2003 用这套水力交换模型从红海氧同位素反演冰期海平面 |
| 直布罗陀海峡 | 门槛约 284 m | 两层交换，约 0.7–0.9 Sv（Bryden & Kinder 1991） | 墨西拿盐度危机期间（约 5.97–5.33 Ma）地中海与外海隔绝、蒸发干涸（Hsü et al. 1973；Krijgsman et al. 1999）；重新连通时的洪水在数年内灌满地中海（Garcia-Castellanos et al. 2009） |
| 格陵兰–苏格兰海脊 | 丹麦海峡门槛约 620 m | 溢流合计约 6 Sv（Dickson & Brown 1994） | 溢流受水力控制，符合 g′h²/2f 的估算（Whitehead 1998）；新生代海脊下沉被认为控制了北大西洋深层水的出现（Wright & Miller 1996） |
| 印尼贯穿流 | 多个通道，门槛数百米 | 约 15 Sv（Gordon 2005；Sprintall et al. 2014） | 冰期巽他陆架出露、浅通道收窄；约 3–4 Ma 新几内亚北移使水源改为北太平洋冷水，印度洋表层变冷，东非随之变干（Cane & Molnar 2001） |

表中门槛深度与曼德海峡、直布罗陀海峡的输运是常用的海洋学数值，未逐一对应到单篇文献；使用时以量级为准。

### 3.3 诊断工具

`scripts/climate/diagnose_ocean_gateways.py` 在世界网格上找出门槛落在给定海平面窗口内的海峡：分隔型（某片
水体的唯一出口，给出门槛深度与被断开的面积）与捷径型（关闭后两侧仍连通但需绕行，给出绕行倍数），并估计
门槛处宽度随海平面的变化。海平面本身随温度的变化见 [sea_level.md](sea_level.md)。
详见 `docs/design/pipelines/geological-pipeline.md` §3.5（高程锚定 + sea_level_offset_m）

## 4. 年际变率：ENSO 类振荡

海气耦合反馈（Bjerknes 1969）：信风减弱 → 东太平洋暖水东涌 → 信风进一步减弱。
产生 2–7 年准周期振荡，无需外部强迫（自激振荡）。**大陆把大洋割裂成半孤立水体时，
振荡幅度放大、周期失谐**——虚构先例：乐意 Ajax《季风世界》的"涛动期"
（洋流翻转周期 4 月–10 年不可预测，见
乐意 Ajax《季风世界》EP1 视频分析）。

对 dreamulator：稳态 EBM 无年际模态；最小可行版 = 风应力与温度梯度博弈的
双驱动表层流 + 海峡水力学约束流（roadmap 3A.3）。

## 5. 与引擎的对应关系

| 知识 | 引擎模块 / 计划 | 状态 |
|------|----------------|------|
| Ekman 偏转 45° / 流速 2% | `climate_physics.py:ekman_current_direction()` | ✅ 已实现、待接入 |
| 西边界强化 / 沿岸热输送 | roadmap 3A.3 子任务表 | 📋 |
| 上升流（东边界离岸风） | roadmap 3A.3 子任务表 | 📋 |
| 海峡水力学约束流 | `map/ocean_circulation.py:detect_straits()`、`compute_strait_flux()`（已实现，未接入管线）；海平面敏感海峡诊断 `scripts/climate/diagnose_ocean_gateways.py` | 📋 设计 |
| 海洋省份子省（WBC/EBC/GYRE…） | 3A.5 Phase 2，见 `ocean_provinces.md` | 📋 |
| 热盐多稳态 / ENSO 时变 | 长期愿景（简化 GCM 之后） | ❌ |

## 6. 数值求解：GMRES（稀疏线性系统）

dreamulator 的洋流 / 气候扩散都归结为「稀疏线性系统 A·x = b」的求解，统一用
**GMRES**（Generalized Minimal RESidual，Saad & Schultz 1986）：

- **Stommel 流函数**（`ocean_circulation.py:solve_ocean_gyre`）：
  β ∂ψ/∂x + R∇²ψ = curl(τ)/(ρ_w H)，算子**非对称**（β 平流项），CG 不适用，
  GMRES 是标准选择。
- **图扩散**（温度 anomaly 输送 `ocean_circulation.py:advect_temperature_anomaly`）：
  (I + αL) q = source，算子**对称正定**（对称化的 wind-biased graph Laplacian），
  理论上可用 CG，但用 GMRES + 对角预处理以复用同一套求解管线。水汽收支
  （`climate_simulator.py:_solve_moisture_budget`）的迎风 + 扩散算子则是非对称
  M-矩阵，用直接稀疏 LU（splu）精确求解。

### 数学

GMRES 是 Krylov 子空间方法：第 k 步从 x₀ + K_k(A, r₀)（Krylov 子空间
span{r₀, Ar₀, …, A^{k−1}r₀}）中取残差 ‖b − Ax‖₂ 最小的 x；等价于用 Arnoldi 迭代
把 A 约化为上 Hessenberg 阵 H_k，再解一个小型最小二乘问题。

- **特点**：对一般非对称矩阵收敛稳健；但每步需存储整个 Krylov 基（内存 O(k·n)），
  故需限制迭代上限或重启（本引擎 `maxiter=200`、`rtol=1e-3`）。
- **预处理**：对角（Jacobi）预处理 `M = diag(|A_ii|)`，把迭代数大致减半
  （`solve_ocean_gyre` 已用）。

### 适用场景（未来引擎复用）

任何「图上的线性算子求稳态解」都可用 GMRES：扩散/平流、泊松方程、热传导、
多孔介质渗流……只要能把物理写成 A·x = b 的稀疏形式，GMRES + 对角预处理就是
开箱即用的求解器。scipy 实现：`scipy.sparse.linalg.gmres`。

## 参考资料

- Stommel, H. (1948). "The theory of the electric field induced in deep ocean currents."
- Stommel, H. (1961). "Thermohaline convection with two stable regimes." *Tellus 13*.
- Cessi, P. (1994). "A simple box model of stochastically forced thermohaline flow." *JPO 24*.
- Sverdrup, H. (1947). "Wind-driven currents in a baroclinic ocean." *PNAS 33*.
- Wijffels, S. et al. (2008). "Changing Exchanges in the Maritime Continent." *Oceanography 21*.
- Bjerknes, J. (1969). "Atmospheric teleconnections from the equatorial Pacific." *MWR 97*.
- Haney, R. L. (1971). "Surface thermal boundary condition for ocean circulation models." *J. Phys. Oceanogr.* 1(4), 241–248.
- Frankignoul, C., & Hasselmann, K. (1977). "Stochastic climate models, Part II: Application to sea-surface temperature anomalies and thermocline variability." *Tellus* 29(4), 289–305.
- Trenberth, K. E., & Caron, J. M. (2001). "Estimates of Meridional Atmosphere and
  Ocean Heat Transports." *J. Climate* 14, 3433–3443.
- Saad, Y., & Schultz, M. H. (1986). "GMRES: A generalized minimal residual algorithm for solving nonsymmetric linear systems." *SIAM J. Sci. Stat. Comput.* 7(3), 856–869.
- Whitehead, J. A., Leetmaa, A. & Knox, R. A. (1974). "Rotating hydraulics of strait and sill flows." *Geophys. Fluid Dyn.* 6. doi:10.1080/03091927409365790
- Whitehead, J. A. (1998). "Topographic control of oceanic flows in deep passages and straits." *Rev. Geophys.* 36. doi:10.1029/98RG01014
- Pratt, L. J. (1991). "Hydraulics of rotating strait and sill flow." *Annu. Rev. Fluid Mech.* 23. doi:10.1146/annurev.fluid.23.1.81
- Farmer, D. M. & Armi, L. (1986). "Maximal two-layer exchange over a sill and through the combination of a sill and contraction with barotropic flow." *J. Fluid Mech.* 164. doi:10.1017/s002211208600246x
- Woodgate, R. A. (2018). "Increases in the Pacific inflow to the Arctic from 1990 to 2015." *Prog. Oceanogr.* 160. doi:10.1016/j.pocean.2017.12.007
- De Boer, A. M. & Nof, D. (2004). "The Bering Strait's grip on the northern hemisphere climate." *Deep-Sea Res. I* 51. doi:10.1016/j.dsr.2004.05.003
- Hu, A. et al. (2010). "Influence of Bering Strait flow and North Atlantic circulation on glacial sea-level changes." *Nat. Geosci.* 3. doi:10.1038/ngeo729
- Hu, A. et al. (2012). "Role of the Bering Strait on the hysteresis of the ocean conveyor belt circulation and glacial climate stability." *PNAS* 109. doi:10.1073/pnas.1116014109
- Siddall, M. et al. (2003). "Sea-level fluctuations during the last glacial cycle." *Nature* 423. doi:10.1038/nature01690
- Bryden, H. L. & Kinder, T. H. (1991). "Steady two-layer exchange through the Strait of Gibraltar." *Deep-Sea Res. A* 38. doi:10.1016/s0198-0149(12)80020-3
- Hsü, K. J., Ryan, W. B. F. & Cita, M. B. (1973). "Late Miocene desiccation of the Mediterranean." *Nature* 242. doi:10.1038/242240a0
- Krijgsman, W. et al. (1999). "Chronology, causes and progression of the Messinian salinity crisis." *Nature* 400. doi:10.1038/23231
- Garcia-Castellanos, D. et al. (2009). "Catastrophic flood of the Mediterranean after the Messinian salinity crisis." *Nature* 462. doi:10.1038/nature08555
- Dickson, R. R. & Brown, J. (1994). "The production of North Atlantic Deep Water: sources, rates, and pathways." *JGR Oceans* 99. doi:10.1029/94JC00530
- Wright, J. D. & Miller, K. G. (1996). "Control of North Atlantic Deep Water circulation by the Greenland-Scotland Ridge." *Paleoceanography* 11. doi:10.1029/95pa03696
- Gordon, A. L. (2005). "Oceanography of the Indonesian Seas and their throughflow." *Oceanography* 18. doi:10.5670/oceanog.2005.01
- Sprintall, J. et al. (2014). "The Indonesian seas and their role in the coupled ocean–climate system." *Nat. Geosci.* 7. doi:10.1038/ngeo2188
- Cane, M. A. & Molnar, P. (2001). "Closing of the Indonesian seaway as a precursor to east African aridification around 3–4 million years ago." *Nature* 411. doi:10.1038/35075500
