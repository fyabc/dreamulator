# Dreamulator

架空世界设定工具——从恒星系和物理定律出发，利用各学科知识进行严谨的世界推演。

## 项目架构

```
dreamulator/
├── docs/
│   ├── knowledge/           # 学科知识库（天体物理、地质、气候、生态、社会）
│   ├── worldbuilding/       # 架空世界创建思路与方法论
│   └── usage/               # 项目用法指南（CLI、API、前端）
├── data/
│   ├── templates/           # 世界模板（minimal, earthlike）
│   └── worlds/              # 世界实例
├── schemas/                 # JSON Schema（由 Pydantic 自动生成）
├── src/dreamulator/         # Python 后端
│   ├── models/              # Pydantic 数据模型
│   │   ├── layers.py        # 层级定义和工具函数
│   │   └── branch.py        # 分支元数据模型
│   ├── engine/              # 模拟引擎（DAG pipeline）
│   ├── io/                  # 文件读写层
│   ├── api.py               # FastAPI 应用
│   ├── api_routes/          # API 路由模块
│   ├── branch_manager.py    # 分支 CRUD 操作
│   ├── resolver.py          # 层级数据解析器
│   ├── world_manager.py     # 世界 CRUD
│   ├── cli.py               # Typer CLI 入口
│   └── utils/               # 常量、单位、RNG
├── frontend/                # TypeScript SPA（Vite + React）
│   └── src/
│       ├── api/             # API 客户端
│       ├── components/      # UI 组件
│       ├── pages/           # 页面
│       ├── stores/          # Zustand 状态管理
│       └── viewers/         # 3D/2D 可视化（Phase 3）
└── tests/                   # Python 测试
```

## 开发命令

### Python 后端（使用 uv）

```bash
# 安装依赖
uv sync --all-extras

# 运行 CLI
uv run dreamulator --help
uv run dreamulator init myworld --template earthlike
uv run dreamulator list
uv run dreamulator info myworld
uv run dreamulator validate myworld
uv run dreamulator build myworld

# 分支管理
uv run dreamulator branch create myworld pangea --at geological
uv run dreamulator branch list myworld
uv run dreamulator branch info myworld pangea
uv run dreamulator build myworld --branch pangea
uv run dreamulator branch delete myworld pangea

# 生成 JSON Schema
uv run dreamulator schema

# 启动 API 服务器
uv run dreamulator serve --reload

# 运行测试
uv run pytest

# 代码检查
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/
```

### TypeScript 前端

```bash
cd frontend

# 安装依赖
npm install

# 开发（自动代理 /api → FastAPI :8000）
npm run dev

# 构建
npm run build

# 类型检查
npx tsc --noEmit

# Lint
npm run lint
```

## 核心设计原则

### 层级架构

世界数据按学科层级组织，从最基础到最衍生：

```
physics → chemistry → stellar → orbital → geological → climate → ecology → civilization
```

每个世界使用 `layers/` 目录结构：

```
data/worlds/myworld/
├── world.yaml
├── layers/
│   ├── physics/
│   │   ├── input/          # 物理定律参数（空=标准物理）
│   │   └── derived/        # 引擎计算结果
│   ├── stellar/
│   │   ├── input/
│   │   │   └── stellar.yaml
│   │   └── derived/
│   ├── geological/
│   │   ├── input/
│   │   │   └── planets.yaml
│   │   └── derived/
│   └── ...
└── branches/
    └── pangea/             # 分支目录
        ├── branch.yaml
        └── layers/         # 仅包含分叉层及之后的层
            ├── geological/
            └── climate/
```

### 分支系统

分支类似 git branch，在某一特定层分叉，共享该层之上的所有数据：

- 在 `stellar` 层分叉 → 相同物理/化学定律下的不同恒星系
- 在 `geological` 层分叉 → 相同恒星系/轨道下的不同海陆分布
- 在 `climate` 层分叉 → 相同地质条件下的不同气候

分支仅存储分叉层及之后的数据，之前的层从父世界继承。

### 输入/衍生分离

每个层严格分离：
- **`input/`**（YAML）：人类/LLM 编写的创意设定
- **`derived/`**（JSON）：引擎计算的物理结果

LLM 只修改 input，引擎负责计算 derived——防止 LLM "幻想"物理结果。

### 可复现性

- 所有引擎使用种子化 RNG（`numpy.random.Generator`）
- 计算清单记录每步的输入/输出校验和
- 相同输入 + 种子 = 相同输出

### 引擎 DAG

```
physics → chemistry → stellar → orbital → geological → climate → ecology → civilization
```

引擎在 `src/dreamulator/engine/` 中继承 `BaseEngine`，声明 `layer`、`requires`、`input_files`、`output_files`，由 `pipeline.py` 自动拓扑排序执行。

引擎通过 `find_input()` 方法沿层级链向上搜索输入文件，支持从分支继承数据。

## 编码规范

- Python: ruff 格式化，line-length=100，strict mypy
- TypeScript: ESLint + strict mode
- 文件 I/O: **始终** 显式指定 `encoding="utf-8"`
- 数据 ID: 使用稳定字符串（如 `"star_sol"`），不用数组索引
- 物理单位: 在字段名中显式标注（`_au`, `_km`, `_kg`, `_days`）
- 使用枚举而非自由字符串（`SpectralClass.G` 而非 `"G-type"`）
- 嵌套深度不超过 4 层
