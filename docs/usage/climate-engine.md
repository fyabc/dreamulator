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

### Phase 3A.1：热带降水修正 🚧 进行中

**状态**：核心调参完成（`feat/tropical-precipitation` 分支），待合并。

**已完成**：
- ✅ ITCZ 增强 700→1200 mm，σ 12→15°
- ✅ 热带对流 15→30 mm/yr/°C
- ✅ 热带降水底线（|lat|<15°, T>20°C → min 800mm）
- ✅ 副高抑制移至 convection 之后（沙漠保持干燥）
- ✅ 陆地蒸散 30%→40%
- ✅ 季节振幅 15→35，纬度梯度 45→40

**当前指标**（vs 基线）：
- A 类准确率：13.3% → **33.3%**（目标 50%，继续改进）
- D 类群组准确率：0% → **48.3%**
- 总群组准确率：40.8% → **53.9%**
- Kappa：0.102 → **0.209**

**剩余工作**：
- BWh→Cfb（400 cells）：沙漠仍偏湿，需进一步限制副热带 BFS 水汽
- Aw→BSh（188 cells）：热带内陆仍偏干

---

### Phase 3A.2：季节变化集成（下一步）

**状态**：`climate_seasonality.py` 模块已实现（光照驱动），**尚未集成到 climate_simulator.py**。

**待做**：
- [ ] 将 `compute_seasonal_climate()` 集成到 `simulate_climate()`
- [ ] 用月度 T_cold/T_hot 替换旧的 `seasonal_temperature()` 近似
- [ ] 用月度 P_factor 分配年降水为 12 个月值
- [ ] Köppen 分类改用真实月度极值（P_dry/P_wet 从月值取）
- [ ] 支持 Gaia-M 参数（obliquity=9.5°, year=80d, S0=622 W/m²）
- [ ] 验证：Cs/Cw/Af/Aw/Am 子类型正确区分

**预期效果**：
- Köppen 子类型（第三字母）正确率大幅提升
- C 类准确率：13.5% → 30%+
- 总准确率：25.5% → 35%+

**预计工期**：1–2 天

---

### Phase 3A.3：洋流 + 温度精细化

**目标**：温度 RMSE 降至 <8°C，消除 BWh→Cfb 混淆。

#### 3A.3a：风生洋流（核心）

物理链条：`风场 → Ekman 输运 → 大洋环流 → 热输送 → 沿岸温度修正`

| 子任务 | 说明 | 验证目标 |
|--------|------|---------|
| 风生表面流 | 每个海洋 cell：current = rotate(wind, 45°×sign(lat)) × 0.02 | 五大环流圈形态 |
| 西边界强化 | 环流圈西侧流速 ×3（Gulf Stream / 黑潮型） | 东岸暖流识别 |
| 沿岸热输送 | 暖流沿岸 +3~8°C，寒流沿岸 -2~5°C，衰减距离 ~500km | 西欧冬季偏暖 |
| 上升流 | 东边界离岸风 → 冷水上涌 → 沿岸降温减湿 | 纳米布/阿塔卡马更干冷 |

#### 3A.3b：季节性洋流（季风区）

| 子任务 | 说明 | 验证目标 |
|--------|------|---------|
| 季风洋流反转 | 夏季风海→陆：暖流增强；冬季风陆→海：流向反转 | 索马里洋流季节反转 |
| 季节 SST 变化 | 洋流+混合层热容量 → SST 季节滞后 1-2 月 | 沿海 T 季节振幅减小 |

#### 3A.3c：其他温度修正

| 子任务 | 说明 | 验证目标 |
|--------|------|---------|
| 冰盖反照率 | 年均 T < -10°C → 反照率 0.7 → 正反馈降温 | 极地/格陵兰更冷 |
| 云反照率 | 热带对流区 → 云量 +0.1 反照率 → 降温 2-3°C | 赤道 T 不过热 |
| 海拔-温度解耦 | 青藏高原型：高海拔+低纬 → 独立温度廓线 | 高原正确分类为 ET/H |

**预期效果**：
- 温度 RMSE：15.87 → <8 °C
- BWh→Cfb（400 cells）大幅减少（寒流让沙漠沿岸更干冷）
- Dfc→ET（618 cells）部分修复（暖流让高纬沿海回到 D）
- 总群组准确率：53.9% → 60%+

**预计工期**：2 周

**开发分支**：`feat/climate-optimization`

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

### Phase 3A.5：海洋气候分区（Longhurst 简化）

**目标**：替换单一 "Ocean" 标签，为海洋 cell 赋予有意义的气候/生态分区。

**参考系统**：Longhurst (1995/2007) 生物地球化学省份 — 海洋学中等价于 Köppen 的分类体系。
详见 `docs/knowledge/climatology/ocean_provinces.md`。

#### Phase 1：4 Biome 分类（不依赖洋流，立即可做）

| Biome | 判定条件 | 地球对应 |
|-------|---------|---------|
| POLAR | \|lat\| > 60° 或 SST < 4°C | 北冰洋、南大洋 |
| WESTERLIES | 30° < \|lat\| < 60° | 北大西洋、南大洋温带 |
| TRADES | \|lat\| < 30°（开阔大洋） | 副热带环流、赤道带 |
| COASTAL | 距海岸 < 500 km | 大陆架、沿岸流 |

#### Phase 2：子省分类（依赖 3A.3 洋流）

| 子省 | 判定条件 | 地球对应 |
|------|---------|---------|
| COASTAL_WBC | 西边界 + 暖流 | Gulf Stream、黑潮 |
| COASTAL_EBC | 东边界 + 寒流/上升流 | Humboldt、加那利 |
| COASTAL_SHELF | 浅水大陆架 | 北海、东海 |
| GYRE_CENTER | 副热带环流中心 | 太平洋垃圾带（极寡营养） |
| EQUATORIAL | \|lat\| < 5° + 上升流 | 赤道太平洋 |
| POLAR_ICE | 永久海冰 | 北极中心 |

**输出**：`VoronoiCell.ocean_province: str`（如 `"TRADES_GYRE"`）
**前端**：新增 "海洋省份" 图层（categorical 着色）
**预计工期**：Phase 1: 2 天 / Phase 2: 3 天（洋流完成后）

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
