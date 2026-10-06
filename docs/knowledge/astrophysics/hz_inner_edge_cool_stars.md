# 晚型星宜居带内缘与失控温室（光谱依赖 + 复杂生命约束）

> 2026-10-06 自 nacrea 路线 1 辐照重标定调研沉淀。基础宜居带公式见
> `stellar_physics.md`；本文覆盖三个进阶层：内缘的光谱型依赖、1D/3D 之争、
> 以及叠加动物生理约束后的「三难结构」。引擎实现 =
> `src/dreamulator/engine/stellar_physics.py`（`HABITABLE_ZONE_COEFFICIENTS`
> + `habitable_zone_boundaries()`，系数已对齐 Kopparapu 官方现行表）。

## 1. Kopparapu 框架与官方系数

宜居带边界以「有效恒星通量」S_eff（单位 S⊕）表达，边界距离
d = √(L/L☉ ÷ S_eff)。S_eff 随恒星光谱型变化，用四次多项式拟合：

```
S_eff = S_eff⊙ + a·T* + b·T*² + c·T*³ + d·T*⁴ ，  T* = T_eff − 5780 K
```

**官方现行系数表**（Kopparapu Penn State HZ 计算器分发的
HZ_coefficients.dat，= 2013 ApJ 765:131 + 勘误 ApJ 770:82 + 2014 ApJL
787:L29 的 1 M⊕ 质量依赖更新；转引文献常混用各版本，引用前必须对表）：

| 边界 | S_eff⊙ | a | b | c | d |
|------|--------|---|---|---|---|
| Recent Venus（乐观内缘） | 1.776 | 2.136e-4 | 2.533e-8 | −1.332e-11 | −3.097e-15 |
| Runaway Greenhouse（保守内缘） | **1.107** | 1.332e-4 | 1.580e-8 | −8.308e-12 | −1.931e-15 |
| Maximum Greenhouse（保守外缘） | 0.356 | 6.171e-5 | 1.698e-9 | −3.198e-12 | −5.575e-16 |
| Early Mars（乐观外缘） | 0.320 | 5.547e-5 | 1.526e-9 | −2.874e-12 | −5.011e-16 |

版本陷阱：RG 截距 1.045（2013 原版）≠ 1.107（2014 质量依赖版，现行
官方表采用）；勘误版对外缘改 1.70→1.67 AU。质量依赖：RG 是唯一随行星
质量变的边界（5 M⊕ → S_eff⊙ 1.188；0.1 M⊕ 更低），1 M⊕ 表用于 ≤2 M⊕
世界误差 <0.5%（nacrea 1.2 M⊕）。

**各谱型阈值**（引擎实算，L=1 L☉ 归一的 S_eff）：

| 谱型 | T_eff (K) | S_RV | S_RG | S_MG | S_EM |
|------|-----------|------|------|------|------|
| F5 | 6510 | 1.939 | 1.209 | 0.401 | 0.360 |
| G2 | 5772 | 1.774 | 1.106 | 0.356 | 0.320 |
| K0 | 5270 | 1.675 | 1.044 | 0.325 | 0.292 |
| K5 | 4375 | 1.551 | 0.967 | 0.279 | 0.251 |
| K8 | 4055 | 1.524 | 0.950 | 0.266 | 0.239 |
| M0 | 3870 | 1.512 | 0.942 | 0.259 | 0.233 |
| M3 | 3410 | 1.492 | 0.930 | 0.244 | 0.220 |
| M5 | 3050 | 1.481 | 0.923 | 0.234 | 0.211 |

规律：**恒星越冷，触发失控温室所需的通量越低**（S_RG 从 G2 的 1.11 降到
M5 的 0.92 后渐近饱和）；四个边界同向移动，保守 HZ 在 S_eff 单位下整体
下移 ~17%（G2→M5）。地球（S_eff=1.0）对太阳的 RG 余量是 10%——「地球
靠近内缘住」本身就是这个框架的著名结论。

## 2. 物理机制：NIR 高层吸收的双通道效应

冷恒星辐射集中在近红外（NIR）：黑体 <0.75 μm 能量份额从 G2 的 0.517 降到
K8 (4055 K) 的 0.28、M5 的 ~0.17（ExoPlaSim 的 solarini 按此做两带分割，
plasim_diag 打印「Energy fraction below 0.75 microns」）。H2O 与 CO2 在
NIR 有强吸收带，于是同一个「高层大气吸收恒星 NIR」事件产生两个**方向
相反**的后果：

- **地表温室削弱（自下而上通道）**：NIR 能量在到达地表前被中高层大气截
  走，地表只能靠向下长波加热——同等气体柱的地表增温效率下降。ExoPlaSim
  GCM 实测（nacrea，0.3 bar CO2，4055 K 光谱）：温室 G ≈ 45 W/m²，比按
  G2 光谱标定的对数律估算低约 1/3。
- **失控温室提前（自上而下通道）**：runaway 的本质不是「地表过热」而是
  **湿平流层失控**——NIR 吸收恰好沉积在对流层顶/平流层附近，直接加热控制
  水汽逃逸的冷阱层；饱和水汽压随温度指数上升，平流层在更低的入射通量下
  变湿，水汽（最强温室气体）进入高层正反馈 → RG 阈值 S_RG 下降。

直觉冲突「温室难提升 ⇒ RG 应宽松」的消解：**NIR 高层吸收对地表是遮阳，
对冷阱是加热**——前者稳定地表温度，后者提前触发逃逸不稳定性。两者是同一
枚硬币的两面，不矛盾。

## 3. 1D 与 3D 之争：内缘其实更宽

第 1 节的 S_RG 来自 1D 辐射-对流模型。3D GCM 系统性地放宽内缘：

- Leconte et al. (2013, A&A 554, A58)：潮汐锁定行星的日下点大范围下沉干区
  高效守住冷阱 + 日面云反射，慢自转行星可承受 ~2× 于 1D 预测的通量。
- Kopparapu et al. (2016, ApJ 819, 84)：用 3D GCM 专算低质量星同步自转
  行星内缘，确认 1D 值偏保守。
- Kopparapu et al. (2017, ApJ 845, 5)：把内缘物理拆成 **moist greenhouse
  （渐进失水，Gyr 尺度，地表仍可居）vs runaway（真失控悬崖）**——越过后
  者的通量下，前者才是实际约束；金星可能以 moist 状态宜居过很久
  （Way et al. 2016）。

使用守则：**1D 保守值用于筛选与安全余量，3D/moist 框架用于个案评估**。
自转 1-10 d 的行星（含非同步的慢自转）都享受部分 3D 放宽；快速自转
（<1 d）更接近 1D 值。

## 4. 复杂生命约束层：HZ_CL 与三难结构

经典 HZ 只问「液态水」（微生物也算）。叠加动物生理约束后：

- **CO2 毒性**：Schwieterman et al. (2019, ApJ 876, 32)——CO2 耐受
  0.01/0.1/1 bar 对应的「复杂生命宜居带」HZ_CL 只有经典 HZ 宽度的
  **21%/32%/50%**，且偏向内缘（那里所需 CO2 最少）。对冷星更严苛：经典
  HZ 本就压缩，外半区所需 CO2 全部超标 → HZ_CL 是内缘的一条窄带。
  Ramirez (2020) 给出基于脂溶性的替代毒性口径（结论同向）。
- 地球型动物的经验上限：CO2 > 1%（10⁴ ppm）慢性中毒、>5% 急性；C3 植物
  >3000 ppm 气孔调节失效。
- **三难结构**（世界构建的定量形态）：目标温度 Ts、大气 pCO2 上限
  （生理）、RG 内缘余量（安全）三者不可兼得，只能选二。因为
  ΔF = 5.35·ln(C/C₀) 对能量缺口指数敏感（±5 W/m² → pCO2 ×/÷2.5），
  而冷星的 NIR 惩罚又抬高达到同一 Ts 所需 pCO2（§2）：
  - 暖世界（Ts≥12°C）+ 可呼吸（pCO2<1%）→ 需 S_eff 贴近 RG 阈；
  - 暖世界 + 安全余量 → pCO2 达 %级（非地球型生理或 CH4 辅助）；
  - 可呼吸 + 安全余量 → Ts 降到 8-10°C 的凉世界。
- 逃逸阀：CH4 辅助温室（太古宙方案，100-400 ppm 抵 20-40 W/m²）——但
  O2 大气下 CH4 光化学寿命 ~10 yr，维持百 ppm 级需 10²-10³× 现代地球
  生物通量；火山 CH4 只能撑 ~1-2 ppm（岩浆气 CH4/CO2 ~10⁻⁴-10⁻³）。

## 5. 碳酸盐-硅酸盐稳态的火山标度（pCO2 的来源侧）

长期 pCO2 由脱气-风化平衡设定：V_outgas = W(pCO2)，W ∝ W⊕·(pCO2/280)^n·
f(T)·f(径流)·f(地形/岩性)，n ≈ 0.3-0.5。稳态解
pCO2_ss = 280·(V/W⊕eff)^(1/n) ——**指数 1/n ≈ 2-3.3 把脱气率的不确定度
放大一个量级**，这是 pCO2 第一性估算天然带 ±×2-3 误差带的原因。潮汐
加热驱动的火山区（热流数×地球、板块速度数×地球 → 脱气 2.5-4×⊕）配合
冷气候风化折扣（f(T)~0.6-0.7），稳态落 ~0.01-0.03 bar——世界设定里
「增强火山」正是维持 %级 CO2 大气的第一性解释。脉冲式脱气（周期 ≫ 风化
响应时标 n×滞留时间）会按 1/n 放大为 pCO2 振荡 → 火山驱动的冰期旋回
（vs 轨道驱动）在定量上成立的条件：脉冲幅度与均值脱气率要保证谷值不跌破
无冰下限。ExoPlaSim 的 carbonmod（VOLCANCO2 以地球脱气为单位）可直接
数值验证该稳态。

## 6. 世界构建启示（nacrea 案例指针）

- 「暖 + 可呼吸 + 厚 CO2 正典」在冷星辐照下会被 GCM 否证（雪ball 平衡）；
  出路 = 提恒星质量（三重红利：通量↑、光谱蓝移 NIR 惩罚↓、S_RG 阈回升）
  + 轨道微调 + Ts 目标重设。完整推导与候选参数组见
  `docs/design/proposals/nacrea-insolation-recalibration.md`。
- 均匀缩放共振链（a 全表同乘）严格保持通约比——改辐照而不动链结构的
  标准手法；N 体认证需重跑，但引力判决按周期单位尺度不变。

## 学术参考

- Kopparapu, R. K., et al. (2013). Habitable Zones around Main-Sequence
  Stars: New Estimates. *ApJ*, 765(2), 131.（+ Erratum: *ApJ*, 770, 82）
- Kopparapu, R. K., et al. (2014). Habitable Zones around Main-Sequence
  Stars: Dependence on Planetary Mass. *ApJL*, 787, L29.
- Kopparapu, R. K., et al. (2016). The Inner Edge of the Habitable Zone for
  Synchronously Rotating Planets around Low-Mass Stars Using GCMs. *ApJ*,
  819, 84.
- Kopparapu, R. K., et al. (2017). Habitable Moist Atmospheres on Terrestrial
  Planets near the Inner Edge of the Habitable Zone around Low-Mass Stars.
  *ApJ*, 845, 5.
- Leconte, J., et al. (2013). 3D climate modeling of close-in land planets:
  Circulation patterns, climate moist instabilities, and habitability.
  *A&A*, 554, A58.
- Schwieterman, E. W., et al. (2019). A Limited Habitable Zone for Complex
  Life. *ApJ*, 876, 32.
- Ramirez, R. M. (2020). A Complex Life Habitable Zone Based on Lipid
  Solubility. *ApJL*, 892, L18.
- Way, M. J., et al. (2016). Was Venus the First Habitable Planet of our
  Solar System? *GRL*, 43, 8376.
- 官方系数表：https://personal.ems.psu.edu/~jfk4/ruk15/planets/
  （HZ_coefficients.dat）
