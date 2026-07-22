# 行星地形生成管线技术参考

> **状态**: 设计草案 · 2026-07-21

> **本文档是 [地图工作流指南](map-workflow.md) 的技术参考**。工作流指南描述"怎么做"，本文档解释"为什么这么做"以及各阶段的算法细节。

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
                        │  Random Seeds → Flood-Fill BFS (variable speed)          │
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

### 3.2 洪水填充生长

每个板块从其种子出发，通过 BFS 向外扩张。**可变速度**模拟不同板块的扩张能力差异：

```python
def flood_fill_plates(
    mesh: CVTMesh,
    seeds: list[int],
    speeds: list[float],        # per-plate growth speed (0.5 - 2.0)
    rng,
) -> np.ndarray:
    """Assign each CVT node to a plate via competitive flood fill.

    Variable speed means some plates grow faster than others,
    producing irregular, non-convex boundaries.

    Returns:
        plate_ids: (N,) int array, one plate ID per node.
    """
    plate_ids = np.full(mesh.num_nodes, -1, dtype=np.int32)
    # Priority queue: (arrival_time, node_id, plate_id)
    heap = []

    for i, seed in enumerate(seeds):
        plate_ids[seed] = i
        heapq.heappush(heap, (0.0, seed, i))

    while heap:
        time, node, plate = heapq.heappop(heap)
        # Skip if already claimed by another plate
        if plate_ids[node] != plate:
            continue
        # Expand to neighbors
        for neighbor in mesh.adjacency[node]:
            if plate_ids[neighbor] >= 0:
                continue
            # Edge weight: angular distance / plate speed
            edge_len = angular_distance_xyz(mesh.nodes[node], mesh.nodes[neighbor])
            # Add small random perturbation for irregularity
            jitter = 1.0 + rng.uniform(-0.1, 0.1)
            arrival = time + (edge_len / speeds[plate]) * jitter

            plate_ids[neighbor] = plate
            heapq.heappush(heap, (arrival, neighbor, plate))

    return plate_ids
```

**速度范围**：0.5× – 2.0× 基准速度。速度越快的板块占据的面积越大。

### 3.3 地壳类型分配

每个板块分配地壳类型（大陆/大洋/混合）：

```python
def assign_crust_types(
    plate_ids: np.ndarray,
    num_plates: int,
    rng,
    continental_fraction: float = 0.35,
) -> list[str]:
    """Assign crust types to plates.

    Earth-like distribution: ~35% continental, ~65% oceanic.
    Mixed plates have both continental and oceanic regions.
    """
    types = []
    for i in range(num_plates):
        r = rng.random()
        if r < continental_fraction * 0.6:
            types.append("continental")
        elif r < continental_fraction * 0.6 + continental_fraction * 0.4:
            types.append("mixed")
        else:
            types.append("oceanic")
    return types
```

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

### 3.5 与现有模型集成

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

每个板块的运动由一个**欧拉极**（Euler pole）描述——球面上的一个旋转轴。
在惯性参考系中，板块 P 绕欧拉极 `ê` 以角速度 ω 做刚体旋转。

```python
def assign_euler_poles(
    num_plates: int,
    mesh: CVTMesh,
    plate_seeds: list[int],
    rng,
) -> list[EulerPole]:
    """Assign random Euler poles to each plate.

    The Euler pole is a random unit vector (rotation axis).
    For more realism, bias it perpendicular to the plate's
    "dominant motion direction".
    """
    poles = []
    for i in range(num_plates):
        # Random rotation axis on unit sphere
        axis = rng.standard_normal(3)
        axis /= linalg.norm(axis)
        poles.append(EulerPole(axis=axis, omega=0.0))  # omega set in next step
    return poles
```

### 4.2 角速度

角速度 ω 控制板块运动速率。地球板块运动速度约 1-10 cm/yr。

```
ω = v / R

v: 板块线速度 (m/yr)
R: 行星半径 (m)
```

| 速度 (cm/yr) | ω (rad/yr) | 描述 |
|--------------|------------|------|
| 1.0 | 1.57 × 10⁻⁹ | 慢速（如非洲板块） |
| 5.0 | 7.85 × 10⁻⁹ | 中等（如北美板块） |
| 10.0 | 1.57 × 10⁻⁸ | 快速（如太平洋板块） |

```python
def assign_angular_velocities(
    poles: list[EulerPole],
    rng,
    speed_range_cm_yr: tuple = (1.0, 10.0),
    radius_km: float = 6371.0,
) -> None:
    """Assign angular velocities to Euler poles."""
    for pole in poles:
        v_cm_yr = rng.uniform(*speed_range_cm_yr)
        v_m_yr = v_cm_yr * 0.01
        pole.omega = v_m_yr / (radius_km * 1000)  # rad/yr
```

### 4.3 速度场

给定欧拉极 `ê` 和角速度 ω，球面上任意点 P 的速度由刚体旋转公式给出：

```
v(P) = ω · (ê × P)
```

其中 P 是单位球面上的位置矢量，`×` 是向量叉积。

**推导**：

设旋转角速度矢量为 **Ω** = ω · **ê**（方向为旋转轴，大小为角速度）。
对于球面上位置矢量 **r**（|**r**| = R），速度为：

```
v = Ω × r
```

速度大小：`|v| = ω · R · sin(α)`，其中 α 是 P 到欧拉极的角距离。
在欧拉极处速度为零，在 90° 处速度最大。

```python
def compute_velocity_field(
    nodes_xyz: np.ndarray,       # (N, 3) unit sphere positions
    euler_axis: np.ndarray,      # (3,) unit rotation axis
    omega: float,                # angular velocity (rad/yr)
    radius_km: float = 6371.0,
) -> np.ndarray:
    """Compute velocity at each node.

    Returns:
        (N, 3) velocity vectors in m/yr (tangent to sphere).
    """
    omega_vec = euler_axis * omega  # (3,)
    # v = omega_vec × r  for each node
    velocities = np.cross(omega_vec, nodes_xyz)  # (N, 3) via broadcasting
    # Scale: unit sphere → real radius
    velocities *= radius_km * 1000  # m/yr
    return velocities
```

### 4.4 参考系

上述速度在惯性参考系（"地幔固定"框架）中定义。可选地，可以减去全球净旋转
（net rotation），使平均角动量为零：

```python
def remove_net_rotation(
    all_velocities: np.ndarray,   # (num_plates, N, 3)
    areas: np.ndarray,            # (N,) cell areas
) -> np.ndarray:
    """Remove net lithospheric rotation (no-net-rotation frame)."""
    # Weighted mean velocity
    weights = areas / areas.sum()
    mean_v = (all_velocities * weights[np.newaxis, :, np.newaxis]).sum(axis=(0, 1))
    return all_velocities - mean_v
```

### 参数表

| 参数 | 默认值 | 范围 | 物理含义 |
|------|--------|------|----------|
| `speed_min_cm_yr` | 1.0 | 0.1 – 5.0 | 最慢板块速度 |
| `speed_max_cm_yr` | 10.0 | 5.0 – 20.0 | 最快板块速度 |
| `remove_net_rotation` | True | bool | 是否移除净旋转 |

---

## 5. 阶段 4: 边界检测与分类

### 5.1 邻接扫描

遍历 CVT 网格的所有边，检测两个端点属于不同板块的边——这些就是**板块边界**。

```python
def detect_boundaries(
    mesh: CVTMesh,
    plate_ids: np.ndarray,
) -> list[BoundarySegment]:
    """Scan all edges to find plate boundaries.

    Returns list of BoundarySegment, each describing one
    boundary edge between two plates.
    """
    segments = []
    seen_edges = set()

    for node_a in range(mesh.num_nodes):
        for node_b in mesh.adjacency[node_a]:
            edge_key = (min(node_a, node_b), max(node_a, node_b))
            if edge_key in seen_edges:
                continue
            seen_edges.add(edge_key)

            if plate_ids[node_a] != plate_ids[node_b]:
                segments.append(BoundarySegment(
                    node_a=node_a,
                    node_b=node_b,
                    plate_a=plate_ids[node_a],
                    plate_b=plate_ids[node_b],
                    midpoint=(mesh.nodes[node_a] + mesh.nodes[node_b]) / 2,
                ))

    return segments
```

### 5.2 相对速度

对于每个边界段，计算两侧板块在边界中点处的相对速度：

```python
def compute_relative_velocity(
    midpoint: np.ndarray,         # (3,) position on unit sphere
    euler_a: EulerPole,
    euler_b: EulerPole,
    radius_km: float,
) -> np.ndarray:
    """v_rel = v_A(P) - v_B(P) at boundary midpoint P."""
    v_a = np.cross(euler_a.axis * euler_a.omega, midpoint) * radius_km * 1000
    v_b = np.cross(euler_b.axis * euler_b.omega, midpoint) * radius_km * 1000
    return v_a - v_b  # m/yr
```

### 5.3 速度分解

将相对速度分解为法向分量（垂直于边界）和切向分量（平行于边界）：

```python
def decompose_velocity(
    v_rel: np.ndarray,            # (3,) relative velocity
    boundary_normal: np.ndarray,  # (3,) unit normal (tangent to sphere, ⊥ boundary)
    midpoint: np.ndarray,         # (3,) position (for radial projection)
) -> tuple[float, float]:
    """Decompose v_rel into normal and tangential components.

    Project velocities onto the tangent plane at midpoint first.

    Returns:
        (v_n, v_t): normal (convergent+) and tangential (transform) components.
    """
    # Project v_rel onto tangent plane (remove radial component)
    v_tangent = v_rel - np.dot(v_rel, midpoint) * midpoint

    # Normal component (along boundary normal, in tangent plane)
    v_n = np.dot(v_tangent, boundary_normal)

    # Tangential component (remainder)
    v_t_vec = v_tangent - v_n * boundary_normal
    v_t = linalg.norm(v_t_vec)

    return float(v_n), float(v_t)
```

**边界法向量**近似为从 plate_A 质心指向 plate_B 质心的方向（投影到切平面）。

### 5.4 边界类型

根据法向分量 `v_n` 的符号和大小分类：

| 条件 | 类型 | 地质效应 |
|------|------|----------|
| `v_n > threshold` | **Convergent** (汇聚) | 山脉、海沟、火山弧 |
| `v_n < -threshold` | **Divergent** (离散) | 洋中脊、裂谷 |
| `\|v_n\| ≤ threshold` 且 `v_t > threshold` | **Transform** (转换) | 走滑断层 |
| `\|v_n\| ≤ threshold` 且 `v_t ≤ threshold` | **Inactive** (非活动) | 无明显效应 |

其中 `threshold ≈ 0.5 cm/yr`（地质不活跃阈值）。

**子类型细化**（汇聚边界）：

| 板块组合 | 子类型 | 典型地貌 |
|----------|--------|----------|
| 大陆-大陆 | Continental collision | 高原（喜马拉雅） |
| 大洋-大洋 | Oceanic subduction | 岛弧 + 海沟（日本） |
| 大陆-大洋 | Andean subduction | 海岸山脉 + 海沟（安第斯） |

### 5.5 边界元数据

每个边界段存储以下信息：

```python
@dataclass
class BoundarySegment:
    node_a: int
    node_b: int
    plate_a: int
    plate_b: int
    midpoint: np.ndarray              # (3,) Cartesian
    boundary_type: str                # convergent | divergent | transform
    subduction_type: str | None       # oceanic-oceanic | continental-oceanic | ...
    v_normal_m_yr: float              # normal velocity component (m/yr)
    v_tangential_m_yr: float          # tangential velocity component
    influence_radius_km: float        # boundary effect radius
```

> **Cortial 2019 俯冲上隆公式**（详见[附录 D.4](#d4-四大构造现象)）：
> $u_j(p) = u_0 \cdot f(d) \cdot g(v) \cdot h(\tilde{z})$
> 其中 $u_0 = 0.6$ mm/y, $r_s = 1800$ km, $h(\tilde{z}) = \tilde{z}^2$。
> 我们的 §6 地形合成使用类似的高斯衰减函数，但简化为距离的指数衰减。
> 实现时间演化后（§17），应切换到 Cortial 的完整公式。

**边界链追踪**：将相邻的同类边界段连接成链（chain），用于生成线性特征（山脉走向、海沟线）：

```python
def trace_boundary_chains(
    segments: list[BoundarySegment],
    mesh: CVTMesh,
) -> list[BoundaryChain]:
    """Connect adjacent boundary segments into chains."""
    # Build boundary graph: segments sharing a node
    # Greedy chain tracing: start from unvisited segment,
    # follow neighbors of same type
    ...
```

### 参数表

| 参数 | 默认值 | 范围 | 物理含义 |
|------|--------|------|----------|
| `boundary_influence_km` | 500.0 | 100 – 2000 | 边界效应影响半径 |
| `velocity_threshold_cm_yr` | 0.5 | 0.1 – 2.0 | 活动/非活动阈值 |

---

## 6. 阶段 5: 地形合成

### 6.1 地壳基准高程

地球的高程分布呈**双峰分布**（hypsometric curve）：大陆平均 ~840m，海底平均 ~-3800m。
新方案在 CVT 节点上直接分配基准高程：

```python
def assign_base_elevation(
    plate_ids: np.ndarray,
    crust_types: list[str],
    mesh: CVTMesh,
    rng,
) -> np.ndarray:
    """Assign base elevation per node based on crust type.

    Bimodal distribution:
        Continental: ~850m ± 200m (Gaussian)
        Oceanic: ~-3800m ± 500m (Gaussian)
        Mixed: depends on local plate context

    Returns:
        (N,) elevation in meters.
    """
    elev = np.zeros(mesh.num_nodes)
    for i in range(mesh.num_nodes):
        ct = crust_types[plate_ids[i]]
        if ct == "continental":
            elev[i] = rng.normal(850, 200)
        elif ct == "oceanic":
            elev[i] = rng.normal(-3800, 500)
        else:  # mixed
            # Use noise to determine local type
            elev[i] = rng.choice([
                rng.normal(850, 200),
                rng.normal(-3800, 500),
            ])
    return elev
```

**双峰高程分布**：

```
频率
 ▲
 │        大陆 (~850m)
 │       ╱╲
 │      ╱  ╲
 │     ╱    ╲
 │────╱──────╲──────────────────── 海面 (0m)
 │   ╱        ╲
 │  ╱          ╲     海底 (~-3800m)
 │ ╱            ╲   ╱╲
 │╱              ╲ ╱  ╲
 └────────────────╳────╲───────► 高程 (m)
  -5000  -3000  -1000  0  1000  3000
```

### 6.2 边界地形效应

板块边界是地球上最剧烈的地形塑造力量。每种边界类型产生特征性的地形信号：

#### 汇聚边界 (Convergent)

```
地形剖面（垂直于边界）：

               ▲ 山脉 (+1500 ~ +4000m)
              ╱╲
             ╱  ╲
            ╱    ╲
───────────╱──────╲──────────── 基准面
          ╱        ╲
         ╱          ╲
                  ───╲───────
                      ╲
                       ▼ 海沟 (-2000 ~ -5000m)

影响半径: 200-500 km (山脉), 100-300 km (海沟)
```

**公式**：

```python
def convergent_effect(distance_km, v_normal, crust_a, crust_b):
    """Elevation contribution from convergent boundary.

    Args:
        distance_km: signed distance from boundary (positive = overriding plate side)
        v_normal: convergence rate (m/yr, positive)
        crust_a, crust_b: crust types of the two plates

    Returns:
        elevation adjustment (m)
    """
    sigma_mountain = 250.0  # km
    sigma_trench = 150.0    # km

    # Mountain range on overriding plate side
    rate_factor = min(v_normal / 5.0, 2.5)  # cap at 2.5× for extreme convergence
    mountain_amp = 2500 * rate_factor  # base amplitude (m)
    if crust_a == "continental" and crust_b == "continental":
        mountain_amp *= 1.6  # continental collision → taller mountains (Himalayas)
    mountain = mountain_amp * exp(-(max(distance_km, 0) / sigma_mountain) ** 2)

    # Trench on subducting plate side
    trench_amp = -3500 * rate_factor
    trench = trench_amp * exp(-(max(-distance_km, 0) / sigma_trench) ** 2)

    return mountain + trench
```

#### 离散边界 (Divergent)

```
地形剖面：

     山脊 (+500~+1500m)
      ╱╲        ╱╲
     ╱  ╲      ╱  ╲
    ╱    ╲    ╱    ╲
───╱──────╲──╱──────╲──── 基准面
          ╲╱
          裂谷 (-500~-1500m)

影响半径: 100-300 km
```

```python
def divergent_effect(distance_km, v_normal):
    """Elevation contribution from divergent boundary."""
    rate_factor = min(abs(v_normal) / 3.0, 2.0)
    sigma_rift = 100.0   # km
    sigma_ridge = 200.0  # km

    # Central rift valley
    rift = -1000 * rate_factor * exp(-(distance_km / sigma_rift) ** 2)

    # Flanking ridges (symmetric)
    ridge = 1000 * rate_factor * exp(-((abs(distance_km) - 200) / sigma_ridge) ** 2)

    return rift + ridge
```

#### 转换边界 (Transform)

转换断层不产生显著高程变化，但增加地形粗糙度：

```python
def transform_effect(roughness_base, distance_km):
    """Multiply roughness near transform boundaries."""
    sigma = 200.0  # km
    factor = 1.0 + 1.0 * exp(-(distance_km / sigma) ** 2)  # up to 2× roughness
    return roughness_base * factor
```

#### 边界效应公式汇总

| 边界类型 | 正效应 | 负效应 | σ (km) | 速率因子 |
|----------|--------|--------|--------|----------|
| Convergent (C-C) | +4000m 山脉 | -5000m 海沟 | 250/150 | v_n/5.0 × 1.6 |
| Convergent (O-O) | +2500m 岛弧 | -3500m 海沟 | 250/150 | v_n/5.0 |
| Convergent (C-O) | +3000m 海岸山 | -4000m 海沟 | 250/150 | v_n/5.0 |
| Divergent | +1500m 山脊 | -1500m 裂谷 | 200/100 | |v_n|/3.0 |
| Transform | — | — | 200 | 粗糙度 ×2.0 |

### 6.3 距边界距离调制

距板块边界的距离影响地形粗糙度——边界附近地形更崎岖：

```python
def distance_to_boundary(
    mesh: CVTMesh,
    boundary_nodes: set[int],
) -> np.ndarray:
    """BFS distance from each node to nearest boundary node.

    Returns:
        (N,) distance in km (angular distance × radius).
    """
    dist = np.full(mesh.num_nodes, inf)
    queue = deque()
    for bn in boundary_nodes:
        dist[bn] = 0.0
        queue.append(bn)

    while queue:
        node = queue.popleft()
        for neighbor in mesh.adjacency[node]:
            edge_len = angular_distance_xyz(
                mesh.nodes[node], mesh.nodes[neighbor]
            ) * mesh.radius_km
            if dist[node] + edge_len < dist[neighbor]:
                dist[neighbor] = dist[node] + edge_len
                queue.append(neighbor)

    return dist

def roughness_modulation(dist_km: np.ndarray, A: float = 1.0, lambda_km: float = 300.0):
    """Roughness multiplier based on distance to boundary.

    roughness = base × (1 + A · exp(-d / λ))

    Near boundary: up to (1+A)× roughness.
    Far from boundary: ~1× (no effect).
    """
    return 1.0 + A * np.exp(-dist_km / lambda_km)
```

### 6.4 多频率 3D Simplex fBm

fBm（fractional Brownian motion）提供多尺度地形细节。**关键**：在 CVT 节点的 3D 坐标上采样，
而非 2D 网格——这完全消除了极点畸变和经度接缝问题。

**参数**：

| Octave | 频率 f | 振幅 A (m) | 累积振幅 | 物理含义 |
|--------|--------|-----------|----------|----------|
| 1 | 1.0 | 1000.0 | 1000.0 | 大区域起伏（~6000 km） |
| 2 | 2.0 | 500.0 | 1500.0 | 次大陆起伏（~3000 km） |
| 3 | 4.0 | 250.0 | 1750.0 | 山脉尺度（~1500 km） |
| 4 | 8.0 | 125.0 | 1875.0 | 山岭尺度（~750 km） |
| 5 | 16.0 | 62.5 | 1937.5 | 丘陵尺度（~375 km） |
| 6 | 32.0 | 31.25 | 1968.75 | 细节起伏（~190 km） |

`persistence = 0.5`，`lacunarity = 2.0`

```python
def generate_fbm_on_cvt(
    nodes_xyz: np.ndarray,        # (N, 3) unit sphere positions
    seed: int,
    noise_scale: float = 2.0,
    octaves: int = 6,
    persistence: float = 0.5,
    lacunarity: float = 2.0,
) -> np.ndarray:
    """Multi-octave 3D Simplex noise sampled at CVT node positions.

    Each node's (x, y, z) is used directly as the noise sampling point.
    No projection artifacts.

    Returns:
        (N,) noise values in approximately [-1, 1].
    """
    result = np.zeros(len(nodes_xyz))
    amplitude = 1.0
    frequency = noise_scale

    for octave in range(octaves):
        # Sample 3D Simplex noise at each node
        scaled = nodes_xyz * frequency
        noise = np.array([
            opensimplex.noise3(p[0], p[1], p[2])
            for p in scaled
        ])
        result += amplitude * noise
        amplitude *= persistence
        frequency *= lacunarity

    # Normalize to [-1, 1]
    max_val = np.max(np.abs(result))
    if max_val > 0:
        result /= max_val

    return result
```

**性能优化**：使用 `pyfastnoise`（C 扩展）替代纯 Python `opensimplex`，
10 万节点 × 6 octave 的采样时间从 ~120s 降至 ~5s。

### 6.5 热点/地幔柱

地幔柱（mantle plume）从深部地幔上升，在地表产生火山热点。参考 Gleba 的
"mantle superswells" 设计——大型地幔上涌可以产生直径数千公里的隆起区域。

```python
def compute_hotspot_uplift(
    nodes_xyz: np.ndarray,
    hotspots: list[HotspotConfig],
    radius_km: float,
) -> np.ndarray:
    """Compute hotspot uplift at each CVT node.

    Each hotspot produces:
    1. Broad Gaussian uplift (superswell)
    2. Optional central caldera depression

    Reference: Gleba mantle superswell model — large plumes
    can uplift regions >2000 km diameter.
    """
    uplift = np.zeros(len(nodes_xyz))

    for hs in hotspots:
        # Hotspot position on unit sphere
        lat0 = radians(hs.lat_deg)
        lon0 = radians(hs.lon_deg)
        hs_xyz = array([cos(lat0)*cos(lon0), sin(lat0), cos(lat0)*sin(lon0)])

        # Angular distance to each node
        dots = np.clip(nodes_xyz @ hs_xyz, -1, 1)
        angular_dist = arccos(dots)
        dist_km = angular_dist * radius_km

        # Broad uplift (Gaussian)
        sigma = hs.radius_km
        uplift += hs.amplitude_m * exp(-(dist_km / sigma) ** 2)

        # Optional caldera (central depression)
        if hs.has_caldera and hs.caldera_radius_km > 0:
            cal_sigma = hs.caldera_radius_km
            uplift -= hs.caldera_depth_m * exp(-(dist_km / cal_sigma) ** 2)

    return uplift
```

### 6.6 合成公式

最终的节点高程由以下各项叠加：

```
elevation[i] = base_elev[i]
             + boundary_effect[i]
             + hotspot_uplift[i]
             + fBm_3d[i] × amplitude × interior_factor[i]
             + tidal_deformation[i]       # 仅潮汐锁定天体

其中:
    interior_factor = 1.0 + 0.3 × (dist_to_boundary / max_dist)
    # 板块内部噪声稍大（大陆内部高原/盆地）
```

```python
def synthesize_terrain(
    mesh: CVTMesh,
    base_elev: np.ndarray,
    boundary_elev: np.ndarray,
    hotspot_elev: np.ndarray,
    fbm_noise: np.ndarray,
    noise_amplitude_m: float = 600.0,
    dist_to_boundary_km: np.ndarray | None = None,
    tidal_elev: np.ndarray | None = None,
) -> np.ndarray:
    """Combine all terrain contributions.

    Returns:
        (N,) final elevation in meters.
    """
    # Distance-based interior modulation
    if dist_to_boundary_km is not None:
        max_dist = dist_to_boundary_km.max()
        interior_factor = 1.0 + 0.3 * (dist_to_boundary_km / max(max_dist, 1))
    else:
        interior_factor = np.ones(mesh.num_nodes)

    elevation = (
        base_elev
        + boundary_elev
        + hotspot_elev
        + fbm_noise * noise_amplitude_m * interior_factor
    )

    if tidal_elev is not None:
        elevation += tidal_elev

    return elevation
```

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

### 8.1 温度

**太阳辐射基础温度**：

```
T_base = (L_star / (16π σ_SB d²))^(1/4) - 273.15    [°C]

L_star: 恒星光度 (W)
d: 行星轨道距离 (m)
σ_SB: Stefan-Boltzmann 常数 (5.67 × 10⁻⁸ W/m²/K⁴)
```

**纬度修正**：

```
T_lat = T_equator - ΔT_lat × sin²(φ)

φ: 纬度
ΔT_lat ≈ 30-60°C（赤道-极地温差，取决于大气成分和自转速率）
```

**海拔递减率**：

```
T_elev = T_surface - Γ × h

Γ ≈ 6.5 °C/km（湿绝热递减率）
h: 海拔 (km)
```

**季节变化**（需要轴倾角和轨道周期）：

```
T_season = T_mean + A_season × cos(2π t / P_orb) × sin(φ) × sin(ε)

A_season: 季节振幅 (~5-15°C)
P_orb: 轨道周期 (days)
ε: 轴倾角 (radians)
t: 时间 (days)
```

```python
def compute_temperature(
    mesh: CVTMesh,
    elevation_m: np.ndarray,
    is_land: np.ndarray,
    stellar_luminosity_sol: float = 1.0,   # L☉
    orbital_distance_au: float = 1.0,
    axial_tilt_deg: float = 23.5,
    rotation_period_days: float = 1.0,
    orbital_period_days: float = 365.25,
    atmosphere_factor: float = 1.0,
) -> dict[str, np.ndarray]:
    """Compute temperature at each CVT node.

    Returns:
        dict with keys: 'mean', 'jan', 'jul', 'annual_range'
        Values are (N,) arrays in °C.
    """
    # Extract latitude from node positions
    lat = arcsin(clip(nodes_xyz[:, 1], -1, 1))

    # Base equilibrium temperature
    T_eq = 255 * (stellar_luminosity_sol / orbital_distance_au**2)**0.25
    T_eq_celsius = T_eq - 273.15

    # Greenhouse + atmosphere correction
    T_surface_base = T_eq_celsius + 33 * atmosphere_factor  # ~15°C for Earth

    # Latitude gradient
    delta_lat = 45.0 * atmosphere_factor
    T_lat = T_surface_base - delta_lat * sin(lat)**2

    # Altitude lapse rate
    elev_km = elevation_m / 1000
    T_with_elev = T_lat - 6.5 * elev_km

    # Continental vs oceanic climate (land has larger annual range)
    annual_range = where(is_land, 25.0, 10.0) * sin(lat)**2

    # Seasonal temperatures
    epsilon = radians(axial_tilt_deg)
    T_jan = T_with_elev + annual_range/2 * sign(-lat) * sin(epsilon)
    T_jul = T_with_elev - annual_range/2 * sign(-lat) * sin(epsilon)

    return {
        "mean": T_with_elev,
        "jan": T_jan,
        "jul": T_jul,
        "annual_range": annual_range,
    }
```

### 8.2 风场

**地转风近似**（Geostrophic wind）：

参考 Gleba devlog #3 的设计决策——使用地转风近似而非完整的 Navier-Stokes 求解。
在大尺度上，风场主要由气压梯度力和科里奥利力的平衡决定。

**科里奥利参数**：

```
f = 2Ω · sin(φ)

Ω: 行星自转角速度 (rad/s)
φ: 纬度
```

**气压梯度**（简化）：

气压主要由温度决定（理想气体定律）。高温 → 低压，低温 → 高压。

```python
def compute_wind_field(
    mesh: CVTMesh,
    temperature: np.ndarray,
    elevation_m: np.ndarray,
    is_land: np.ndarray,
    rotation_period_days: float = 1.0,
) -> np.ndarray:
    """Compute simplified geostrophic wind on CVT graph.

    Implementation:
    1. Compute pressure proxy from temperature
    2. Compute pressure gradient on graph (finite differences)
    3. Apply geostrophic balance: v_g = (1/fρ) × ∇p × ẑ
    4. Simplify Hadley/Ferrel/Polar cells
    5. Apply terrain blocking (high mountains deflect wind)

    Returns:
        (N, 3) wind velocity vectors (m/s) tangent to sphere.
    """
    # Pressure proxy (lower T → higher P, simplified)
    pressure = 1013.25 * exp(-elevation_m / 8500)  # barometric formula
    T_normalized = (temperature - temperature.min()) / (temperature.max() - temperature.min() + 1e-6)
    pressure -= 20 * T_normalized  # thermal low

    # Compute gradient on graph
    grad_p = compute_graph_gradient(mesh, pressure)

    # Coriolis parameter
    lat = arcsin(clip(mesh.nodes[:, 1], -1, 1))
    omega_planet = 2 * pi / (rotation_period_days * 86400)
    f = 2 * omega_planet * sin(lat)

    # Geostrophic wind (perpendicular to pressure gradient)
    # In NH: wind blows parallel to isobars with low P to left
    # In SH: reversed
    rho = 1.225  # air density kg/m³
    wind = np.zeros((mesh.num_nodes, 3))
    for i in range(mesh.num_nodes):
        if abs(f[i]) < 1e-6:  # near equator, geostrophic breaks down
            wind[i] = -grad_p[i] * 0.5  # simplified trade winds
        else:
            # Cross product with local vertical for geostrophic
            k_hat = mesh.nodes[i]  # local vertical = radial direction
            wind[i] = np.cross(k_hat, grad_p[i]) / (f[i] * rho)

    # Simplified Hadley/Ferrel/Polar cell overlay
    wind += compute_cell_circulation(lat, mesh.nodes)

    # Terrain blocking: high mountains reduce wind speed
    blocking = 1.0 - 0.5 * exp(-elevation_m / 3000)  # 50% reduction at 3000m
    wind *= blocking[:, np.newaxis]

    return wind
```

**简化环流单元**（Hadley/Ferrel/Polar）：

```
纬度    │ 环流单元    │ 地面风方向
────────┼────────────┼──────────────
0°-30°  │ Hadley     │ 东北信风 (NH) / 东南信风 (SH)
30°-60° │ Ferrel     │ 西南风 (NH) / 西北风 (SH)
60°-90° │ Polar      │ 东北风 (NH) / 东南风 (SH)
```

### 8.3 降水与水循环

**核心机制**：海洋蒸发 → 风场输送水汽 → 地形抬升降水（迎风坡）→ 雨影效应（背风坡）

```python
def compute_precipitation(
    mesh: CVTMesh,
    is_land: np.ndarray,
    temperature: np.ndarray,
    wind: np.ndarray,
    elevation_m: np.ndarray,
) -> np.ndarray:
    """Compute annual precipitation via BFS moisture transport.

    Algorithm:
    1. Initialize moisture: ocean cells = f(temperature), land = 0
    2. BFS along wind direction:
       - Transport moisture from upwind cells
       - When air rises (elevation increases), condense → rain
       - When air descends, moisture capacity increases (rain shadow)
    3. ITCZ seasonal migration: shift moisture source toward warm hemisphere

    Reference: Gleba ITCZ model — the Intertropical Convergence Zone
    migrates seasonally, bringing monsoon patterns to tropical regions.

    Returns:
        (N,) annual precipitation in mm.
    """
    # Step 1: Evaporation from ocean
    # Warmer water → more evaporation
    moisture = np.zeros(mesh.num_nodes)
    ocean_mask = ~is_land
    moisture[ocean_mask] = 2000 * (1 + 0.03 * temperature[ocean_mask])  # mm/yr base

    # Step 2: BFS moisture transport
    # Process cells in wind-advection order
    precip = np.zeros(mesh.num_nodes)
    visited = set()

    # Start from ocean cells, propagate along wind
    queue = deque()
    for i in range(mesh.num_nodes):
        if ocean_mask[i]:
            queue.append(i)

    while queue:
        node = queue.popleft()
        if node in visited:
            continue
        visited.add(node)

        # Find downwind neighbor
        wind_dir = wind[node]
        if linalg.norm(wind_dir) < 1e-6:
            continue

        best_neighbor = None
        best_dot = -1
        for n in mesh.adjacency[node]:
            edge_dir = mesh.nodes[n] - mesh.nodes[node]
            edge_dir /= (linalg.norm(edge_dir) + 1e-12)
            dot = np.dot(wind_dir, edge_dir)
            if dot > best_dot:
                best_dot = dot
                best_neighbor = n

        if best_neighbor is None or best_dot < 0.3:
            continue

        # Orographic effect: rising air → precipitation
        elev_diff = elevation_m[best_neighbor] - elevation_m[node]
        if elev_diff > 0 and is_land[best_neighbor]:
            # Air forced to rise → condensation → rain
            rain = moisture[node] * min(elev_diff / 1000, 0.5)
            precip[best_neighbor] += rain
            moisture[best_neighbor] = moisture[node] - rain
        elif elev_diff < 0 and is_land[best_neighbor]:
            # Descending air → rain shadow (less precipitation)
            precip[best_neighbor] += moisture[node] * 0.05
            moisture[best_neighbor] = moisture[node] * 0.95
        else:
            # Flat terrain / ocean: gradual moisture loss
            moisture[best_neighbor] = moisture[node] * 0.9
            precip[best_neighbor] += moisture[node] * 0.1

        if best_neighbor not in visited:
            queue.append(best_neighbor)

    # Step 3: Convective precipitation in tropics
    lat = arcsin(clip(mesh.nodes[:, 1], -1, 1))
    tropical = abs(lat) < radians(23.5)
    precip[tropical] += 500  # ITCZ-enhanced tropical rainfall

    return precip
```

**ITCZ 季节性迁移**：

```python
def itcz_latitude(day_of_year: int, axial_tilt_deg: float = 23.5) -> float:
    """Approximate ITCZ latitude as a function of season.

    The ITCZ lags the subsolar point by ~1-2 months due to
    thermal inertia of oceans.

    Reference: Gleba — ITCZ migration drives monsoon cycles.
    """
    # Subsolar point
    epsilon = radians(axial_tilt_deg)
    solar_declination = epsilon * sin(2 * pi * (day_of_year - 80) / 365.25)

    # ITCZ lags by ~30 days and is damped
    itcz_offset = radians(5)  # mean ITCZ offset (NH bias on Earth)
    itcz_lat = 0.7 * solar_declination + itcz_offset

    return degrees(itcz_lat)
```

### 8.4 洋流（简化）

洋流对气候的影响通过简化的表面流模型实现：

```python
def compute_surface_currents(
    mesh: CVTMesh,
    wind: np.ndarray,
    is_land: np.ndarray,
) -> np.ndarray:
    """Simplified surface ocean currents.

    Surface currents are driven by wind (Ekman transport),
    deflected by continents, and organized into gyres.

    Simplification:
    - Current direction ≈ 45° deflected from wind (Ekman spiral)
    - Currents blocked by land
    - Western boundary intensification (Gulf Stream, Kuroshio)

    Returns:
        (N, 3) current velocity vectors (m/s).
    """
    # Ekman transport: ~45° deflection from wind
    # In NH: deflected right; in SH: deflected left
    lat = arcsin(clip(mesh.nodes[:, 1], -1, 1))
    deflection_angle = sign(lat) * radians(45)

    currents = np.zeros_like(wind)
    ocean_mask = ~is_land

    for i in range(mesh.num_nodes):
        if not ocean_mask[i]:
            continue
        # Rotate wind vector by deflection angle
        # (in the tangent plane at this node)
        w = wind[i]
        if linalg.norm(w) < 1e-6:
            continue
        # ... rotation in tangent plane ...
        currents[i] = rotate_tangent(w, mesh.nodes[i], deflection_angle) * 0.02
        # 0.02: current speed ≈ 2% of wind speed

    return currents
```

**洋流热输送**：

```python
def apply_ocean_heat_transport(
    temperature: np.ndarray,
    currents: np.ndarray,
    mesh: CVTMesh,
    is_land: np.ndarray,
) -> np.ndarray:
    """Apply ocean current heat transport to coastal temperatures.

    Warm currents → coastal warming
    Cold currents → coastal cooling (e.g., Humboldt, California)
    """
    # Find coastal nodes (land adjacent to ocean)
    coastal = find_coastal_nodes(mesh, is_land)

    # Propagate temperature along current direction
    T_adjusted = temperature.copy()
    for node in coastal:
        # Average temperature of upcurrent ocean nodes
        T_ocean_avg = average_upcurrent_temperature(node, currents, mesh, temperature)
        # Coastal moderation: ±2-5°C from current
        T_adjusted[node] += 0.3 * (T_ocean_avg - temperature[node])

    return T_adjusted
```

### 8.5 Köppen 气候分类

从 `(temperature, precipitation)` 直接映射到 Köppen 气候类型：

```python
def koppen_classify(
    T_mean: np.ndarray,
    T_cold: np.ndarray,        # coldest month mean
    T_hot: np.ndarray,         # hottest month mean
    P_annual: np.ndarray,      # annual precipitation (mm)
    P_dry: np.ndarray,         # driest month precipitation
    P_wet: np.ndarray,         # wettest month precipitation
) -> list[str]:
    """Köppen climate classification for each CVT node.

    5 main groups:
    A: Tropical (T_cold > 18°C)
    B: Arid (P < threshold based on T)
    C: Temperate (T_cold ∈ [-3, 18]°C, T_hot > 10°C)
    D: Continental (T_cold < -3°C, T_hot > 10°C)
    E: Polar (T_hot < 10°C)

    Sub-classification based on precipitation seasonality.

    Returns:
        List of Köppen codes (e.g., 'Cfa', 'BWh', 'ET').
    """
    classes = []
    for i in range(len(T_mean)):
        tc, th, ta = T_cold[i], T_hot[i], T_mean[i]
        pa, pd, pw = P_annual[i], P_dry[i], P_wet[i]

        # Group E: Polar
        if th < 10:
            if th > 0:
                classes.append("ET")  # Tundra
            else:
                classes.append("EF")  # Ice cap

        # Group B: Arid
        elif pa < 20 * ta + (280 if pw > 2*pd else 140 if pd > 2*pw else 0):
            if ta > 18:
                classes.append("BWh" if pa < 10*ta else "BSh")
            else:
                classes.append("BWk" if pa < 10*ta else "BSk")

        # Group A: Tropical
        elif tc > 18:
            if pd > 60:
                classes.append("Af")   # Tropical rainforest
            elif pa - pw > pa * 0.5:
                classes.append("Aw")   # Tropical savanna
            else:
                classes.append("Am")   # Tropical monsoon

        # Group C: Temperate
        elif tc > -3:
            if pw > 3*pd and pw > 40:
                classes.append("Cs")   # Mediterranean
            elif pd > 30:
                classes.append("Cf")   # Humid subtropical (if th>22: Cfa, else Cfb)
            else:
                classes.append("Cw")   # Dry winter

        # Group D: Continental
        else:
            if pw > 3*pd:
                classes.append("Ds")   # Dry summer continental
            elif pd > 30:
                classes.append("Df")   # Humid continental
            else:
                classes.append("Dw")   # Dry winter continental

    return classes
```

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

### 瓶颈分析

| 操作 | 复杂度 | 100K 节点耗时 | 瓶颈原因 |
|------|--------|--------------|----------|
| Fibonacci lattice | O(N) | <0.01s | 无 |
| Lloyd relaxation (×8) | O(k·N·log N) | ~8s | SphericalVoronoi 构建 |
| 洪水填充板块 | O(N·log N) | ~1s | 优先队列 |
| 欧拉极速度场 | O(N) | <0.1s | 向量化叉积 |
| 边界检测 | O(N) | <0.1s | 邻接扫描 |
| 边界效应计算 | O(N·B) | ~15s | B = 边界节点数 |
| fBm 噪声 (6 oct) | O(N·O) | ~120s (纯 Python) / ~5s (pyfastnoise) | 逐点 Simplex |
| 海平面二分 | O(N·log(precision)) | <0.01s | 无 |
| 温度计算 | O(N) | <0.1s | 向量化 |
| 风场计算 | O(N·k) | ~2s | k = 平均邻居数 |
| BFS 降水 | O(N) | ~3s | 单次 BFS |
| 流向确定 | O(N·k) | ~2s | 逐节点扫描 |
| 汇水累积 | O(N) | ~1s | 拓扑排序 |
| 热侵蚀 (×10) | O(k·N·I) | ~10s | 迭代松弛 |
| 等距投影插值 | O(N·log N) | ~5s | scipy griddata |
| **总计** | | **~70s** (pyfastnoise) | |

### 优化策略

1. **pyfastnoise 替代 opensimplex**：fBm 从 120s 降至 5s（24× 加速）
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

### A.1 Haversine 角距离

```
d(φ₁,λ₁, φ₂,λ₂) = 2 · arcsin(√(sin²(Δφ/2) + cos(φ₁)·cos(φ₂)·sin²(Δλ/2)))

其中 Δφ = φ₂ - φ₁, Δλ = λ₂ - λ₁
```

### A.2 Fibonacci 球面格点

```
φ_k = arccos(1 - 2(k + 0.5) / N)          k = 0, 1, ..., N-1
θ_k = 2πk / Φ                              Φ = (1 + √5) / 2

x_k = sin(φ_k) · cos(θ_k)
y_k = cos(φ_k)
z_k = sin(φ_k) · sin(θ_k)
```

### A.3 欧拉极运动学

```
设欧拉极方向为 ê (单位向量)，角速度为 ω (rad/yr)。

角速度矢量：Ω = ω · ê

球面上点 P 的速度（在半径 R 的球面上）：
    v(P) = Ω × P · R                      [m/yr]

速度大小：
    |v(P)| = ω · R · sin(α)

其中 α = arccos(ê · P) 是 P 到欧拉极的角距离。
```

**相对速度（边界处）**：

```
v_rel(P) = v_A(P) - v_B(P)
         = (Ω_A - Ω_B) × P · R

分解为法向和切向分量：
    v_n = v_rel · n̂                        （法向：汇聚为正）
    v_t = |v_rel - v_n · n̂|               （切向：走滑）

n̂：边界法向量（在切平面内，从 plate_A 指向 plate_B）
```

### A.4 fBm (Fractional Brownian Motion)

```
fBm(P) = Σᵢ₌₀ᴼ⁻¹ Aᵢ · noise3(P · fᵢ)

O: octaves (default 6)
Aᵢ = persistence^i                         (default 0.5^i)
fᵢ = noise_scale · lacunarity^i            (default 2.0 · 2.0^i)

noise3: 3D Simplex noise function
P: (x, y, z) 球面上的 3D 坐标

归一化：fBm /= max(|fBm|) → range ≈ [-1, 1]
```

### A.5 Köppen 气候阈值

| 组 | 条件 | 子类型条件 |
|----|------|-----------|
| A (热带) | T_cold > 18°C | f: P_dry > 60mm; m: monsoon; w: dry winter |
| B (干旱) | P < 20·T + C | W: desert (P < 10·T); S: steppe |
| C (温带) | -3 < T_cold < 18, T_hot > 10 | f: no dry season; s: dry summer; w: dry winter |
| D (大陆) | T_cold < -3, T_hot > 10 | f: no dry season; s: dry summer; w: dry winter |
| E (极地) | T_hot < 10 | T: tundra (T_hot > 0); F: ice cap |

B 组的 C 值：C = 280 如果 P_wet > 2·P_dry; C = 140 如果 P_dry > 2·P_wet; C = 0 其他。

### A.6 汇水累积

```
accum(i) = area(i) + Σ accum(j) for j in upstream(i)

其中 upstream(i) = {j | flow_dir(j) = i}

计算顺序：拓扑排序（从源头到河口）
```

### A.7 球面多边形面积

```
A = |Σᵢ₌₁ⁿ θᵢ - (n - 2)·π| · R²

θᵢ: 多边形第 i 个顶点的内角（球面角）
n: 顶点数
R: 球体半径

立体角（steradians）：Ω = A / R²
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
| `_compute_noise_elementwise()` | ⚠️ 改造 | 向量化改造或用 pyfastnoise 替代 |
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
- [ ] 添加 `pyfastnoise` 到可选依赖 (`pyproject.toml`)
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
> Vol. 38, No. 2. DOI: [10.1111/cgf.13614](https://doi.org/10.1111/cgf.13614)
>
> **HAL 全文**: [hal-02136820](https://hal.science/hal-02136820/)
> **视频**: [Eurographics 2019 Presentation (YouTube)](https://www.youtube.com/watch?v=GJQVl6Xld0w)
> **后续**: Cortial 获 2020 CNRS 最佳博士论文奖，现为 Arkane Studios 图形程序员。

### D.1 论文定位

这篇论文是**程序化星球生成**领域的里程碑工作。它不追求物理精确模拟（不计算地幔对流 PDE），
而是用**现象学方法（phenomenological approach）** 捕捉板块构造的大尺度地貌效应。
核心贡献：

1. **首次实现完整的交互式程序化板块星球**：用户可实时控制板块运动、触发裂解事件
2. **四大构造现象的程序化建模**：俯冲、大陆碰撞、洋壳创生、板块裂解
3. **双层放大管线**：粗分辨率构造模型 → GPU 放大至 ~100m 分辨率

### D.2 网格与数据结构

#### 球面采样与三角剖分

- **Fibonacci 采样**：近似均匀的球面点分布
- **STRIPACK 算法**（Renka 1997）：全局球面 Delaunay 三角剖分
- **默认 500,000 采样点**（6,370km 半径行星 → ~35km 分辨率）
- 三角剖分按 Voronoi cell 归属划分为板块

#### 重采样策略（关键设计决策）

- 采样/网格化作为**离线预处理**完成
- **不在每步重新网格化**（太贵），而是每 10-60 步执行一次全局重采样
- 离散板块之间的新点从洋壳生成方法获取参数
- 其他点使用重心插值从所属板块获取

### D.3 地壳参数化

每个板块上的每个采样点存储以下属性：

| 属性 | 海洋地壳 | 大陆地壳 |
|------|---------|---------|
| 地壳类型 $x_C$ | oceanic | continental |
| 地壳厚度 $e$ | ~7km | ~35-50km |
| 地形高程 $z$ | -1 到 -10km | 0 到 10km |
| 地壳年龄 $a_o$ | ✓（自洋中脊创生） | — |
| 洋脊方向 $r$ | ✓ | — |
| 造山年龄 $a_c$ | — | ✓ |
| 造山类型 $o$ | — | Andean / Himalayan |
| 褶皱方向 $f$ | — | ✓ |

### D.4 四大构造现象

#### 俯冲（Subduction）

**触发条件**：
- 洋-洋汇聚 → 较老板块俯冲
- 洋-陆汇聚 → 洋壳始终俯冲
- 陆-陆汇聚 → 部分强制俯冲，随后转为碰撞

**上隆公式**（上方板块点 $p$ 的高程增量）：

$$u_j(p) = u_0 \cdot f(d(p)) \cdot g(v(p)) \cdot h(\tilde{z}_i(p))$$

其中：
- $u_0 = 0.6$ mm/y — 基准上隆速率
- $f(d)$ — 分段三次曲线：在控制距离处达峰值，在 $r_s = 1800$ km 处衰减至 0
- $g(v) = v / v_0$ — 线性速度传递（$v_0 = 100$ mm/y 为最大板块速度）
- $h(\tilde{z}_i) = \tilde{z}_i^2$ — **二次**高程影响（海平面以上特征主导）

**Slab Pull（欧拉极修改）**：

$$\mathbf{w}_i(t+\delta t) = \mathbf{w}_i(t) + \varepsilon \sum_{k} \frac{\mathbf{c}_i \times \mathbf{q}_k}{\|\mathbf{c}_i \times \mathbf{q}_k\|} \cdot \delta t$$

俯冲带动态修改板块旋转轴，使长俯冲前线对板块运动方向产生显著影响。

#### 大陆碰撞（Continental Collision）

- **触发**：两板块互穿距离 > 300km
- **影响半径**：$r = r_c \cdot \sqrt{v/v_0} \cdot (A/A_0)^\beta$，$r_c = 4200$ km
- **离散高程跃升**：$\Delta z(p) = \Delta_c \cdot A \cdot (1 - d/r)^2{}^2$，$\Delta_c = 1.3 \times 10^{-5}$ km$^{-1}$
- **地体缝合**：碰撞地体从俯冲板块脱离，附着到上覆板块

#### 洋壳创生（Oceanic Crust Generation）

- 在离散边界自动形成洋中脊
- **高程混合**：$z = \alpha \cdot \bar{z} + (1-\alpha) \cdot z_\Gamma$
  - $\bar{z}$：两板块间线性插值
  - $z_\Gamma$：模板洋中脊剖面函数
  - $\alpha$：到洋脊距离 / (到洋脊距离 + 到最近板块边界距离)
- 每 10-60 步执行一次（涉及采样和网格化）

#### 板块裂解（Plate Rifting）

- **Poisson 概率模型**：$P = \lambda e^{-\lambda}$，$\lambda = \lambda_0 \cdot f(x_P) \cdot A/A_0$
- 大板块更容易裂解（防止超级大陆永久存在）
- 裂解为 2-4 个子板块，各自获得随机离散方向
- 支持用户手动触发（指定位置、断裂线、时机）

### D.5 侵蚀与衰减

**每步**应用的简化模型：

| 过程 | 公式 | 常数 |
|------|------|------|
| 大陆侵蚀 | $z \mathrel{-}= (z/z_c) \cdot \varepsilon_c \cdot \delta t$ | $\varepsilon_c = 0.03$ mm/y, $z_c = 10$ km |
| 洋壳沉降 | $z \mathrel{-}= (1 - z/z_t) \cdot \varepsilon_o \cdot \delta t$ | $\varepsilon_o = 0.04$ mm/y, $z_t = -10$ km |
| 海沟沉积 | $z \mathrel{+}= \varepsilon_t \cdot \delta t$ | $\varepsilon_t = 0.3$ mm/y |

**无**水力侵蚀、热侵蚀、冰川侵蚀或风蚀——设计为与后续侵蚀方法兼容。

### D.6 放大管线（Amplification）

| 区域 | 方法 | 技术 |
|------|------|------|
| 海洋地壳 | 程序化 | 3D Gabor 噪声（沿洋脊方向定向，模拟转换断层）+ 高频梯度噪声 |
| 大陆地形 | 基于样例 | USGS SRTM90 真实地形原语，按造山类型分类（Andean/Himalayan/古山/平原），沿褶皱方向旋转对齐 |

使用 19 个真实地形样例集：7 个喜马拉雅型、11 个安第斯型、6 个古山脉。

### D.7 完整常数表

| 符号 | 含义 | 值 |
|------|------|-----|
| $\delta t$ | 时间步长 | 2 My |
| $R$ | 行星半径 | 6,370 km |
| $z_r$ | 洋中脊最高高程 | -1 km |
| $z_a$ | 深海平原高程 | -6 km |
| $z_t$ | 海沟高程 | -10 km |
| $z_c$ | 大陆最高海拔 | 10 km |
| $r_s$ | 俯冲影响距离 | 1,800 km |
| $r_c$ | 碰撞影响距离 | 4,200 km |
| $\Delta_c$ | 碰撞系数 | $1.3 \times 10^{-5}$ km$^{-1}$ |
| $v_0$ | 最大板块速度 | 100 mm/y |
| $\varepsilon_o$ | 洋壳沉降率 | $0.04$ mm/y |
| $\varepsilon_c$ | 大陆侵蚀率 | $0.03$ mm/y |
| $\varepsilon_t$ | 海沟沉积率 | $0.3$ mm/y |
| $u_0$ | 俯冲上隆率 | $0.6$ mm/y |

### D.8 性能数据

| 指标 | 值 |
|------|-----|
| 语言 | C++（CPU 构造计算）+ GPU（放大渲染） |
| 硬件 | Intel i7-6700K @ 4GHz, 16GB RAM, GTX 1080 |
| 分辨率 | 35-500km（构造层），~100m（放大层） |
| 默认采样 | 500,000 点 |
| 完成行星 | ~125-250 步（≈250-500 My 模拟时间） |
| 帧率 | 37-145 Hz（自适应网格 + GPU 渲染） |
| 每步耗时 (35km) | 1.9s 总计（俯冲 0.65s + 碰撞 0.63s + 高程 0.62s） |
| 洋壳生成 | 13.1s（每 20-120 My 执行一次） |
| 板块裂解 | 7.7s（离散事件） |

### D.9 已知局限（作者自评 + 地质专家评审）

1. **无热点**：不生成火山岛链（如夏威夷），但可作为特殊采样点实现
2. **无被动大陆边缘**：未建模大陆架浅水区
3. **无排水网络**：但与现有河流生成方法兼容
4. **无气候/大气模型**：明确列为未来工作
5. **过度强制俯冲**：大型地体的俯冲检测/防止计算成本过高
6. **板块裂解不够自然**：旋转轴沿裂谷线，非真实物理断裂

### D.10 对 dreamulator 的启示

| Cortial 2019 特性 | dreamulator 对应 | 状态 |
|-------------------|-----------------|------|
| Euler pole 运动学 | §4 欧拉极与板块运动学 | ✓ 基础管线已覆盖 |
| 地壳参数化表 | §14 数据模型变更 | ✓ 已设计 |
| 俯冲上隆公式 | §5 边界检测 + §6 地形合成 | ✓ 已覆盖（简化版） |
| Slab pull 反馈 | §17.3.B 俯冲消亡 | § 进阶功能 |
| 大陆碰撞造山 | §17.3.C 大陆拼合 | § 进阶功能 |
| 洋壳创生 + 年龄 | §17.3.A 洋壳创生 | § 进阶功能 |
| 板块裂解 Poisson | §17.3.D 板块裂解 | § 进阶功能 |
| 侵蚀/衰减 | §10 侵蚀 | 基础版已覆盖 |
| 放大管线 | §13 Gaea 局部精细化 | 使用 Gaea 替代 |
| 热点 | 未来工作 | ✗ |
| 气候/大气 | §8 气候模拟 | ✓ 基础管线已覆盖 |
| 河流网络 | §9 河流水文 | ✓ 基础管线已覆盖 |

### D.11 研究谱系

```
2016  Cordonnier et al. — 构造隆起 + 河流侵蚀（高度图，非球面）
       Eurographics 2016 / CGF 35(2)
  ▼
2019  Cortial et al. — 完整球面交互式板块星球 ← 本文
       Eurographics 2019 / CGF 38(2)
  ▼
2020  Cortial et al. — 实时超放大（低分辨率行星 → 高分辨率细节）
       The Visual Computer 36(10-12)
  ▼
2026  Borg et al. — 扩散模型生成类地行星（ML + 四叉球）
       Eurographics 2026 / CGF 45(2)
```

### D.12 相关开源实现

| 项目 | 语言 | 与论文关系 |
|------|------|-----------|
| [Arches-Team/Real-Time-Hyper-Amplification-of-Planets](https://github.com/Arches-Team/Real-Time-Hyper-Amplification-of-Planets) | C++/GLSL | 官方 2020 后续论文代码（仅放大，非构造引擎） |
| [FioDev/Procedural-Tectonics](https://github.com/FioDev/Procedural-Tectonics) | C#/HLSL | 社区实现，模拟板块族 + 俯冲 + 岛链 |
| [hecubah/driftworld-tectonics](https://github.com/hecubah/driftworld-tectonics) | Unity/C# | 明确引用 Cortial 2019 |
| [SecondSystem Plate Tectonics](https://second-system.de/2022/03/01/tectonics_1) | — | "深受 Cortial 启发"，统一 Delaunay 网格 + 弹簧-阻尼力 |
| Blender Tectonic Tools | Python | 明确引用论文方法论 |

### D.13 科普与可视化资源

| 资源 | 链接 | 与本项目的关系 |
|------|------|---------------|
| **Fractal Philosophy**: *Maps: Fractals, Tectonics and the Fourth Dimension* | [B站中字](https://www.bilibili.com/video/BV1n2i7BrEmq)（BV1n2i7BrEmq） | 系统讲解分形几何、板块动力学模拟与高维空间映射的科普视频。其中关于地貌特征如何受数学规则驱动、板块运动的可视化呈现，与本管线的 fBm 噪声叠加（§6.4）和板块构造模拟（§3-§5）思路高度契合。对本项目的设计理念有较大启发。 |
