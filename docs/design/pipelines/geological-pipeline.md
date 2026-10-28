# 行星地形生成管线技术参考

> 本文档描述 dreamulator 地质层生成管线的当前实现：模块与调用方（§1）、执行顺序
> （§2）、各相位细节（§3-§10）、数据模型与性能（§11-§12）、已知限制与未实现设计
> 余量（§13）。对应源码：`src/dreamulator/map/` 与 `src/dreamulator/engine/geological.py`。
> **球面质心 Voronoi 镶嵌（CVT Mesh）是一等公民数据，等距圆柱投影高度图是派生导出产物**：
> 全部模拟（构造、地形、湖泊标记、气候）在 CVT 不规则网格上完成，仅在最终导出阶段投影为栅格。
> 使用向操作指南见 [map-workflow.md](../../usage/map-workflow.md)；气候相位细节见
> [climate-pipeline.md](climate-pipeline.md)；引擎总目录见
> [world-generation-pipeline.md](world-generation-pipeline.md)。

## 目录

1. [架构总览](#1-架构总览)
2. [执行顺序](#2-执行顺序)
3. [CVT 网格生成](#3-cvt-网格生成)
4. [构造板块剖分](#4-构造板块剖分)
5. [构造时间演化](#5-构造时间演化)
6. [边界检测与分类](#6-边界检测与分类)
7. [地形合成](#7-地形合成)
8. [海平面与水系统](#8-海平面与水系统)
9. [封闭盆地湖泊](#9-封闭盆地湖泊)
10. [导出与可视化](#10-导出与可视化)
11. [数据模型](#11-数据模型)
12. [性能](#12-性能)
13. [已知限制与未实现设计余量](#13-已知限制与未实现设计余量)
- [附录 A: 数学公式参考](#附录-a-数学公式参考)
- [附录 D: 论文解读 - Cortial et al. 2019](#附录-d-论文解读--cortial-et-al-2019-procedural-tectonic-planets)


---

## 1. 架构总览

**模块清单**（`src/dreamulator/map/`，本管线直接涉及；气候/生态见各自文档）：

- `cvt_mesh.py` - Fibonacci 球面螺旋 + Lloyd 松弛 + SphericalVoronoi 构建（§3）
- `plate_generator.py` - Poisson-disc 种子选取 + Cortial 2019 加权 Voronoi 剖分 + 地壳类型分配 + 欧拉极（§4）
- `geography.py` - geography.yaml 地理锚定：陆地偏置场 / 全局阈值 / 高程钉扎 / 密集偏置导入（§4.4）
- `tectonic_simulator.py` - 构造时间演化：质心旋转 / 俯冲 / 碰撞 / 裂解 / 海沟弧（§5）
- `boundary_detector.py` - 边界检测、分类与链追踪（§6）
- `terrain_synthesizer.py` - 地形合成：双峰基底 + 边界效应 + fBm + 后处理（§7）
- `water_bodies.py` - 海陆分类（连通性洪泛）与大内流湖升级（§8）
- `hydrology.py` - 优先洪泛填洼（供地形合成的沉积填充使用）与封闭盆地湖泊标记（§9）
- `ice_sheets.py` - 极地冰盖追加相位：日照门 + 海陆分域 + 完美塑性穹丘（§8）
- `terrain_cache.py` - 子阶段内容指纹缓存，增量重建（§2）
- `export.py` - 等距圆柱栅格导出 + 图层导出（§10）
- `importer.py` / `elevation_codec.py` - 外部高度图导入与 16-bit PNG 编解码（§10）
- `models.py` / `pipeline_types.py` / `manager.py` - 数据模型、管线配置、地图 CRUD + 分支继承 + 图层注册表（§11）

**调用方**：

| 调用方 | 入口 | 场景 |
|--------|------|------|
| 地质引擎 | `GeologicalEngine` 调 `run_terrain_pipeline`（`terrain_pipeline.py:189`） | `dreamulator build` DAG 主路径 |
| 气候引擎 | 相位 6/8 内嵌 `simulate_climate`（`GeologicalEngine` 的默认阶段列表不含此相位）；`ClimateEngine` 独立重建 | [climate-pipeline.md](climate-pipeline.md) §10 |
| 生态 / 文明引擎 | 读 mesh 上的气候/生态字段 | [world-generation-pipeline.md](world-generation-pipeline.md) |
| 地图 API / 前端 | `api_routes/maps.py` 与前端查看器消费导出产物 | [map-system.md](map-system.md) |

### 核心理念

**CVT 网格 = 行星表面的离散表示**。所有物理模拟、属性存储、空间查询都在这个不规则图上进行。
等距圆柱投影（equirectangular）高度图仅在以下场景生成：

- 前端 2D 地图可视化（Three.js / Canvas 渲染）
- 导出给 Gaea 进行局部精细化
- 与外部 GIS 工具互操作

### 关键架构决策

- **CVT 而非 HEALPix**: CVT 可以自然表示不规则边界（板块、海岸），HEALPix 的固定层次结构
  不适合线性特征的追踪。但 CVT 的代价是邻接关系需要显式存储。
- **fBm 在 3D 球面采样**: 避免 2D 投影的极点噪声畸变。每个 CVT 节点的噪声值由其 3D 坐标
  `(x, y, z)` 直接索引 Simplex noise。
- **板块 Cortial 2019 Voronoi 剖分**: 加权 Voronoi 重分区（替代早期洪水填充），
  产生自然的不规则板块边界（参考真实地球板块的非凸性）。
- **欧拉极运动学**: 板块运动使用刚体旋转（`v = ω × P`），确保球面上的运动自洽性。
- **河谷雕刻归 Gaea**: 51 km 网格上流水侵蚀只会产生单 cell 宽人工沟壑，故地质层不做
  流水侵蚀；河谷雕刻归管线最后一步的 Gaea 局地高清精修（米级）。


---

## 2. 执行顺序

`run_terrain_pipeline(config, output_dir, stages, ...)`（`terrain_pipeline.py:189`）按固定
顺序执行 8 个相位（`_STAGE_NAMES` :69-78，控制台 `1/8`-`8/8`）；`stages` 参数可选子集，
`_resolve_stages`（:116）校验阶段名称，并按管线顺序执行选定阶段；调用方提供其前置状态。行号锚为 `terrain_pipeline.py` 当前值，
细节章节在 §3-§10 展开。

| 相位 | 名称 | 行号 | 调用 | 产出 → 下游 |
|------|------|------|------|------------|
| 1/8 | mesh | `:235` | `generate_cvt_mesh`；geography 栅格偏置采样 | `CVTMesh` → 全部后续相位 |
| 2/8 | plates | `:280` | `generate_plates`（种子 / 剖分 / 地壳 / 欧拉极 / 地理锚定，§4） | `plate_id` / `crust_type` → 3、4 |
| 3/8 | tectonics | `:325` | `run_tectonic_evolution`（§5）+ `apply_geography_crust` 重锚定 | 演化后 plates 与累积构造量 → 4、5 |
| 4/8 | boundaries | `:424` | `detect_boundaries`（§6） | `boundary_type` → 5 |
| 5/8 | terrain | `:465` | `synthesize_terrain`（§7）；`compute_land_mask` → `water_class` 写入 | `elevation` / 海陆掩膜 → 6-8 |
| 6/8 | climate | `:615` | `simulate_climate`；`GeologicalEngine` 的默认阶段列表跳过此相位，因为气候引擎才是气候字段的权威来源（细节见 [climate-pipeline.md](climate-pipeline.md) §10） | 温度 / 降水 / Köppen / 风 / 洋流 |
| 7/8 | ice | `:638` | `apply_polar_ice_sheets`（§8 极地冰盖：日照门 + 海陆分域 + Vialov 穹丘） | `ice_thickness_m` / 冰面 `elevation` → 8 |
| 8/8 | export | `:650` | `upgrade_large_endorheic_lakes` → `export_equirectangular` + `save_outputs`（§10） | 栅格 PNG + plates.json + cvt_mesh.msgpack.gz |

海陆分类在 5/8 末尾写入。气候相位之后、冰盖之前，管线调用 `mark_closed_basin_lakes`
（`terrain_pipeline.py:634`）把与全球海洋不连通的低于海平面盆地标记为湖泊（§9）。
极地冰盖在 7/8 追加到陆地上，大内流湖升级在 8/8 开头执行。因此「海平面与水系统」（§8）
横跨多个相位，该章开头有说明。

**增量缓存**（`terrain_cache.py`）：每个相位的输入做内容指纹（config 字段 + 相位
schema 版本 + 上游相位指纹 + geography 哈希，`build_stage_fingerprint`），指纹命中则
整相位跳过——改 geography.yaml 只失效受影响的相位，不需要 `--force`（`--force` 仅用于
强制全量重建）。

**固定构造状态续算**：`run_terrain_pipeline(..., tectonic_state=...)` 接受明确选定的
地形处理前网格、板块、边界及历史契约，复制状态后执行显式指定的下游阶段。
入口核对格子数、编号顺序、板块归属及球面面积对应的半径，来源状态的内容哈希进入地形指纹。
调用方保存原状态及其文件哈希、配置和代码版本；续算采用关闭阶段缓存的独立目录。
若提供历史契约，地形与后续导出共同消费该契约；采用范围变化时另行建立并核验来源。
这种续算保留已选定的构造格局，地形重算的海陆与高程变化仍需独立检查。

**缓存负载必须覆盖相位的全部 in-place cell 副作用**（2026-09-17 nacrea 图层丢失教训）：
凡「计算过程直接改 `mesh.cells[*]` 字段」的相位，缓存负载要一并保存这些字段数组、
命中时回放到 cells——否则全缓存命中的重建会导出空字段（inf 距离→null、缺失→None），
前端图层静默消失。当前覆盖：tectonics → `cumulative_convergence_km`/
`cumulative_divergence_km`；boundaries → `distance_to_boundary_km`/
`convergence_rate_cm_yr`/`tangential_fraction`；terrain → `elevation`/`crust_type`/
`boundary_type`/`landform`/`hotspot_id`。**新增 in-place 字段时**：加入
`terrain_pipeline.py` 的阶段负载 + 回放，并提升 `terrain_cache._STAGE_SCHEMA_VERSIONS`
中该相位的版本号（旧 pickle 自动失效）。回归守卫 =
`tests/test_map/test_cell_field_cache_replay.py`（新鲜运行 vs 全缓存回放逐字段全等）。
地形阶段从格子字段现算的量（如历史契约）不得依赖进程级状态：Python 的字符串哈希按进程随机化，遍历字符串
集合的顺序因此每次运行不同，按出现次数取众数时平局必须按编号决断（`orogen_contract.contact_polarity`），
`test_orogen_contract.py::test_contract_independent_of_hash_seed` 在三个哈希种子下比较契约。

**ice 相位不缓存**：极地冰盖是幂等的追加后处理（先从 `elevation − ice_thickness_m`
加回冰载荷下沉量重建无冰基岩再重算，`ice_sheets.py`），秒级完成，每次重建从头执行，也不进入
`_STAGE_SCHEMA_VERSIONS`。


---

## 3. CVT 网格生成

### 3.1 Fibonacci 球面螺旋

初始点集使用 Fibonacci 螺旋（又称 "sunflower pattern"），在球面上产生近乎均匀分布的点集。

**公式**：

```
φ_k = arccos(1 - 2(k + 0.5) / N)        # 极角（余纬度），k = 0, 1, ..., N-1
θ_k = 2π · k / Φ                           # 方位角，Φ = (1+√5)/2 ≈ 1.6180339887
```

其中 `φ` 是从北极量起的极角，`θ` 是经度。

**伪代码**：

```python
def fibonacci_lattice(N: int, radius: float = 1.0) -> np.ndarray:
    """Generate N points on the unit sphere using Fibonacci spiral.

    Returns:
        (N, 3) array of Cartesian coordinates.
    """
    golden_ratio = (1 + sqrt(5)) / 2
    indices = arange(N)

    # Polar angle: arccos evenly spaced in [-1, 1]
    phi = arccos(1 - 2 * (indices + 0.5) / N)

    # Azimuthal angle: golden-angle increments
    theta = 2 * pi * indices / golden_ratio

    # Convert to Cartesian
    x = sin(phi) * cos(theta)
    y = cos(phi)          # y = up (north pole)
    z = sin(phi) * sin(theta)

    return radius * stack([x, y, z], axis=-1)
```

**优点**：
- 确定性（无需 RNG），O(N) 生成
- 面积近似均匀：每个点占据约 `4π/N` 球面度
- 无极点聚集（与随机均匀采样不同）

### 3.2 可选随机扰动

纯 Fibonacci 格点过于规则，会在噪声频谱中产生伪峰。添加高斯扰动破坏规则性：

```python
def jitter_points(points: np.ndarray, sigma: float, rng) -> np.ndarray:
    """Add isotropic Gaussian jitter, then re-project onto sphere."""
    noise = rng.standard_normal(points.shape) * sigma
    perturbed = points + noise
    # Re-project onto unit sphere
    norms = linalg.norm(perturbed, axis=1, keepdims=True)
    return perturbed / norms
```

**扰动强度**：`σ ≈ 0.3 × d_mean`，其中 `d_mean ≈ √(4π/N)` 是平均点间距。

| σ/d_mean | 效果 |
|-----------|------|
| 0.0 | 完美均匀（伪峰） |
| 0.1 | 轻微不规则（推荐用于高分辨率） |
| 0.3 | 自然随机（默认推荐） |
| 0.5+ | 过度聚集，部分区域出现空洞 |

### 3.3 Lloyd 松弛

Lloyd 松弛（Lloyd's algorithm）迭代地将每个点移动到其 Voronoi cell 的质心，从而获得
**质心 Voronoi 镶嵌（CVT）**。在球面上，质心需要投影回球面。

**算法**：

```python
def lloyd_relax_spherical(points: np.ndarray, iterations: int, radius: float = 1.0):
    """Lloyd relaxation on the unit sphere."""
    for _ in range(iterations):
        # Build SphericalVoronoi
        sv = SphericalVoronoi(points, radius=radius, center=zeros(3))

        for i, region in enumerate(sv.regions):
            if not region or region[0] == -1:
                continue
            # Compute centroid of Voronoi cell vertices
            vertices = sv.vertices[region]
            centroid = vertices.mean(axis=0)
            # Project centroid back to sphere
            centroid /= linalg.norm(centroid)
            points[i] = centroid * radius

    return points
```

**默认迭代次数**: 5-10 次。超过 10 次收益递减（CVT 已充分收敛）。
实际收敛判据：所有点的位移量 < 阈值（`1e-4 × d_mean`）。

### 3.4 SphericalVoronoi 构建

使用 `scipy.spatial.SphericalVoronoi` 计算球面 Voronoi 图，然后构建邻接图。

```python
def build_cvt_mesh(points: np.ndarray, radius: float = 1.0) -> CVTMesh:
    """Build CVT mesh from point set.

    Steps:
        1. Compute SphericalVoronoi
        2. Build cell adjacency (shared edges)
        3. Compute dual edge midpoints
        4. Compute cell areas (spherical polygon area)

    Returns:
        CVTMesh with nodes, adjacency, dual edges, cell areas.
    """
    sv = SphericalVoronoi(points, radius=radius, center=zeros(3))
    sv.sort_vertices_of_regions()

    # Build adjacency from shared Voronoi edges
    adjacency: dict[int, list[int]] = defaultdict(list)
    edge_to_cells: dict[tuple[int,int], list[int]] = defaultdict(list)

    for cell_idx, region in enumerate(sv.regions):
        if not region or region[0] == -1:
            continue
        n_verts = len(region)
        for j in range(n_verts):
            v1, v2 = region[j], region[(j + 1) % n_verts]
            edge_key = (min(v1, v2), max(v1, v2))
            edge_to_cells[edge_key].append(cell_idx)

    for edge_key, cells in edge_to_cells.items():
        if len(cells) == 2:
            adjacency[cells[0]].append(cells[1])
            adjacency[cells[1]].append(cells[0])

    # Compute cell areas via spherical excess
    areas = compute_spherical_polygon_areas(sv)

    # Compute dual edge info (midpoints, lengths)
    dual_edges = compute_dual_edges(sv, adjacency)

    return CVTMesh(
        nodes=points,               # (N, 3) Cartesian
        adjacency=adjacency,        # graph adjacency
        areas=areas,                # (N,) cell areas in steradians
        dual_edges=dual_edges,      # edge metadata
        sv=sv,                      # underlying SphericalVoronoi
    )
```

**球面多边形面积**使用球面角盈公式（spherical excess）：

```
A = Σᵢ αᵢ - (n - 2)π
```

其中 `αᵢ` 是多边形第 i 个顶点的内角，n 是顶点数。

### 3.5 分辨率与性能

| 节点数 N | 平均间距 d_mean | 等效栅格分辨率 | 内存 (CVTMesh) | Lloyd 松弛时间 |
|----------|----------------|---------------|----------------|---------------|
| 10K | ~226 km | ~512×256 | ~10 MB | ~0.5s |
| 50K | ~101 km | ~1024×512 | ~45 MB | ~3s |
| 100K | ~71 km | ~2048×1024 | ~85 MB | ~8s |
| 200K | ~51 km | ~4096×2048 | ~220 MB | ~20s |
| 500K | ~32 km | ~6144×3072 | ~400 MB | ~50s |
| 1M | ~23 km | ~8192×4096 | ~800 MB | ~120s |

> `d_mean ≈ radius × √(4π/N)`，对于 `R = 6371 km`。

### 参数表

| 参数 | 默认值 | 范围 | 物理含义 |
|------|--------|------|----------|
| `num_nodes` | 100,000 | 10K – 1M | CVT 节点数（分辨率；nacrea 主力用 200,000） |
| `jitter_sigma` | 0.3 | 0.0 – 0.5 | 随机扰动强度（× d_mean） |
| `lloyd_iterations` | 8 | 0 – 20 | Lloyd 松弛迭代次数 |
| `seed` | (world seed) | 任意 int | RNG 种子 |
| `radius_km` | 6371.0 | 100 – 100,000 | 行星半径 |


---

## 4. 构造板块剖分

### 4.1 种子选取

在 CVT 网格上选取 ~20 个种子节点作为板块核心（`select_plate_seeds`，
`plate_generator.py:57`）：**变密度 Poisson-disc 采样**——每个候选种子抽取一个
log-uniform 尺度因子（~0.45–2.2）缩放自己的最小间距（基础间距 = 平均间距的
~0.3×），间距不足的候选被拒绝。大因子种子把邻居推远 → 大板块；小因子允许密集
堆叠 → 小板块。这样得到的板块大小分布**右偏**（少数大板块 + 一批小板块），接近
地球的幂律板块大小分布，优于均匀 Poisson-disc 的近等尺寸。

> **参考 Cortial 2019 §3**: 论文使用球面 Voronoi cell 作为板块，通过向测地距离
> 添加噪声来产生不规则的板块形状（`geodetic distance + noise warp`）。我们的
> Cortial 2019 Voronoi 剖分（§4.2）实现了类似的不规则性，且更容易控制板块大小分布。

板块种子目前只由该采样自动生成（无手动种子配置）；控制「哪里是陆」的正道是
地理锚定（§4.4 的 geography.yaml / 锚定灰度图）。

### 4.2 球面 Voronoi 剖分（Cortial 2019）

遵循 [Cortial et al. (2019)](https://doi.org/10.1111/cgf.13614) *Procedural Tectonic Planets*
的球面 Voronoi 板块剖分方法。

**算法**：同步多源 BFS。所有种子从各自的 FIFO 队列逐层扩展（每轮每 plate 扩 1 层）。
每个 cell 归属于第一个到达的 wavefront，产生球面 Voronoi 图。Voronoi 区域在图上
天然凸 → 板块永不包围彼此。CVT 网格的不规则拓扑天然提供有机边界。

```python
def _voronoi_partition(
    mesh: CVTMesh,
    seeds: list[int],
) -> dict[int, str]:
    """Spherical Voronoi on the CVT graph — synchronous multi-source BFS."""
    queues = [deque([s]) for s in seeds]
    cell_plate_map = {s: f"plate_{i:03d}" for i, s in enumerate(seeds)}
    total = len(seeds)

    while total < mesh.num_cells:
        for plate_idx, q in enumerate(queues):
            if not q:
                continue
            plate_id = f"plate_{plate_idx:03d}"
            for _ in range(len(q)):           # one layer
                for nid in mesh.cells[q.popleft()].neighbors:
                    if nid not in cell_plate_map:
                        cell_plate_map[nid] = plate_id
                        q.append(nid)
                        total += 1
    return cell_plate_map
```

板面积由 **可变密度 Poisson-disc 种子**与球面 Voronoi 几何共同决定：
`select_plate_seeds` 中每个种子抽取对数均匀 size-factor（e^{U(-0.8, 0.8)}≈0.45–2.2）
缩放其最小间距——大间距种子周围形成大板块、小间距种子挤成小板块，初始剖分
即呈偏态（nacrea 实测 CV≈0.44）。无需额外的目标尺寸（Pareto）或速度参数。

> **偏态的保持（构造重采样）**：构造演化的周期性重分区若是无权重的
> "最近种子" Voronoi，则等价于 Lloyd 迭代——其吸引子是等面积的质心
> Voronoi 剖分（CVT），会把初始偏态洗掉（nacrea 实测 50 步后 CV 0.44→0.22）。
> 因此重采样改用**乘法加权 Voronoi**（power diagram 的图版本）：每个板块
> 持有出生时确定的持久权重 wᵢ（初始板块取初始面积、裂解碎片取碎片面积），
> 波前 i 进入 cell 的代价为 cost/wᵢ，面积比 ∝ 权重比。规定权重后迭代吸引子
> 变为**加权 CVT**（等面积只是 w≡const 的特例），偏态在质心旋转/边界迁移
> 过程中保持。实现见 `plate_generator.py::voronoi_partition_warped`
> （`plate_speed` 参数）与 `tectonic_simulator.py::_evolve_cortial2019`
> （`plate_weight` 字典，随裂解/清理同步）。

### 4.3 地壳类型分配

每个 cell 的地壳类型（大陆/大洋）通过 **5-octave 分形布朗运动（fBm）** 在板块内分配。
这替代了早期设计中按板块整体分配的方法，实现了更真实的大陆形状。

**算法**：

1. 每个板块获得随机大陆比例 f ∈ [0.1, 0.9]
2. 对板块内所有 cell，使用 3D simplex noise（OpenSimplex）在 cell 的球面坐标 (x, y, z) 上采样
3. 5-octave fBm 叠加：`noise = Σ amplitude_k · noise3(x · f_k, y · f_k, z · f_k)`
   - persistence = 0.5（1/f 振幅衰减）
   - lacunarity = 2.5（频率倍增系数）
   - base_freq ∝ 1 / N_cells^0.15（自动适配板块大小）
4. 归一化后施加纬度偏差：`noise -= 0.3 · |lat| / 90°`（赤道偏向大陆）
5. 按 noise 值降序排列，前 f×100% 的 cell 标记为 continental，其余为 oceanic

**分形海岸线原理**：

fBm 具有 1/f 功率谱（Mandelbrot 1967），因此 noise 等值面——即大陆/大洋
边界——在所有可分辨尺度上表现出统计自相似性。随着 CVT 分辨率提高（更多 cell），
海岸线自动呈现更多细节，无需额外参数调整。

> **参考文献**：
> * Mandelbrot, B.B. (1967). "How Long Is the Coast of Britain? Statistical
>   Self-Similarity and Fractional Dimension." *Science*, 156(3775), 636–638.
> * Musgrave, F.K. et al. (1989). "The synthesis and rendering of eroded
>   fractal terrains." *SIGGRAPH '89*.

### 4.4 地理锚定（geography.yaml）

默认的地壳分配（§4.3）是**纯程序化**的——大陆落在哪里完全由纬度偏好 + fBm
噪声决定，作者无法控制。对于"样板世界"（如 nacrea），世界构建者往往已经在
设定文档里写死了海陆格局（哪个大陆在哪、多大的洋），需要让引擎**按设定生成**。

**业界先例**：Gleba 支持"自定义陆块概率图导入"来引导大陆生成；Azgaar 用
heightmap 模板/手绘高度图控制陆地。Dreamulator 的等价物是**机器可读的地理规格
→ 逐 cell 陆地偏置场 → 全局阈值**，实现在 `src/dreamulator/map/geography.py`。

#### 规格文件

`data/worlds/<world>/layers/geological/input/geography.yaml`（可选；缺省时管线
行为与 §4.3 完全一致）。由 `GeologicalEngine._load_config` 经
`load_geography_spec()` 载入并挂到 `config.geography`。

```yaml
version: 1
land_fraction_target: 0.28      # 缺省则用 config.target_land_fraction
hemisphere_land_bias: 0.10      # >0 北半球偏陆（按 sin(lat) 平滑加权）
reapply_after_tectonics: true   # 构造演化后重新锚定（见下）
features:
  - name: 世界岛
    lon: -90.0
    lat: 0.0
    radius_deg: 35.0            # 圆半径；拉长特征 = 半短轴（半宽）
    strength: 0.85              # + 陆地 … − 海洋；|strength|>1 用于"切开"大陆
    elongation: 1.6             # 半长轴/半短轴（≥1，1=圆）
    bearing_deg: 0.0            # 半长轴朝向（0=北，90=东）
    noise_amplitude: 0.8        # 可选：边界粗糙化强度（0=光滑椭圆；见「陆地偏置场」）
    elevation_target_m: -120.0  # 可选：高程钉扎（相对校准海面 0 m；负=水深）
    pin_strength: 1.0           # 可选：钉扎信任度 0–1（核提供空间软边）
```

**`overlays`：地形微调层（2026-09-30）**：feature 列表分两层——`features:` 是主特征
（大陆、裂谷海、海峡），参与板块阶段（板块种子 `select_geography_seeds` / 地壳切分
`apply_geography_crust` / 海岸代价 / 构造后重锚定），编辑它们使 plates/tectonics
阶段缓存指纹失效 → **板块全球重生成**（新洋中脊/海岸——与改动处无关的远端地形剧变），
是"改世界"级操作；`overlays:` 是地形微调层（海岸粗化、群岛噪声、局部刻海/补陆），
只对地形合成可见（`all_features` 全量叠加），不进板块阶段、不进 plates/tectonics
指纹（`GeographySpec.plate_view()` / `plates_fingerprint()`，plates/tectonics 用
plate 视图 hash、terrain 保持全文件 hash）——编辑它们保持板块缓存命中、改动保持局部。
水量校准（`_apply_sea_level_calibration`）对 overlay 覆盖格**盲解**（`overlay_cell_mask`，
~86% 半径无噪声核盘，>40% 覆盖回退全局）：overlay 的增陆/刻海成为局部偏离，不拖动
全球海平面/海岸线；全球陆地比例随 overlay 净贡献漂移（局部编辑语义）。
编写规则平实说明在 `geography.yaml` 文件头部。

**地物形状**：每个 feature 与 overlay 是椭圆（中心、半径、拉长率、朝向）或多边形（`polygon`，[经度, 纬度] 点列，
大圆连边，`geography._polygon_kernel`）。多边形的核函数在轮廓外与轮廓上为 0，进入内部 `edge_deg` 后余弦升到 1；
内外判定在以顶点质心为切点的心射切面投影上用射线法（大圆边在该投影里是直线），距离是到闭合轮廓的角距离。`noise_amplitude` 把带符号距离平移最多
`noise_amplitude · edge_deg`。补丁尺度噪声的特征半径取 `size_deg`（椭圆的半短轴，或多边形质心到顶点的平均距离）。

**overlay 陆壳碎片**：正 overlay 代表陆壳碎片（作者 2026-10-21 裁决，Zealandia 语义）。偏置到海拔是 ±0.5
的双模门（`_apply_base_override`），+850 m 的大陆基准只给陆壳，洋壳格随后被年龄-深度覆写回 −3 到 −5 km，所以
正 overlay 在 terrain 合成开头把它的足迹 restamp 为陆壳（`_restamp_overlay_microcontinents`），这些格保留大陆
基准、跳过年龄-深度、接收全部程序化纹理。足迹是 overlay 核函数 > 0.05 的范围（`_overlay_claims`），半径按补丁
尺度的 fBm（基础波数 4/半径）乘以 1 ± `noise_amplitude`（轮廓起伏幅度，上限 0.9），所以碎片边缘——陆壳与
洋壳的台阶，也就是陆架坡折与外缘海岸——是不规则的，不是名义椭圆；起伏有上限，远处噪声离群点不会声明
单格碎陆。足迹与 strength 无关。负 overlay 不 restamp（刻海走 −0.5 门，陆壳在水下即陆间海）。overlay 与主
特征冲突时 overlay 优先（restamp 在 `_relabel_leaked_crust` 之后）。认识论：近似推导（真实碎片是减薄陆壳）。
控海峡与陆桥高度用 elevation pin。

**overlay 群岛切割（strength = 陆地占比）**：`_apply_overlay_archipelago_texture` 在全部后处理与海平面末次
微调之后、地理钉扎之前，在最终地表上处理每个正 overlay：碎片足迹内，补丁尺度 fBm（单个倍频，基础波数 3/半径，
岛约为半径的三分之一，在 54 km 格子上有数格大）最低 `1 − strength` 分位的格成为海峡，其余保持原高程，补丁内的
陆地占比因此精确等于 strength（0.3–0.6 群岛，1.0 实心碎片，大于 1 按 1）。海峡深度按到最近岛屿的图距离（格心距岸
约半个格距）给出：岛边为岸线深度 3 m，一个被动陆缘陆架宽度（88 km）内加深到 `shelf_break_depth_m`，再经一个陆架
宽度平滑加深到碎片块体之间的盆地深度 1000 m（拉薄陆壳碎片上的盆地与海槽约 0.5–1.5 km，如西兰洲）；fBm 低于切割
水平的程度把距离伸缩 0.5–1.5 倍，海峡中轴比两侧深。碎片外侧一个陆架宽度内、比坡折浅的洋壳格（未切割时绕高台
铺下的陆架，末次微调会让它露出成环）也按同一剖面处理。原本更深的格保持原深度。切割自实际海面量起，后续阶段
不会把海峡抬回水面。校准不看 overlay 足迹，切割成为局部偏差。编写规则平实说明在 `geography.yaml` 文件头部。

**陆壳划分中的洋壳斑点**：陆壳划分取带噪声得分的前 `target_land_fraction` 个格，噪声会在大陆内部留下零星的
洋壳格；它们拿洋壳基准，后续又被抬到海平面附近，成为大陆内部圆形的小洼地与小湖。`compute_geography_land_mask`
切完阈值后由 `_fill_oceanic_specks` 填补：不是世界大洋、不超过 20 格（约 6 万 km²，最小的残留洋盆量级）、且去噪后的
偏置场处处不低于 −0.3（不是作者画的海）的洋壳连通块改为陆壳。更大的封闭洋壳块视为盆地（与外海隔断的裂谷海、
深内陆盆地）保留。划分在板块阶段与构造演化后的重新锚定共用，所以板块、构造演化与地形看到同一份地壳；改动它
会让板块格局整体重新实现（作者 2026-10-21 接受）。

**壳声明与噪声（2026-09-30）**：feature-kernel 噪声把 kernel 实际半径放大到
(1+A)× 半长轴（A=4 → 5×），因此**阈值型壳决策必须吃无噪声场**——overlay 微陆块
restamp（`_restamp_overlay_microcontinents`）的轮廓起伏有 0.9 的上限；
不设上限时远处噪声尖峰会过门变成散碎单格陆（全球群岛杂讯，实测踩坑）。features 的壳
分位数（`compute_geography_land_mask`）仍吃带噪声场：分位数自适应 + 全局排名 +
`_relabel_leaked_crust` 清理，离群效应表现为特征外围的岛链纹理（现状保留；
改无噪声场试过、海岸形态劣化已回滚）。有机海岸线形态同时来自 fBm 分数混合与
terrain 阶段的带噪声场（base override/uplift damping/边界效应），噪声的纹理
使命不变。

#### 陆地偏置场

对每个 cell（单位球面坐标 **p**），把各 feature 的贡献叠加成偏置场
`field ∈ [-1, 1]`（正=陆地、负=海洋）：

1. 计算到 feature 中心 **c** 的大圆距 `d = arccos(p·c)`。
2. **圆/极点特征**：`q = d / radius`。
3. **拉长特征**（裂谷海、地峡）：在中心切平面内把偏移分解为沿半长轴分量
   `along` 与垂直分量 `across`，取椭圆度量
   `q = √((along/a)² + (across/b)²)`（`a = radius·elongation`、`b = radius`）。
   注意：切平面投影在**对跖点**会退化（偏移→0 → q→0，产生假性满强度），
   因此先令 `d > a` 的 cell 直接为 0——这同时排除了对跖点。
4. 核函数为余弦钟形（边缘 C¹ 连续）：`kernel(q) = 0.5(1 + cos(πq))`（q<1），
   否则 0。贡献 = `strength · kernel`。
5. 叠加全部 feature，再加 `hemisphere_land_bias · sin(lat)`，clamp 到 [-1, 1]。

**边界粗糙化**（`noise_amplitude > 0`）：`_feature_kernel` 把归一化距离缩放为
`q / (1 + noise_amplitude·noise)`，其中 `noise` 是逐 cell 的确定性 fBm
（seed 派生自 `config.seed`，octaves=5、lacunarity=2.5、persistence=0.5、
base_freq=15）——有效半径随噪声在 ±`noise_amplitude` 内扰动，椭圆/裂谷边缘变成
分形海岸线而非规整形状（proposal §4）。`noise_amplitude` 上限 3.0，但取值需 < 1
（避免 `1 + noise_amplitude·noise` 触及零除）。

#### 地壳赋值（全局阈值）

有 spec 时，`apply_geography_crust()` 用**全局阈值**替代 §4.3 的"每板块随机
比例"：

```
score = anchor_weight · field + (1 − anchor_weight) · fBm
```

`anchor_weight`（`config.anchor_weight`，默认 0.6）混合锚定场与 fBm 纹理；
fBm 的 seed = `config.seed + 500`（确定性）。按 score 降序取前
`land_fraction_target × N` 个 cell 为 continental，其余 oceanic。这样：

- 命名大陆（正场强）稳定落在锚点；命名大洋（负场）被压到阈值以下。
- fBm 让海岸线保持分形、让弱场区（如前导点褶皱山系）叠加噪声产生复杂地形。
- 目标比例按格数确定全局排序的初始陆壳选取数量。

全局排序选取的是陆壳分配的初始数量。随后 `_fill_oceanic_specks` 填入大陆内部的小洋壳斑块，
`apply_geography_crust` 对非豁免板块按 `crust_plate_floor` 补足陆壳比例；
均值地理偏置低于 −0.3 的板块属于明确大洋，豁免这项下限。补入格按同一评分排序选取。
这两步可以增加陆壳面积，最终出露陆地面积由地形合成及海平面校准确定。
来源诊断分别保存排序掩膜、填充增量和下限增量，并使用 `plate_view()` 核对板块阶段输入。
地壳分配的阈值属于生成规则，评分的连续轮廓描述其几何支持，高程和厚度另按地质模型确定。

#### 注入点与构造漂移

- **plates 阶段**：`_generate_plates_impl` 检测到 `config.geography` 时改走
  `apply_geography_crust`（板块仍照常生成，供 tectonics/boundaries 使用，
  只有地壳被锚定）。
- **tectonics 阶段后**：构造演化只读取地壳数组，不搬运地壳，大陆不会离开锚点
  （roadmap 技术债 34）。若 `reapply_after_tectonics: true`，演化结束后用**同一 seed-确定场**
  重新锚定一次，得到的掩膜与演化前相同，差别只在按板块施加的地壳下限；而 tectonics 产生的边界/造山数据
  （`boundary_type`、`distance_to_boundary_km`、`convergence_rate_cm_yr`）独立存储，
  山脉得以保留。注意：重锚只重盖**地壳类型**（此时刻高程尚不存在）；
  高程锚定统一在地形合成阶段完成（见下）。

#### 汇聚抬升抑制（roadmap #9 修复，2026-08）

锚定只钉地壳的脆弱机制：横穿 authored 裂谷/海盆的汇聚边界会把 +4000 m 级
抬升加在洋壳 cell 上，把裂谷推上海面（nacrea 大裂谷海曾测得 +927 m）。
修复：合成阶段在入口重算偏置场（纯函数，与地壳锚定逐位一致），对**正抬升项**
乘阻尼

```
damp = clip(2·bias + 2, 0.1, 1.0)   （bias < −0.5 时；否则 1.0，阈值处连续）
```

作用于 gaussian/asymmetric 两种边界效应的汇聚分支与岛弧后处理；海沟负项与
离散分支不动。数值核对：裂谷 bias=−1 走 O-O 幅度，抬升 ≤ 0.1×（≈+350 m），
叠最坏基底仍 <0。正常造山带（bias ≥ −0.5）完全无感。

仅有阻尼还不够：top-N 地壳阈值总会向 authored 海洋泄漏少量 continental cell
（nacrea 裂谷核心 ~13%），它们拿 continental 双峰基准 + 板块偏移直接
隆起成高原。因此 |bias| > 0.5 处**双峰基准服从作者**（负侧用 oceanic 基准、
正侧用 continental 基准，`_apply_base_override`），锚定贯通到高程而不仅是
地壳类型——这正是 roadmap #9 的验收要求。

#### 高程钉扎（elevation_target_m）

带 `elevation_target_m` 的 feature 经 `build_elevation_pins()` 生成核加权的
(weight, target, strength) 场；合成阶段在**海平面校准与全部后处理（岛弧/内部
地貌/大陆架/沿海平原）之后**、海陆分类之前施加：

```
elevation += strength · clip(2·weight, 0, 1) · (target − elevation)
```

- 凸组合，不过冲；核在 w≥0.5 的核心饱和（离散网格上作者意图决定性），边缘平滑；
- target 相对**校准海面（间冰期 0 m）**钉住海底/陆地：`sea_level_offset_m = −120`
  时 −80 m 的海峡钉扎出露 → 海峡"冰期关闭"（临界洋流剧情的前提）；
- 无 target 时返回 None，管线逐位不变（默认行为保持）。

#### 密集偏置场导入（geography_raster.png，Gleba 模式，2026-08）

`layers/geological/input/geography_raster.png`（可选；上传端点
`POST /api/worlds/{world}/geography-raster`，或地图页"⬆ 锚定灰度图"按钮）
把整幅灰度图作为**密集陆地偏置场**叠进锚定：灰度 [0,1] 映射到 bias [−1,1]
（中灰=中立），与 feature 场同级叠加后 clip：

```
field = clip(Σ feature 贡献 + hemisphere·sin(lat) + raster_weight · raster_bias)
```

- `raster_weight`（GeographySpec，默认 1.0，0=禁用）调和手绘形状与 feature；
- 导入场与 feature 场**同等待遇**：参与 plates 地壳切分、tectonics 后重锚、
  合成阶段的抬升抑制/基准服从/钉扎（bias 经 `sample_raster_at_cells` 按 cell
  最近像素采样，一次计算三处共用，纯函数确定性不变）；
- 典型用法：手绘大陆轮廓灰度图 → "形状是我的、地貌细节是物理的"混合世界；
  与 feature 叠用（raster 定大形、feature 钉裂谷/地峡高程）；
- 分支友好：raster 存 geological input，分支可替换/继承（resolver 逐层向上搜）。

**格式与采样**（作者向完整规范见 `../usage/map-workflow.md` §10 格式规范）：
等距圆柱、任意分辨率；`sample_raster_at_cells` 按 cell 中心
`lon_lat_to_pixel`（像素中心约定，不 wrap）最近像素采样。解码经
`importer.import_heightmap`：16-bit PNG 全精度、16-bit TIFF、32-bit float TIFF
（越界 min-max 归一）、8-bit PNG（256 级，警告）、多通道取首通道；
灰度 [0,1] → bias = 2v−1。上传端点统一重编码 `encode_elevation(…, 0, 1)`
落 16-bit PNG。仅 `config.geography is not None` 时参与（`geography.yaml`
可零 features）。

#### 海平面偏移旋钮（sea_level_offset_m）

`terrain_config.yaml` 新增 `sea_level_offset_m`（默认 0）。校准（"倒水"）仍按
`target_land_fraction` 求 datum；offset 移动**水面标量**而非地形数组——冰期是水体
移动不是地形移动。大陆架/沿海平原/岛弧 transitional 判定/海陆分类/气候陆海掩膜
（`climate_simulator.py`）均读该值。前端色标仍假设 0 m——定位为实验旋钮。

#### 已知限制

- **海岸线偏直**：海陆判定在 cell 粒度（~51 km @ 200k cells），海岸线沿 cell
  边、过于平直。改进方向：更高 cell 密度 / 海岸带高频噪声扰动 / sub-cell 阈值化。
- **~~浅海深度~~**：已由高程钉扎解决（`shallow_sea` + `elevation_target_m: -120`
  表达陆缘浅海，2026-08）。
- **offset 下游假设**：前端色标按水面 0 m 假设；
  `sea_level_offset_m ≠ 0` 仅用于实验性重建。
- **钉扎与海陆比**：钉扎只动核支撑区，对 `land_fraction_target` 的扰动 ≤
  核面积占比（nacrea 地峡 ≈0.3pp）；大陆级钉扎（>5% 表面）需自行调 target。
  钉扎后不重跑校准（全局平移会放大局部操作且 target 相对水面→迭代不适定）。
- **参数需调优**：feature 的 radius/strength/elongation 是作者旋钮，需按渲染
  结果迭代（如"切开大陆"要求裂谷 `|strength|` 超过下伏大陆 strength）。
- **分支整层覆盖**：在地质层分叉的分支会整体覆写根世界的地质 input，须一并携带
  `geography.yaml`（及 `planets.yaml` / `geography_raster.png`），否则大陆退化为
  随机分布。这是分支系统的预期语义（见
  [audit/wave3-architecture.md](../audit/wave3-architecture.md) §4）。

### 4.5 板块数据模型

板块模型为 `TectonicPlate`（`src/dreamulator/map/models.py`，§11）：`id`、`name`、
`type`（PlateType 枚举）、`cell_ids`（CVT cell ID 列表）、`euler_pole`（欧拉极，
旋转轴单位向量 + `omega_rad_yr` 角速度）、`growth_speed_multiplier`（剖分生长速度
乘数）。板块运动统一用欧拉极表示（v = ω × P）。

### 参数表

| 参数 | 默认值 | 范围 | 物理含义 |
|------|--------|------|----------|
| `num_plates` | 20 | 5 – 50 | 构造板块数量 |
| `plate_speed_mean_cm_yr` | 5.0 | 1–25 | 全部板块的面积加权平均地表速度（世界输入；地球约 5，nacrea 12.5） |
| `continental_fraction` | 0.35 | 0.1 – 0.8 | 大陆板块比例 |


---

### 4.6 欧拉极与板块运动学（plates 相位的组成步骤）

#### 欧拉极分配

每个板块的运动由一个**欧拉极**（Euler pole）描述——球面上的一个旋转轴；
在惯性参考系中板块绕该轴做刚体旋转。

> 运动学公式已上浮至
> [knowledge/geology/plate_tectonics.md](../../knowledge/geology/plate_tectonics.md)
> §欧拉极运动学：角速度换算 ω = v/R 与地球板块速度参考表、速度场
> v(P) = ω·(ê×P) 及其大小 |v| = ωR·sin α、边界相对速度与法向/切向分解、
> 无净旋转（no-net-rotation）参考系。

**实现要点**（`tectonic_simulator.py` / `plate_generator.py`）：

- **欧拉极分配**：默认（`coherent_motion`）按相干速度场最小二乘拟合每个板块的
  旋转轴；关闭时用随机单位旋转轴。潮汐锁定的天体（`tidally_locked`，由
  `physical_inputs.py::resolve_tidal_lock` 按自转周期与绕母体的开普勒周期相差不超过
  5% 推出）把速度场锚定在向星点与背星点的轴上。
- **大陆减速与速度归一**：每个板块的转速乘以大陆减速系数
  `1 − (1 − continental_plate_speed_factor) × 大陆格子占比`
  （`plate_generator.py::continental_slowdown`），然后全部转速按同一比例缩放，使面积
  加权平均地表速度等于 `plate_speed_mean_cm_yr`
  （`plate_generator.py::normalise_plate_speeds`）。板块之间的速度比来自速度场、大陆
  减速与裂解扰动，绝对速度来自世界输入。
- **板块排热检查**：总潮汐热流不决定板块速度。强潮汐加热的世界里大部分内热由热管火山
  带出，板块只排出传导部分（nacrea design-note 0017）。按半空间冷却，洋底平均热流约
  正比于板块速度的平方根，`tidal_physics.py::plate_heat_flux_w_m2` 由平均速度与陆地
  比例给出板块所排热流；超过 `plate_heat_flow_budget_w_m2` 时引擎给出警告。
- **速度场**：向量化叉积一次算出全部节点速度（单位球坐标 → 乘
  `radius_km × 1000` 得 m/yr）。
- **时间演化的 δt 自动缩放**（实现行为，见 §5 与
  `tectonic_simulator.py::_auto_compute_dt`）：
  `δt = 3 · √(4πR²/N) / v_max`——令最快板块每步移动 ~3 个 cell
  （100K cells 时 δt ≈ 2 My；`tectonic_dt_my > 0` 时显式覆盖）。

#### 参数表

| 参数 | 默认值 | 范围 | 物理含义 |
|------|--------|------|----------|
| `plate_speed_mean_cm_yr` | 5.0 | 1–25 | 面积加权平均地表速度（世界输入） |
| `plate_heat_flow_budget_w_m2` | 无 | 0.05–2 | 板块所排热流的上限（当代地表热流）；不设则不检查 |
| `continental_plate_speed_factor` | 0.3 | 0.2–0.5 | 纯大陆板块相对纯大洋板块的速度比（地球非洲约 2 cm/yr、太平洋约 10 cm/yr） |


---

## 5. 构造时间演化

> 时间演化由 `tectonic_simulator.py` 实现（`run_tectonic_evolution`，算法
> `cortial2019`，`tectonic_steps` 控制步数，nacrea 为 50 步）。§5.1–§5.3 描述
> **当前实现**；威尔逊循环未实现部分与随时间变化的行星物理参数在 §13
> 「未实现设计余量」。核心参考：Cortial et al. 2019（见[附录 D](#附录-d-论文解读--cortial-et-al-2019-procedural-tectonic-planets)）。

**现状管线是「指定现状」模式（作者裁决 2026-10-20）**：有 geography.yaml 时，地壳类型由作者的海陆锚点决定，
演化期间板块边界被海岸吸附成本钉在大陆边缘，演化结束后按锚点重新锚定；构造演化只负责生成现状的板块边界、累积
汇聚与伸展量和造山带，**不搬运地壳**，这是设计而非缺陷。大陆漂移由地质时间轴（地壳质点运动学，
[geological-timeline.md](../proposals/geological-timeline.md)）和新世界的演化模式
（[evolution-mode.md](../proposals/evolution-mode.md)）负责；三者统一到同一套运动学内核的计划见 roadmap
「历史契约」一项。

### 5.1 当前实现：质心旋转 + 加权重剖分（固定网格）

**CVT 顶点在整个演化中永不移动**（移动顶点意味着每步都要重构 Delaunay）。
实现采用 Cortial 2019 原案的「质心运动 + 周期重剖分」策略（`_evolve_cortial2019`）：

1. **网格固定**：200K cell 是不动的观测站；演化状态保存在数组（高程、地壳类型、
   累积汇聚 s_arr / 累积伸展 e_arr）中，演化结束时一次性写回 cell。
2. **质心旋转**：重剖分时把每个板块的质心按各自欧拉极做 Rodrigues 旋转
   （`_rodrigues_rotate`），角度 = ω·δt·（距上次重剖分经过的步数），板块走满名义距离。
3. **周期重剖分**：每 `resample_every` 步（以及裂解事件后立即一次）以旋转后的
   质心为种子重跑 Voronoi 剖分——使用**出生面积乘性加权**的 Voronoi
   （`voronoi_partition_warped`），让板块尺寸偏态在迭代中不被拉平；有 geography.yaml
   锚定时剖分代价叠加海岸吸附成本，板块边界被钉在大陆边缘。重复种子去重
   （`_assign_distinct_seeds`），新生板块有 ~25 步保护期不被重剖分吞掉。
4. **海沟弧弛豫**：重剖分的直线二分边界按 Frank (1968) 海沟弧模型弯成弧
   （`_trench_arc_relaxation`，逐（俯冲侧, 上覆侧）对累积弧矢高，最终边界 warping
   时重放）。
5. **累积汇聚与伸展**：重剖分后按经过的时长累积边界两侧的汇聚与伸展量
   （`_accumulate_convergence`），驱动 §4.5 的造山带与裂谷宽度。Cortial 原文的逐步高程效应
   （俯冲上隆、碰撞造山、洋脊剖面、侵蚀）不运行：地形合成会从地壳、边界和累积汇聚量重建每个格子的
   高程，演化出的高程会被整体覆盖（空操作对照实验逐格一致）。
6. **板块裂解**：`_rift_plates`（Poisson 概率，大板块更易裂解，见 §13 威尔逊循环-D）。
7. **清理**：零 cell 板块移除（`_cleanup_empty`），尺寸权重与板块名册同步。
8. **终态整形**：演化结束后按边界类型分段整形（汇聚→弧、离散→雁列链、
   转换→直线，`_shape_boundary_segments`）→ 噪声 warping（`warp_boundaries`）→
   多数票平滑（`_smooth_partition`）→ 飞地合并（`_merge_plate_enclaves` /
   `_merge_enclosed_plates`）。

**时长模式**（`tectonic_duration_my > 0`，nacrea 与 earthlike 模板）：演化时长是世界输入；步长按该世界最快
板块的实际速度推导（`_auto_compute_dt`：`δt = 3 · √(4πR²/N) / v_max`，最快板块每步最多移动约 3 格），
步数 = 时长 ÷ 步长（`_evolution_steps`），每步都重剖分；裂解率按每百万年给出（`rift_rate_per_my`），
裂解冷却期约 8 Myr。未设时长时沿用步数模式（`tectonic_steps`，v_max 假定 10 cm/yr、每 10 步重剖分）。
`tectonic_dt_my > 0` 时显式覆盖步长。

### 5.2 演化状态（当前实现）

cell 在演化中跟踪的状态：所属板块（cell→plate 映射）、地壳类型（continental /
oceanic）、**累积汇聚量 s**（km，驱动造山带宽度——critical taper，§4.5）、
**累积伸展量 e**（km，驱动裂谷宽度）、高程，以及**连续汇聚段**：格子落在汇聚边界上时累加经过的
时间与汇聚量，边界移走即清零，演化结束时写入 `convergent_duration_my` 与 `convergent_run_km`，
供历史契约推导碰撞开始时刻（§6.1）。下方元组是全威尔逊循环的未实现设计：

| 属性 | 符号 | 类型 | 状态 |
|------|------|------|------|
| 地壳厚度 | `Thickness` | float (km) | 未实现 |
| 地壳年龄 | `Age` | float (My) | 未实现 |
| 造山年龄 | `Orogeny_Age` | float (My) | 未实现（§7.2 老造山带只读缝合带的碰撞年龄） |
| 褶皱方向 | `Fold_Dir` | 3D vector | 未实现 |
| 克拉通 | `craton` 地壳类型 | enum | 未实现 |


### 5.3 时间步进循环（当前实现）

```
For step = 0 to tectonic_steps:
  1. 质心旋转: 每板块质心按欧拉极 Rodrigues 旋转（角度 = ω·δt，δt 自动缩放）
  2. 周期重剖分（每 resample_every 步 + 裂解后）: 出生面积加权 Voronoi
     （有 geography 锚定时叠加海岸吸附代价）→ 海沟弧弛豫（Frank 1968）
  3. 易主 cell 检测 → 累积汇聚/伸展量（s_arr / e_arr）
  4. 板块裂解: Poisson 概率（rift_base_rate，大板块更易裂）；碎片继承父板块
     转速并加 ±15% 扰动
  5. 清理: 零 cell 板块移除，权重同步
  6. 速度刷新（重剖分或裂解后）: 按板块当前的大陆格子占比重算大陆减速，再把全部
     转速归一到平均速度（_refresh_plate_speeds）。地壳不随板块搬运，板块边界移动后
     大陆占比会变，减速随之更新；归一也阻止裂解扰动逐代累积抬高速度
演化结束后: 边界分段整形 → 噪声 warping → 平滑 → 飞地合并 → 写回 cell
```

未实现的循环成分（对应 §13 未实现设计余量）：全局环境演化（T_mantle /
omega_global / tide_stress / sea_level）、半拉格朗日属性平流（Thickness/Age/Type）、
洋壳创生、物质削减与 slab pull 反馈、气候快照、任意地质年代回溯。


---

## 6. 边界检测与分类

在 CVT 网格的邻接图上扫描所有边，两端属于不同板块的边即为**板块边界**段。

> 边界运动学与地质学依据已上浮至
> [knowledge/geology/plate_tectonics.md](../../knowledge/geology/plate_tectonics.md)
> §边界检测与分类：相对速度
> v_rel = (Ω_A − Ω_B) × P · R 及其法向/切向分解（v_n 汇聚为正、v_t 走滑），
> 各边界类型的地质效应（山脉/海沟/火山弧、洋中脊/裂谷、走滑断层）与
> 汇聚子类型（陆-陆碰撞、洋-洋俯冲、安第斯型俯冲）。

**实现要点**（`boundary_detector.py`）：

1. **邻接扫描**：遍历邻接表，以 `(min(a,b), max(a,b))` 去重，收集
   `BoundarySegment`（两端节点、两侧板块、中点坐标、`boundary_influence_km` 等字段）。
2. **相对速度分解**：先把 v_rel 投影到切平面（扣除径向分量），再沿边界法向分解
   （v_n 汇聚为正、v_t 走滑）。
3. **分段聚类分类**（`_classify_boundary_segments`）：按相邻板块对 `(plate_a, plate_b)`
   把边界 cell 聚类成连通段（`_cluster_cells`），每段用**段内平均法向**（指向另一侧板块的
   方向均值）+ 段质心的相对速度统一分类 → 边界类型连续成带，消除逐 cell `n̂` 噪声的斑驳。
   判据：`v_t/v_total > 0.7` → transform，`v_n > +0.5 cm/yr` → convergent，
   `v_n < −0.5` → divergent，否则 transform。
4. **边界链追踪**：将共享节点的同类边界段贪心连成链（`BoundaryChain`），
   供山脉走向、海沟线等线性特征生成使用。

> **Cortial 2019 俯冲上隆公式**（详见
> [knowledge/geology/cortial_2019_notes.md](../../knowledge/geology/cortial_2019_notes.md) §D.4）：
> $u_j(p) = u_0 \cdot f(d) \cdot g(v) \cdot h(\tilde{z})$
> 其中 $u_0 = 0.6$ mm/y, $r_s = 1800$ km, $h(\tilde{z}) = \tilde{z}^2$。
> 时间演化阶段不再计算该上隆（其高程会被地形合成覆盖，见 §5.1）；最终高程由 §7 地形合成的边界效应
> 给出。

### 参数表

| 参数 | 默认值 | 范围 | 物理含义 |
|------|--------|------|----------|
| `boundary_influence_km` | 500.0 | 100 – 2000 | 边界效应影响半径 |

### 6.1 历史契约：汇聚边界段（`orogen_contract.py`）

地形合成开始前，`build_orogen_contract` 按历史契约（`docs/design/proposals/history-contract.md` §3）
整理每段汇聚边界的缩短史，供造山剖面和海沟计算读取，结果写入 `orogen_contract.json`。
文件采用 `orogen-contract-v2`：保留分段摘要，并在 `detail` 中保存完整精度的段参数、接触格归属、逐格汇聚量、
现今速率、逃逸比和保留缩短量。导出阶段同时记录接触格坐标、板块归属、行星半径及网格几何签名。
`load_orogen_contract` 可恢复这些量，并按格号与坐标核对所用网格；旧摘要文件在重新导出后用于来源重放。

`contact_history` 保存逐接触格的连续汇聚时长、连续与累积汇聚量、最近演化格号及迁移弦长。
`ContactConvergenceHistory` 的 `status` 标记匹配结果；未匹配格沿用数值契约的零值，来源格号与迁移距离为 null。
作者覆盖改变有效段参数与汇聚量，演化记录继续作为独立来源保存。旧 v2 数值 `detail` 的结构保持，历史字段缺省的文件仍可读取。
`geometry.interfaces` 保存所选段全部接触格对应的共享 CVT 边，`geometry.vertices` 保存共用顶点的球面坐标，
弧的两端按法向指向 `pro_plate` 定向。每条边同时记录接触格与正保留量接触格，零贡献段保留其界线；
`geometry.evolution_sources` 保存迁移来源格的坐标。来源范围、界线连接与后续山前、主谷几何分别处理。

`subduction_polarity` 以 `subduction-polarity-v1` 保存所有汇聚接触的类型、下插与上覆板块、来源定义和年代。
`subduction_polarity.py` 读取 `plate_history.yaml` 的明确板块对声明，作者声明与有引用的观测声明使用同一接口。
缺省的洋陆方向来自陆壳对比，洋洋方向来自原绝对速度近似，碰撞方向来自原板块尺寸近似；来源类别分别保存。
明确俯冲声明作用于洋陆和洋洋接触，碰撞段的侧别仍由其历史契约确定。
`resolve_contract_polarities` 在地形阶段的陆壳恢复和整理完成后保存 `terrain-crust` 快照，
海沟与岛弧共享其接触类型和侧别，陆架读取同一次海沟计算的作用域。
缓存命中时从已恢复的地壳建立相同快照，造山段缩短史保持原数值。
加载契约除几何签名外，还校验接触格的板块归属和相邻板块对。terrain 缓存版本为 46。

1. **接触格与类型**：汇聚边界上、速率高于 0.3 cm/yr、紧邻另一板块的格子。两侧各取该板块 500 km 内
   的陆壳占比：都过半为碰撞，俯冲侧取较小的板块；一侧过半为安第斯型，洋壳一侧俯冲；都不过半的洋—洋
   边界留给岛屿目录。同一板块对、相距 150 km 以内的接触格连成一段。
2. **碰撞开始时刻与积分汇聚量**：演化结束后的边界整形会把边界移开（nacrea 上终态接触格到最近的演化
   汇聚格中位约 100 km，90 分位约 400 km），所以每个接触格读取 400 km 内最近的演化汇聚格的
   `convergent_duration_my` 与 `convergent_run_km`。留存缩短量逐格计算（边界会弯折、斜交程度沿走向变化，
   整段共用一个中位数会把正面段的汇聚量套到斜交段上）；段内中位数作为摘要，逐格量另存于契约的完整记录。
3. **作者覆盖**：`plate_history.yaml` 的 `collisions` 与 `andean_margins`（`load_collision_overrides`）
   按板块对或折线（两倍半宽内过半的接触格）认领段，可改写开始时刻（积分汇聚量随之取现今速率乘开始
   时刻）、断离时长、安第斯型缩短比与俯冲侧。
4. **侧向逃逸比**（`escape_ratios`）：碰撞接触格按 150 km 连成造山带前缘，W 为前缘沿走向的测地长度。
   出口是上覆板块 2W 内的边缘格：面向大洋俯冲的海沟（外移速度取四分之一压入速率），或与正在远离
   造山带（远离分量大于 0.5 cm/yr）的相邻板块之间的非汇聚边界（外移速度取远离分量，不小于四分之一
   压入速率）。每格逃逸比 = Σ 外移速度 × 格距 × exp(−D/W) / (U·W)，上限 1。
5. **留存缩短量**：碰撞格为 (min(积分汇聚量, 3000 km) − 180 km − 现今速率 × 断离时长) × (1 − 逃逸比)，
   不小于零，再加缩短比 × 碰撞前汇聚量（碰撞前的安第斯型阶段）；安第斯型为缩短比 × 积分汇聚量。3000 km 是
   地球最大碰撞（印度—亚洲）的量级：碰撞阻力让板块减速，而「指定现状」模式下大陆不动，合成边界可以在大陆
   内部持续汇聚几乎整段演化（nacrea 最多约 8000 km）。断离时长缺省 10 My，缩短比缺省 0.026（地球洋陆边缘按汇聚量加权的观测值）。

一致性提示：作者开始时刻超过构造演化长度；碰撞太年轻、尚未开始增厚的段数。nacrea 当前 26 个碰撞段的
开始时刻中位约 21 My、75 分位约 25 My，其中 13 段尚未开始增厚。

---

## 7. 地形合成

节点高程 = 双峰基准 + 边界构造效应 + 热点隆起 + 区域 fBm + 细节 fBm × 内部调制
（+ 潮汐形变，仅潮汐锁定天体）。

> 地球物理依据与公式已上浮至
> [knowledge/geology/terrain_synthesis.md](../../knowledge/geology/terrain_synthesis.md)：
> 双峰高程分布依据（§1）、三类边界剖面公式与速率因子汇总表（§2）、
> 距边界粗糙度调制（§2）、fBm octave 物理尺度表（§3）、热点/地幔柱高斯隆起
> 与高程合成叠加式（§6），以及老造山带的地貌学依据（§4.3）。

### 7.1 合成流程（6 步）

**实现**：`terrain_synthesizer.py:_synthesize_asymmetric`（默认算法，
策略由 `terrain_algorithm` 选择；`cortial2019_gaussian` 为对称版）：

1. **基准高程**：按地壳类型双峰分配——continental `continental_elevation_m`
   （默认 850 m）、oceanic `oceanic_elevation_m`（默认 −3800 m）两个常量；若 `ocean_age_depth_enabled`，
   已知年龄的洋壳替换为年龄-深度剖面（见 §7.4）。每板块叠加均匀偏移 ±`plate_elevation_spread_m`（陆地取
   0.4×），已知年龄的洋底不加（深度由年龄决定）；陆地叠加多尺度起伏 `_continental_undulation`
   （`continental_undulation_m`，默认 600 m），它代表地幔流场之外的岩石圈厚度差与小尺度对流造成的
   1000–5000 km 起伏（地球大陆残余地形 ±1–2 km，Stephenson et al. 2024），属启发式。
   **动力地形**（`dynamic_topography.py`，技术债 43 阶段 E 第 2 步）：引擎地幔流场的径向分量只有绕极向轴
   （潮汐锁定为潮汐轴，否则为自转轴）的二阶极向环流，所以动力地形为 h = A·P₂(cos θ)，两个上涌点抬升 A、
   下沉环带下沉 A/2；A 在洋壳上取 800 m（地球残余地形二阶分量的水负载峰值，Davies et al. 2019），陆壳上按
   (ρm − ρw)/ρm 取约 550 m。浮力与偏转都正比于 g，幅度在各世界间不变。叠加在基准高程上，先于海沟、弧前与
   海平面校准。
2. **非对称边界效应**：`_asymmetric_boundary_effects` 按边界类型叠加高斯剖面
   （σ 由 `boundary_influence_km`，振幅 × 速率因子 `min(|v_n|/10, 1)`，
   `mountain_asymmetry` 控制迎/背风坡不对称），叠加 **沿弧分段 fBm 调制**
   （~800 km 波长，隆起幅度 ∈ [−0.25, 1.35]）：高值段成主岛/山结，负值段沉降为
   弧间断陷海——汇聚带不再均匀缎带；`boundary_uplift_noise` 调制岛弧/洋脊。
   **沿线形态（2026-09-29）**：(a) 大陆裂谷宽度叠加沿线相位调制
   `σ × (1−m + 2m·u)`（`rift_axis_modulation`，u 为 ~800 km 平滑 fBm ∈ [0,1]），
   入海深度同步渐变 `×(0.55+0.45u)`——低 u 段回退为东非式高出海面地堑，一条边界
   上呈现红海↔东非裂谷相变镶嵌（Vink 1982 传播裂谷沿线伸展梯度）；(b) 剖面中心
   **侧向蜿蜒**：裂谷轴线 `ds_side = d·side − rift_meander_km·δ_div(x)`、汇聚带
   山体/山间盆地/海沟整体 `d − orogen_meander_km·δ_conv(x)`（δ 为 ~650 km fBm
   ±1，`_divergent_side_sign` 提供裂谷的稳定带符号侧向坐标）——水体与山带不再
   精确贴板块边界，而是随先存弱带蜿蜒（Danakil en-echelon 错列 / 阿巴拉契亚
   salient-recess ~100 km 量级）。
   **大陆汇聚带不在这一步**：碰撞与安第斯型边缘上覆侧的大陆格子不再取幅度剖面与山间盆地，
   改由下一步的造山带格子平均高程给出，海沟改由第 2c 步的挠曲剖面给出；洋—洋岛弧改由第 3 步的岛屿目录给出
   （`island_catalog_enabled` 关闭时才回到这里的岛弧幅度与后处理 `_apply_island_arcs`）；这里只保留裂谷与转换边界。
2b. **造山带格子平均高程** `orogen_profile.py::orogen_relief`（技术债 43 阶段 A，设计见
   `docs/knowledge/geology/orogen_topography.md` §2–4）：读取历史契约（§6.1）每个接触格的留存缩短量，
   沿走向 300 km 平均后得到地壳截面积 A = 留存缩短量 × 35 km；Airy 均衡（ρc 2800、ρm 3300 kg/m³）下
   高程截面积为 A / 6.6。剖面两翼坡度都取 0.6°（地球格子平均翼部坡度的中位数，观测拟合；喜马拉雅前缘
   约 2.8° 的陡前缘类别留待以后）；顶部平均高程不超过
   上限再减去大陆基准高程：碰撞型上限由力平衡推出（`collision_cap_m`：Airy 补偿高原的浮力
   ρc·g·h·(H0 + h·ρm/(2Δρ)) 等于以青藏 5.0 km 标定的可传递力，强度系数暂取 1；nacrea 约 4.82 km），
   安第斯型取阿尔蒂普拉诺 3.8 km 按 9.81/g 缩放（`andean_cap_m`）；截面积超过楔形容量时，
   多出的部分在上覆板块一侧铺成高原。每个非洋壳格子在所有边界段中取最高的剖面：前楔一侧是该段的俯冲板块，
   后楔一侧是边界以外的全部非洋壳格子（上覆高原可以跨越几块板块），距离沿该侧格子的图距离量；每段的搜索
   范围覆盖它完整的剖面；离边界越远，留存缩短量越从最近接触格的值过渡到全段平均（混合距离取边界段长度），
   以免相邻格子取到不同接触格而切出悬崖。地形合成在海平面校准之后，用 `apply_orogen_cap` 把造山带格子的
   最终平均高程软压在各自的上限附近（超出部分按 300 m·tanh 压缩，青藏高原面格子平均的离散约 ±0.3 km），
   纹理噪声不能把高原推过上限。
   **亚格子起伏与峰顶**（阶段 C，`subgrid_relief.py`）：地形阶段之后，陆地格子写入 `relief_std_m`（格内
   高程标准差）与 `peak_elevation_m`（格内最高点）。μ = c·Δx·S / (1 + c·Δx·S / μ_sat)，S 为与陆地邻格平均
   高程差的平均坡度，Δx 为格距，c ≈ 0.97、μ_sat ≈ 2.9 km；峰顶 = 平均 + 3.5μ。标定用地球 2722 个被 Copernicus
   90 m 高程完全覆盖的陆地格（观测拟合，对数残差标准差 0.69），按它推算的地球最高峰 8190 m 落在珠峰所在格。
   洋格写 None，沟轴最深点见第 2c 步。
2c. **海沟** `trench_flexure.py::trench_relief`（技术债 43 阶段 D，物理与标定见 `docs/knowledge/geology/orogen_topography.md` §5–6）：
   只在俯冲板块的洋壳格子上加挠曲下弯 w(x) = −W0·e^(−x/α)·cos(x/α)，叠加在年龄深度海底上。沟轴格是俯冲侧的
   汇聚接触格：洋陆边界取历史契约安第斯段的俯冲板块，洋洋边界取共同极性快照的下插板块（`contract_contact_polarity`）。x 沿该板块
   洋壳格子的图距离量，每格取 w 在 [d, d + Δx] 上的解析平均，剖面在 3π/2·α 处归零。Te 取 25 km（地球
   α ≈ 65 km，随 g 按 g^(−¼) 变化），W0 取 2.0 km（ETOPO 沟轴格相对外侧海底的中位数反推，观测拟合）。
   地形阶段之后，俯冲侧沟轴格写入 `trench_axis_elevation_m`（沟轴格的最终平均高程减去 0.38·W0，即 W0 与沟轴格平均下弯 0.62·W0 之差），
   其余格子写 None。
   **弧前带**（`trench_flexure.py::forearc`，物理见 `docs/knowledge/geology/orogen_topography.md` §6）：洋陆边缘上覆一侧的格子平均高程不高于楔面
   s(x) = z_axis + tan 1.55° · x（z_axis 为沟轴格平均高程，x 为沿上覆一侧到最近沟轴格的图距离），楔面一直跟到
   海平面以上 6 km：海平面以下是淹没的弧前带，以上是一道斜坡，使相邻的碰撞高原等上覆板块起伏不会在弧前带上方
   立成悬崖。楔面在陆架之后施加，它淹没的陆地由后处理第 7 步的海平面末次微调补回。安第斯型
   剖面的前翼从弧前带内缘（海岸，弧前带宽度 −z_axis / tan α）起抬升，峰脊在其内侧一个翼长（峰高 / tan 0.6°）处
   （`orogen_relief` 的 `forearc_km`），截面积不变。
3. **热点链、岛弧与热管火山省（亚格子岛屿目录）**：`island_catalog.build_island_catalog`（技术债 44 阶段 A–C，设计见
   `docs/design/proposals/island-catalog.md`）。热点数按地球面积比例（每地球面积 49 个，Courtillot et al. 2003），
   带种子的 Poisson-disc 撒在全球，只有落在洋壳上的建岛。每个热点固定在地幔里，沿所在板块的现今欧拉极回溯
   2000 万年，每隔 λ = 0.70·α 开一座新火山（α 为洋壳挠曲参数，Te 25 km；0.70 用夏威夷约 45 km 的间距标定），
   λ 与板块速度无关，喷发间隔 = λ ÷ 板块速度。火山高出原海底的体积 = 热点岩浆通量 × 喷发间隔 × 0.5（另一半
   在自身挠曲山根里，Robinson & Eakins 2006）；通量按对数正态分布抽取，中位数 0.017 km³/yr、σ_ln 1.0（夏威夷约为
   中位数的六倍）。火山体为 5° 锥体，高度上限 9 km × 9.81/g，超过上限时变宽而不变高。格子平均高程吸收火山体
   体积（按锥高分摊到覆盖的格子，`volcano_cell_mean`），老火山按 S(t) = 2 km × (1 − e^(−t/0.8 My)) 相对周围海底
   下沉，一个格子的抬升不超过覆盖它的最高火山。海山按每地球大洋 3.9 万座高于 1 km（Hillier & Watts 2007）撒在
   深于 2 km 的洋底上，只进目录。
   岛弧取洋—洋俯冲接触格（`contact_polarity`）上覆板块一侧，弧轴离海沟 240 km（弧沟距离均值，Perrin et al. 2018；
   板片深约 105 km，Syracuse & Abers 2006），距离沿同一板块的洋壳格求最短路（`_arc_geometry`）。弧的岩浆供给取
   每公里弧长 40 km³/Myr（Dimalanta et al. 2002 为 30–95，Reymer & Schubert 1984 为 20–40），侵入与喷出约 5 : 1
   （White et al. 2006）。侵入部分按弧龄累积，分布在弧轴两侧各 125 km 的三角形截面上（伊豆—小笠原—马里亚纳弧的
   地震剖面，Takahashi et al. 2007），按水下 Airy 系数 (ρm − ρc)/(ρm − ρw) ≈ 0.22 抬升成弧地壳平台
   （`arc_platform`）；弧龄取 400 km 内最近的演化汇聚格的连续汇聚时长。喷出部分建弧火山：沿弧轴按平均间距
   50 km 的一维泊松过程放置（弧上火山没有特征间距，de Bremond d'Ars et al. 1995），每座体积 = 40 × 0.2 × 50 ×
   1 Myr = 400 km³，年龄在最近 100 万年内均匀抽取，和热点火山一样进入格子平均。
   热管火山省只在世界提供潮汐热流史（`tidal_heat_history.yaml`，由引擎读入 `tidal_heat_history`）时生成，纯函数在
   `map/heat_pipe.py`。加热图样取倾角潮在软流圈薄层的 Beuthe 图样 B（`heating_pattern`，Ĥ = 2.5(x² + y²) − 10x²y²，
   全球均值 1），极大在向星点、背星点与两极，四个火山省按最近的极大划分（`province_index`）。当地热管热流 =
   max(q(t)·a·Ĥ − q_plate, 0)，q_plate 为板块按半空间冷却排出的热流（`tidal_physics.plate_heat_flux_w_m2`），
   每 W/m² 合每百万年 5.26 km 岩层（`heat_pipe_rate_km_my`）。`heat_segments` 把时间线分成静息段与潮汐期（阈值
   `active_threshold_w_m2`）：最近 200 万年用世界给的正典热流，更早到 2000 万年按集合统计带种子抽取；潮汐期各火山省
   的活跃度按 `province_activity_sigma_ln` 随机抽取，最近一期取 `latest_phase_activity`。每块地壳沿板块欧拉极回溯，
   离开所在板块即停止；每段内喷口密度 = 当地热管热流 ÷ 单口功率 2.4×10¹¹ W（木卫一 1.0×10¹⁴ W ÷ 417 个火山口），
   每口建一座 0.4° 的宽缓盾（木卫一盾的坡度 0.2–0.6°），体积 = 单口岩浆量 × min(火山间距 ÷ 板块速度, 段长) ×
   0.2 × 0.5；其余岩浆铺成熔岩流，掩埋更早时段的火山。每块地壳保留现存最高的一座。热管盾生长时已均衡补偿，不加
   建成后的沉降；地壳取稳态，不加高原。地形阶段之后 `summarise_islands` 在最终地表上算峰顶（出水部分按 500 万年的
   e 折时间降低，考艾岛标定）、出水面积与状态（立在陆地上的记为 land volcano），出水部分比格子还宽的火山由网格分辨、
   不计入汇总，写入格子字段 `island_count`、`island_area_frac`、`island_peak_m`
   与 `hotspot_id`，火山格的 `peak_elevation_m` 取目录峰顶；地图目录输出 `island_catalog.json`。

   目录同时输出 `built_relief_m`、`floor_elevation_m` 和 `present_relief_m`。
   建成起伏相对于建成背景海底，当前背景高程为最终格平均减去目录自身格内贡献后相对于海平面的高程，
   当前峰顶高差为 `summit_m` 减去该背景。新增字段便于细剖面与格内贡献使用同一参考态。
   格内体积的沉降近似和出水轮廓的演化近似分别登记，连续剖面接入先核对二者的体积与基底范围。
4. **区域噪声**：低频 fBm（`regional_noise_scale`，陆/海不同振幅
   `regional_noise_amplitude_land_m` / `regional_noise_amplitude_ocean_m`）。
5. **细节噪声**：`_anisotropic_fbm`（3D Simplex 在节点 (x,y,z) 采样，无投影畸变；
   各向异性 `noise_anisotropy` 沿边界走向拉伸）；近边界 `interior_factor` 增强
   （1.2→1.5×，山体更崎岖）。
6. **合成**：`elevation = base + boundary + orogen + hotspot + regional + detail`。

> **边界平滑**（作用于分区，非高程）：最终分区多数投票 `_smooth_partition`
> （4 轮）+ 飞地合并 `_merge_plate_enclaves`，消除锯齿边界。per-plate 地壳下限
> `crust_plate_floor`（默认 0.10）避免整板近零陆壳；泄漏陆壳 `_relabel_leaked_crust`
> 在 base 前重标为洋壳（洒点岛屿只由岛弧/热点/钉扎涌现）。

### 7.2 老造山带：沿古缝合带的残留山脊

> 实施：`paleo_orogens.py::paleo_orogen_relief`（技术债 43 阶段 E 第 1 步，设计见
> `docs/design/proposals/orogen-topography.md`）；地貌学依据见
> [knowledge/geology/terrain_synthesis.md](../../knowledge/geology/terrain_synthesis.md) §4.3。

老造山带只来自历史输入：`plate_history.yaml` 中带碰撞年龄的 `sutures`（引擎读入 `paleo_sutures`）。
没有缝合带的世界没有老造山带。每条缝合带沿折线立起一道山脊，脊线高出大陆基准

```
Δh(t) = h_r + (h₀ − h_r) · e^(−t/τ)        t = collision_age_myr
```

τ = 70 My（含均衡回弹的观测拟合，Pazzaglia & Brandon 1996），h_r = 400 m（地球约 300 My、未经再抬升的老带
脊线：阿巴拉契亚南段 587 m、北段 301 m、乌拉尔 359 m，20 万格格子平均高出相邻地台的第 90 百分位）。h₀ 是
本世界典型碰撞的脊线：各碰撞段中值留存缩短量对应的楔形峰高（不超过碰撞型平均高程上限）取中位数
（`orogen_profile.collision_crests_m`）；世界没有碰撞段时取碰撞型上限减大陆基准。横剖面是活动造山带的楔形，
半宽 W = h₀ / tan 0.6°（与 §7.1 第 2b 步的翼部坡度相同），按衰减后的脊线缩放：Δh(t)·(1 − d/W)，d 为到折线的
距离；衰减只降低、不收窄。只作用于非洋壳格子，与造山带剖面取较大者，作为 `orogen` 的一部分在海平面校准
之前叠加；有残留山脊的格子标记 `landform = "orogeny"`。缝合带的 `width_km` 只是古地理倒推的标记宽度。
地质时间轴从起伏倒推年龄时用同一公式的反函数（`paleo_orogens.collision_age_from_crest`）。

### 7.3 内部低地：大陆内部系统性下压

> 实施：`terrain_synthesizer.py:_apply_interior_lowlands`
> 科学依据：`knowledge/geology/terrain_synthesis.md` §4.4（Cogley 1984；ETOPO1）

双峰基准（大陆 850 m）+ 汇聚边界隆起后，板块内部残留为均匀高原——纯过程合成会把
近半陆地堆到 >1000 m，而地球陆均高 ~350–500 m。`_apply_interior_lowlands` 以汇聚
边界 cell（`boundary_type == "convergent"` 且 `distance_to_boundary_km == 0`）为源
做多源 BFS，得每个陆壳 cell 到最近汇聚边界的距离 `d`，再按 Hermite smoothstep 下压：

```
lowering = depth × smoothstep(d / scale)
elev     = softmax(elev − lowering, sea_level + floor)   # 软钳制，只降陆壳 cell
```

`floor` 把下压**软钳制**在海平面之上（logsumexp 光滑最大值，非硬钳 `max`）——
**校准后的海岸线（目标陆面比）不变**，低地也不会全部堆在同一个高度。在 §7.5
后处理中排在海平面校准之后、岛弧之前；老造山带在校准之前已叠加，随大陆基准一起下压，相对高度不变，裂谷与
盆地则下切（部分低于海平面，成内流湖或内海）。

`interior_lowland_distance_scale_km` 表示距汇聚边界达到全部下压量的过渡距离，
`interior_lowland_depth_m` 与 `interior_lowland_floor_m` 分别约束下压量和高程下限。
作者给出的区域高程钉扎另在最终地表作用。山前和沿岸平原的宽度、存在范围与岸边高程采用各自的来源依据；
沿岸默认剖面和陆架的陆缘类型均值分别保留其数值重建与海底地形近似的适用范围。

| 参数 | 默认值 | 范围 | 含义 |
|------|--------|------|------|
| `interior_lowland_enabled` | true | — | 是否启用（false = 关闭） |
| `interior_lowland_depth_m` | 600 | 200–1200 | 深部最大下压量（m） |
| `interior_lowland_distance_scale_km` | 1500 | 500–3000 | 下压 0→满深的距离（km） |
| `interior_lowland_floor_m` | 0 | 0–200 | 下压后离海平面最低高度（m，0=海平面） |

**沉积填充**（`_apply_deposition_fill`，紧接内部低地之后）：内部低地把深部压到海平面
以下后，`floor` 软钳制把它们钳到 ~0m（先保住海岸线），并返回**被钳制的 cell 掩码**。
沉积填充**只填这些被钳制的 cell**（内部低地的过冲），把它们填到**溢流点**（通往全球海洋
的最低出口），使其重新排水——参照 [Landlab SinkFiller](https://landlab.csdms.io/generated/api/landlab.components.sink_fill.fill_sinks.html)
（Tucker et al. 2001）；以海洋为源做 priority-flood 得每 cell 的溢流点高度，把被钳制、
且低于溢流点的 cell 填到溢流点。**天然的海/海峡没被钳制，不会被填**。留一小部分盆地
（`lake_fraction`，仅 ≥20 格的大盆地）填到 `spill − lake_depth_m`，标记 `is_lake` 为
外流湖。这样**只调整内陆海拔、不动海岸线**（陆地面积比保持 28%）。

| 参数 | 默认值 | 范围 | 含义 |
|------|--------|------|------|
| `deposition_enabled` | true | — | 是否启用 |
| `lake_fraction` | 0.2 | 0–1 | 留作外流湖的盆地比例 |
| `lake_depth_m` | 50 | 10–400 | 湖面低于溢流点深度（m） |

### 7.4 洋底年龄-深度沉降（板块冷却模型）

> 实施：`terrain_synthesizer.py:_compute_ocean_age_depth`
> 配置：`terrain_config.yaml` → `ocean:` 段落；理论：`isostasy_elevation_limits.md`

洋底深度随距洋中脊距离增加而加深，遵循半空间冷却律：

```
depth = ridge_depth + subsidence_coeff · sqrt(age)
```

**年龄估算**：不用距 divergent 边界的直接距离（Voronoi 边界密集复杂），而是
**divergent ↔ convergent 距离比插值**：

```
age = max_age · d_div / (d_div + d_conv)
```

- divergent 边界（d_div=0）：age=0 → shallow ridge (~2500m)
- convergent 边界（d_conv=0）：age=max → deep basin (~5500m)
- 中间按比例插值，模拟洋壳从脊到沟的输送带运动

不能同时到达两类边界的海洋 cell（孤立盆地）保持均匀 `oceanic_elevation_m`。

**nacrea 参数**（活跃地质体 + 较高重力）：

| 参数 | nacrea 值 | 地球参考 |
|------|----------|---------|
| `ocean_ridge_depth_m` | 2500 | ~2500 |
| `ocean_subsidence_coeff` | 350 | ~350 |
| `ocean_max_age_myr` | 100 | ~100 |
| `ocean_max_age_depth_m` | 5500 | ~5500 |

效果：均海深 3015→3687 m（对齐地球 3682 m）；浅水 0-500m 占比 14.8%→10.6%（地球 8%）。

### 7.5 后处理（顺序）

合成后按序执行（弧/造山带增加高程，架/平原必须最后，否则被覆盖）：

1. **海平面校准（倒水）**：在按高程排序的累计面积曲线上求海平面，使陆面比例 = `target_land_fraction`；曲线在相邻格子高程之间线性插值，解随高程连续变化，一个海岸格的浮点末位差异不会让全图平移一个高程空隙（§8；该值未在
   terrain_config 显式配置时，从 planets.yaml 的 `hydrosphere.water_coverage` 推导为
   1 − 水覆盖率，保证设定文档与生成地形不脱节）。
2. **内部低地** `_apply_interior_lowlands`（见 §7.3）：以汇聚边界为源做多源 BFS，
   大陆内部按 `depth × smoothstep(d/scale)` 下压。
3. **沉积填充** `_apply_deposition_fill`（见 §7.3）：把低于海平面的闭合盆地填到溢流
   点，留一小部分为内流湖。
4. **岛弧** `_apply_island_arcs`：只在 `island_catalog_enabled` 关闭时运行（岛弧高度加隆起调制）；缺省由岛屿目录
   给出岛弧（见地形合成第 3 步）。
5. **大陆架** `_apply_continental_shelf`：陆架铺在与海岸相连的淹没大陆地壳上，宽度是海岸线到陆洋边界的
   距离（`_shelf_profile`）；地壳划分没有拉薄陆缘这一档，所以每段海岸另按陆缘类型补一条淹没陆缘带（被动 88 km、
   主动 31 km，Harris et al. 2014；离汇聚或转换边界不足 `boundary_influence_km` 的海岸为主动），陆架取两者中
   较远的一个；平台从岸边线性降到坡折深度 `shelf_break_depth_m`，坡折以外按约 4° 的陆坡降到
   原有海底；距离从海陆 Voronoi 边量起，每格取剖面在本格范围内的平均。`shelf_width_km <= 0` 关闭此步。
   物理依据见
   `docs/knowledge/geology/continental_margins.md`。
   常规非对称合成通过 `active_flexure` 传入同一次 `trench_relief` 计算的下沉板块挠曲作用域；
   这些格保留入沟海底与挠曲地形，陆架和陆坡用于其余陆缘基底。随机数消耗保持一致，
   弧前楔、海底限深与末次海平面校准继续消费实际地表。terrain 缓存版本为 46。
   高斯合成采用原有海沟表达，陆架调用沿用该算法的作用域。
   极性来源与共同接触快照见 6.1 节，连续来源的采用范围见
   [画布管线 2.5.2](canvas-chain.md#252-连续地形来源)。
6. **沿海平原** `_apply_coastal_plain`（`coastal_plain_width_km`）：对所有陆上 cell
   （海拔高于海平面且有海洋邻居）施加海岸过渡，不论地壳类型——O-C 俯冲带下插侧
   （物理上是海沟）和大陆海岸山一起平滑（§4.4 海岸过渡）。随后施加弧前楔（§7.1 第 2c 步）。
7. **海平面末次微调**（技术债 47）：弧前楔等后处理在第 1 步之后改变了陆地面积。在最终地表上按同一口径再解一次
   海平面，使陆面比例回到 `target_land_fraction`；此时淹没的陆壳已是陆架，海平面只需移动几十米（nacrea 约
   −18 m），露出陆架内缘一圈浅滩。陆架不重铺：它随海平面而定，重铺会让校准沿铺陆架之前的陡坡一路追下去
   （nacrea 需压低约 480 m）。
8. **地理钉扎** `_apply_geography_pins`：钉扎 authored 高程（最后覆盖）。`pin_exponent>1`
   （削峰）只放大「高于目标」的下压方向，低于目标（海沟）保持线性上拉——避免把
   feature 软边上的深沟 cell 对称指数化抬成山（§4.4 钉扎过抬修复）。拉动量不超过到目标的偏差
   （最多拉到目标）。分两遍：`pin_crosses_sea_level` 为假的地物（默认，大陆平均海拔一类）只作用于与
   目标同侧的格子——正目标只动陆地、负目标只动海洋——所以不改变海岸线；标为真的地物（陆桥、
   人工海峡）随后作用于所有格子。
9. **不做渐近压缩**：格子值是格子平均高程，海沟的格子平均深度由第 2c 步的挠曲剖面给出，海洋深度上限
   `isostasy_max_ocean_depth_m` 只是沟轴点深度的检验量。陆地上限
   `isostasy_max_continental_elevation_m`（峰顶高度，nacrea 8443 m）不再压缩格子平均高程，造山带的平均高程由
   §7.1 第 2b 步的剖面上限约束；为抹平压缩台阶而设的陆地拉普拉斯平滑一并取消（对称版
   `cortial2019_gaussian` 仍保留旧的海沟凹槽、压缩与平滑）。

洋中脊在已知年龄的洋底上就是年龄-深度曲线本身（脊轴年龄为 0），边界剖面不再另加脊顶凸起：轴部隆起与
中央裂谷宽 10–30 km，在格子平均的地图上属亚格子。没有年龄的洋底（只够得到一种边界的板块）沿用按张开速率
选择的形态：全速率不低于 9 cm/yr 时为平滑的轴部隆起，不高于 5 cm/yr 时为中央裂谷加两侧裂谷山，其间过渡
（Frisch et al. 2011）。张开速率来自板块运动学，没有单独的扩张速率参数。

### 7.6 参数表

常规管线可通过 `run_terrain_pipeline(..., source_fields=...)` 按需导出原地质阶段的数值来源。
该选项保留有效的网格、板块、构造与边界缓存，重新计算地形以记录实际阶段值。
`terrain_sources.npz` 保存源网格坐标、各活动山带贡献、古山带包络、基底、边界地形、海沟及弧前表面，
同时保存陆架和平原前后高程、该次计算的低地目标和最终高程。
陆架捕获还保存原岸格编号、实际宽度、岸距、岸边深度及剖面调制；
`shelf_coast_drowned_width_m` 保存与岸相连的淹没陆壳所给出的几何范围，
`shelf_coast_type_width_m` 保存当前陆缘类型采用的观测平均宽度，
`shelf_coast_type_active_mask` 保存该岸格的活动陆缘分类。
三者沿用 `shelf_coast_cell_id` 的来源对应，实际宽度取几何范围与类型平均值中较大的一个。
侧记文件的 `basis` 说明各项依据；类型平均值描述全球观测尺度，局部宽度由相应地质或作者来源补充。
`coastal_plain_blend_fraction` 保存原平原算子的实际混合系数，未参与混合的格子为 1。
这些字段由该次合成的原参数和随机实现取得，来源捕获保持正常数值路径和随机数消耗。
侧记文件 `terrain_sources.json` 采用
`terrain-source-fields-v1`，记录数组形状、单位、缺值语义、地形指纹、半径及源格距。
来源数组在捕获时复制并冻结，消费时校验文件哈希及所用地形指纹。
匹配指纹的缓存重放保留来源档案，地形来源改变后使旧档案失效。
这些数组保存现有计算的信息，解析几何精度仍由原网格及地物来源决定。
主体构造演化和地形合成使用同一原生 CVT 网格；200k 格对应约 50 km 的信息尺度。
山带解析剖面、挠曲曲线和岛屿目录可在亚格子位置求值，来源捕获保存这些已有信息。
连续查询的取样间距与构造几何的原始精度分别记录。

阶段档案同时保存与源点同序的 `cell_area_km2`、实际大陆地壳指示量
`shelf_continental_crust_mask` 和造山资格 `land_crust_mask`。
`combined_elevation_m` 与 `after_initial_sea_level_m` 给出初次海面校准前后的表面；
`orogen_cap_m`、`after_orogen_cap_m`、`after_interior_lowlands_m`、
`interior_lowland_clamped_mask` 和 `after_deposition_fill_m` 给出实际高程上限及低地响应。
岸坡之后的 `final_forearc_surface_m` 与初次校准采用同一海面基准，
`after_forearc_m`、`after_deep_ocean_clamp_m`、`after_final_sea_level_m` 和
`after_overlay_archipelago_m` 给出后续阶段端点。`final_elevation_m` 是作者约束后的表面。
消费者按这些阶段的实际顺序组合来源，并用相同球面面积核对原生重放及来源体积。
按需捕获也保存 `volcano_cell_mean_m` 和 `arc_platform_m`，分别记录火山体的原格内贡献与弧地壳平台。
侧记的 `source.island_geometry` 使用 `volcanic-cone-sources-v1`，以完整精度保存地物来源、年龄、建成几何和当前背景。
`island_source.catalogue_geometry` 根据当前峰顶与建成翼坡导出连续锥体，其体积与原格内载荷分别保存。
默认地形与目录汇总沿用当前算法，连续几何由来源试点显式消费。
连续来源替换使用实际撤回响应建立背景。原载荷经陆架覆盖、海面校准及作者钉扎后，
对最终高程的贡献随阶段组合而变；研究重放保存各阶段输入与输出，并使目录峰顶消费对应背景。
生产目录的背景估计与实际来源存活分别核对，新的背景定义通过全局验收后再接入汇总。

`geography.build_elevation_pins_at_xyz` 为连续球面查询提供同一作者高程约束，
`terrain_synthesizer.apply_elevation_pin_values` 共用于粗格和连续地表，保留两遍侧别、指数和目标约束。
`shelf_source.ShelfEnvelopeDifferenceSource` 按前陆架地表的海面交线计算连续岸距，
查询原宽度与调制场，将陆架—陆坡剖面与实际背景组成较浅表面包络。
它返回冻结陆架端点差，后续平原、前弧、海底限深、海面与作者约束由消费入口另行组合。
当前连续陆架采用显式研究入口，常规 200k 地形继续沿用已接受路径。

| 参数 | 默认值 | 范围 | 物理含义 |
|------|--------|------|----------|
| `continental_elevation_m` | 850 | 400 – 1500 | 大陆基准高程 |
| `oceanic_elevation_m` | -3800 | -5000 – -2000 | 海底基准高程 |
| `convergent_uplift_m` | 4000 | 1000 – 5000 | 汇聚边界山脉振幅 |
| `divergent_depth_m` | 2000 | 500 – 2000 | 离散边界山脊振幅 |
| `boundary_influence_km` | 500 | 100 – 2000 | 边界效应影响半径 |
| `mountain_asymmetry` | 0.4 | 0 – 1 | 迎/背风坡不对称度 |
| `rift_axis_modulation` | 0.525 | 0 – 1 | 裂谷宽度沿线调制跨度（σ × [1−m, 1+m]） |
| `rift_meander_km` | 80 | 0 – 200 | 裂谷轴线侧向蜿蜒（±km，0=贴边界） |
| `orogen_meander_km` | 70 | 0 – 200 | 汇聚带剖面中心侧移（±km，0=贴边界） |
| `noise_amplitude_land_m` | 900 | 200 – 1500 | 细节噪声振幅（陆地） |
| `noise_amplitude_ocean_m` | 450 | 200 – 1000 | 细节噪声振幅（海洋） |
| `regional_noise_amplitude_land_m` | 1800 | 500 – 3000 | 区域噪声振幅（陆地） |
| `regional_noise_amplitude_ocean_m` | 1200 | 500 – 2000 | 区域噪声振幅（海洋） |
| `noise_scale` | 2.0 | 0.5 – 5.0 | 细节噪声基础频率 |
| `regional_noise_scale` | 0.5 | 0.5 – 5.0 | 区域噪声基础频率 |
| `noise_octaves` | 6 | 3 – 8 | fBm octave 数 |
| `noise_persistence` | 0.5 | 0.3 – 0.7 | fBm 振幅衰减率 |
| `noise_lacunarity` | 2.0 | 1.5 – 3.0 | fBm 频率增长率 |
| `noise_anisotropy` | 0.3 | 0 – 1 | 各向异性噪声强度 |
| `plate_elevation_spread_m` | 1500 | 500 – 3000 | per-plate 均匀偏移（已知年龄的洋底不加） |
| `continental_undulation_m` | 600 | 200 – 1500 | 地幔流场之外的大陆长波起伏 |
| `interior_lowland_enabled` | true | — | 内部低地开关 |
| `interior_lowland_depth_m` | 600 | 200 – 1200 | 内部低地下压量 |
| `interior_lowland_distance_scale_km` | 1500 | 500 – 3000 | 下压 0→满深距离 |
| `interior_lowland_floor_m` | 0 | 0 – 200 | 下压后离海平面最低高度 |
| `deposition_enabled` | true | — | 沉积填充开关 |
| `lake_fraction` | 0.2 | 0 – 1 | 留作外流湖的盆地比例 |
| `lake_depth_m` | 50 | 10 – 400 | 湖面低于溢流点深度 |

> **noise_scale 与物理波长的换算**：OpenSimplex 在单位球面 (x,y,z) 上采样，
> 特征波长 ≈ **R / scale**（R = 行星半径，nacrea = 6817 km）：
> scale 0.5 → ~13,600 km（全球级）；2.0 → ~3,400 km（大陆级）；
> 3.0 → ~2,300 km（板块级）；5.0 → ~1,400 km（区域级）。


---

## 8. 海平面与水系统

> 本章机制横跨多个相位：海陆分类（`water_class`）在 5/8 地形合成末尾写入，封闭盆地湖泊
> 在冰盖之前标记（§9），极地冰盖在 7/8 独立相位追加，大内流湖升级在 8/8 导出开头执行（见 §2）。

### 海平面设定

海平面可由以下三种方式确定：

1. **绝对值**：`sea_level_m = 0.0`（默认，与地球一致）
2. **水量约束**：给定水圈总水量（kg），迭代求解使海洋体积匹配的海平面
3. **覆盖率目标**：给定目标海陆比（如 70% 海洋），迭代求解

```python
def compute_sea_level(
    elevation: np.ndarray,
    areas: np.ndarray,            # (N,) cell areas in km²
    mode: str = "absolute",
    target_water_fraction: float = 0.70,
    sea_level_m: float = 0.0,
) -> float:
    """Determine sea level.

    For 'target' mode, binary search for the elevation that gives
    the desired ocean area fraction.
    """
    if mode == "absolute":
        return sea_level_m

    # Binary search
    lo, hi = elevation.min(), elevation.max()
    for _ in range(50):  # sufficient for ~15 decimal digits
        mid = (lo + hi) / 2
        ocean_mask = elevation < mid
        ocean_area = areas[ocean_mask].sum()
        total_area = areas.sum()
        frac = ocean_area / total_area

        if frac < target_water_fraction:
            lo = mid
        else:
            hi = mid

    return (lo + hi) / 2
```

### 陆地/海洋分类（water_class）

陆地/海洋判定不是裸 `elevation >= sea_level` 符号测试（会把吐鲁番等低于海平面的干盆地
误判为海），而是**海洋连通性 flood-fill**（`water_bodies.compute_land_mask`）：

- 把 `elevation <= sea_level` 的水体 cell 用邻接 BFS 聚类成连通盆地；
- **全球海洋 = 最大的连通盆地** → ocean，其余（出露陆地 + 闭合内流盆地/内陆湖）→ land。

这是**地质属性**（高程 + 海平面 + 连通性），在**地形管线合成后**写入每个 cell 的
`water_class`（`"ocean"`/`"land"`，`terrain_pipeline.py`），气候引擎和前端直接读该字段，
不再各自重复判据。真实地球由 GSHHG 水掩膜导入（`import_earth_watermask.py`），生成世界
走连通性 flood-fill——两条路径在地质层统一出 `water_class`。

### 大陆架检测

大陆架是大陆边缘的浅水区域（水深 < 200m），生态和文明意义重大：

```python
def detect_continental_shelf(
    is_land: np.ndarray,
    water_depth: np.ndarray,
    mesh: CVTMesh,
    shelf_depth_m: float = 200.0,
) -> np.ndarray:
    """Detect continental shelf nodes.

    Shelf = ocean nodes that are:
    1. Shallow (< shelf_depth_m)
    2. Adjacent to land (BFS distance ≤ 2 hops)

    Returns:
        (N,) boolean mask.
    """
    # Find shallow ocean
    shallow = (water_depth > 0) & (water_depth <= shelf_depth_m)

    # Find nodes adjacent to land
    near_land = np.zeros(mesh.num_nodes, dtype=bool)
    for i in range(mesh.num_nodes):
        if is_land[i]:
            for n in mesh.adjacency[i]:
                near_land[n] = True

    return shallow & near_land
```

### 极区海陆配置

参考 Gleba 设计决策：极区可以是冰盖覆盖的海洋（如地球北极）或冰原覆盖的大陆
（如地球南极/南极洲）。这影响洋流模式和气候。

```python
def check_polar_configuration(
    is_land: np.ndarray,
    nodes_xyz: np.ndarray,
) -> dict:
    """Check if poles are land or ocean.

    Important for:
    - Ocean circulation (Arctic vs Antarctic patterns differ)
    - Ice sheet dynamics (land-based ice vs sea ice)
    - Climate modeling (polar amplification)
    """
    north_pole = array([0, 1, 0])
    south_pole = array([0, -1, 0])

    # Find nearest node to each pole
    north_idx = np.argmax(nodes_xyz @ north_pole)
    south_idx = np.argmax(nodes_xyz @ south_pole)

    return {
        "north_pole_is_land": bool(is_land[north_idx]),
        "south_pole_is_land": bool(is_land[south_idx]),
        "north_pole_node": north_idx,
        "south_pole_node": south_idx,
    }
```

### 极地冰盖（7/8 追加相位，`ice_sheets.py`）

极地冰盖在海平面校准、地理钉扎、均衡压缩、平滑与封闭盆地湖泊标记全部完成**之后**追加
（`apply_polar_ice_sheets`，`ice_sheets.py:168`）：冰只堆叠在陆地 cell 上，海平面
维持校准值不动，**海岸线格局不受影响**。
每个 cell 的 `ice_thickness_m` 字段记录冰厚，受载基岩高程为 `elevation − ice_thickness_m`。冰载荷按局地 Airy
均衡压低基岩 `ICE_LOAD_DEPRESSION` = ρ_i/ρ_m ≈ 0.28 倍冰厚（技术债 45），冰面 = 无冰基岩 + 0.72·冰厚；重跑幂等
（先剥旧冰并补回下沉量，再重算，不会重复叠加或重复下压）。
机制分三段：

1. **日照门（无量纲）**：cell 的年平均大气顶（TOA）日照低于本世界赤道值的
   `ice_sheet_insolation_fraction`（0.50）即具备成冰资格——经典的米兰科维奇日照
   控制。年平均由逐日平均日照（Hartmann 2016 式 3.7，与气候层
   `climate_seasonality` 同一实现）对赤纬周期取样平均；太阳常数
   S₀ = 1361·L/d² 由恒星光度与轨道距离解析。门的穿越纬度因此跟随黄赤交角与
   恒星通量走（0.50 在地球 ≈67°；在 ε=14.9° 极区更暗的 nacrea ≈62°），
   换星无需调参。
2. **海陆分域（南北不对称的来源）**：地球上北极圈陆地是苔原而南极承大陆穹丘，
   差异是地理的（北冰洋加热沿岸）而非天文的。以到最近海洋的测地距离
   （多源 Dijkstra，`_distance_to_sea`）复现该机制：距海超过
   `ice_maritime_distance_km`（700 km）的大陆内部建完整穹丘；门内近海陆地只在
   雪线（`ice_cap_snowline_m`）以上长局部冰帽（加拿大北极 / 斯瓦尔巴式，上限
   `ice_cap_max_m`）。地球参照：苔原海岸距海 < ~500 km，Dome A 内陆 ~1200 km。
   邻接边的球面角距由 `_edge_angles` 计算，采用 `atan2(|a×b|, a·b)`。
   向量的长度与方向分别处理，导出坐标的小数截断保持同一角距定义；
   边长以弧度进入图，再乘行星半径得到物理距离。
3. **穹丘剖面（完美塑性 Vialov）**：冰厚 h(x) = √(2·τ_d·x/(ρ_i·g))，x 为到冰缘
   的测地距离（穹丘子图内从边界 cell 多源 Dijkstra；子图隔离保证冰只在陆地上
   传播、绝不穿过海洋）。驱动应力 τ_d = 40 kPa（观测冰盖范围 50–100 kPa，
   Cuffey & Paterson 2010），世界重力直接进入——重力更大的世界冰更薄。nacrea
   北极核心（≥77°N）冰面均值 ~2320 m、峰值 ~4856 m（南极 Bedmap2 地面冰均值
   ~2048 m，Dome A 4093 m）；南半球暮光大陆全境距海 < 700 km，只出冰帽
   （≤500 m，斯瓦尔巴式景观）。

| 参数 | 默认值 | 物理含义 |
|------|--------|----------|
| `ice_sheet_enabled` | true | 相位开关 |
| `ice_sheet_insolation_fraction` | 0.50 | 日照门无量纲阈值 q̄(lat)/q̄(eq) |
| `ice_sheet_driving_stress_kpa` | 40 | 完美塑性驱动应力 τ_d |
| `ice_maritime_distance_km` | 700 | 穹丘 / 冰帽分域的距海阈值 |
| `ice_cap_snowline_m` | 1200 | 冰帽雪线（基岩高程门槛） |
| `ice_cap_max_m` | 500 | 冰帽厚度上限 |

**认识论分类与限制**：日照门 + 穹丘剖面 = 近似推导；雪线 / 冰帽上限 / 距海阈值 =
观测拟合（地球北极岸类比）。已知限制：门只看热量——假定极地积雪充足（寒冷极区
在 Myr 尺度即使低降水也持续积累，参照南极），海洋热量输送只通过距海代理进入，
极向热输送极端强的世界可能过冰；气候层交叉校验：冰 cell 年均温应 < 0 °C。
下游衔接：气候层的高程递减率直接吃含冰面的 `elevation`，冰原表面自然得到更冷的
气候（物理正确的反馈）。物理推导与文献全文见
[knowledge/geology/ice_sheets.md](../../knowledge/geology/ice_sheets.md)。


---

## 9. 封闭盆地湖泊

> 全球 200k 网格上不做汇流与河网：平均 cell 约 51 km，真实河谷（5–50 km 宽）全部是
> 亚网格尺度，在这个分辨率上计算的流向与河道只是网格伪迹。渲染用的汇流、河流与湖泊
> 在高分辨率画布链上计算，见 [canvas-chain.md](canvas-chain.md)；画布链不读取
> 网格上的任何水文字段。全球网格只保留下面两类湖泊标记，它们写入 `VoronoiCell.is_lake`，
> 供气候、生态、文明与海陆划分读取。

### 9.1 沉积填充留下的湖

地形合成的沉积填充（`_apply_deposition_fill`，§7.3）用 `priority_flood_fill`
（`hydrology.py:25`，Barnes et al. 2014 的优先洪泛，O(N log N)）求每个 cell 的溢流
高程：从海洋 cell 出发按高程用最小堆向内扩张，把每个洼地抬到它通往海洋的最低出口。
被内部低地钳制过的盆地大多填到溢流高程；其中一部分大盆地（至少 20 格，比例由
`lake_fraction` 控制）只填到溢流高程以下 `lake_depth_m`，并被标记为 `is_lake`。

### 9.2 低于海平面的闭合盆地

气候相位之后、冰盖相位之前，管线调用 `mark_closed_basin_lakes(mesh, sea_level_m)`
（`hydrology.py:120`，调用点 `terrain_pipeline.py:634`）。它委托 `detect_closed_basins`
（`hydrology.py:68`）对低于海平面的 cell 做连通分量划分：最大的分量视为全球海洋，
其余低于海平面的分量是没有出海口的内陆海或盐湖，这些 cell 被标记为 `is_lake`。
沉积填充已经标记的湖泊保持不变。这一判据假设世界有一个占主导的全球海洋；在陆地
占绝对优势、没有全球海洋的世界上，最大分量本身可能是湖泊，函数不对此做特殊处理。

标记在地形表面上进行，因此先于冰盖堆叠。导出相位开头的
`upgrade_large_endorheic_lakes` 读取这些标记，把面积不小于 6×10⁴ km² 且大部分由湖泊
cell 组成的封闭水体升级为 `water_class` 为 "ocean" 的类海水体（§8）。

### 9.3 流水侵蚀（为什么没有）

200k 地质层不做流水侵蚀（stream power 下切与坡面扩散），也不做沉积物搬运。尺度理由
与不做汇流相同：在 51 km 网格上，流水侵蚀只会产生单 cell 宽的人工沟壑；而且
detachment-limited 模型没有输沙极限，会过度夷平或造出深谷（任何不少于 1 Myr 的时长、
任何合理的 K₀ 下，干流都会直接下切到基准面，参数无解）。河谷雕刻归管线最后一步的
Gaea 局地高清精修（米级，§10），大陆内部低地由地形合成的「内部低地」机制解决，而不是
靠侵蚀。详见 `docs/knowledge/geology/hydrology.md` 与 `competitor-analysis.md` §4.2。


---

## 10. 导出与可视化

### 10.1 等距圆柱投影导出

CVT cell 数据经**单位球 cKDTree 最近邻映射**栅格化到规则经纬度网格：先由
`export_cell_index_grid` 把每个目标像素映射到角距离最近的 cell（`build_export_tree`
对 cell 质心 3D 坐标建树一次，多字段导出时复用），再由 `export_equirectangular`
按 cell 索引查表取值。逐 cell 常值映射而非连续插值——保留 cell 边界，与前端
烘焙图层（`layerBakes.ts` 的 cell-id map）同一语义。

```python
def export_equirectangular(
    mesh: CVTMesh,
    width: int = 4096,
    height: int = 2048,
    field: str = "elevation",
    tree: cKDTree | None = None,
) -> np.ndarray:
    indices = export_cell_index_grid(mesh, width, height, tree=tree)
    cell_values = np.array([getattr(c, field, 0.0) for c in mesh.cells])
    return cell_values[indices]
```

多字段批量导出走 `export_multiple_fields`（共享同一棵 KD-tree）；
`export_climate_layers` 导出气候栅格图层。

**16-bit PNG 导出**（`export_elevation_png`）：`[min_m, max_m]`（默认 −11000…9000 m）
线性归一化到 `[0, 65535]`，uint16 数组直接交给 Pillow 的 `I;16` 模式。
编解码的可逆实现在 `elevation_codec.py`（`encode_elevation` / `decode_elevation`）。

### 10.2 投影支持

后端导出固定为**等距圆柱投影**（`MapProjection` 枚举仅 `EQUIRECTANGULAR`）——
管线产物与导入/导出工作流的统一交换格式。前端查看器同样以等距圆柱渲染
（2D 地图页与 3D 球面视图共用同一套烘焙纹理）。

### 10.3 前端可视化

Three.js 渲染使用 CVT 网格的直接映射：

```
前端渲染架构:
┌────────────────────────────────────────────┐
│  CVT Mesh (Three.js BufferGeometry)         │
│  • 节点 → 球面顶点                          │
│  • Voronoi 邻接 → 三角化 faces              │
│  • elevation → 顶点颜色/位移                │
│  • climate/biome → texture overlay          │
├────────────────────────────────────────────┤
│  SVG Overlay (2D projection)                │
│  • 板块边界 polyline                        │
│  • 城市/标记 point                          │
│  • 等值线 contour                           │
└────────────────────────────────────────────┘
```

### 10.4 与 dreamulator 集成

CVT 管线输出直接对接现有 `MapManager` 和 `MapLayerRegistry`：

```python
# 创建/更新地图
manager = MapManager(world_dir)
manager.create_map(
    planet_id="nacrea",
    source="cvt_pipeline",
    cvt_mesh=cvt_result,
    layers={
        "elevation": elevation_data,
        "temperature": temperature_data,
        "precipitation": precipitation_data,
        "biomes": biome_data,
    },
)

# 注册图层
registry = MapLayerRegistry(planet_id="nacrea")
registry.raster_layers["elevation"] = RasterLayerMeta(
    layer_type=MapLayerType.ELEVATION,
    source="engine-derived",
    file_path="rasters/elevation.png",
    resolution=(4096, 2048),
    depends_on=[],
)
```

**分支系统集成**：

```
世界分支 → CVT 管线参数差异:
├── base (默认)
│   └── seed=42, num_plates=20, sea_level=0
├── branch:pangea
│   └── seed=42, num_plates=5 (超大陆), sea_level=+50m
└── branch:icehouse
    └── seed=42, num_plates=20, sea_level=-120m (冰期)
```

每个分支只需重跑受影响的阶段（如改海平面只需重跑 Phase 5+），
而非重新生成整个地形。


---

## 11. 数据模型

管线数据模型全部在 `src/dreamulator/map/models.py`，按「cell → 网格 → 板块 → 地图元数据」
四层组织：

| 模型 | 职责 | 关键字段 |
|------|------|---------|
| `VoronoiCell` | 单个 CVT cell（管线一等公民，全部物理量挂在 cell 上） | `id`、`lon/lat`、`x/y/z`（单位球）、`area_km2`、`elevation`（绝对米）、`crust_type`、`plate_id`、`boundary_type`、`convergence_rate_cm_yr`、`cumulative_convergence_km` / `cumulative_divergence_km`（构造演化累积量，驱动造山带/裂谷宽度）、`distance_to_boundary_km`（无边界网格序列化为 null），气候/水文/生态字段（`temperature_C`、`precipitation_mm`、`koppen_class`、`is_lake`、`biome` 等）由各层引擎后填 |
| `CVTMesh` | 网格顶层容器（管线的持久化输出） | `seed`、`num_cells`、`lloyd_iterations`、`cells`、`adjacency`（cell_id → 邻接表）、`vertices` / `regions`（SphericalVoronoi 顶点与逐 cell 多边形，供渲染与面积计算） |
| `TectonicPlate` | 构造板块 | `id`、`name`、`type`、`cell_ids`、`euler_pole`（欧拉极）、`growth_speed_multiplier` |
| `EulerPole` | 板块运动学：v(P) = ω × P | 单位向量旋转轴 + `omega_rad_yr` |
| `MapMetadata` | `maps/<planet_id>/map.yaml` 元数据 | `planet_id`、`projection`（仅 `EQUIRECTANGULAR`）、`width/height`、`elevation_min_m/max_m`、`sea_level_m`、`voronoi_seed`、`voronoi_num_cells` |
| `VoronoiNetwork` | 旧栅格时代网格模型 | 保留以兼容既有数据文件，新管线一律用 `CVTMesh` |

**图层标识**（`MapLayerType`）：栅格层 `ELEVATION`（可编辑）、
`TERRAIN` / `TEMPERATURE` / `PRECIPITATION` / `BIOMES` / `PLATES_RASTER` / `BOUNDARIES`
（引擎派生）；矢量层 `PLATES` / `PROVINCES` / `FEATURES` / `CVT_MESH`。
图层依赖追踪见 `MapLayerRegistry`（`manager.py`）。

**模块布局**（`src/dreamulator/map/`）：`cvt_mesh.py`（Fibonacci + Lloyd + 网格构建）、
`plate_generator.py`（种子选取 + Cortial 2019 剖分 + 地壳分配 + 欧拉极）、
`boundary_detector.py`（边界检测/分类/链追踪）、`terrain_synthesizer.py`（地形合成）、
`tectonic_simulator.py`（构造时间演化，§5）、`hydrology.py`（填洼与封闭盆地湖泊，§9）、
`export.py`（栅格导出）、`elevation_codec.py`（高度图 PNG 编解码）、
`climate_simulator.py`（气候，见 climate-pipeline.md）、`manager.py`（地图 CRUD +
分支继承 + 图层注册）。


---

## 12. 性能

当前基线：nacrea（200k 胞、构造 ×50）全量构建 **~391s**（geological 238s + climate 147s +
ecology 5s；`build_profile.json` 逐阶段计时）。地质段内 tectonics（50 步演化 + 加权重采样）
~105s 占主导，其余为 terrain ~44s / mesh ~33s / export ~27s / plates ~13s。
噪声内核为 **Numba JIT**（`noise_kernels.py`，`@njit(parallel=True)`；`opensimplex` 的
`noise3array` 是纯 Python 循环，不用）。逐操作复杂度表、优化记录与基准工作流见
[profiling.md](../profiling.md) 与
[performance-optimizations.md](../performance-optimizations.md)；1M 节点扩展（自适应分辨率 /
C 扩展 / GPU / 分块 / 增量 LOD）为远期方案，见 [roadmap.md](../roadmap.md)。

### 前端渲染性能

10 万节点的 CVT 网格在前端渲染时面临两大挑战：

| 问题 | 根因 | 解决方案 | 效果 |
|------|------|---------|------|
| hover 延迟 ~500ms | SVG hit-test 为每个 cell 创建不可见 `<polygon>` DOM 节点，数千个节点导致浏览器 hit-test 缓慢 | **KD-tree 数学命中测试**：3D 笛卡尔坐标构建 KD 树，`mousemove` 时投影逆变换 → 3D 坐标 → `O(log n)` 最近邻查询 | hover 延迟 ~5ms |
| 点击 Voronoi 网格后浏览器冻结 | SVG 同时渲染 10 万个 polygon DOM 节点 | **删除 Voronoi 网格显示选项**；SVG overlay 仅渲染 hover/select 的 1-2 个高亮 polygon | DOM 节点降至个位数 |

#### KD-tree 命中测试架构

```
mousemove 事件
    ↓
requestAnimationFrame 节流 (每帧最多一次)
    ↓
投影逆变换: screen (px, py) → geographic (lon, lat)
    ↓
球面坐标转换: (lon, lat) → 3D Cartesian (x, y, z)
    ↓
KD-tree nearest(x, y, z) → cell ID    [O(log n)]
    ↓
onCellHover(cellId) → React 状态更新 → SVG 高亮 1 个 polygon
```

**关键设计决策：**
- 使用 3D 笛卡尔坐标（而非 lon/lat）构建 KD-tree，避免 ±180° 经度环绕问题
- `requestAnimationFrame` 节流确保每帧最多处理一次鼠标事件，避免事件堆积
- SVG overlay 设为 `pointer-events: none`，所有交互由 MapViewer 容器的 `onMouseMove` / `onClick` 处理
- 视觉反馈（hover 高亮、select 高亮）仍通过 SVG polygon 渲染，但仅 1-2 个节点，无性能问题

#### Cell-ID 贴图预计算 + 调色板查找

板块/边界类型的着色需要为每个像素确定所属的 CVT cell。直接方案是每像素查询 KD-tree（O(log n)），但在 4096×2048 纹理上意味着 ~800 万次查询，导致切换图层模式时卡顿 5-10 秒。

优化方案：**预计算 cell-ID 贴图**，将几何查询与着色分离。

```
┌─────────────────────────────────────────────────┐
│  一次性计算（cvtMesh/dimensions 变化时触发）       │
│                                                   │
│  每像素 → (lon,lat) → 3D → KD-tree → cell ID     │
│  存入 cellIdMap: Uint32Array[width × height]      │
│  耗时: ~5-10s（4096×2048 × O(log 100K)）         │
├─────────────────────────────────────────────────┤
│  每次切换图层模式（colorMode 变化时触发）           │
│                                                   │
│  构建调色板: cell_id → packed RGB                  │
│  每像素 → cellIdMap[pixel] → palette[cell_id]     │
│  耗时: <0.5s（4096×2048 × O(1) 数组查找）        │
└─────────────────────────────────────────────────┘
```

**性能提升：**

| 操作 | 优化前 | 优化后 | 提升 |
|------|--------|--------|------|
| 首次加载 | ~5-10s（KD-tree 查询） | ~5-10s（同） | — |
| 切换板块/边界模式 | ~5-10s（重新 KD-tree） | **<0.5s**（调色板查找） | **10-20×** |
| 切换投影 | ~5-10s | ~5-10s（同） | — |
| 平移/缩放 | <16ms | <16ms（无纹理操作） | — |

**设计模式参考：**

此方案遵循游戏引擎和 GIS 中广泛使用的 **调色板索引纹理（palette-indexed texture）** 模式：

- **id Software**（Doom/Quake）：预计算光照贴图（lightmap）按表面 ID 索引，渲染时通过查找表着色
- **Unreal Engine**：虚拟纹理（Virtual Texturing）使用间接表（indirection table）将 UV 映射到物理页
- **Mapbox GL JS**：瓦片级要素 ID 纹理（feature-ID texture）用于拾取和高亮，避免重新遍历几何体
- **QGIS**：栅格像元值图 + 分类渲染器（categorized renderer），像元值 → 调色板颜色
- ** deferred rendering**：G-buffer ID 通道——几何体渲染一次到 ID 缓冲区，后续着色通道通过查找表应用材质

共同原理：**几何遍历（昂贵）与着色查找（廉价）分离**。cell-ID 贴图等价于 G-buffer 中的 object-ID 通道。

**缓存失效规则：**
- `cellIdMap` 仅依赖 `(cvtMesh, width, height)`
- 与 `colorMode`、`projection`、`elevation` 数据无关
- 因此切换图层模式时复用已缓存的 cellIdMap

**实现文件：**
- `frontend/src/components/map/utils/kdtree.ts` — 3D KD-tree（build O(n log n), query O(log n)）
- `frontend/src/viewers/map/useCellIdMap.ts` — cell-ID 贴图预计算 hook（useMemo 缓存）
- `frontend/src/viewers/map/TerrainPlane.tsx` — 调色板查找着色（cell-ID → packed RGB）
- `frontend/src/components/map/MapViewer.tsx` — 集成 KD-tree + rAF 节流 + cellIdMap 传递
- `frontend/src/components/map/MapSvgOverlay.tsx` — 纯视觉反馈（无事件处理）

#### GPU Fragment Shader 渲染

所有纹理生成操作（LUT 映射、山体阴影、水面变暗、叠加混合）均在 GPU fragment shader 中并行执行，取代了 CPU 侧 Canvas2D 逐像素循环。

**架构：**

```
elevation (Float32Array)  → DataTexture (R32F)       ┐
cellIdMap (Uint32Array)   → DataTexture (R32F, norm) ├→ fragment shader
LUT (Uint8Array, 256×1)   → DataTexture (RGBA)       │   (GPU 并行处理)
palette (Uint8Array, N×1) → DataTexture (RGBA)       ┘        ↓
                                                    ShaderMaterial
                                                    on PlaneGeometry
```

**Fragment shader 职责：**
- 采样 elevation DataTexture → 查 256-entry LUT → 基础颜色
- 梯度采样 → 法向量 → 方向光山体阴影（Sobel-like）
- 海平面以下 → 深度变暗
- 查 cell-ID DataTexture → 查 palette DataTexture → 叠加混合

**性能对比：**

| 操作 | CPU (Canvas2D) | GPU (ShaderMaterial) | 提升 |
|------|----------------|---------------------|------|
| 初始加载 | 5-10s（Canvas2D 循环） | **~50ms**（DataTexture 上传） | 100-200× |
| 切换图层模式 | 0.5s（CPU 调色板） | **~1ms**（更新 uniform） | 500× |
| 切换投影 | 5-10s（重采样） | ~50ms（重上传） | 100× |
| 平移/缩放 | <16ms | <1ms（无重计算） | — |

**降级策略：**
- WebGL 2 可用 → GPU 路径（ShaderMaterial，等距圆柱 UV 直接映射）
- WebGL 2 不可用 → 地图无法渲染（无 CPU 栅格回退）

**设计参考：**
- **CesiumJS**：高程瓦片作为纹理 + GLSL shader 渲染地形
- **VTK/ParaView**：传输函数纹理（1D LUT）用于体渲染着色
- **游戏模拟器**（RetroArch）：调色板索引渲染，每像素查调色板纹理
- **延迟渲染**（Deferred Shading）：G-buffer 数据纹理 → 光照 shader

**实现文件：**
- `frontend/src/viewers/map/useGPUTerrain.ts` — GPU terrain hook（ShaderMaterial + DataTexture）
- GLSL 顶点/片元着色器内嵌于 `useGPUTerrain.ts`


---

## 13. 已知限制与未实现设计余量

### 当前限制

1. **河谷雕刻非地质层职责**：51 km 网格上流水侵蚀只会产生单 cell 宽人工沟壑，
   故地质层不做流水侵蚀（§9.3）；河谷雕刻归 Gaea 局地高清精修（米级）。

2. **静态气候**：当前气候模型是稳态快照，不模拟气候的季节内变化或年际变率（ENSO 等）。

3. **无冰川模拟**：冰盖的生长/退缩/流动未建模。极地地区的气候和地形耦合
   需要冰川动力学。

4. **简化的洋流**：表面流近似 + 风驱动，缺少深层热盐环流
   （thermohaline circulation）。

5. **单球面假设**：不支持非球形天体（如小行星、扁球体）。

### 未实现设计余量

1. **全威尔逊循环补全**：当前时间演化（§5）只实现板块旋转平流 + 俯冲/碰撞/裂解/
   海沟弧；未实现部分——地壳属性元组（厚度/年龄/造山年龄）、克拉通稳定化、
   地幔长期冷却、潮汐应力衰减、洋中脊体积-海平面耦合。

2. **冰川引擎**：在极地和高海拔区域模拟冰川动力学，冰蚀地形（U 型谷、冰碛）。

3. **深层洋流**：实现温盐环流，影响全球热量分配和气候稳定性。

4. **生态演替**：植被不仅是气候的被动映射，还反馈影响气候（蒸腾、反照率）。

5. **文明互动**：河流改道、灌溉、采矿等文明行为改变地形/水文。

6. **多分辨率 LOD**：前端支持从全球视图（10K 节点）无缝缩放到区域视图（100K 节点）。

7. **GPU 加速**：使用 CuPy 或 PyTorch 将 fBm、BFS 等计算迁移到 GPU。


### 威尔逊循环四大过程（现状与未实现）

在固定 CVT 场中，威尔逊循环由相邻 cell 之间的**相对速度场**直接触发：

#### A. 洋壳创生（Divergence / Ridge Push）— 未实现

- **条件**：相对速度法向分量 $v_\perp > 0$（相互远离），两侧均为洋壳
- **设计**：`Crust_Type` = OCEANIC、`Age` 重置为 0、`Thickness` = $7 + 8 \cdot T_\text{mantle}$ km
  （受地幔温度调制）、地形叠加洋中脊剖面函数。
  当前实现中离散边界的地形剖面（洋中脊）由 §6 静态地形合成给出，演化阶段不追踪
  洋壳年龄，也不做洋壳创生/重置。

#### B. 俯冲消亡（Subduction / Slab Pull）— 已实现高程效应，未实现物质削减

- **条件**：$v_\perp < 0$，至少一侧为洋壳（较老/较重者俯冲）
- **已实现**：上覆板块一侧的抬升、火山弧与海岸山脉由 §7 地形合成的边界效应（累积汇聚量驱动）产生。
- **未实现**：老洋壳 `Thickness` 削减与物质转移（无厚度状态）、slab pull 对欧拉极的
  反馈（欧拉极在演化中固定）。

#### C. 大陆拼合（Continental Collision）— 已实现造山，未实现厚度叠加

- **条件**：$v_\perp < 0$，两侧均为陆壳
- **已实现**：累积汇聚量驱动造山带宽度（critical taper，§4.5），高程由 §7 地形合成给出。
- **未实现**：陆壳 `Thickness` 叠加（40km + 40km = 80km，无厚度状态）。

#### D. 板块裂解（Plate Rifting）— 已实现

- **已实现**（`_rift_plates`）：大板块更易裂解的 Poisson 概率事件
  （`rift_base_rate`，默认 0.01/步），将板块切割为 `rift_min_pieces`–数个子板块
  （Voronoi 细分）、分配独立欧拉极、冷却期防止碎片立即再裂解。
- **未实现**：裂解中心陆壳减薄并翻转为洋壳（红海模式——无厚度/年龄状态支撑）。

### 随时间变化的行星物理参数（全部未实现设计）

行星并非静态系统，而是随内热耗散不断"衰老"的热力学系统。以下四项是设计余量
（当前实现中 `T_mantle`、欧拉极、潮汐应力、海平面在演化全程固定）：

#### 地幔长期冷却（Secular Cooling）

```python
T_mantle *= 0.995  # 每时间步地幔温度衰减
# 效果：
#   - 洋壳厚度从早期 ~15km 降至晚期 ~7km
#   - 板块角速度 ω(t) 随黏滞度增加而衰减
omega_global *= 0.998
```

#### 克拉通稳定化（Craton Stabilization）

```python
if cell.orogeny_age > 1500:  # Myr 未经历造山
    cell.crust_type = CRATON
    # 克拉通绝对不可被裂解——解释了为何加拿大地盾历经数十亿年不灭
```

#### 潮汐应力衰减（Tidal Stress Decay）

```python
tide_stress = 1.0 / (1 + t / 1000)  # 随卫星远离而衰减
# 效果：早期板块碎裂频繁（类木卫二），晚期进入稳定构造期
rift_probability = (tension * tide_stress) - craton_resistance
```

#### 洋中脊体积与全球海平面

```python
mean_ocean_age = average(all_ocean_cells.age)
# 年轻 → 洋中脊活跃 → 体积膨胀 → 海平面上升（如白垩纪）
sea_level = base_sea_level + ridge_volume_factor / mean_ocean_age
```


---

## 附录 A: 数学公式参考

> 本附录公式已上浮至知识库，以下为指针清单。

| 条目 | 内容 | 上浮位置 |
|------|------|----------|
| A.1 Haversine 角距离 | 大圆距离公式 | [cvt_mesh.md](../../knowledge/geology/cvt_mesh.md) §角距离 |
| A.2 Fibonacci 球面格点 | 极角/方位角 + 笛卡尔坐标 | [cvt_mesh.md](../../knowledge/geology/cvt_mesh.md) §Fibonacci 球面螺旋 |
| A.3 欧拉极运动学 | v = ω × P、速度大小、相对速度与 v_n/v_t 分解 | [plate_tectonics.md](../../knowledge/geology/plate_tectonics.md) §欧拉极运动学 / §边界检测与分类 |
| A.4 fBm | octave 叠加公式与归一化 | [terrain_synthesis.md](../../knowledge/geology/terrain_synthesis.md) §3 fBm 噪声 |
| A.5 Köppen 气候阈值 | 五主群 + 亚型判据 | [koppen_classification.md](../../knowledge/climatology/koppen_classification.md) |
| A.7 球面多边形面积 | 球面角盈公式 | [cvt_mesh.md](../../knowledge/geology/cvt_mesh.md) §Cell 面积 |


---

## 附录 D: 论文解读 — Cortial et al. 2019 *Procedural Tectonic Planets*

> **引用**: Yann Cortial, Adrien Peytavie, Éric Galin, Éric Guérin.
> *Procedural Tectonic Planets*. Computer Graphics Forum (Eurographics 2019),
> Vol. 38, No. 2. DOI: [10.1111/cgf.13614](https://doi.org/10.1111/cgf.13614) ·
> [HAL 全文](https://hal.science/hal-02136820/) ·
> [视频](https://www.youtube.com/watch?v=GJQVl6Xld0w)
>
> 论文解读全文（原 D.1–D.15：论文定位、网格与地壳参数化、四大构造现象公式、
> 侵蚀/衰减 ε 常数、完整常数表、性能数据、已知局限，以及与 dreamulator 的
> 实现对照、板块裂解实现细节、自适应裂解率与研究谱系）已整体移入
> [knowledge/geology/cortial_2019_notes.md](../../knowledge/geology/cortial_2019_notes.md)。

