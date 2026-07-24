# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.6.0] — 2026-07-24

### Added

**3D 球面 — 多边形高亮与图层叠加**
- Voronoi cell 多边形高亮（蓝色悬停 + 黄色选中），渲染真实球面多边形边界
- 四层独立透明度滑块（地形/海陆/板块/边界），任意组合叠加
- 海岸线自动检测：海陆异号像素边缘绘制黑线
- 球面经纬线网格 + 极轴（北红/南蓝 + N/S 文字）

**配色升级**
- LUT 精度 256→1024 级，色彩渐变更平滑
- 浅海色调修正：消除沙滩过渡区的黄色偏色

### Fixed

- 修复 3D 球面纹理映射（行列反转匹配 SphereGeometry UV）
- 修复 CVTVertex/CVTRegion 类型与实际数据格式不一致
- 修复 cli terrain generate 日志丢失 rich 彩色输出
- 修复桌面端移动端响应式布局（3D 球面对齐 2D 地图）
- 统一 2D/3D 单元格选择逻辑（Ctrl+双击复选）

## [0.5.0] — 2026-07-24

### Added

**3D 球面地球视图**
- 全新 3D 球面地形可视化：equirectangular 纹理贴 SphereGeometry
- R3F Canvas + OrbitControls（旋转/缩放/倾斜）+ 星空背景 + 大气辉光壳
- 缩小过渡特效（Dyson Sphere Program 风格）：持续缩小出现 "转入星系视图" 进度条，满条自动跳转
- 进入恒星系视图时自动聚焦来源行星（?focus= 参数）

**恒星系行星纹理（路线 C）**
- 恒星系 3D 视图中有地图的行星自动加载真实地形纹理
- ETOPO1 + ESRI 混合配色，256×128 DataTexture 贴球体

**3D 视图独立路由**
- 3D 恒星系视图从 WorldDetail tab 抽离为侧边栏一级入口
- 新增 `/worlds/:worldName/viewer3d` 路由

### Fixed

- CI: package-lock.json 镜像源兼容 + vitest 降级（vite 5 兼容）

## [0.4.0] — 2026-07-23

### Added

**地图查看器 — 3D 恒星系 + 星球纹理**
- 3D 恒星系视图从世界详情页抽离为独立页面 + 侧边栏一级入口
- 恒星系中有地图的行星自动显示真实地形纹理（ETOPO1+ESRI 混合配色）
- 多投影支持：等距圆柱 / Mollweide / Robinson，含经纬线网格
- GPU 地形渲染：CPU 预计算纹理 + ShaderMaterial 直出

**地图查看器 — 交互增强**
- 双击选中单元格（替代单击），避免拖拽误触
- KD-tree 球面最近邻命中测试 (O(log n))
- Cell-ID 贴图预计算 + 调色板查找，图层切换 10-20× 提速
- URL 持久化分支参数 (?branch=)

**地图查看器 — 坐标系统重构**
- mapCenter (lon/lat) + zoom 统一坐标模型，替代 pan/panWrapOffset
- 24 个单元测试覆盖核心坐标转换函数

**配色 & 视觉**
- 海洋 NOAA ETOPO1 + 陆地 ESRI Natural Earth 混合 hypsometric tint
- 海陆图层动态二值 LUT（基于真实 sea_level_m）
- 输出色彩空间统一（LinearSRGBColorSpace），消除非等距圆柱投影偏浅
- 地壳类型/边界类型中文化标签

**3D 恒星系可视化**
- 3D 视图独立路由 `/worlds/:worldName/viewer3d`
- 现有 `feat/terrain-sphere-view` 分支为后续 3D 球面地球视图准备

### Changed

- 地图设计文档精简，重定向到 `docs/usage/` 现行文档
- 旧 2D Voronoi 管线保留为 fallback，主路径切换为 CVT 球面网格

## [0.3.0] — 2026-07-14

### Added

**文明地图（CivMap）系统**
- 基于真实地球行政区划的文明层地图涂色
- Leaflet 嵌入式地图组件 + GeoJSON 渲染
- 国家面积（km²）显示、省份计数
- 分支感知的文明数据查询
- GeoJSON 底图数据通过 Git LFS 存储

**文明层文档系统**
- Markdown 文档查看器（remark-gfm 表格渲染）
- 自动链接反引号引用的 .md 文件
- ERE-if 架空历史分支（东罗马文明 IF）

**前端交互增强**
- 分支选择与活动标签页持久化到 URL search params
- WorldDetail、CivMapEditor、CivilizationDocuments 响应式移动端布局

### Changed

- l4-companion 分支迁移至 Markdown 格式，移除 civilization YAML 渲染
- CLAUDE.md 新增静态导出同步规则和 React Hooks 规则文档

### Fixed

- CivMapPreview hooks 规则违反导致页面崩溃
- 静态模式下文明数据解包错误
- 文明文档加入静态导出 + 条件 CivMapPreview 渲染
- 静态 civmap GeoJSON 导出优化与错误处理
- 移动端导航抽屉背景透明问题
- 分支 404 错误消除

## [0.2.0] — 2026-06-29

### Added

**地图系统（栅格 + Voronoi 双层架构）**
- 栅格高度图（2048×1024）+ Voronoi 语义网络（~5000 cells）
- 地图编辑器全页布局（左面板图层控制 + 中央地图视图 + 右面板单元格详情）
- WebGPU 地形渲染（Three.js `WebGPURenderer`），CPU 预渲染 CanvasTexture
- WebGL 自动 fallback（移动端 / 不支持 WebGPU 的浏览器）
- 圆柱投影无限水平环绕：ghost mesh 地形无缝拼接 + SVG 动态偏移副本
- pan.x 取模 + panWrapOffset 实现无限拖动无边界
- 鸟瞰图（Minimap）：缩略全图 + 视口矩形标注，支持 wrap 拆分
- 板块边界渲染（跳过跨反子午线伪线段，dlat > 20° 过滤）
- Voronoi cells 交互（hover 高亮 + click 选择 + 属性面板）
- 4 种着色模式：地形 / 海拔 / 海陆 / 坡度
- 移动端响应式布局：地图全屏 + 抽屉式左面板
- 程序化地形生成 API（大陆数、山脉度、板块数）
- 静态模式支持（GitHub Pages 只读部署）

**3D 恒星系可视化**
- Three.js + @react-three/fiber 渲染
- 恒星、行星、卫星轨道动画
- 天体信息面板 + 描述叙述
- 分支感知的 3D 视图查询

**conlang 人造语言工具（workspace 子包）**
- IPA → ASCII-IPA / X-SAMPA / Kirshenbaum 音素转换
- eSpeak-NG TTS 语音合成（`speak` 命令）
- 独立 CLI 子命令

**AI 叙述（narrator）**
- Claude API 集成，支持流式输出
- Token 用量追踪 + max-tokens 参数
- 分支感知叙述（`narrate --branch`）

**分支系统增强**
- `_inherit: true` 分支数据合并
- 分支选择器集成到世界详情页和地图编辑器
- 分支感知的 API 查询

### Changed

- 路线图重排：前端可视化提升为 Phase 2（已完成），模拟引擎移至 Phase 3
- 主页重设计为快速入口卡片 + 世界列表
- `solar_system` 重命名为 `earth`
- 默认 max-tokens 从 4096 提升至 32768

### Fixed

- 拖拽方向修正（Three.js 俯视相机退化坐标系：screen-right=+X, screen-up=-Z）
- 缩放约束：最小缩放 = 地图填满视口（cover 策略），最大 20x
- 移动端 WebGPU 不可用时的 WebGL fallback
- 地图边缘拖动跳跃（dragStart 统一使用容器相对坐标）
- Git LFS 在 CI 中的兼容性处理
- 3D 查看器多项渲染 bug

### Technical Notes

- 相机坐标系：`position=(0,h,0)` + `lookAt(0,0,0)` + `up=(0,1,0)` 触发 Three.js 退化处理，实际相机轴为 right=(1,0,0), up=(0,0,-1)
- AMD ANGLE/D3D11 顶点属性插值 bug 导致自定义 GLSL shader 在大视口下失败，改用 Canvas 2D 预渲染 + MeshBasicMaterial（详见 `.claude/notes/threejs-camera-pan-debug.md`）
- 地图平面尺寸使用 cover 策略（`max()`），保证地图始终覆盖视口

## [0.1.0] — 2026-05-30

### Added

- 项目骨架：Python 后端（uv + hatchling）+ TypeScript 前端（Vite + React）
- 数据模型：Pydantic 层级架构（physics → chemistry → astronomy → geological → climate → ecology → civilization）
- CLI 工具：init / list / info / validate / build / branch / schema / serve
- 世界管理：CRUD + 分支系统（层分叉 + 继承）
- 前端骨架：世界列表 + 详情页 + Tab 导航
- 天文学引擎：恒星物理（质量/光度/温度/寿命）+ 轨道力学
- FastAPI 服务 + Vite 代理开发模式
- GitHub Pages 静态站点部署
- 学科知识库文档框架

[0.3.0]: https://github.com/user/dreamulator/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/user/dreamulator/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/user/dreamulator/releases/tag/v0.1.0
