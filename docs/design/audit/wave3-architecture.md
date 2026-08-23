# 审计第三波：架构审计（Phase 3B 启动前）

> 日期：2026-08-20 · 目的：3B 流水侵蚀将引入 `surface_evolution_steps` +
> `climate_coupling` + 地貌降水代理，是对 DAG 与四层控制模型的结构性改动。
> 按 audit-plan 第三波判据，在加新结构前审四个条目：DAG 边界、manifest/可复现性、
> 分支继承逻辑、四层控制模型落地差距。
>
> 结论：**proxy 默认耦合不破坏 DAG，可以开工**；发现两处需在实施时规避的
> 结构性坑（`full` 耦合单趟不可行、地质分叉分支会静默丢失 geography.yaml）。

---

## 一、结论速览

1. **DAG 单向、无环**，侵蚀落在地质层内部不改变任何层间边。地质层已把权威高程
   写进 `maps/{planet_id}/cvt_mesh.json`，气候层经 `_load_cvt_mesh_from_geological`
   读回——侵蚀改的是地质层内部高程，改完自动流入气候/生态/文明，**零 DAG 改动**。
2. **`climate_coupling: full` 单趟构建不可行**：地质层排在气候层之前
   （`LAYER_DEPENDENCIES`），地质运行时尚无本趟气候输出。`full` 只能是接口占位，
   落地需二趟迭代耦合或读上一轮陈旧气候。**proxy 默认值不受影响。**
3. **`ComputationManifest` 是缓存指纹存根，非完整溯源清单**：`StepRecord` 只记
   `{"fingerprint": …}`，`output_files`/`parameters` 为空，`reproducible` 字段
   从未被校验。可复现性实际靠「种子 RNG + 确定性算法 + config 指纹」。侵蚀循环
   只要不用未种子 RNG 即满足。
4. **`TerrainCache` 未覆盖 erosion/rivers 阶段**：`CacheConfig.stages` 默认止于
   `terrain`，`_config_fingerprint` 的 `stage_fields` 也无侵蚀字段。**已定：首版
   erosion/rivers 不缓存，后续再扩展 `TerrainCache`**（扩展前若直接加会静默跳过
   侵蚀，属隐性 bug）。
5. **地质分叉分支会覆盖本层全部内容（预期语义，非缺陷）**：`resolve_layer` 只要
   分支地质 input 非空就整体遮蔽根世界同层，`find_input` 不逐文件回退父层。因此
   地质分叉分支必须携带 `geography.yaml`（及 `planets.yaml`/`geography_raster.png`），
   否则大陆退化为随机分布。**处置：文档化，不改代码。** 详见 §四。
6. **四层控制模型只落地了「引擎层 + 部分约束层」**：约束=geography.yaml（仅地质）、
   校验=文件存在性（`validate_inputs`）、覆写=`edits.json` 未实现。侵蚀新参数
   落 terrain_config.yaml（引擎层配置）是**正确放置**，但缺「校验层侵蚀不变量」
   与「约束层区域侵蚀强度」两条，前者应在 M3 补测试，后者属 v1 范围外。

---

## 二、DAG 边界

### 2.1 层间依赖现状（无环，单向）

- `LAYER_ORDER` / `LAYER_DEPENDENCIES`：`src/dreamulator/models/layers.py:30-61`
  —— geological 依赖 astronomy；climate 依赖 astronomy+geological；ecology 依赖
  climate+geological；civilization 依赖 ecology+climate+geological。
- 各引擎 `requires` 与之一致：
  - `geological.py:36` `requires=["astronomy"]`
  - `climate.py:48` `requires=["astronomy","geological"]`（注释："geological data
    is loaded via maps, not DAG"）
  - `ecology.py:43` `requires=["climate","geological"]`
  - `civilization.py:55` `requires=["ecology","climate","geological"]`
- `pipeline.topological_sort`（`pipeline.py:23-58`）只按 `requires` 排序，无环检测
  靠 DFS 三色标记；当前 `requires` 无环。

### 2.2 高程数据流：侵蚀自动流入下游

地质层把权威高程写进 `maps/{planet_id}/cvt_mesh.json`（`geological.py:41-46` 的
`output_files`），气候层经 `_load_cvt_mesh_from_geological`（`climate.py:282-312`）
从 `maps/` 目录读回（优先 `maps/`，回退旧 layer 目录）。**侵蚀发生在 `synthesize_terrain`
之后、`export` 之前（terrain-pipeline §10.1），改的是地质层内部高程，改完照常写入
cvt_mesh.json → 气候/生态/文明自动拿到侵蚀后高程，无需任何 DAG 变更。**

### 2.3 环依赖风险点

`find_input`（`base.py:81-115`）的搜索顺序是「本层优先 → 反向 LAYER_ORDER
（civilization→physics）」，因此地质层**技术上能**够到 climate 的 derived 目录。
但当前地质引擎只读 `planets.yaml`/`stellar*.yaml`（经 `physical_inputs`）+
`terrain_config.yaml` + `geography.yaml`，不读 climate。

**约束（实施时强制）**：地貌降水代理必须是纯函数 `(地形, 纬度, 行星参数) → P`，
**不得调用 `find_input` 取任何 climate 层文件**。`climate_coupling: full` 留接口位
即可，不在首版实现——理由见 2.4。

### 2.4 `full` 耦合的不可行性（记录为接口位，非缺陷）

地质层排在气候层前（`LAYER_DEPENDENCIES`，`layers.py:57-58`）。单趟 build 中
地质运行时本趟 climate 尚未产出，`full` 读不到。可选落地路径（均为后续工作）：
(a) 二趟迭代耦合（地质→气候→用真实降水重跑地质，收敛判据）；(b) 读上一轮陈旧
气候输出（破坏可复现性，不推荐）。**首版 proxy 默认值不受此影响。**

---

## 三、manifest / 可复现性

### 3.1 `ComputationManifest` 接入现状

`ComputationManifest`（`simulation.py:40-51`）含 `input_checksum`、`steps`、
`reproducible`；`StepRecord`（`simulation.py:23-37`）声明 `input_files`/`output_files`
为「路径→sha256」映射。但唯一使用点在 `terrain_cache.py`，且写入的是**存根**：

```python
StepRecord(engine=stage,
           input_files={"fingerprint": fingerprint},  # 不是文件 sha256
           output_files={},                           # 空
           parameters={},                             # 空
           ...)
```

（`terrain_cache.py:180-192`）。`reproducible` 字段默认 `True`，从未被计算或校验。

### 3.2 真正的可复现性依赖链

build 跳过/脏判定走 `_is_dirty`（`pipeline.py:295-309`）——**mtime 比较，非内容 hash**
（roadmap 技术债 #4 已记录：mtime 优先、`ComputationManifest` 内容 hash 升级"后续"）。
当前可复现性由三层保证：

1. 种子 RNG：`create_rng(seed)`（`base.py:70`）→ `numpy.random.Generator`；
2. 确定性算法（CVT/板块/地形/气候均为种子化纯函数）；
3. config 指纹：`_config_fingerprint`（`terrain_cache.py:50-105`）按 stage 子集
   字段序列化哈希，用于 per-stage 缓存失效。

### 3.3 对侵蚀的实施约束

- 侵蚀循环 + 地貌降水代理**必须是纯函数**：不得调 `engine.rng`、不得用未种子的
  `np.random.default_rng()` / `np.random.*` 全局。Smith & Barstad (2004) 傅里叶域
  求解是确定性算符，天然满足；若代理场引入任何随机扰动，必须从 config.seed 派生。
- `TerrainCache` 当前 `CacheConfig.stages` 默认 `["mesh","plates","tectonics",
  "boundaries","terrain"]`（`terrain_cache.py:210-211`），`stage_fields` 无
  erosion/rivers 字段。**M2 落地时须决定**：扩展缓存（加 `erosion`/`rivers` 的
  stage_fields 到 `_config_fingerprint` 与 `_stage_dependencies`），或首版不缓存
  （侵蚀每次全算，代价是 surface_evolution_steps>0 时重跑）。不扩展直接加会静默
  用旧地形缓存 + 跳过侵蚀，属隐性 bug，必须记录。

---

## 四、分支继承逻辑

### 4.1 继承机制现状

- `LayerResolver.resolve_layer`（`resolver.py:161-183`）：从当前分支向根世界走链，
  返回**第一个** `input_dir` 非空（`any(input_dir.iterdir())`）的层级。
- `find_input`（`base.py:95-115`）只在**已解析出的** `layer_input_dirs` 里搜，
  且该 dict 是按 layer 名扁平化的（`pipeline.py:118-122`）：一旦 `resolve_layer`
  把某层的 input 指向分支，根世界同层目录就不在搜索范围内。
- `load_layer_yaml` 的 `_inherit: true` 深合并（`resolver.py:259-320`）存在，但
  **地质引擎不用它**——地质引擎直接 `find_input("terrain_config.yaml")` /
  `load_geography_spec(find_input("geography.yaml"))`（`geological.py:225`、`:253`），
  取到的是链上第一个文件，无合并语义。

### 4.2 语义澄清：地质分叉 = 整层覆盖（预期行为）

组合上述两点：若一个在地质层分叉的分支只放了 `terrain_config.yaml`（例如为开启
侵蚀改 `surface_evolution_steps`），则：

1. `resolve_layer(geological)` 返回分支的 `geological/input`（非空）；
2. `find_input("geography.yaml")` 在分支地质目录找不到，也不会回退根世界地质目录；
3. `load_geography_spec(None)` → `None` → **大陆退化为随机分布**（无报错、无警告）。

**这是预期语义，不是缺陷**：在某层分叉，意味着该层内容从此完全由分支拥有
（CLAUDE.md 分支系统：「分支仅存储分叉层及之后的数据，之前的层从父世界继承」——
分叉层本身即被整体覆写）。作者若想保留根世界的大陆，必须在分支里一并携带
`geography.yaml`（及 `planets.yaml` / `geography_raster.png`）。

**实证**：`data/worlds/earth/branches/terrain-dev/layers/geological/input/` 现含
`{planets.yaml, terrain_config.yaml}` 两个文件、无 `geography.yaml`——earth 本身
不用 geography.yaml 故无影响；但 gaia-m 用 geography.yaml
（`private/worlds/gaia-m/layers/geological/input/geography.yaml` 存在），未来为
gaia-m 建地质分叉分支调侵蚀时须记得携带。

### 4.3 处置：文档化（已定，2026-08-20）

不改代码。在地图/分支工作流文档写清「地质分叉分支必须携带 `geography.yaml`
（及 `planets.yaml` / `geography_raster.png`）」——见
[geological-pipeline.md](../pipelines/geological-pipeline.md) §3.5 末尾的 caveat。

---

## 五、四层控制模型落地差距

layer-control-model.md 定义四层（覆写/约束/引擎/校验）。落地现状：

| 层 | 纸面 | 已实现 | 差距 |
|----|------|--------|------|
| 约束层 | 语义化命名控制（Hard/Soft/Preference） | `geography.yaml`（仅地质层；无分级 schema） | 其余层无约束载体；无分级 |
| 引擎层 | 物理/数学推演 | 完整 DAG pipeline | ✅ |
| 校验层 | 一致性/守恒/警告拒绝 | `validate_inputs`（`base.py:117-127`，仅文件存在）；地质 20% 分歧警告（`geological.py:265-277`）、`check_body_field_consistency` | 无 `conflict_resolution.yaml`、无物理不变量套件（audit-plan 第二波 `test_invariants.py` 未建） |
| 覆写层 | 逐 cell 强制（seed 绑定） | **`edits.json` 未实现**（roadmap P2） | 完全缺失 |

### 对侵蚀的放置结论

侵蚀新参数（`surface_evolution_steps` / `climate_coupling` / `fluvial_erodibility` /
`stream_power_m/n` / `hillslope_diffusivity` / `precip_proxy_base_mm`）落
`terrain_config.yaml` = **引擎层配置**，放置正确（它们是引擎旋钮，不是语义约束
也不是逐 cell 覆写）。

两条差距需处理：

1. **校验层侵蚀不变量（M3 内补，非独立校验层）**：无 NaN、侵蚀后高程有界、
   陆地河流连通（每陆 cell 汇入海洋或内流盆出口）、均陆高下降方向。作为 M3 的
   验证测试/诊断脚本，不必等到完整 `conflict_resolution.yaml`。
2. **约束层「区域侵蚀强度」**：用户可能想表达「此区域强烈侵蚀/夷平」（语义约束）。
   首版范围外（需 geography.yaml feature 扩展），登记为后续，不在 v1 实现。

---

## 六、对 3B 实施的具体约束清单

1. **纯函数**：侵蚀循环 + 降水代理不得用未种子 RNG（§3.3）。
2. **DAG 安全**：代理不 `find_input` 任何 climate 层文件；`full` 仅接口位（§2.3）。
3. **缓存**：首版 erosion/rivers 不缓存；后续扩展 `TerrainCache`（`stage_fields`
   与 `_stage_dependencies` 加 erosion/rivers）后再启用，避免静默跳过（§3.3）。
4. **分支语义**：地质分叉 = 整层覆盖（预期），文档化「地质分叉分支须携带
   `geography.yaml` / `planets.yaml` / `geography_raster.png`」，不改代码（§4）。
5. **配置放置**：新键进 `terrain_config.yaml`（引擎层），不引入新的约束/覆写载体（§5）。
6. **校验不变量**：M3 补侵蚀不变量测试（§5）。
7. **诊断字段**：`net_erosion_m` 仅诊断（无真实沉积搬运，v1）。

---

## 出处

- `src/dreamulator/models/layers.py:30-61` — LAYER_ORDER / LAYER_DEPENDENCIES
- `src/dreamulator/engine/geological.py:36,41-46,225,253,265-277` — requires / output / find_input / 20% 分歧警告
- `src/dreamulator/engine/climate.py:48,282-312` — requires("via maps") / mesh 加载
- `src/dreamulator/engine/ecology.py:43`、`engine/civilization.py:55` — requires
- `src/dreamulator/engine/base.py:70,81-115,117-127` — create_rng / find_input / validate_inputs
- `src/dreamulator/engine/pipeline.py:23-58,118-122,295-309` — topo sort / layer dirs / _is_dirty
- `src/dreamulator/models/simulation.py:23-51` — StepRecord / ComputationManifest
- `src/dreamulator/map/terrain_cache.py:50-105,180-192,210-211` — config 指纹 / manifest 存根 / stages
- `src/dreamulator/resolver.py:161-183,259-320` — resolve_layer / _inherit 合并
- `docs/design/layer-control-model.md` — 四层控制模型（纸面）
- `data/worlds/earth/branches/terrain-dev/layers/geological/input/` — 分支遮蔽实证
- `private/worlds/gaia-m/layers/geological/input/geography.yaml` — gaia-m 用 geography.yaml 实证
