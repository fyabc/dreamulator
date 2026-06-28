# 地图系统

dreamulator 的地图系统为每颗有固体表面的行星提供 2D 交互地图，支持查看、编辑和多图层切换。

## 参考项目

本系统的设计参考了以下经典地图软件和游戏：

| 项目 | 类型 | 参考要素 |
|------|------|----------|
| [Azgaar's Fantasy Map Generator](https://github.com/Azgaar/Fantasy-Map-Generator) | Web 地图生成器 | Voronoi cell 架构、grid/pack 双层数据模型、SVG 渲染、4 层架构（State/Generators/Editors/Renderers） |
| [Paradox Interactive](https://www.paradoxinteractive.com/) 系列游戏（EU4, CK3, Vic3） | 大战略游戏 | 多地图模式（map modes）、高度图 + 省份着色、bitmap 省份交互、图层切换系统 |
| [Red Blob Games](https://www.redblobgames.com/x/2022-voronoi-maps-tutorial/) | 技术教程 | Voronoi 地图生成方法论、多边形网格表示 |
| [QGIS](https://qgis.org/) / [ArcGIS](https://www.arcgis.com/) | 专业 GIS 工具 | 栅格 DEM + 矢量特征提取的工作流、分层数据管理 |
| [Google Earth](https://earth.google.com/) / [NASA World Wind](https://worldwind.nasa.gov/) | 3D 地球可视化 | 等距纹理贴球体的 3D 渲染方法（Phase 2 参考） |
| [Clausewitz-style Web Map](https://github.com/SirCypkowskyy/clausewitz-style-web-map-projection) | Web 地图框架 | 双层 bitmap（visual + data）、Canvas 省份 O(1) 交互 |
| [Inkarnate](https://inkarnate.com/) / [Wonderdraft](https://www.wonderdraft.net/) | 奇幻地图编辑器 | 2D 平面编辑器 UI 设计、画笔工具交互 |

## 架构概览

地图系统采用**栅格 + Voronoi 双层混合架构**（参考 [QGIS](https://qgis.org/) 的栅格 DEM + 矢量特征模式）：

- **栅格高度图**（Raster）：2048×1024 像素的 16-bit PNG，作为核心可编辑数据和视觉渲染底图
- **Voronoi 网络**（Vector）：~5000 个 cell 的语义分组，用于板块划分、省份管理、引擎模拟计算

```
栅格高度图 (编辑 + 渲染)          ← 参考 Paradox 的 heightmap 方法
        │ 采样
Voronoi 网络 (语义分组)           ← 参考 Azgaar 的 Voronoi cell 方法
        │ 聚合
区域特征 (板块、省份、大陆)        ← 参考 Paradox 的 province/state 系统
```

**为什么选栅格而非纯 Voronoi？**
- 栅格编辑直观（画笔工具），Canvas 2D 渲染兼容性最佳
- Voronoi 语义丰富但编辑复杂，两者互补

**为什么选 Voronoi 而非纯栅格？**
- 栅格缺少拓扑信息（不知道"山脊"和"河谷"的区别）
- Voronoi cells 可分组为板块、省份，天然支持文明层和引擎模拟
- 逐 cell 计算比逐像素计算快约 400 倍（5000 cells vs 200 万像素）

## 核心设计决策

### 投影：等距圆柱投影

> **参考**：[Google Earth](https://earth.google.com/)、[NASA World Wind](https://worldwind.nasa.gov/) 的球面 UV 映射；[Azgaar](https://azgaar.github.io/Fantasy-Map-Generator/) 的 2D 编辑器

- lat/lon 直接映射到 x/y，计算简单
- 极点变形在 2D 编辑中不影响使用（大部分内容集中在中低纬度）
- 3D 球体视图（Phase 2）直接贴纹理即可，GPU 自动处理 UV 映射

### 渲染：Canvas 2D 地形 + SVG 叠加

> **参考**：[Paradox 游戏](https://www.paradoxinteractive.com/) 的 terrain + overlay 渲染分离；[Azgaar](https://github.com/Azgaar/Fantasy-Map-Generator) 的 SVG 图层系统

- **Canvas 2D** 预渲染地形（颜色映射 + 山体阴影 + 水面效果），通过 CSS 定位显示
- **SVG 叠加**渲染矢量特征：Voronoi cells 交互（hover/click）在 DOM 层实现更简单
- **双层分离**：地形着色和矢量叠加独立控制，可单独开关

> **架构变更说明**（2026-06）：原方案使用 Three.js (R3F) + 自定义 GLSL shader 渲染地形。
> 但在 AMD 集显 + Windows ANGLE/D3D11 环境下，`ShaderMaterial` 的 `uv` attribute
> 无法正确绑定到 `PlaneGeometry`（position attribute 正常），导致纹理采样失效。
> `DataTexture`、`CanvasTexture`、`RawShaderMaterial`、GLSL 1/3 均复现此问题。
> 最终改用 Canvas 2D 预渲染方案，彻底绕过 WebGL UV 绑定，在所有 GPU 上可靠工作。
> 代价：山体阴影在 CPU 上计算（2048×1024 ≈ 0.5s），非实时 GPU 渲染。
> 待 Three.js 版本升级或确认 ANGLE 驱动修复后，可考虑回迁 GPU 方案以获得实时编辑性能。

### 数据架构：input/ + derived/ 分离

> **参考**：dreamulator 自身的层级架构设计

- 地图数据遵循现有的层目录结构（`layers/geological/input/maps/`）
- 编辑数据放 `input/`，引擎计算结果放 `derived/`
- 分支继承通过 `LayerResolver` 处理

### 地图系统作为主包模块

> 地图数据深度耦合于层级系统，不适合做成独立包：

- 地图编辑需要 `LayerResolver` 处理分支继承
- 地图引擎需要接入 `BaseEngine` + `pipeline.py` 的 DAG 管线
- 数据模型共享 `Planet`、`Lithosphere`、`BiomeType`、`Settlement` 等
- 前端地图查看器需要与现有 WorldDetail 页面集成

### 独立地图页面（而非 tab）

> **参考**：[Azgaar](https://azgaar.github.io/Fantasy-Map-Generator/) 的全屏编辑器；[Inkarnate](https://inkarnate.com/) 的独立编辑器

- 地图是架空世界设计的核心元素，应给予独立编辑空间
- 全屏布局最大化地图可视区域
- 世界详情页中的预览卡片提供快速入口

## 数据位置

地图数据遵循 `input/` + `derived/` 分离原则：

```
layers/
├── geological/
│   ├── input/maps/<planet_id>/
│   │   ├── map.yaml          # 元数据
│   │   ├── elevation.png     # 高度图（git-lfs 管理）
│   │   ├── voronoi.json      # Voronoi 网络
│   │   ├── plates.json       # 板块分组
│   │   └── features.json     # 线性特征
│   └── derived/maps/<planet_id>/
│       └── terrain.png       # 地形分类
├── climate/derived/maps/...  # 气候衍生图层
├── ecology/derived/maps/...  # 生态衍生图层
└── civilization/input/maps/  # 文明层地图数据
```

> **注意**：PNG 高度图使用 git-lfs 管理（`.gitattributes` 中配置 `*.png filter=lfs`）。

## 后端模块

| 模块 | 说明 | 关键参考 |
|------|------|----------|
| `map/models.py` | Pydantic 数据模型 | — |
| `map/elevation_codec.py` | 高度图 PNG ↔ numpy 编解码 | Pillow 16-bit PNG I/O |
| `map/voronoi_generator.py` | Voronoi 网络生成 + Lloyd relaxation | [Red Blob Games](https://www.redblobgames.com/x/2022-voronoi-maps-tutorial/)、scipy.spatial.Voronoi |
| `map/terrain_generator.py` | 多频率高斯噪声地形生成 | [Red Blob Games](https://www.redblobgames.com/maps/terrain/) 地形生成方法论 |
| `map/feature_extractor.py` | 从高度图提取海岸线、河流、山脊 | QGIS DEM 分析工具 |
| `map/manager.py` | 地图 CRUD + 分支继承 + 同步 | dreamulator LayerResolver |

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/worlds/{w}/maps` | 列出有地图的行星 |
| GET | `/api/worlds/{w}/maps/{p}/meta` | 地图元数据 |
| GET | `/api/worlds/{w}/maps/{p}/elevation` | 高度图 PNG |
| GET | `/api/worlds/{w}/maps/{p}/voronoi` | Voronoi 网络 JSON |
| GET | `/api/worlds/{w}/maps/{p}/plates` | 板块分组 JSON |
| GET | `/api/worlds/{w}/maps/{p}/features` | 特征 JSON |
| POST | `/api/worlds/{w}/maps/{p}/elevation` | 上传高度图 |
| POST | `/api/worlds/{w}/maps/{p}/generate` | 程序化生成 |
| DELETE | `/api/worlds/{w}/maps/{p}` | 删除地图 |

所有端点支持 `?branch=xxx` 查询参数。

## 前端组件

### 页面结构

> **参考**：[Azgaar](https://azgaar.github.io/Fantasy-Map-Generator/) 的全屏编辑器 UI

- `/worlds/:worldName` — 世界详情页，概览 tab 中有地图预览卡片
- `/worlds/:worldName/map` — 独立全页地图编辑器
- `/worlds/:worldName/map/:planetId` — 指定行星的地图编辑器

### 渲染技术

> **参考**：[Paradox](https://www.paradoxinteractive.com/) 的 terrain rendering；[Azgaar](https://github.com/Azgaar/Fantasy-Map-Generator) 的 SVG overlay 系统

- **地形渲染**：`useTerrainCanvas` hook 预渲染到 OffscreenCanvas (Canvas 2D)
  - 海拔→颜色映射（hypsometric tint，参考 GIS 标准色表）
  - 山体阴影（hillshading，CPU 计算梯度 + 模拟西北 45° 光源）
  - 水面深度暗化
  - 通过 CSS 定位 + `transform` 实现缩放/平移
- **矢量叠加**：SVG 层覆盖在地形 Canvas 上
  - Voronoi cells（圆圈 + hover 高亮，参考 Azgaar 的 cell 交互）
  - 板块边界（红色线段，参考 Paradox 的 trade region borders）
  - 河流/山脊（polyline）

### 图层系统

> **参考**：[Paradox 游戏](https://www.paradoxinteractive.com/) 的 Map Modes 系统（EU4 有 20+ 种 map mode）

| 图层 | 来源 | 渲染方式 |
|------|------|----------|
| 地形 | elevation.png | 海拔着色 + 山体阴影 |
| 海陆 | elevation + sea_level | 二值着色 |
| 海拔 | elevation.png | 灰度梯度 |
| 坡度 | elevation 梯度 | 梯度着色 |
| Voronoi | voronoi.json | SVG circles + 属性着色 |
| 板块 | plates.json | SVG 边界线 |
| 河流/海岸 | features.json | SVG polyline |

## 使用流程

### 生成第一张地图

1. 进入世界详情页 → 点击 "生成第一张地图"
2. 或进入地图编辑器 → 点击 "🌍 生成地形"
3. 后端使用行星参数（板块数、火山活动等）生成地形 + Voronoi + 板块

### 编辑地图

1. 在地图编辑器中选择画笔工具（升起/降低/平滑/平坦）
2. 调节画笔大小和强度
3. 在地图上拖动鼠标修改地形
4. 点击 "💾 保存修改" 上传到后端

### 图层切换

- 左侧面板中切换着色模式（地形/海拔/海陆/坡度）
- 开关矢量叠加层（Voronoi 网格、板块边界、河流）
- 调节山体阴影强度

## 分支继承

地图数据支持分支系统：

- 在 `geological` 层分叉的分支可以继承或覆盖父世界的地图
- 分支的地图修改存储在 `branches/<name>/layers/geological/input/maps/` 下
- 使用 `LayerResolver` 沿继承链查找有效数据

## 后续阶段

### Phase 2：气候 & 生态图层 + 3D 球体

> **参考**：[Azgaar](https://github.com/Azgaar/Fantasy-Map-Generator) 的 climate/biome 图层；[Google Earth](https://earth.google.com/) 的 3D 球体渲染

- 气候引擎读取栅格+Voronoi → 逐 cell 计算温度/降水
- 生态引擎 → Whittaker biome 分类
- 3D 球体视图：等距纹理贴 SphereGeometry

### Phase 3：文明图层

> **参考**：[Paradox EU4/CK3](https://eu4.paradoxwikis.com/Map_modding) 的 province system

- Voronoi cell 分组为省份/国家（类似 Paradox 的 province 着色）
- 定居点放置工具（结合 cell 属性约束）
- 贸易路线（cell 间连线）
