# 气候引擎实现架构

> 本文档描述 dreamulator 气候引擎的代码架构、模块职责、数据流和物理模型。
> 对应源码：`src/dreamulator/engine/climate_physics.py`、`climate_seasonality.py`、
> `src/dreamulator/engine/climate.py`、`src/dreamulator/map/climate_simulator.py`。
> 物理公式见 [`docs/knowledge/climatology/energy_balance.md`](../../knowledge/climatology/energy_balance.md)。

---

## 目录

1. [架构总览](#1-架构总览)
2. [模块详解](#2-模块详解)
3. [数据流](#3-数据流)
4. [输出格式](#4-输出格式)
5. [验证方法](#5-验证方法)
6. [已知限制与调优方向](#6-已知限制与调优方向)

---

## 1. 架构总览

```
┌──────────────────────────────────────────────────────────────┐
│                    src/dreamulator/engine/                    │
│                                                              │
│  climate_physics.py          climate_seasonality.py           │
│  (纯函数，无 I/O)             (光照 + 季节 + 年平 EBM)         │
│  ├─ equilibrium_temperature  ├─ monthly_insolation            │
│  ├─ surface_temperature      ├─ solve_1d_ebm_temperature      │
│  ├─ altitude_lapse_rate      ├─ monthly_temperature            │
│  ├─ moist_lapse_rate         ├─ seasonal_heat_capacity         │
│  ├─ hadley_cell_wind         ├─ monthly_precipitation_factor   │
│  ├─ terrain_wind_blocking    └─ compute_seasonal_climate       │
│  ├─ evaporation_rate                                         │
│  ├─ koppen_classify                                          │
│  └─ ...                                                      │
│                                                              │
│  climate.py (BaseEngine 封装 — DAG 入口)                      │
└──────────────────────┬───────────────────────────────────────┘
                       │ 调用
┌──────────────────────▼───────────────────────────────────────┐
│                    src/dreamulator/map/                        │
│                                                              │
│  climate_simulator.py         export.py                       │
│  ├─ simulate_climate()        └─ export_climate_layers()      │
│  ├─ _compute_precipitation_bfs                                │
│  ├─ _meridional_convergence                                    │
│  ├─ _surface_divergence                                        │
│  ├─ _geostrophic_wind                                          │
│  └─ _ocean_surface_temperature                                 │
└──────────────────────────────────────────────────────────────┘
```

**两个入口路径**：

| 入口 | 触发方式 | 适用场景 |
|------|---------|---------|
| `simulate_climate(mesh, config)` | 地形管线 Stage 6 / 诊断脚本 | CVT mesh 已有 elevation，直接跑气候 |
| `ClimateEngine.run()` | DAG 管线 `dreamulator build earth` | 独立引擎运行，读写标准层文件 |

---

## 2. 模块详解

### 2.1 `climate_physics.py` — 纯物理函数

**设计原则**：无 I/O、无 RNG、确定性、可单元测试。全部函数接收 numpy 数组，系数通过参数传入。

| 函数 | 物理含义 |
|------|---------|
| `equilibrium_temperature()` | 恒星辐射 → 黑体平衡温度 |
| `surface_temperature()` | + 温室效应 |
| `altitude_lapse_rate()` | 海拔递减率 |
| `moist_lapse_rate()` | 温度相关湿绝热递减率 |
| `hadley_cell_wind()` | 三圈环流风场（含 `itcz_lat_deg` 季节迁移） |
| `terrain_wind_blocking()` | 山脉挡风 |
| `evaporation_rate()` | 海面蒸发（Clausius–Clapeyron） |
| `orographic_precipitation()` | 地形抬升降水（纯函数版，管线用内联版） |
| `ice_albedo_feedback()` | 年均冰反照率反馈（Earth 默认关闭，季节版见 §2.2） |
| `koppen_classify()` | Köppen–Geiger 分类（s/w/f 季节感知） |
| `coriolis_parameter()` / `pressure_from_temperature()` | 风场输入 |

> **Legacy 兼容**：`latitude_temperature()`（sin² 剖面）、`diffuse_heat_graph()`（图扩散）、
> `lat_gradient_from_omega()`（ΔT∝Ω^0.3）仍保留，供 `ebm_1d=false` 的旧路径使用
> （gaia-m 尚未切到 ebm_1d，见 §6）。

### 2.2 `climate_seasonality.py` — 年平 EBM + 季节模型

| 函数 | 物理含义 |
|------|---------|
| `monthly_insolation()` | 12 月日平均辐照（Hartmann 2016 eq. 3.7） |
| `solve_1d_ebm_temperature()` | **1D EBM 稳态解**（Legendre 谱），纬向年均温 |
| `monthly_temperature()` | **季节 EBM**（显式热输送 + 冰反照率），月度温度 |
| `seasonal_heat_capacity()` | 海陆热容量（海洋性 vs 大陆性） |
| `itcz_latitude_monthly()` | ITCZ 季节迁移 |
| `monthly_precipitation_factor()` | 月度降水分布因子 |
| `compute_seasonal_climate()` | 高层入口：月度 T/P + ITCZ |

#### 年平温度：`solve_1d_ebm_temperature`

解 `0 = D∇²T + Q(φ)(1−α) − (A+BT)`，Legendre 谱法。$A$ 内部标定使全球均温锚定
equilibrium+greenhouse 链。参数 `ebm_olr_b_wm2k`（B=2）、`ebm_diffusion_wm2k`（D=0.35）。
陆地用 `ebm_diffusion_land_wm2k`（D=0.2，仅大气输送）产生**大陆度**（海陆年均对比）。

#### 季节温度：`monthly_temperature`

季节振幅 $T_{amp} = \Delta Q_\omega(1-\alpha)/\sqrt{B_{eff}^2 + (\omega C)^2}$，
$B_{eff} = B + 6D$（显式热输送的四极模阻尼，取代旧标定常数）。叠加季节冰反照率
（夏季冻结 cell 保留冰反照率 → 振幅缩小），区分冰盖（EF）与副极地（Dfc）。

### 2.3 `climate_simulator.py` — CVT mesh 气候模拟

**入口**：`simulate_climate(mesh: CVTMesh, config: TerrainPipelineConfig) -> dict[str, float]`

**执行流程**：

```
1. 提取 CVT mesh → numpy 数组（elevation / lat / land-ocean mask / 3D 节点）
2. Stage 1: 温度
   ├─ equilibrium_temperature + surface_temperature → 全球均温 t_surf
   ├─ ebm_1d=true: solve_1d_ebm_temperature(D_land) → 陆地温度（大陆度）
   │   ebm_1d=false: legacy sin² + 图扩散（见 §6）
   ├─ ice_albedo_feedback（年均，若开启）
   ├─ 海拔直减率（仅陆地）
   └─ _ocean_surface_temperature（海洋 SST，地球剖面锚定）
3. Stage 1b: 季节
   └─ compute_seasonal_climate → t_monthly / t_cold / t_hot / p_factor / itcz_lat
4. Stage 2: 风场
   ├─ 气压场（barometric + thermal low）→ 图梯度 → 地转风（Coriolis）
   ├─ hadley_cell_wind（三圈 + 地形阻挡）
   └─ 40% 地转 + 60% 环流
5. Stage 2.5: 洋流（Stommel 环流 + SST 平流 + 涌升）
6. Stage 3: 降水（_compute_precipitation_bfs，见 §2.4）
7. Stage 4: Köppen 分类（koppen_classify）
8. 写回 mesh.cells（temperature_C / precipitation_mm / koppen_class / 月度极值）
```

### 2.4 降水：`_compute_precipitation_bfs` — 辐合驱动三层模型

降水是三层物理之和（详细公式见 energy_balance.md §8）：

```
P = η_recycle · q_diff                      # 基线：水汽回收（层积云/副高弱下沉/蒸散）
  + η_conv · min(W(T), W_cap) · conv        # 辐合增强：ITCZ / 极锋（从风场涌现）
  + P_storm                                 # 斜压风暴路径（独立机制）
```

执行步骤：

1. **Step 1 蒸发源**：海洋蒸发（C–C，SST 依赖）+ 陆地蒸散（海洋的 40%）。
2. **Step 2 水汽输送**：风偏图扩散（`(I + α̅L) q = q_source`，GMRES），多 pass；
   每 pass 后做地形抬升降水 + 雨影。
3. **Step 3 基线回收**：`recycling_fraction × q_diff`（让副热带下沉带不干到零）。
4. **Step 3.5 辐合增强**：`_meridional_convergence`（平滑纬向辐合，12 月 ITCZ 平均）→
   `η_conv × min(W, W_cap) × conv`；随后加**斜压风暴路径**（幅度 ∝ ∇T × Ω^0.3 × 蒸发，
   中心在极锋）。
5. **Step 4 季风增强**：沿海热带陆地 ×1.5/×1.3（过渡先验，待季节季风机制替代）。
6. **Step 5 局地对流**：暖陆地午后雷暴（`30 × max(T−10, 0)`）。
7. **Step 6.5 内陆干旱梯度**、**6.6 海岸不对称**、**6.7 Föhn 雨影**、**7 热带底线**、
   **8 次行星半球强迫**。
8. 最终封顶 11000 mm/yr。

**关键设计**：ITCZ、副热带干带、极锋全部从 `_meridional_convergence` 的 ∇·u 自然涌现，
**无纬度硬编码**——对 Earth 三圈环流与 gaia-m 单圈环流（`hadley_extent=90`）同一套代码
自动适配（见 `scripts/diagnose_wind_divergence.py`）。

**辐合函数**：

- `_meridional_convergence(lat_rad, hadley_extent, polar_cell_start, rotation, itcz_lat_deg)`：
  在细纬度网格上算经向风散度 `(1/cos φ) d(v cos φ)/dφ`（`np.gradient`），12 月 ITCZ 平均
  后插值回 cell。平滑无噪声（避免逐 cell Voronoi 几何噪声）。
- `_surface_divergence(nodes_xyz, wind, neighbors, areas_ster)`：有限体积逐 cell 散度，
  供诊断脚本 `diagnose_wind_divergence.py` 使用。

### 2.5 洋流：`ocean_circulation.py`

> 详细物理（Ekman / Sverdrup / Stommel / 热盐双稳态 / 海峡闸门）见
> [knowledge/climatology/ocean_currents.md](../../knowledge/climatology/ocean_currents.md)。

洋流在 `simulate_climate` 的 **Stage 2.5**（风场之后、降水之前）挂载，单向单遍
（不做 SST↔风迭代回耦合）。三步：

1. **Stommel 流函数解**（`solve_ocean_gyre`）：对每个海盆解 β 平面摩擦涡度方程，
   西边界强化（WBC）作为摩擦边界层**自然涌现**（不手贴 ×3 系数）。流函数形式在
   赤道无 `1/f` 奇点（β=2Ωcosφ/a 在赤道最大）——gaia-m 慢自转（Ω=0.31Ω⊕）下地转
   求逆会除零，流函数是唯一全程良态的极小模型。
2. **SST 沿流平流修正**（`advect_sst_semilagrangian`）：semi-Lagrangian 沿流溯源
   松弛（复用 BFS 水汽的「沿输送方向迭代松弛」思路），暖流增温/寒流降温，修正后的
   SST 进入 stage 3 蒸发与 stage 4 Köppen。
3. **涌升诊断**（`compute_upwelling_index` + `apply_upwelling_sst_correction`）：
   风应力旋度 → 沿岸上升流 → 东边界冷舌（寒流）。

逐 cell 洋流字段（`ocean_current_east_m_s` / `ocean_current_north_m_s` /
`sst_anomaly_c`）写入 `VoronoiCell`，经气候回写进入 `cvt_mesh.json`，前端本地烘焙流线。

**配置**（`TerrainPipelineConfig` 的 `Ocean` 小节）：`ocean_currents_enabled`（开关）、
`ocean_drag_coefficient`、`ocean_mixed_layer_depth_m`（H_ml）、`ocean_bottom_friction_s`
（Stommel R，调 WBC 比）、`ocean_sst_advection_days`（τ）、`ocean_coastal_influence_km`、
`ocean_upwelling_enabled`。

### 2.6 `climate.py` — DAG 引擎封装

```python
class ClimateEngine(BaseEngine):
    name = "climate"
    layer = Layer.CLIMATE
    requires = ["astronomy", "geological"]
    input_files = ["stellar.yaml", "stellar_derived.yaml", "planets.yaml"]
    output_files = ["climate_summary.yaml", "maps/{planet_id}/temperature.png", ...]
```

从 `terrain_config.yaml` 读气候调参，`resolve_and_apply_physical_parameters` 从
planets.yaml/stellar.yaml 解析恒星/轨道/倾角/温室等物理强迫。执行 `simulate_climate`，
写回 `cvt_mesh.json`，导出图层。

### 2.7 `export.py` — 气候图层导出

`export_climate_layers(mesh, output_dir, config)` 生成：

- `temperature.png` — 16-bit PNG，范围 [-40, +50] °C
- `precipitation.png` — 16-bit PNG，范围 [0, 6000] mm/yr
- `koppen.json` — per-cell 分类 + 统计汇总
- `climate_metadata.json` — 模拟参数记录

---

## 3. 数据流

### 3.1 通过地形管线

```
terrain_config.yaml → terrain_pipeline.py → simulate_climate(mesh, config)
                                            → export_climate_layers(mesh, ...)
                                            → maps/{planet}/temperature.png / ... / koppen.json
```

### 3.2 通过 DAG 引擎

```
planets.yaml + stellar.yaml + cvt_mesh.json
  → ClimateEngine.run()
      → 解析物理参数 → 构建 TerrainPipelineConfig
      → simulate_climate() → 写回 cvt_mesh.json → 导出 raster + JSON
```

---

## 4. 输出格式

### temperature.png / precipitation.png

16-bit 单通道 PNG（与 elevation.png 相同编码）。前端解码：

```typescript
const temperature = tMin + (pixelValue / 65535) * (tMax - tMin);  // from climate_metadata.json
```

### koppen.json

```json
{
  "cells": { "0": "Cfa", "1": "Aw", ... },
  "summary": { "Cfa": 3200, "Aw": 1500, "BWh": 4800, ... },
  "num_cells": 200000
}
```

### climate_metadata.json

```json
{
  "temperature_range_c": [-40, 50],
  "precipitation_range_mm": [0, 6000],
  "koppen_classes": ["Af", "Am", "Aw", "BSh", "BWh", ...],
  "export_resolution": [2048, 1024]
}
```

---

## 5. 验证方法

见 [`docs/design/climate-validation.md`](climate-validation.md)。

**验证方式**：ETOPO1 真实高程输入（earth/climate-dev 分支，200k cells）对比 Beck 2018
Köppen / ERA5 温度 / GPCP 降水。诊断脚本区分「引擎 bug」vs「参数微调」。

**M4 验收口径**（roadmap §4）：① 分布匹配 >55%；② 群组(5类) Kappa >0.45；③ 逐 cell
30 类匹配 ≥30%；④ 温度纬向 corr >0.9。

```bash
uv run python scripts/diagnose_koppen_confusion.py     # 逐类 precision/recall/F1 + 混淆矩阵
uv run python scripts/diagnose_latitudinal_profile.py  # 海陆分离 T/P 纬向剖面
uv run python scripts/diagnose_koppen_spatial.py       # 空间准确率热图
uv run python scripts/diagnose_wind_divergence.py      # 风场辐合/辐散纬向剖面
```

---

## 6. 已知限制与调优方向

### 当前状态（2026-08）

| 机制 | 状态 |
|------|------|
| 温度（年平） | ✅ 1D EBM 正式求解 + 大陆度（`ebm_diffusion_land_wm2k`） |
| 温度（季节） | ✅ 显式热输送（B+6D）+ 季节冰反照率 |
| 降水 | ✅ 辐合驱动三层模型（基线回收 + 辐合增强 + 斜压风暴） |
| 风场 | ✅ 地转 + 三圈环流（`itcz_lat_deg` 季节迁移已实现、未接线） |
| 洋流 | ✅ Stommel 环流 + SST 平流 + 涌升 |

### 待办（过渡先验 → 第一性）

| 项 | 现状 | 方向 | 位置 |
|---|---|---|---|
| 季风 | Step 4 系数 ×1.5/×1.3 固定 | 季节风反转 + 海陆热力对比驱动的向岸水汽平流（`itcz_lat_deg` 已就绪） | `climate_simulator.py` Step 4 |
| 内陆干旱梯度 / 海岸不对称 / 热带底线 | 逐 cell 启发式 | BFS 季节输送 / 涌升 + 季风 / 双 ITCZ | `_compute_precipitation_bfs` Step 6.5/6.6/7 |
| 南半球 SST 过暖 | `_ocean_surface_temperature` 南半球偏暖 +4~+10°C | 独立标定 | `_ocean_surface_temperature` |
| 三圈环流边界 | Hadley 30° / Ferrel 60° 可配置 | Held-Hou 标度 φ_H ∝ (gHΔθ)^½/(Ωa)^½ 行星化 | `hadley_cell_wind` |
| gaia-m 回归 | gaia-m 仍走 `ebm_1d=false` legacy 路径 | flip `ebm_1d: true` 后回归验证（计划 §六 #1） | `gaia-m/terrain_config.yaml` |

### 地球调优的方案常数（影响异星保真度）

| 参数 | 默认 | 说明 |
|------|------|------|
| `ebm_diffusion_wm2k` | 0.35 | 总经向热输送 D，Earth ΔT≈41°C 标定 |
| `ebm_diffusion_land_wm2k` | 0.2 | 陆地（大气）输送，≈0.6×总输送 |
| `convergence_efficiency` | 1.8 | 辐合降水效率（含单位换算） |
| `convergence_moisture_cap_mm` | 40.0 | 能量受限可降水柱（热带降水能量受限） |
| `recycling_fraction` | 0.3 | 基线水汽回收比例 |
| `storm_track_amplitude_mm` | 900.0 | 斜压风暴路径幅度 |
| `evaporation_base_mm` | 2000.0 | 热带洋面年蒸发基准 |
| `moisture_diffusivity` | 5.0 | 图扩散 D₀ |

---

## 7. GCM 与参数化管线的定位（指导纲要）

### 结论

GCM（求解原始方程）技术上能取代参数化管线，但**不适合做主干**——计算量差 3–4 个数量级
（ExoPlaSim 一个案例数小时 vs 管线 ~2 分钟），且 GCM 的次网格参数化同样有几十个地球标定
的「补丁」，用到 gaia-m 需重新标定。

### 定位

「参数化 vs GCM」不是对立，而是「参数是否物理自洽」。逐项打补丁暴露的问题（速度单位、
随意 λ）是**参数不物理**，不是参数化模型的原罪。本轮（辐合驱动降水、显式热输送季节、
大陆度）正是把「纬度高斯补丁」替换为「从风场/辐射第一性推导的物理量」，方向正确。
