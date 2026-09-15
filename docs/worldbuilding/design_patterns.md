# 架空世界设计模式

可复用的世界配置模板。每个模式说明概念、YAML 编码方式和源码引用。

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
├── maps/planet_earth/
│   ├── elevation.png           ← 基础地形
│   └── plates.json
│
└── branches/pangea/
    └── maps/planet_earth/      ← 存在时优先于父世界（map/manager.py 解析顺序）
        ├── elevation.png       ← 覆盖：盘古大陆
        └── plates.json         ← 重新生成
```

**参考**：
- `docs/design/architecture.md` — 层级架构与分支管理
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
num_nodes: 100000     # 节点数（引擎默认；现行标准世界用 200000）
jitter_sigma: 0.3     # Fibonacci 初始扰动（0 = 无扰动，0.3 = 推荐）
lloyd_iterations: 8   # Lloyd 松弛迭代次数（越高 cell 越均匀）
```

**参数指南**（200k cell ≈ 51 km/cell，地球级世界现行标准；量级参考：mesh 阶段
200k 约 2.5 s——Numba 内核优化后，全管线（含构造演化 + 气候）基线 ~391 s，
见 roadmap v0.36.0 口径）：

| 场景 | num_nodes | lloyd_iterations |
|------|-----------|-----------------|
| 快速原型 | 32768 | 4-5 |
| 引擎默认 | 100000 | 8 |
| 现行标准（earth / nacrea） | 200000 | 8 |

**参考**：
- `src/dreamulator/map/pipeline_types.py` — TerrainPipelineConfig
- `src/dreamulator/map/cvt_mesh.py` — `generate_cvt_mesh()`, `fibonacci_sphere()`
- `docs/design/pipelines/geological-pipeline.md` §3 — CVT 网格生成算法

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
# <world>/maps/<planet>/registry.yaml（注册表随地图产物存放）
raster_layers:
  elevation:
    layer_type: elevation
    source: imported
    file_path: elevation.png
    depends_on: []
    stale: false
  temperature:
    layer_type: temperature
    source: engine-derived
    depends_on: [elevation]
    stale: true        # elevation 更新 → BFS 级联标记 stale

vector_layers:
  plates:
    layer_id: plates
    format: plates-json
    depends_on: [elevation]
    stale: false
  provinces:
    layer_id: provinces
    format: geojson
    depends_on: [plates]
    stale: true
```

**图层标识**（`MapLayerType`）：栅格层 `elevation`（可编辑）、`terrain` /
`temperature` / `precipitation` / `biomes` / `plates_raster` / `boundaries`
（引擎派生）；矢量层 `plates` / `provinces`（文明行省，可编辑）。

**级联失效**：`mark_downstream_stale()` BFS 遍历依赖图。

**参考**：
- `src/dreamulator/map/manager.py` — `mark_downstream_stale()` / `update_registry_on_elevation_change()`
- `src/dreamulator/map/models.py` — MapMetadata, MapLayerRegistry, MapLayerType
- `docs/design/pipelines/map-system.md` — 图层依赖关系 DAG

---

## 模式 7：地图自适应配色

**概念**：地形着色自动适配行星实际高程范围——色标断点基于 `elevMinM`/`elevMaxM`/
`seaLevelM` 动态计算，无需手动调色；地球类/浅海/深谷世界同一套代码自动适配。
配色方案（海洋 NOAA ETOPO1 + 陆地 ESRI Natural Earth）与断点公式见
[map-system.md](../design/pipelines/map-system.md) 的渲染章节与
`src/viewers/map/utils/colorScales.ts` 的 `generateAdaptiveTerrainScale()`。

---

## 模式 8：PID 自适应参数调节

**概念**：比例-积分-微分控制器（PID controller）用于自动调节模拟参数，使系统在
变化条件下缓慢收敛到目标状态（板块数量稳定、海陆比等），模拟真实地质过程的惯性。
当前唯一接线用途：构造演化的板块裂解率 λ₀ 调节（板块数量稳定在 12–15）。
算法细节（滑动平均 / 触发阈值 / 调整上限）与实现见
[../knowledge/geology/cortial_2019_notes.md](../knowledge/geology/cortial_2019_notes.md)
§D.12；代码在 `src/dreamulator/map/tectonic_simulator.py` 的 `_evolve_cortial2019()`。

---

## 模式 9：地理锚定（geography.yaml）

**概念**：默认地形是纯程序化的（大陆落在哪由纬度偏好 + fBm 决定，作者无法控制）。
对于已经在设定文档里写死海陆格局的"样板世界"，用机器可读的 `geography.yaml`
把命名地貌编码为**锚点**，引擎据此构建逐 cell 陆地偏置场并以全局阈值分配地壳，
让"世界岛在 90°W、深渊洋在 0°"这类设定真正落地。

这是"受控想象引擎"的典型范例：作者给定宏观格局（锚点），程序补全微观细节
（fBm 海岸线、岛链碎裂），两者经一个混合权重 (`anchor_weight`) 调和。

**业界先例**：Gleba 的"自定义陆块概率图导入"、Azgaar 的 heightmap 模板/手绘。

```yaml
# layers/geological/input/geography.yaml
version: 1
land_fraction_target: 0.28      # 缺省则用 terrain_config.target_land_fraction
hemisphere_land_bias: 0.10      # >0 北半球偏陆（sin(lat) 平滑加权）
reapply_after_tectonics: true   # 构造演化后重新锚定（防大陆随板块漂移）

features:
  - name: 世界岛
    kind: continent             # continent/archipelago/plateau/ocean_basin/
    lon: -90.0                  #   rift_sea/shallow_sea/isthmus
    lat: 0.0
    radius_deg: 35.0            # 圆半径；拉长特征 = 半短轴（半宽）
    strength: 0.85              # + 陆地 … − 海洋；|s|>1 可"切开"下伏大陆
    elongation: 1.6             # 半长轴/半短轴（≥1，1=圆）
    bearing_deg: 0.0            # 半长轴朝向（0=北，90=东）

  - name: 大裂谷海
    kind: rift_sea
    lon: -90.0
    lat: 0.0
    radius_deg: 3.0
    strength: -2.0              # 强度须超过世界岛(+0.85)才能切穿
    elongation: 11.0            # 狭长裂谷
    bearing_deg: 0.0

  - name: 南极浅海
    kind: shallow_sea
    lon: 0.0
    lat: -90.0
    radius_deg: 20.0
    strength: -0.2
    elevation_target_m: -120.0  # 高程钉扎：陆缘浅海 120 m 水深
    pin_strength: 1.0           # 0–1；核提供空间软边
```

**调参要点**：

| 目标 | 做法 |
|------|------|
| 大陆落在指定位置 | 正 strength 锚点，半径按目标面积反推 |
| 大洋保持无陆 | 负 strength 锚点覆盖该区域 |
| 裂谷切开大陆 | rift_sea 的 `|strength|` 须大于下伏大陆 strength |
| 群岛而非整块大陆 | 弱正 strength（~0.1–0.2），让 fBm 噪声把陆地碎成岛链 |
| 全球海陆比 | `land_fraction_target`（全局阈值精确命中） |
| 陆缘浅海 / 地峡高度 | `elevation_target_m` 钉扎（负=水深、正=陆高，相对校准海面） |
| 临界海峡（冰期关闭） | 浅海钉扎 + `terrain_config.yaml: sea_level_offset_m: -120` |
| 裂谷不被横穿造山抬出海面 | 自动：强负偏置场抑制汇聚抬升（无需作者干预） |
| 手绘大陆大形 | 上传 `geography_raster.png` 灰度概率图，与 feature 叠加（Gleba 模式） |

**已知限制**：
- 海岸线偏直（海陆判定在 cell 粒度 ~51 km，见 geological-pipeline.md §4.4）
- 钉扎后不重跑校准：大陆级钉扎（>5% 表面）会偏离 `land_fraction_target`，需自调
- `sea_level_offset_m ≠ 0` 时前端色标仍按 0 m（实验旋钮定位）

**参考**：
- `docs/design/pipelines/geological-pipeline.md` §4.4 — 地理锚定算法与注入点
- `src/dreamulator/map/geography.py` — `GeographySpec` / `build_land_bias_field()` / `apply_geography_crust()`
- `data/worlds/nacrea/layers/geological/input/geography.yaml` — nacrea 实例

---

## 模式 10：文档模板渲染（Jinja2 占位符）

**概念**：世界事实（天体物理、气候/生态聚合等）的单一来源是 `system_catalog.yaml`
+ 各层 `*_summary.yaml`，由 `guard/facts.py::build_fact_context` 组装为**事实上下文**
（见 harness.md §5）。此前参数还被**手抄**进多个 Markdown 文档、衍生值靠手算，
改一次参数要手动同步多处且屡有遗漏。现在：参数表类文档写 **Jinja2 占位符**，
在**读取时**（API `layer-documents`/`design-documents` 端点）与**静态导出时**
（`export_static.py`）统一从事实上下文渲染；**渲染产物不落盘、不进 git**——渲染是
<1ms 纯函数，是缓存而非引擎产物。模板因此成为唯一被 git 跟踪的来源，从机制上
杜绝漂移。

占位符**按实体寻址**：`{{ entities.<id>.<field> }}`（天体，稳定 ID）+ 
`{{ aggregates.<layer>.<field> }}`（气候/生态/文明聚合）。旧的角色键
（`body` / `star` / `orbit` / `derived` / `satellite`）已废弃。

```markdown
<!-- 模板化前（手抄，易漂移） -->
| 太阳日 | **3.42 天（82.0 小时）** | 1/(1/3.25 − 1/67) |

<!-- 模板化后（渲染时从事实上下文填充） -->
| 太阳日 | **{{ entities.satellite_nacrea.solar_day_days | round2 }} 天（{{ entities.satellite_nacrea.solar_day_days | hours | round1 }} 小时）** | 1/(1/{{ entities.satellite_nacrea.rotation_period_days }} − 1/{{ entities.planet_aegis.period_days | round0 }}) |
```

**Filter 清单**（`doc_render.build_environment()`）：

| filter | 作用 | 示例 |
|--------|------|------|
| `round0`/`round1`/`round2` | 四舍五入到整数/1/2 位 | `{{ entities.planet_aegis.period_days \| round0 }}` → 67 |
| `hours` | 天 → 小时（×24），常与 round 组合 | `{{ entities.satellite_nacrea.period_days \| hours \| round0 }}` → 78 |
| `pct` | 小数 → 百分比字符串 | `{{ entities.star_ignis.evolution_progress \| pct }}` → 8.8% |
| `group` | 千分位分组定长（`group`/`group(1)`） | `{{ entities.satellite_nacrea.hill_radius_km \| group }}` → 66,715 |
| `"%.2f"\|format(...)` | 定长小数（保尾随零） | → 1.20 |

**降级行为**（`render_body()` 返回 `(text, rendered)`）：

| 情形 | 行为 |
|------|------|
| 无占位符的文档 | 原样直通，`rendered: true` |
| 缺 `system_catalog.yaml`（fresh clone / 分支未构建） | 返回模板原文 + `rendered: false`，前端显示横幅提示 |
| 个别变量缺失（节被按需省略） | 按源码回显 `{{ path }}`，不崩溃 |
| 语法错误 / 沙箱违规 | 返回原文 + warning 日志，`rendered: false` |

**分支继承**：分支继承父世界的模板，但用**分支自己的** `system_catalog.yaml`
渲染。覆写了天文 input 却未构建 derived 的分支**不回退**根世界数据——那可能已是
不同的恒星系——而是降级显示源码。

**调参要点**：

| 目标 | 做法 |
|------|------|
| 参数表数值模板化 | 确认字段在 `system_catalog.yaml` 对应实体中存在，写占位符 + 选合适 filter |
| 链式手算量 / 观测量 / 叙事量 | 保留手写（不做成占位符） |
| 定长小数（如 1.20） | `"%.2f" \| format(...)`（`round2` 会丢尾随零） |
| frontmatter | 永不渲染——标题/tags 勿放占位符 |

**参考**：
- `src/dreamulator/doc_render.py` — `parse_frontmatter()` / `load_render_context()` / `render_body()` / filters
- `src/dreamulator/guard/facts.py::build_fact_context` — 事实上下文（实体 + 聚合）
- `src/dreamulator/engine/physical_inputs.py::build_system_catalog` — `system_catalog.yaml` 的生产者（含卫星动力学派生量：`hill_radius_km`/`a_rh_ratio`/互希尔间距/`synchronous_orbit_radius_km`/自转轴方位；物理源 `engine/satellite_dynamics.py`）
- `docs/design/roadmap.md` #22 — 世界参数单一来源（两阶段）背景
- `data/worlds/nacrea/layers/astronomy/input/orbital_dynamics.md` — nacrea 模板化实例

---

*模式将持续从代码库中提取和补充。每个模式的 "参考" 给出了源码位置以便查阅。*
