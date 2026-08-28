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
| `hadley_cell_wind()` | 三圈环流风场（含 `itcz_lat_deg` 季节迁移 + 经向风软肩部） |
| `terrain_wind_blocking()` | 山脉挡风 |
| `evaporation_rate()` | 海面蒸发（Clausius–Clapeyron） |
| `orographic_precipitation()` | 地形抬升降水（纯函数版，管线用内联版） |
| `ice_albedo_feedback()` | 年均冰反照率反馈（Earth 默认关闭，季节版见 §2.2） |
| `koppen_classify()` | Köppen–Geiger 分类（s/w/f 季节感知） |
| `coriolis_parameter()` / `pressure_from_temperature()` | 风场输入 |

> **Legacy 兼容**：`latitude_temperature()`（sin² 剖面）、`diffuse_heat_graph()`（图扩散）、
> `lat_gradient_from_omega()`（ΔT∝Ω^0.3）仍保留，供 `ebm_1d=false` 的旧路径使用
> （nacrea 尚未切到 ebm_1d，见 §6）。

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

**入口**：`simulate_climate(mesh: CVTMesh, config: TerrainPipelineConfig, debug: dict[str, np.ndarray] | None = None) -> dict[str, float]`

**执行流程**（六步：温度 → 风场 → 洋流 → 降水 → Köppen → 写回）：

```
1. 提取 CVT mesh → numpy 数组（elevation / lat / land-ocean mask / 3D 节点）
2. Stage 1: 温度
   ├─ equilibrium_temperature + surface_temperature → 全球均温 t_surf
   ├─ ebm_1d=true:
   │   ├─ hadley_extent_deg ≥ 90: solve_held_hou_temperature（单圈 Held-Hou 慢自转）
   │   └─ 否则: solve_1d_ebm_temperature(D_land) → 陆地温度（大陆度）
   │   ebm_1d=false: legacy sin² + 图扩散（见 §6）
   ├─ ice_albedo_feedback（年均，若开启）
   ├─ _ocean_surface_temperature（海洋 SST，地球剖面锚定）
   ├─ 沿海调节（coastal moderation：海平面陆地温度向最近海洋 SST 混合，自动冰感知）
   ├─ 海拔直减率（仅陆地，在沿海调节之后 → 高冰盖仍冷）
   └─ sub_planet_warming_c（潮汐锁定卫星向星面增温，若 >0）
3. Stage 1b: 季节
   └─ compute_seasonal_climate → t_monthly / t_cold / t_hot / p_factor / itcz_lat
4. Stage 2: 风场
   ├─ 气压场（barometric + thermal low）→ 图梯度 → 地转风（Coriolis）
   ├─ hadley_cell_wind（三圈 + 地形阻挡）
   └─ 40% 地转 + 60% 环流
5. Stage 3: 洋流（Stommel 环流 + SST 平流 + 涌升）
6. Stage 4: 降水（_compute_precipitation_bfs，见 §2.4）
7. Stage 5: Köppen 分类（koppen_classify）
8. 写回 mesh.cells（temperature_C / precipitation_mm / koppen_class / 月度极值 / distance_to_coast_km）
```

### 2.4 降水：`_compute_precipitation_bfs` — 质量守恒水汽收支

核心是一个**质量守恒的柱水汽收支方程**（`_solve_moisture_budget`，详细公式见
energy_balance.md §8）：

```
∇·(W u) + k_rain(x)·W − κ∇²W = E ,   P = k_rain(x)·W
k_rain(x) = (1/τ)·(1 + _storm_enhance(x) + _conv_enhance(x) + _boost_enhance(x))
```

迎风有限体积（边平均风速保证通量守恒）+ 湍流扩散 κ∇²W（κ≈3.75e5 m²/s，从 1e6 下调以
抑制海洋→陆地的过度扩散湿润，见 §6 标定；代价是 ITCZ 更集中，属已知待办）+ 直接稀疏 LU
求解。**质量守恒由构造保证**（ΣP = ΣE，任意 `k_rain(x)` 场都成立），ITCZ / 副热带干带
从风场自然涌现。

**雨出率空间调制**：`k_rain(x)` 非常数——风暴路径等增强机制当作**雨出效率的空间
调制**（τ 更短 → 雨出更高效），而非加法降水项。这保证全球 ΣP = ΣE（Held & Soden
2006：降水受地表/辐射能量预算约束，只能从平流来的柱水汽中析出，不能凭空加）。

执行步骤：

1. **蒸发源 E**：海洋蒸发（能量限制 ~3%/°C）+ 陆地蒸散——后者走 **Budyko 再循环**
   （`E_land = E_pot·P/(E_pot+P)`，湿陆蒸散近潜势、干陆近零），取代旧的距离海岸内陆
   干旱衰减；基准因子 `_LAND_EVAPOTRANSPIRATION_FRACTION` ≈ 0.55 作首轮初值（配 Earth
   ~490 mm/yr 陆地蒸散）。
2. **水汽收支求解**：`_solve_moisture_budget` 解出柱水汽 W，P = W/τ（质量守恒）；Budyko
   再循环在解内作固定点迭代（矩阵与 E 无关，只 LU 分解一次、迭代重解 RHS）。
3. **地形抬升雨**：从 W 算迎风抬升雨 + 雨影。
4. **斜压风暴路径**：雨出率增强 `_storm_enhance`（幅度 ∝ ∇T × Ω^0.3 × 蒸发，作为 `k_rain` 调制而非加法项；`_eddy_enhance` 同比例增强涡旋水汽扩散 κ）。带的位置由 `_baroclinic_band` 从纬向平均温度的经向梯度推导（Eady 不稳定性跟随 ∇T）：中心取 |dT/dφ| 峰值纬度（限制在 20° 以上），σ 取半峰全宽/2.355（钳制 5–20°）；地球与 nacrea 的年均梯度峰值都在 ~67°（极锋区），σ≈20°。旧的胞圈边界方案（φ=(φ_H+φ_P)/2）在单圈行星退化为零宽，但慢自转 GCM 表明瞬变涡旋「减弱而不为零」（Gnanaraj et al. 2025; Showman & Kaspi 2010），梯度推导让单圈行星也得到弱而真实的斜压带（技术债 20 ⑥）。
5. **局地对流 + 热带底线**（同为 `k_rain` 调制 `_conv_enhance`/`_boost_enhance`，非加法）、**季风增强**、
   **海岸不对称**、**Föhn 雨影**、**次行星半球强迫**。
6. 最终封顶 11000 mm/yr。

**关键设计**：ITCZ、副热带干带、极锋全部从水汽收支的 ∇·(W u) 自然涌现，
**无纬度硬编码**——对 Earth 三圈环流与 nacrea 单圈环流（`hadley_extent=90`）同一套代码
自动适配（见 `scripts/diagnose_wind_divergence.py`）。

**守恒约束与文献参照**：

- **Held & Soden (2006)**：全球降水受能量预算约束（ΣP = ΣE），`P = W/τ` 即其雨出
  弛豫形式；雨出效率空间可变（风暴路径 τ 短、副热带 τ 长）。
- **Trenberth et al. (2007)**：海洋 E−P = +40×10³ km³/yr（净源）、陆地 P−E = +40
  （净汇），海洋→陆地输送 ≈ +110 mm/yr（海洋均值）；模型标定目标。
- **climlab**（Betts-Miller 对流 + LargeScaleCondensation）：降水是「已有湿度/柱水汽
  的汇」（弛豫/凝结），从不凭空加法——与本文件 `k_rain(x)·W` 同构。
- **PlaSim/ExoPlaSim**（Kuo 对流）：对流降水 ∝ 水汽辐合，天然守恒。
- **WAM-2layers**（van der Ent 2014）：水汽标记追踪；~40% 陆地降水来自陆地再蒸发，
  作再循环率标定目标。
- **Savenije (1995) / van der Ent & Savenije (2011)**：内陆降水沿水汽轨迹指数衰减
  `P = P₀·exp(−x/λ)`，但再循环长度 λ 区域依赖（热带 500–2000 km、沙漠 >7000 km），
  由当地 E/P 决定而非距海距离——这是 Budyko 再循环取代距离衰减的依据。

**诊断辅助函数**：

- `_surface_divergence(nodes_xyz, wind, neighbors, areas_ster)`：有限体积逐 cell 散度，
  供诊断脚本 `diagnose_wind_divergence.py` 使用。

### 2.5 洋流：`ocean_circulation.py`

> 详细物理（Ekman / Sverdrup / Stommel / 热盐双稳态 / 海峡闸门）见
> [knowledge/climatology/ocean_currents.md](../../knowledge/climatology/ocean_currents.md)。

洋流在 `simulate_climate` 的 **Stage 2.5**（风场之后、降水之前）挂载，单向单遍
（不做 SST↔风迭代回耦合）。三步：

1. **Stommel 流函数解**（`solve_ocean_gyre`）：对每个海盆解 β 平面摩擦涡度方程，
   西边界强化（WBC）作为摩擦边界层**自然涌现**（不手贴 ×3 系数）。流函数形式在
   赤道无 `1/f` 奇点（β=2Ωcosφ/a 在赤道最大）——nacrea 慢自转（Ω=0.31Ω⊕）下地转
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
（Stommel R，调 WBC 比）、`ocean_sst_advection_days`（τ）、`ocean_temperature_diffusivity`
（D₀，温度平流扩散）、`ocean_coastal_influence_km`、`ocean_upwelling_enabled`。

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
  "export_resolution": [4096, 2048]
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
| 降水 | ✅ 质量守恒水汽收支 + 雨出率 `k_rain` 空间调制（风暴路径 / 对流 / 热带底线均已守恒化）+ Budyko 陆地再循环 |
| 风场 | ✅ 地转 + 三圈环流（`itcz_lat_deg` 季节迁移已实现、未接线） |
| 洋流 | ✅ Stommel 环流 + SST 平流 + 涌升 |

### 待办（过渡先验 → 第一性）

| 项 | 现状 | 方向 | 位置 |
|---|---|---|---|
| 季风 | Step 4 系数 ×1.5/×1.3 固定 | 季节风反转 + 海陆热力对比驱动的向岸水汽平流（`itcz_lat_deg` 已就绪） | `climate_simulator.py` Step 4 |
| 海岸不对称 | Step 6.6 逐 cell 启发式（向岸/离岸风系数） | 涌升 + 向岸水汽平流 | `_compute_precipitation_bfs` Step 6.6 |
| 南半球 SST 过暖 | `_ocean_surface_temperature` 南半球偏暖 +4~+10°C | 独立标定 | `_ocean_surface_temperature` |
| 三圈环流边界 | Hadley 30° / Ferrel 60° 可配置 | Held-Hou 标度 φ_H ∝ (gHΔθ)^½/(Ωa)^½ 行星化 | `hadley_cell_wind` |
| nacrea 回归 | nacrea 仍走 `ebm_1d=false` legacy 路径 | flip `ebm_1d: true` 后回归验证（计划 §六 #1） | `nacrea/terrain_config.yaml` |

### 地球标定的方案常数（影响异星保真度）

| 参数 | 默认 | 说明 |
|------|------|------|
| `ebm_diffusion_wm2k` | 0.35 | 总经向热输送 D，Earth ΔT≈41°C 标定 |
| `ebm_diffusion_land_wm2k` | 0.2 | 陆地（大气）输送，≈0.6×总输送 |
| `storm_track_amplitude_mm` | 900.0 | 斜压风暴路径幅度 |
| `evaporation_base_mm` | 1000.0 | 15 °C 洋面年蒸发基准（能量限制 ~3%/°C） |

> 水汽收支的物理常数在代码内（非 config）：驻留时间 τ≈9 天（`_MOISTURE_RESIDENCE_DAYS`）、
> 湍流扩散 κ≈3.75e5 m²/s（`_MOISTURE_DIFFUSIVITY_M2S`，从 1e6 下调以抑制海洋→陆地过度
> 扩散湿润）、陆地蒸散基准因子 ≈0.55（`_LAND_EVAPOTRANSPIRATION_FRACTION`，Budyko 再循环
> 首轮初值）+ Budyko 再循环参数（`_LAND_RECYCLING_*`）。它们所有世界共享。

---

## 7. GCM 与参数化管线的定位（指导纲要）

### 结论

GCM（求解原始方程）技术上能取代参数化管线，但**不适合做主干**——计算量差 3–4 个数量级
（ExoPlaSim 一个案例数小时 vs 管线 ~2 分钟），且 GCM 的次网格参数化同样有几十个地球标定
的「补丁」，用到 nacrea 需重新标定。

### 定位

「参数化 vs GCM」不是对立，而是「参数是否物理自洽」。逐项打补丁暴露的问题（速度单位、
随意 λ）是**参数不物理**，不是参数化模型的原罪。本轮（辐合驱动降水、显式热输送季节、
大陆度）正是把「纬度高斯补丁」替换为「从风场/辐射第一性推导的物理量」，方向正确。
