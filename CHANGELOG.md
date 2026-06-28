# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

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

[0.2.0]: https://github.com/user/dreamulator/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/user/dreamulator/releases/tag/v0.1.0
