# 地图系统

dreamulator 的地图系统为每颗有固体表面的行星提供 2D 交互地图，支持地形导入、多图层查看和 Voronoi 语义管理。

> **使用指南**：完整的 Gaea 设计 → 导入 → 查看工作流见 [map-workflow.md](map-workflow.md)。

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
- 栅格编辑直观（画笔工具），WebGPU 渲染高效且兼容性好
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

### 渲染：WebGPU 地形 + SVG 叠加

> **参考**：[Paradox 游戏](https://www.paradoxinteractive.com/) 的 terrain + overlay 渲染分离；[Azgaar](https://github.com/Azgaar/Fantasy-Map-Generator) 的 SVG 图层系统

- **WebGPU**（Three.js `WebGPURenderer`）渲染地形：CPU 预渲染纹理 + GPU 显示
  - 颜色映射 + 山体阴影 + 水面效果在 CPU 端 Canvas 2D 预渲染
  - 预渲染结果作为 `CanvasTexture` 贴在 `PlaneGeometry` + `MeshBasicMaterial` 上
  - WebGPU 在 Windows 上使用 D3D12 后端，不受 ANGLE/D3D11 bug 影响
  - 若 WebGPU 不可用，自动 fallback 到 WebGL 后端
- **SVG 叠加**渲染矢量特征：Voronoi cells 交互（hover/click）在 DOM 层实现更简单
- **双层分离**：地形着色和矢量叠加独立控制，可单独开关

> **架构变更说明**（2026-06）：
> 1. 原方案使用 Three.js (R3F) + 自定义 GLSL shader。在 AMD 集显 + Windows ANGLE/D3D11
>    环境下，所有顶点属性（`uv`、`position`）在 mesh 覆盖大面积视口时无法正确插值，
>    导致纹理采样失效。
> 2. 临时回退到 Canvas 2D + CSS 定位方案，功能正常但无 GPU 加速。
> 3. 最终采用 WebGPU 方案：Three.js `WebGPURenderer` 使用 D3D12 后端，完全绕过
>    ANGLE/D3D11 bug。CPU 预渲染地形纹理，GPU 负责显示。
>    山体阴影烘焙在纹理中（固定强度 0.7），实时 hillshade 需要 GPU shader 支持。
>    实验过程记录在 `experiment/gpu-terrain-shader` 分支。

### 交互：圆柱投影平移 + 缩放

> **参考**：[EU4](https://eu4.paradoxwikis.com/Map_modding) 的无限水平滚动地图

地图使用等距圆柱投影（equirectangular），水平方向支持无缝环绕（圆柱投影特性），垂直方向限制在地图边界内。

**缩放约束**：
- 最小缩放：地图刚好填满视口（动态计算 `minZoom = max(viewW/planeW, viewH/planeH)`）
- 最大缩放：20x
- 平面尺寸使用 **cover** 策略（取较大值），保证地图始终覆盖整个视口

**平移约束**：
- 水平方向：无限制，圆柱投影无缝环绕
- 垂直方向：限制在地图边界内（`maxPanY = (planeH × zoom - viewH) / 2`）

**圆柱投影无缝环绕实现**（2026-06）：

地形层使用 **Ghost Mesh** 方案：在主 mesh 左右各放置一个相同的 mesh（偏移 ±worldW），当用户平移超出地图一侧时，ghost mesh 从另一侧进入视口，实现视觉无缝。只需 3 个 mesh（main + 2 ghosts），GPU 开销极低。

SVG 叠加层使用 **动态偏移副本** 方案：
1. 计算视口中心对应的经度，找到最近的 360° 整数倍作为中心偏移
2. 根据视口宽度 / 地图宽度确定需要多少份副本
3. 每个 Voronoi cell / 板块边界在 `centerOffset ± k × 360°` 处各渲染一份
4. 视口外的副本被 culling 过滤

**水平 pan 取模**：为支持无限水平拖动（不依赖 ghost mesh 数量），`pan.x` 在拖拽时取模到 `±planeWidth × zoom / 2` 范围内。同时用 `panWrapOffset` ref 累计记录取模偏移量，SVG 的 `project`/`unproject` 使用 `pan.x + panWrapOffset` 保持屏幕坐标连续。

**Three.js 相机坐标系**：相机位于 `(0, h, 0)` 向下看，使用默认 `up=(0,1,0)`。`lookAt` 处理退化情况（up 平行于视线）时，`_z.z += 0.0001` 微扰，导致相机坐标系为：
- screen-right = world +X
- screen-up = world -Z（**非** +Z）
- mesh 位移公式：`meshX = +(panX/w) × visibleW`，`meshZ = +(panY/h) × visibleH`

### 鸟瞰图（Minimap）

> **参考**：EU4 右下角的小地图

右侧面板底部固定显示缩略鸟瞰图，实时标注当前视口在全图中的位置。

- 使用 Canvas 2D 渲染高度图缩略图（180px 宽）
- SVG 叠加层绘制半透明白色矩形表示视口范围
- 支持水平 wrap：视口跨越反子午线时拆分为两个矩形
- MapViewer 通过 `onViewStateChange` 回调上报视口状态

### 响应式布局

- **桌面端（≥ 768px）**：三栏布局（左面板 + 地图 + 右面板）
- **移动端（< 768px）**：地图全屏，左面板变为抽屉覆盖层（☰ 按钮触发），右面板隐藏
- WebGPU 不可用时自动 fallback 到 WebGL（移动端 Safari 等）

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
| `map/terrain_generator.py` | 程序化地形生成（快速原型，推荐用 Gaea 替代） | [Red Blob Games](https://www.redblobgames.com/maps/terrain/) 地形生成方法论 |
| `map/importer.py` | 外部高度图导入（Gaea/World Machine 输出格式解码） | — |
| `map/manager.py` | 地图 CRUD + 分支继承 + 同步 | dreamulator LayerResolver |

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/worlds/{w}/maps` | 列出有地图的行星 |
| GET | `/api/worlds/{w}/maps/{p}/meta` | 地图元数据 |
| GET | `/api/worlds/{w}/maps/{p}/elevation` | 高度图 PNG |
| GET | `/api/worlds/{w}/maps/{p}/layer/{type}` | 指定图层数据 |
| GET | `/api/worlds/{w}/maps/{p}/voronoi` | Voronoi 网络 JSON |
| GET | `/api/worlds/{w}/maps/{p}/plates` | 板块分组 JSON |
| GET | `/api/worlds/{w}/maps/{p}/features` | 特征 JSON（预留） |
| POST | `/api/worlds/{w}/maps/{p}/elevation` | 上传原始高度数组 |
| POST | `/api/worlds/{w}/maps/{p}/import-elevation` | 从文件导入高度图 |
| POST | `/api/worlds/{w}/maps/{p}/voronoi` | 更新 Voronoi 网络 |
| POST | `/api/worlds/{w}/maps/{p}/plates` | 更新板块分组 |
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

- **地形渲染**：`useTerrainTexture` hook 预渲染到 OffscreenCanvas → `CanvasTexture`
  - 海拔→颜色映射（hypsometric tint，参考 GIS 标准色表）
  - 山体阴影（hillshading，CPU 计算梯度 + 模拟西北 45° 光源，固定强度 0.7）
  - 水面深度暗化
  - 由 `WebGPURenderer` + `MeshBasicMaterial` 在 GPU 上显示
  - 缩放/平移通过调整 Three.js 相机和 mesh 位置实现
- **矢量叠加**：SVG 层覆盖在地形 Canvas 上
  - Voronoi cells（圆圈 + hover 高亮，参考 Azgaar 的 cell 交互）
  - 板块边界（红色线段，跳过跨反子午线的边避免横跨全图的线）
  - 河流/山脊（polyline）
- **鸟瞰图**：`MapMinimap` 组件，Canvas 2D 缩略图 + SVG 视口矩形

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

> 完整的 Gaea → Dreamulator 工作流详见 [map-workflow.md](map-workflow.md)。

### 创建地图

有两种方式：

**方式 A：从外部工具导入（推荐）**

在 Gaea 等外部工具中设计地形，导出 16-bit TIFF，然后在地图编辑器中点击「📥 导入高度图」。

**方式 B：程序化生成（快速原型）**

进入地图编辑器 → 点击「🌍 生成地形」，后端使用多频率高斯噪声生成基础海陆分布 + Voronoi + 板块。

### 查看地图

- 左侧面板中切换着色模式（地形/海拔/海陆/坡度）
- 开关矢量叠加层（Voronoi 网格、板块边界、河流/山脊）
- 悬停 Voronoi 单元格查看属性（经纬度、海拔、板块等）

## 分支继承

地图数据支持分支系统：

- 在 `geological` 层分叉的分支可以继承或覆盖父世界的地图
- 分支的地图修改存储在 `branches/<name>/layers/geological/input/maps/` 下
- 使用 `LayerResolver` 沿继承链查找有效数据

## 后续阶段

> 完整路线图详见 [`docs/design/roadmap-analysis.md`](../design/roadmap-analysis.md)。

### 已完成（v0.5.0）

- ✅ **3D 球面地球视图** — equirectangular 纹理贴 SphereGeometry + OrbitControls
- ✅ **缩小过渡特效** — 类似《戴森球计划》的球面→恒星系过渡
- ✅ **行星纹理（路线 C）** — 恒星系中有地图的行星显示真实地形纹理
- ✅ **多投影 2D 地图** — 等距圆柱 / Mollweide / Robinson + GPU 渲染 + 经纬线网格

### 计划中

- [ ] **气候与流体引擎**（Phase 3A）— 能量平衡模型、大气环流、地形雨影、洋流
- [ ] **侵蚀与河流生成**（Phase 3B）— D8 流向、水力侵蚀、沉积物搬运
- [ ] **文明半格式化管理**（Phase 3C）— Entities+Modifiers → Event Stream → LLM 编译 Wiki
- [ ] **分支差异可视化**（Phase 3D）— DAG 影响半径、混沌预警
- [ ] **LLM 叙事引擎**（Phase 3E）— 结构化数据 → 史诗叙事
