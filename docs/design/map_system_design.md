# 地图系统架构设计文档

> **⚠️ 此文档已过时，不再维护。**  
> 最新的地图系统文档请参阅 `docs/usage/` 目录：
>
> | 文档 | 说明 |
> |------|------|
> | [`docs/usage/map-workflow.md`](../usage/map-workflow.md) | 地图工作流指南（CVT 网格 → 板块 → 地形 → 前端查看器） |
> | [`docs/usage/terrain-pipeline.md`](../usage/terrain-pipeline.md) | 行星地形生成管线技术参考（算法原理、数学公式） |
> | [`docs/usage/map-system.md`](../usage/map-system.md) | 地图子系统架构（数据模型、渲染技术、API 端点） |
> | [`docs/usage/civmap-guide.md`](../usage/civmap-guide.md) | 文明地图使用指南 |

---

## 历史设计决策（仍具参考价值）

以下 ADR 虽然细节已随代码演进，但决策逻辑仍然适用：

### ADR-001：放弃内置编辑器，保留可视化

Dreamulator 的核心价值是**推演**而非**绘画**。地图系统专注于
可视化 + 程序化生成 + 导入能力，不试图做一个内置笔刷编辑器。

### ADR-002：CVT 网格优先（替代旧 2D Voronoi）

初期使用 `scipy.spatial.Voronoi` + Ghost Points 处理等距圆柱投影的经纬线环绕。
2026-06 重写为**球面质心 Voronoi 网格**（Fibonacci 球面螺旋 + Lloyd 松弛 +
`scipy.spatial.SphericalVoronoi`），消除了极地畸变和不均匀 cell 大小问题。

详见 `docs/usage/terrain-pipeline.md` §2。

### ADR-003：CPU 预渲染 + GPU 显示

因 AMD ANGLE/D3L11 顶点属性插值 bug，所有颜色计算在 CPU 完成
（LUT 着色 + hillshading + water depth），GPU 只负责贴图显示。
详见项目根目录 `CLAUDE.md` 中的调试记录。

### ADR-004：单一真相源 + 多分辨率派生

维护一个 Master Heightmap 作为唯一可编辑版本，所有其他分辨率的地图都从它派生。

---

## 技术栈（当前）

| 层 | 技术 |
|----|------|
| 地形生成 | `scipy.spatial.SphericalVoronoi` + numpy |
| API | FastAPI + Pydantic v2 |
| 3D 渲染 | Three.js (WebGLRenderer) + React Three Fiber |
| 2D 叠加 | SVG overlay (Voronoi cell 选中高亮) |
| 地图交互 | KD-tree 命中测试 + rAF 节流 |
| 数据获取 | React Query (TanStack Query) |

---

*此文档保留作为历史参考。如需了解当前实现细节，请以上述 `docs/usage/` 中的文档为准。*
