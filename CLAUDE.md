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
│   ├── map/                 # 地图子系统（栅格高度图 + Voronoi 语义网络）
│   │   ├── models.py        # 地图数据模型（MapMetadata, VoronoiCell, TectonicPlate）
│   │   ├── elevation_codec.py  # 高度图 PNG ↔ numpy 编解码
│   │   ├── voronoi_generator.py # Voronoi 网络生成 + Lloyd relaxation
│   │   ├── terrain_generator.py # 程序化地形生成（多频率高斯噪声）
│   │   ├── feature_extractor.py # 特征提取（海岸线、河流、山脊）
│   │   └── manager.py       # 地图 CRUD + 分支继承 + 同步
│   ├── civmap/              # 文明地图子系统（真实地球行政区划 + 架空领土涂色）
│   │   ├── models.py        # 数据模型（CivCountry, CivSnapshot, CivTerritory）
│   │   └── manager.py       # CRUD + 分支继承 + 国家/省份映射
│   ├── io/                  # 文件读写层
│   ├── api.py               # FastAPI 应用
│   ├── api_routes/          # API 路由模块（worlds、narrate、maps、civmap）
│   ├── branch_manager.py    # 分支 CRUD 操作
│   ├── resolver.py          # 层级数据解析器
│   ├── narrator.py          # AI 叙述后端（Claude API）
│   ├── world_manager.py     # 世界 CRUD
│   ├── cli.py               # Typer CLI 入口
│   └── utils/               # 常量、单位、RNG
├── frontend/                # TypeScript SPA（Vite + React）
│   └── src/
│       ├── api/             # API 客户端
│       ├── components/      # UI 组件（含 map/ 地图编辑器组件）
│       ├── pages/           # 页面（含 MapEditorPage 全页地图编辑器）
│       ├── stores/          # Zustand 状态管理
│       └── viewers/         # 3D 恒星系 + 2D 地图可视化器（Three.js / WebGPU）
├── scripts/
│   ├── export_static.py     # 静态站点数据导出脚本
│   └── prepare_civmap_data.py # 文明地图底图数据下载与预处理
├── .github/
│   └── workflows/
│       └── deploy-pages.yml # GitHub Pages 自动部署
├── .claude/
│   └── commands/            # Claude Code 自定义技能
│       └── narrate.md       # /narrate 技能（调用 narrate 后端）
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

# AI 叙述（用 Claude 生成世界的口语化描述）
uv sync --extra narrate                        # 安装可选依赖（仅需一次）
uv run dreamulator narrate myworld
uv run dreamulator narrate myworld --branch pangea

# 文明地图底图数据（已通过 Git LFS 存储在仓库中，无需手动下载）
uv run dreamulator narrate myworld -m claude-opus-4-6   # 指定模型

# 启动服务器（API + 前端，一条命令）
uv run dreamulator serve --open              # 启动并打开浏览器
uv run dreamulator serve --reload             # 开发模式（热重载）
uv run dreamulator serve --data-dir private/worlds  # 使用自定义数据目录

# 数据目录配置
# 所有 CLI 命令和 API 服务支持 --data-dir 参数或 DREAMULATOR_DATA_DIR 环境变量
# 来覆盖默认的 data/worlds/ 数据目录。开发时建议使用 private/worlds/
# （已在 .gitignore 中排除），避免编辑地图等操作污染 git 工作区。

# 运行测试
uv run pytest

# 代码检查
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/
```

### TypeScript 前端

前端支持两种模式：**API 模式**（默认，需要后端）和**静态模式**（GitHub Pages，只读）。

```bash
cd frontend

# 安装依赖
npm install

# 开发（API 模式：Vite HMR，自动代理 /api → FastAPI :8000）
npm run dev

# 构建（API 模式：构建后由 `dreamulator serve` 统一提供）
npm run build

# 导出世界数据为静态 JSON（静态模式前置步骤）
npm run export

# 构建静态站点（GitHub Pages，只读模式，base path 由 .env.static 控制）
npm run build:static

# 本地预览静态构建结果
npm run build:static:local && npm run preview:static

# 类型检查
npx tsc --noEmit

# Lint
npm run lint
```

> **单命令启动**：`npm run build` 后，`uv run dreamulator serve` 同时提供 API 和前端。
> 开发时仍可单独 `npm run dev` 使用 Vite HMR（代理到 :8000）。
>
> **静态模式**：`VITE_STATIC_MODE=true` 时前端读取预导出的 JSON（`scripts/export_static.py`），
> 不依赖后端，但创建/删除/构建/验证/叙述等写操作不可用。
> GitHub Pages 部署通过 `.github/workflows/deploy-pages.yml` 自动化。
>
> **⚠️ 静态导出同步**：新增 API 端点或数据字段时，**必须同步更新**以下三个文件，
> 否则 GitHub Pages 部署后对应功能将不可用：
> 1. `scripts/export_static.py` — 添加新数据到导出流程
> 2. `frontend/src/api/staticClient.ts` — 添加对应的静态数据读取方法
> 3. `frontend/src/api/client.ts` — 确保 unified API 在静态模式下委托给 staticClient

### Claude Code 自定义技能

本项目在 `.claude/commands/` 中定义了自定义技能，可在 Claude Code 中直接使用：

```
/narrate earth                         # 描述基础世界
/narrate earth --branch l4-companion   # 描述分支世界
```

技能底层调用 `src/dreamulator/narrator.py` 后端模块，与 CLI `dreamulator narrate` 命令共享逻辑。

**API 配置解析链**（优先级从高到低）：
1. CLI `--model` 参数 / 环境变量 `ANTHROPIC_API_KEY`、`ANTHROPIC_AUTH_TOKEN`、`ANTHROPIC_BASE_URL`、`ANTHROPIC_MODEL`
2. `~/.claude/settings.json` → `env.*` 字段及顶层 `model` 字段
3. 内置默认值 `claude-sonnet-4-6`

## 核心设计原则

### 层级架构

世界数据按学科层级组织，从最基础到最衍生：

```
physics → chemistry → astronomy → geological → climate → ecology → civilization
```

每个世界使用 `layers/` 目录结构：

```
data/worlds/myworld/
├── world.yaml
├── layers/
│   ├── physics/
│   │   ├── input/          # 物理定律参数（空=标准物理）
│   │   └── derived/        # 引擎计算结果
│   ├── astronomy/
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

- 在 `astronomy` 层分叉 → 相同物理/化学定律下的不同恒星系
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
physics → chemistry → astronomy → geological → climate → ecology → civilization
```

引擎在 `src/dreamulator/engine/` 中继承 `BaseEngine`，声明 `layer`、`requires`、`input_files`、`output_files`，由 `pipeline.py` 自动拓扑排序执行。

引擎通过 `find_input()` 方法沿层级链向上搜索输入文件，支持从分支继承数据。

### 引擎输入模式与一致性校验

开发新引擎时，输入数据应遵循以下模式（参考天文学引擎 `engine/astronomy.py`）：

1. **自变量/因变量分类**：每个引擎的数据模型明确区分自变量（输入）和因变量（输出）。自变量字段设为可选，通过 `model_validator` 确保至少提供一组完整自变量。

2. **混合输入模式**：允许可选的替代自变量集。例如 `Star` 模型支持 mass-only、luminosity-only、both 三种输入方式。引擎内部根据实际提供的字段选择计算路径。

3. **手动覆盖 + 一致性校验**：因变量字段允许用户手动填写（覆盖引擎计算值）。当用户同时提供自变量和因变量时，引擎正向计算预期值并与用户值比较：
   - 偏差 ≤ 阈值（通常 20%）→ 静默接受
   - 偏差 > 阈值 → 记录 warning（`EngineResult.warnings`），严格模式下抛错

4. **纯计算模块分离**：物理公式实现为纯函数模块（如 `engine/stellar_physics.py`），与引擎 IO 层（`engine/astronomy.py`）分离。纯函数无 IO、无 RNG，可独立单元测试。

## 编码规范

- Python: ruff 格式化，line-length=100，strict mypy
- TypeScript: ESLint + strict mode
- 文件 I/O: **始终** 显式指定 `encoding="utf-8"`
- 数据 ID: 使用稳定字符串（如 `"star_sol"`），不用数组索引
- 物理单位: 在字段名中显式标注（`_au`, `_km`, `_kg`, `_days`）
- 使用枚举而非自由字符串（`SpectralClass.G` 而非 `"G-type"`）
- 嵌套深度不超过 4 层
