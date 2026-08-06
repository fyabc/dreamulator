# 气候引擎实现架构

> 本文档描述 dreamulator 气候引擎（Phase 3A）的代码架构、模块职责和集成方式。

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
│  climate_physics.py          climate.py                       │
│  (纯函数，无 I/O)            (BaseEngine 封装)                 │
│  ├─ equilibrium_temperature  ├─ ClimateEngine.run()           │
│  ├─ latitude_temperature     │   ├─ 读 planets.yaml           │
│  ├─ altitude_lapse_rate      │   ├─ 读 stellar.yaml           │
│  ├─ seasonal_temperature     │   ├─ 加载 CVT mesh             │
│  ├─ hadley_cell_wind         │   ├─ 调用 simulate_climate()   │
│  ├─ evaporation_rate         │   └─ 写输出文件               │
│  ├─ orographic_precipitation │                                │
│  ├─ koppen_classify          │                                │
│  └─ ...                      │                                │
└──────────────────────┬───────────────────────────────────────┘
                       │ 调用
┌──────────────────────▼───────────────────────────────────────┐
│                    src/dreamulator/map/                        │
│                                                              │
│  climate_simulator.py         export.py                       │
│  (CVT mesh 操作)              (栅格导出)                      │
│  ├─ simulate_climate()        ├─ export_climate_layers()      │
│  │   ├─ 温度                  │   ├─ temperature.png           │
│  │   ├─ 风场                  │   ├─ precipitation.png         │
│  │   ├─ BFS 水汽输送          │   ├─ koppen.json              │
│  │   └─ Köppen 分类           │   └─ climate_metadata.json    │
│  └─ _compute_precipitation_bfs                                │
└──────────────────────────────────────────────────────────────┘
```

**两个入口路径**：

| 入口 | 触发方式 | 适用场景 |
|------|---------|---------|
| `simulate_climate(mesh, config)` | 地形管线 Stage 6 | CVT mesh 已有 elevation，直接跑气候 |
| `ClimateEngine.run()` | DAG 管线 `dreamulator build earth` | 独立引擎运行，读写标准层文件 |

---

## 2. 模块详解

### 2.1 `climate_physics.py` — 纯物理函数

**设计原则**：无 I/O、无 RNG、确定性、可单元测试。

全部函数接收 numpy 数组，返回 numpy 数组。所有系数通过参数传入（无隐式常数）。

| 函数 | 物理含义 | 测试 |
|------|---------|------|
| `equilibrium_temperature()` | 恒星辐射 → 黑体平衡温度 | ✅ |
| `surface_temperature()` | + 温室效应 | ✅ |
| `latitude_temperature()` | sin² 纬度依赖 | ✅ |
| `altitude_lapse_rate()` | 海拔递减率 | ✅ |
| `seasonal_temperature()` | 轴倾角 → 季节周期 | ✅ |
| `hadley_cell_wind()` | 三圈环流风场 | ✅ |
| `terrain_wind_blocking()` | 山脉挡风 | ✅ |
| `evaporation_rate()` | 海面蒸发（Clausius-Clapeyron） | ✅ |
| `orographic_precipitation()` | 地形抬升降水 | ✅ |
| `itcz_latitude()` | ITCZ 纬度 | ✅ |
| `koppen_classify()` | Köppen-Geiger 分类 | ✅ |
| `ekman_current_direction()` | Ekman 输运方向 | ⏳ |

### 2.2 `climate_simulator.py` — CVT mesh 气候模拟

**入口**：`simulate_climate(mesh: CVTMesh, config: TerrainPipelineConfig) -> None`

**执行流程**：

```
1. 提取 CVT mesh → numpy 数组
2. Stage 1: 温度
   ├─ EBM 平衡温度
   ├─ 纬度梯度 (sin²)
   ├─ 海拔修正（仅陆地）
   └─ SST 估算（海洋）
3. Stage 2: 风场
   ├─ 气压场 (barometric + thermal low)
   ├─ 梯度 (图差分)
   ├─ 地转风 (Coriolis)
   ├─ Hadley/Ferrel/Polar 叠加
   └─ 地形阻挡
4. Stage 3: 降水（多 pass BFS）
   ├─ 海洋蒸发 (Clausius-Clapeyron)
   ├─ 沿风向 BFS 水汽输送
   ├─ 地形降水 / 雨影
   └─ ITCZ 对流增强
5. Stage 4: Köppen 分类
   └─ (T_mean, T_cold, T_hot, P_annual, P_dry, P_wet) → 代码
6. 写回 mesh.cells
```

### 2.3 `climate.py` — DAG 引擎封装

`ClimateEngine` 实现 `BaseEngine` 接口：

```python
class ClimateEngine(BaseEngine):
    name = "climate"
    layer = Layer.CLIMATE
    requires = ["astronomy"]  # stellar params
    input_files = ["stellar.yaml", "stellar_derived.yaml", "planets.yaml"]
    output_files = ["climate_summary.yaml", ...]
```

**执行**：`uv run dreamulator build earth --engine climate`

### 2.4 `export.py` — 气候图层导出

`export_climate_layers(mesh, output_dir, config)` 生成：

- `temperature.png` — 16-bit PNG，范围 [-40, +50] °C
- `precipitation.png` — 16-bit PNG，范围 [0, 6000] mm/yr
- `koppen.json` — per-cell 分类 + 统计汇总
- `climate_metadata.json` — 模拟参数记录

---

## 3. 数据流

### 3.1 通过地形管线

```
terrain_config.yaml
       │
       ▼
  terrain_pipeline.py (stages: mesh → plates → ... → climate → export)
       │
       ▼
  simulate_climate(mesh, config)   ← climate_simulator.py
       │
       ▼
  export_climate_layers(mesh, ...)  ← export.py
       │
       ▼
  output/maps/earth/
    ├── temperature.png
    ├── precipitation.png
    ├── koppen.json
    └── climate_metadata.json
```

### 3.2 通过 DAG 引擎

```
planets.yaml + stellar.yaml + cvt_mesh.json
       │
       ▼
  ClimateEngine.run()
       │
       ├── 读取行星参数（radius, rotation, atmosphere, orbit）
       ├── 加载 CVT mesh（从 geological derived）
       ├── 构建 TerrainPipelineConfig
       ├── 调用 simulate_climate()
       ├── 导出 raster + JSON
       └── 写入 climate/derived/
```

---

## 4. 输出格式

### temperature.png / precipitation.png

16-bit 单通道 PNG（与 elevation.png 相同编码方式）。前端解码：

```typescript
const normalized = pixelValue / 65535;
const temperature = tMin + normalized * (tMax - tMin);  // from climate_metadata.json
```

### koppen.json

```json
{
  "cells": { "0": "Cfa", "1": "Aw", ... },
  "summary": { "Cfa": 3200, "Aw": 1500, "BWh": 4800, ... },
  "num_cells": 32768
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

**当前精度**（v0.2.0，ETOPO1 真实高程输入，earth/climate-dev 分支）：

| 指标 | 值 | 阈值 | 状态 |
|------|-----|------|------|
| 全球均温 | 15.0 °C | 15 °C (地球) | ✅ |
| 陆地比例 | 29.1% | 29.0% (地球) | ✅ |
| 降水 RMSE (加权) | 493 mm/yr | < 800 mm/yr | ✅ |
| 降水 Bias | +20 mm/yr | — | ✅ |
| 降水 R² | 0.605 | — | ✅ |
| 温度 RMSE (加权) | 12.87 °C | < 5 °C | ❌ |
| Köppen 分布匹配 | 48.3% | > 55% | ❌ |
| **Köppen 空间准确率** | **18.6%** | > 55% | ❌ |
| **Köppen 群组准确率** | **43.0%** | — | — |
| **Cohen's Kappa** | **0.094** | > 0.4 | ❌ |

**空间混淆矩阵**（top 5 错误来源）：

| 观测 → 模拟 | 数量 | 根因 |
|-------------|------|------|
| Af/Aw → BWh/BSh | 567 cells | 热带降水不足 |
| BWh → Cfb | 112 cells | 亚热带温度偏低 |
| D* → (缺失) | 165 cells | 无季节温差 |
| C* → (缺失) | 240 cells | 温带条件不满足 |

---

## 6. 已知限制与调优方向

> 改进路线图（Phase 3A 子任务分解、验收里程碑、长期愿景）已单点收敛至
> [roadmap.md](roadmap.md) §4。本节仅保留代码级已知限制与调优方向。

### Phase 3A.6：方案常数行星化与工程清理

来源：2026-08-03 性能优化（`perf/profiling-and-optimization` 分支 0.0c）期间的
气候代码 hard-code 系统审计。**行星相关硬编码已在 0.0c 修复**：反照率（planets.yaml
注入）、轨道周期（开普勒第三定律 `P = 365.25·√(a³/M★)` 从已解析量导出）、重力/标高与
海平面气压（行星质量/半径 + 大气压）、SST 纬度剖面锚定（地球剖面 + `t_surf − t_surf⊕`
整体平移，地球比特级复现、异星随强迫 1:1 响应）。

以下为**地球调优的方案常数**——不是数据错误，但影响异星保真度：

| 项 | 现状（地球硬编码） | 行星化方向 | 位置 |
|---|---|---|---|
| 三胞环流边界 | Hadley 0–30° / Ferrel 30–60° / Polar 60–90° 固定 | Held-Hou 标度 φ_H ∝ (gHΔθ)^½/(Ωa)^½：慢自转 → Hadley 胞加宽（gaia-m Ω=0.31⊕ → ~50°+，当前方案形式上越界） | `climate_physics.py::hadley_cell_wind`（296-310） |
| 季节振幅 | `seasonal_amplitude_c=35` 常数（docstring 写 30，不一致） | 依赖热惯性 / 年长 / 海洋占比；修正 docstring | `climate_physics.py::seasonal_temperature`（148） |
| 降水封顶次序 | `np.minimum(precip, 12000)` 在 ITCZ/季风加成**之前**，封顶失效（gaia-m 实测 Pmax 19800）；12000 为地球值 | 移到全部加成之后；封顶可配置或按气候态设定 | `climate_simulator.py:571` vs 584-597 |
| 季风方案 | 系数 1.5/1.3、纬度阈 20°/35° 固定 | 依赖海陆热力对比 / ITCZ 振幅 | `climate_simulator.py`（589-597） |
| 次行星半球强迫（卫星世界） | 无经度强迫：温度场 = 纬向平均 + 地形 | 行星反照（~2 W/m²）+ 热红外（~1.4 W/m²）+ 食遮蔽 → 潮汐锁定坐标系下准静态强迫场（78h 太阳日相位调制 + 食季）；gaia-m 上产生次 Aegis 半球夜侧 ~1–2°C 增温与大陆干涸不对称（`climate_zones.md` 设定，物理自洽） | `climate_simulator.py` Stage 1（新强迫场） |
| 柯本月分配 | `seasonality=0.4` 常数 | 由倾角 / 轨道偏心率驱动干湿月对比 | `climate_simulator.py:209` |
| 蒸发/BFS 调优参数 | 陆面系数 0.40、BFS 12 趟、逐跳 4%/90%、海洋上限 5000 | 与 3A.3d 降水物理改进联合标定 | `climate_simulator.py`（61, 450, 556-559） |
| 工程清理 | 太阳常数三处重复定义（1361.0）；`climate_seasonality.py` 为死模块（全库零引用）但含正规日照日长模型 | 常数并入 `utils/constants`；死模块删除或转正为 NLO 季节变化（配合 3A.2） | `climate_physics.py:28`、`climate_seasonality.py:31`、`stellar_physics.py:28` |

**与 EFT 架构纪律的关系**（见 `private/plans/perf-profiling-and-optimization.md` §4.0）：
环流胞宽度是"纬向平均气候"有效理论的 NLO 修正——快速自转类地行星上当前硬编码在适用域内；
慢自转 / 高倾角行星越界，验证器应告警（与气候代理的适用域元数据机制一致）。

**预计工期**：Hadley 行星化 2 天；其余随 3A.3d 联合标定（~3 天）

---
