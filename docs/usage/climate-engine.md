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

见 [`docs/usage/climate-validation.md`](climate-validation.md)。

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

## 6. 改进路线图（数据驱动）

> 优先级由空间验证混淆矩阵驱动：先修最大误差源，再逐步细化。

### Phase 3A.1：热带降水修正（最高优先级）

**目标**：解决 A→B 混淆（567 cells），将热带准确率从 7.7% 提升到 >50%。

| 子任务 | 说明 | 验证目标 |
|--------|------|---------|
| ITCZ 降水增强 | 当前 ITCZ 峰值 700 mm 不够。热带年均降水应 >1500 mm。增加到 1200–1500 mm | Af 区域 P > 1500 |
| 热带对流参数化 | 温暖海洋面（SST > 27°C）上的深对流应产生 >2000 mm/yr | 赤道带 P > 2000 |
| 副热带高压下沉 | 20–30° 的下沉气流应更强烈地抑制降水（当前 suppression 不够） | 撒哈拉 P < 100 |
| 信风汇聚增强 | 赤道附近信风汇聚 → 强制上升 → 额外对流降水 | ITCZ 带 P 峰值 sharper |

**预期效果**：
- A 类准确率：7.7% → 50%+
- 空间总准确率：18.6% → 30%+
- 降水 zonal R²：0.605 → 0.75+

**预计工期**：1–1.5 周

---

### Phase 3A.2：季节变化（解锁 D/C 类）

**目标**：产生大陆性气候（D）和正确的温带子类型（Cs/Cw/Cf）。

| 子任务 | 说明 | 验证目标 |
|--------|------|---------|
| 大陆度模型 | 陆地年较差 = f(距海距离, 纬度)。内陆 > 沿海 20–40°C | D 类 T_cold < -3°C |
| 降水季节分配 | 月降水 = 年均 × 季节因子。地中海型：夏干冬湿；季风型：夏湿冬干 | Cs/Cw 正确识别 |
| 季风反转 | 热带/副热带沿海：夏季风从海洋吹向陆地（湿），冬季反转（干） | Cwa/Cwb 出现 |
| ITCZ 逐月迁移 | 每月计算 ITCZ 位置 → 热带降水有干湿季 → Aw vs Af 区分 | Aw 准确率 > 40% |

**预期效果**：
- D 类准确率：0% → 40%+
- C 类准确率：0.8% → 30%+
- 空间总准确率：30% → 45%+
- Cohen's Kappa：0.094 → 0.3+

**预计工期**：2–3 周

---

### Phase 3A.3：温度模型精细化

**目标**：温度 RMSE 从 12.87°C 降至 <8°C。

| 子任务 | 说明 | 验证目标 |
|--------|------|---------|
| 冰盖反照率 | 年均 T < -10°C 的区域 → 冰盖 → 反照率 0.7 → 进一步降温 | 极地 T 更冷 |
| 云反照率 | 热带对流区 → 云量增加 → 反照率 +0.1 → 降温 2–3°C | 赤道 T 降 2°C |
| 洋流热输送 | 简化西边界流（Gulf Stream 型）：暖流沿岸 +5°C，寒流沿岸 -3°C | 西欧冬季偏暖 |
| 海拔-温度解耦 | 高海拔但低纬（如青藏高原）应有独特温度特征 | 高原 ET 正确 |

**预期效果**：
- 温度 RMSE：12.87 → <8 °C
- BWh→Cfb 混淆消除
- E 类准确率维持 >65%

**预计工期**：2 周

---

### Phase 3A.4：空间格局精细化

**目标**：空间准确率 >55%，Kappa >0.4。

| 子任务 | 说明 | 验证目标 |
|--------|------|---------|
| 西岸/东岸不对称 | 中纬度西岸（西风带）比东岸湿润 500+ mm | 欧洲 vs 东亚 |
| 雨影精确化 | 山脉背风侧 Föhn 效应：降水减少 70%+ | 安第斯东侧干旱 |
| 内陆干旱梯度 | 距海岸 >1500 km → 降水指数衰减 | 中亚沙漠 |
| 沿海雾降水 | 寒流沿岸（纳米布、阿塔卡马）→ 极少降水但非零 | 纳米布 P < 50 |

**预计工期**：1.5–2 周

---

### 里程碑与验收标准

| 里程碑 | 验收标准 | 预计时间 |
|--------|---------|---------|
| **M1: 热带修正** | A 类准确率 > 50%, 空间总准确率 > 30% | +1.5 周 |
| **M2: 季节变化** | D 类出现, C 类准确率 > 30%, Kappa > 0.3 | +4 周 |
| **M3: 温度精细** | 温度 RMSE < 8°C, B→C 混淆消除 | +6 周 |
| **M4: 空间精细** | 空间准确率 > 55%, Kappa > 0.4 | +8 周 |
| **合并 main** | M4 达标后合并 | +8 周 |

---

### 后续 Phase（3A 之后）

| Phase | 内容 | 依赖 |
|-------|------|------|
| **Phase 3B** | 河流网络 + 水力侵蚀 | 3A 降水模型 |
| **Phase 3C** | 文明半格式化管理 | 独立 |
| **Phase 3D** | 世界线 Diff 可视化 | 独立 |
| **前端气候可视化** | 温度/降水色阶 + 风场箭头动画 | 3A 合并后 |

### 长期愿景

| 方向 | 说明 |
|------|------|
| 简化 GCM | 从 BFS 升级为 2D 浅水方程或谱方法 |
| 动态植被 | 气候 ↔ 植被双向耦合（反照率/蒸散反馈） |
| 古气候模拟 | 冰期/间冰期、米兰科维奇参数扫描 |
| 系外行星 | 潮汐锁定、高 CO₂、极端自转周期 |
