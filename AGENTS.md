# Dreamulator

架空世界设定工具——从恒星系和物理定律出发，利用各学科知识进行严谨的世界推演。

## 项目架构

```
dreamulator/
├── docs/
│   ├── knowledge/           # 学科知识库（天体物理、地质、气候、生态、社会）
│   ├── worldbuilding/       # 架空世界创建思路与方法论
│   ├── usage/               # 用法指南（CLI、地图工作流、前端操作）
│   └── design/              # 架构设计文档（架构、愿景、路线图、子系统设计文档）
├── data/
│   ├── templates/           # 世界模板（minimal, earthlike）
│   └── worlds/              # 世界实例
├── schemas/                 # JSON Schema（由 Pydantic 自动生成）
├── src/dreamulator/         # Python 后端
│   ├── models/              # Pydantic 数据模型
│   │   ├── layers.py        # 层级定义和工具函数
│   │   └── branch.py        # 分支元数据模型
│   ├── engine/              # 模拟引擎（DAG pipeline）
│   ├── map/                 # 地图子系统（球面 CVT 网格 + 板块构造管线）
│   │   ├── models.py        # 地图数据模型（MapMetadata, CVTMesh, VoronoiCell, TectonicPlate）
│   │   ├── cvt_mesh.py      # CVT 球面网格（Fibonacci 螺旋 + Lloyd 松弛）
│   │   ├── plate_generator.py  # 板块剖分（Cortial 2019）+ 地理锚定地壳切分
│   │   ├── tectonic_simulator.py # 构造时间演化（旋转/俯冲/碰撞/裂解/海沟弧）
│   │   ├── terrain_synthesizer.py # 地形合成（边界效应 + fBm + 海平面校准）
│   │   ├── geography.py     # 配置化海陆锚定（geography.yaml 偏置场）
│   │   ├── climate_simulator.py # EBM 温度 + 地转风 + BFS 水汽 + Köppen
│   │   ├── elevation_codec.py  # 高度图 PNG ↔ numpy 编解码
│   │   ├── importer.py      # 外部高度图导入（PNG/TIFF 解码 + 重采样）
│   ├── gcm/             # ExoPlaSim offline-oracle 薄适配层（mapping/runner/
│   │                    # diagnostics/plotting；[gcm] 可选 extra）
│   │   ├── export.py        # CVT → 等距圆柱栅格导出
│   │   └── manager.py       # 地图 CRUD + 分支继承 + 图层注册表
│   ├── civmap/              # 文明地图子系统（真实地球行政区划 + 架空领土涂色）
│   │   ├── models.py        # 数据模型（CivCountry, CivSnapshot, CivTerritory）
│   │   └── manager.py       # CRUD + 分支继承 + 国家/省份映射
│   ├── io/                  # 文件读写层
│   ├── api.py               # FastAPI 应用
│   ├── api_routes/          # API 路由模块（worlds、narrate、maps、civmap）
│   ├── branch_manager.py    # 分支 CRUD 操作
│   ├── resolver.py          # 层级数据解析器
│   ├── doc_render.py        # 文档模板渲染（Jinja2，读取/导出时按需）
│   ├── narrator.py          # AI 叙述后端（Claude API）
│   ├── world_manager.py     # 世界 CRUD
│   ├── cli.py               # Typer CLI 入口
│   └── utils/               # 常量、单位、RNG
├── frontend/                # TypeScript SPA（Vite + React）
│   └── src/
│       ├── api/             # API 客户端
│       ├── components/      # UI 组件（含 map/ 地图编辑器组件）
│       ├── pages/           # 页面（含 MapViewerPage 全页地图查看器）
│       ├── stores/          # Zustand 状态管理
│       └── viewers/         # 3D 恒星系 + 2D 地图可视化器（Three.js / WebGPU）
├── scripts/                 # 按域分组（各组说明见 scripts/README.md）
│   ├── climate/             # 气候验证与诊断（validate_climate、diagnose_*、climate_diff）
│   ├── earth/               # 真实地球数据导入与验证参考（import_earth_*、download_validation_data）
│   ├── astro/               # 天文 N 体与恒星诊断（rebound_*、diagnose_stellar_physics）
│   ├── release/             # 发布与静态导出（publish_world_data、export_static）
│   └── dev/                 # 开发工具（check_doc_refs、profile_build、prepare_civmap_data）
├── .github/
│   └── workflows/
│       └── deploy-pages.yml # GitHub Pages 自动部署
├── AGENTS.md                # 全体 agent 共用的项目规则（各级子目录同名文件为作用域规则）
├── CLAUDE.md                # 只含 @AGENTS.md 导入，供 Claude Code 读取
├── .agents/skills/          # 项目技能的唯一来源（Codex 直接读取）
├── .claude/skills/          # 技能的同步副本（Claude Code 读取，由脚本生成）
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
uv run dreamulator build myworld --branch pangea

# 生成 JSON Schema
uv run dreamulator schema

# AI 叙述（用 Claude 生成世界的口语化描述；需先 uv sync --extra narrate）
uv run dreamulator narrate myworld
uv run dreamulator narrate myworld --branch pangea
uv run dreamulator narrate myworld -m claude-opus-4-6   # 指定模型

# 地图与画布（详见 docs/usage/cli.md）：map layers|globe、region pack|build、render
uv run dreamulator canvas run data/worlds/nacrea/canvases/gcm-t42-712   # 生成后：侵蚀 + S2 水文
uv run dreamulator canvas window <画布> --lat 15 --lon -100 --span-km 550

# 启动服务器（API + 前端，一条命令）
uv run dreamulator serve --open              # 启动并打开浏览器
uv run dreamulator serve --reload             # 开发模式（热重载）

# 数据目录
# 所有 CLI 命令和 API 服务支持 --data-dir 参数或 DREAMULATOR_DATA_DIR 环境变量
# 来覆盖默认的 data/worlds/ 数据目录。构建输出（maps/ + layers/*/derived/）已被
# .gitignore 忽略，直接在 data/worlds 构建不污染 git 工作区，无需单独的开发目录。

# ExoPlaSim GCM 参照臂（独立 pip venv，不走 uv）：见 docs/usage/exoplasim-gcm.md

# 运行测试（默认 xdist 并行，--maxprocesses 8；全量 ~1 min）
uv run pytest
# 迭代单个测试时关掉并行（省 worker 启动 ~3-5 s）
uv run pytest tests/test_foo.py -n 0

# 独立包测试（conlang；根 pytest 的 testpaths 不含包内测试）
uv run pytest packages/conlang/tests -q

# 代码检查
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/
```

改气候引擎后用 `scripts/climate/climate_diff.py` 对比两次构建（步骤见
[气候验证工作流](docs/usage/climate-validation-workflow.md#7-两次构建的差异对比)）。

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
> **静态模式**：`VITE_STATIC_MODE=true` 时前端读取预导出的 JSON（`scripts/release/export_static.py`），
> 不依赖后端，但创建/删除/构建/验证/叙述等写操作不可用。
> GitHub Pages 部署通过 `.github/workflows/deploy-pages.yml` 自动化。
> 新增 API 端点/数据字段时的三文件同步义务见 `frontend/AGENTS.md`「静态导出同步」。

### 项目技能

技能按 Agent Skills 开放格式写在 `.agents/skills/<名称>/SKILL.md`：`narrate`（口语化描述世界）、`audit-doc`（文档与代码
一致性审计）、`grill-world`（设定自洽性拷问）、`diagnose-climate`（气候异常诊断）与 `read-map`（读图核查）。
Claude Code 用 `/narrate earth` 调用，Codex 用 `$narrate earth` 调用。`narrate` 底层调用 `src/dreamulator/narrator.py`，
与 CLI `dreamulator narrate` 共享逻辑（API 配置解析链见该 skill 本体）。

## 核心设计原则

### 引擎设计纪律（最高优先级）

1. **第一性计算 > 先验启发式**：每个引擎决策优先从物理推导，尽量少引入启发式自变量。新增参数必须是可推导量（从自转/光度/倾角/海陆分布等物理量推出），不接受「为让结果像一点」的裸调。
2. **同物理（所有世界同一套物理引擎）**：只差输入参数，不做单世界特调。改完必须在其他世界（如 nacrea）回归验证，指标不能退化。
3. **不因一时变差而放弃第一性**：当第一性改动让验证指标暂时变差时，先判断「指标变差是物理错了，还是标定/口径没跟上」——物理错了才回退，标定没跟上就修标定或整体重推，而不是退回启发式。
4. **避免过早优化**：为了第一性可适当放弃运行速度，先建立准确的模型，之后再回头优化。交互性（秒级~分钟级）是硬约束，但不能以牺牲正确性为代价去满足它。
5. **减少互相矛盾的近似 > 继续增加机制数量**（astra 审计 §9）：先修守恒账本与状态一致，等「合同与预算稳定」后，剩余偏差才适合用来决定是否加动力学升级；不要用新门去修旧门的标定失效。
6. **守恒账本先于任何新降水机制**（astra 审计 §2.1）：先把账本外的后处理（地形雨/雨影/冷阱截断/海岸修温/向行星加雨）搬进预算内核成为真正的汇/源，再谈新增机制；账本残差是衡量这一步进度的硬指标。
7. **每轮只新增一个闭合假设**（astra 审计 §7）：最多两轮事先约定的消融/参数实验；避免「加第三个门修第二个门」。持续需要垂直风切变/上层基本态/瞬变涡旋才能完成核心需求时，转向现成动力后端（GCM），而非自建「小 GCM」。
8. **固定验证顺序**（astra 审计 §1/§8）：数据口径 → 守恒/自洽 → 大尺度过程 → 区域误差 → 下游用途；偏差图用于找线索，不直接决定加哪条规则。做干预实验归因（规定输入仅用于诊断、不进入产品），不凭偏差位置加补丁。
9. **闭合的知识论分类**（astra 审计 §6.3）：每个闭合/参数注明认识论类别——守恒定律 / 近似推导 / 观测拟合 / 数值稳定化——及标定域与不确定度。将拟合参数从 config 移到代码常数，不会让它从经验参数变成第一性常数。
10. **双轨验收**（astra 审计 shared-physics §8）：科学验收（预算/收敛/尺度/独立观测）与创作验收（世界意图是否实现）分开，不混用；模型派生的事实不称独立真值；无观测真值的世界（如 nacrea）不得以「维持原状」为科学验证——预测不符合作者意图时，调的是作者允许的输入或叙事，不是物理模型。

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
earth 参照世界的 obs 态铁律与对外设定的写作标准见 `data/worlds/AGENTS.md`。

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
新引擎的输入数据模式与一致性校验见 `src/dreamulator/engine/AGENTS.md`。

## 编码规范

- Python: ruff 格式化，line-length=100，strict mypy
- TypeScript: ESLint + strict mode
- 文件 I/O: **始终** 显式指定 `encoding="utf-8"`
- 数据 ID: 使用稳定字符串（如 `"star_sol"`），不用数组索引
- 物理单位: 在字段名中显式标注（`_au`, `_km`, `_kg`, `_days`）
- 使用枚举而非自由字符串（`SpectralClass.G` 而非 `"G-type"`）
- 嵌套深度不超过 4 层

## 开发纪律与约定

### 多 agent 与跨平台约定

- **共享记忆**：开工读 `private/memory/MEMORY.md` 与 `private/todos/today.md`，按索引读相关记录；收工更新必要事实与进度。
  规范写 `AGENTS.md`，经验写 `private/memory/`，待办写执行台。私有文件缺失时继续工作。
- **规则只写在 `AGENTS.md`。** 根目录与子目录的 `AGENTS.md` 是 Claude Code、Codex 等工具共用的唯一来源；同目录的
  `CLAUDE.md` 只含 `@AGENTS.md` 导入，不写内容。新建作用域规则时两个文件一起建，`tests/test_agent_instructions.py` 检查成对与导入。
- **进入子目录先读该目录的 `AGENTS.md`。** Codex 只加载从仓库根到启动目录路径上的文件，在根目录启动时不会自动读到
  `frontend/AGENTS.md` 或 `docs/**/AGENTS.md`；改前端前读 `frontend/AGENTS.md`，改文档前读对应目录的索引。
- **根 `AGENTS.md` 只保留概览与核心规则，且保持在 32 KiB 以内。** 这是 Codex 拼接项目说明的缺省上限，超出部分会被截断；
  目录专属规则放进该目录的 `AGENTS.md`（落点见文末「作用域规则索引」）。
- **技能改 `.agents/skills/`。** 改完运行 `uv run python scripts/dev/sync_agent_skills.py` 同步到 `.claude/skills/`；
  测试会比对两份内容。frontmatter 只用 Agent Skills 规范字段（`name`、`description`），参数写成 `$ARGUMENTS` 并注明宿主未替换时从用户请求读取。
- **不提交符号链接。** Windows 需要管理员权限或开发者模式才能创建符号链接，未开启 `core.symlinks` 的克隆会把链接检出为一行文本；
  需要共享内容时用导入或脚本生成的真实文件。规则与技能文件由 `.gitattributes` 固定为 LF 换行。

### 文档与设定更新：只写当前设定，不写历史

文档或设定更新时，直接写「当前设定」，不残留之前设定、也不写「XX已修正/翻案/原XX」
这类历史表述——历史由 git 管理，git commit message 才是记录历史的地方。涉及推导参数表，
只放「当前值 + 参数范围」，不放「旧值 → 新值」叙事。

### 文风：平实完整句，全库禁电报体

**所有**文档（对外设定、设计笔记、docs/、审计台账、CHANGELOG 皆然）用平实
易读的完整句子写作，术语首次出现要解释。禁止电报体：箭头链（`A → B → C`
代替因果句）、斜杠堆叠（`温度/海冰/降水` 代替完整列举）、无动词碎片
（「死点 22.3 kyr 韵珠弹射」式的裸短语）、括号套括号的多重嵌套注记。
表格可以用，但单元格也应是可独立读懂的短句，不是关键词串。数字要带单位
和口径（「订正后 ≈ +10°C（含 −9.6 K 参照偏差）」而不是「10C*」）。
写完自查一遍：每个句子有主语和动词吗？读者不看别的文档能懂吗？

### 开发流程纪律

1. **新任务默认开 feature 分支**：`git checkout -b feature/<描述>`，不在 main 上直接开发；合入 main 前清理 commits（squash 为语义清晰的少量提交）。
2. **开发分支不推远程**：`git push` 仅用于 `main` 分支。
3. **每次 commit/push 前需用户确认**：先展示改动摘要（`git diff --stat` 或关键 diff），等用户明确说「提交/推送」再执行。
4. **提交前先在 `data/worlds` 上构建验证**：改动涉及引擎/管线时，先跑
   ```bash
   uv run dreamulator build nacrea --force
   ```
   让用户检查结果后再合并。
5. **mypy/ruff 本地检查是硬门槛**：准备 commit 前至少跑 `uv run mypy src/` + `uv run ruff check src/ tests/`，零错误才能提交（发版前再加 `uv run ruff format --check src/ tests/`）。
6. **合并到 main 后再推送**：用户验证通过 → merge 到 main → `git push`。
7. **构建产物不入 git（GitHub Releases 发布）**：`maps/` 与 `layers/*/derived/` 是「input + 代码 +
   seed」的确定性产物，**不 commit、不走 LFS**（`.gitignore` 已忽略）。直接在 `data/worlds` 构建；
   发版前跑 `uv run python scripts/release/publish_world_data.py` 一条命令完成「构建 + 打包 + 上传」到固定 release
   tag `worlds-data`，`deploy-pages.yml` 下载后做静态导出。**顺序：先 publish 再 push 会影响数据的
   input 改动**，否则 Pages 拿到旧数据。mesh 盘上格式 = `cvt_mesh.msgpack.gz`（gzip 帧 msgpack）；
   读写一律走 `map/export.py` 的 `save_cvt_mesh` / `load_cvt_mesh` / `load_cvt_mesh_model` / `find_mesh_file`（嗅探兼容旧格式）。
8. **导出产物一律进 `exports/`**：图片、视频、QA 静帧与对比图等导出产物统一写到主仓库
   `exports/`（已 gitignore），按链分子目录；相关导出/渲染脚本放 `scripts/media/` 随版本管理。
   `exports/` 内的大文件不进 git 也不走 release（气象图层包等同理）。
9. **长任务先估内存峰值，超限必须分块**：本机内存溢出会让整台机器重启，丢掉所有会话和未存盘的结果。
   峰值预计超过可用内存一半的任务改为分块处理；后台长任务要设每进程内存上限，并挂看门狗，
   内存用量越线就终止该任务。

## 作用域规则索引

根目录只保留全仓通用的概览与核心规则；以下专题规则住在各自目录的 `AGENTS.md`（进该目录干活先读）：

| 主题 | 位置 |
|------|------|
| 前端开发、静态导出三文件同步 | `frontend/AGENTS.md` |
| 文档目录结构与写作指引、知识库/设计模式文档同步 | `docs/AGENTS.md` |
| 任务文档五层分工、proposal 生命周期与判据、文档↔代码一致性审计、竞品先调研 | `docs/design/AGENTS.md` |
| earth 参照世界 obs 态铁律、对外设定 vs 设计笔记划分 | `data/worlds/AGENTS.md` |
| 引擎输入模式与一致性校验 | `src/dreamulator/engine/AGENTS.md` |
| 学科知识库各库索引 | `docs/knowledge/<discipline>/AGENTS.md` |
| narrate 的 API 配置解析链 | `.agents/skills/narrate/SKILL.md` |
