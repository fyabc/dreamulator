# 架空世界设计模式

可复用的世界配置模板。每个模式说明概念、YAML 编码方式和源码引用。

> 科学知识文档已迁移至 `docs/knowledge/` 目录。

---

## 模式 1：分支与层级继承

**概念**：类似 Git branch，在任意学科层（天文/地质/气候）分叉世界，
共享上游数据，仅存储分叉层及之后的修改。适用于 "what-if" 推演
（"如果大陆形状不同会怎样？"）。

**实现**：
- `data/worlds/<name>/branches/<branch>/branch.yaml` 声明 `fork_point` 层级
- 引擎通过 `LayerResolver.find_input()` 沿继承链向上搜索
- 数据合并使用 `_inherit: true` 标记，Pydantic `model_validator` 处理

**YAML 示例**：

```yaml
# data/worlds/myworld/branches/pangea/branch.yaml
name: pangea
fork_point: geological
description: "盘古大陆分支 — 在 geological 层分叉"
```

```
基础世界 (main)
├── layers/geological/input/maps/earth/
│   ├── elevation.png           ← 基础地形
│   └── plates.json
│
└── branches/pangea/
    └── layers/geological/input/maps/earth/
        ├── elevation.png       ← 覆盖：盘古大陆
        └── plates.json         ← 重新生成
```

**参考**：
- `docs/usage/project-structure.md` — 层级架构与分支管理
- `src/dreamulator/resolver.py` — LayerResolver 实现
- `src/dreamulator/branch_manager.py` — Branch CRUD

---

## 模式 2：双星 / 多星系统

**概念**：在 `stellar.yaml` 中声明多个恒星，通过 `orbits` 表定义
层级轨道关系（如 A-B 互绕 + 行星绕 AB 质心）。

**YAML 示例**：

```yaml
# layers/astronomy/input/stellar.yaml
stars:
  - id: star_A
    spectral_class: G
    mass: 1.0
    position: { x: -0.5, y: 0, z: 0 }

  - id: star_B
    spectral_class: K
    mass: 0.7
    position: { x: 0.5, y: 0, z: 0 }

orbits:
  # 双星互绕（质心在原点）
  - body_id: star_A
    parent_id: null
    semi_major_axis_au: 0.5
    eccentricity: 0.0

  - body_id: star_B
    parent_id: null
    semi_major_axis_au: 0.5
    eccentricity: 0.0
    mean_anomaly_epoch_deg: 180  # 与 A 相对

  # 行星绕双星质心（P-type / circumbinary）
  - body_id: planet_tatooine
    parent_id: null              # 绕系统质心
    semi_major_axis_au: 2.5
    eccentricity: 0.02
```

**参考**：
- `src/dreamulator/models/world.py` — Star/OrbitBody 模型
- `src/dreamulator/engine/astronomy.py` — 双星宜居带计算
- `src/dreamulator/viewers/utils/scale.ts` — `computeOrbitalPosition()` 多层级位置解析

---

## 模式 3：行星类型与水文配置

**概念**：通过 `planet_type`、`atmosphere`、`hydrosphere` 等字段
定义行星表面特征。`PlanetMesh` 根据类型自动着色。

**YAML 示例**：

```yaml
# layers/geological/input/planets.yaml
bodies:
  - id: planet_earth
    planet_type: terrestrial
    mass_earth: 1.0
    radius_km: 6371
    hydrosphere:
      water_coverage: 0.71
    atmosphere:
      surface_pressure_atm: 1.0
      composition:
        N2: 0.78
        O2: 0.21
        Ar: 0.009

  - id: planet_ocean
    planet_type: ocean_world        # 类地 + 100% 海洋
    mass_earth: 1.2
    radius_km: 6800
    hydrosphere:
      water_coverage: 0.98
    atmosphere:
      surface_pressure_atm: 3.0

  - id: planet_gasgiant
    planet_type: gas_giant
    mass_earth: 318
    radius_km: 69911
```

**行星类型表**（`PlanetMesh.tsx::PLANET_TYPE_LABELS`）：

| Type | 中文 | 渲染 |
|------|------|------|
| `terrestrial` | 类地行星 | 蓝绿褐混合（基于 water_coverage） |
| `gas_giant` | 气态巨行星 | 橙棕色 |
| `ice_giant` | 冰巨行星 | 青蓝色 |
| `ocean_world` | 海洋世界 | 深蓝色 |
| `dwarf` | 矮行星 | 灰棕色 |

**参考**：
- `src/dreamulator/models/world.py` — Planet 模型
- `src/dreamulator/viewers/PlanetMesh.tsx` — `getPlanetColor()`

---

## 模式 4：CVT 网格参数化

**概念**：调整球面 CVT 网格参数以控制地形精度和生成时间。

**YAML 示例**：

```yaml
# layers/geological/input/terrain_config.yaml
seed: 42
num_nodes: 4096       # 节点数（快速迭代：~4000；生产质量：~100000）
jitter_sigma: 0.3     # Fibonacci 初始扰动（0 = 无扰动，0.3 = 推荐）
lloyd_iterations: 8   # Lloyd 松弛迭代次数（越高 cell 越均匀）
```

**参数指南**：

| 场景 | num_nodes | lloyd_iterations | 预计耗时 |
|------|-----------|-----------------|---------|
| 快速原型 | 4096 | 4-5 | ~7s |
| 标准质量 | 50000 | 8 | ~40s |
| 生产质量 | 100000 | 8-10 | ~70s |

**参考**：
- `src/dreamulator/map/pipeline_types.py` — TerrainPipelineConfig
- `src/dreamulator/map/cvt_mesh.py` — `generate_cvt_mesh()`, `fibonacci_sphere()`
- `docs/usage/terrain-pipeline.md` §2 — CVT 网格生成算法

---

## 模式 5：地形配置覆写

**概念**：通过 `terrain_config.yaml` 覆写高程范围、海平面、噪声等参数。

```yaml
# layers/geological/input/terrain_config.yaml
elevation_min_m: -11000
elevation_max_m: 9000
sea_level_m: 0.0

# 地形合成
continental_elevation_m: 850      # 大陆基准高程
oceanic_elevation_m: -3800        # 洋底基准高程
boundary_influence_km: 500        # 构造边界影响半径
convergent_uplift_m: 4000         # 汇聚边界抬升
divergent_depth_m: 2000           # 离散边界下沉

# 噪声
noise_octaves: 6
noise_persistence: 0.5
noise_lacunarity: 2.0
noise_amplitude_land_m: 600
noise_amplitude_ocean_m: 300
```

**不同世界类型的推荐值**：

| 参数 | 类地行星 | 干旱世界 | 海洋世界 |
|------|---------|---------|---------|
| `sea_level_m` | 0 | -500 | +200 |
| `continental_elevation_m` | 850 | 600 | 400 |
| `noise_amplitude_land_m` | 600 | 800 | 300 |

**参考**：
- `src/dreamulator/map/pipeline_types.py` — TerrainPipelineConfig
- `src/dreamulator/map/terrain_synthesizer.py` — `synthesize_terrain()`

---

## 模式 6：地图图层依赖图

**概念**：通过 `registry.yaml` 声明栅格/矢量图层的依赖关系，
DAG 引擎在 upstream 修改时自动标记 downstream 为 `stale`。

```yaml
# layers/geological/input/maps/earth/registry.yaml
raster_layers:
  elevation:
    source: imported
    file_path: elevation.png
    depends_on: []
    stale: false
  temperature:
    source: engine-derived
    depends_on: [elevation]
    stale: true        # elevation 更新 → BFS 级联标记 stale

vector_layers:
  plates:
    depends_on: [elevation]
    stale: false
  provinces:
    depends_on: [voronoi, plates]
    stale: true
```

**依赖链**：
```
elevation → plates → provinces → civ_territory
elevation → features (河流/山脊)
elevation → temperature → biomes
```

**级联失效**：`mark_downstream_stale()` BFS 遍历依赖图。

**参考**：
- `src/dreamulator/map/manager.py` — `mark_downstream_stale()`
- `src/dreamulator/map/models.py` — MapMetadata, MapLayerRegistry
- `docs/usage/map-system.md` — 图层依赖关系 DAG

---

## 模式 7：地图自适应配色

**概念**：地形着色自动适配行星实际高程范围。色标断点基于
`elevMinM`/`elevMaxM`/`seaLevelM` 动态计算，无需手动调色。

```
配色方案：海洋 NOAA ETOPO1 + 陆地 ESRI Natural Earth
断点位置：minElev → +15% → +30% → sea-2% → sea-0.5% → sea →
          +0.5% → +2% → +8% → +18% → +30% → +35% → +40% → maxElev
```

**不同世界的自动适配**：

| 场景 | 最低点 | 最高点 | 海平面位置 |
|------|--------|--------|-----------|
| 地球类 | -11000m | 9000m | 0m (归一化 0.55) |
| 浅海世界 | -3000m | 5000m | -500m (归一化 0.31) |
| 深谷世界 | -20000m | 6000m | 0m (归一化 0.77) |

**参考**：
- `src/viewers/map/utils/colorScales.ts` — `generateAdaptiveTerrainScale()`
- `docs/design/roadmap-analysis.md` — 配色方案调研

---

*模式将持续从代码库中提取和补充。每个模式的 "参考" 给出了源码位置以便查阅。*
