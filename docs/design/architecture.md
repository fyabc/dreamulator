# 项目架构

> 项目目录结构、模块职责与核心设计概念。2026-07-29 文档整理时从 `usage/project-structure.md` 迁入
> （内容是架构设计而非使用说明）。操作类指南见 [../usage/](../usage/)，设计类文档见本目录其他文件。

---

## 目录结构

```
dreamulator/
├── docs/                        # 项目文档（详见下方"文档导航"）
│   ├── knowledge/               # 学科知识库（真实科学知识：天体物理、地质、气候等）
│   ├── worldbuilding/           # 架空世界创建方法论
│   ├── usage/                   # 用法指南（CLI、工作流、前端操作）
│   └── design/                  # 架构与设计文档（本目录）
├── data/
│   ├── templates/               # 世界模板（minimal, earthlike）
│   └── worlds/                  # 世界实例（含 branches/）
├── schemas/                     # JSON Schema（由 Pydantic 自动生成）
├── src/dreamulator/             # Python 后端
│   ├── models/                  # Pydantic 数据模型（layers、branch、stellar、world 等）
│   ├── engine/                  # 模拟引擎（DAG pipeline）
│   ├── map/                     # 地图子系统（栅格高度图 + Voronoi 语义网络）
│   ├── civmap/                  # 文明地图子系统（真实地球行政区划 + 架空领土涂色）
│   ├── guard/                   # 守护轴：校验/审计/设定维护（与生成轴 engine 正交）
│   ├── io/                      # 文件读写层（YAML loader、schema 生成）
│   ├── api.py                   # FastAPI 应用（同时 serve 前端静态文件）
│   ├── api_routes/              # API 路由模块（worlds、narrate、maps、civmap）
│   ├── branch_manager.py        # 分支 CRUD
│   ├── resolver.py              # 层级数据解析器（分支继承链）
│   ├── narrator.py              # AI 叙述后端（Claude API）
│   ├── world_manager.py         # 世界 CRUD
│   ├── cli.py                   # Typer CLI 入口
│   ├── cli_climate.py           # climate 子命令组
│   └── utils/                   # 物理常量、单位换算、种子化 RNG
├── scripts/                     # 开发/验证脚本（静态导出、气候验证、底图数据准备等）
├── frontend/                    # TypeScript SPA（Vite + React + Three.js + Leaflet）
│   └── src/
│       ├── api/                 # API 客户端（API 模式 / 静态模式双客户端）
│       ├── components/          # UI 组件（含 map/ 地图编辑器组件）
│       ├── pages/               # 页面（首页、世界详情、地图/球面/文明地图查看器、帮助）
│       ├── stores/              # Zustand 状态管理
│       └── viewers/             # 可视化器（3D 恒星系、3D 球面、2D 地图）
├── packages/
│   └── conlang/                 # 独立子包：人造语言工具（自有文档与路线图）
├── .github/workflows/           # GitHub Actions（GitHub Pages 自动部署）
├── private/                     # 私有内容（plans、chats、私有世界数据，git 排除或独立管理）
└── tests/                       # Python 测试
```

## 各目录职责

### src/dreamulator/

| 模块 | 职责 |
|------|------|
| `models/` | Pydantic 数据模型：世界（`WorldConfig`）、分支元数据、层级定义、恒星系、地图数据模型等 |
| `engine/` | 模拟引擎。每个引擎继承 `BaseEngine`，声明 `layer`、`requires`、`input_files`、`output_files`；`pipeline.py` 拓扑排序后按序执行。已实现：`astronomy`（含纯函数模块 `stellar_physics.py`，输出含 `world_parameters.yaml` 世界参数派生汇总与 `system_catalog.yaml` 天体统一目录）、`geological`（封装地形管线）、`climate`（含纯函数模块 `climate_physics.py`）；`physical_inputs.py` 统一解析卫星感知物理参数 + `derive_world_parameters()` 世界参数聚合 + `build_system_catalog()` 天体目录合并（stellar.yaml + planets.yaml，后者为共享字段权威） |
| `map/` | 地图子系统：CVT 网格生成、板块构造（Cortial 2019 时间演化）、地形合成、边界检测、地理锚定、气候模拟、栅格编解码、外部高度图导入、地图 CRUD + 分支继承。算法原理见 [geological-pipeline.md](geological-pipeline.md)，系统架构见 [map-system.md](map-system.md) |
| `civmap/` | 文明地图：真实地球国家/省份底图上的架空领土涂色与时间快照 |
| `guard/` | 守护轴：校验、审计与设定维护（与生成轴 `engine/` 正交）。含事实上下文（扩展 `doc_render`）、几何/空间查询、过期检测、拷问编排。设计见 [harness.md](harness.md) |
| `io/` | YAML 文件加载（支持分支继承链查找）和 JSON Schema 生成 |
| `api.py` / `api_routes/` | FastAPI 应用与路由（worlds、narrate、maps、civmap），同时 serve `frontend/dist/` |
| `resolver.py` | 层级数据解析器，沿分支继承链向上查找每层的实际数据来源（支持 `_inherit` 深度合并） |
| `branch_manager.py` / `world_manager.py` | 分支与世界的 CRUD |
| `narrator.py` | AI 叙述：读取结构化世界数据，经 Claude API 生成口语化描述 |
| `cli.py` / `cli_climate.py` | Typer CLI（命令参考见 [../usage/cli.md](../usage/cli.md)） |
| `utils/` | 物理常量、单位换算、种子化随机数生成器 |

### scripts/

| 脚本 | 用途 |
|------|------|
| `export_static.py` | 将世界数据导出为静态 JSON（GitHub Pages 静态模式前置步骤） |
| `validate_climate.py` | 气候验证 CLI 薄壳（实现在 `dreamulator.validate_climate`；zonal 加权 RMSE、Cohen's Kappa），见 [climate-validation.md](climate-validation.md) |
| `import_earth_elevation.py` | ETOPO1 导入 CLI 薄壳（实现在 `dreamulator.import_earth_elevation`） |
| `convert_koppen_map.py` | 转换 Beck et al. (2018) Köppen 参考数据 |
| `prepare_civmap_data.py` | 文明地图底图数据下载与预处理 |
| `generate_planet_heightmap.py` | 行星高度图生成工具（CVT 管线前的原型，见地形工作流文档） |
| `profile_build.py` | 构建性能剖析 + 基准 harness（见 [../usage/profiling.md](../usage/profiling.md)） |

### frontend/src/

| 目录 | 职责 |
|------|------|
| `api/` | REST API 客户端。`client.ts`（统一入口）、`staticClient.ts`（静态模式只读）、`civmapClient.ts`、`mode.ts`（模式检测） |
| `components/` | 全局 UI 组件 + `map/` 地图编辑器组件（图层面板、配色、帮助内容） |
| `pages/` | 页面：首页、世界信息/列表/详情、2D 地图查看器、3D 球面查看器、恒星系查看器、文明地图编辑器、帮助页 |
| `viewers/` | 可视化器：3D 恒星系（Three.js，详见 [../usage/frontend-3d-viewer.md](../usage/frontend-3d-viewer.md)）、3D 球面地球、2D 多投影地图（`viewers/map/`，GPU 地形渲染） |
| `stores/` | Zustand 全局状态管理 |

## 核心概念

### 层级架构

世界数据按学科层级组织，从最基础到最衍生：

```
physics → chemistry → astronomy → geological → climate → ecology → civilization
```

每个世界使用 `layers/` 目录结构，每个层包含 `input/`（YAML，人写的创意设定）和 `derived/`（JSON，引擎计算的物理结果）。

### 分支系统

分支类似 git branch，在某一特定层分叉，共享该层之上的所有数据：

- 在 `astronomy` 层分叉 → 相同物理/化学定律下的不同恒星系
- 在 `geological` 层分叉 → 相同恒星系/轨道下的不同海陆分布

分支仅存储分叉层及之后的数据，之前的层从父世界继承（`resolver.py` 沿继承链解析，
支持 `_inherit: true` 的增量合并）。

### 输入/衍生分离

- **input/**（YAML）— 人类或 LLM 编写的创意设定
- **derived/**（JSON）— 引擎计算的物理结果

LLM 只修改 input，引擎负责计算 derived——防止 LLM "幻想"物理结果。
这一分离在架构层面强制了因果箭头（详见 [vision.md](vision.md) 的设计哲学）。

input 下的 **Markdown 文档**（`*.md` 与 `design-notes/`）同样属于人类创作，但其中
引用物理参数处应写 **Jinja2 占位符**（如 `{{ entities.satellite_gaiam.solar_day_days | round2 }}`），
在读取时（API）与静态导出时由 `doc_render.py` 从事实上下文（`system_catalog.yaml` +
各层 summary，见 `guard/facts.py`）渲染填充；渲染产物不落盘、不进 git，模板是唯一
被跟踪的来源。详见 [worldbuilding/design_patterns.md](../worldbuilding/design_patterns.md) 模式 10。

### 可复现性

- 所有引擎使用种子化 RNG（`numpy.random.Generator`）
- 计算清单记录每步的输入/输出校验和
- 相同输入 + 种子 = 相同输出

### 守护轴（Harness）

与「生成轴」（`engine/` 推演）正交的「守护轴」（校验 / 审计 / 设定维护）——防止世界设定与
文档随演化静默漂移（silent drift / stale memory）。核心理念：**生成轴决定「能造出什么」，
守护轴决定「造出的东西能不能信任」**。两个守护对象：**引擎代码**（[audit-plan.md](audit-plan.md)
三波审计）与**世界设定**（设定维护工作流：拷问 → 补全 → 归档 → 过期检测）。设计总纲见
[harness.md](harness.md)。

- **事实上下文**：扩展 `doc_render.py` 渲染上下文至各层 `derived/*_summary.yaml`，作为
  文档模板、决策记录模板与 agent 事实库的单一来源；
- **过期检测**：三级信号——模板断链（`{{ path }}` 回显）、`ComputationManifest.input_checksum`
  指纹不匹配、渲染 diff 数值漂移；
- **决策记录台账**：`data/worlds/<world>/design-notes/`（ADR 约定）记录每条拷问的问题/结论/证据/构建指纹，
  状态 `proposed → accepted / deprecated / superseded`。

### 引擎输入模式与一致性校验

每个引擎的输入数据遵循**自变量/因变量**分类：

1. **默认自变量集**（必需）：引擎从这组变量出发推导所有因变量。例如天文学引擎默认以恒星质量为自变量，推导出光度、半径、温度。
2. **可选替代自变量集**：部分引擎允许用不同的物理量作为输入起点。例如天文学引擎也接受以光度为自变量（反演质光关系求质量）。
3. **手动覆盖因变量**：用户可以在 input 文件中直接填写因变量的值（覆盖引擎计算结果）。
4. **一致性校验**：同时提供自变量和因变量时，引擎正向计算预期值并与用户值比较——偏差 ≤ 阈值（通常 20%）静默接受，偏差 > 阈值记录 warning（严格模式下抛错）。

**参考实现**：`engine/astronomy.py` 的 `_compute_star_derived()`；`models/stellar.py` 的 `Star` 类通过 `model_validator` 确保 mass/luminosity 至少提供一个。

### 前端双模式

| 模式 | 数据来源 | 写操作 | 适用场景 |
|------|---------|--------|---------|
| **API 模式**（默认） | FastAPI 后端 | 全部可用 | 本地开发、云服务器 |
| **静态模式** | 预导出的静态 JSON | 不可用（只读） | GitHub Pages 等静态托管 |

> **静态导出同步原则**：新增 API 端点或数据字段时，必须同步更新 `scripts/export_static.py`、
> `frontend/src/api/staticClient.ts`、`frontend/src/api/client.ts` 三处，否则静态部署后功能缺失。

### 地图子系统

行星地图采用**栅格高度图 + Voronoi 语义网络**混合表示：CVT 球面网格承载语义数据
（板块、气候、生态），最终可视化时投影为 2D 栅格。设计文档：

- [geological-pipeline.md](geological-pipeline.md) — 12 阶段地形生成管线技术参考（算法原理、数学公式、论文解读）
- [map-system.md](map-system.md) — 地图系统架构（数据模型、多投影 GPU 渲染、API 端点）
- [climate-pipeline.md](climate-pipeline.md) — 气候引擎实现架构与改进路线图
- [climate-validation.md](climate-validation.md) — 真实地球数据验证方法
- [archive/map_system_design.md](archive/map_system_design.md) — 早期架构决策记录（ADR，已归档）

操作指南见 [../usage/map-workflow.md](../usage/map-workflow.md) 和 [../usage/civmap-guide.md](../usage/civmap-guide.md)。

## 文档导航

| 目录 | 读者 | 内容 |
|------|------|------|
| `docs/design/`（本目录） | 开发者 | 架构、愿景、路线图、子系统设计文档与技术参考 |
| `docs/usage/` | 用户 | CLI 参考、地图工作流、文明地图指南、前端查看器操作 |
| `docs/knowledge/` | LLM / 引擎开发者 | 各学科真实科学参考（公式、参数、学术文献） |
| `docs/worldbuilding/` | 世界创作者 | 架空世界创建方法论与设计模式 |
