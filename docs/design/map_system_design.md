# 地图系统架构设计文档

> **面向读者**：Dreamulator 开发者、架空世界设定爱好者、以及未来 Bilibili 视频观众。
>
> **文档版本**：2026-07 | **对应代码版本**：v0.3.x

---

## 目录

1. [设计动机](#1-设计动机)
2. [系统架构](#2-系统架构)
3. [核心算法](#3-核心算法)
4. [数据流](#4-数据流)
5. [设计决策记录（ADR）](#5-设计决策记录adr)
6. [未来演进](#6-未来演进)
7. [技术栈](#7-技术栈)

---

## 1. 设计动机

### 1.1 为什么不在应用内做一个完整的地形编辑器？

Dreamulator 的目标是**从物理定律出发，严谨推演架空世界**。地图是推演的画布，但
"画布编辑器"本身并不是我们要解决的问题。

早期原型确实尝试过内置笔刷编辑器，但遇到了严重的体验瓶颈：

| 问题 | 描述 |
|------|------|
| 笔刷工具未实现 | 高度图笔刷需要处理高斯衰减、流量控制、多层混合——工作量相当于一个小型 Photoshop |
| 参数 UI 不可用 | 地形生成的 `TerrainParams` 有 9 个参数，逐一调节效率极低 |
| 质量天花板 | 即便完美实现，内置编辑器的地形质量也无法与专业工具竞争 |
| 维护成本 | 编辑器代码量可能超过整个 map 子系统的其余部分 |

**结论**：保留可视化 + 导入能力，将地形创作交给专业工具。

### 1.2 专业工具对比：为什么选 Gaea？

| 特性 | Gaea (QuadSpinner) | World Machine | World Creator |
|------|---------------------|---------------|---------------|
| **免费版分辨率** | **4096 × 4096** | 512 × 512 | 1024 × 1024 |
| **渲染引擎** | GPU (CUDA/OpenCL) | CPU | GPU |
| **UI 设计** | 现代节点图 | 经典但过时 | 现代 |
| **CLI 支持** | ✅ `GaeaCLI` | ❌ | 有限 |
| **模板化工作流** | ✅ 保存 `.graph` 复用 | 部分 | 部分 |
| **导出格式** | RAW16/TIFF16/PNG16 | RAW16/PNG16 | RAW16/PNG16 |
| **学习曲线** | 中等 | 陡峭 | 较低 |
| **成熟度** | ★★★★ | ★★★★★（最老牌） | ★★★ |

**选择 Gaea 的核心理由**：

1. **免费版 4K 分辨率**——World Machine 免费版只有 512×512，完全不够用
2. **CLI 管线**——`GaeaCLI -graph world.graph -output elevation.tiff` 可集成到自动化管线
3. **`.graph` 模板复用**——一次搭建侵蚀节点图，反复应用到不同世界
4. **GPU 加速**——预览和导出都很快

> World Machine 仍然是最成熟的工具，社区资源丰富。如果你的工作流已经依赖它，
> Dreamulator 的 TIFF/PNG 导入管线同样支持。

### 1.3 两套地图系统为什么需要桥接？

Dreamulator 内部有**两套独立的地图子系统**，各自服务不同的推演阶段：

```
┌─────────────────────────────────────────────────────────────┐
│                     Dreamulator 地图系统                      │
│                                                             │
│  ┌──────────────────────┐    ┌───────────────────────────┐  │
│  │   Planet Map (地形图)  │    │   CivMap (文明图)          │  │
│  │                      │    │                           │  │
│  │  • 栅格高度图          │    │  • 真实地球行政区划        │  │
│  │  • Voronoi 语义网络   │    │  • GeoJSON 多边形          │  │
│  │  • 板块/河流/山脊     │    │  • 虚构国家领土涂色        │  │
│  │                      │    │                           │  │
│  │  用途：地质/气候/生态  │    │  用途：政治/文明推演       │  │
│  │  渲染：Three.js       │    │  渲染：Leaflet.js          │  │
│  └──────────┬───────────┘    └─────────────┬─────────────┘  │
│             │                              │                │
│             └──────── 桥梁：GeoJSON ────────┘                │
│                  VoronoiCell.province_id                      │
└─────────────────────────────────────────────────────────────┘
```

- **Planet Map**：服务于 `geological → climate → ecology` 推演链。高度图驱动温度场、
  降水场、 biome 分布；Voronoi 网格将栅格分组为语义单元（板块、省份）
- **CivMap**：服务于 `civilization` 推演层。在真实地球底图上绘制虚构国家，
  用于"如果罗马帝国存续到今天"之类的架空历史设定
- **桥梁需求**：对于完全架空的世界，需要将 Voronoi 省份导出为 GeoJSON，
  作为 CivMap 的涂色底图——两套系统在同一个空间里共存

---

## 2. 系统架构

### 2.1 图层注册表（MapLayerRegistry）

所有地图数据通过**图层注册表**统一管理。每个星球对应一个 `registry.yaml`，
记录所有栅格和矢量图层的元数据。

```yaml
# registry.yaml 示例
planet_id: planet_gaia
raster_layers:
  elevation:
    layer_type: elevation
    source: imported          # editable | engine-derived | imported
    file_path: elevation.png
    resolution: [2048, 1024]
    depends_on: []
    stale: false
  temperature:
    layer_type: temperature
    source: engine-derived
    file_path: temperature.png
    resolution: [2048, 1024]
    depends_on: [elevation]
    stale: true               # elevation 已更新，需要重新计算
  biomes:
    layer_type: biomes
    source: engine-derived
    file_path: biomes.png
    resolution: [2048, 1024]
    depends_on: [temperature, moisture]
    stale: true

vector_layers:
  voronoi:
    layer_id: voronoi
    format: voronoi-json
    file_path: voronoi.json
    depends_on: [elevation]
    stale: false
  plates:
    layer_id: plates
    format: plates-json
    file_path: plates.json
    depends_on: [elevation]
    stale: false
  provinces:
    layer_id: provinces
    format: geojson
    file_path: provinces.geojson
    depends_on: [voronoi, plates]
    stale: false
```

每个图层记录三个关键状态：

| 字段 | 含义 | 取值 |
|------|------|------|
| `source` | 数据来源 | `editable`（用户可编辑）、`engine-derived`（引擎计算）、`imported`（外部导入） |
| `depends_on` | 依赖的上游图层 | 图层 ID 列表 |
| `stale` | 是否过期 | 上游变更时通过 BFS 级联标记 |

**级联失效机制**（`mark_downstream_stale`）：

```python
def mark_downstream_stale(registry, changed_layer: str):
    """BFS 遍历依赖图，将所有下游图层标记为 stale。"""
    queue = [changed_layer]
    visited = set()
    while queue:
        layer = queue.pop(0)
        if layer in visited:
            continue
        visited.add(layer)
        # 找到所有依赖 layer 的下游图层
        for downstream in find_dependents(registry, layer):
            downstream.stale = True
            queue.append(downstream.layer_id)
```

### 2.2 图层依赖关系 DAG

```
                    ┌─────────────┐
                    │  elevation  │  ← editable / imported
                    │  (高度图)    │
                    └──────┬──────┘
                           │
            ┌──────────────┼──────────────┐
            │              │              │
            ▼              ▼              ▼
     ┌─────────────┐ ┌──────────┐ ┌──────────┐
     │   plates    │ │ features │ │ moisture │
     │  (板块分配)  │ │ (特征线) │ │ (湿度场) │
     └──────┬──────┘ └──────────┘ └──────────┘
            │                            │
            ▼                            │
     ┌─────────────┐                     │
     │  provinces  │  ← Voronoi → GeoJSON │
     │  (省份多边形) │                     │
     └──────┬──────┘                     │
            │                            │
            ▼                            ▼
     ┌──────────────┐            ┌───────────────┐
     │civ_territory │            │ temperature   │
     │ (文明涂色)    │            │ (温度场)      │
     └──────────────┘            └───────┬───────┘
                                         │
                                         ▼
                                  ┌─────────────┐
                                  │   biomes    │
                                  │ (生态群落)   │
                                  └─────────────┘
```

**关键依赖链**：

- `elevation → plates → provinces → civ_territory`：地形决定板块，板块参与省份生成，省份是涂色的最小单元
- `elevation → features`：河流、山脊、海岸线都从高度图提取
- `elevation → moisture → biomes` + `elevation → temperature → biomes`：Whittaker 图需要温度和降水两个输入

### 2.3 数据存储结构

```
layers/
├── geological/
│   ├── input/
│   │   ├── planets.yaml                    # 星球定义
│   │   └── maps/<planet_id>/               # 每个星球一个目录
│   │       ├── map.yaml                    # MapMetadata（投影、尺寸、海拔范围）
│   │       ├── elevation.png               # 16-bit 高度图（git-lfs 追踪）
│   │       ├── voronoi.json                # Voronoi 语义网络
│   │       ├── plates.json                 # 板块数据
│   │       ├── features.json               # 特征线（河流/山脊/海岸线）
│   │       └── registry.yaml               # 图层注册表
│   └── derived/
│       └── maps/<planet_id>/               # 引擎计算的派生数据
│           ├── terrain.png                 # 地形着色图
│           └── ...
├── climate/
│   └── derived/maps/<planet_id>/
│       ├── temperature.png
│       └── precipitation.png
├── ecology/
│   └── derived/maps/<planet_id>/
│       └── biomes.png
└── civilization/
    └── input/
        ├── civilizations.yaml
        └── civ_territory.yaml              # 文明涂色数据
```

> **为什么高度图用 git-lfs？**
> 一张 2048×1024 的 16-bit PNG 约 2–4 MB。多个星球 + 多次迭代后，
> 仓库体积会快速膨胀。git-lfs 将大文件存储在外部，只保留指针。

---

## 3. 核心算法

### 3.1 Voronoi 网格 → GeoJSON 多边形化

Voronoi 网络是 Dreamulator 地图系统的语义骨架。每个 `VoronoiCell` 代表一个
语义区域（可以属于某个板块、某个省份、某个 biome），引擎在 cell 级别做计算
比逐像素计算高效约 400 倍（5000 cells vs 2M pixels）。

**算法流程**：

```
输入：种子点集 S = {(lon_i, lat_i)}
                │
                ▼
┌─────────────────────────────┐
│ 1. scipy.spatial.Voronoi    │
│    + Ghost Points           │
│    (±360° 环绕)             │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│ 2. Lloyd Relaxation         │
│    (3 轮迭代)                │
│    → 均匀化 cell 大小        │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│ 3. Delaunay 邻接图           │
│    → 每个 cell 的邻居列表    │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│ 4. 多边形顶点提取            │
│    + Douglas-Peucker 简化    │
│    → GeoJSON Polygon        │
└─────────────────────────────┘
```

#### Ghost Point 方法处理经线环绕

等距柱状投影（equirectangular）的水平边界在 lon = ±180° 处相接。
Voronoi 图不知道"环绕"——边界附近的 cell 会被截断。

**解决方案**：在 ±360° 处创建"幽灵"副本点集，让边界 cell 获得正确的多边形形状：

```
                  真实区域                 ghost 副本
               ┌────────────┐        ┌────────────┐
               │            │        │            │
  lon: -180°   │   ●  ● ●  │  +360° │  ●  ● ●   │  → lon: +180°
               │ ●     ●   │        │●     ●    │
               │  ●  ●  ●  │        │ ●  ●  ●   │
               │            │        │            │
               └────────────┘        └────────────┘

  实际计算的点集 = 真实点 + ghost_left(lon-360) + ghost_right(lon+360)
  最终只保留真实点的 cell 多边形
```

代码实现（`voronoi_generator.py`）：

```python
def _lloyd_relax(points, aspect):
    n = len(points)
    # 创建 ghost 副本
    ghost_l = points.copy()
    ghost_l[:, 0] -= 360
    ghost_r = points.copy()
    ghost_r[:, 0] += 360
    all_pts = np.vstack([ghost_l, points, ghost_r])  # 3n 个点

    vor = Voronoi(all_pts)
    # 只取中间 n 个点的 Voronoi 区域
    for i in range(n, 2 * n):
        region = vor.regions[vor.point_region[i]]
        if -1 not in region and len(region) > 0:
            vertices = vor.vertices[region]
            points[i - n] = vertices.mean(axis=0)  # 质心
    return points
```

#### Douglas-Peucker 多边形简化

原始 Voronoi 多边形顶点数可能很多（尤其 Lloyd 放松后）。
使用 Douglas-Peucker 算法将顶点数控制在合理范围，
同时保持多边形形状：

```
简化前 (200+ 顶点)        简化后 (≤20 顶点)

    *──*                      *
   /    \                    / \
  *      *                  *   *
  |      |       →          |   |
  *      *                  *   *
   \    /                    \ /
    *──*                      *
```

### 3.2 省份分割策略

Voronoi 网格生成后，需要将 cell 分组为"省份"。我们提供两种策略：

#### 策略 A：Grid-Split（网格切割）

```
┌─────┬─────┬─────┬─────┐
│     │     │     │     │
│ P1  │ P2  │ P3  │ P4  │   按经纬度网格直接切分
│     │     │     │     │   → 殖民主义风格的直线边界
├─────┼─────┼─────┼─────┤
│     │     │     │     │   实现简单，适合：
│ P5  │ P6  │ P7  │ P8  │   • 快速原型
│     │     │     │     │   • 殖民地设定（美洲、非洲）
└─────┴─────┴─────┴─────┘   • 平原地区
```

**优点**：实现极简——按 lon/lat 等分即可
**缺点**：边界穿过山脉和河流，不符合自然地理

#### 策略 B：Watershed（流域分割）

```
        ∧ 山脊线（分水岭）
       / \
      /   \         每个流域 = 一个省份
     / P1  \        边界沿山脊走
    /       \
   ╱    ·    ╲      · = 流域最低点（汇水点）
──╱──河流─────╲──
```

**算法**：

1. **D8 流向计算**：每个像素的水流向 8 个邻居中海拔最低的方向流动
2. **流量累积**：从高处向低处逐像素累积流量
3. **流域识别**：流量超过阈值的像素形成河流；河流之间的山脊构成分水岭

```python
def _compute_flow_direction(elev):
    """8 方向最陡下降"""
    h, w = elev.shape
    flow = np.full((h, w), -1, dtype=np.int8)
    offsets = [(-1,-1), (-1,0), (-1,1),
               ( 0,-1),         ( 0,1),
               ( 1,-1), ( 1,0), ( 1,1)]
    for y in range(1, h-1):
        for x in range(1, w-1):
            min_e = elev[y, x]
            min_dir = -1
            for d, (dy, dx) in enumerate(offsets):
                e = elev[y+dy, x+dx]
                if e < min_e:
                    min_e = e
                    min_dir = d
            flow[y, x] = min_dir
    return flow
```

**优点**：边界沿自然地形走，符合地理常识（"翻过分水岭就是另一个省"）
**缺点**：实现复杂，且可能产生面积不均匀的省份

### 3.3 高度图导入管线

从 Gaea/World Machine 导出的高度图需要经过标准化处理才能进入 Dreamulator：

```
┌──────────────────────────────────────────────────────────┐
│                   高度图导入管线                            │
│                                                          │
│  ┌─────────┐    ┌──────────┐    ┌───────────┐            │
│  │ 格式检测  │ →  │  解码     │ →  │  归一化    │            │
│  │(magic    │    │ (PNG/    │    │ → [0, 1]  │            │
│  │ bytes)   │    │  TIFF)   │    │           │            │
│  └─────────┘    └──────────┘    └─────┬─────┘            │
│                                       │                  │
│                                ┌──────▼──────┐           │
│                                │  可选重采样  │           │
│                                │ LANCZOS/BIL │           │
│                                └──────┬──────┘           │
│                                       │                  │
│                                ┌──────▼──────┐           │
│                                │ 保存 16-bit  │           │
│                                │ PNG         │           │
│                                └─────────────┘           │
└──────────────────────────────────────────────────────────┘
```

#### 格式检测（Magic Bytes）

```python
def detect_format(data: bytes) -> str:
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return 'png'
    elif data[:2] in (b'II', b'MM'):      # TIFF: Intel / Motorola byte order
        return 'tiff'
    else:
        raise ValueError("不支持的格式")
```

#### 解码策略

| 格式 | 位深 | 库 | 模式 |
|------|------|----|------|
| PNG | 8-bit | Pillow `L` 模式 | ÷ 255 → [0, 1] |
| PNG | 16-bit | Pillow `I;16` 模式 | ÷ 65535 → [0, 1] |
| PNG | 32-bit | Pillow `I` 模式 | 假设已归一化 |
| TIFF | 16-bit | tifffile | uint16 ÷ 65535 |
| TIFF | 32-bit | tifffile | float32 直接使用 |
| TIFF | 64-bit | tifffile | float64 → float32 |

#### 重采样

```python
def _resample(elev, target_w, target_h):
    from PIL import Image
    arr_16 = (elev * 65535).astype(np.uint16)
    img = Image.fromarray(arr_16, mode='I;16')

    # 降采样用 LANCZOS（高质量抗锯齿）
    # 上采样用 BILINEAR（避免过冲）
    if target_w < elev.shape[1]:
        method = Image.Resampling.LANCZOS
    else:
        method = Image.Resampling.BILINEAR

    img = img.resize((target_w, target_h), method)
    return np.array(img, dtype=np.float64) / 65535
```

> **为什么用 16-bit 中间表示？**
> Pillow 的重采样对 `I;16` 模式支持最好。如果在 float64 上做重采样，
> Pillow 需要先转 `F` 模式，部分版本不支持 LANCZOS。

---

## 4. 数据流

### 4.1 完整数据流图

```
                    外部工具
                    ┌─────────────┐
                    │   Gaea      │
                    │  (.graph)   │
                    └──────┬──────┘
                           │ 导出
                           ▼
                    ┌─────────────┐
                    │ 16-bit TIFF │
                    │ (4096×2048) │
                    └──────┬──────┘
                           │
              ┌────────────▼────────────┐
              │   Dreamulator 导入       │
              │   importer.py           │
              │   格式检测 → 解码 → 归一化│
              │   → 重采样到目标分辨率    │
              └────────────┬────────────┘
                           │
              ┌────────────▼────────────┐
              │   elevation.png         │
              │   16-bit PNG (2048×1024)│
              │   [单一真相源]           │
              └────────────┬────────────┘
                           │
           ┌───────────────┼───────────────┐
           │               │               │
           ▼               ▼               ▼
    ┌─────────────┐ ┌─────────────┐ ┌──────────────┐
    │ Voronoi     │ │ Feature     │ │ Climate      │
    │ 重采样      │ │ 提取        │ │ Engine       │
    │ (cell 采样)  │ │ (河流/山脊) │ │ (温度/降水)  │
    └──────┬──────┘ └──────┬──────┘ └──────┬───────┘
           │               │               │
           ▼               ▼               ▼
    ┌─────────────┐ ┌─────────────┐ ┌──────────────┐
    │ 板块分配     │ │ GeoJSON     │ │ Ecology      │
    │ (flood-fill)│ │ 导出        │ │ Engine       │
    └──────┬──────┘ └──────┬──────┘ │ (biomes)     │
           │               │        └──────┬───────┘
           ▼               ▼               │
    ┌─────────────┐ ┌─────────────┐        │
    │ GeoJSON     │ │ CivMap      │        │
    │ 省份多边形   │ │ 涂色        │        │
    └─────────────┘ └─────────────┘        │
                                           ▼
                                    ┌──────────────┐
                                    │ Biome 图     │
                                    │ (Whittaker)  │
                                    └──────────────┘
```

### 4.2 分支继承机制

分支是 Dreamulator 的核心概念——类似 git branch，在某个学科层分叉，
共享该层之上的所有数据。地图系统通过 `LayerResolver` 实现继承：

```
基础世界 earth
│
├── layers/geological/input/maps/planet_gaia/
│   ├── elevation.png              ← 基础地形
│   ├── voronoi.json
│   └── plates.json
│
└── branches/
    ├── pangea (在 geological 层分叉)
    │   └── layers/geological/input/maps/planet_gaia/
    │       ├── elevation.png      ← 覆盖：盘古大陆地形
    │       ├── voronoi.json       ← 重新生成
    │       └── plates.json        ← 重新分配
    │
    └── ice-age (在 climate 层分叉)
        └── layers/climate/input/  ← 只修改气候参数
            (geological 层数据从 earth 继承，无需复制)
```

**读取链**（LayerResolver 向上搜索）：

```python
def resolve_path(layer, filename):
    """从当前分支向上搜索，返回第一个存在的文件路径。"""
    for ancestor in branch_chain:    # [当前分支, 父分支, ..., 基础世界]
        path = ancestor.layers[layer] / filename
        if path.exists():
            return path
    raise FileNotFoundError
```

**写入规则**：始终写入当前分支的目录，不修改祖先数据。

### 4.3 多精度地图的一致性保证

一个星球可能同时存在多个分辨率的地图变体：

| 变体 | 分辨率 | 用途 |
|------|--------|------|
| **Master Heightmap** | 2048×1024 ~ 4096×2048 | 单一真相源，所有派生数据的来源 |
| **Overview** | 512×256 | 缩略图、世界列表预览 |
| **Display** | 视口分辨率 | Three.js 渲染用 |
| **Regional** | 局部高分辨率 | 未来：放大某区域时叠加高频细节 |

**一致性保证**：所有变体都从 Master 派生，不存在独立编辑的副本。

```
Master Heightmap (4096×2048)
    │
    ├──→ Overview (LANCZOS 降采样 → 512×256)
    ├──→ Display (根据视口尺寸动态降采样)
    └──→ Regional (裁切子区域 + 叠加 Gaea 高频噪声)  [未来]
```

---

## 5. 设计决策记录（ADR）

### ADR-001：选择 Gaea 作为推荐外部工具

**状态**：已接受 (2026-06)

**背景**：需要为 Dreamulator 选择推荐的地形创作工具。

**决策**：推荐 QuadSpinner Gaea 作为主要外部工具。

**理由**：

| 考量 | Gaea | World Machine | World Creator |
|------|------|---------------|---------------|
| 免费版分辨率 | 4096² ✅ | 512² ❌ | 1024² |
| CLI 自动化 | ✅ | ❌ | 有限 |
| 模板复用 | `.graph` 节点图 | `.tmd` | 有限 |
| GPU 加速 | ✅ | CPU only | ✅ |

World Machine 虽然最成熟，但免费版 512×512 分辨率在现代标准下几乎不可用。
Gaea 的 CLI + `.graph` 模板化工作流特别适合 Dreamulator 的批量世界生成场景。

**后果**：导入管线需要同时支持 TIFF 和 PNG 两种格式（Gaea 默认 TIFF，
World Machine 默认 PNG）。已在 `importer.py` 中通过 magic bytes 自动检测实现。

---

### ADR-002：保留可视化、移除编辑器内编辑功能

**状态**：已接受 (2026-06)

**背景**：早期原型包含内置笔刷编辑器，但体验不佳。

**决策**：保留地图可视化（Three.js 3D 渲染 + SVG 矢量叠加），
移除高度图编辑功能，改为导入外部工具生成的高度图。

**理由**：

1. 内置笔刷需要处理高斯衰减、流量控制、多层混合——工作量相当于小型 Photoshop
2. `TerrainParams` 的 9 个参数逐一调节效率极低
3. 专业工具（Gaea/World Machine）在地形质量上远超内置生成器
4. Dreamulator 的核心价值是**推演**，不是**绘画**

**保留的编辑能力**：
- 程序化生成（`generate_map`：一键生成随机地形）
- 导入外部高度图（PNG/TIFF 文件上传）
- Voronoi 参数调节（cell 数量、放松迭代次数）

**后果**：用户需要安装外部工具来创作精细地形。对于快速原型，
程序化生成仍然可用。

---

### ADR-003：Voronoi → GeoJSON 作为两套系统的桥梁

**状态**：已接受 (2026-06)

**背景**：Planet Map（栅格 + Voronoi）和 CivMap（GeoJSON 涂色）需要共享空间。

**决策**：通过 Voronoi → GeoJSON 多边形化，将 Planet Map 的 cell 导出为
GeoJSON，作为 CivMap 的底图。

**理由**：

1. `VoronoiCell` 已预留 `province_id` 字段，数据模型天然兼容
2. GeoJSON 是 CivMap 的原生格式（Leaflet 直接渲染）
3. 转换过程无损：Voronoi 多边形化后直接输出标准 GeoJSON Polygon
4. 未来可扩展：biome、plate 等也可以导出为 GeoJSON

**实现路径**：

```python
# 伪代码
for cell in voronoi_network.cells:
    polygon = voronoi_cell_to_polygon(cell)  # scipy Voronoi regions
    simplified = douglas_peucker(polygon, tolerance=0.01)
    geojson_feature = {
        "type": "Feature",
        "properties": {
            "province_id": cell.id,
            "plate_id": cell.plate_id,
            "biome": cell.biome,
            "elevation": cell.elevation,
        },
        "geometry": {
            "type": "Polygon",
            "coordinates": [simplified]
        }
    }
```

**后果**：对于完全架空的世界，CivMap 的底图来自 Planet Map 的 Voronoi 导出；
对于基于真实地球的架空历史（如"罗马帝国存续"场景），CivMap 直接使用
Natural Earth 行政区划数据。两条路径通过 CivMap 的 `level` 参数区分。

---

### ADR-004：单一真相源 + 多分辨率派生策略

**状态**：已接受 (2026-06)

**背景**：不同场景需要不同分辨率的地图（缩略图 vs 渲染 vs 详细分析）。

**决策**：维护一个 Master Heightmap 作为唯一可编辑的版本，
所有其他分辨率的地图都从它派生。

**理由**：

1. **避免不一致**：如果允许多个版本独立编辑，必然产生分歧
2. **简化冲突解决**：分支继承只需要对比 Master，无需合并多个变体
3. **节省存储**：只存储 Master，派生版本按需生成（Overview 可以缓存）

**派生策略**：

| 操作 | 方法 | 说明 |
|------|------|------|
| 降采样 | LANCZOS | 抗锯齿，保留大尺度特征 |
| 上采样 | BILINEAR | 避免过冲（LANCZOS 可能产生负值） |
| 区域裁切 | 数组切片 + 高频叠加 | 未来实现 |

**后果**：每次编辑后需要重新生成派生版本。由于降采样非常快（<100ms），
这在实际使用中不是问题。

---

### ADR-005：MapSpec 的 LLM 辅助生成方案

**状态**：提案 (2026-07)

**背景**：创建一个详细的架空世界需要大量结构化的地图参数
（大陆形状、山脉走向、海流方向等）。手动填写 `TerrainParams` 对普通用户不友好。

**提案**：

1. 用户用自然语言描述地图设定：
   > "一个被赤道横穿的大陆，西部有南北走向的山脉，东部是广阔的平原，
   > 北方有一片被冰川覆盖的群岛"

2. LLM（通过 `narrator.py` 后端）将描述转换为 `MapSpec` 结构：
   ```yaml
   continents:
     - shape: elongated_north_south
       position: equator_crossing
       features:
         - type: mountain_range
           orientation: north_south
           position: western_edge
           height: high
         - type: plain
           position: eastern_half
           scale: large
     - shape: archipelago
       position: northern_latitudes
       features:
         - type: glacial_coverage
   ```

3. `MapSpec` 注入 `terrain_generator.py`，转化为具体的 `TerrainParams` +
   约束噪声场（如在山脉位置叠加强制高值区域）

**优势**：减少"文字设定 → 结构化参数"的人工翻译成本。
LLM 不直接生成像素（避免"幻想"物理上不可能的地形），
而是生成约束条件，由程序化生成引擎保证物理一致性。

---

## 6. 未来演进

### 6.1 MapSpec → 约束注入的程序化生成

当前的 `terrain_generator.py` 使用 6 层高斯噪声叠加生成地形。
未来计划将 MapSpec 的约束条件注入噪声场：

```
                    MapSpec 约束
                    ┌───────────────┐
                    │ 大陆形状       │
                    │ 山脉走向       │
                    │ 海盆深度       │
                    └───────┬───────┘
                            │ 转化为
                            ▼
                    ┌───────────────┐
                    │ 约束噪声场     │
                    │ (guide layer) │
                    └───────┬───────┘
                            │ 叠加
                            ▼
┌─────────────────────────────────────────┐
│         terrain_generator.py            │
│                                         │
│  continental_base  ← guide layer 调制   │
│  + mountain_ridges ← 方向约束           │
│  + medium_detail                        │
│  + fine_roughness                       │
│  + latitude_effect                      │
│  + continental_shelf                    │
└─────────────────────────────────────────┘
```

**示例**：如果 MapSpec 指定"西部南北山脉"，则在大陆噪声场上叠加
一个南北走向的高斯脊线函数，使西部区域的海拔被强制抬高。

### 6.2 气候引擎和生态引擎的地图图层

当前已实现的引擎输出：

| 引擎 | 输出图层 | 状态 |
|------|----------|------|
| `terrain_generator` | elevation.png | ✅ 已实现 |
| `feature_extractor` | features.json | ✅ 已实现 |
| `voronoi_generator` | voronoi.json + plates.json | ✅ 已实现 |
| climate engine | temperature.png, precipitation.png | 🔧 开发中 |
| ecology engine | biomes.png | 📋 计划中 |

**气候引擎计划**：

- **温度**：基于纬度 + 海拔的温度递减率（lapse rate ≈ -6.5°C/km）
- **降水**：基于风场 + 地形雨影效应的简化模型
  - 主导风向 → 迎风坡增雨 + 背风坡减雨
  - 山脉阻挡 → 雨影沙漠（如安第斯山脉东侧的巴塔哥尼亚）

**生态引擎计划**：

- **Whittaker Biome Diagram**：温度 × 降水 → biome 类型
  ```
  温度高 + 降水多 → 热带雨林
  温度高 + 降水少 → 热带荒漠
  温度低 + 降水多 → 针叶林
  温度低 + 降水少 → 苔原
  ```
- 每个 VoronoiCell 根据 `(temperature, precipitation)` 查表分配 biome

### 6.3 区域放大（Regional）的详细设计

对于"放大查看某个区域的地形细节"的需求：

```
┌──────────────────────────────────────────┐
│           Master Heightmap               │
│           (2048 × 1024)                  │
│                                          │
│        ┌────────────┐                    │
│        │ 裁切区域    │                    │
│        │ (512×256)  │                    │
│        └─────┬──────┘                    │
└──────────────┼───────────────────────────┘
               │
               ▼
      ┌────────────────┐
      │ 上采样到目标分辨率│
      │ BILINEAR       │
      │ (2048×1024)    │
      └────────┬───────┘
               │
               │  叠加
               ▼
      ┌────────────────┐     ┌─────────────────┐
      │ 高频细节        │ ←── │ Gaea 高频噪声    │
      │ (程序化生成)    │     │ 或分形噪声       │
      └────────────────┘     └─────────────────┘

      最终 Regional 高度图 = 上采样的低频 + 高频细节
```

这种方案保证：
1. Regional 与 Master 的大尺度地形一致（来自同一源）
2. 放大后有足够的高频细节（岩石、沟壑、小溪）
3. 高频细节可以程序化生成，也可以由用户在 Gaea 中精细制作

---

## 7. 技术栈

### 7.1 Python 后端

| 库 | 版本 | 用途 |
|----|------|------|
| `scipy` | ≥1.10 | Voronoi/Delaunay 计算、ndimage 形态学操作 |
| `numpy` | ≥1.24 | 数值数组运算、高度图处理 |
| `Pillow` | ≥9.0 | PNG 编解码（16-bit 支持）、图像重采样 |
| `tifffile` | ≥2023.0 | TIFF 高度图解码（16/32/64-bit） |
| `shapely` | ≥2.0 | GeoJSON 多边形简化、面积计算 |
| `PyYAML` | ≥6.0 | YAML 元数据读写 |
| `pydantic` | ≥2.0 | 数据模型验证 |
| `FastAPI` | ≥0.100 | REST API 服务 |

**关键 scipy 用法**：

```python
from scipy.spatial import Voronoi, Delaunay
from scipy.ndimage import gaussian_filter, binary_dilation, binary_erosion, label

# Voronoi 网格生成
vor = Voronoi(points)

# Delaunay 三角剖分 → 邻接图
tri = Delaunay(points)
for simplex in tri.simplices:
    for i in range(3):
        adj[simplex[i]].append(simplex[(i+1) % 3])

# 形态学操作 → 海岸线提取
coastline = binary_dilation(land) ^ binary_erosion(land)

# 连通区域标记 → 河流/山脊分段
labeled, num_features = label(river_mask)
```

### 7.2 TypeScript / React 前端

| 库 | 用途 |
|----|------|
| **Three.js** | 3D 地形渲染（WebGPU 优先，WebGL 回退） |
| **Leaflet.js** | CivMap 2D 地图渲染 |
| **React Query** | API 数据获取 + 缓存 + 乐观更新 |
| **Zustand** | 全局状态管理（分支选择、UI 状态） |

**Three.js 渲染管线**：

```
API 返回 elevation.png (Blob)
        │
        ▼
decodePngToFloat32()
  ImageBitmap → OffscreenCanvas → Float32Array
        │
        ▼
useTerrainTexture()
  OffscreenCanvas: LUT 着色 + 山体阴影 + 水面
        │
        ▼
THREE.CanvasTexture
        │
        ▼
MeshBasicMaterial + PlaneGeometry
  (3 个 mesh: main + 2 ghost 实现水平环绕)
        │
        ▼
WebGPURenderer (D3D12 backend)
  失败时 fallback → WebGLRenderer
```

> **为什么用 CPU 预渲染 + GPU 显示？**
> AMD Radeon 集显 + Windows ANGLE/D3L11 驱动在顶点属性插值上存在 bug
> （详见 CLAUDE.md 中的调试记录）。绕过方案：所有颜色计算在 CPU 完成，
> GPU 只负责贴图显示。这个方案在所有硬件上都能稳定工作。

**CivMap 渲染管线**：

```
API 返回 adm1.geojson
        │
        ▼
Leaflet GeoJSON Layer
  preferCanvas: true (性能优化)
        │
        ▼
每个 province 一个 path
  fill color ← country.color (通过 assignment 查找)
  click → onProvincePaint(adm1_code)
        │
        ▼
PATCH /civmap/snapshots/{id}/assignments
  React Query 乐观更新 → 即时视觉反馈
```

### 7.3 文件格式汇总

| 格式 | 扩展名 | 用途 | 存储方式 |
|------|--------|------|----------|
| 16-bit PNG | `.png` | 高度图 (elevation) | git-lfs |
| JSON | `.json` | Voronoi 网络、板块数据 | git |
| GeoJSON | `.geojson` | 省份多边形、行政区划 | git |
| YAML | `.yaml` | 元数据、注册表、领土数据 | git |

### 7.4 API 端点一览

#### Planet Map API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/worlds/{w}/maps` | 列出有地图的星球 |
| GET | `/api/worlds/{w}/maps/{p}/meta` | 地图元数据 |
| GET | `/api/worlds/{w}/maps/{p}/elevation` | 高度图 PNG |
| GET | `/api/worlds/{w}/maps/{p}/voronoi` | Voronoi 网络 |
| GET | `/api/worlds/{w}/maps/{p}/plates` | 板块数据 |
| GET | `/api/worlds/{w}/maps/{p}/features` | 特征线 |
| GET | `/api/worlds/{w}/maps/{p}/layer/{type}` | 派生图层 PNG |
| POST | `/api/worlds/{w}/maps/{p}/elevation` | 上传高度图 |
| POST | `/api/worlds/{w}/maps/{p}/import-elevation` | 导入外部高度图 |
| POST | `/api/worlds/{w}/maps/{p}/generate` | 程序化生成 |
| DELETE | `/api/worlds/{w}/maps/{p}` | 删除地图数据 |

#### CivMap API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/worlds/{w}/civmap/boundaries/{level}` | 行政区划 GeoJSON |
| GET | `/api/worlds/{w}/civmap/territory` | 领土数据 |
| POST | `/api/worlds/{w}/civmap/countries` | 创建/更新国家 |
| GET | `/api/worlds/{w}/civmap/snapshots` | 快照列表 |
| PATCH | `/api/worlds/{w}/civmap/snapshots/{id}/assignments` | 涂色/擦除 |

> 所有端点支持 `?branch=xxx` 查询参数，用于分支切换。

---

## 附录 A：关键数据结构

### VoronoiCell

```python
class VoronoiCell(BaseModel):
    id: int                      # 0-based 唯一 ID
    lon: float                   # 经度 (°)
    lat: float                   # 纬度 (°)
    elevation: float             # 归一化海拔 [0, 1]
    moisture: float              # 归一化湿度 [0, 1]
    neighbors: list[int]         # 相邻 cell ID 列表
    plate_id: int | None         # 所属板块
    biome: str | None            # 生态群落类型
    province_id: str | None      # 所属省份（CivMap 桥梁字段）
```

### MapMetadata

```python
class MapMetadata(BaseModel):
    planet_id: str               # 星球 ID
    projection: MapProjection    # 投影方式（目前仅 equirectangular）
    width: int = 2048            # 像素宽度
    height: int = 1024           # 像素高度
    elevation_min_m: float = -11000  # 最低海拔（米）
    elevation_max_m: float = 9000    # 最高海拔（米）
    sea_level: float             # 归一化海平面 [0, 1]
    voronoi_seed: int            # Voronoi 随机种子
    voronoi_num_cells: int = 5000   # Voronoi cell 数量
```

### TectonicPlate

```python
class TectonicPlate(BaseModel):
    id: int
    name: str
    type: PlateType              # oceanic | continental | mixed
    cell_ids: list[int]          # 包含的 Voronoi cell
    velocity: PlateVelocity      # 运动矢量 (dx, dy)
```

---

## 附录 B：Bilibili 视频脚本大纲

> 以下为未来 Bilibili 介绍视频的参考结构。

### Part 1：为什么要做地图系统？（2 分钟）

- 架空世界需要"画地图"——但市面上的工具要么太贵，要么太简单
- Dreamulator 的思路：不做编辑器，做**推演引擎**
- 对比演示：World Machine 手动设计 vs Dreamulator 一键生成 + 物理推演

### Part 2：两套地图系统（3 分钟）

- Planet Map：栅格高度图 + Voronoi 语义网络 → Three.js 3D 可视化
- CivMap：真实地球底图 + 虚构国家涂色 → Leaflet 2D 编辑器
- 桥梁：Voronoi cell 导出为 GeoJSON

### Part 3：从 Gaea 到 Dreamulator（3 分钟）

- 演示 Gaea 节点图 → 导出 TIFF → Dreamulator 导入
- 格式自动检测、分辨率适配、分支继承
- 一键程序化生成 vs 精细外部工具

### Part 4：核心技术揭秘（4 分钟）

- Voronoi + Ghost Points 经线环绕处理
- 板块 flood-fill 分配
- 特征提取：D8 流向 → 河流网络
- CPU 预渲染 + GPU 显示的架构决策（含 AMD bug 故事）

### Part 5：未来展望（2 分钟）

- 气候引擎：温度场 + 降水场自动生成
- 生态引擎：Whittaker biome 图
- MapSpec：用自然语言描述世界 → LLM 生成约束 → 程序化引擎保证物理一致性

---

*文档结束。如有疑问或建议，请在 GitHub Issues 中讨论。*
