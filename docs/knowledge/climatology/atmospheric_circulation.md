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
用 H=55°、P=75°。当前实现把边界当方案常数；严格做法是按 Ω 动态计算
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

静压公式 + 热低压修正：

```
P(h) = P₀ exp(−h/H),  H ≈ 8500 m × (9.81/g)      # 标高随重力缩放
P ← P − 20 hPa × norm(T)                          # 暖空气→低压
```

源码：`climate_physics.py:pressure_from_temperature()`。这是"温度场驱动风场"的
耦合点——也是 EBM（见 `energy_balance.md`）与环流的接口。

## 5. 已知简化（与真实大气的差距）

- 纬向平均：无瞬变涡动（天气系统）、无急流核心结构；
- 无 ITCZ 的动力位置求解（ITCZ 降水见 `precipitation` 规划文档）；
- 季风以海陆热力对比的经验修正表达（`climate_simulator.py` 季风系数），
  非真实的海陆风环流求解；
- 垂直结构单层——递减率与稳定度处理见 `energy_balance.md` §海拔。

## 6. 与引擎的对应关系

| 知识 | 引擎函数 | 状态 |
|------|---------|------|
| f = 2Ωsinφ | `climate_physics.py:coriolis_parameter()` | ✅ |
| 三胞纬向风 | `climate_physics.py:hadley_cell_wind()` | ✅（边界参数化） |
| 地转风 | `climate_simulator.py:_geostrophic_wind()` | ✅ |
| 温度→气压 | `climate_physics.py:pressure_from_temperature()` | ✅ |
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

**nacrea**：Ω = 0.31 Ω⊕（周期 ≈ 3.2 天），Hadley = 55°，Polar = 75°，Ferrel 宽 20°。

| 指标 | 地球 | nacrea | 比例 |
|------|------|--------|------|
| Ω | 1 Ω⊕ | 0.31 Ω⊕ | 0.31× |
| Hadley 边界 | 30° | 55° | 1.83× |
| Ferrel 宽度 | 30°（30°–60°） | 20°（55°–75°） | 0.67× |
| 总流函数 | 1.9 | ~3.6 (插值) | 1.9× |
| Ferrel 质量输运 | 1（参考） | ~0.3–0.5× | 弱 |
| 涡动动能 | 1（参考） | ~0.5× | 弱 |
| Ferrel 水汽输运 | 1（参考） | ~0.3–0.5× | 弱 |

**结论**：nacrea 处于弱三胞体制（Ω=0.31 > 临界 0.25）。Ferrel 理论上存在但极窄弱——
水汽输运仅为地球的 1/3–1/2。中纬度降水主要依靠 BFS 平流 + 局地对流，
Ferrel 西风贡献有限。sub-tropical suppression 覆盖 Ferrel 大部在物理上是自洽的。

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
suppression 宽度 σ = 2.5° / sin(H)。地球（H=30°）→ σ=5°；nacrea（H=55°）
→ σ=3.05°。

**参考资料**：
- Vallis, G.K. (2017). *Atmospheric and Oceanic Fluid Dynamics*, ch. 5.
- Chelton, D.B. et al. (1998). "Geographical variability of the first
  baroclinic Rossby radius of deformation." *J. Phys. Oceanogr.* 28.

### 7.5 代码中的简化

当前 `climate_physics.py:hadley_cell_wind()` 对所有三胞统一施加
Ω^(-1/3) 风速标度（Hill et al. 2019），Ferrel 西风峰值 = 8.0 × ω_scale m/s。
这对 Ferrel 是过高估计（慢自转时涡动应减弱而非增强）。
**已知局限**：roadmap 3A.3a 中期计划细化 Ferrel/polar 强度标度。

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
