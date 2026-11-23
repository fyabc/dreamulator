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
  是地图的存储格式与模拟载体。板块与地形使用原生网格；气候可以由参数化引擎计算，
  或从固定 GCM 分支读取有限面积月气候。
- **栅格图层**（Raster，派生导出）：4096×2048 像素，由 CVT 网格导出，
  作为前端渲染纹理与外部工具（Gaea 等）的交换格式

高清地形使用独立画布链。原生地质档案提供山带、岸坡、陆架及阶段表面，
连续来源按球面覆盖积分写入 TD 条件。GCM 降水保持原生父格月预算，
画布气候与水文读取对应足迹。新气候进入 TD 时，条件和共享统计场共同更新，
全部原生块重新生成。技术细节见 [地质管线](geological-pipeline.md)、
[气候管线](climate-pipeline.md) 和 [画布链](canvas-chain.md)。

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

### 渲染：WebGL 槽位合成 + SVG 叠加

> **参考**：[Paradox 游戏](https://www.paradoxinteractive.com/) 的 terrain + overlay 渲染分离；
> [Azgaar](https://github.com/Azgaar/Fantasy-Map-Generator) 的 SVG 图层系统

- **WebGL**（Three.js `WebGLRenderer`）渲染：CPU 预烘焙纹理 + GPU slot-based 合成
  - 底图/专题/填充/特征四个槽位依次合成（`WebGLRenderTarget` 全屏 quad），opacity 控制为 GPU uniform（零重烘）
  - 全分辨率 cell 贴图（~8 px/cell），NearestFilter 保持锐利边缘
- **SVG 叠加**渲染矢量特征（洋流箭头）：DOM 层，任意缩放清晰
- **槽位分离**：slot-based 架构确保互斥层不会同时激活

> **CPU 预烘焙的技术动机**：交互性能——图层切换 = uniform 更新 + 一次便宜的 GPU
> 合成 pass，零重烘；山体阴影烘焙在纹理中（固定强度 0.7）。AMD 集显 +
> ANGLE/D3D11 顶点属性插值 bug（大视口 mesh 上 `uv`/`position` 不插值，2026-06
> 记录）已于 2026-10 探针复核确认**不复现**：同一 GPU 上三种 shader 变体大视口
> checkerboard 插值全部正常。它不再是渲染方案的约束条件。

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
│   ├── cvt_mesh.msgpack.gz   # CVT 网格（gzip 帧 MessagePack；读端嗅探兼容旧 cvt_mesh.json）
│   ├── elevation.png         # 高度图
│   ├── plates.json           # 板块分组
│   ├── temperature.png       # 气候温度图层
│   ├── precipitation.png     # 气候降水图层
│   └── koppen.json           # Köppen 分类
└── branches/<name>/maps/<planet_id>/   # 分支地图（覆盖主地图）
```

> **产物管理**：`maps/` 与 `layers/*/derived/` 是「input + 代码 + seed」的确定性构建产物，
> 不入 git、不走 LFS（`.gitignore` 已忽略）；发版由 `scripts/release/publish_world_data.py`
> 打包上传到 GitHub Releases 的 `worlds-data` tag。

## 网格序列化（cvt_mesh.msgpack.gz）

盘上格式 = **gzip 帧 MessagePack**（2026-09-23 起；此前为名实不符的 gzip-JSON
`cvt_mesh.json`）。读写**一律**走 `map/export.py` 的四个函数，禁止手拼
`json.loads(gzip...)`：

| 函数 | 用途 |
|------|------|
| `save_cvt_mesh(path, mesh, *, backup_existing=False)` | 规范写：JSON 文本中间层（保 4 位小数截断 + 非有限→null 语义）→ msgpack → gzip；顺带删除同目录 legacy `cvt_mesh.json`（防双网格漂移）；传 legacy 路径时写前规范化到 canonical 名（防「写目标==清理目标」自毁）。`backup_existing=True` 覆写前轮转 1 代 `.prev`——仅 root 真实数据写入点使用（重导入昂贵、磁盘单份），引擎/分支构建保持默认关 |
| `load_cvt_mesh(path) -> dict` | 嗅探读：gzip→（JSON 文本 或 msgpack）→ dict |
| `load_cvt_mesh_model(path) -> CVTMesh` | 同上但校验为模型；legacy JSON 走 pydantic-core `validate_json` 快路径 |
| `find_mesh_file(dir)` / `iter_mesh_files(base)` | 定位网格文件（canonical 优先，legacy 回退；跳过 `_` 前缀草稿目录） |

**迁移**：零重建——旧世界的 gzip-JSON / 纯 JSON 文件由嗅探读端透明支持，
下次该层重建或引擎写回时自动转为规范格式。**服务链**：API `cvt-mesh` 端点对
规范文件字节直发（`Content-Encoding: gzip`，浏览器原生解压，后端零解析——
此前每请求 gunzip+json.loads 全量 earth ≈ 5 s CPU）；静态导出直接拷贝规范文件，
前端 `DecompressionStream` + 既有 msgpack worker 解码（不再主线程 parse 300 MB
纯 JSON）。大小与旧格式相当（gzip 是主要压缩项，容器格式影响 ±20% 内容依赖）。

## 高程语义与导入契约

地图上的高程有两种存法，单位都是米，只是存储形式不同：

- **CVT 网格**的 `cell.elevation` 直接以米保存高程，海平面由输入声明，默认是 0 m。气候与生态层按米消费，海陆以 `water_class` 为权威判据。
- **栅格** `elevation.png` 是 16 位归一化 PNG，它的米制刻度写在同目录 `map.yaml` 的 `elevation_min_m` 与
  `elevation_max_m` 里：米数 = `elevation_min_m` + v ×（`elevation_max_m` − `elevation_min_m`）。旧的 Voronoi
  网络由 `sample_heightmap` 按这条式子从栅格采样，格子上存的同样是米。

外部高度图的导入以 `ElevationMapping` 为契约，由 `import_heightmap_metres` 执行。解码出的值 v 是图像满刻度的比例
（8 位图为灰度级除以 255，16 位图除以 65535），映射有三种模式：

| 模式 | 用于 | 米数与海陆 |
|------|------|-----------|
| `range` | 带水深的高度图，包括本库自己导出的 `elevation.png` | 米数 = `min_m` + v ×（`max_m` − `min_m`），高于 `sea_level_m` 为陆地；本库导出的图按它的 `map.yaml` 刻度导回，误差不超过一个 16 位台阶 |
| `threshold` | 只画了陆地的灰度图 | v 不超过 `sea_level` 为海；陆地从阈值处的 0 m 沿传递曲线升到满刻度的 `max_m`，曲线缺省线性，可选 `gamma`；图里没有水深，所有海格取声明的 `seafloor_m`，结果标记为海底是假设值 |
| `metres` | 值本身就是米的浮点 TIFF | 原样读入，高于 `sea_level_m` 为陆地 |

海陆在源图像素上判定。需要缩小预览等显示数据时，海陆掩膜按面积重采样，覆盖过半为陆地的输出格判为陆地；高程按类加权平均，陆格只平均
陆地样本，海格只平均海洋样本。两者都用正滤波（缩小用盒式，放大用双线性），所以海岸不会被另一侧的值拖偏，也不会因振铃
翻转。导入结果同时给出陆地占比、一级灰度对应的高度（海岸处与最大值）和海底是否为假设值，并提醒作者注意 8 位图的精度。
解码出的源值范围还会生成一组机器可读的诊断（`diagnostics`，代码如 `range_all_sea`、`range_grey_use`、
`range_darkest_share`、`threshold_reach` 和 `metres_all_land`）：它们说明当前映射在这张图上全成了海或陆地、
源图只用了一部分灰度，或最深一级灰度占了多大面积，并附上作者可以照着填的建议数字，例如让最亮像素达到声明纯白高度的
纯白高程、或适合的海平面阈值。诊断只陈述计算事实与可选调整，不修改映射，也不猜作者意图。
`import-elevation` 端点按这份契约导入，不给映射参数时取 `range` 模式和地图现有的刻度。它按输入尺寸写成米制高程对应的 16 位栅格，并更新 `map.yaml` 的刻度与 `elevation_import` 溯源记录。正式计算网格由地质构建更新。
映射参数与浮点图像必须为有限值，缺失像素须先由作者补齐再导入。灰度步长由线性或幂曲线的端点直接计算，
内存开销不随位深增长，因此 32 位整数 TIFF 也能返回精度报告。

全球高度图必须使用等距圆柱投影，宽度恰好是高度的两倍；源图最多为 4096 × 2048 像素，文件不得超过 64 MiB。
参考 [web-exoplasim 的导入规格](https://github.com/ryoung48/web-exoplasim/blob/main/docs/climate/custom-terrain.md)，
两个端点均在解码像素前检查文件大小与图像尺寸。此限制针对全球上传，不影响地理锚定栅格、命令行区域数据包或已有高程输入的重建。

导入前的只读预览由 `POST /api/elevation-preview`（`preview_elevation_import`）提供。它与 `import-elevation` 走同一套解码、
和映射，不写任何文件。请求给出 `world` 与 `planet_id` 时，接口先校验导入目标。不给映射参数时沿用地图现有刻度；若没有目标，则使用契约默认值。两种情况均以原图尺寸作为导入输出。返回内容是与导入相同的报告（含 `diagnostics`），另加
`mapping_source`（映射来自请求、地图还是契约默认）和一张宽度不超过 720 像素的显示网格：米制高程按小端 float32、海陆
按 uint8 存放，两者都以 base64 编码，由 `preview_grid` 用导入时的按类重采样缩小。显示网格只供界面绘制海岸与读数，统计量
按完整输出栅格计算。两个接口都返回 `land_area_fraction`，即按每行球面面积加权的陆地占比（`land_area_fraction`
函数）；`land_fraction` 仍是等距圆柱像素的比例，两者在高纬陆地多时差别明显。PNG 超过 Pillow 的像素上限
（缺省约 1.79 亿像素）时，解码在读像素前就拒绝，接口返回说明像素数与上限的输入错误。

### 导入输入与构建接线

API 导入把原图按 SHA-256 内容哈希保存在地质层 `input/elevation_sources/`，
`input/elevation_imports.yaml` 按行星编号记录哈希、映射、目标尺寸与溯源。原图是作者输入，
地图栅格与网格是可重新生成的产物。分支在自己的地质输入中保存覆盖，未覆盖文件按继承链读取。
参照世界的 root 不接受导入，继承地质层的气候分支也不能覆盖地形。

地图视图把高程栅格和 CVT 模拟网格分别读取。对于导入世界，地形、海陆和海岸线默认从 `elevation.png` 绘制，网格字段仍从 CVT 读取。放大高程图不会增加气候图层的纹理尺寸或计算分辨率。静态导出沿用同一份 `elevation.png` 和 `elevation_import` 元数据，区域网页按像素中心投影裁切导入高程。

地质引擎优先读取该行星的导入声明，校验原图哈希，再生成带邻接关系与面积的 CVT 网格。
它复用 `generate_cvt_mesh` 与标准行星参数解析，半径来自该行星的正典输入。
高程与海陆从同一个等距圆柱像素采样，避免在海岸混合两类高度；这是包含像素采样，
不是对每个球面格子的面积求积。网格海陆面积与栅格像素比例因此属于不同口径。

导入像素声明的所有非陆地格都作为水域，本入口尚不区分内陆湖与开阔海洋，也不推测板块构造史。
构建写出空板块表，移除会遮蔽新 CVT 网格的旧 Voronoi 表。海平面同步到地图元数据与气候配置，
气候读取网格的 `water_class`，不会把海底高度当作大气下边界。

导入声明与原图纳入地质构建的过期判定，重新导入后下游会重算。删除地图后可以从输入重建；
原图缺失、哈希不匹配或声明无效时明确失败，不以已有旧网格掩盖输入问题。
外部安装的地球和太阳系参照网格仍使用 `elevation_source: imported` 的专用保护路径。
普通上传无需手改这个全局开关，导入声明按行星生效。

操作与验收见[地图工作流](../../usage/map-workflow.md#71-后端导入链验收)，
前端旅程由[前端入口提案](../proposals/frontend-entry.md)维护。
陆地偏置图和 `import_heightmap` 的归一化结果是概率场，不属于高程契约。

## 后端模块

| 模块 | 说明 | 关键参考 |
|------|------|----------|
| `map/models.py` | Pydantic 数据模型 | — |
| `map/elevation_codec.py` | 高度图 PNG ↔ numpy 编解码 | Pillow 16-bit PNG I/O |
| `map/voronoi_generator.py` | 高度图采样（`sample_heightmap`；Voronoi 生成 + Lloyd 已迁至 `cvt_mesh.py` / `plate_generator.py`） | [Red Blob Games](https://www.redblobgames.com/x/2022-voronoi-maps-tutorial/)、scipy.spatial.Voronoi |
| `map/terrain_synthesizer.py` | 程序化地形合成（双峰基底 + 边界效应 + 热点 + fBm） | [Red Blob Games](https://www.redblobgames.com/maps/terrain/) 地形生成方法论 |
| `map/elevation_input.py` | 原图保留、导入声明与构建网格采样 | SHA-256 内容寻址与分支继承 |
| `map/importer.py` | 外部高度图导入：格式解码，以及按 `ElevationMapping` 转成米的导入契约（见上节） | — |
| `map/manager.py` | 地图 CRUD + 分支继承 + 同步 | dreamulator LayerResolver |

## API

地图后端路由全部在 `api_routes/maps.py`，前缀 `/api/worlds/{w}/maps/{p}`，按功能分组：
元数据与栅格图层（elevation PNG / climate-monthly）、CVT 网格（`cvt-mesh`）、矢量数据
（voronoi / plates）、写操作（elevation / import-elevation / generate / DELETE）。导入预览不属于某个已有世界，
路由为 `/api/elevation-preview`，同样只在 API 模式提供。

**端点的权威参考**：`dreamulator serve` 后访问 `http://localhost:8000/docs`——FastAPI
从路由代码自动生成的 OpenAPI 交互文档，与实现 by-construction 同步（手写端点表会漂移，
不再维护）。静态模式（GitHub Pages）下无后端，API 不可用。

**OpenAPI 描述不承载、需要在此记录的约定**：

- 所有端点支持 `?branch=xxx` 查询参数指定分支（沿 `LayerResolver` 继承链解析）。
- `cvt-mesh` 的 `fmt=msgpack`：规范文件字节直发并附 `Content-Encoding: gzip`
  （浏览器透明解压，后端零解析）；legacy gzip-JSON 文件则解码后重打包为
  msgpack（纯 JSON 文本从不上 msgpack 线格式）。
- `climate-monthly` 返回 `climate_monthly.msgpack` 原始字节（N×12 场，int16 量化）；
  **月序约定：索引 0 = 三月**（引擎年从春分起算，前端月份标签按此排列）。
- `climate-yearly` 返回 `climate_yearly.msgpack` 原始字节（N 个 per-cell UCC 连续
  描述量，float32 + uint8 状态码；字段与元数据约定见 climate-pipeline.md §11）。

### 地图结果元数据与静态一致性

API 的 `meta` 端点与静态站的 `meta.json` 共用
`src/dreamulator/map/models.py` 中的 `map_metadata_result`。
该函数用 `MapMetadata` 校验已知字段并补齐默认值，同时保留地图 YAML 中额外的生成来源字段。
日期统一输出为 JSON 字符串，非有限数值统一输出为 `null`。
`MapManager` 的模型读取入口继续服务内部计算，`get_map_metadata_result` 专门提供传输结果。

公共元数据由 `src/dreamulator/result_contract.py` 定义。当前格式版本为字符串 `"3"`，
参考年为 365.25 天，参考月为参考年的十二分之一。这些声明在传输时覆盖地图 YAML 中的同名字段，
不改变输入文件。前端的 API 与静态客户端共用 `MapResultMetadata` 类型读取元数据。

月度和年度气候文件均原样传输，文件内部的格式版本、数据来源、缺值状态及时间口径保持原样。
公共元数据描述参考单位；具体年度文件的总量仍须按自身的 `p_total_basis` 解读，
当地窗口总量与参考年总量的区别见[气候管线](climate-pipeline.md#11-图层导出与输出格式)。
静态地图导出跳过名称以 `_` 或 `.` 开头的内部目录，避免将诊断快照作为行星发布。
API 和静态导出共用 `MapManager.list_planets_with_maps` 的完整行星列表。列表先列出分支有地图产品的行星，
再按名称列出从父世界继承的其余行星，同一行星只出现一次。只有气候产品的分支目录也能参加列表；
空目录和只有诊断笔记的目录不会参加列表。静态导出为所有继承行星写出 `maps.json`，
但分支目录只保留与根世界不同的文件：逐字节相同的副本会被省略并记入该分支的
`maps/shared.json`，静态客户端读到清单后直接读取根世界的同名文件，因此不会产生 404 请求。
浏览器气候试算从分支目录直接读取网格，所以合并后的 `cvt_mesh.msgpack.gz`、观测 Köppen 栅格
和 `climate_trial.json` 始终保留在分支目录。分支目录因此只携带真正的差异，
静态站点的发布体积保持在 GitHub Pages 的 1 GB 上限以内。

`tests/test_result_transport.py` 用真实高程 PNG、月度文件和引擎生成的年度 UCC 文件验证传输。
测试覆盖根世界、分支继承和年度覆写，要求 API 与静态元数据完全相等、三个数据文件逐字节相等，
并检查缓存响应、年度总量、海洋的不适用状态和冻结陆地的缺值状态。

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
- **矢量叠加**：SVG 层覆盖在地形 Canvas 上
  - 经纬网（等距圆柱直线网格实时绘制）
  - 单元格高亮（蓝=悬停 / 黄=选中）
  - 板块边界、地壳类型等特征层烘焙进纹理（特征槽位，见「图层系统」）
- **鸟瞰图**：`MapMinimap` 组件，Canvas 2D 缩略图 + SVG 视口矩形

### 2D 渲染与昼夜光照

2D 地图使用**等距圆柱**（Plate Carrée）单一投影，与引擎栅格数据同构（GPU 纹理直贴，
`useGPUTerrain` 预渲染 → `ShaderMaterial` 显示）。极区形状/面积的真实比例用 3D 球面
视图查看；其他投影的静态出图走导出侧。

昼夜光照、经纬网、单元格高亮均在叠加层 / shader 中计算（不烘焙进纹理）：

- **昼夜**：着色器内按太阳天顶角 `cos θz = sinφ·sinδ + cosφ·cosδ·cos(λ−λ☉)` 计算，晨昏线 smoothstep 柔化 + 夜间冷色调。
- **经纬网**：SVG 叠加层按 `project()` 实时绘制（直线网格）。
- **单元格高亮**：SVG 叠加层（蓝=悬停 / 黄=选中）。

**相关 URL 参数**：

| `?sun=<经度>` | 太阳直射经度（0–360°，周日变化） |
| `?season=<角度>` | 轨道位置（0=春分 / 90=夏至 / 180=秋分 / 270=冬至，驱动太阳赤纬） |
| `?night=1` | 开启 2D 昼夜光照叠加（默认关） |
| `?clean=1` | 纯净视图：隐藏全部 UI 与场景装饰（面板/状态栏/经纬网/极轴），只留地图或球体画面，视频录制用。Esc 或右上角悬停按钮退出；2D/3D 通用 |
| `?spin=1` | 自动旋转（仅 3D）：慢速匀速自转（~120 s/圈），视频录制用。拖拽或 N 键北极飞行期间自动暂停、松手恢复；与 `?clean=1` 组合为标准录制姿态 |
| `?monthly=1&month=<索引>` | 显示所选月份的数据。窗口索引从 0 开始，与光照参数独立。 |
| `?detail=downscaled` | 对支持降尺度的主图层显示插值结果。 |
| `?layer=<id>` | 主图层深链（如 `terrain` / `temperature` / `precipitation` / `koppen`）：打开时该图层按默认不透明度点亮，槽位语义与面板点击一致（仅同槽互斥，地形底默认保留）。切换主图层时回写 `?layer=`（replace，不进历史）；默认地形底不写，保持 URL 干净 |

> 光照参数（`sun`/`season`/`night`）在 2D↔3D 视图间通过 URL 同步、可分享。

降尺度将连续球面网格场重采样到规则经纬网，再对数值做双线性插值，最后应用图层色标。经度在反经线处循环，缺失角点不参加插值。原单元缺值或不在图层适用范围时，像素仍然留空。导入细地形时，温度可根据当地高程与降水所决定的直减率修正；没有降水依据时只插值。降水、气压、气候偏差、净初级生产力、农业评分和宜居评分只插值已有值，不重新计算物理过程或评分。陆地限定字段不绘制到海上，气压保留不可靠单元的掩膜。

柯本图层需要同一张地图的完整逐月温度和降水才能降尺度。浏览器在后台线程插值逐月数值，再重判陆地类别和海域温度分带。季节由最暖和最冷的各六个月确定，年降水由参照月累积量相加，不按行星公转周期另行缩放。类别颜色不参与插值。缺少整年配对数据时保留模式网格。其他离散分类和板块边界保持原样，风和洋流继续按专用矢量方式绘制。地形、海陆和海岸线可直接使用细高程栅格，不对类别做平滑。降尺度地图纹理最多为 2048 × 1024，求解、单元格读数和统计继续使用原始数据。

平面和球面把当前连续主图层的色阶浮放在地图左上角。色阶与地图着色使用相同的范围，悬停或聚焦可读时间口径和色标说明；更换图层不会改变地图视口尺寸。正式和试算模式共用此规则。

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
- **粒子流**：图层面板顶部开关把风/洋流从箭头切换为平流粒子（`FlowParticles`）。
  `flowField.ts` 把逐细胞矢量按面积加权聚合成 2° 经纬网格，粒子用 RK2 在球面
  前向积分（m/s→°/s 以行星半径换算；洋流比风慢约三个量级，用更大的显示倍率）。
  3D 通过 `GlobeViewer` 的免分配点投影器（`PointProjector`，随相机矩阵递增 epoch）
  画到覆盖球面的 2D 画布；2D 通过 `MapViewer` 的等距投影画到地图容器。拖尾是
  屏幕空间轨迹：视图变化时清空旧拖尾，同时用上一帧经纬位置在新视角下补一条
  至少约 5 像素的短轨迹，静止后重新积累长拖尾。洋流粒子在平流前后各查一次
  `useCellIdMap` 的逐像素最近细胞（`sampleCellId`），若落在 `water_class === "land"`
  的细胞上则立即消亡重生；2° 流场网格只负责矢量平滑，不承担陆地掩膜。风场月度数据来自
  `climate_monthly.msgpack` 的 `wind_east_monthly` / `wind_north_monthly`；
  洋流当前只有年均场。
- **月度模式**：月度风场（箭头或粒子）+ 月度专题层（`climate-monthly` 端点数据，
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
| **特征标注** (feature) | 0–N（多选叠加，永远置顶） | 线/箭头/高亮 | 地壳边界、洋流、风场、海岸线、风/洋流偏差箭头 |

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
- **2D 等距圆柱地图** — GPU 纹理直贴（`useGPUTerrain`）+ 经纬线网格
- **昼夜光照（2D + 3D）** — 着色器内太阳天顶角计算，季节/时刻滑块驱动赤纬/经度，URL 同步
- **SVG 单元格高亮 + 经纬网** — 统一 SVG 叠加层
- **气候图层与月度模式** — 温度/降水/气压/Köppen 专题层 + 月度切换（`climate-monthly` 端点）
- **湖泊着色** — 地形底图与海陆底图按 mesh 的 `is_lake` 把湖泊 cell 着为水面色（冰冻湖为浅冰色）；全球网格不提供河流图层，渲染用河流来自高分辨率画布链（见 [canvas-chain.md](canvas-chain.md)）
- **偏差诊断图层** — ΔT/ΔP/ΔSLP 热力层 + 风/洋流偏差箭头（开发组，devMode + Earth）

后续方向（文明层 Phase 3C-3E、分支差异可视化等）属路线图事项，单一事实源 =
[roadmap.md](../roadmap.md)。
