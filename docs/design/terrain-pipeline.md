# 行星地形生成管线技术参考

> **状态**: 设计草案 · 2026-07-21

> **本文档是 [地图工作流指南](../usage/map-workflow.md) 的技术参考**。工作流指南描述"怎么做"，本文档解释"为什么这么做"以及各阶段的算法细节。

本文档描述 dreamulator 行星地形生成管线的完整技术方案。
**球面质心 Voronoi 镶嵌（CVT Mesh）是一等公民数据，等距圆柱投影高度图是派生导出产物**。
全部模拟（构造、侵蚀、气候、水文）在 CVT 不规则网格上完成，仅在最终可视化/导出阶段投影为栅格。
Gaea 可作为可选的局部精细化工具使用。

---

## 目录

1. [总体架构](#1-总体架构)
2. [阶段 1: 球面 CVT 网格生成](#2-阶段-1-球面-cvt-网格生成)
3. [阶段 2: 构造板块](#3-阶段-2-构造板块)
4. [阶段 3: 欧拉极与板块运动学](#4-阶段-3-欧拉极与板块运动学)
5. [阶段 4: 边界检测与分类](#5-阶段-4-边界检测与分类)
6. [阶段 5: 地形合成](#6-阶段-5-地形合成)
7. [阶段 6: 海平面与基础分类](#7-阶段-6-海平面与基础分类)
8. [阶段 7: 气候模拟](#8-阶段-7-气候模拟)
9. [阶段 8: 河流与水文](#9-阶段-8-河流与水文)
10. [阶段 9: 侵蚀（简化）](#10-阶段-9-侵蚀简化)
11. [阶段 10: 植被与生态（简述）](#11-阶段-10-植被与生态简述)
12. [阶段 11: 数据导出与可视化](#12-阶段-11-数据导出与可视化)
13. [阶段 12: Gaea 局部精细化（可选）](#13-阶段-12-gaea-局部精细化可选)
14. [数据模型变更](#14-数据模型变更)
15. [性能考量](#15-性能考量)
16. [已知限制与未来工作](#16-已知限制与未来工作)
17. [时间演化与威尔逊循环（进阶）](#17-时间演化与威尔逊循环进阶)
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

```
                        ┌──────────────────────────────────────────────────────────┐
                        │           Phase 0: CVT Mesh Generation                   │
                        │  Fibonacci Lattice → Jitter → Lloyd Relaxation            │
                        │  → scipy.spatial.SphericalVoronoi (CVT Mesh)             │
                        │  Output: CVTMesh (nodes[], adjacency, dual_edges)         │
                        └──────────────────────┬───────────────────────────────────┘
                                               │
                        ┌──────────────────────▼───────────────────────────────────┐
                        │           Phase 1: Tectonic Plates                        │
                        │  Poisson-disc Seeds → Voronoi BFS (Cortial 2019)         │
                        │  → Plate Assignment + Crust Type                          │
                        │  Output: plate_id[], crust_type[]                         │
                        └──────────────────────┬───────────────────────────────────┘
                                               │
                        ┌──────────────────────▼───────────────────────────────────┐
                        │           Phase 2: Euler Poles & Kinematics               │
                        │  Random rotation axis → angular velocity ω               │
                        │  → velocity field v(P) = ω × P                           │
                        │  Output: euler_pole[], omega[], velocity[3][N]            │
                        └──────────────────────┬───────────────────────────────────┘
                                               │
                        ┌──────────────────────▼───────────────────────────────────┐
                        │           Phase 3: Boundary Detection & Classification    │
                        │  Neighbor scan → v_rel decomposition                      │
                        │  → convergent / divergent / transform tagging             │
                        │  Output: boundary_segments[], boundary_type[]             │
                        └──────────────────────┬───────────────────────────────────┘
                                               │
                        ┌──────────────────────▼───────────────────────────────────┐
                        │           Phase 4: Terrain Synthesis                      │
                        │  base_elev (bimodal) + boundary_effects (Gaussian)        │
                        │  + hotspot_uplift + fBm_3d (6 octaves, on CVT nodes)     │
                        │  Output: elevation[N]                                     │
                        └──────────────────────┬───────────────────────────────────┘
                                               │
                        ┌──────────────────────▼───────────────────────────────────┐
                        │           Phase 5: Sea Level & Classification             │
                        │  sea_level → land/ocean mask → shelf detection            │
                        │  Output: is_land[], is_shelf[], water_depth[]             │
                        └──────────────────────┬───────────────────────────────────┘
                                               │
                        ┌──────────────────────▼───────────────────────────────────┐
                        │           Phase 6: Climate Simulation                     │
                        │  Solar radiation → temperature → geostrophic wind         │
                        │  → BFS moisture transport → precipitation → Köppen        │
                        │  Output: temperature[], precipitation[], koppen_class[]   │
                        └──────────────────────┬───────────────────────────────────┘
                                               │
                        ┌──────────────────────▼───────────────────────────────────┐
                        │           Phase 7: Rivers & Hydrology                     │
                        │  Steepest descent → flow accumulation → river network     │
                        │  → lake / endorheic basin detection                       │
                        │  Output: flow_dir[], flow_accum[], rivers[], lakes[]      │
                        └──────────────────────┬───────────────────────────────────┘
                                               │
                        ┌──────────────────────▼───────────────────────────────────┐
                        │           Phase 8: Erosion (Simplified)                   │
                        │  Thermal (talus smoothing) + visual water erosion         │
                        │  Output: elevation_modified[N]                            │
                        └──────────────────────┬───────────────────────────────────┘
                                               │
                        ┌──────────────────────▼───────────────────────────────────┐
                        │           Phase 9: Vegetation & Ecology                   │
                        │  (temperature, precipitation) → Whittaker biome           │
                        │  Output: biome_class[], vegetation_density[]              │
                        └──────────────────────┬───────────────────────────────────┘
                                               │
                        ┌──────────────────────▼───────────────────────────────────┐
                        │           Phase 10: Export & Visualization                │
                        │  scipy.interpolate.griddata → equirectangular PNG         │
                        │  + Lambert / Hammer projection + Three.js rendering       │
                        │  Output: heightmap.png, climate layers, SVG overlays      │
                        └──────────────────────┬───────────────────────────────────┘
                                               │
                        ┌──────────────────────▼───────────────────────────────────┐
                        │           Phase 11: Gaea Local Refinement (Optional)      │
                        │  Stereographic projection → Gaea erode → inverse proj     │
                        │  → feathered blending back into CVT mesh                  │
                        │  Output: refined elevation for selected regions           │
                        └──────────────────────────────────────────────────────────┘
```

### 关键架构决策

- **CVT 而非 HEALPix**: CVT 可以自然表示不规则边界（板块、河流），HEALPix 的固定层次结构
  不适合线性特征的追踪。但 CVT 的代价是邻接关系需要显式存储。
- **fBm 在 3D 球面采样**: 避免 2D 投影的极点噪声畸变。每个 CVT 节点的噪声值由其 3D 坐标
  `(x, y, z)` 直接索引 Simplex noise。
- **板块洪水填充而非 Voronoi 最近邻**: Voronoi 最近邻产生过于规则的板块形状。
  可变速度洪水填充产生更自然的锯齿状边界（参考真实地球板块的非凸性）。
- **欧拉极运动学**: 板块运动使用刚体旋转（`v = ω × P`），确保球面上的运动自洽性。
- **简化侵蚀**: 全水力学侵蚀（hydraulic erosion）计算量巨大且 Gaea 已有成熟实现。
  CVT 管线仅做热侵蚀 + 视觉水蚀，需要精细侵蚀的区域交给 Gaea 局部处理。

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
| 10K | ~640 km | ~512×256 | ~10 MB | ~0.5s |
| 50K | ~290 km | ~1024×512 | ~45 MB | ~3s |
| 100K | ~200 km | ~2048×1024 | ~85 MB | ~8s |
| 500K | ~90 km | ~4096×2048 | ~400 MB | ~50s |
| 1M | ~64 km | ~8192×4096 | ~800 MB | ~120s |

> `d_mean ≈ radius × √(4π/N)`，对于 `R = 6371 km`。

### 参数表

| 参数 | 默认值 | 范围 | 物理含义 |
|------|--------|------|----------|
| `num_nodes` | 100,000 | 10K – 1M | CVT 节点数（分辨率） |
| `jitter_sigma` | 0.3 | 0.0 – 0.5 | 随机扰动强度（× d_mean） |
| `lloyd_iterations` | 8 | 0 – 20 | Lloyd 松弛迭代次数 |
| `lloyd_tolerance` | 1e-4 | 1e-6 – 1e-2 | 收敛判据（× d_mean） |
| `seed` | (world seed) | 任意 int | RNG 种子 |
| `radius_km` | 6371.0 | 100 – 100,000 | 行星半径 |

---

## 3. 阶段 2: 构造板块

### 3.1 种子选取

在 CVT 网格上随机选取 ~20 个种子节点作为板块核心。

> **参考 Cortial 2019 §3**: 论文使用球面 Voronoi cell 作为板块，通过向测地距离
> 添加噪声来产生不规则的板块形状（`geodetic distance + noise warp`）。我们的
> 洪水填充方法（§3.2）实现了类似的不规则性，且更容易控制板块大小分布。

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
即呈偏态（gaia-m 实测 CV≈0.44）。无需额外的目标尺寸（Pareto）或速度参数。

> **偏态的保持（构造重采样）**：构造演化的周期性重分区若是无权重的
> "最近种子" Voronoi，则等价于 Lloyd 迭代——其吸引子是等面积的质心
> Voronoi 剖分（CVT），会把初始偏态洗掉（gaia-m 实测 50 步后 CV 0.44→0.22）。
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
噪声决定，作者无法控制。对于"样板世界"（如 gaia-m），世界构建者往往已经在
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
- fBm 让海岸线保持分形、让弱场区（如破碎群岛）碎成岛链。
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
抬升加在洋壳 cell 上，把裂谷推上海面（gaia-m 大裂谷海曾测得 +927 m）。
修复：合成阶段在入口重算偏置场（纯函数，与地壳锚定逐位一致），对**正抬升项**
乘阻尼

```
damp = clip(2·bias + 2, 0.1, 1.0)   （bias < −0.5 时；否则 1.0，阈值处连续）
```

作用于 gaussian/asymmetric 两种边界效应的汇聚分支与岛弧后处理；海沟负项与
离散分支不动。数值核对：裂谷 bias=−1 走 O-O 幅度，抬升 ≤ 0.1×（≈+350 m），
叠最坏基底仍 <0。正常造山带（bias ≥ −0.5）完全无感。

仅有阻尼还不够：top-N 地壳阈值总会向 authored 海洋泄漏少量 continental cell
（gaia-m 裂谷核心 ~13%），它们拿 +850 m 双峰基准 + 板块偏移（±1500 m）直接
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

#### 海平面偏移旋钮（sea_level_offset_m）

`terrain_config.yaml` 新增 `sea_level_offset_m`（默认 0）。校准（"倒水"）仍按
`target_land_fraction` 求 datum；offset 移动**水面标量**而非地形数组——冰期是水体
移动不是地形移动。大陆架/沿海平原/岛弧 transitional 判定/海陆分类/气候陆海掩膜
（`climate_simulator.py`）均读该值。前端色标仍假设 0 m——定位为实验旋钮。

#### 已知限制

- **海岸线偏直**：海陆判定在 cell 粒度（~76 km @ 100k cells），海岸线沿 cell
  边、过于平直。改进方向：更高 cell 密度 / 海岸带高频噪声扰动 / sub-cell 阈值化。
- **~~浅海深度~~**：已由高程钉扎解决（`shallow_sea` + `elevation_target_m: -120`
  表达陆缘浅海，2026-08）。
- **offset 下游假设**：前端色标/河流生成（TODO）按水面 0 m 假设；
  `sea_level_offset_m ≠ 0` 仅用于实验性重建。
- **钉扎与海陆比**：钉扎只动核支撑区，对 `land_fraction_target` 的扰动 ≤
  核面积占比（gaia-m 地峡 ≈0.3pp）；大陆级钉扎（>5% 表面）需自行调 target。
  钉扎后不重跑校准（全局平移会放大局部操作且 target 相对水面→迭代不适定）。
- **参数需调优**：feature 的 radius/strength/elongation 是作者旋钮，需按渲染
  结果迭代（如"切开大陆"要求裂谷 `|strength|` 超过下伏大陆 strength）。

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
speed_multiplier    →      (新增字段)
```

现有 `PlateVelocity(dx, dy)` 将被废弃，替换为 Euler pole 表示。

### 参数表

| 参数 | 默认值 | 范围 | 物理含义 |
|------|--------|------|----------|
| `num_plates` | 20 | 5 – 50 | 构造板块数量 |
| `speed_range` | (0.5, 2.0) | (0.1, 5.0) | 洪水填充速度范围 |
| `continental_fraction` | 0.35 | 0.1 – 0.8 | 大陆板块比例 |
| `fill_jitter` | 0.1 | 0.0 – 0.5 | 填充随机扰动 |

---

## 4. 阶段 3: 欧拉极与板块运动学

### 4.1 欧拉极分配

每个板块的运动由一个**欧拉极**（Euler pole）描述——球面上的一个旋转轴；
在惯性参考系中板块绕该轴做刚体旋转。

> 运动学公式已上浮至
> [knowledge/geology/plate_tectonics.md](../knowledge/geology/plate_tectonics.md)
> §欧拉极运动学：角速度换算 ω = v/R 与地球板块速度参考表、速度场
> v(P) = ω·(ê×P) 及其大小 |v| = ωR·sin α、边界相对速度与法向/切向分解、
> 无净旋转（no-net-rotation）参考系。

**实现要点**（`tectonic_simulator.py` / `plate_generator.py`）：

- **欧拉极分配**：每板块随机单位旋转轴（高斯采样后归一化），角速度由
  `speed_min_cm_yr`–`speed_max_cm_yr` 均匀采样后经 ω = v/R 换算。
- **速度场**：向量化叉积一次算出全部节点速度（单位球坐标 → 乘
  `radius_km × 1000` 得 m/yr）。
- **参考系**：可选移除岩石圈净旋转（按 cell 面积加权平均速度后扣除），
  由配置键 `remove_net_rotation` 控制。
- **时间演化的 δt 自动缩放**（实现行为，见 §17 与
  `tectonic_simulator.py::_auto_compute_dt`）：
  `δt = 3 · √(4πR²/N) / v_max`——令最快板块每步移动 ~3 个 cell
  （100K cells 时 δt ≈ 2 My；`tectonic_dt_my > 0` 时显式覆盖）。

### 参数表

| 参数 | 默认值 | 范围 | 物理含义 |
|------|--------|------|----------|
| `speed_min_cm_yr` | 1.0 | 0.1 – 5.0 | 最慢板块速度 |
| `speed_max_cm_yr` | 10.0 | 5.0 – 20.0 | 最快板块速度 |
| `remove_net_rotation` | True | bool | 是否移除净旋转 |

---

## 5. 阶段 4: 边界检测与分类

在 CVT 网格的邻接图上扫描所有边，两端属于不同板块的边即为**板块边界**段。

> 边界运动学与地质学依据已上浮至
> [knowledge/geology/plate_tectonics.md](../knowledge/geology/plate_tectonics.md)
> §边界检测与分类：相对速度
> v_rel = (Ω_A − Ω_B) × P · R 及其法向/切向分解（v_n 汇聚为正、v_t 走滑），
> 各边界类型的地质效应（山脉/海沟/火山弧、洋中脊/裂谷、走滑断层）与
> 汇聚子类型（陆-陆碰撞、洋-洋俯冲、安第斯型俯冲）。

**实现要点**（`boundary_detector.py`）：

1. **邻接扫描**：遍历邻接表，以 `(min(a,b), max(a,b))` 去重，收集
   `BoundarySegment`（两端节点、两侧板块、中点坐标、`v_normal_m_yr`、
   `v_tangential_m_yr`、`influence_radius_km` 等字段）。
2. **相对速度分解**：先把 v_rel 投影到中点切平面（扣除径向分量），再沿
   边界法向分解；边界法向近似取 plate_A 质心 → plate_B 质心方向（投影到切平面）。
3. **分类**：按 `velocity_threshold_cm_yr`（默认 0.5 cm/yr）划分
   convergent / divergent / transform / inactive，并按两侧地壳组合细化
   汇聚子类型（`subduction_type`）。
4. **边界链追踪**：将共享节点的同类边界段贪心连成链（`BoundaryChain`），
   供山脉走向、海沟线等线性特征生成使用。

> **Cortial 2019 俯冲上隆公式**（详见
> [knowledge/geology/cortial_2019_notes.md](../knowledge/geology/cortial_2019_notes.md) §D.4）：
> $u_j(p) = u_0 \cdot f(d) \cdot g(v) \cdot h(\tilde{z})$
> 其中 $u_0 = 0.6$ mm/y, $r_s = 1800$ km, $h(\tilde{z}) = \tilde{z}^2$。
> 我们的 §6 地形合成使用类似的高斯衰减函数，但简化为距离的指数衰减。
> 实现时间演化后（§17），应切换到 Cortial 的完整公式。

### 参数表

| 参数 | 默认值 | 范围 | 物理含义 |
|------|--------|------|----------|
| `boundary_influence_km` | 500.0 | 100 – 2000 | 边界效应影响半径 |
| `velocity_threshold_cm_yr` | 0.5 | 0.1 – 2.0 | 活动/非活动阈值 |

---

## 6. 阶段 5: 地形合成

节点高程 = 双峰基准 + 边界构造效应 + 热点隆起 + 多频 3D fBm × 内部调制
（+ 潮汐形变，仅潮汐锁定天体）。

> 地球物理依据与公式已上浮至
> [knowledge/geology/terrain_synthesis.md](../knowledge/geology/terrain_synthesis.md)：
> 双峰高程分布依据（§1）、三类边界剖面公式与速率因子汇总表（§2）、
> 距边界粗糙度调制（§2）、fBm octave 物理尺度表（§3）、热点/地幔柱高斯隆起
> 与高程合成叠加式（§6），以及内陆古造山带/山间盆地的地貌学依据（§4.3）。

**实现要点**（`terrain_synthesizer.py`，策略由 `terrain_algorithm` 配置键选择）：

1. **基准高程**：按地壳类型双峰高斯分配——continental `normal(850, 200)`、
   oceanic `normal(-3800, 500)`，mixed 按局部噪声二选一；每板块再叠加
   均匀偏移 ±`plate_elevation_spread_m`。
2. **边界效应**：`_asymmetric_boundary_effects` 按边界类型叠加高斯剖面
   （σ 由 `boundary_influence_km` 控制，振幅 × min(|v_n|/10, 1) 速率因子）。
   **沿弧分段调制（2026-08-06，日本列岛式岛链）**：在垂直剖面之上叠加
   ~800 km 波长的沿弧 fBm 调制：隆起幅度系数 ∈ [−0.25, 1.35]、带宽度 ×0.7–1.3。
   高值段成主岛/山结，中值段成小岛/浅滩，负值段沉降为弧间断陷海——汇聚带不再
   是均匀缎带。
3. **距边界距离**：多源 BFS 沿邻接图传播（球面距离 = 角距离 × 半径），
   结果同时用于粗糙度调制与 `distance_to_boundary_km` 输出字段。
4. **fBm**：3D Simplex 在节点 (x, y, z) 上采样（无投影畸变、无极点接缝），
   使用 Numba JIT 噪声内核（见 §15 实测修正：~60s → ~2s）。
5. **热点/地幔柱**：宽尺度高斯隆起 + 可选中央破火山口凹陷。
6. **合成**：按上述叠加式逐节点求和，`interior_factor` 使板块内部噪声稍大
   （大陆内部高原/盆地）。

### 参数表

| 参数 | 默认值 | 范围 | 物理含义 |
|------|--------|------|----------|
| `continental_elev_m` | 850 | 400 – 1500 | 大陆基准高程 |
| `oceanic_elev_m` | -3800 | -5000 – -2000 | 海底基准高程 |
| `convergent_amp_m` | 2500 | 1000 – 5000 | 汇聚边界山脉振幅 |
| `divergent_amp_m` | 1000 | 500 – 2000 | 离散边界山脊振幅 |
| `boundary_influence_km` | 500 | 100 – 2000 | 边界效应影响半径 |
| `noise_amplitude_m` | 600 | 200 – 1500 | fBm 噪声振幅 |
| `noise_octaves` | 6 | 3 – 8 | fBm octave 数 |
| `noise_persistence` | 0.5 | 0.3 – 0.7 | fBm 振幅衰减率 |
| `noise_lacunarity` | 2.0 | 1.5 – 3.0 | fBm 频率增长率 |
| `noise_scale` | 2.0 | 0.5 – 5.0 | fBm 基础空间频率 |
| `interior_boost` | 0.3 | 0.0 – 0.5 | 板块内部噪声增强 |

### 6.7 内部地貌：古造山带、山间盆地与裂谷

板块内部（距边界 >600 km 的大陆区域）放置 1–3 条线性构造带，模拟
古生代/中生代造山带残余（乌拉尔、阿巴拉契亚型）和裂谷臂。
地貌学依据（造山带沿走向高度变化、山间断陷盆地实例、裂谷臂）已上浮至
[knowledge/geology/terrain_synthesis.md](../knowledge/geology/terrain_synthesis.md) §4.3。

**实现要点**：

- **沿走向调制**：每条 belt 用 1D simplex 噪声沿大圆弧采样，调制各段振幅
  （`noise2(t × 8, belt_seed)`，振幅 ∈ [base × 0.3, base × 1.7]），
  造山带呈高峰 + 鞍部而非均匀脊线。
- **山间盆地**：沿走向噪声低于阈值时（`interior_basin_chance`）该段成为
  断陷盆地，深度上限 `interior_basin_depth_max_m`（部分盆底低于海平面）。
- **裂谷**：30% 概率/板块，独立线性凹陷（深 300–800 m，σ=40–100 km），
  同样使用沿走向深度调制。

### 内部地貌参数

| 参数 | 默认值 | 范围 | 含义 |
|------|--------|------|------|
| `interior_orogeny_count` | 2 | 0–5 | 基准 belt 数，随 inland cell 数缩放（每 800 cell +1），硬上限 4 |
| `interior_height_variation` | 0.7 | 0–1 | 沿走向高度变化强度 |
| `interior_basin_chance` | 0.25 | 0–0.5 | 山间盆地出现概率 |
| `interior_basin_depth_max_m` | 600 | 100–1500 | 盆地最大沉降深度 |

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

## 8. 阶段 7: 气候模拟

气候模拟在 CVT 网格上进行，利用图的邻接关系进行空间传播（风场、水汽输送）。

> 物理公式已上浮至知识库（去重，不再于本文重复）：
>
> - **温度（原 §8.1）**：EBM 平衡温度、温室增温、纬度梯度（sin²φ）、
>   海拔递减率、季节变化 →
>   [knowledge/climatology/energy_balance.md](../knowledge/climatology/energy_balance.md) §1–5
> - **风场（原 §8.2）**：科里奥利参数、三胞环流、地转风、温度→气压耦合 →
>   [knowledge/climatology/atmospheric_circulation.md](../knowledge/climatology/atmospheric_circulation.md)
> - **降水（原 §8.3）**：海洋蒸发 → BFS 水汽平流 → 地形雨/雨影、ITCZ 季节迁移 →
>   [knowledge/climatology/energy_balance.md](../knowledge/climatology/energy_balance.md) §7
> - **洋流（原 §8.4）**：Ekman 45° 偏转、西边界强化、热输送 →
>   [knowledge/climatology/ocean_currents.md](../knowledge/climatology/ocean_currents.md)
> - **Köppen 分类（原 §8.5 / 附录 A.5）**：五主群 + 亚型阈值 →
>   [knowledge/climatology/koppen_classification.md](../knowledge/climatology/koppen_classification.md)

**实现要点**（`map/climate_simulator.py::simulate_climate`；物理常数与纯函数在
`engine/climate_physics.py`；模块架构见 `design/climate-engine.md`）：

1. **温度**（stage 1）：平衡黑体 → 纬度梯度 → 海拔递减率 → 季节极值，
   写入 cell 的 `temperature_C` 与 1 月/7 月温度。
2. **风场**（stage 2）：0.4× 地转风 + 0.6× 三胞风叠加，再经地形阻挡
   （`wind_blocking_height_m` 以上山体衰减风速）。
3. **降水**（stage 3）：海洋蒸发初始化 → 沿风向多轮 BFS 平流
   （`_MOISTURE_ADVECTION_STEPS = 12`）→ 地形抬升凝结
   （效率 `orographic_efficiency`）→ 雨影，另加 ITCZ/季风/局地对流/
   副热带高压抑制修正。
4. **Köppen 分类**（stage 4）：由年均/季节温度 + 降水映射 `koppen_class`。

### 参数表

| 参数 | 默认值 | 范围 | 物理含义 |
|------|--------|------|----------|
| `lapse_rate_c_km` | 6.5 | 4.0 – 10.0 | 温度海拔递减率 |
| `lat_gradient_c` | 45.0 | 20 – 70 | 赤道-极地温差 |
| `atmosphere_factor` | 1.0 | 0.3 – 3.0 | 大气保温系数 |
| `evaporation_base_mm` | 2000 | 500 – 4000 | 热带海洋年蒸发量 |
| `orographic_efficiency` | 0.5 | 0.2 – 0.8 | 地形降水效率 |
| `itcz_lag_days` | 30 | 0 – 60 | ITCZ 滞后天数 |
| `wind_blocking_height_m` | 3000 | 1500 – 5000 | 风场阻挡高度 |

---

## 9. 阶段 8: 河流与水文

### 9.1 流向确定

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

### 9.2 汇水累积

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

### 9.3 河流分类

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

### 9.4 河流网络提取

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

### 9.5 湖泊与内流盆地

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

### 参数表

| 参数 | 默认值 | 范围 | 物理含义 |
|------|--------|------|----------|
| `min_river_accum_km2` | 1000 | 100 – 10000 | 河流最小汇水面积 |
| `river_order_thresholds` | {1:100, 2:1K, 3:10K, 4:100K} | — | 河流分级阈值 |
| `lake_min_area_km2` | 10 | 1 – 100 | 最小湖泊面积 |
| `evaporation_rate_mm` | 800 | 300 – 2000 | 简化蒸发率 |

---

## 10. 阶段 9: 侵蚀（简化）

### 10.1 热侵蚀 (Thermal Erosion)

热侵蚀通过减小超过安息角（talus angle）的坡度来实现：

```python
def thermal_erosion(
    mesh: CVTMesh,
    elevation_m: np.ndarray,
    talus_angle_deg: float = 35.0,
    iterations: int = 10,
    relaxation: float = 0.5,
) -> np.ndarray:
    """Iterative thermal erosion smoothing.

    For each edge where the slope exceeds the talus angle,
    material is transferred from higher to lower node.

    Args:
        talus_angle_deg: maximum stable slope angle
        iterations: number of relaxation passes
        relaxation: fraction of excess to transfer per pass (0-1)

    Returns:
        Modified elevation array.
    """
    elev = elevation_m.copy()
    talus_rad = radians(talus_angle_deg)
    tan_talus = tan(talus_rad)

    for _ in range(iterations):
        for i in range(mesh.num_nodes):
            for n in mesh.adjacency[i]:
                dist_km = angular_distance_xyz(mesh.nodes[i], mesh.nodes[n]) * mesh.radius_km
                if dist_km < 1e-6:
                    continue
                slope = abs(elev[i] - elev[n]) / (dist_km * 1000)  # m/m

                if slope > tan_talus:
                    excess = (slope - tan_talus) * dist_km * 1000  # meters
                    transfer = excess * relaxation * 0.5
                    if elev[i] > elev[n]:
                        elev[i] -= transfer
                        elev[n] += transfer
                    else:
                        elev[n] -= transfer
                        elev[i] += transfer

    return elev
```

### 10.2 视觉水蚀 (Visual Water Erosion)

基于汇水累积量对法线方向施加微扰，产生沟壑视觉效果：

```python
def visual_water_erosion(
    mesh: CVTMesh,
    elevation_m: np.ndarray,
    flow_accum: np.ndarray,
    strength: float = 0.3,
) -> np.ndarray:
    """Apply visual water erosion based on flow accumulation.

    High-accumulation channels get slightly deeper (carved),
    adjacent ridges get slightly higher.

    This is a visual approximation — real hydraulic erosion
    requires iterative simulation (deferred to Gaea).

    Returns:
        Modified elevation.
    """
    # Normalized accumulation (log scale)
    log_accum = np.log1p(flow_accum)
    log_accum /= log_accum.max() + 1e-10

    # Carving: deeper channels where accumulation is high
    # But only on slopes (flat areas don't erode as much)
    slope = compute_node_slopes(mesh, elevation_m)
    carving = strength * 200 * log_accum * slope  # up to 200m carving

    elev = elevation_m - carving

    # Smooth slightly to avoid sharp artifacts
    elev = graph_laplacian_smooth(mesh, elev, iterations=2, alpha=0.3)

    return elev
```

### 10.3 为何简化

完整的水力学侵蚀（hydraulic erosion）需要：

1. **降雨模拟**：每个时间步在每个节点添加水量
2. **流量传播**：水在节点间流动，携带泥沙
3. **侵蚀/沉积**：根据流量和坡度计算侵蚀/沉积量
4. **蒸发**：水量蒸发，留下沉积物
5. **迭代收敛**：数千到数万次迭代

这个过程在 100K 节点上可能需要数分钟。而 Gaea 的 Erosion2 节点已经实现了
高度优化的 GPU 水力学侵蚀。因此：

- **CVT 管线**：热侵蚀 + 视觉水蚀（快速，~10s，足够支撑气候/生态推演）
- **Gaea 精细化**：在选定区域使用完整水力学侵蚀（慢，~5min，提供米级细节）

### 参数表

| 参数 | 默认值 | 范围 | 物理含义 |
|------|--------|------|----------|
| `talus_angle_deg` | 35.0 | 25 – 45 | 安息角 |
| `thermal_iterations` | 10 | 3 – 50 | 热侵蚀迭代次数 |
| `thermal_relaxation` | 0.5 | 0.1 – 1.0 | 松弛系数 |
| `water_erosion_strength` | 0.3 | 0.0 – 1.0 | 视觉水蚀强度 |
| `erosion_smoothing` | 2 | 0 – 5 | 水蚀后 Laplacian 平滑 |

---

## 11. 阶段 10: 植被与生态（简述）

植被/生态分类是地形管线的下游消费者，输入为 `(temperature, precipitation, elevation)`。

### 气候 → 植被映射

| Köppen 类型 | 植被类型 | 覆盖率 |
|-------------|----------|--------|
| Af (热带雨林) | 密林 | 90-100% |
| Aw (热带草原) | 草地+稀树 | 60-80% |
| BWh (热沙漠) | 荒漠 | 0-10% |
| BSk (冷草原) | 草原 | 30-50% |
| Cfa (亚热带湿润) | 阔叶林 | 70-90% |
| Cs (地中海) | 硬叶林/灌木 | 50-70% |
| Df (大陆性湿润) | 针阔混交林 | 60-80% |
| Ds/Dw (大陆性干燥) | 针叶林 (泰加) | 50-70% |
| ET (苔原) | 苔藓/地衣 | 10-30% |
| EF (冰原) | 无 | 0% |

### 土壤肥力噪声

在植被覆盖率基础上叠加 Perlin 噪声模拟土壤肥力差异：

```python
def compute_vegetation(
    koppen: list[str],
    mesh: CVTMesh,
    seed: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute vegetation density and soil fertility.

    Returns:
        (veg_density, soil_fertility): both (N,) in [0, 1].
    """
    veg_density = np.array([VEG_MAP[k[:2]] for k in koppen])  # lookup table

    # Soil fertility: fBm noise modulated by vegetation
    fertility_noise = generate_fbm_on_cvt(mesh.nodes, seed, octaves=3)
    soil_fertility = 0.5 + 0.3 * veg_density + 0.2 * fertility_noise
    soil_fertility = np.clip(soil_fertility, 0, 1)

    return veg_density, soil_fertility
```

### Whittaker 生态群系分类

使用 Whittaker 图（温度-降水空间）进行精细分类：

```
年降水 (mm)
  4000 │ ┌─────────────────────────────────┐
       │ │  热带雨林 (Af)                    │
  3000 │ │                                  │
       │ ├──────────┐                       │
  2000 │ │  温带雨林  │  温带季雨林            │
       │ │  (Cfb)    │  (Cfa/Cwa)           │
  1000 │ ├────┐      ├──────────┐           │
       │ │草原 │ 落叶林│  针叶林   │           │
   500 │ │(BS)│(Cfb) │  (Df/Dw) │           │
       │ ├────┤      ├────┬─────┤           │
   250 │ │荒漠 │ 灌木  │苔原│ 极地 │           │
       │ │(BW)│      │(ET)│(EF) │           │
     0 └─┴────┴──────┴────┴─────┴───────────┘
       -10   0     10    20    30   年均温 (°C)
```

---

## 12. 阶段 11: 数据导出与可视化

### 12.1 等距圆柱投影导出

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

### 12.2 多投影支持

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

### 12.3 前端可视化

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

### 12.4 与 dreamulator 集成

CVT 管线输出直接对接现有 `MapManager` 和 `MapLayerRegistry`：

```python
# 创建/更新地图
manager = MapManager(world_dir)
manager.create_map(
    planet_id="gaia_m",
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
registry = MapLayerRegistry(planet_id="gaia_m")
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

## 13. 阶段 12: Gaea 局部精细化（可选）

### 13.1 何时使用

在以下场景使用 Gaea 精细化：

- 需要**米级**地形细节（如河谷剖面、悬崖纹理）
- 需要**逼真侵蚀纹理**（Gaea Erosion2 的物理模拟质量远超简化版）
- 生成用于**叙事描写**的地形细节（`/narrate` 技能引用）
- 导出高分辨率**纹理贴图**给 3D 渲染

### 13.2 区域选择

通过经纬度边界框选择精细化区域：

```yaml
# data/worlds/myworld/layers/geological/input/gaea_refine.yaml
refine_regions:
  - id: "grand_canyon_area"
    name: "大峡谷区域"
    lat_min: 35.0
    lat_max: 37.5
    lon_min: -113.5
    lon_max: -111.0
    target_resolution: 4096   # Gaea output resolution
    erosion_passes: 3

  - id: "himalaya_region"
    name: "喜马拉雅区域"
    lat_min: 26.0
    lat_max: 32.0
    lon_min: 78.0
    lon_max: 90.0
    target_resolution: 8192
    erosion_passes: 5
```

### 13.3 球极平面投影

将球面区域投影到平面高度图（用于 Gaea 导入）：

**球极平面投影 (Stereographic Projection)**：

```
设投影中心为 (φ₀, λ₀)，球面点为 (φ, λ)：

k = 2R / (1 + sin(φ₀)·sin(φ) + cos(φ₀)·cos(φ)·cos(λ - λ₀))

x = k · cos(φ) · sin(λ - λ₀)
y = k · (cos(φ₀)·sin(φ) - sin(φ₀)·cos(φ)·cos(λ - λ₀))
```

**优点**：
- 保角（conformal）：局部形状不变
- 圆变圆：圆形特征保持圆形
- 适合小区域（< ~30° 跨度）

```python
def stereographic_project(
    mesh: CVTMesh,
    elevation_m: np.ndarray,
    center_lat_deg: float,
    center_lon_deg: float,
    radius_deg: float,
    resolution: int = 4096,
) -> tuple[np.ndarray, dict]:
    """Project a spherical region to stereographic plane.

    Returns:
        (heightmap_2d, projection_params) for Gaea import.
    """
    lat0 = radians(center_lat_deg)
    lon0 = radians(center_lon_deg)

    # Select nodes within radius
    dist = angular_distance_from_center(mesh.nodes, lat0, lon0)
    mask = dist < radians(radius_deg)

    selected_nodes = mesh.nodes[mask]
    selected_elev = elevation_m[mask]

    # Stereographic projection
    lat = arcsin(clip(selected_nodes[:, 1], -1, 1))
    lon = arctan2(selected_nodes[:, 2], selected_nodes[:, 0])

    cos_c = sin(lat0)*sin(lat) + cos(lat0)*cos(lat)*cos(lon - lon0)
    k = 2 / (1 + cos_c)

    x = k * cos(lat) * sin(lon - lon0)
    y = k * (cos(lat0)*sin(lat) - sin(lat0)*cos(lat)*cos(lon - lon0))

    # Interpolate to regular grid
    grid_x = linspace(-x.max(), x.max(), resolution)
    grid_y = linspace(-y.max(), y.max(), resolution)
    heightmap = griddata(
        stack([x, y], axis=-1),
        selected_elev,
        meshgrid(grid_x, grid_y),
        method='cubic',
    )

    params = {
        "center_lat": center_lat_deg,
        "center_lon": center_lon_deg,
        "radius_deg": radius_deg,
        "resolution": resolution,
        "x_range": (float(-x.max()), float(x.max())),
        "y_range": (float(-y.max()), float(y.max())),
    }

    return heightmap, params
```

### 13.4 Gaea 处理

Gaea 图（graph）配置：

```
File (import heightmap)
  → Math (normalize to 0-1)
  → Erode (thermal + hydraulic)
  → Rivers (flow simulation)
  → Sea (water level)
  → Export (16-bit PNG + flow data)
```

Gaea 处理通过 CLI 或 Python API 自动化（如果 Gaea 提供 API）。
否则，导出高度图后手动在 Gaea 中处理，再导入结果。

### 13.5 回导

将 Gaea 输出的精细化高度图反向投影回 CVT 网格：

```python
def import_gaea_refinement(
    mesh: CVTMesh,
    gaea_heightmap: np.ndarray,
    projection_params: dict,
    elevation_m: np.ndarray,
    blend_radius_deg: float = 2.0,
) -> np.ndarray:
    """Import Gaea-refined data back into CVT mesh.

    Uses feathered blending at the boundary of the refined region
    to avoid sharp discontinuities.

    Returns:
        Updated elevation array.
    """
    lat0 = radians(projection_params["center_lat"])
    lon0 = radians(projection_params["center_lon"])

    # For each CVT node in the region, inverse-project and sample
    dist = angular_distance_from_center(mesh.nodes, lat0, lon0)
    in_region = dist < radians(projection_params["radius_deg"])

    refined_elev = elevation_m.copy()

    for i in np.where(in_region)[0]:
        # Inverse stereographic projection
        lat, lon = inverse_stereographic(
            mesh.nodes[i], lat0, lon0, projection_params
        )
        # Sample Gaea heightmap
        gaea_val = sample_heightmap(gaea_heightmap, lat, lon, projection_params)
        refined_elev[i] = gaea_val

    # Feathered blending at boundary
    blend_mask = (dist > radians(projection_params["radius_deg"] - blend_radius_deg)) & \
                 (dist < radians(projection_params["radius_deg"] + blend_radius_deg))
    for i in np.where(blend_mask)[0]:
        d = dist[i]
        r = radians(projection_params["radius_deg"])
        br = radians(blend_radius_deg)
        alpha = smoothstep((d - (r - br)) / (2 * br))
        refined_elev[i] = (1 - alpha) * refined_elev[i] + alpha * elevation_m[i]

    return refined_elev
```

---

## 14. 数据模型变更

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
    speed_multiplier: float = 1.0        # flood-fill speed

class BoundaryData(BaseModel):
    """Plate boundary segment."""
    plate_a: str
    plate_b: str
    boundary_type: str                   # convergent | divergent | transform
    subduction_type: str | None = None
    v_normal_m_yr: float
    v_tangential_m_yr: float
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
| `PlateVelocity` | **废弃**（替换为 Euler pole） | 不再使用平面速度 |
| `TectonicPlate` | 新增 `euler_pole`, `omega_rad_yr` | 球面运动学 |
| `MapLayerType` | 新增 `FLOW_ACCUMULATION`, `WIND`, `KOPPEN` | 新图层类型 |

### 新增模块文件

| 模块 | 路径 | 职责 |
|------|------|------|
| `cvt_models.py` | `src/dreamulator/map/` | CVT 数据模型 |
| `cvt_generator.py` | `src/dreamulator/map/` | Fibonacci + Lloyd + 网格构建 |
| `plate_generator.py` | `src/dreamulator/map/` | 种子选取 + 洪水填充 + 地壳类型 |
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

## 15. 性能考量

> **实测修正（2026-08-03，perf/profiling-and-optimization 分支）**：
> 本节原估算（总计 ~70s）偏差较大——实测 gaia-m（100K 胞、构造 ×50）全量构建
> **532s**（geological 388s + climate 143s + astronomy <1s）。
> pyfastnoise 路线已失效：**该包不在 PyPI**（uv 解析失败、无 py3.12 wheel）；
> `opensimplex.noise3array` 是纯 Python 循环（21µs/点，仅比标量 44µs/次快 2 倍）。
> 噪声后端改为 **Numba JIT 内核**。详见 `private/plans/perf-profiling-and-optimization.md`。

### 瓶颈分析

| 操作 | 复杂度 | 100K 节点耗时 | 瓶颈原因 |
|------|--------|--------------|----------|
| Fibonacci lattice | O(N) | <0.01s | 无 |
| Lloyd relaxation (×8) | O(k·N·log N) | ~8s | SphericalVoronoi 构建 |
| 洪水填充板块 | O(N·log N) | ~1s | 优先队列 |
| 欧拉极速度场 | O(N) | <0.1s | 向量化叉积 |
| 边界检测 | O(N) | <0.1s | 邻接扫描 |
| 边界效应计算 | O(N·B) | ~15s | B = 边界节点数 |
| fBm 噪声 (6+3 oct) | O(N·O) | ~60s（纯 Python 实测）/ ~2s（Numba JIT 预期） | 逐点 Simplex（实测 44µs/次，约 140 万次调用） |
| 海平面二分 | O(N·log(precision)) | <0.01s | 无 |
| 温度计算 | O(N) | <0.1s | 向量化 |
| 风场计算 | O(N·k) | ~2s | k = 平均邻居数 |
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

## 16. 已知限制与未来工作

### 当前限制

1. **简化侵蚀**：热侵蚀 + 视觉水蚀无法产生真实的河谷网络和沉积扇。
   需要完整水力学侵蚀的区域依赖 Gaea 精细化。

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
| A.1 Haversine 角距离 | 大圆距离公式 | [cvt_mesh.md](../knowledge/geology/cvt_mesh.md) §角距离 |
| A.2 Fibonacci 球面格点 | 极角/方位角 + 笛卡尔坐标 | [cvt_mesh.md](../knowledge/geology/cvt_mesh.md) §Fibonacci 球面螺旋 |
| A.3 欧拉极运动学 | v = ω × P、速度大小、相对速度与 v_n/v_t 分解 | [plate_tectonics.md](../knowledge/geology/plate_tectonics.md) §欧拉极运动学 / §边界检测与分类 |
| A.4 fBm | octave 叠加公式与归一化 | [terrain_synthesis.md](../knowledge/geology/terrain_synthesis.md) §3 fBm 噪声 |
| A.5 Köppen 气候阈值 | 五主群 + 亚型判据 | [koppen_classification.md](../knowledge/climatology/koppen_classification.md) |
| A.7 球面多边形面积 | 球面角盈公式 | [cvt_mesh.md](../knowledge/geology/cvt_mesh.md) §Cell 面积 |

**A.6 汇水累积**（水文学知识文档尚待建立，见 `knowledge/geology/CLAUDE.md`
规划清单；实现见 §9.2）：

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
| `_compute_continent_field()` | ❌ 废弃 | 被 CVT 基准高程 + 洪水填充替代 |
| `_elliptical_gaussian()` | ⚠️ 可选保留 | 可用于 CVT 上的局部特征叠加 |
| `_compute_base_elevation()` | ⚠️ 改造 | 改为基于地壳类型的双峰分配 |
| `_compute_tidal_deformation()` | ✅ 直接复用 | P₂ Legendre 潮汐形变 |
| `_generate_plates()` | ⚠️ 重大改造 | Voronoi 最近邻 → 洪水填充；Euler 极逻辑保留 |
| `_compute_boundary_effects()` | ⚠️ 改造 | 边界检测改为图邻接扫描；效应公式保留 |
| `_compute_convergence_rate()` | ⚠️ 改造 | 保留 v = ω × P 核心逻辑，修正边界法向计算 |
| `_plate_velocity_at()` | ✅ 直接复用 | 刚体旋转 v = ω × r |
| `_compute_hotspot_effects()` | ⚠️ 改造 | 从网格采样改为 CVT 节点采样 |
| `_compute_noise_detail()` | ⚠️ 改造 | 振幅调制逻辑保留，采样改为 CVT |
| `SphericalHeightmapGenerator.generate()` | ❌ 废弃 | 被 CVT 管线的分阶段函数替代 |
| `generate_cubemap_faces()` | ❌ 废弃 | CVT 管线不需要立方体投影 |
| `ContinentFeature` | ⚠️ 可选保留 | 用于手动指定大陆特征 |
| `HotspotFeature` | ✅ 直接复用 | 热点配置 |
| `PlateSeed` | ⚠️ 改造 | 增加 `speed_multiplier` 字段 |
| `PlanetConfig` | ⚠️ 重大改造 | 增加 CVT 参数，移除栅格相关参数 |
| `make_equirect_grid()` | ✅ 保留 | 仅用于导出阶段 |

### 来自 `src/dreamulator/map/` 模块

| 函数/模型 | 复用状态 | 说明 |
|-----------|----------|------|
| `VoronoiCell` | ❌ 废弃 | 替换为 `CVTNode` |
| `VoronoiNetwork` | ❌ 废弃 | 替换为 `CVTMeshData` |
| `TectonicPlate` | ⚠️ 扩展 | 新增 Euler pole 字段 |
| `PlateType` | ✅ 直接复用 | 枚举值不变 |
| `PlateVelocity` | ❌ 废弃 | 替换为 Euler pole |
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

- [ ] 创建 `src/dreamulator/map/plate_generator.py` — 种子 + 洪水填充
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

### Phase 5: 气候引擎（2-3 周）

- [ ] 创建 `src/dreamulator/engine/climate_engine.py`
- [ ] 实现温度模型（纬度 + 海拔 + 季节）
- [ ] 实现简化风场（地转风 + 环流单元）
- [ ] 实现 BFS 降水传播
- [ ] 实现简化洋流
- [ ] 实现 Köppen 分类
- [ ] 单元测试：温度-纬度相关性、降水-地形关系
- [ ] 验证：与地球 Köppen 地图对比

### Phase 6: 水文（1-2 周）

- [ ] 创建 `src/dreamulator/engine/hydrology_engine.py`
- [ ] 实现流向确定
- [ ] 实现汇水累积（拓扑排序）
- [ ] 实现河流分类和网络提取
- [ ] 实现湖泊和内流盆地检测
- [ ] 单元测试：水守恒（所有陆地水最终到达海洋或内陆湖）
- [ ] 验证：河流网络与 Azgaar 生成器对比

### Phase 7: 侵蚀（1 周）

- [ ] 实现热侵蚀（迭代松弛）
- [ ] 实现视觉水蚀
- [ ] 单元测试：侵蚀后高程范围、坡度分布
- [ ] 性能基准：100K 节点 < 15s

### Phase 8: 生态 + 导出（1 周）

- [ ] 实现 Whittaker 生态分类
- [ ] 实现等距圆柱投影导出
- [ ] 实现多投影导出（Lambert, Hammer）
- [ ] 与 MapManager / MapLayerRegistry 集成
- [ ] 前端 Three.js 可视化更新

### Phase 9: Gaea 精细化（0.5 周）

- [ ] 实现球极平面投影导出
- [ ] 实现 Gaea 结果回导 + 羽化混合
- [ ] 文档：Gaea 图模板

### Phase 10: 集成测试与文档（1 周）

- [ ] 端到端测试：从 world.yaml → 完整地形
- [ ] 性能基准报告
- [ ] 更新 CLAUDE.md 和 API 文档
- [ ] 更新 `scripts/export_static.py` + `staticClient.ts` + `client.ts`（静态导出同步）

### 依赖关系图

```
Phase 0 (基础设施)
  ├── Phase 1 (板块)
  │     ├── Phase 2 (运动学)
  │     │     └── Phase 3 (地形合成)
  │     │           ├── Phase 4 (海平面)
  │     │           │     ├── Phase 5 (气候)
  │     │           │     │     ├── Phase 6 (水文)
  │     │           │     │     │     └── Phase 7 (侵蚀)
  │     │           │     │     └── Phase 8 (生态 + 导出)
  │     │           │     └── Phase 8 (生态 + 导出)
  │     │           └── Phase 9 (Gaea 精细化)
  │     └── Phase 3 (地形合成)
  └── Phase 10 (集成测试) ← 所有 Phase 完成后
```

**关键路径**: Phase 0 → 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 10

预计总工期：**8-12 周**（单人全职开发）

---

## 17. 时间演化与威尔逊循环（进阶）

> **状态**: 进阶功能规划。基础管线（§2–§12）生成静态快照；本节描述如何引入时间变量 $t$，
> 使 CVT 网格成为"活着的、具有地质记忆的星球模拟器"。
> 核心参考：Cortial et al. 2019（见[附录 D](#附录-d-论文解读--cortial-et-al-2019-procedural-tectonic-planets)）
> 及对话记录中的威尔逊循环讨论。

### 17.1 核心原则：固定网格 + 属性平流

**绝对不要在时间轴上物理移动 CVT 的顶点！**

移动顶点意味着每一步都需要进行昂贵的 Delaunay 重构。Cortial 2019 和现代气候模型
均采用**固定背景场 + 半拉格朗日平流（Semi-Lagrangian Advection）**：

1. **网格固定**：100K（或更多）CVT 节点在整个推演中永远不动，它们是行星表面的"固定观测站"
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

### 17.2 地壳属性元组

每个 CVT cell 维护以下随时间演化的状态：

| 属性 | 符号 | 类型 | 说明 |
|------|------|------|------|
| 所属板块 | `Plate_ID` | int | 当前所属板块编号 |
| 地壳类型 | `Crust_Type` | enum | continental / oceanic / craton |
| 地壳厚度 | `Thickness` | float (km) | 陆壳 ~35-50km，洋壳 ~7km |
| 地壳年龄 | `Age` | float (My) | 洋壳自洋中脊创生以来的年龄 |
| 造山年龄 | `Orogeny_Age` | float (My) | 陆壳自上次造山运动以来的年龄 |
| 褶皱方向 | `Fold_Dir` | 3D vector | 局部褶皱/折叠方向（用于放大阶段） |

### 17.3 威尔逊循环四大过程

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

### 17.4 随时间变化的行星物理参数

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

### 17.5 完整时间步进循环

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

### 17.6 与基础管线的关系

| 功能 | 基础管线 (§2-§12) | 时间演化 (§17) |
|------|-------------------|----------------|
| 板块分配 | 一次性洪水填充 | 随裂解/拼合动态变化 |
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
> [knowledge/geology/cortial_2019_notes.md](../knowledge/geology/cortial_2019_notes.md)。

