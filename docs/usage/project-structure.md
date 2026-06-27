# 项目结构

```
dreamulator/
├── docs/
│   ├── knowledge/           # 学科知识库（天体物理、地质、气候等真实科学知识）
│   ├── worldbuilding/       # 架空世界创建思路与方法论
│   └── usage/               # 项目用法指南
├── data/
│   ├── templates/           # 世界模板（minimal, earthlike）
│   └── worlds/              # 世界实例
├── schemas/                 # 自动生成的 JSON Schema
├── src/dreamulator/         # Python 后端
│   ├── models/              # Pydantic 数据模型
│   │   ├── layers.py        # 层级定义和工具函数
│   │   ├── world.py         # 世界根模型（WorldConfig）
│   │   ├── branch.py        # 分支元数据模型
│   │   ├── stellar.py       # 恒星系模型
│   │   └── simulation.py    # 模拟种子等运行时模型
│   ├── engine/              # 模拟引擎（DAG pipeline）
│   │   ├── base.py          # BaseEngine 基类
│   │   └── pipeline.py      # 拓扑排序执行器
│   ├── io/                  # 文件读写层（YAML loader、schema 生成）
│   ├── api.py               # FastAPI 应用（同时 serve 前端静态文件）
│   ├── api_routes/          # API 路由模块
│   ├── branch_manager.py    # 分支 CRUD 操作
│   ├── resolver.py          # 层级数据解析器（分支继承链）
│   ├── world_manager.py     # 世界 CRUD
│   ├── cli.py               # Typer CLI 入口
│   └── utils/               # 物理常量、单位换算、RNG
├── frontend/                # TypeScript SPA（Vite + React）
│   └── src/
│       ├── api/             # API 客户端
│       ├── components/      # UI 组件（Layout、Sidebar）
│       ├── pages/           # 页面（HomePage、WorldInfo、WorldList、WorldDetail）
│       ├── viewers/         # 3D/2D 可视化组件（Three.js）
│       │   ├── StellarSystemViewer.tsx  # 主容器（Canvas + 场景）
│       │   ├── StarMesh.tsx             # 恒星渲染
│       │   ├── PlanetMesh.tsx           # 行星渲染
│       │   ├── OrbitLine.tsx            # 轨道路径
│       │   ├── HabitableZoneRing.tsx    # 宜居带
│       │   ├── Label.tsx                # 标注系统（dot + 引线）
│       │   ├── InfoPanel.tsx            # 天体详情面板
│       │   └── utils/                   # 黑体颜色、单位换算、轨道力学
│       └── stores/          # Zustand 状态管理
├── private/                 # 私有设计资源（logo 风格说明等）
└── tests/                   # Python 测试
```

## 各目录职责

### docs/

- **knowledge/** — 各学科的真实科学参考文档（天体物理、地质、气候、生态、社会），为模拟引擎和世界设定提供科学依据
- **worldbuilding/** — 架空世界设定的方法论和最佳实践
- **usage/** — 工具本身的使用说明（CLI、API、前端）

### data/

- **templates/** — 世界模板。创建新世界时复制模板作为起点
- **worlds/** — 世界实例。每个世界是一个独立目录，包含 `world.yaml` 和 `layers/` 子目录

### src/dreamulator/

| 模块 | 职责 |
|------|------|
| `models/` | Pydantic 数据模型，定义世界、分支、层级、恒星系等数据结构 |
| `engine/` | 模拟引擎。每个引擎继承 `BaseEngine`，声明 `requires`、`input_files`、`output_files`；`pipeline.py` 拓扑排序后按序执行 |
| `io/` | YAML 文件加载（支持分支继承链查找）和 JSON Schema 生成 |
| `api.py` | FastAPI 应用，同时 serve `frontend/dist/` 静态文件和 SPA 路由 |
| `api_routes/` | API 路由模块（worlds CRUD 等） |
| `branch_manager.py` | 分支的创建、删除、列出、提升等 CRUD 操作 |
| `resolver.py` | 层级数据解析器，沿分支继承链向上查找每个层级的实际数据来源 |
| `world_manager.py` | 世界的创建、列出、加载、删除、验证 |
| `cli.py` | Typer CLI 入口，所有 `dreamulator` 子命令在此定义 |
| `utils/` | 物理常量、单位换算、种子化随机数生成器 |

### frontend/

| 目录 | 职责 |
|------|------|
| `api/` | 与后端 REST API 通信的客户端（自动切换 API 模式 / 静态模式） |
| `components/` | 全局 UI 组件（Layout 布局、Sidebar 侧边栏、BranchSelector） |
| `pages/` | 页面组件：首页、世界信息、世界管理、世界详情 |
| `viewers/` | 3D/2D 可视化组件（Three.js 恒星系查看器，详见 `frontend-3d-viewer.md`） |
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

分支仅存储分叉层及之后的数据，之前的层从父世界继承。

### 输入/衍生分离

- **input/**（YAML）— 人类或 LLM 编写的创意设定
- **derived/**（JSON）— 引擎计算的物理结果

LLM 只修改 input，引擎负责计算 derived——防止 LLM "幻想"物理结果。

### 可复现性

- 所有引擎使用种子化 RNG（`numpy.random.Generator`）
- 计算清单记录每步的输入/输出校验和
- 相同输入 + 种子 = 相同输出

### 引擎输入模式与一致性校验

每个引擎的输入数据遵循**自变量/因变量**分类：

1. **默认自变量集**（必需）：引擎从这组变量出发推导所有因变量。例如天文学引擎默认以恒星质量为自变量，推导出光度、半径、温度。

2. **可选替代自变量集**：部分引擎允许用不同的物理量作为输入起点。例如天文学引擎也接受以光度为自变量（反演质光关系求质量），适合"先确定行星光照条件，再反推恒星参数"的世界构建工作流。

3. **手动覆盖因变量**：用户可以在 input 文件中直接填写因变量的值（覆盖引擎的计算结果）。当用户同时提供了自变量和因变量时，引擎以用户提供的因变量为准。

4. **一致性校验**：当用户同时提供了自变量和因变量（覆盖值）时，引擎会用自变量正向计算出预期值，并与用户提供的值比较：
   - 偏差 ≤ 阈值 → 静默接受
   - 偏差 > 阈值 → 发出 **warning**（默认模式）或 **error**（严格模式）

**参考实现**：天文学引擎 (`src/dreamulator/engine/astronomy.py`) 中的 `_compute_star_derived()` 函数。恒星模型 (`src/dreamulator/models/stellar.py`) 的 `Star` 类通过 `model_validator` 确保 mass/luminosity 至少提供一个。
