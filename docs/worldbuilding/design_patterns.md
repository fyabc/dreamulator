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
- `docs/design/geological-pipeline.md` §2 — CVT 网格生成算法

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
- `docs/design/map-system.md` — 图层依赖关系 DAG

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
- `docs/design/roadmap.md` — 配色方案调研

---

## 模式 8：PID 自适应参数调节

**概念**：比例-积分-微分控制器（PID controller）是工业控制中的经典算法，
在 dreamulator 中用于自动调节模拟参数，使系统在变化条件下保持目标状态。
核心思想：**测量当前值 → 与目标比较 → 微调参数 → 重复**。

与一步到位的参数设定不同，PID 提供**缓慢适应**——模拟真实地质/物理过程的惯性。

**算法伪代码**：

```python
def adaptive_pid(current_value, target, base_rate, history):
    # 滑动平均平滑噪声
    avg = mean(history[-window:])

    # 比例响应（P 项）：偏差越大，调整越强
    if avg < target * 0.6:      # 严重偏低
        rate = min(base_rate * 5, rate * 1.25)   # 加速但设上限
    elif avg > target * 1.5:    # 严重偏高
        rate = max(base_rate * 0.2, rate * 0.80) # 减速但设下限
    else:                        # 正常范围
        rate += (base_rate - rate) * 0.1          # 向基准衰减

    return rate
```

**关键参数**：

| 参数 | 含义 | 推荐值 |
|------|------|--------|
| 窗口大小 | 滑动平均的步数 | 5（平衡响应速度与噪声过滤） |
| 触发阈值 | 离目标多远才调整 | 0.6× / 1.5×（避免频繁微调） |
| 调整速率 | 每次调整的幅度 | ×1.25 / ×0.80（缓慢修正） |
| 上限/下限 | 防止失控 | ×5 / ×0.2（绝对不许裂解归零或暴增） |
| 衰减速率 | 正常时向基准回归 | 0.1（每步回归 10%） |

**代码库中的使用**：

| 模块 | 文件 | 调节目标 | PID 参数 |
|------|------|---------|----------|
| 构造演化 | `tectonic_simulator.py:489-502` | 板块数量稳定在 12-15 | λ₀ (裂解率) |
| （建议） | 地形合成 | 目标海陆比 70:30 | sea_level_m |
| （建议） | 气候模拟 | 目标全球均温 | atmosphere_factor |

**参考**：
- `docs/knowledge/geology/cortial_2019_notes.md` §D.12 — 板块裂解 PID 实现细节
- `src/dreamulator/map/tectonic_simulator.py` — `_evolve_cortial2019()` 中的 PID 控制器
- Matthews et al. (2016) — 地球 410 My 板块数量参考数据

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
- 海岸线偏直（海陆判定在 cell 粒度 ~51 km，见 geological-pipeline.md §3.5）
- 钉扎后不重跑校准：大陆级钉扎（>5% 表面）会偏离 `land_fraction_target`，需自调
- `sea_level_offset_m ≠ 0` 时前端色标仍按 0 m（实验旋钮定位）

**参考**：
- `docs/design/geological-pipeline.md` §3.5 — 地理锚定算法与注入点
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
- `src/dreamulator/engine/physical_inputs.py::build_system_catalog` — `system_catalog.yaml` 的生产者
- `docs/design/roadmap.md` #22 — 世界参数单一来源（两阶段）背景
- `data/worlds/nacrea/layers/astronomy/input/orbital_dynamics.md` — nacrea 模板化实例

---

*模式将持续从代码库中提取和补充。每个模式的 "参考" 给出了源码位置以便查阅。*
