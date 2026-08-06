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

**慢自转标度**：Held–Hou 理论给出 Hadley 胞宽度
φ_H ∝ (gHΔθ/Ω²a²)^{1/2}——Ω 减半 → φ_H 显著加宽。gaia-m（Ω=0.31 Ω⊕）
用 H=55°、P=75°。当前实现把边界当方案常数；严格做法是按 Ω 动态计算
（roadmap 3A.3a 中期项，与 `climate-engine.md` §6 3A.6 审计表一致）。

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

## 参考资料

- Held, I.M., & Hou, A.Y. (1980). "Nonlinear axially symmetric circulations." *JAS 37*.
- Hartmann, D.L. (2016). *Global Physical Climatology* (2nd ed.), ch. 4–7.
- Vallis, G.K. (2017). *Atmospheric and Oceanic Fluid Dynamics*, ch. 12.
