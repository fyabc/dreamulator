# 行星地形生成管线技术参考

> **状态**: 设计草案 · 2026-07-21

> **本文档是 [地图工作流指南](../../usage/map-workflow.md) 的技术参考**。工作流指南描述"怎么做"，本文档解释"为什么这么做"以及各阶段的算法细节。

本文档描述 dreamulator **地质层**生成管线的完整技术方案。
**球面质心 Voronoi 镶嵌（CVT Mesh）是一等公民数据，等距圆柱投影高度图是派生导出产物**。
全部模拟（构造、侵蚀、水文）在 CVT 不规则网格上完成，仅在最终可视化/导出阶段投影为栅格。

---

## 目录

1. [总体架构](#1-总体架构)
2. [阶段 1: 球面 CVT 网格生成](#2-阶段-1-球面-cvt-网格生成)
3. [阶段 2: 构造板块](#3-阶段-2-构造板块)
4. [阶段 3: 欧拉极与板块运动学](#4-阶段-3-欧拉极与板块运动学)
5. [阶段 4: 边界检测与分类](#5-阶段-4-边界检测与分类)
6. [阶段 5: 地形合成](#6-阶段-5-地形合成)
7. [阶段 6: 海平面与基础分类](#7-阶段-6-海平面与基础分类)
8. [阶段 7: 河流与水文](#8-阶段-7-河流与水文)
9. [阶段 8: 地表演化侵蚀](#9-阶段-8-地表演化侵蚀)
10. [阶段 9: 数据导出与可视化](#10-阶段-9-数据导出与可视化)
11. [数据模型变更](#11-数据模型变更)
12. [性能考量](#12-性能考量)
13. [已知限制与未来工作](#13-已知限制与未来工作)
14. [时间演化与威尔逊循环](#14-时间演化与威尔逊循环)
- [附录 A: 数学公式参考](#附录-a-数学公式参考)
- [附录 B: 现有代码复用清单](#附录-b-现有代码复用清单)
- [附录 C: 实施清单](#附录-c-实施清单)
- [附录 D: 论文解读 — Cortial et al. 2019 *Procedural Tectonic Planets*](#附录-d-论文解读--cortial-et-al-2019-procedural-tectonic-planets)

---

## 1. 总体架构

### 核心理念

**CVT 网格 = 行星表面的离散表示**。所有物理模拟、属性存储、空间查询都在这个不规则图上进行。
等距圆柱投影（equirectangular）高度图仅在以下场景生成：

- 前端 2D 地图可视化（Three.js / Canvas 渲染）
- 导出给 Gaea 进行局部精细化
- 与外部 GIS 工具互操作

### 数据流总览

地质层管线（9 阶段，均作用在 CVT 网格上）：

| 阶段 | 名称 | 输入 → 输出 |
|------|------|------------|
| 1 | 球面 CVT 网格生成 | Fibonacci 螺旋 → Lloyd 松弛 → SphericalVoronoi → `CVTMesh` |
| 2 | 构造板块 | Poisson-disc 种子 → Voronoi BFS（Cortial 2019）→ `plate_id` / `crust_type` |
| 3 | 欧拉极与板块运动学 | 旋转轴 + 角速度 → 速度场 `v = ω × P` |
| 4 | 边界检测与分类 | 邻接扫描 → 收敛/离散/转换边界 |
| 5 | 地形合成 | 双峰基底 + 边界效应 + 热点 + fBm → `elevation` |
| 6 | 海平面与基础分类 | 海平面校准 → 海陆掩膜 → 大陆架 |
| 7 | 河流与水文 | 最陡下降 → 流量累积 → 河网/湖泊/内流湖 |
| 8 | 地表演化侵蚀 | stream power + 坡面扩散（地貌降水代理强迫）→ `elevation` |
| 9 | 数据导出与可视化 | 等距圆柱投影 → PNG / Three.js / SVG |

下游（气候 → 生态 → 文明）与 Gaea 精细化不在此管线内，见
[world-generation-pipeline.md](world-generation-pipeline.md)。

### 关键架构决策

- **CVT 而非 HEALPix**: CVT 可以自然表示不规则边界（板块、河流），HEALPix 的固定层次结构
  不适合线性特征的追踪。但 CVT 的代价是邻接关系需要显式存储。
- **fBm 在 3D 球面采样**: 避免 2D 投影的极点噪声畸变。每个 CVT 节点的噪声值由其 3D 坐标
  `(x, y, z)` 直接索引 Simplex noise。
- **板块 Cortial 2019 Voronoi 剖分**: 加权 Voronoi 重分区（替代早期洪水填充），
  产生自然的不规则板块边界（参考真实地球板块的非凸性）。
- **欧拉极运动学**: 板块运动使用刚体旋转（`v = ω × P`），确保球面上的运动自洽性。
- **全球尺度流水侵蚀**: 用 stream power + 坡面扩散做层内 surface evolution 循环，
  以地貌降水代理为强迫（不读气候引擎，避免地质→气候→地质的 DAG 环）；Gaea 仍用于
  米级局部细节。

---

## 2. 阶段 1: 球面 CVT 网格生成

### 2.1 Fibonacci 球面螺旋

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

### 2.2 可选随机扰动

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

### 2.3 Lloyd 松弛

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

### 2.4 SphericalVoronoi 构建

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

### 2.5 分辨率与性能

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

## 3. 阶段 2: 构造板块

### 3.1 种子选取

在 CVT 网格上随机选取 ~20 个种子节点作为板块核心。

> **参考 Cortial 2019 §3**: 论文使用球面 Voronoi cell 作为板块，通过向测地距离
> 添加噪声来产生不规则的板块形状（`geodetic distance + noise warp`）。我们的
> Cortial 2019 Voronoi 剖分（§3.2）实现了类似的不规则性，且更容易控制板块大小分布。

```python
def select_plate_seeds(mesh: CVTMesh, num_plates: int, rng) -> list[int]:
    """Select plate seed nodes with minimum spacing constraint."""
    candidates = rng.choice(mesh.num_nodes, size=num_plates * 3, replace=False)
    seeds = [candidates[0]]

    min_dist = 2.0 * sqrt(4 * pi / mesh.num_nodes) * sqrt(num_plates / (4 * pi))
    # Greedy farthest-point sampling for better spacing
    for c in candidates[1:]:
        if len(seeds) >= num_plates:
            break
        # Check minimum distance to all existing seeds
        dists = angular_distance_xyz(mesh.nodes[c], mesh.nodes[seeds])
        if dists.min() > min_dist:
            seeds.append(c)

    # Fill remaining with random if greedy didn't find enough
    while len(seeds) < num_plates:
        seeds.append(int(rng.choice(mesh.num_nodes)))

    return seeds
```

### 3.2 球面 Voronoi 剖分（Cortial 2019）

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

### 3.3 地壳类型分配

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

### 3.4 手动板块指定

支持通过 YAML 配置文件覆盖自动生成的板块：

```yaml
# data/worlds/myworld/layers/geological/input/plates.yaml
plates:
  - id: plate_north continent
    name: "北大洲板块"
    seed_lat_deg: 45.0
    seed_lon_deg: -30.0
    speed: 1.2
    crust_type: continental

  - id: plate_pacific
    name: "大洋板块"
    seed_lat_deg: 0.0
    seed_lon_deg: 170.0
    speed: 1.8
    crust_type: oceanic

  # ... 更多板块
```

### 3.5 地理锚定（geography.yaml）

默认的地壳分配（§3.3）是**纯程序化**的——大陆落在哪里完全由纬度偏好 + fBm
噪声决定，作者无法控制。对于"样板世界"（如 nacrea），世界构建者往往已经在
设定文档里写死了海陆格局（哪个大陆在哪、多大的洋），需要让引擎**按设定生成**。

**业界先例**：Gleba 支持"自定义陆块概率图导入"来引导大陆生成；Azgaar 用
heightmap 模板/手绘高度图控制陆地。Dreamulator 的等价物是**机器可读的地理规格
→ 逐 cell 陆地偏置场 → 全局阈值**，实现在 `src/dreamulator/map/geography.py`。

#### 规格文件

`data/worlds/<world>/layers/geological/input/geography.yaml`（可选；缺省时管线
行为与 §3.3 完全一致）。由 `GeologicalEngine._load_config` 经
`load_geography_spec()` 载入并挂到 `config.geography`。

```yaml
version: 1
land_fraction_target: 0.28      # 缺省则用 config.target_land_fraction
hemisphere_land_bias: 0.10      # >0 北半球偏陆（按 sin(lat) 平滑加权）
reapply_after_tectonics: true   # 构造演化后重新锚定（见下）
features:
  - name: 世界岛
    kind: continent             # 语义标签：continent / archipelago / plateau /
                                #   ocean_basin / rift_sea / shallow_sea / isthmus
    lon: -90.0
    lat: 0.0
    radius_deg: 35.0            # 圆半径；拉长特征 = 半短轴（半宽）
    strength: 0.85              # + 陆地 … − 海洋；|strength|>1 用于"切开"大陆
    elongation: 1.6             # 半长轴/半短轴（≥1，1=圆）
    bearing_deg: 0.0            # 半长轴朝向（0=北，90=东）
    elevation_target_m: -120.0  # 可选：高程钉扎（相对校准海面 0 m；负=水深）
    pin_strength: 1.0           # 可选：钉扎信任度 0–1（核提供空间软边）
```

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

#### 地壳赋值（全局阈值）

有 spec 时，`apply_geography_crust()` 用**全局阈值**替代 §3.3 的"每板块随机
比例"：

```
score = anchor_weight · field + (1 − anchor_weight) · fBm
```

`anchor_weight`（`config.anchor_weight`，默认 0.6）混合锚定场与 fBm 纹理；
fBm 的 seed = `config.seed + 500`（确定性）。按 score 降序取前
`land_fraction_target × N` 个 cell 为 continental，其余 oceanic。这样：

- 命名大陆（正场强）稳定落在锚点；命名大洋（负场）被压到阈值以下。
- fBm 让海岸线保持分形、让弱场区（如前导点褶皱山系）叠加噪声产生复杂地形。
- 全局海陆比精确命中 `land_fraction_target`。

#### 注入点与构造漂移

- **plates 阶段**：`_generate_plates_impl` 检测到 `config.geography` 时改走
  `apply_geography_crust`（板块仍照常生成，供 tectonics/boundaries 使用，
  只有地壳被锚定）。
- **tectonics 阶段后**：板块运动会带着地壳漂移（crust 粘在 cell 上），大陆会
  离开锚点。若 `reapply_after_tectonics: true`，演化结束后用**同一 seed-确定场**
  重新锚定一次，大陆回到设定位置；而 tectonics 产生的边界/造山数据
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
（nacrea 裂谷核心 ~13%），它们拿 +850 m 双峰基准 + 板块偏移（±1500 m）直接
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
- **offset 下游假设**：前端色标/河流生成（TODO）按水面 0 m 假设；
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

### 3.6 与现有模型集成

新板块模型映射到现有 `TectonicPlate`（`src/dreamulator/map/models.py`）：

```
新模型                      现有 TectonicPlate
─────────────────          ─────────────────────
plate_id            →      id
plate_name          →      name
crust_type          →      type (PlateType enum)
cell_ids            →      cell_ids (CVT node IDs)
euler_pole[3]       →      (新增字段)
omega_rad_yr        →      (新增字段)
growth_speed_multiplier →  (新增字段)
```

`PlateVelocity(dx, dy)` 已移除，板块运动统一用 Euler pole 表示。

### 参数表

| 参数 | 默认值 | 范围 | 物理含义 |
|------|--------|------|----------|
| `num_plates` | 20 | 5 – 50 | 构造板块数量 |
| `plate_speed_range_cm_yr` | (1.0, 10.0) | (0.1, 5.0)–(5.0, 20.0) | 板块速度范围（最慢/最快） |
| `continental_fraction` | 0.35 | 0.1 – 0.8 | 大陆板块比例 |

---

## 4. 阶段 3: 欧拉极与板块运动学

### 4.1 欧拉极分配

每个板块的运动由一个**欧拉极**（Euler pole）描述——球面上的一个旋转轴；
在惯性参考系中板块绕该轴做刚体旋转。

> 运动学公式已上浮至
> [knowledge/geology/plate_tectonics.md](../../knowledge/geology/plate_tectonics.md)
> §欧拉极运动学：角速度换算 ω = v/R 与地球板块速度参考表、速度场
> v(P) = ω·(ê×P) 及其大小 |v| = ωR·sin α、边界相对速度与法向/切向分解、
> 无净旋转（no-net-rotation）参考系。

**实现要点**（`tectonic_simulator.py` / `plate_generator.py`）：

- **欧拉极分配**：每板块随机单位旋转轴（高斯采样后归一化），角速度由
  `plate_speed_range_cm_yr` 均匀采样后经 ω = v/R 换算。
- **速度场**：向量化叉积一次算出全部节点速度（单位球坐标 → 乘
  `radius_km × 1000` 得 m/yr）。
- **时间演化的 δt 自动缩放**（实现行为，见 §17 与
  `tectonic_simulator.py::_auto_compute_dt`）：
  `δt = 3 · √(4πR²/N) / v_max`——令最快板块每步移动 ~3 个 cell
  （100K cells 时 δt ≈ 2 My；`tectonic_dt_my > 0` 时显式覆盖）。

### 参数表

| 参数 | 默认值 | 范围 | 物理含义 |
|------|--------|------|----------|
| `plate_speed_range_cm_yr` | (1.0, 10.0) | (0.1, 5.0)–(5.0, 20.0) | 板块速度范围（最慢/最快） |

---

## 5. 阶段 4: 边界检测与分类

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
2. **相对速度分解**：先把 v_rel 投影到中点切平面（扣除径向分量），再沿
   边界法向分解；边界法向近似取 plate_A 质心 → plate_B 质心方向（投影到切平面）。
3. **分类**：按边界相对速度划分 convergent / divergent / transform / inactive，
   并按两侧地壳组合细化汇聚子类型。
4. **边界链追踪**：将共享节点的同类边界段贪心连成链（`BoundaryChain`），
   供山脉走向、海沟线等线性特征生成使用。

> **Cortial 2019 俯冲上隆公式**（详见
> [knowledge/geology/cortial_2019_notes.md](../../knowledge/geology/cortial_2019_notes.md) §D.4）：
> $u_j(p) = u_0 \cdot f(d) \cdot g(v) \cdot h(\tilde{z})$
> 其中 $u_0 = 0.6$ mm/y, $r_s = 1800$ km, $h(\tilde{z}) = \tilde{z}^2$。
> 我们的 §6 地形合成使用类似的高斯衰减函数，但简化为距离的指数衰减。
> 实现时间演化后（§17），应切换到 Cortial 的完整公式。

### 参数表

| 参数 | 默认值 | 范围 | 物理含义 |
|------|--------|------|----------|
| `boundary_influence_km` | 500.0 | 100 – 2000 | 边界效应影响半径 |

---

## 6. 阶段 5: 地形合成

节点高程 = 双峰基准 + 边界构造效应 + 热点隆起 + 区域 fBm + 细节 fBm × 内部调制
（+ 潮汐形变，仅潮汐锁定天体）。

> 地球物理依据与公式已上浮至
> [knowledge/geology/terrain_synthesis.md](../../knowledge/geology/terrain_synthesis.md)：
> 双峰高程分布依据（§1）、三类边界剖面公式与速率因子汇总表（§2）、
> 距边界粗糙度调制（§2）、fBm octave 物理尺度表（§3）、热点/地幔柱高斯隆起
> 与高程合成叠加式（§6），以及内陆古造山带/山间盆地的地貌学依据（§4.3）。

### 6.1 合成流程（6 步）

**实现**：`terrain_synthesizer.py:_synthesize_asymmetric`（默认算法，
策略由 `terrain_algorithm` 选择；`cortial2019_gaussian` 为对称版）：

1. **基准高程**：按地壳类型双峰分配——continental `normal(850, 200)`、
   oceanic `normal(-3800, 500)`；每板块叠加均匀偏移 ±`plate_elevation_spread_m`
   （陆地取 0.4×）；叠加多尺度「动态地形」起伏 `_continental_undulation`
   （`continental_undulation_m`，默认 600 m，地幔对流类比 Flament et al. 2013）。
   若 `ocean_age_depth_enabled`，洋壳替换为年龄-深度剖面（见 §6.3）。
2. **非对称边界效应**：`_asymmetric_boundary_effects` 按边界类型叠加高斯剖面
   （σ 由 `boundary_influence_km`，振幅 × 速率因子 `min(|v_n|/10, 1)`，
   `mountain_asymmetry` 控制迎/背风坡不对称），叠加 **沿弧分段 fBm 调制**
   （~800 km 波长，隆起幅度 ∈ [−0.25, 1.35]）：高值段成主岛/山结，负值段沉降为
   弧间断陷海——汇聚带不再均匀缎带；`boundary_uplift_noise` 调制岛弧/洋脊。
3. **热点链**：`_generate_hotspots` 宽尺度高斯隆起 + 可选中央破火山口凹陷。
4. **区域噪声**：低频 fBm（`regional_noise_scale`，陆/海不同振幅
   `regional_noise_amplitude_land_m` / `regional_noise_amplitude_ocean_m`）。
5. **细节噪声**：`_anisotropic_fbm`（3D Simplex 在节点 (x,y,z) 采样，无投影畸变；
   各向异性 `noise_anisotropy` 沿边界走向拉伸）；近边界 `interior_factor` 增强
   （1.2→1.5×，山体更崎岖）。
6. **合成**：`elevation = base + boundary + hotspot + regional + detail`。

> **边界平滑**（作用于分区，非高程）：最终分区多数投票 `_smooth_partition`
> （4 轮）+ 飞地合并 `_merge_plate_enclaves`，消除锯齿边界。per-plate 地壳下限
> `crust_plate_floor`（默认 0.10）避免整板近零陆壳；泄漏陆壳 `_relabel_leaked_crust`
> 在 base 前重标为洋壳（洒点岛屿只由岛弧/热点/钉扎涌现）。

### 6.2 内部地貌：古造山带、山间盆地与裂谷

板块内部（距边界 >600 km 的大陆区域）放置线性构造带（`_apply_interior_landforms`），
模拟古生代/中生代造山带残余（乌拉尔、阿巴拉契亚型）和裂谷臂。地貌学依据已上浮至
[knowledge/geology/terrain_synthesis.md](../../knowledge/geology/terrain_synthesis.md) §4.3。

- **沿走向调制**：每条 belt 用 1D simplex 噪声沿大圆弧采样，调制各段振幅
  （振幅 ∈ [base × 0.3, base × 1.7]），造山带呈高峰 + 鞍部而非均匀脊线；
  路径双频 meander（0.35+0.12 rad），宽度沿走向 0.55–1.45× 变化。
- **山间盆地**：沿走向噪声低于阈值时（`interior_basin_chance`）该段成为断陷盆地，
  深度上限 `interior_basin_depth_max_m`（部分盆底低于海平面）。
- **裂谷**：30% 概率/板块，独立线性凹陷（深 300–800 m，σ=40–100 km）。

| 参数 | 默认值 | 范围 | 含义 |
|------|--------|------|------|
| `interior_orogeny_count` | 2 | 0–5 | 基准 belt 数，随 inland cell 数缩放，硬上限 4 |
| `interior_height_variation` | 0.7 | 0–1 | 沿走向高度变化强度 |
| `interior_basin_chance` | 0.25 | 0–0.5 | 山间盆地出现概率 |
| `interior_basin_depth_max_m` | 600 | 100–1500 | 盆地最大沉降深度 |

### 6.3 洋底年龄-深度沉降（板块冷却模型）

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
| `ocean_spreading_rate_cm_yr` | 6.0 | 1–5 |
| `ocean_ridge_depth_m` | 2500 | ~2500 |
| `ocean_subsidence_coeff` | 350 | ~350 |
| `ocean_max_age_myr` | 100 | ~100 |
| `ocean_max_age_depth_m` | 5500 | ~5500 |

效果：均海深 3015→3687 m（对齐地球 3682 m）；浅水 0-500m 占比 14.8%→10.6%（地球 8%）。

### 6.4 后处理（顺序）

合成后按序执行（弧/造山带增加高程，架/平原必须最后，否则被覆盖）：

1. **海平面校准（倒水）**：二分查找使陆面比例 = `target_land_fraction`（§7）。
2. **岛弧** `_apply_island_arcs`：岛弧高度 + 隆起调制。
3. **内部地貌** `_apply_interior_landforms`（见 §6.2）。
4. **大陆架** `_apply_continental_shelf`（`shelf_width_km`）。
5. **沿海平原** `_apply_coastal_plain`（`coastal_plain_width_km`）。
6. **地理钉扎** `_apply_geography_pins`：钉扎 authored 高程（最后覆盖）。
7. **均衡尾部压缩**（`isostasy_enabled`）：只压缩超出物理上限的尾部，指数衰减保序：
   `compressed = limit + excess · exp(-5·excess/limit)`，不产生「平顶山/平底沟」。
   上限 `h_max ∝ 1/g`——nacrea g=10.28 → 陆极 ~8443 m、海沟 ~11550 m。
8. **拉普拉斯平滑** `_smooth_land_discontinuities`：均衡压缩只压超标 cell 会留下
   悬崖式跳跃，3 轮 30% 邻域均值混合（仅陆地）松弛为连续坡降：
   `elev_i = 0.7·elev_i + 0.3·mean(land_neighbors)`；>3000m 邻域跳跃 1446→137 cell。

### 6.5 参数表

| 参数 | 默认值 | 范围 | 物理含义 |
|------|--------|------|----------|
| `continental_elevation_m` | 850 | 400 – 1500 | 大陆基准高程 |
| `oceanic_elevation_m` | -3800 | -5000 – -2000 | 海底基准高程 |
| `convergent_uplift_m` | 4000 | 1000 – 5000 | 汇聚边界山脉振幅 |
| `divergent_depth_m` | 2000 | 500 – 2000 | 离散边界山脊振幅 |
| `boundary_influence_km` | 500 | 100 – 2000 | 边界效应影响半径 |
| `mountain_asymmetry` | 0.4 | 0 – 1 | 迎/背风坡不对称度 |
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
| `plate_elevation_spread_m` | 1500 | 500 – 3000 | per-plate 均匀偏移 |
| `continental_undulation_m` | 600 | 200 – 1500 | 大陆动态地形起伏 |

> **noise_scale 与物理波长的换算**：OpenSimplex 在单位球面 (x,y,z) 上采样，
> 特征波长 ≈ **R / scale**（R = 行星半径，nacrea = 6817 km）：
> scale 0.5 → ~13,600 km（全球级）；2.0 → ~3,400 km（大陆级）；
> 3.0 → ~2,300 km（板块级）；5.0 → ~1,400 km（区域级）。

---

## 7. 阶段 6: 海平面与基础分类

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

### 陆地/海洋分类

```python
def classify_land_ocean(
    elevation: np.ndarray,
    sea_level_m: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Classify nodes as land or ocean.

    Returns:
        (is_land, water_depth): boolean mask and depth in meters.
    """
    is_land = elevation >= sea_level_m
    water_depth = np.where(is_land, 0.0, sea_level_m - elevation)
    return is_land, water_depth
```

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

---

## 8. 阶段 7: 河流与水文

> 侵蚀落地后，本节是**侵蚀后地形**上的一次性水文学产品：洼地填平 → D8 流向 →
> 流量累积 → 河网提取，填入 `VoronoiCell.flow_direction / flow_accumulation /
> river_id / river_order`。侵蚀循环（§10）每次迭代内部复用同一套"洼地填平 +
> D8 + 累积"纯函数，与本节的最终提取共用实现，避免两套水文逻辑漂移。
> 物理公式与引用见 [knowledge/geology/hydrology.md](../../knowledge/geology/hydrology.md)。

### 8.0 洼地填平（前置）

CVT 地形合成会产出大量局部洼地（pit）：直接跑 D8 会在每个洼地得到一个 sink、
河网破碎、流量累积截断。先做 **priority-flood 填平**（Barnes et al. 2014，
O(N log N)）：

1. 从海洋 / 边界 cell 出发，用最小堆按高程向内扩张；
2. 每个陆 cell 的临时标高推到 `max(elevation, spill)`，保证至少有更低出口；
3. 填平只在**临时数组**上进行（供流向 / 累积 / 侵蚀循环使用），
   **不写回** `cell.elevation`——最终河网提取仍在真实（已侵蚀）地形上做；
4. 内流盆地（无通海出口）填平后仍保留其最低出口作为 sink（§8.5）。

### 8.1 流向确定

每个节点的流向是其**最陡下降方向**的邻居：

```python
def compute_flow_directions(
    mesh: CVTMesh,
    elevation_m: np.ndarray,
    is_land: np.ndarray,
) -> np.ndarray:
    """Determine flow direction for each node.

    Each node flows to its steepest-descent neighbor.
    Ocean nodes and local minima flow to -1 (sink).

    Returns:
        (N,) int array. flow_dir[i] = neighbor index, or -1 for sinks.
    """
    flow_dir = np.full(mesh.num_nodes, -1, dtype=np.int32)

    for i in range(mesh.num_nodes):
        if not is_land[i]:
            continue  # ocean = sink

        best_neighbor = -1
        best_gradient = 0.0

        for n in mesh.adjacency[i]:
            # Compute gradient: elevation drop / distance
            dist_km = angular_distance_xyz(mesh.nodes[i], mesh.nodes[n]) * mesh.radius_km
            if dist_km < 1e-6:
                continue
            gradient = (elevation_m[i] - elevation_m[n]) / dist_km

            if gradient > best_gradient:
                best_gradient = gradient
                best_neighbor = n

        flow_dir[i] = best_neighbor  # -1 if no downhill neighbor (local minimum)

    return flow_dir
```

### 8.2 汇水累积

通过拓扑排序（从源头到河口）计算每个节点的汇水面积：

```python
def compute_flow_accumulation(
    mesh: CVTMesh,
    flow_dir: np.ndarray,
    is_land: np.ndarray,
    areas: np.ndarray,
) -> np.ndarray:
    """Compute flow accumulation (upstream catchment area) per node.

    Algorithm:
    1. Compute in-degree for each node (how many neighbors flow into it)
    2. Topological sort: process nodes with in-degree 0 first (headwaters)
    3. Accumulate: each node passes its accumulation to its downstream neighbor

    Returns:
        (N,) accumulation in km².
    """
    accum = areas.copy()  # each node starts with its own area
    accum[~is_land] = 0   # ocean doesn't contribute

    # Compute in-degree
    in_degree = np.zeros(mesh.num_nodes, dtype=np.int32)
    for i in range(mesh.num_nodes):
        target = flow_dir[i]
        if target >= 0:
            in_degree[target] += 1

    # Topological sort (Kahn's algorithm)
    queue = deque()
    for i in range(mesh.num_nodes):
        if in_degree[i] == 0 and is_land[i]:
            queue.append(i)

    while queue:
        node = queue.popleft()
        target = flow_dir[node]
        if target >= 0:
            accum[target] += accum[node]
            in_degree[target] -= 1
            if in_degree[target] == 0:
                queue.append(target)

    return accum
```

### 8.3 河流分类

根据汇水面积对河流进行分级：

| 汇水面积 (km²) | 等级 | 描述 | 例子 |
|----------------|------|------|------|
| < 100 | 溪流 | 季节性小溪 | — |
| 100 – 1,000 | 小河 | 常年流水 | 小河 |
| 1,000 – 10,000 | 河流 | 中等河流 |  Thames |
| 10,000 – 100,000 | 大河 | 主要河流 | Rhine |
| > 100,000 | 巨河 | 大陆级河流 | Amazon, Nile |

```python
def classify_rivers(
    accum_km2: np.ndarray,
    flow_dir: np.ndarray,
    is_land: np.ndarray,
    thresholds: dict = None,
) -> np.ndarray:
    """Classify river segments by Strahler-like order based on accumulation.

    Returns:
        (N,) int array. 0 = no river, 1-5 = stream to mega-river.
    """
    if thresholds is None:
        thresholds = {1: 100, 2: 1000, 3: 10000, 4: 100000}

    river_order = np.zeros(len(accum_km2), dtype=np.int32)
    for order, threshold in sorted(thresholds.items()):
        river_order[accum_km2 >= threshold] = order

    return river_order
```

### 8.4 河流网络提取

从河口（海岸节点）逆流追踪到源头，生成 `MapFeature` 对象：

```python
def extract_river_network(
    mesh: CVTMesh,
    flow_dir: np.ndarray,
    accum_km2: np.ndarray,
    is_land: np.ndarray,
    min_accum_km2: float = 1000.0,
) -> list[MapFeature]:
    """Trace river networks from mouth to headwaters.

    1. Find river mouths: land nodes flowing into ocean (flow_dir → ocean node)
    2. For each mouth, trace upstream following reverse flow direction
    3. At confluences, follow the branch with higher accumulation

    Returns:
        List of MapFeature objects (type=RIVER).
    """
    # Build reverse flow graph: who flows into each node?
    reverse_flow: dict[int, list[int]] = defaultdict(list)
    for i in range(mesh.num_nodes):
        target = flow_dir[i]
        if target >= 0:
            reverse_flow[target].append(i)

    # Find river mouths
    mouths = []
    for i in range(mesh.num_nodes):
        if is_land[i] and flow_dir[i] >= 0 and not is_land[flow_dir[i]]:
            if accum_km2[i] >= min_accum_km2:
                mouths.append(i)

    # Trace each river
    rivers = []
    for mouth_idx, mouth in enumerate(mouths):
        path = trace_upstream(mouth, reverse_flow, accum_km2, min_accum_km2)

        # Convert node path to (lon, lat) coordinates
        coords = []
        for node_id in path:
            lat, lon = xyz_to_lat_lon(
                mesh.nodes[node_id, 0],
                mesh.nodes[node_id, 1],
                mesh.nodes[node_id, 2],
            )
            coords.append((degrees(lon), degrees(lat)))

        rivers.append(MapFeature(
            id=f"river_{mouth_idx:04d}",
            name=f"River {mouth_idx}",
            type=FeatureType.RIVER,
            coordinates=coords,
        ))

    return rivers

def trace_upstream(
    mouth: int,
    reverse_flow: dict,
    accum: np.ndarray,
    min_accum: float,
) -> list[int]:
    """Trace upstream from mouth, always following the largest tributary."""
    path = [mouth]
    current = mouth

    while True:
        upstream = reverse_flow.get(current, [])
        # Filter to nodes above accumulation threshold
        valid = [u for u in upstream if accum[u] >= min_accum]
        if not valid:
            break
        # Follow the branch with highest accumulation
        current = max(valid, key=lambda u: accum[u])
        path.append(current)

    return path
```

### 8.5 湖泊与内流盆地

局部最小值（没有下坡邻居的陆地节点）形成湖泊或内流盆地。参考 Gleba 的
endorheic basins 设计——内流盆地（如里海、死海）是重要的地理特征。

```python
def detect_lakes_and_endorheic(
    mesh: CVTMesh,
    flow_dir: np.ndarray,
    elevation_m: np.ndarray,
    is_land: np.ndarray,
    precipitation: np.ndarray,
) -> tuple[list[Lake], list[EndorheicBasin]]:
    """Detect lakes (local minima) and endorheic basins.

    Lake: local minimum with positive water balance (precip > evap)
    Endorheic basin: local minimum with negative water balance
    (water accumulates to a level, then evaporates — like Dead Sea)

    Reference: Gleba endorheic basins — large inland drainage
    systems affect regional climate and civilization placement.

    Returns:
        (lakes, endorheic_basins)
    """
    # Find local minima on land
    sinks = np.where((flow_dir == -1) & is_land)[0]

    lakes = []
    endorheic = []

    for sink in sinks:
        # BFS to find the catchment basin
        basin = find_catchment(sink, flow_dir)
        basin_area_km2 = sum(mesh.areas[b]) for b in basin

        # Estimate water balance
        total_precip = sum(precipitation[b] * mesh.areas[b] for b in basin)
        # Simple evaporation estimate
        evap = 800 * basin_area_km2  # mm/yr × km² → volume

        if total_precip > evap:
            # Positive balance → lake fills to spill point
            lakes.append(Lake(
                sink_node=sink,
                basin_nodes=list(basin),
                area_km2=basin_area_km2,
                spill_elevation=elevation_m[sink],
            ))
        else:
            # Negative balance → endorheic (salt lake / dry basin)
            endorheic.append(EndorheicBasin(
                sink_node=sink,
                basin_nodes=list(basin),
                area_km2=basin_area_km2,
                water_deficit=evap - total_precip,
            ))

    return lakes, endorheic
```

### 8.6 输出字段

| `VoronoiCell` 字段 | 类型 | 说明 |
|---|---|---|
| `flow_direction` | `int \| None` | 下游邻居 id；`-1` = sink（海洋 / 内流盆出口）；海洋 cell 为 `None` |
| `flow_accumulation` | `float` | 上游汇水面积（km²，非 cell 数；由 `area_km2` 求和） |
| `river_id` | `str \| None` | 所属河流 id（`river_XXXX`），无河为 `None` |
| `river_order` | `int` | Strahler 级数（0 = 无河） |

### 8.7 河流矢量图层（features.json）与渲染

**提取**（`river_generator.extract_river_features`，管线 rivers 阶段末尾调用，
写入地图目录 `features.json`，`manager.get_features` / API / 静态导出直接消费）：

- **河道 cell**：`river_order >= 1`。order 阈值按 cell 面积缩放（§8.3
  `classify_rivers`），200k 网格下只画主干河网（陆域按汇水面积前 ~2–3%）——
  世界地图的河流密度。
- **折线追踪**：每个河道「源头」（无上游河道邻居的河道 cell）沿
  `flow_direction` 向下游走；遇到 order 升高（汇合点）当前折线结束、从该
  cell 起新折线——每条折线只含一个宽度级别。已被走过的 cell（主干先从别的
  源头到达）使支流游走终止——支流止于主干线上。
- **反子午线**：相邻点经度跳变 >180° 时折断折线。
- 输出 `MapFeature(type=RIVER, coordinates=[(lon,lat)...], order=级别)`，
  格式 `{"features": [...]}`。

**渲染**（前端 `MapSvgOverlay`，SVG 矢量叠加层）：每条折线逐点经当前投影的
`project()` 投到屏幕（等距圆柱 / Mollweide / Robinson 通用，与经纬网格同一
机制）；线宽 `(0.55 + 0.5×order)/√zoom`、圆头/圆角连接，不透明度由图层开关
控制（默认开，0.9）。制图学路线：51 km 网格上「看得见河」靠矢量线而非 DEM
切谷（竞品分析 §4.2.1 结论；3D 球面渲染留后续）。

nacrea 实测（200k，seed 42）：103 条折线（order 1 × 97、order 2 × 6），
1365 个顶点。

### 参数表

| 参数 | 默认值 | 范围 | 物理含义 |
|------|--------|------|----------|
| `min_river_accum_km2` | 1000 | 100 – 10000 | 河流最小汇水面积（河网提取阈值） |
| `evaporation_base_mm` | 800 | 300 – 2000 | 简化蒸发率 |

> 湖泊 / 内流盆地的水收支（§8.5 的 `detect_lakes_and_endorheic`）需要降水强迫，
> 首版以 §10 的地貌降水代理为输入；完整水收支（湖泊面积收敛、盐湖判别）留第二批。

---

## 9. 阶段 8: 地表演化侵蚀

> 本阶段取代早期的"简化侵蚀 + 完整水力侵蚀交给 Gaea"方案：地质层现在自己做
> **全球尺度的流水侵蚀**，Gaea 仍保留用于米级局部细节——两者互补而非替代。
> 架构依据（roadmap §五 3B 决策，2026-08-09）：地质层用**地貌降水代理**，不读气候
> 引擎输出，避免地质→气候→地质的 DAG 环依赖。物理公式与引用见
> [knowledge/geology/erosion.md](../../knowledge/geology/erosion.md)。
>
> 算法由 `erosion_algorithm` 选择（当前仅 `stream_power`，保留为将来可能的不同
> 算法留扩展位）；时间离散由 `stream_power_steps` 控制（隐式格式无条件稳定，
> 步数少而均匀，~20）。

### 9.1 总体：层内时间循环

侵蚀是接在 terrain synthesis（§6）之后的**层内时间循环**，每步更新高程并
重算流网：

```
surface evolution 循环 × surface_evolution_steps：
    洼地填平（临时）→ D8 流向 → 流量累积 → stream power 下切 + 坡面扩散
    （每步 elevation 变化 → 下一步重算流向 / 累积）
```

海陆判定统一用 `elevation >= config.sea_level_offset_m`（与气候引擎
`simulate_climate` 的 `is_land` 完全一致），避免掩膜分歧。循环不引入任何
RNG——纯函数，确定性由 seed 与上游地形保证。

### 9.2 地貌降水代理（climate_coupling）

完整水力侵蚀需要降水强迫，而气候是地质的下游。地质层内用**地貌降水代理场**
（`map/precip_proxy.py`），纯函数 `(地形, 纬度, 行星参数) → P`，不读气候引擎输出：

- `climate_coupling: none` —— 均匀降水 `P = precip_proxy_base_mm`；
- `climate_coupling: proxy`（默认）—— 拆成**环流相关**与**环流无关**两部分，使
  **同一代理适配任意环流体制**（地球三圈 / 潮汐锁定单圈 / 任意 Hadley 边界）：
  - **纬向基础场** `P_base(lat)`：镜像气候引擎的纬向项（ITCZ 对流峰 + 副热带抑制 +
    风暴路径），复用 `hadley_extent_deg` / `storm_track_amplitude_mm` /
    `precip_proxy_base_mm` 同一批旋钮；
  - **地形响应** `_orographic_factor`：线性 upslope `w = U·∇h`（`hadley_cell_wind` 纬向风 ×
    地形梯度），迎风坡湿、背风坡干——Smith & Barstad (2004) 线性地形降水模型的
    **零平流极限**，完整傅里叶传递函数（凝结水顺风平流）留后续。
- `climate_coupling: full` —— 读气候引擎输出（DAG 环，当前留接口位不实现）。

**验证**（`scripts/validate_precip_proxy.py`，代理 vs 气候引擎权威降水，陆地逐 cell）：
nacrea 实测 `corr_log = 0.761`（形状对、幅度标定问题）；残余偏差是陆地降水 ~2×
高于纬向均值（BFS 把海洋水汽集中搬运到陆地，纬向基础场无法捕获），归 M3 标定。

代理场是"强迫"，气候引擎的 BFS 水汽是"精细化"——二者是 roadmap 写明的
"强迫 vs 精细化"关系。discharge 用 `Q = P · A`，下切律以 `Q^m` 代替 `A^m`。

### 9.3 河流下切（stream power law）

标准河道下切律（Howard 1994）：

```
E = K · Q^m · S^n
```

- `Q`：上游流量（= P·A，面积加权）
- `S`：局部坡降 `(h_i − h_j) / dist_ij`（沿流向）
- `m = 0.5`、`n = 1`：Fastscape 默认（Braun & Willett 2013），
  保证坡降-面积关系呈凹形剖面（concave-up long profile）

### 9.4 坡面扩散（hillslope diffusion）

线性扩散律 `∂h/∂t = D ∇²h`，在图邻接上离散为图拉普拉斯。作用等价于旧的
"热侵蚀 / 安息角"——坡面物质蠕移，把超过稳定坡度的陡坡平滑掉。它只作用于
坡面、不产生河道，与 stream power 的河道下切互补。

### 9.5 时间积分（隐式格式，分辨率无关）

不规则球面图上用 **Fastscape 式隐式格式**（Braun & Willett 2013）：

- **stream power 三角精确解**：n=1 时 `E = K·Q^m·S` 是线性的，且每个 cell 只有一个
  下游（流图是森林），按逆拓扑序（河口→源头）一次遍历即精确解、无条件稳定；
- **坡面扩散 Jacobi**：小项（`D·dt/d² ≪ 1`），几次迭代收敛；
- `dt = surface_evolution_time_myr / stream_power_steps`（大、均匀），步数小（~20）、
  与网格分辨率无关；
- **分形 K 缩放**：粗网格平滑了坡度（`S ∝ Δx^(H−1)`），运行时按
  `K_eff = K₀·(Δx/reference_cell_km)^(n(1−H))` 自动换算，使输入的 `K₀` 分辨率无关。

### 9.6 亚网格河道宽度稀释与内流海缺口（2026-08-25）

两块网格尺度修正，详见 [knowledge/geology/erosion.md](../../knowledge/geology/erosion.md)
§3.1/§3.2：

- **河道宽度稀释**：stream power 下切的是河床（宽度 `w = 5·Q^0.5`，Leopold &
  Maddock 1953），不是整个 cell——cell 平均下切乘 `min(1, w/d)`。没有它，D8
  单流向把全部流量集中进单 cell 宽细流，在 51 km 网格上切出深达 1–2 km 的
  网格级峡谷（真实地球同分辨率无此特征）。**封堵坝 cell 豁免**：海峡下切是
  集中缺口推进，按全河道速率下切。
- **基准面规则**：陆 cell 下限 clamp 到 `sea_level + 1 m`；排入开阔海洋的陆
  cell 静止（无输沙极限的 detachment-limited 律会夷平全部低地，nacrea 回归
  验证过）；排入**未连通外洋的内流海**的陆 cell 向海平面基准面下切。
- **缺口冲开**：侵蚀结束后跑一次海侵通道——minimax Dijkstra 找每个内流海
  通向大洋的最低鞍部（= priority flood 溢流水位）；鞍部已被切到海平面时，把
  路径上残余陆 cell 降到 `sea_level − 5 m`，内流海连通外洋。实现 roadmap
  §7 #7 能力需求（侵蚀冲开被堵海峡），验收测试
  `tests/test_map/test_erosion.py::test_erosion_breaches_dammed_basin`。

### 9.7 沉积物搬运（第二批，暂不做）

首版**只做侵蚀下切 + 坡面扩散**，沉积物 / 三角洲搬运留第二批：它是独立物理
（沉积通量平衡、海岸三角洲形态），还牵扯海岸与海平面交互。当前 `net_erosion_m`
字段只记录诊断量（侵蚀 − / 沉积 +），不做真实搬运。

### 9.8 参数表

| 参数 | 默认值 | 范围 | 物理含义 |
|------|--------|------|----------|
| `erosion_algorithm` | `"none"` | none / stream_power | 侵蚀算法（当前仅 stream_power，保留扩展位） |
| `surface_evolution_time_myr` | 0 | 0 – 1000 | 侵蚀总时长（Myr；0 = 禁用，分辨率无关） |
| `stream_power_steps` | 20 | 1 – 200 | 隐式格式的均匀大步数（dt = time/steps） |
| `climate_coupling` | `"proxy"` | none / proxy / full | 降水强迫源 |
| `fluvial_erodibility` | 1.4e-3 | 1e-4 – 1e-2 | 参考分辨率下的侵蚀系数 K₀（m/yr） |
| `reference_cell_km` | 1.0 | — | K 缩放的参考分辨率（km） |
| `terrain_hurst_exponent` | 0.5 | 0.3 – 0.7 | 地形 Hurst 指数 H（坡度分形标度 S ∝ Δx^(H−1)） |
| `stream_power_m` | 0.5 | 0.3 – 0.7 | 流量指数 m |
| `stream_power_n` | 1.0 | 0.7 – 2.0 | 坡降指数 n |
| `hillslope_diffusivity` | 1e-5 | 1e-6 – 1e-3 | 坡面扩散 D₀（m²/yr @ 1km，分形缩放） |
| `precip_proxy_base_mm` | 2000 | 100 – 4000 | 代理场 ITCZ 峰振幅 |

---

## 10. 阶段 9: 数据导出与可视化

### 10.1 等距圆柱投影导出

将 CVT 节点数据插值到规则经纬度网格：

```python
def export_equirectangular(
    mesh: CVTMesh,
    data: np.ndarray,           # (N,) node values
    width: int = 4096,
    height: int = 2048,
    method: str = "cubic",
) -> np.ndarray:
    """Interpolate CVT node data to equirectangular grid.

    Uses scipy.interpolate.griddata with the node positions
    projected to (lon, lat) as the interpolation source.

    Returns:
        (height, width) 2D array.
    """
    # Convert node positions to (lon, lat)
    lat = arcsin(clip(mesh.nodes[:, 1], -1, 1))
    lon = arctan2(mesh.nodes[:, 2], mesh.nodes[:, 0])

    # Source points
    points = stack([degrees(lon), degrees(lat)], axis=-1)

    # Target grid
    target_lon = linspace(-180, 180, width, endpoint=False)
    target_lat = linspace(90, -90, height)
    grid_lon, grid_lat = meshgrid(target_lon, target_lat)

    # Interpolate
    result = scipy_interpolate_griddata(
        points, data,
        (grid_lon, grid_lat),
        method=method,
    )

    return result
```

**16-bit PNG 导出**：

```python
def save_heightmap_png(
    elevation_grid: np.ndarray,
    elev_min: float = -11000,
    elev_max: float = 9000,
    path: str = "elevation.png",
) -> None:
    """Save elevation as 16-bit PNG.

    Maps [elev_min, elev_max] → [0, 65535].
    """
    normalized = (elevation_grid - elev_min) / (elev_max - elev_min)
    normalized = clip(normalized, 0, 1)
    uint16 = (normalized * 65535).astype(np.uint16)
    Image.fromarray(uint16).save(path)
```

### 10.2 多投影支持

除等距圆柱投影外，支持以下等面积投影：

**Lambert 方位等面积投影**（Lambert Azimuthal Equal-Area）：

```
x = R · √(2 / (1 + cos(c))) · cos(φ) · sin(Δλ)
y = R · √(2 / (1 + cos(c))) · (cos(φ₀)·sin(φ) - sin(φ₀)·cos(φ)·cos(Δλ))

cos(c) = sin(φ₀)·sin(φ) + cos(φ₀)·cos(φ)·cos(Δλ)
```

适用于半球视图，面积保持正确。

**Hammer 投影**（Hammer equal-area）：

```
x = 2√2 · cos(φ)·sin(λ/2) / √(1 + cos(φ)·cos(λ/2))
y = √2 · sin(φ) / √(1 + cos(φ)·cos(λ/2))
```

参考 Gleba 的投影选择——Hammer 投影是椭圆形全图投影，面积保持正确，
极点畸变远小于等距圆柱投影，适合全球总览。

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
│  • 河流 polyline                            │
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

## 11. 数据模型变更

### 新增 Pydantic 模型

#### `src/dreamulator/map/cvt_models.py`（新文件）

```python
class CVTNode(BaseModel):
    """A single node in the CVT mesh."""
    id: int
    xyz: tuple[float, float, float]     # unit sphere Cartesian
    lat: float = Field(ge=-90, le=90)    # geographic latitude (degrees)
    lon: float = Field(ge=-180, le=180)  # geographic longitude (degrees)
    area_km2: float                       # Voronoi cell area
    neighbors: list[int]                  # adjacent node IDs
    plate_id: str | None = None
    crust_type: str | None = None        # continental | oceanic | mixed

class CVTMeshData(BaseModel):
    """Complete CVT mesh stored as JSON."""
    num_nodes: int
    radius_km: float
    seed: int
    lloyd_iterations: int
    nodes: list[CVTNode]
    # Plate metadata
    plates: list[PlateData]
    # Boundary segments
    boundaries: list[BoundaryData]
    # Hotspot metadata
    hotspots: list[HotspotData]

class PlateData(BaseModel):
    """Tectonic plate with Euler pole kinematics."""
    id: str
    name: str
    crust_type: str                      # continental | oceanic | mixed
    cell_ids: list[int]
    euler_pole: tuple[float, float, float]  # unit vector (rotation axis)
    omega_rad_yr: float                  # angular velocity
    growth_speed_multiplier: float = 1.0        # flood-fill speed

class BoundaryData(BaseModel):
    """Plate boundary segment."""
    plate_a: str
    plate_b: str
    boundary_type: str                   # convergent | divergent | transform
    node_pairs: list[tuple[int, int]]    # CVT node pairs forming boundary

class ClimateData(BaseModel):
    """Climate attributes per CVT node."""
    temperature_mean_c: float
    temperature_jan_c: float
    temperature_jul_c: float
    precipitation_mm: float
    koppen_class: str

class HydrologyData(BaseModel):
    """Hydrology attributes per CVT node."""
    flow_direction: int                  # downstream node ID, -1 = sink
    flow_accumulation_km2: float
    river_order: int                     # 0 = no river, 1-5
    is_lake: bool
    is_endorheic: bool

class BiomeData(BaseModel):
    """Ecology attributes per CVT node."""
    biome_class: str                     # Whittaker classification
    vegetation_density: float            # [0, 1]
    soil_fertility: float                # [0, 1]
```

### 修改现有模型

#### `src/dreamulator/map/models.py`

| 模型 | 变更 | 说明 |
|------|------|------|
| `MapProjection` | 新增枚举值 `HAMMER`, `LAMBERT_AZ` | 支持多投影导出 |
| `MapMetadata` | 新增字段 `source: Literal["raster", "cvt_pipeline"]` | 区分数据来源 |
| `MapMetadata` | 新增字段 `cvt_seed: int | None` | CVT 生成种子 |
| `MapMetadata` | 新增字段 `cvt_num_nodes: int | None` | CVT 节点数 |
| `VoronoiCell` | **废弃**（替换为 `CVTNode`） | CVT 节点包含更多信息 |
| `VoronoiNetwork` | **废弃**（替换为 `CVTMeshData`） | 新的网格存储格式 |
| `PlateVelocity` | ✅ 已删除 | Euler pole 表示 |
| `TectonicPlate` | 新增 `euler_pole`, `omega_rad_yr` | 球面运动学 |
| `MapLayerType` | 新增 `FLOW_ACCUMULATION`, `WIND`, `KOPPEN` | 新图层类型 |

### 新增模块文件

| 模块 | 路径 | 职责 |
|------|------|------|
| `cvt_models.py` | `src/dreamulator/map/` | CVT 数据模型 |
| `cvt_generator.py` | `src/dreamulator/map/` | Fibonacci + Lloyd + 网格构建 |
| `plate_generator.py` | `src/dreamulator/map/` | 种子选取 + Cortial 2019 Voronoi 剖分 + 地壳类型 |
| `euler_kinematics.py` | `src/dreamulator/map/` | 欧拉极分配 + 速度场计算 |
| `boundary_classifier.py` | `src/dreamulator/map/` | 边界检测 + 分类 + 链追踪 |
| `terrain_synth.py` | `src/dreamulator/map/` | 地形合成（base + boundary + fBm） |
| `climate_engine.py` | `src/dreamulator/engine/` | 温度 + 风场 + 降水 + Köppen |
| `hydrology_engine.py` | `src/dreamulator/engine/` | 流向 + 汇水 + 河流 + 湖泊 |

### 向后兼容

- `VoronoiCell` / `VoronoiNetwork` 模型保留但标记 `deprecated`
- 栅格工作流（`MapManager.import_heightmap()`）继续工作
- `MapMetadata.source` 字段区分数据来源（`"raster"` 或 `"cvt_pipeline"`）
- 迁移脚本：`scripts/migrate_voronoi_to_cvt.py`（将 Voronoi 数据转为 CVT 格式）

---

## 12. 性能考量

> **实测修正（2026-08-03，perf/profiling-and-optimization 分支）**：
> 本节原估算（总计 ~70s）偏差较大——实测 nacrea（100K 胞、构造 ×50）全量构建
> **532s**（geological 388s + climate 143s + astronomy <1s）。
> pyfastnoise 路线已失效：**该包不在 PyPI**（uv 解析失败、无 py3.12 wheel）；
> `opensimplex.noise3array` 是纯 Python 循环（21µs/点，仅比标量 44µs/次快 2 倍）。
> 噪声后端改为 **Numba JIT 内核**。详见 `docs/usage/profiling.md`。

### 瓶颈分析

| 操作 | 复杂度 | 100K 耗时 | 200K 耗时 | 瓶颈原因 |
|------|--------|-----------|-----------|----------|
| Fibonacci lattice | O(N) | <0.01s | <0.01s | 无 |
| Lloyd relaxation (×8) | O(k·N·log N) | ~8s | ~20s | SphericalVoronoi 构建 |
| 板块剖分（Cortial 2019） | O(N·log N) | ~1s | ~2s | 优先队列 |
| 欧拉极速度场 | O(N) | <0.1s | <0.1s | 向量化叉积 |
| 边界检测 | O(N) | <0.1s | <0.1s | 邻接扫描 |
| 边界效应计算 | O(N·B) | ~15s | ~30s | B = 边界节点数 |
| fBm 噪声 (6+3 oct) | O(N·O) | ~2s（Numba JIT） | ~4s | 逐点 Simplex |
| 海平面二分 | O(N·log(precision)) | <0.01s | <0.01s | 无 |
| 温度计算 | O(N) | <0.1s | <0.1s | 向量化 |
| 风场计算 | O(N·k) | ~2s | ~4s | k = 平均邻居数 |
| BFS 降水 | O(N) | ~3s | 单次 BFS |
| 流向确定 | O(N·k) | ~2s | 逐节点扫描 |
| 汇水累积 | O(N) | ~1s | 拓扑排序 |
| 热侵蚀 (×10) | O(k·N·I) | ~10s | 迭代松弛 |
| 等距投影插值 | O(N·log N) | ~5s | scipy griddata |
| **总计** | | **实测 532s**（2026-08-03，含气候引擎与构造 ×50） | |

### 优化策略

1. **Numba JIT 噪声内核替代 opensimplex**（~~pyfastnoise~~ 已失效——不在 PyPI）：逐点调用 44µs → ~100ns（≈400×），fBm ~60s → ~2s
2. **NumPy 向量化**：所有 O(N) 操作使用向量化而非 Python 循环
3. **分块计算**：边界效应使用 KD-tree 范围查询，避免 O(N·B) 全扫描
4. **增量计算**：分支系统仅重跑受影响的阶段
5. **缓存**：fBm 噪声结果缓存（同 seed 不变），仅在地形参数变更时重算
6. **多进程**：Lloyd 松弛和 fBm 可使用 `multiprocessing` 并行

### 扩展到 1M 节点

| 策略 | 描述 | 预期效果 |
|------|------|----------|
| 自适应分辨率 | 板块边界附近加密，板块内部稀疏 | 总节点减少 50% |
| C 扩展 | 关键路径用 Cython/Rust 重写 | 10-50× 加速 |
| GPU 计算 | fBm 和侵蚀使用 CUDA/Vulkan | 100× 加速 |
| 分块处理 | 将球面分成 8 个八分面，独立计算后拼接 | 内存减半 |
| 增量 LOD | 先生成 10K 低分辨率预览，按需细化 | 交互响应 <1s |

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
- 等距圆柱投影 + WebGL 2 支持 → GPU 路径（ShaderMaterial）
- 非等距投影或 WebGL 2 不可用 → CPU 路径（CanvasTexture + MeshBasicMaterial）
- GPU 路径当前仅支持等距圆柱（UV 直接映射）；Mollweide/Robinson 投影仍需 CPU 重采样

**设计参考：**
- **CesiumJS**：高程瓦片作为纹理 + GLSL shader 渲染地形
- **VTK/ParaView**：传输函数纹理（1D LUT）用于体渲染着色
- **游戏模拟器**（RetroArch）：调色板索引渲染，每像素查调色板纹理
- **延迟渲染**（Deferred Shading）：G-buffer 数据纹理 → 光照 shader

**实现文件：**
- `frontend/src/viewers/map/useGPUTerrain.ts` — GPU terrain hook（ShaderMaterial + DataTexture）
- GLSL 顶点/片元着色器内嵌于 `useGPUTerrain.ts`

---

## 13. 已知限制与未来工作

### 当前限制

1. **侵蚀精度**：全球 stream power + 坡面扩散做大尺度地貌改造（河道宽度稀释
   抑制了网格级峡谷，§9.6）；沉积扇 / 三角洲（§9.7 第二批）与米级细节仍需
   Gaea 精细化。

2. **静态气候**：当前气候模型是稳态快照，不模拟气候的季节内变化或年际变率（ENSO 等）。

3. **无冰川模拟**：冰盖的生长/退缩/流动未建模。极地地区的气候和地形耦合
   需要冰川动力学。

4. **简化的洋流**：表面流近似 + 风驱动，缺少深层热盐环流
   （thermohaline circulation）。

5. **单球面假设**：不支持非球形天体（如小行星、扁球体）。

6. **板块固定**：基础管线中板块划分在生成后不随时间演化。
   时间演化（板块分裂/拼合/威尔逊循环）在 §17 中规划为进阶功能。

7. **无热点**：不生成火山岛链（如夏威夷）。Cortial 2019 同样缺少此功能，
   但指出可作为特殊采样点漂移实现。

### 未来工作

1. **时间演化**（§17 已规划）：让板块以地质时间尺度移动（百万年），地形随板块运动演化。
   核心算法：半拉格朗日平流 + 威尔逊循环（详见 Cortial 2019，[附录 D](#附录-d-论文解读--cortial-et-al-2019-procedural-tectonic-planets)）。

2. **冰川引擎**：在极地和高海拔区域模拟冰川动力学，冰蚀地形（U 型谷、冰碛）。

3. **深层洋流**：实现温盐环流，影响全球热量分配和气候稳定性。

4. **生态演替**：植被不仅是气候的被动映射，还反馈影响气候（蒸腾、反照率）。

5. **文明互动**：河流改道、灌溉、采矿等文明行为改变地形/水文。

6. **多分辨率 LOD**：前端支持从全球视图（10K 节点）无缝缩放到区域视图（100K 节点）。

7. **GPU 加速**：使用 CuPy 或 PyTorch 将 fBm、BFS、侵蚀等计算迁移到 GPU。

8. **天体物理集成**：从 `astronomy` 层的恒星参数（光度、轨道距离）自动驱动气候模型，
   实现真正的"自底向上"推演。

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

**A.6 汇水累积**（水文学知识文档尚待建立，见 `knowledge/geology/CLAUDE.md`
规划清单；实现见 §8.2）：

```
accum(i) = area(i) + Σ accum(j) for j in upstream(i)

其中 upstream(i) = {j | flow_dir(j) = i}

计算顺序：拓扑排序（从源头到河口）
```

---

## 附录 B: 现有代码复用清单

### 来自 `scripts/generate_planet_heightmap.py`

| 函数 | 复用状态 | 说明 |
|------|----------|------|
| `lat_lon_to_xyz()` | ✅ 直接复用 | 球面坐标转换，逻辑完全相同 |
| `xyz_to_lat_lon()` | ✅ 直接复用 | 逆向坐标转换 |
| `angular_distance()` | ✅ 直接复用 | Haversine 角距离 |
| `angular_distance_xyz()` | ✅ 直接复用 | 3D 向量角距离 |
| `smooth_step()` | ✅ 直接复用 | Hermite 平滑插值 |
| `generate_fbm_3d()` | ⚠️ 改造 | 改为在 CVT 节点 3D 坐标上采样，而非等距网格 |
| `_compute_noise_elementwise()` | ⚠️ 改造 | 向量化改造或用 Numba JIT 噪声内核替代 |
| `_fallback_fbm()` | ❌ 废弃 | CVT 管线不需要 2D fallback |
| `_compute_continent_field()` | ❌ 废弃 | 被 CVT 基准高程 + Cortial 2019 Voronoi 剖分替代 |
| `_elliptical_gaussian()` | ⚠️ 可选保留 | 可用于 CVT 上的局部特征叠加 |
| `_compute_base_elevation()` | ⚠️ 改造 | 改为基于地壳类型的双峰分配 |
| `_compute_tidal_deformation()` | ✅ 直接复用 | P₂ Legendre 潮汐形变 |
| `_generate_plates()` | ⚠️ 重大改造 | Voronoi 最近邻/洪水填充 → Cortial 2019 Voronoi 剖分；Euler 极逻辑保留 |
| `_compute_boundary_effects()` | ⚠️ 改造 | 边界检测改为图邻接扫描；效应公式保留 |
| `_compute_convergence_rate()` | ⚠️ 改造 | 保留 v = ω × P 核心逻辑，修正边界法向计算 |
| `_plate_velocity_at()` | ✅ 直接复用 | 刚体旋转 v = ω × r |
| `_compute_hotspot_effects()` | ⚠️ 改造 | 从网格采样改为 CVT 节点采样 |
| `_compute_noise_detail()` | ⚠️ 改造 | 振幅调制逻辑保留，采样改为 CVT |
| `SphericalHeightmapGenerator.generate()` | ❌ 废弃 | 被 CVT 管线的分阶段函数替代 |
| `generate_cubemap_faces()` | ❌ 废弃 | CVT 管线不需要立方体投影 |
| `ContinentFeature` | ⚠️ 可选保留 | 用于手动指定大陆特征 |
| `HotspotFeature` | ✅ 直接复用 | 热点配置 |
| `PlateSeed` | ⚠️ 改造 | 增加 `growth_speed_multiplier` 字段 |
| `PlanetConfig` | ⚠️ 重大改造 | 增加 CVT 参数，移除栅格相关参数 |
| `make_equirect_grid()` | ✅ 保留 | 仅用于导出阶段 |

### 来自 `src/dreamulator/map/` 模块

| 函数/模型 | 复用状态 | 说明 |
|-----------|----------|------|
| `VoronoiCell` | ❌ 废弃 | 替换为 `CVTNode` |
| `VoronoiNetwork` | ❌ 废弃 | 替换为 `CVTMeshData` |
| `TectonicPlate` | ⚠️ 扩展 | 新增 Euler pole 字段 |
| `PlateType` | ✅ 直接复用 | 枚举值不变 |
| `PlateVelocity` | ✅ 已删除 | Euler pole 表示 |
| `MapFeature` | ✅ 直接复用 | 河流/山脉等线性特征 |
| `FeatureType` | ✅ 直接复用 | 可扩展新类型 |
| `MapLayerType` | ⚠️ 扩展 | 新增图层类型 |
| `MapLayerRegistry` | ✅ 直接复用 | 图层依赖追踪 |
| `RasterLayerMeta` | ✅ 直接复用 | 导出栅格元数据 |
| `MapManager` | ⚠️ 扩展 | 新增 CVT 管线入口方法 |
| `generate_voronoi()` | ❌ 废弃 | 被 `cvt_generator.py` 替代 |
| `generate_terrain()` | ⚠️ 保留 | 作为简单 2D 地形生成的备选 |
| `elevation_codec` | ✅ 直接复用 | 高度图编解码 |

---

## 附录 C: 实施清单

### Phase 0: 基础设施（1-2 周）

- [ ] 创建 `src/dreamulator/map/cvt_models.py` — 新数据模型
- [ ] 创建 `src/dreamulator/map/cvt_generator.py` — Fibonacci + Lloyd + 网格构建
- [ ] Numba JIT 噪声内核（`map/noise_kernels.py`，`cache=True`）——见 §15 实测修正
- [ ] 单元测试：CVT 网格面积总和 ≈ 4π、邻接图对称性
- [ ] 可视化：Three.js 渲染 CVT 网格（debug 用）

### Phase 1: 构造板块（1 周）

- [ ] 创建 `src/dreamulator/map/plate_generator.py` — 种子 + Cortial 2019 Voronoi 剖分
- [ ] 实现可变速度 BFS 填充
- [ ] 手动板块指定 YAML 解析
- [ ] 单元测试：所有节点被分配、板块数正确
- [ ] 可视化：板块着色 + 边界高亮

### Phase 2: 运动学（0.5 周）

- [ ] 创建 `src/dreamulator/map/euler_kinematics.py`
- [ ] 实现欧拉极分配和速度场
- [ ] 实现相对速度分解和边界分类
- [ ] 单元测试：速度场连续性、边界类型覆盖率

### Phase 3: 地形合成（1-2 周）

- [ ] 创建 `src/dreamulator/map/terrain_synth.py`
- [ ] 实现双峰基准高程
- [ ] 移植边界效应公式到 CVT 图
- [ ] 实现 CVT 节点上的 3D fBm 采样
- [ ] 实现热点/地幔柱隆起
- [ ] 集成潮汐形变
- [ ] 单元测试：高程范围合理、双峰分布验证
- [ ] 与 `generate_planet_heightmap.py` 对比输出

### Phase 4: 海平面与分类（0.5 周）

- [ ] 实现海平面求解器（绝对值 + 目标覆盖率）
- [ ] 大陆架检测
- [ ] 极区配置分析
- [ ] 单元测试：海陆比例精度


### Phase 5: 水文（1-2 周）

- [ ] 创建 `src/dreamulator/engine/hydrology_engine.py`
- [ ] 实现流向确定
- [ ] 实现汇水累积（拓扑排序）
- [ ] 实现河流分类和网络提取
- [ ] 实现湖泊和内流盆地检测
- [ ] 单元测试：水守恒（所有陆地水最终到达海洋或内陆湖）
- [ ] 验证：河流网络与 Azgaar 生成器对比

### Phase 6: 侵蚀（1 周）

- [ ] 实现热侵蚀（迭代松弛）
- [ ] 实现视觉水蚀
- [ ] 单元测试：侵蚀后高程范围、坡度分布
- [ ] 性能基准：200K 节点 < 30s

### Phase 7: 导出（1 周）

- [ ] 实现等距圆柱投影导出
- [ ] 实现多投影导出（Lambert, Hammer）
- [ ] 与 MapManager / MapLayerRegistry 集成
- [ ] 前端 Three.js 可视化更新


### Phase 8: 集成测试与文档（1 周）

- [ ] 端到端测试：从 world.yaml → 完整地形
- [ ] 性能基准报告
- [ ] 更新 CLAUDE.md 和 API 文档
- [ ] 更新 `scripts/export_static.py` + `staticClient.ts` + `client.ts`（静态导出同步）

### 依赖关系图

```
Phase 0 (基础设施)
  ├── Phase 1 (板块)
  │     └── Phase 2 (运动学)
  │           └── Phase 3 (地形合成)
  │                 └── Phase 4 (海平面)
  │                       ├── Phase 5 (水文)
  │                       │     └── Phase 6 (侵蚀)
  │                       └── Phase 7 (导出)
  └── Phase 8 (集成测试) ← 所有 Phase 完成后
```

**关键路径**: Phase 0 → 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8

预计总工期：**8-12 周**（单人全职开发）

---

## 14. 时间演化与威尔逊循环

> **状态**: 进阶功能规划。基础管线（§2–§12）生成静态快照；本节描述如何引入时间变量 $t$，
> 使 CVT 网格成为"活着的、具有地质记忆的星球模拟器"。
> 核心参考：Cortial et al. 2019（见[附录 D](#附录-d-论文解读--cortial-et-al-2019-procedural-tectonic-planets)）
> 及对话记录中的威尔逊循环讨论。

### 14.1 核心原则：固定网格 + 属性平流

**绝对不要在时间轴上物理移动 CVT 的顶点！**

移动顶点意味着每一步都需要进行昂贵的 Delaunay 重构。Cortial 2019 和现代气候模型
均采用**固定背景场 + 半拉格朗日平流（Semi-Lagrangian Advection）**：

1. **网格固定**：200K（或更多）CVT 节点在整个推演中永远不动，它们是行星表面的"固定观测站"
2. **属性分离**：板块信息视为在每个 cell 上流动的"流体属性"
3. **时间步进**：沿速度反方向追踪来源 cell，插值获取上一时刻的属性

```python
# 半拉格朗日平流伪代码
def advect_attributes(mesh, velocities, attributes, dt):
    for cell in mesh.cells:
        # 沿速度反方向追踪
        source_pos = cell.xyz - velocities[cell.id] * dt
        # 在固定网格上找到 source_pos 最近的 cell
        source_cell = mesh.find_nearest(source_pos)
        # 将来源 cell 的属性平流到当前 cell
        attributes[cell.id] = interpolate(attributes, source_cell)
```

### 14.2 地壳属性元组

每个 CVT cell 维护以下随时间演化的状态：

| 属性 | 符号 | 类型 | 说明 |
|------|------|------|------|
| 所属板块 | `Plate_ID` | int | 当前所属板块编号 |
| 地壳类型 | `Crust_Type` | enum | continental / oceanic / craton |
| 地壳厚度 | `Thickness` | float (km) | 陆壳 ~35-50km，洋壳 ~7km |
| 地壳年龄 | `Age` | float (My) | 洋壳自洋中脊创生以来的年龄 |
| 造山年龄 | `Orogeny_Age` | float (My) | 陆壳自上次造山运动以来的年龄 |
| 褶皱方向 | `Fold_Dir` | 3D vector | 局部褶皱/折叠方向（用于放大阶段） |

### 14.3 威尔逊循环四大过程

在固定 CVT 场中，威尔逊循环由相邻 cell 之间的**相对速度场**直接触发：

#### A. 洋壳创生（Divergence / Ridge Push）

- **条件**：相对速度法向分量 $v_\perp > 0$（相互远离），两侧均为洋壳
- **操作**：
  - `Crust_Type` = OCEANIC
  - `Age` 重置为 0
  - `Thickness` = $7 + 8 \cdot T_\text{mantle}$ km（受地幔温度调制）
  - 地形叠加洋中脊剖面函数

#### B. 俯冲消亡（Subduction / Slab Pull）

- **条件**：$v_\perp < 0$，至少一侧为洋壳（较老/较重者俯冲）
- **操作**：
  - 老洋壳 cell 的 `Thickness` 按比例削减
  - 上方板块 cell 接收物质，形成火山弧/海岸山脉
  - **Slab pull 反馈**：俯冲带修改板块的欧拉极方向（见 Cortial §4.1）

#### C. 大陆拼合（Continental Collision）

- **条件**：$v_\perp < 0$，两侧均为陆壳
- **操作**：
  - 陆壳 `Thickness` 叠加（40km + 40km = 80km）
  - 触发离散造山事件（Cortial 的 collision surge）
  - 一侧 `Plate_ID` 修改为另一侧，实现物理拼合

#### D. 板块裂解（Plate Rifting）

- **触发**：大陆板块内部出现高拉张力
- **操作**：
  - 将大板块切割为 2-4 个子板块（Voronoi 细分）
  - 为新板块分配独立欧拉极
  - 裂解中心陆壳减薄 → 可能翻转为洋壳（红海模式）
- **概率模型**（Cortial §4.4 Poisson 律）：
  ```
  P = λ · e^{-λ},  λ = λ_0 · f(陆壳比例) · A/A_0
  ```
  大板块更容易裂解，防止不自然的超级大陆永久存在

### 14.4 随时间变化的行星物理参数

行星并非静态系统，而是随内热耗散不断"衰老"的热力学系统。

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

### 14.5 完整时间步进循环

```
For t = 0 to T_end step Δt (= 2 My):
  1. 全局环境演化: 更新 T_mantle, omega_global, tide_stress, sea_level
  2. 运动学解算: v(p) = omega_global × (ω_plate × p)
  3. 半拉格朗日平流: 搬运 Thickness, Age, Type
  4. 边界交互 (Wilson Cycle):
     A. 洋壳创生 (v_⊥ > 0, 洋-洋)
     B. 俯冲消亡 (v_⊥ < 0, 洋壳参与)
     C. 大陆拼合 (v_⊥ < 0, 陆-陆)
     D. 板块裂解 (Poisson 概率事件)
  5. 动力学反馈: 根据质量分布重算板块质心 → 微调欧拉极
  6. 侵蚀与沉积: 大陆侵蚀 + 洋壳沉降 + 海沟沉积
  7. 气候快照 (可选): 在关键地质年代运行气候模拟
```

### 14.6 与基础管线的关系

| 功能 | 基础管线 (§2-§12) | 时间演化 (§17) |
|------|-------------------|----------------|
| 板块分配 | 一次性 Cortial 2019 剖分 | 随裂解/拼合动态变化 |
| 地形生成 | 静态合成 | 每步增量更新 |
| 海平面 | 固定值 | 随洋中脊体积波动 |
| 侵蚀 | 简化后处理 | 持续作用 |
| 气候 | 终态快照 | 可在任意时间步截取 |
| 输出 | 单一地图 | 可回溯任意地质年代 |

**实施优先级**：基础管线（Phase 1）→ 时间演化（Phase 2）。Phase 2 预计额外 4-6 周。

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

