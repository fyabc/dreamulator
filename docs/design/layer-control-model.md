# 层级控制模型：引擎推演 vs 用户设定

> 来源：2026-08 设计讨论。定义 Dreamulator 各 DAG 层级中"引擎自动推演"与"用户手动控制"的平衡框架。

---

## 一、核心设计哲学：四层控制模型

Dreamulator 的每个 DAG 层级都应遵循统一的四层架构：

```
┌─────────────────────────────────────────────────────────┐
│  Layer 4: Override（覆写层）                              │
│  逐 cell / 逐实体的数值强制设定，绑定 seed                 │
├─────────────────────────────────────────────────────────┤
│  Layer 3: Constraint（约束层）                            │
│  语义化、命名化的宏观控制，seed 无关                       │
├─────────────────────────────────────────────────────────┤
│  Layer 2: Engine Computation（引擎推演层）                │
│  物理/数学计算，从 input 推导 derived                     │
├─────────────────────────────────────────────────────────┤
│  Layer 1: Validation（校验层）                            │
│  一致性检查、物理守恒律验证、警告/拒绝机制                 │
└─────────────────────────────────────────────────────────┘
```

**关键原则**：
- **约束层**是"作者意图"的表达——"我要这里有一座山脉"
- **引擎层**是"物理后果"的计算——"这座山脉会导致雨影效应"
- **校验层**是"自洽性守卫"——"这个设定是否违反能量守恒？"
- **覆写层**是"最终裁决权"——"我不管物理怎么说，这个 cell 的温度就是 30°C"

### 约束类型分级

| 类型 | 语义 | 引擎行为 | 示例 |
|------|------|---------|------|
| **Hard Constraint** | 必须满足 | 违反则报错 | "海陆比必须为 30%" |
| **Soft Constraint** | 尽量满足 | 违反则警告 | "此区域偏好干旱" |
| **Preference** | 倾向性 | 违反则记录日志 | "海岸线偏好曲折" |
| **Override** | 直接覆写 | 跳过引擎计算 | "#7244 elevation=-20m" |

### 地质层已实现的两层编辑

地质层是第一个落地此模型的层级：

| 层级 | 载体 | seed 依赖 | 粒度 | 示例 |
|------|------|----------|------|------|
| 约束层 | `geography.yaml` | 无关 | 命名地貌 | "这里要有裂谷海" |
| 覆写层 | `edits.json` | 绑定 | 逐 cell | "#7244 elevation −20m" |

---

## 二、逐层设计方案

### 2.1 Physics Layer（物理层）

**当前状态**：仅含物理常量和单位换算。

```yaml
# layers/physics/input/physics.yaml
constants:
  G: 6.674e-11        # 引力常数
  c: 2.998e8          # 光速
  k_B: 1.381e-23      # 玻尔兹曼常数
  sigma_SB: 5.670e-8  # 斯特藩-玻尔兹曼常数

# 覆写层：允许"异物理宇宙"
overrides:
  gravity_scale: 1.0       # 重力缩放因子
  entropy_direction: 1     # 熵增方向（-1 = 时间倒流）

# 校验层
validation:
  mode: strict             # strict | lenient | off
  max_gravity_scale: 10.0
```

**平衡策略**：99% 引擎控制。物理常量是"宪法"，仅允许修改影响世界构建的宏观参数。

### 2.2 Chemistry Layer（化学层）

**当前状态**：未实现。

```yaml
# layers/chemistry/input/atmosphere.yaml
composition:
  N2: 0.78
  O2: 0.21
  CO2: 0.0004
  CH4: 0.000002
  H2O_vapor: variable    # 由气候引擎动态计算

total_pressure_hpa: 1013.25

# 约束层：用"效果"代替"成分"
constraints:
  greenhouse_forcing_K: null    # 若填写，跳过成分→辐射计算
  uv_shielding: "earth-like"    # 臭氧层等效描述

# 覆写层
overrides:
  co2_ppm: null          # 直接设定 CO2 浓度（绕过动态碳循环）
```

**引擎职责**：从成分计算辐射强迫、温室效应、气压标高、光谱吸收特性。

**平衡策略**：
- 用户设定成分（input）→ 引擎计算辐射效果（derived）
- 用户可直接设定温室强迫（constraint）→ 引擎反推所需成分
- 一致性校验：若同时给出成分和强迫，验证偏差 ≤ 20%

### 2.3 Astronomy Layer（天文学层）

**当前状态**：已实现。恒星物理 + 轨道力学。使用自变量/因变量分类 + 一致性校验模式。

**改进方向**：

```yaml
# layers/astronomy/input/stellar_events.yaml
events:
  - id: supernova_nearby
    type: external_perturbation
    time_myr: 500
    effect:
      radiation_burst_Gy: 0.5
      cosmic_ray_increase: 3.0
    affected_layers: [climate, ecology]
```

**新增约束类型**：轨道共振约束、潮汐锁定约束、宜居带约束。

### 2.4 Geological Layer（地质层）

**当前状态**：已实现。CVT 网格 + 板块构造（Cortial 2019）+ 地形合成 + 地理锚定。

**约束层增强方向**：

```yaml
# geography.yaml 增强
features:
  - id: northern_continent
    type: continent
    anchor: {lat: 70, lon: 0, radius_deg: 25}
    constraints:
      min_area_km2: 5e6
      coastline_style: "fjord-dominated"   # 新增
      tectonic_setting: "passive_margin"   # 新增

# 全局风格约束
style:
  continent_shape: "irregular"     # irregular | circular | elongated
  mountain_distribution: "clustered"
  island_density: 0.3
  volcanic_activity: "moderate"
```

**覆写层改进（edits.json）**：

```json
{
  "version": "0.23.0",
  "seed": 42,
  "edits": [
    {
      "type": "elevation",
      "target": {"cell_id": 7244},
      "value": -20.0,
      "reason": "切开北方内海通道",
      "persistence": "seed_bound",
      "migration_strategy": "nearest_neighbor"
    }
  ]
}
```

`persistence` 区分：
- `seed_bound`：绑定 seed，换 seed 标记 stale
- `feature_bound`：绑定命名特征，可跨 seed 迁移

### 2.5 Climate Layer（气候层）

**当前状态**：EBM + 风带 + BFS 降水 + Köppen + Stommel 洋流。

```yaml
# layers/climate/input/climate_constraints.yaml
constraints:
  - id: arid_interior
    type: soft
    target: {region: "continental_interior"}
    effect: "precipitation_reduction"
    value: 0.6

# 场景注入：瞬态气候事件
scenarios:
  - id: volcanic_winter
    time_yr: 500
    duration_yr: 5
    effect:
      global_temp_offset_K: -3.0
      precipitation_reduction: 0.2
```

**改进方向**：
- **反向推导模式**：用户设定"此区域应为热带雨林"→ 引擎反推所需 T/P 范围 → 校验
- **气候分区锁定**：锁定某些区域的气候类型，引擎在其余区域自由计算
- **古气候扫描**：设定米兰科维奇参数序列，引擎计算冰期-间冰期循环

### 2.6 Ecology Layer（生态层）

**当前状态**：P0 已实现（Whittaker 群系、Miami NPP、可驯化标签）。

```yaml
# layers/ecology/input/ecology_constraints.yaml
biome_overrides:
  - region: {feature_id: isolated_island_chain}
    biome: "tropical_rainforest"
    reason: "信风迎风坡，尽管纬度偏高"

modifiers:
  - id: megafauna_presence
    target: {biome: "temperate_grassland"}
    effect: "large_herbivore_availability"
    value: "high"

  - id: isolated_continent
    target: {region: "isolated_continent"}
    effect: "endemism_rate"
    value: 0.7    # 70% 特有物种
```

**改进方向**：
- **生态隔离机制**：根据海洋/山脉/沙漠自动计算物种分布隔离效应
- **生态演替时间轴**：定义"此区域 1000 年前是草原，现在是森林"
- **入侵物种事件**：注入"大陆桥形成"事件，引擎计算物种交换和生态冲击

### 2.7 Civilization Layer（文明层）

**当前状态**：设计文档已完成（[civilization-layer.md](civilization-layer.md)），引擎未实现。

```yaml
# layers/civilization/input/civilizations.yaml
entities:
  - id: maritime_empire
    name: "碎门帝国"
    type: empire
    origin:
      anchor: {cell_id: 32361}
      year: -500
    tags: ["maritime", "trade_focused", "thalassocracy"]
    constraints:
      - type: "geographic_determinism"
        source: "strait_control"
        effect: {trade_income: "+50%", naval_power: "+30%"}
      - type: "ecological_base"
        source: "ecology_summary"
        effect: {carrying_capacity: "auto"}
    modifiers:
      - type: "technological_advancement"
        source: "navigation_tools"
        effect: {exploration_range: "+100%"}
    overrides:
      population: 2_000_000
      territory_cells: [32361, 32362, 32400]

# 事件流
events:
  - id: strait_closure
    type: environmental_crisis
    trigger:
      condition: "sea_level_offset_m < -100"
    effects:
      - {target: maritime_empire, mod: "trade_collapse", severity: 0.8}
    narrative_seed: "碎门海峡因海退而关闭，帝国贸易命脉断绝"
```

**平衡策略**：用户定义实体和初始条件 → 引擎计算承载力和发展轨迹 → 用户注入关键事件 → LLM 渲染叙事。

---

## 三、跨层协调机制

### 3.1 级联影响追踪（DAG Diff）

当用户修改某一层时，系统自动标记下游层级为 Dirty：

```
用户修改 geography.yaml（地质层）
    ↓ 引擎重新计算地形
    ↓ 标记 climate 为 Dirty
    ↓ 标记 ecology 为 Dirty
    ↓ 标记 civilization 为 Dirty（承载力可能变化）
```

每层 `derived/` 目录包含 `manifest.json`，记录输入指纹。上游变更后 `dreamulator build --cascade` 自动重建所有 stale 层。

### 3.2 冲突解决策略

```yaml
# conflict_resolution.yaml
strategy: "warn_and_proceed"  # reject | warn_and_proceed | silent_override

conflicts:
  - type: "energy_violation"
    action: reject
  - type: "biome_climate_mismatch"
    action: warn_and_proceed
  - type: "civilization_carrying_capacity"
    action: warn_and_proceed
```

### 3.3 时间轴统一

所有层级的编辑都应支持时间维度：

```yaml
# timeline.yaml
epochs:
  - id: formation
    time_range: [0, 1e9]
    active_layers: [physics, chemistry, astronomy]
  - id: geological_era
    time_range: [1e9, 1e6]
    active_layers: [geological]
  - id: climate_epoch
    time_range: [1e6, 1e4]
    active_layers: [climate, ecology]
  - id: civilization_era
    time_range: [1e4, present]
    active_layers: [civilization]
```
