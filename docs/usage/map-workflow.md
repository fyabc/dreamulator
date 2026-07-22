# 地图工作流指南

本文档介绍 dreamulator 的地图生成工作流——从球面 CVT 网格出发，自动完成板块构造、地形生成、河流网络、气候模拟的完整管线，并提供可选的 Gaea 局部精细化能力。

> **相关文档**：[地图系统架构](map-system.md) · [文明地图使用指南](civmap-guide.md)

> **技术参考**：[行星地形生成管线](terrain-pipeline.md) — 各阶段的算法原理与数学公式

---

## 目录

1. [概述](#1-概述)
2. [快速开始](#2-快速开始)
3. [生成管线详解](#3-生成管线详解)
4. [配置参数](#4-配置参数)
5. [在编辑器中查看](#5-在编辑器中查看)
6. [Gaea 局部精细化（高级）](#6-gaea-局部精细化高级)
7. [迭代与分支](#7-迭代与分支)
8. [数据存储](#8-数据存储)
9. [附录](#9-附录)

---

## 1. 概述

dreamulator 的地图系统采用**球面质心 Voronoi 镶嵌（Spherical CVT）**作为核心数据结构。所有地形生成——板块构造、山脉形成、河流汇水、气候分布——都直接在球面网格上完成，最终投影为等距圆柱高度图用于渲染和导出。

系统通过少量参数即可在约 60 秒内生成一个包含完整地质和气候信息的行星地图。Gaea 可用于局部区域的精细化侵蚀模拟（详见[第 6 节](#6-gaea-局部精细化高级)）。

### 管线流程

```
球面点集                 CVT 网格              板块构造
┌──────────┐          ┌──────────┐          ┌──────────┐
│ 均匀采样  │ ───────▶ │ 10万 cell │ ───────▶ │ 20 板块  │
│ + jitter │  Lloyd   │ 球面Voronoi│  分配    │ 欧拉极   │
└──────────┘  松弛    └──────────┘          └────┬─────┘
                                                 │
                                  边界分析        ▼
┌──────────┐          ┌──────────┐          ┌──────────┐
│ 气候模拟  │ ◀─────── │ 海平面   │ ◀─────── │ 山脉/裂谷│
│ 温/降/Köp│  叠加    │ 海陆划分  │  噪声    │ 碰撞/张裂│
└────┬─────┘          └──────────┘          └──────────┘
     │
     ▼
┌──────────┐          ┌──────────┐          ┌──────────┐
│ 河流网络  │ ───────▶ │ 侵蚀模拟  │ ───────▶ │ 导出     │
│ 汇水算法  │          │ 热/水侵蚀 │  投影    │ 高度图PNG│
└──────────┘          └──────────┘          └──────────┘
```

### 核心特性

- **球面 CVT 网格**：10 万 cell 的质心 Voronoi 镶嵌，直接在球面上运算
- **自动板块构造**：20 个构造板块，基于欧拉极运动学生成山脉、裂谷、海沟
- **河流网络**：图论汇水算法，自动形成河流、湖泊和入海口
- **气候模拟**：温度、降水、Köppen 气候分类全自动计算
- **可复现性**：相同种子 + 相同参数 = 相同结果
- **生成时间**：约 60 秒完成全部管线
- **可选 Gaea 精细化**：局部区域的高精度侵蚀模拟（详见第 6 节）

---

## 2. 快速开始

### 2.1 CLI 生成

最快速的生成方式——一行命令完成全部管线：

```bash
uv run dreamulator map generate myworld satellite_gaiam
```

**预期输出**：

```
🌍 Generating map for planet 'satellite_gaiam' in world 'myworld'...
  [1/9] CVT mesh generation (100,000 cells) ......... 8.2s
  [2/9] Tectonic plates (20 plates) .................. 2.1s
  [3/9] Boundary analysis & terrain .................. 5.4s
  [4/9] Noise overlay (6 octaves) .................... 3.7s
  [5/9] Sea level calibration ........................ 0.3s
  [6/9] Climate simulation ........................... 12.8s
  [7/9] River network ................................ 8.6s
  [8/9] Erosion simulation ........................... 15.2s
  [9/9] Export (equirectangular 2048×1024) ........... 3.1s
✅ Map generated in 59.4s
   → data/worlds/myworld/maps/satellite_gaiam/
```

整个流程大约需要 60 秒（视机器性能和网格密度而定）。生成完成后，所有数据文件会自动写入行星的地图目录。

**自定义参数**：

```bash
# 使用不同种子
uv run dreamulator map generate myworld satellite_gaiam --seed 123

# 更多板块、更高海平面
uv run dreamulator map generate myworld satellite_gaiam --num-plates 30 --sea-level 50

# 使用配置文件
uv run dreamulator map generate myworld satellite_gaiam -c config.yaml
```

### 2.2 API 生成

通过 REST API 触发生成（适合自动化脚本和前端调用）：

```bash
curl -X POST "http://localhost:8000/api/worlds/myworld/maps/satellite_gaiam/generate" \
  -H "Content-Type: application/json" \
  -d '{
    "seed": 42,
    "num_nodes": 100000,
    "num_plates": 20,
    "sea_level_m": 0
  }'
```

响应示例：

```json
{
  "ok": true,
  "planet_id": "satellite_gaiam",
  "projection": "equirectangular",
  "width": 2048,
  "height": 1024,
  "generation_time_s": 59.4
}
```

### 2.3 前端生成

在前端地图编辑器中，点击左侧面板的 **「🌍 生成地形」** 按钮即可触发程序化生成。生成过程中会显示进度条和当前阶段名称，完成后编辑器自动刷新显示新地形。

### 2.4 输出文件

生成完成后，以下文件被创建在 `maps/<planet_id>/` 目录下：

| 文件 | 大小 | 说明 |
|------|------|------|
| `elevation.png` | ~2 MB | 16-bit 等距圆柱高度图（可视化 + 渲染用） |
| `voronoi.json` | ~15 MB | 10 万 cell 球面 CVT 网格（**主要数据**） |
| `plates.json` | ~50 KB | 20 个构造板块定义（含欧拉极参数） |
| `features.json` | ~2 MB | 河流、山脊、海岸线等线性特征 |
| `climate.json` | ~8 MB | 每 cell 气候数据（温度、降水、Köppen 分类） |
| `map.yaml` | ~1 KB | 元数据（投影、参数、生成时间） |

> **重要**：`voronoi.json` 是主要数据——所有后续模拟（气候、生态、文明）都基于这个网格运行。`elevation.png` 是从网格导出的可视化副产品。

---

## 3. 生成管线详解

生成管线按顺序执行以下阶段。每个阶段都可以通过参数调节（详见[第 4 节](#4-配置参数)）。

### Stage 1：CVT 网格生成

在球面上均匀撒点，通过 Lloyd 松弛迭代使点分布趋于均匀，最终形成质心 Voronoi 镶嵌。

```
球面 → 均匀采样 → jitter 扰动 → Lloyd 松弛 → CVT 网格
```

**关键参数**：
- `num_nodes`：网格节点数（默认 100,000）。越多 → 地形细节越丰富，但生成越慢
- `jitter_sigma`：初始点的随机扰动强度（默认 0.3）。0 = 完全规则，0.5 = 高度随机
- `lloyd_iterations`：Lloyd 松弛迭代次数（默认 8）。越多 → cell 越均匀，但边际递减

**输出**：每个 cell 包含经纬度坐标、邻居列表、面积信息。

### Stage 2：板块构造

将 CVT 网格划分为若干构造板块，每个板块用欧拉极（Euler pole）描述其运动方向和速度。

```
CVT 网格 → 种子点选取 → 区域生长 → 板块分配 → 欧拉极赋值
```

**关键参数**：
- `num_plates`：板块数量（默认 20）。越多 → 地质结构越复杂
- 板块类型自动分配：`oceanic`（纯洋壳）、`continental`（含陆壳）、`mixed`（混合）

**输出**：每个板块的名称、类型、包含的 cell 列表、欧拉极（lat, lon, angular_velocity）。

### Stage 3：边界分析与地形生成

根据相邻板块的欧拉极相对运动，自动判定板块边界类型并生成对应地形：

| 边界类型 | 运动方式 | 地形效果 |
|----------|----------|----------|
| **汇聚型**（convergent） | 板块相向运动 | 褶皱山脉、海沟、火山弧 |
| **张裂型**（divergent） | 板块背离运动 | 大洋中脊、裂谷 |
| **转换型**（transform） | 板块侧向滑动 | 断层线、微地形起伏 |

**关键参数**：
- `boundary_influence_km`：边界效应影响半径（默认 500 km）。越宽 → 山脉/裂谷带越宽
- `mountain_height`：汇聚边界的基准山脉高度（默认 6000 m）
- `rift_depth`：张裂边界的裂谷深度（默认 -2000 m）

### Stage 4：噪声叠加

在构造地形之上叠加多频率高斯噪声，模拟中小尺度地形起伏（丘陵、盆地、平原微地形）。

**关键参数**：
- `noise_octaves`：噪声层数（默认 6）。越多 → 地形层次越丰富
- `noise_persistence`：每层振幅衰减（默认 0.5）。越高 → 高频成分越强，地形越崎岖
- `noise_lacunarity`：每层频率递增（默认 2.0）。越高 → 各层尺度差异越大

### Stage 5：海平面校准

设定全球海平面高度，划分海洋与陆地。

**关键参数**：
- `sea_level_m`：海平面海拔（默认 0 m）。正值 → 更多海洋，负值 → 更多陆地
- `sea_level_target`：（可选）目标海洋面积比例。设置后系统自动校准 `sea_level_m`

### Stage 6：气候模拟

基于纬度、海拔、海洋距离等因素，为每个 cell 计算温度和降水：

1. **温度**：纬度梯度（赤道暖、极地冷）+ 海拔递减率（每 1000m 降 6.5°C）
2. **风场**：简化行星风系（信风、西风、极地东风）
3. **降水**：迎风坡增雨 + 背风坡雨影效应 + 距海距离衰减
4. **Köppen 分类**：根据温度和降水自动分类气候带（热带雨林、沙漠、苔原等）

**关键参数**：
- `equator_temp_c`：赤道平均温度（默认 25°C）
- `pole_temp_c`：极地平均温度（默认 -20°C）
- `rain_shadow_strength`：雨影效应强度（默认 0.6）
- `moisture_decay_distance`：水汽距海衰减距离（默认 2000 km）

### Stage 7：河流生成

使用图论汇水算法，在网格上模拟地表径流：

```
每个 cell 的降水 → 沿坡度最陡方向汇流 → 累积流量 → 超过阈值形成河流
```

**关键参数**：
- `river_flow_threshold`：形成河流的最小累积流量（默认 500）。越低 → 河流越密集
- `min_river_length`：最短河流长度（默认 3 cells），过滤短小溪流

**输出**：每条河流的源头、流经 cell 序列、入海口、流量等级。

### Stage 8：侵蚀模拟

对地形进行后处理侵蚀，使地貌更加自然：

- **热侵蚀**（Thermal erosion）：模拟风化作用，将陡坡物质向下滑移，软化尖锐地形
- **视觉水侵蚀**（Visual water erosion）：沿河流路径刻蚀河谷，形成 V 形谷和冲积扇

**关键参数**：
- `thermal_iterations`：热侵蚀迭代次数（默认 10）
- `water_erosion_strength`：水侵蚀强度（默认 0.3）

> 侵蚀仅作用于视觉效果，不改变气候模拟结果（气候在侵蚀前已完成计算）。

### Stage 9：导出

将球面 CVT 网格投影为等距圆柱（equirectangular）高度图 PNG，供编辑器和 3D 球体渲染使用。

**关键参数**：
- `export_width` / `export_height`：输出分辨率（默认 2048×1024）

导出过程使用面积加权插值，确保球面 cell 的值正确映射到矩形像素上。

---

## 4. 配置参数

### 4.1 基础参数

这些参数控制地图的宏观特征，适合大多数用户调整：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `num_nodes` | 100,000 | CVT 网格节点数 |
| `num_plates` | 20 | 构造板块数量 |
| `sea_level_m` | 0 | 海平面海拔（米） |
| `seed` | 世界种子 | 随机种子，控制所有程序化生成 |

### 4.2 高级参数

这些参数提供精细控制，适合需要特定地貌效果时使用：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `lloyd_iterations` | 8 | Lloyd 松弛迭代次数 |
| `jitter_sigma` | 0.3 | 初始点随机扰动强度（× 平均间距） |
| `boundary_influence_km` | 500 | 板块边界效应影响半径（km） |
| `mountain_height` | 6000 | 汇聚边界基准山脉高度（m） |
| `rift_depth` | -2000 | 张裂边界裂谷深度（m） |
| `noise_octaves` | 6 | 噪声叠加层数 |
| `noise_persistence` | 0.5 | 噪声振幅衰减率 [0, 1] |
| `noise_lacunarity` | 2.0 | 噪声频率递增率 |
| `equator_temp_c` | 25 | 赤道平均温度（°C） |
| `pole_temp_c` | -20 | 极地平均温度（°C） |
| `rain_shadow_strength` | 0.6 | 雨影效应强度 [0, 1] |
| `river_flow_threshold` | 500 | 河流形成的最小累积流量 |
| `thermal_iterations` | 10 | 热侵蚀迭代次数 |
| `water_erosion_strength` | 0.3 | 水侵蚀强度 [0, 1] |
| `export_width` | 2048 | 导出高度图宽度（像素） |
| `export_height` | 1024 | 导出高度图高度（像素） |

### 4.3 配置文件

对于需要精细控制的场景，建议使用 YAML 配置文件。以下是一个类地行星的完整配置：

```yaml
# earthlike_terrain.yaml — 类地行星地形配置
terrain:
  num_nodes: 100000
  num_plates: 20
  sea_level_m: 0
  seed: 42

  # 网格参数
  mesh:
    lloyd_iterations: 8
    jitter_sigma: 0.3

  # 构造参数
  tectonics:
    boundary_influence_km: 500
    mountain_height: 6000
    rift_depth: -2000

  # 噪声参数
  noise:
    octaves: 6
    persistence: 0.5
    lacunarity: 2.0

  # 气候参数
  climate:
    equator_temp_c: 25
    pole_temp_c: -20
    rain_shadow_strength: 0.6
    moisture_decay_distance: 2000

  # 河流参数
  rivers:
    flow_threshold: 500
    min_river_length: 3

  # 侵蚀参数
  erosion:
    thermal_iterations: 50
    water_erosion_strength: 0.3

  # 导出参数
  export:
    width: 2048
    height: 1024
```

使用配置文件生成：

```bash
uv run dreamulator map generate myworld satellite_gaiam -c earthlike_terrain.yaml
```

### 4.4 预设模板

系统内置了几种常见行星类型的预设模板，可通过 `--preset` 参数直接使用：

| 预设 | 说明 | 关键差异 |
|------|------|----------|
| `earthlike` | 类地行星（默认） | 20 板块，海平面 0m，温带气候 |
| `ocean_world` | 海洋行星 | 海平面 +500m，少量大型板块 |
| `desert_world` | 干旱行星 | 海平面 -300m，降水衰减 2x |
| `archipelago` | 群岛行星 | 海平面 +200m，40 个小板块 |

```bash
uv run dreamulator map generate myworld satellite_gaiam --preset ocean_world
```

预设提供合理的默认值，你仍可以通过 CLI 参数或配置文件覆盖任意选项。

### 4.5 参数效果速查表

快速参考——调整某个参数时地形会如何变化：

| 参数 | 增大 → | 减小 → |
|------|--------|--------|
| `num_plates` | 更多山脉、更碎裂的大陆 | 更少更大的板块、更平坦 |
| `sea_level_m` | 更多海洋、更小的陆地 | 更多陆地、更少海洋 |
| `noise_persistence` | 更崎岖的地形、更多峡谷 | 更平缓的地形、更宽阔的高原 |
| `noise_octaves` | 更多中小尺度细节 | 更平滑、缺少小地形特征 |
| `mountain_height` | 更高更壮观的山脉 | 低矮丘陵 |
| `boundary_influence_km` | 更宽的山脉带/裂谷带 | 窄而陡峭的边界地形 |
| `equator_temp_c` | 更热的热带、更大的沙漠 | 更凉爽、更多温带气候 |
| `pole_temp_c` | 更暖的极地、更小的冰盖 | 更冷、更大的冰盖 |
| `river_flow_threshold` | 更少但更大的主干河流 | 更密集的河网 |
| `num_nodes` | 更精细的网格、更丰富的细节 | 更粗糙的网格、更快的生成速度 |
| `lloyd_iterations` | 更均匀的 cell 分布 | 更不规则的 cell 形状 |
| `water_erosion_strength` | 更深的河谷、更明显的冲积扇 | 更平缓的河谷 |

---

## 5. 在查看器中查看

### 5.1 启动服务器

```bash
uv run dreamulator serve --open
```

浏览器会自动打开。进入目标世界 → 选择行星 → 进入地图查看器。

### 5.2 查看器布局

```
┌─────────────────────────────────────────────────────────────────┐
│  顶栏：返回 · 世界名 · 行星选择 · 投影切换 ▼                   │
├──────────┬───────────────────────────────┬──────────────────────┤
│          │                               │  右面板              │
│  图层面板 │        中央地图视图            │                      │
│          │                               │  · 未选中: 行星摘要  │
│ 【地理】  │  地形渲染 + 山体阴影           │    (海陆比例/高程/   │
│  · 地形   │  (Canvas 2D 预渲染 +          │     板块数/节点数)   │
│  · 海陆   │   Three.js 显示)              │                      │
│          │                               │  · 悬停: 单元格详情  │
│ 【地质】  │  + SVG 高亮层                 │    (经纬度/海拔/     │
│  · 板块   │  (hover/select 反馈)          │     地壳/板块/边界)  │
│  · 边界   │                               │                      │
│          │                               │  · 选中: 多单元格    │
├──────────┴───────────────────────────────┴──────────────────────┤
│  底栏：经度 · 纬度 · 海拔(m) · 地壳类型 · 板块名               │
└─────────────────────────────────────────────────────────────────┘
```

**导航操作**：

| 操作 | 方式 |
|------|------|
| 平移 | 按住鼠标左键拖拽（水平无限环绕） |
| 缩放 | 鼠标滚轮（最小 = 地图填满视口，最大 20x） |
| 查看属性 | 移动鼠标，底栏实时显示经纬度、海拔、地壳类型、板块 |
| 选中单元格 | 单击（Shift+单击多选），右面板显示详细属性 |

### 5.3 着色模式（按概念分组）

图层面板按学科概念分组，提供 4 种可视化模式：

**【地理】组：**

| 模式 | 说明 | 用途 |
|------|------|------|
| **地形** | 自适应分层设色（深蓝→浅蓝→绿→黄→棕→紫）+ 山体阴影 | 整体地貌概览 |
| **海陆** | 二值着色，深色海洋 + 浅色陆地 | 查看海陆比例 |

**【地质】组：**

| 模式 | 说明 | 用途 |
|------|------|------|
| **板块** | 按构造板块 ID 随机色着色 | 查看板块分布和大小 |
| **边界类型** | 汇聚（红）· 离散（绿）· 转换（黄） | 分析板块边界运动 |

> **自适应配色**：地形模式的色标根据行星实际高程范围自动计算断点，
> 无需手动调整。海洋从深蓝（最深）到浅蓝（海岸），陆地进行类似渐变。

#### 配色方案

地形模式的混合 hypsometric tint 配色，参考了下表所列三种业界常用方案后，
选取了 **海洋 C + 陆地 B** 的混合方案：

| 方案 | 来源 | 风格 | 特点 |
|------|------|------|------|
| **A** | 经典 Bartholomew | 制图传统 | 绿色→黄色→棕色→灰色→白色，教科书标准 |
| **B** | ESRI / ArcGIS Natural Earth | 现代 GIS | 色彩鲜明，分层设色对比度强 |
| **C** | NOAA ETOPO1 v2.64 | 科研出版物 | 海洋冷暖渐变精细，强调物理深度感 |

**配色表**（`colorScales.ts` → `generateAdaptiveTerrainScale`）：

| 高程 | 颜色 | Hex | 说明 |
|------|------|-----|------|
| 最深点 (minElev) | ██ | `#023858` | 深海沟 — C |
| +15% range | ██ | `#045A8D` | 深海 — C |
| +30% range | ██ | `#2B8CBE` | 中海 — C |
| 海平面 -2% (≥200m) | ██ | `#74A9CF` | 浅海 — C |
| 海平面 -0.5% (≥50m) | ██ | `#A8D8EA` | 近海 — C |
| 海平面 (0m) | ██ | `#C8B898` | 沙色海岸线 |
| +0.5% (≥50m) | ██ | `#7DAF5A` | 滨海绿 — B |
| +2% range | ██ | `#2F7A3C` | 森林深绿 — B |
| +8% range | ██ | `#A0B040` | 丘陵黄绿 — B |
| +18% range | ██ | `#C8A858` | 台地黄棕 — B |
| +30% range | ██ | `#8B5E3C` | 山地棕 — B |
| +35% range | ██ | `#A08078` | 高山灰棕 — B |
| +40% range | ██ | `#D8D0C8` | 积雪灰 — B |
| 最高点 (maxElev) | ██ | `#FFFFFF` | 山顶白 — B |

**参考来源**：
- Thuillier et al. (2024) *Colour Palettes for Digital Elevation Models*. Zenodo. [DOI: 10.5281/zenodo.10530295](https://doi.org/10.5281/zenodo.10530295)
- Patterson, T. *Cross-blended Hypsometric Tints*. [shadedrelief.com](http://www.shadedrelief.com/hypsometric/)
- Wikipedia: [Hypsometric tints](https://en.wikipedia.org/wiki/Hypsometric_tints)
- NOAA NCEI: [ETOPO1 Global Relief Model](https://www.ngdc.noaa.gov/mgg/global/)

### 5.4 投影切换

右上角下拉菜单支持 3 种地图投影：

| 投影 | 类型 | 特点 | 适合场景 | 参考 |
|------|------|------|---------|------|
| **等距圆柱** (Equirectangular) | 圆柱投影 | 2:1 矩形，水平环绕，经纬线正交 | 默认视图，GPU 渲染，全面概览 | [ArcGIS 文档](https://desktop.arcgis.com/zh-cn/arcmap/latest/map/projections/equidistant-cylindrical.htm) |
| **Mollweide** | 伪圆柱投影（等积） | 2:1 椭圆外形，面积准确但形状畸变 | 面积分析（海陆比例、气候带） | [ArcGIS 文档](https://desktop.arcgis.com/zh-cn/arcmap/latest/map/projections/mollweide.htm) |
| **Robinson** | 伪圆柱投影（折中） | 约 2.66:1，曲线边缘，视觉美观 | 展示用途，曾为《国家地理》标准 | [ArcGIS 文档](https://desktop.arcgis.com/zh-cn/arcmap/latest/map/projections/robinson.htm) |

#### 投影与交互语义

三种投影共享相同的**地理坐标级**平移/缩放模型（`mapCenter.lon/lat` + `zoom`）——即平移改
变地图中心的地理经纬度，缩放改变视口覆盖的度数范围。投影仅在 `project`/`unproject`
（地理 ↔ 屏幕坐标）层面产生差异。

具体行为：

| 操作 | 等距圆柱 | Mollweide / Robinson |
|------|---------|---------------------|
| **左右平移** | 经度绕回，无缝循环 | 经度绕回，但投影边缘有透明区域 |
| **上下平移** | 到极点自然截止 | 到极点自然截止；离中央经线远时畸变大 |
| **缩放** | 以屏幕中心为锚点缩放 | 同左，地图占据的视口面积变化 |
| **投影边界** | 填满视口（矩形） | 非矩形 — 边缘外为透明/背景色 |

**关键设计决策**：伪圆柱投影的边缘透明区域**保留**，不做额外裁剪或 fit-to-viewport。
这遵循 QGIS / ArcGIS 的标准行为——让用户直观看到投影的形状特征。如需填满视口，
切换到等距圆柱即可。

#### 坐标系统设计

前端使用统一的坐标模块 `mapCoords.ts`（24 个单元测试）：

```
视图状态 ViewState = { mapCenter: {lon, lat}, zoom }
屏幕坐标 screen = project(geo, viewState, viewport)
地理坐标 geo     = unproject(screen, viewState, viewport)
平移后的新状态    = applyDrag(state, {dx, dy}, viewport)
缩放后的新状态    = applyZoom(state, factor, anchor, viewport)
```

`mapCenter.lon` 始终保持在 `[-180, 180]`（取模绕回），不累积溢出。所有计算与
投影类型解耦——切换投影只改变 `project`/`unproject` 的实现（GPU 路径用等距圆柱
公式快速计算，CPU 路径走 `projectForward`/`projectInverse`）。

### 5.5 单元格详情（右面板）

**未选中时 — 行星摘要：**

| 信息 | 说明 |
|------|------|
| 行星名 + Seed | 标识信息 |
| 海陆比例 | X% 陆地 / Y% 海洋 |
| 高程范围 | [最低, 最高] m |
| 板块数 | 构造板块总数 |
| 网格节点 | CVT cell 总数 |

**悬停/选中时 — 单元格属性：**

| 属性 | 说明 |
|------|------|
| 经度 / 纬度 | 地理坐标（度） |
| 海拔 | 米（绝对值） |
| 地壳类型 | oceanic / continental / transitional |
| 板块 | 所属构造板块 ID |
| 边界类型 | convergent / divergent / transform / 无 |
| 汇聚速率 | cm/yr |
| 距边界距离 | km |
| 面积 | km² |

### 5.6 前端性能优化

地图查看器使用 **KD-tree 数学命中测试** 替代 SVG polygon hit-test，
确保 10 万节点下的流畅交互体验：

- **hover 延迟**：~5ms（KD-tree O(log n) 查找 vs SVG DOM 遍历）
- **DOM 节点**：仅 1-2 个高亮 polygon（无隐藏 hit-test 节点）
- **rAF 节流**：`requestAnimationFrame` 确保每帧最多一次更新

> 详见 `docs/usage/terrain-pipeline.md` §15 "前端渲染性能" 章节。

---

## 6. Gaea 局部精细化（高级）

### 6.1 何时使用

大多数情况下，自动管线生成的地形已经足够好。但在以下场景中，你可能需要 Gaea 进行局部精细化：

- 需要**米级**侵蚀细节（如峡谷纹理、河流阶地）
- 需要对特定区域进行**艺术化**地形雕刻
- 需要模拟**特殊地质过程**（冰川侵蚀、风蚀地貌）

Gaea 精细化仅作用于选定区域，不会影响全球管线结果（气候、河流等保持不变）。

### 6.2 导出区域

使用 `export-region` 命令将指定经纬度范围的区域导出为独立高度图，采用立体投影（stereographic projection）以减少形变：

```bash
uv run dreamulator map export-region myworld satellite_gaiam \
    --lat 20:40 --lon -10:30 --resolution 4096 \
    -o region_heightmap.png
```

**参数说明**：

| 参数 | 说明 |
|------|------|
| `--lat MIN:MAX` | 纬度范围（南负北正） |
| `--lon MIN:MAX` | 经度范围（西负东正） |
| `--resolution N` | 输出分辨率（N×N 像素，推荐 4096） |
| `-o FILE` | 输出文件路径 |

导出的高度图包含元数据头信息，记录了投影参数和地理范围，以便后续回导。

### 6.3 Gaea 处理

在 Gaea 中处理导出的区域高度图：

1. **导入**：将 `region_heightmap.png` 导入 Gaea（Image In 节点）
2. **编辑**：使用 Gaea 节点图进行侵蚀、雕刻等操作
3. **导出**：输出为 16-bit PNG（保持与导入相同的分辨率）

> **注意**：不要改变图像分辨率或宽高比，否则回导时会出现对位偏差。

### 6.4 回导

将 Gaea 处理后的区域高度图回导到全局地图中：

```bash
uv run dreamulator map import-region myworld satellite_gaiam \
    --lat 20:40 --lon -10:30 \
    -i refined_region.png --feather 0.1
```

**参数说明**：

| 参数 | 说明 |
|------|------|
| `--feather F` | 边缘融合羽化宽度（0~1，默认 0.1 = 10% 的边界宽度） |
| `-i FILE` | 输入文件路径 |

羽化参数控制回导区域与周围地形的融合程度。0 = 硬边缘（可能出现接缝），1 = 最大融合（过渡自然但影响范围大）。推荐值 0.05~0.15。

### 6.5 限制

- 局部精细化**仅影响**选定区域的海拔数据
- 不会重新运行气候模拟或河流生成（气候和河流基于全局网格）
- 回导后，区域对应的 Voronoi cell 海拔值会同步更新
- 如果精细化后的地形与气候不一致（如在热带制造了冰川），系统不会自动修正

---

## 7. 迭代与分支

### 7.1 不同种子快速迭代

最快的迭代方式——换种子看不同结果：

```bash
# 生成多个候选
uv run dreamulator map generate myworld satellite_gaiam --seed 123
uv run dreamulator map generate myworld satellite_gaiam --seed 456
uv run dreamulator map generate myworld satellite_gaiam --seed 789
```

每次生成会完全覆盖之前的数据。如果需要在不同种子之间比较，建议将满意的结果复制到其他分支（见 [7.4 分支工作流](#74-分支工作流)）。

### 7.2 调整参数

在选定种子后，可以只修改需要调整的参数：

```bash
# 种子满意，但想增加山脉 → 增大 num_plates
uv run dreamulator map generate myworld satellite_gaiam --seed 123 --num-plates 30

# 海平面太低，想增加海洋面积
uv run dreamulator map generate myworld satellite_gaiam --seed 123 --num-plates 30 --sea-level 200
```

> **注意**：即使种子不变，修改参数也会导致不同的地形——因为管线各阶段的输入已经改变。种子只保证"相同参数 = 相同结果"。

### 7.3 手动指定板块

如果对自动生成的板块分布不满意，可以通过配置文件手动指定板块的初始位置和类型：

```yaml
# custom_plates.yaml
terrain:
  num_plates: 5
  tectonics:
    manual_plates:
      - name: "北大陆板块"
        type: continental
        center: [30, 45]    # [经度, 纬度]
      - name: "南大陆板块"
        type: continental
        center: [-60, -20]
      - name: "大洋板块A"
        type: oceanic
        center: [150, 0]
      - name: "大洋板块B"
        type: oceanic
        center: [-120, 10]
      - name: "碰撞带板块"
        type: mixed
        center: [0, 30]
```

手动指定板块时，系统会以指定位置为种子点进行区域生长，确保板块中心落在预期位置。欧拉极仍由系统自动分配（确保运动学自洽），但也可以在配置中手动覆盖。

### 7.4 分支工作流

分支系统允许你在同一世界的不同地质方案之间并行探索，而不需要反复覆盖数据：

```bash
# 创建分支（在 geological 层分叉）
uv run dreamulator branch create myworld pangea --at geological

# 在分支上生成地图（使用不同配置）
uv run dreamulator map generate myworld satellite_gaiam \
    --branch pangea -c pangea_config.yaml

# 对比查看
uv run dreamulator serve --open
# 在前端切换分支下拉菜单即可对比
```

**分支地图数据**存储在 `branches/<分支名>/layers/geological/input/maps/` 下，通过 `LayerResolver` 实现继承。未修改的层自动从基础世界继承，只有地图数据是分支独立的。

**典型分支策略**：

| 分支场景 | 分叉层 | 配置差异 |
|----------|--------|----------|
| 盘古大陆（Pangea） | geological | 少量大板块，低海平面 |
| 冰河时期 | climate | 极地温度 -40°C，低海平面 |
| 海洋世界 | geological | 高海平面，多海洋板块 |
| 火山活跃期 | geological | 多板块，高边界活动 |

---

## 8. 数据存储

### 目录结构

地图数据存储在世界的地图目录中：

```
maps/<planet_id>/
├── map.yaml          # MapMetadata（含 CVT 参数、生成时间、投影信息）
├── elevation.png     # 等距圆柱导出（16-bit，可视化 + 渲染用）
├── voronoi.json      # CVT 网格（主要数据：cell 坐标、邻居、属性）
├── plates.json       # 板块定义（名称、类型、cell 列表、欧拉极）
├── features.json     # 线性特征（河流路径、山脊线、海岸线）
├── climate.json      # 每 cell 气候数据（温度、降水、Köppen 分类）
└── registry.yaml     # 图层依赖追踪（标记哪些下游层需要重新计算）
```

分支的地图数据存储在分支目录中：

```
branches/<分支名>/
└── layers/
    └── geological/
        └── input/
            └── maps/<planet_id>/
                ├── map.yaml
                ├── elevation.png
                ├── voronoi.json
                └── ...
```

### 文件大小参考

| 文件 | 典型大小 | 说明 |
|------|----------|------|
| `map.yaml` | ~1 KB | 纯文本元数据 |
| `elevation.png` | ~2 MB | 2048×1024 16-bit PNG |
| `voronoi.json` | ~15 MB | 100K cell，含坐标和邻居列表 |
| `plates.json` | ~50 KB | 20 个板块 |
| `features.json` | ~2 MB | 河流和山脊路径 |
| `climate.json` | ~8 MB | 每 cell 3~5 个气候字段 |

### Git LFS 配置

`elevation.png` 和 `voronoi.json` 是大文件，建议通过 Git LFS 管理：

```gitattributes
# .gitattributes
maps/**/elevation.png filter=lfs diff=lfs merge=lfs -text
maps/**/voronoi.json filter=lfs diff=lfs merge=lfs -text
maps/**/climate.json filter=lfs diff=lfs merge=lfs -text
```

> **提示**：`voronoi.json` 虽然是文本格式，但体积较大（15 MB+），建议纳入 LFS。如果需要人工审查 diff，可以只将 `elevation.png` 和 `climate.json` 纳入 LFS。

---

## 9. 附录

### 参考资料

- **技术论文**: Cortial et al. 2019 *Procedural Tectonic Planets*（详见 [terrain-pipeline.md 附录 D](terrain-pipeline.md#附录-d-论文解读--cortial-et-al-2019-procedural-tectonic-planets)）
- **科普视频**: [Fractal Philosophy — *Maps: Fractals, Tectonics and the Fourth Dimension*](https://www.bilibili.com/video/BV1n2i7BrEmq)（B站中字 BV1n2i7BrEmq）— 分形几何、板块动力学与高维空间映射的可视化讲解

### 常见问题 FAQ

**Q: 生成太慢了，能加速吗？**

A: 降低 `num_nodes` 是最有效的加速手段。50,000 个节点大约需要 30 秒，适合快速迭代。确定满意的种子后，再用 100,000 节点生成最终版本。侵蚀阶段（Stage 8）也可以跳过（设置 `thermal_iterations: 0`），节省约 15 秒。

**Q: 大陆形状太圆/太规则了？**

A: 这是 CVT 网格均匀性的副产品。尝试以下方法：
- 增大 `jitter_sigma`（如 0.4~0.5），让初始点更随机
- 减少 `lloyd_iterations`（如 2~4），保留更多不规则性
- 增大 `noise_persistence`（如 0.6~0.7），让海岸线更曲折

**Q: 河流没有流入海洋？**

A: 河流算法保证水从高处流向低处并最终到达海洋或内陆洼地。如果出现"河流消失"的情况：
- 检查是否有内陆盆地（低于海平面但不与海洋连通）
- 降低 `river_flow_threshold`，让更多水流汇聚
- 这是已知问题，通常在增加 `num_nodes` 后自然消失（更密的网格 → 更精确的坡度计算）

**Q: 极地地区看起来不对？**

A: 等距圆柱投影在极地附近有严重形变（面积被拉伸）。管线在球面 CVT 网格上运行，极地 cell 的面积和邻居关系是正确的。但导出为 equirectangular PNG 后，极地在图像中会被水平拉伸。这不影响模拟精度，但影响视觉观感。未来版本计划支持 Mollweide 和 Robinson 投影。

**Q: 生成的地形太平/全是山？**

A: 调整以下参数：
- 太平 → 增大 `mountain_height`、`noise_persistence`，或增加 `num_plates`
- 全是山 → 减小 `mountain_height`，降低 `num_plates`，或增大 `sea_level_m`

**Q: 导出的高度图和编辑器里看到的不一样？**

A: 编辑器的"地形"着色模式包含山体阴影（hillshading）效果，而导出的 PNG 是纯海拔数据。如果需要带阴影的渲染图，可以在编辑器中截图，或使用 `--with-hillshade` 导出选项（即将推出）。

**Q: 分支和 CVT 网格如何配合？**

A: 每个分支可以拥有独立的地图数据。在分支上运行 `map generate` 会使用分支的参数配置生成全新地图。分支也可以只覆盖部分参数（如海平面），其余从基础世界继承。修改基础世界的地图不会影响已有分支。

**Q: `num_nodes` 设太大（> 500K）会怎样？**

A: 生成时间会显著增加（500K 节点约需 5~8 分钟），JSON 文件体积也会膨胀（~75 MB）。更重要的是，管线后续阶段（气候、河流）的计算量与 cell 数成正比。建议日常使用 100K，最终发布时用 200K~300K。

**Q: 两个种子生成的地图能混合吗？**

A: 目前没有直接混合功能。但你可以通过分支系统分别生成两个版本，然后手动将某个分支的 `voronoi.json` 复制到另一个分支。更优雅的方案是使用手动板块配置（§7.3）来精确控制板块位置，从而在一个种子下重现想要的布局。

