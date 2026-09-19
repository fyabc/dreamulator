# 地图系统

dreamulator 的地图系统为每颗有固体表面的行星提供 2D/3D 交互地图，基于球面 CVT 网格，
支持外部高度图导入、多图层查看与分支继承。

> 对应源码：`src/dreamulator/map/`、`src/dreamulator/api_routes/maps.py`、
> `frontend/src/pages/MapViewerPage.tsx`、`frontend/src/pages/GlobeViewerPage.tsx`、
> `frontend/src/components/map/`、`frontend/src/viewers/map/`。
>
> **使用指南**：完整的 Gaea 设计 → 导入 → 查看工作流见 [map-workflow.md](../../usage/map-workflow.md)。

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

地图系统采用 **CVT 网格 + 派生栅格** 架构（参考 [QGIS](https://qgis.org/) 的矢量 + 栅格分工）：

- **球面 CVT 网格**（Vector，一等公民）：标准 20 万（200k）个 cell 的不规则网格，
  是地图的存储格式与模拟载体——板块划分、地形合成、气候/水文模拟全部在 cell 上完成
- **栅格图层**（Raster，派生导出）：4096×2048 像素，由 CVT 网格导出，
  作为前端渲染纹理与外部工具（Gaea 等）的交换格式

```
球面 CVT 网格 (存储 + 模拟)         ← 参考 Azgaar 的 Voronoi cell 方法
        │ 导出
栅格图层 (渲染 + 外部交换)           ← 参考 Paradox 的 heightmap 方法
        │ 聚合
区域特征 (板块、省份、大陆)          ← 参考 Paradox 的 province/state 系统
```

**为什么 CVT 网格是一等公民？**
- 栅格缺少拓扑信息（不知道"山脊"和"河谷"的区别）；CVT cells 有邻接关系，
  可分组为板块、省份，天然支持文明层和引擎模拟
- 逐 cell 计算比逐像素计算快约 40 倍（200k cells vs ~800 万像素）
- 全部模拟（构造、水文、气候）在球面网格上进行，无投影畸变

**为什么仍要栅格导出？**
- 栅格纹理渲染高效（GPU 直贴），且是与外部地形工具交换数据的通用格式
- 外部高度图（Gaea 输出）可反向导入，重采样回 CVT 网格

## 核心设计决策

### 投影：等距圆柱投影

> **参考**：[Google Earth](https://earth.google.com/)、[NASA World Wind](https://worldwind.nasa.gov/) 的球面 UV 映射；[Azgaar](https://azgaar.github.io/Fantasy-Map-Generator/) 的 2D 编辑器

- lat/lon 直接映射到 x/y，计算简单
- 极点变形在 2D 编辑中不影响使用（大部分内容集中在中低纬度）
- 3D 球体视图（Phase 2）直接贴纹理即可，GPU 自动处理 UV 映射

### 渲染：WebGPU 地形 + SVG 叠加

> **参考**：[Paradox 游戏](https://www.paradoxinteractive.com/) 的 terrain + overlay 渲染分离；
> [Azgaar](https://github.com/Azgaar/Fantasy-Map-Generator) 的 SVG 图层系统

- **WebGPU**（Three.js `WebGPURenderer`）渲染：CPU 预烘焙纹理 + GPU slot-based 合成
  - 底图/专题/填充/特征四个槽位依次合成，opacity 控制为 GPU uniform（零重烘）
  - 全分辨率 cell 贴图（~8 px/cell），NearestFilter 保持锐利边缘
  - WebGPU 在 Windows 上使用 D3D12 后端，不受 ANGLE/D3D11 bug 影响
- **SVG 叠加**渲染矢量特征（洋流箭头）：DOM 层，任意缩放清晰
- **槽位分离**：slot-based 架构确保互斥层不会同时激活

> **WebGPU 方案的技术动机**：Three.js `WebGPURenderer` 在 Windows 上使用 D3D12 后端，
> 绕过 AMD 集显 + ANGLE/D3D11 的顶点属性插值 bug（大视口 mesh 上 `uv`/`position`
> 无法正确插值，导致 WebGL 自定义 shader 纹理采样失效）。CPU 预渲染地形纹理，
> GPU 负责显示；山体阴影烘焙在纹理中（固定强度 0.7）。

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

**圆柱投影无缝环绕实现**：

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

- 地图数据存于统一顶层 `maps/<planet_id>/` 目录（旧 `layers/geological/input/maps/` 已弃用，仅作向后兼容 fallback）
- 分支地图存于 `branches/<name>/maps/<planet_id>/`，覆盖主地图
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
maps/
├── <planet_id>/
│   ├── map.yaml              # 元数据
│   ├── cvt_mesh.json         # CVT 网格（gzip 压缩）
│   ├── elevation.png         # 高度图
│   ├── plates.json           # 板块分组
│   ├── features.json         # 河流矢量图层
│   ├── temperature.png       # 气候温度图层
│   ├── precipitation.png     # 气候降水图层
│   └── koppen.json           # Köppen 分类
└── branches/<name>/maps/<planet_id>/   # 分支地图（覆盖主地图）
```

> **产物管理**：`maps/` 与 `layers/*/derived/` 是「input + 代码 + seed」的确定性构建产物，
> 不入 git、不走 LFS（`.gitignore` 已忽略）；发版由 `scripts/release/publish_world_data.py`
> 打包上传到 GitHub Releases 的 `worlds-data` tag。

## 后端模块

| 模块 | 说明 | 关键参考 |
|------|------|----------|
| `map/models.py` | Pydantic 数据模型 | — |
| `map/elevation_codec.py` | 高度图 PNG ↔ numpy 编解码 | Pillow 16-bit PNG I/O |
| `map/voronoi_generator.py` | 高度图采样（`sample_heightmap`；Voronoi 生成 + Lloyd 已迁至 `cvt_mesh.py` / `plate_generator.py`） | [Red Blob Games](https://www.redblobgames.com/x/2022-voronoi-maps-tutorial/)、scipy.spatial.Voronoi |
| `map/terrain_synthesizer.py` | 程序化地形合成（双峰基底 + 边界效应 + 热点 + fBm） | [Red Blob Games](https://www.redblobgames.com/maps/terrain/) 地形生成方法论 |
| `map/importer.py` | 外部高度图导入（Gaea/World Machine 输出格式解码） | — |
| `map/manager.py` | 地图 CRUD + 分支继承 + 同步 | dreamulator LayerResolver |

## API

地图后端路由全部在 `api_routes/maps.py`，前缀 `/api/worlds/{w}/maps/{p}`，按功能分组：
元数据与栅格图层（elevation PNG / climate-monthly）、CVT 网格（`cvt-mesh`）、矢量数据
（voronoi / plates / features）、写操作（elevation / import-elevation / generate / DELETE）。

**端点的权威参考**：`dreamulator serve` 后访问 `http://localhost:8000/docs`——FastAPI
从路由代码自动生成的 OpenAPI 交互文档，与实现 by-construction 同步（手写端点表会漂移，
不再维护）。静态模式（GitHub Pages）下无后端，API 不可用。

**OpenAPI 描述不承载、需要在此记录的约定**：

- 所有端点支持 `?branch=xxx` 查询参数指定分支（沿 `LayerResolver` 继承链解析）。
- `cvt-mesh` 的 `fmt=msgpack` 返回压缩二进制（前端透明解压，兼容纯 JSON）。
- `climate-monthly` 返回 `climate_monthly.msgpack` 原始字节（N×12 场，int16 量化）；
  **月序约定：索引 0 = 三月**（引擎年从春分起算，前端月份标签按此排列）。
- `climate-yearly` 返回 `climate_yearly.msgpack` 原始字节（N 个 per-cell UCC 连续
  描述量，float32 + uint8 状态码；字段与元数据约定见 climate-pipeline.md §11）。

## 前端组件

### 页面结构

> **参考**：[Azgaar](https://azgaar.github.io/Fantasy-Map-Generator/) 的全屏编辑器 UI

- `/worlds/:worldName` — 世界详情页，概览 tab 中有地图预览卡片
- `/worlds/:worldName/map` — 独立全页地图查看器
- `/worlds/:worldName/map/:planetId` — 指定行星的地图查看器
- `/worlds/:worldName/globe/:planetId` — 3D 球面查看器

### 渲染技术

> **参考**：[Paradox](https://www.paradoxinteractive.com/) 的 terrain rendering；[Azgaar](https://github.com/Azgaar/Fantasy-Map-Generator) 的 SVG overlay 系统

- **地形渲染**：`layerBakes.ts` CPU 预烘焙各图层纹理（全分辨率 cell 贴图）→
  `useGPUTerrain` GPU 槽位合成（底图/专题/填充/特征，opacity 为 uniform）
  - 海拔→颜色映射（hypsometric tint，参考 GIS 标准色表）
  - 山体阴影（hillshading，CPU 计算梯度 + 模拟西北 45° 光源，固定强度 0.7）
  - 水面深度暗化
  - 由 `WebGPURenderer` + `MeshBasicMaterial` 在 GPU 上显示
  - 缩放/平移通过调整 Three.js 相机和 mesh 位置实现
  - Mollweide/Robinson 的 CPU 重投影调试路径走 `useTerrainTexture`
    （OffscreenCanvas → CanvasTexture，见下节）
- **矢量叠加**：SVG 层覆盖在地形 Canvas 上
  - 经纬网（按当前投影实时绘制）
  - 单元格高亮（蓝=悬停 / 黄=选中，三投影行为一致）
  - 板块边界、地壳类型、河流等特征层烘焙进纹理（特征槽位，见「图层系统」）
- **鸟瞰图**：`MapMinimap` 组件，Canvas 2D 缩略图 + SVG 视口矩形

### 多投影渲染与调试路径

2D 地图支持三种投影：**等距圆柱**（Plate Carrée）、**Mollweide**、**Robinson**。

**渲染架构（默认全 GPU）**：

| 投影 | 渲染方式 | 实现 |
|------|----------|------|
| 等距圆柱 | GPU 纹理直贴 | `useGPUTerrain` 预渲染等距圆柱纹理 → `ShaderMaterial` 直接显示 |
| Mollweide / Robinson | GPU 逆 warp shader | `gpuReproject.ts`：片元着色器对每个像素跑投影逆变换，采样等距圆柱纹理 |

三种投影的昼夜光照、经纬网、单元格高亮均在叠加层 / shader 中计算（不烘焙进纹理）：

- **昼夜**：着色器内按太阳天顶角 `cos θz = sinφ·sinδ + cosφ·cosδ·cos(λ−λ☉)` 计算，晨昏线 smoothstep 柔化 + 夜间冷色调。
- **经纬网**：SVG 叠加层按 `project()` 实时绘制（等距圆柱为直线、Mollweide/Robinson 为平滑曲线）。
- **单元格高亮**：SVG 叠加层（蓝=悬停 / 黄=选中），三投影行为一致。

**CPU 重投影调试路径（`?reproject=cpu`）**：

URL 加 `?reproject=cpu` 可强制 Mollweide/Robinson 走旧的 **CPU 逐像素重投影**
（`useTerrainTexture`：在 OffscreenCanvas 上对每个输出像素跑投影逆变换 + 双线性采样等距圆柱源）。

- **用途**：与 GPU 逆 warp 结果做 **A/B 对照验证**——排查重投影正确性时的参照基准。
- **⚠️ 这不是"无 GPU 兜底"**：无论 GPU 还是 CPU 路径，最终都通过 WebGL 显示纹理；没有
  WebGL 的环境**整个地图都无法渲染**。CPU 路径只是把"重投影计算"挪到 CPU，显示仍依赖 GPU。
- CPU 路径明显慢于 GPU（逐像素 JS 循环），仅作调试，不作常规使用。

**相关 URL 参数**：

| 参数 | 说明 |
|------|------|
| `?reproject=cpu` | Mollweide/Robinson 强制走 CPU 重投影（调试对照，非无 GPU 兜底） |
| `?sun=<经度>` | 太阳直射经度（0–360°，周日变化） |
| `?season=<角度>` | 轨道位置（0=春分 / 90=夏至 / 180=秋分 / 270=冬至，驱动太阳赤纬） |
| `?night=1` | 开启 2D 昼夜光照叠加（默认关） |

> 光照参数（`sun`/`season`/`night`）在 2D↔3D 视图间通过 URL 同步、可分享。

#### 3D 球面渲染（GlobeViewer）

3D 视图（`/worlds/:worldName/globe/:planetId`）与 2D 共享同一套烘焙纹理，渲染管线
独立（`frontend/src/viewers/GlobeViewer.tsx` + `pages/GlobeViewerPage.tsx`，Three.js/R3F）：

- **球体**：equirectangular 纹理直接贴 `SphereGeometry`（与 2D 等距圆柱同一纹理，
  零额外烘焙）+ `OrbitControls` 交互。
- **昼夜光照**：`SunLight` 组件按太阳直射经度 + 赤纬（随季节参数变化）放置
  `directionalLight`（GlobeViewer.tsx:95-101）；昼夜模式下 `ambientLight` 降至 0.25
  （:437），晨昏线由几何自然产生。光照参数（sun/season/night）与 2D 视图经 URL 同步。
- **矢量箭头**：风/洋流箭头为独立实例（`GlobeWindArrows` / `GlobeCurrentArrows`，
  GlobeViewerPage.tsx:36-37），切空间投影用 THREE 相机矩阵解析计算（不用数值差分，
  避免与缩放耦合）；速度与方向分离归一（洋流 ~0.002 m/s 与风速 ~5 m/s 差 3 个量级）。
  偏差（deviation）箭头是独立图层实例，与常规箭头各自控制透明度。
- **月度模式**：月度风场箭头 + 月度专题层（`climate-monthly` 端点数据，
  monthlyMode 状态组，GlobeViewerPage.tsx:69-83）。
- **缩小过渡**：缩放超出阈值触发「转入星系视图」动画（`onTransition` 回调，
  GlobeViewer.tsx:15、:556-558）——类《戴森球计划》的球面→恒星系过渡。

## 图层系统（Slot-based Map Modes）

> **参考**：[Paradox](https://www.paradoxinteractive.com/) 的 map modes（EU4 20+ 模式）、
> [Azgaar FMG](https://azgaar.github.io/Fantasy-Map-Generator/) 的 Style 下拉、
> Gleba 的单选色彩叠加。

所有图层按渲染语义分四个槽位（slot），合成顺序固定为
**底图 → 专题 → 填充 → 特征**：

| 槽位 | 选择 | 语义 | 示例 |
|------|------|------|------|
| **底图** (base) | 恰好 1 个（radio） | 不透明画布 | 地形、海陆 |
| **专题着色** (thematic) | 0 或 1 个（radio） | 全表面着色，alpha 叠在底图上 | Köppen、温度、降水、气压、Whittaker 群系、NPP、宜居/农业、诊断偏差层 |
| **分类填充** (fill) | 0–N（多选叠加） | 半透明 cell 着色 | 板块 |
| **特征标注** (feature) | 0–N（多选叠加，永远置顶） | 线/箭头/高亮 | 地壳边界、洋流、风场、海岸线、河流、风/洋流偏差箭头 |

UI 按学科组织为五个面板组：**地形** / **气候** / **生态** / **文明** / **开发**
（开发组为诊断偏差层，仅开发者模式 + Earth 世界显示）。专题着色槽内选项互斥（radio）——
这与 Azgaar 的 Style 下拉和 P 社的 map mode 切换逻辑一致，
用户一次只能看到一个"地图模式"，不会出现两个全表面涂色叠加导致的视觉混乱。

## 使用流程

创建（程序化生成 / 外部高度图导入）与查看的操作步骤属于用户指南，单一事实源 =
[map-workflow.md](../../usage/map-workflow.md)。

## 分支继承

地图数据支持分支系统：

- 在 `geological` 层分叉的分支可以继承或覆盖父世界的地图
- 分支的地图数据存储在 `branches/<name>/maps/<planet_id>/` 下，覆盖主地图
- 使用 `LayerResolver` 沿继承链查找有效数据

## 已实现能力

**已实现能力**：

- **3D 球面地球视图** — equirectangular 纹理贴 SphereGeometry + OrbitControls + 昼夜光照 + 风/洋流/偏差箭头 + 月度模式 + 星系过渡（见上文"3D 球面渲染"）
- **行星纹理** — 恒星系中有地图的行星显示真实地形纹理
- **多投影 2D 地图** — 等距圆柱（GPU 纹理直贴）/ Mollweide / Robinson（GPU 逆 warp shader，`gpuReproject.ts`）+ 经纬线网格
- **昼夜光照（2D + 3D）** — 着色器内太阳天顶角计算，季节/时刻滑块驱动赤纬/经度，URL 同步
- **CPU 重投影调试路径** — `?reproject=cpu` 保留为 A/B 对照（见上文"多投影渲染与调试路径"）
- **SVG 单元格高亮 + 经纬网** — 三投影统一叠加层
- **气候图层与月度模式** — 温度/降水/气压/Köppen 专题层 + 月度切换（`climate-monthly` 端点）
- **河流矢量图层** — features.json 渲染外流河与内流河
- **偏差诊断图层** — ΔT/ΔP/ΔSLP 热力层 + 风/洋流偏差箭头（开发组，devMode + Earth）

后续方向（文明层 Phase 3C-3E、分支差异可视化等）属路线图事项，单一事实源 =
[roadmap.md](../roadmap.md)。
