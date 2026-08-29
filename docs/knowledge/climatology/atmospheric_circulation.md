# 大气环流

dreamulator 风场的科学基础与实现映射：科里奥利参数、三胞环流、地转风与
热成风式的温度-气压耦合。本文为 `climate_simulator.py` Stage 2 的反写
（2026-08 自实现反写）。

## 1. 科里奥利参数

```
f = 2Ω sin(φ),   Ω = 2π / T_rot
```

源码：`climate_physics.py:coriolis_parameter()`——`rotation_period_days` 为参数，
异星自转周期直接进入 f（慢自转 → f 小 → 地转风弱、天气尺度大）。

## 2. 三胞环流（Hadley / Ferrel / Polar）

纬向平均经圈环流的地表风带：

| 胞 | 纬度带 | 地表风 | 实现峰值风速 |
|----|--------|--------|-------------|
| Hadley | 0–H | 信风（东风） | −5 m/s（赤道峰值，余弦剖面） |
| Ferrel | H–P | 西风带 | +8 m/s（胞中心峰值） |
| Polar | P–90 | 极地东风 | −3 m/s（极地峰值） |

地球默认 H=30°、P=60°。源码：`climate_physics.py:hadley_cell_wind()`，
边界已参数化（`hadley_extent_deg` / `polar_cell_start_deg`，3A.3a）。

**经向风**（`hadley_cell_wind` 的另一输出，驱动 ITCZ 辐合与洋流风应力旋度）：
Hadley 胞地表支流向赤道，峰值经向风 M = 1.5 m/s（地球参考，随 Ω^(-1/3) 标度）。
近赤道用**软肩部**剖面 `u = M·sin(πt)·(s + (1−s)·sin(πt))`（t=|lat|/h，s=0.2），
赤道斜率降到 s·π（纯正弦为 π）——把 ITCZ 辐合带加宽，避免有限体积散度在
51 km 网格上把赤道风反转放大 ~100× 成单 cell 尖峰（ITCZ 偏强）。

**慢自转标度**：Held–Hou 理论给出 Hadley 胞宽度
φ_H ∝ (gHΔθ/Ω²a²)^{1/2}——Ω 减半 → φ_H 显著加宽。nacrea（Ω=0.31 Ω⊕）
用 H=90°、P=90°（单圈，抵极）。当前实现把边界当方案常数；严格做法是按 Ω 动态计算
（roadmap 3A.3a 中期项，与 `climate-pipeline.md` §6 3A.6 审计表一致）。

## 3. 地转风

大尺度水平风近似满足科氏力与气压梯度力平衡：

```
u_g = −(1/ρf) ∂p/∂y,   v_g = (1/ρf) ∂p/∂x
```

源码：`climate_simulator.py:_geostrophic_wind()`——在 CVT 图上用相邻 cell 气压差
（`pressure_from_temperature()` 的静压 + 热低压项）估计梯度。
最终风场 = **0.4 × 地转风 + 0.6 × 三胞风**，再经 `terrain_wind_blocking()`
地形阻挡（>3000 m 衰减）。

赤道附近 f→0，地转风发散——实现以三胞风为主体、地转风为修正的加权即为此。

## 4. 气压场（温度→气压）

静压公式 + 热低压修正（热低压项用**位温 θ**，捕获抬升热源）：

```
P(h) = P₀ exp(−h/H),  H ≈ 8500 m × (9.81/g)      # 标高随重力缩放
θ = T + Γ_d·z,  Γ_d = g/c_p                       # 位温（干绝热递减率，推导量）
P ← P − 20 hPa × norm(θ)                          # 暖位温→低压
```

高原地表冷但气柱暖（抬升热源，青藏高原/安第斯/埃塞俄比亚），用位温 θ 才能把高原
正确判为热低压——地表 T 会误读成冷异常（符号反）。
源码：`climate_physics.py:pressure_from_temperature()`。这是"温度场驱动风场"的
耦合点——也是 EBM（见 `energy_balance.md`）与环流的接口。

## 4.5 季风边界层风

海陆**季节**热力对比产生的气压异常 ΔP 驱动边界层风（`engine/monsoon_circulation.py`）：

```
0 = G + f k̂×v − k_d·v ,   G = −∇(ΔP)/ρ
```

- f→0（赤道）：`v = G/k_d`，直接下坡流——跨赤道季风气流（索马里急流型）；
- k_d→0：地转平衡，沿等压线。

**拖曳系数** `k_d = C_D·|U|/h_BL`：
- 开阔水面 / 光滑地表：C_D ≈ 1.3e-3 → k_d ≈ 1e-5 s⁻¹；
- 粗糙植被（密林）：C_D ≈ 0.05–0.1 → k_d ≈ 1e-4~1e-3 s⁻¹。

**标定锚点（区域风速，独立于端到端气候验收）**：

| 区域 | 观测地表风 | 季风异常风目标 |
|------|-----------|---------------|
| 亚马逊（密林） | 1–2 m/s（全年） | ~1 m/s |
| 索马里急流（洋面） | ~18 m/s（850 hPa） | ~10 m/s |

参考：巴西地表风 1980–2014（地面站+再分析，亚马逊年均 1–2 m/s）；
Masiwal & Dixit (JAS 80(3)) 索马里急流 850 hPa 月均最大 ~18 m/s。

> 教训（2026-08-30）：f→0 退化项本身没错（正确生成 ~10 m/s 索马里急流），但若 k_d
> 全网格统一用开阔水面的 1e-5，会把亚马逊（密林、应高拖曳）的温和 ΔP 放大成 ~20 m/s
> 假强风 → 干季水汽被抽干、亚马逊 Af→Aw。修法 = k_d 按地表类型区分。

## 5. 已知简化（与真实大气的差距）

- 纬向平均：无瞬变涡动（天气系统）、无急流核心结构；
- 无 ITCZ 的动力位置求解（ITCZ 降水见 `precipitation` 规划文档）；
- 季风边界层风是单层（无垂直结构），k_d 尚未按地表粗糙度区分（§4.5 待修）；
- 垂直结构单层——递减率与稳定度处理见 `energy_balance.md` §海拔。

## 6. 与引擎的对应关系

| 知识 | 引擎函数 | 状态 |
|------|---------|------|
| f = 2Ωsinφ | `climate_physics.py:coriolis_parameter()` | ✅ |
| 三胞纬向风 | `climate_physics.py:hadley_cell_wind()` | ✅（边界参数化） |
| 地转风 | `climate_simulator.py:_geostrophic_wind()` | ✅ |
| 温度→气压 | `climate_physics.py:pressure_from_temperature()` | ✅（位温 θ） |
| 季风边界层风 | `engine/monsoon_circulation.py:monsoon_boundary_layer_wind()` | ✅（f→0 退化 + 边界层平衡，k_d 待按地表区分） |
| Hadley 宽度 Ω 标度 | 3A.3a 中期 | 📋 |
| 瞬变涡动 / 急流 | 长期愿景（简化 GCM） | ❌ |

## 7. 慢自转与环流胞数转换

### 7.1 文献综述

**Kaspi & Showman (2015)**（*ApJ* 804:60，[arXiv:1407.6349](https://arxiv.org/abs/1407.6349)）用理想化湿润 GCM
（T42 分辨率、slab ocean、Betts-Miller 对流）扫描 Ω = 1/16 ∼ 8 Ω⊕，结论：

- **环流体制由 Rossby 数 Ro = U/(ΩL) 控制**。Ro ≪ 1 = 旋转主导（地球，多胞）；Ro ≳ 1 = 平流主导（慢自转，单胞）
- **Ferrel 胞出现阈值**：Ω > **1/4 Ω⊕**。低于此值 Ferrel 消失，环流退化为单一 Hadley 胞达极地
- **涡动 vs 平均流热输运转换**：0.2 Ω⊕（Fig. 8b）。低于此值涡动输运"变号"——平流（Hadley）完全主导
- **急流数目 ∝ Ω**：快自转 → 多急流；慢自转 → 单一副热带急流 + 赤道超旋转（Venus/Titan 型）

**实验室验证**（Sukhanovskii et al. 2023, *GApFD*）：浅层旋转流体实验中三胞结构
仅在有限参数范围内存在。

### 7.2 质量流函数（Kaspi & Showman Fig. 5）

| Ω (×Ω⊕) | 总流函数 (10¹¹ kg/s) | 体制 |
|-----------|---------------------|------|
| 1/16 | 8.7 | 单胞 Hadley |
| 1/8 | 5.1 | 过渡 |
| **1/4** | **4.2** | **Ferrel 刚出现** |
| 1/2 | 3.0 | 弱 Ferrel |
| **1** | **1.9** | **地球：完整三胞** |
| 2 | 1.2 | 多窄胞 |

> **注意**：流函数值大 = Hadley 强，不代表 Ferrel 强。实际上慢自转行星 Hadley 宽且强，
> 处理更多总质量；Ferrel 是叠加其上的弱涡动驱动分量。

### 7.3 dreamulator 中的应用

**nacrea**：Ω = 0.31 Ω⊕（周期 3.25 天，潮汐锁定于 Aegis 巨行星）。专用 GCM 模拟证实
科氏力弱到不产生 Ferrel/极地胞——环流为**单圈 Hadley 胞直抵极地**
（`hadley_extent_deg=90`、`polar_cell_start_deg=90`，见 `terrain_config.yaml`）。

| 指标 | 地球 | nacrea | 说明 |
|------|------|--------|------|
| Ω | 1 Ω⊕ | 0.31 Ω⊕ | 潮汐锁定 |
| Hadley 边界 | 30° | 90°（抵极） | 单圈 |
| Ferrel / 极地胞 | 有（30°–90°） | 无 | 单圈 |
| 温度剖面 | 扩散 EBM | Held–Hou 四次方 | `ebm_1d=true` |

**结论**：nacrea 是单圈环流，经向热输送由翻转环流（MOC）主导，而非地球的三胞涡旋输送。
温度剖面用 Held & Hou (1980) 四次方 T(φ)=T_mean+ΔT·(1/5−sin⁴φ)，ΔT=Ω²a²θ₀/(2gH)——
副热带平（无冷荒漠）、极地有冰盖。

### 7.4 罗斯贝变形半径

**罗斯贝变形半径** L_d 是旋转层结流体中重力波与科里奥利力平衡的特征长度：

```
L_d = N · H / f
```

其中 N 为 Brunt–Väisälä 频率（~0.01 s⁻¹），H 为大气标高（~8 km），
f = 2Ω sin(φ) 为科里奥利参数。

L_d 决定了大气的"记忆长度"——小于 L_d 的结构受重力波调控，大于 L_d 的结构受
行星旋转调控。在 dreamulator 中，L_d 控制以下**临界纬度依赖性**：

| 应用 | 标度 | 说明 |
|------|------|------|
| **副热带干燥带宽** (σ) | ∝ 1/sin(H) | H = Hadley 边界纬度。低纬 H 小 → sin(H)小 → L_d 大 → 干燥带宽；极地 L_d 小 → 窄 |
| 涡动尺度 | ∝ L_d | 天气系统中急流/气旋的特征宽度 |
| 急流间距 | ∝ L_d | 快自转行星多急流（窄 L_d → 多波数） |
| 洋流西边界层宽度 | ∝ L_d^(1/2) | Stommel 边界层理论 |

**dreamulator 应用**：`climate_simulator.py` Step 6 的 Gaussian subtropical
suppression 宽度 σ = 2.5° / sin(H)。地球（H=30°）→ σ=5°；nacrea（H=90°，单圈）
→ σ=2.5°。

**参考资料**：
- Vallis, G.K. (2017). *Atmospheric and Oceanic Fluid Dynamics*, ch. 5.
- Chelton, D.B. et al. (1998). "Geographical variability of the first
  baroclinic Rossby radius of deformation." *J. Phys. Oceanogr.* 28.

### 7.5 代码中的简化

当前 `climate_physics.py:hadley_cell_wind()` 对所有三胞统一施加
Ω^(-1/3) 风速标度（Hill et al. 2019），Ferrel 西风峰值 = 8.0 × ω_scale m/s。
这对 Ferrel 是过高估计（慢自转时涡动应减弱而非增强）。
**已知局限**：roadmap 3A.3a 中期计划细化 Ferrel/polar 强度标度。

### 7.6 单圈环流下的涡旋活动

「单圈环流 = 没有涡旋」是不成立的过度简化。慢自转 GCM 的一致结论是：
瞬变涡旋随 Ω 降低而减弱，但不消失；定常涡旋（驻波）的比重上升。
Gnanaraj et al. (2025) 的水行星旋转速率扫描显示，慢自转端 Hadley 胞扩张、
对流层变干，但斜压涡旋热通量依然可测；Hermosilla Canobra (2026) 用 Isca
模型扫到 0.083 Ω⊕，发现涡旋驱动的经向输送效率低于直接平流但仍非零；
Showman & Kaspi (2010) 的潮汐锁定水行星里，定常涡旋主导角动量输送并塑造
降水分布。

对引擎的含义（2026-08-29 落地，技术债 20 ⑥）：斜压雨出带的位置不取环流胞
边界（单圈时退化为零宽），而是从纬向平均温度的经向梯度推导——Eady 不稳定
跟随 ∇T，带中心取 |dT/dφ| 峰值、σ 取半峰全宽/2.355（`_baroclinic_band`）。
地球与 nacrea 的年均梯度峰值都在 ~67°（极锋区），σ≈20°。幅度沿用共享默认
（900 mm）加 Ω^0.3 标度，慢自转行星自动得到弱增强：nacrea 有效幅度约
560 mm，中高纬增湿 +31~+89 mm/年，BW 沙漠 −910 cell，沿海沙漠
（<200 km）853→636——方向与「涡旋减弱而不为零」一致。

## 参考资料

- Held, I.M., & Hou, A.Y. (1980). "Nonlinear axially symmetric circulations." *JAS 37*.
- Hartmann, D.L. (2016). *Global Physical Climatology* (2nd ed.), ch. 4–7.
- Vallis, G.K. (2017). *Atmospheric and Oceanic Fluid Dynamics*, ch. 12.
- Kaspi, Y., & Showman, A.P. (2015). "Atmospheric dynamics of terrestrial exoplanets
  over a wide range of orbital and atmospheric parameters." *ApJ* 804:60.
  [arXiv:1407.6349](https://arxiv.org/abs/1407.6349).
- Hill, S.A., Bordoni, S., & Mitchell, J.L. (2019). "Constraints from invariant
  subtropical vertical velocities on the scalings of Hadley cell strength and
  downdraft width with rotation rate." *J. Atmos. Sci.* 76.
- Sukhanovskii, A., Popova, E., & Vasiliev, A. (2023). "A shallow layer laboratory
  model of large-scale atmospheric circulation." *GApFD* 117.
- Gnanaraj, C., et al. (2025). "The impact of the rotation rate on an aquaplanet's
  radiant energy budget." *Weather Clim. Dynam.* 6, 489–509.
- Showman, A.P., & Kaspi, Y. (2010). "Atmospheric dynamics of Earth-like tidally
  locked aquaplanets." *JAMES* 2.
- Hermosilla Canobra, S. (2026). "Circulation and cloud-cover fingerprints in
  aquaplanet atmospheres." Utrecht University MSc thesis.
- Masiwal, R., & Dixit, V. (2023). "Explaining dynamics and rapid onset of the Somali
  jet through its kinetic energy budget." *J. Atmos. Sci.* 80(3).
- 巴西地表风特征（1980–2014，地面站 + 再分析）：亚马逊盆地年均地表风 1–2 m/s，
  为全球最弱地表风区之一（季风异常风标定锚点，§4.5）。
