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
>
> **⚠️ 静态导出同步**：新增 API 端点或数据字段时须同步三个文件，见下文「静态导出同步」。

### 项目技能

技能按 Agent Skills 开放格式写在 `.agents/skills/<名称>/SKILL.md`：`narrate`（口语化描述世界）、`audit-doc`（文档与代码
一致性审计）、`grill-world`（设定自洽性拷问）、`diagnose-climate`（气候异常诊断）与 `read-map`（读图核查）。
Claude Code 用 `/narrate earth` 调用，Codex 用 `$narrate earth` 调用。`narrate` 底层调用 `src/dreamulator/narrator.py`，
与 CLI `dreamulator narrate` 共享逻辑。

**narrate 的 API 配置解析链**（优先级从高到低）：
1. CLI `--model` 参数 / 环境变量 `ANTHROPIC_API_KEY`、`ANTHROPIC_AUTH_TOKEN`、`ANTHROPIC_BASE_URL`、`ANTHROPIC_MODEL`
2. `~/.claude/settings.json` → `env.*` 字段及顶层 `model` 字段
3. 内置默认值 `claude-sonnet-4-6`

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

### 模型态 vs obs 态分离（earth root = 真实数据锚，永不 build）

`earth` 是**真实地球参照世界**（reference baseline），不是「模型的地球」。硬规则：

- **root 的 `maps/planet_earth/cvt_mesh.json` 绝对只含真实地球数据**：ETOPO1 高程、真实板块边界、
  海陆掩膜，以及 `import_earth_climate` 导入的真实观测 obs 态字段（ERA5 / GPCP / Beck / SODA）。
- **所有模型算出的字段**（`temperature_C` / `precipitation_mm` / `koppen_class` 等）**只写在分支上**
  （`earth/branches/climate-dev` 等），绝不写进 root。
- **earth root 永不 build**：模型字段宁可空缺（缺失），也绝不用生成值填充。前端/验证读不到 root 的
  模型字段时，报「缺失」并指向分支，而不是触发一次 root build。

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

## 开发注意事项

### 多 agent 与跨平台约定

- **规则只写在 `AGENTS.md`。** 根目录与子目录的 `AGENTS.md` 是 Claude Code、Codex 等工具共用的唯一来源；同目录的
  `CLAUDE.md` 只含 `@AGENTS.md` 导入，不写内容。新建作用域规则时两个文件一起建，`tests/test_agent_instructions.py` 检查成对与导入。
- **进入子目录先读该目录的 `AGENTS.md`。** Codex 只加载从仓库根到启动目录路径上的文件，在根目录启动时不会自动读到
  `frontend/AGENTS.md` 或 `docs/**/AGENTS.md`；改前端前读 `frontend/AGENTS.md`，改文档前读对应目录的索引。
- **根 `AGENTS.md` 保持在 32 KiB 以内。** 这是 Codex 拼接项目说明的缺省上限，超出部分会被截断；只适用于某个目录的规则放进该目录的 `AGENTS.md`。
- **技能改 `.agents/skills/`。** 改完运行 `uv run python scripts/dev/sync_agent_skills.py` 同步到 `.claude/skills/`；
  测试会比对两份内容。frontmatter 只用 Agent Skills 规范字段（`name`、`description`），参数写成 `$ARGUMENTS` 并注明宿主未替换时从用户请求读取。
- **不提交符号链接。** Windows 需要管理员权限或开发者模式才能创建符号链接，未开启 `core.symlinks` 的克隆会把链接检出为一行文本；
  需要共享内容时用导入或脚本生成的真实文件。规则与技能文件由 `.gitattributes` 固定为 LF 换行。

### 文档/设定更新：只写当前设定，不写历史

文档或设定更新时，直接写「当前设定」，不残留之前设定、也不写「XX已修正/翻案/原XX」
这类历史表述——历史由 git 管理，git commit message 才是记录历史的地方。涉及推导参数表，
只放「当前值 + 参数范围」，不放「旧值 → 新值」叙事。

### 文风：平实完整句，全库禁电报体（含设计笔记）

**所有**文档（对外设定、设计笔记、docs/、审计台账、CHANGELOG 皆然）用平实
易读的完整句子写作，术语首次出现要解释。禁止电报体：箭头链（`A → B → C`
代替因果句）、斜杠堆叠（`温度/海冰/降水` 代替完整列举）、无动词碎片
（「死点 22.3 kyr 韵珠弹射」式的裸短语）、括号套括号的多重嵌套注记。
表格可以用，但单元格也应是可独立读懂的短句，不是关键词串。数字要带单位
和口径（「订正后 ≈ +10°C（含 −9.6 K 参照偏差）」而不是「10C*」）。
写完自查一遍：每个句子有主语和动词吗？读者不看别的文档能懂吗？

### 对外设定 vs 设计笔记的划分（作者裁决 2026-10-07）

**对外设定** = `data/worlds/*/layers/*/input/*.md` 全文 + yaml 的 `description`
等叙事字段（会渲染给读者/前端/视频）。标准：

1. 只写世界内现行状态，平实完整句、解释术语、忌电报体；
2. **现实天体/地球类比不入文**（「木卫三类比」「Europa 大小」「Charon 级」等
   太阳系/地球专名只进设计笔记）；面向读者的**单位参照**合法（「0.69× 满月宽」
   「亮于金星 ~38 倍」——换算帮助，不是世界内命名）；
3. **豁免/审计叙事不入文**：被叙事豁免覆盖的事件（死期、失稳、末世天象）与
   工程过程语（REBOUND、抽签、认证跑、MEGNO 等）只进设计笔记；对外只写正面
   正典 + 一句 design-notes 指针；
4. **数值优先模板化**：引擎目录有字段的量用 `{{ entities.* }}`/`{{ sky.* }}`
   渲染；目录没有的允许硬编码，但正典变更时必须全库同步（教训：路线 1 亮度链
   半同步残留 12+ 处）；yaml 注释同样不留历史叙事。

**设计笔记**（design-notes/、docs/design/、docs/knowledge/）承载决策理由、实验
记录、类比、审计值与工程红线；旧结果只留在文首「更新历史」块；文风同样遵守
上节「平实完整句，全库禁电报体」。

### 任务文档分工（收集 → 执行 → 战略 → 设计 → 归档）

任务/计划/设计类文档按时间尺度与生命周期分五层，信息单向流动。**单一事实源**：每个条目的
完整定义只住一处，其余层只持有指针，不复述内容（防双写漂移）。

| 层 | 文件 | 入库 | 记什么 | 不记什么 |
|------|------|:--:|--------|---------|
| 收集箱 | 本机私有收集箱文件（gitignored） | ✗ | 开发中闪现的原始想法，append-only | 不排序不细化；**条目全部落入执行层后即清空（总量优先）** |
| 执行台 | 本机私有执行台文件（gitignored） | ✗ | 本周执行顺序、分支/构建状态快照、教训一行、进行中项指针 | 不复述 roadmap/proposal 条目；已完成项删掉换一行 ✅ 指针 |
| 战略图 | `docs/design/roadmap.md` | ✓ | Phase 状态机、P0–P3 待办表（每格 ≤2 行 = 一句话摘要 + 指针）、技术债登记表 | 不记每日进度、不堆积已完成项、条目不写成段落 |
| 设计文档 | `docs/design/proposals/`（未实现设计+方法论）、`docs/design/pipelines/`（已实现技术参考） | ✓ | 物理第一性推理 + 文献 + **当前**方案 + 已否证方向各一行 | **不堆积实验记录**（敏感性扫描/正负结果数值）；不记优先级/技术债（roadmap 的事）、不记每日进度（today 的事）；不写「已修正/旧值」叙事 |
| 归档层 | `CHANGELOG.md`、各世界 `design-notes/`、git | ✓ | 已完成工作与最终决策的全部细节 | — |

**分诊规则**（收集箱 → 其他层，开/收工时扫一眼）：当场可做 → 执行台待办；
方向性/功能提案 → roadmap 一行（需展开则写 `proposals/`）；纯知识 → `docs/knowledge/`；
无价值 → 删。roadmap.md 回答「接下来几个月做什么、为什么是这个顺序」，月更频率；
每日待办只写执行台文件，不进 roadmap。

**proposal 生命周期**（「活的但稳定」的设计文档，非工作日志、非一次性总结）：
立项（物理+方案）→ 迭代执行（**方案变更才动**，实验记录进 git/CHANGELOG）→ 完成后
「已实现」技术参考移到 `pipelines/`，proposal 只留「为什么」+「已否证方向」。
**完成态流向**：普适物理机制 → `docs/knowledge/`；已实现管线细节 → `pipelines/`；
完成结果一行 → `CHANGELOG` + git commit；proposal 里的方案段 → 删，留「✅ 已实现 → 指针」；
负结果 → proposal 留「已否证」一行（防重试），细节进 git。

**proposal 是公开文本，入库前过三条判据**（`docs/design/audit/wave7-proposal-hygiene.md` 为执行台账）：

1. **只写结论**：方案、物理依据、验收指标与已否证方向各一行入库；逐轮试验数字、调参过程、
   带日期的诊断小节不入库，它们住 git、`CHANGELOG.md` 与私有实验目录。
2. **不写私有信息**：不出现私有目录路径与本地数据缓存路径（改写为「复现脚本另存」），
   不出现机器分工与开发机硬件（需要保留的性能数字只写配置，不写是谁的机器）。
3. **有状态头**：文首写明状态（草案 / 已接受 / 部分实现 / 已实现 / 已否证终止）与立项日期；
   历史只留在文首「更新历史」块。

单一世界的定稿裁决属于该世界的 `design-notes/`，不放 `proposals/`。

### 开发流程纪律

1. **新任务默认开 feature 分支**：`git checkout -b feature/<描述>`，不在 main 上直接开发；合入 main 前清理 commits（squash 为语义清晰的少量提交）。
2. **开发分支不推远程**：`git push` 仅用于 `main` 分支。
3. **每次 commit/push 前需用户确认**：先展示改动摘要（`git diff --stat` 或关键 diff），等用户明确说「提交/推送」再执行。
4. **提交前先在 `data/worlds` 上构建验证**：改动涉及引擎/管线时，先跑
   ```bash
   uv run dreamulator build nacrea --force
   ```
   （默认数据目录即 `data/worlds`，输出已被 ignore）让用户检查结果后再合并。
5. **mypy/ruff 本地检查是硬门槛**：准备 commit 前至少跑 `uv run mypy src/` + `uv run ruff check src/ tests/`，零错误才能提交（发版前再加 `uv run ruff format --check src/ tests/`）。
6. **合并到 main 后再推送**：用户验证通过 → merge 到 main → `git push`。
7. **构建产物不入 git（GitHub Releases 发布）**：`maps/` 与 `layers/*/derived/` 是「input + 代码 +
   seed」的确定性产物，**不 commit、不走 LFS**（`.gitignore` 已忽略）。
   直接在 `data/worlds` 构建（输出被 ignore、不污染工作区）；发版前跑
   `uv run python scripts/release/publish_world_data.py` 一条命令完成「构建 + 打包 + 上传」到固定 release
   tag `worlds-data`，`deploy-pages.yml` 下载后做静态导出。**顺序：先 publish 再 push 会影响数据的
   input 改动**，否则 Pages 拿到旧数据。mesh 盘上格式 = `cvt_mesh.msgpack.gz`（gzip 帧msgpack）；读写一律走 `map/export.py` 的 `save_cvt_mesh` / `load_cvt_mesh` / `load_cvt_mesh_model` /`find_mesh_file`（嗅探兼容旧 gzip-JSON / 纯 JSON `cvt_mesh.json`，零迁移）。
8. **导出产物一律进 `exports/`**：图片、视频、QA 静帧与对比图等导出产物统一写到主仓库
   `exports/`（已 gitignore），按链分子目录（`exports/globe/`、`exports/video/<类>/` 等）；
   相关导出/渲染脚本放 `scripts/media/` 随版本管理。`exports/` 内的大文件不进 git 也不走
   release（气象图层包等同理）。

### 气候修改差异对比

改气候引擎后用 `scripts/climate/climate_diff.py` 对比两次构建，步骤见
[气候验证工作流](docs/usage/climate-validation-workflow.md#7-两次构建的差异对比)。

### 静态导出同步

新增 API 端点或数据字段时，**必须同步更新**以下三个文件，否则 GitHub Pages 部署后对应功能不可用：
1. `scripts/release/export_static.py` — 添加新数据到导出流程
2. `frontend/src/api/staticClient.ts` — 添加对应的静态数据读取方法
3. `frontend/src/api/client.ts` — 确保 unified API 在静态模式下委托给 staticClient

**改动后必须本地验证静态站**（历史教训：v0.10.0 的 `maps/` 目录迁移未同步到导出脚本，
导致 Pages 地图长期 404）：

```bash
cd frontend && npm run build:static:local && npm run preview:static
# 打开 http://localhost:4173，确认页面功能正常、控制台无 404
```

> 本地静态导出/预览前，先在 `data/worlds` 上构建（`uv run dreamulator build ...` 或
> `uv run python scripts/release/publish_world_data.py`）；`export_static.py` 默认读 `data/worlds`。

### 知识库与设计模式文档同步

引入新的学科知识（公式、参数、模型）或设计模式时，**必须同步更新**对应文档：

1. **学科知识** → `docs/knowledge/<discipline>/`：
   - 新的物理公式、化学方程式、地质参数、气候模型、生态分类等
   - 参考现有格式：公式 + 参数表 + 源码引用 + 学术参考
   - 各学科子目录的 `AGENTS.md` 索引文件也需更新

2. **设计模式** → `docs/worldbuilding/design_patterns.md`：
   - 新的 YAML/JSON 配置模板、分支工作流、数据编码方式
   - 每个模式包含：概念说明 + YAML 示例 + 源码引用路径

3. **路线图/架构变更** → `docs/design/roadmap.md`：
   - 竞品分析更新、Phase 优先级调整、新功能提案

**原则**：代码是"实现"，文档是"解释"。代码变更无文档同步 = 技术债务。

### 文档↔代码一致性审计

`docs/design/` 按实现状态分三类：`pipelines/`（已实现管线技术参考）、`proposals/`
（设计提案/方法论）、根目录（总览/路线图/竞品/审计）。**只有 `pipelines/` 的引用必须对齐
当前代码**；`proposals/` 的未来字段/设计词汇是合法的前向引用，`archive/`+`audit/` 是历史快照。

- **工具**：`scripts/dev/check_doc_refs.py` 扫 `pipelines/` 的 file:line 引用 + 反引号
  snake_case 符号，报出改名/删除/失效。**pre-push 钩子已挂为硬门槛（只 gate main）**。
- **审计发现**记入 `docs/design/audit/waveN-<slug>.md`（映射表 + `文件:行号` 证据），
  修复后重跑 `check_doc_refs.py` 确认归零。
- **改引擎字段/函数时**：同步更新 `pipelines/` 里引用它的文档 + 重跑 `check_doc_refs.py`；
  否则 push main 会被钩子拦下。斜杠技能 `/audit-doc` 封装了这条审计流程。

### 竞品参照：实现/诊断前先调研

`docs/design/competitor-analysis.md` 记录了各 DAG 层级的对标专业软件和开源项目。
**在实现或修改某个层级的引擎/算法时，以及诊断/攻关某个气候或物理异常时，
都必须先调研相关竞品的实现方案与文献**：

1. **查阅竞品文档** — 找到对应层级（天文/地质/气候/生态/文明）的专业工具列表
2. **搜索论文** — 用 `WebSearch` 检索该工具的发表论文（arXiv、MNRAS、JGR 等），提取关键公式、参数表和验证方法。诊断根因与提修法同样遵循物理第一性：先文献定位机制，再动代码
3. **阅读开源源码**（如果可用）— 用 `WebFetch` 抓取 GitHub 仓库中的核心算法文件。重点关注：
   - 输入参数和默认值
   - 数值方法和求解器选择
   - 输出数据结构和可视化方式
   - 单元测试中的验证基准
4. **本地引擎资源**（开源 & 闭源）— 决策方案时对照它们的实现：
   - 本机私有目录中克隆的外部项目（不随仓库分发，如 ExoPlaSim 实验副本）
   - 本机安装的工具（如 Gleba；可用性/用途见本机任务记录）
   - 能跑则跑（对照输出），闭源则读文档/数据文件推断其方案

**各层级参照工具速查**：

| 层级 | 优先参照 | 开源 |
|------|---------|:--:|
| 天文 | MESA（恒星演化）、REBOUND（N 体轨道） | ✅ |
| 地质 | GPlates（板块重建）、Landlab（地表过程）、Fastscape（河流侵蚀） | ✅ |
| 气候 | ExoPlaSim（系外行星 GCM）、climlab（Python 气候工具箱）、World Orogen（同类 EBM 验证工装参照，GPL 勿抄码） | ✅ |
| 生态 | Madingley Model（通用生态系统）、Biblaridion Alien Biosphere（方法论） | ✅ |
| 文明 | Seshat Databank（历史验证数据）、HANDY（人口-资源 ODE） | ✅ |

**原则**：不在真空中设计算法、也不在真空中诊断问题。每个引擎决策和每个根因判断都要有
**物理第一性**（从物理推导）、**地球真实参考**（观测数据）或**业界成熟方案**
（论文/源码/竞品引擎实现）三者至少其一的支撑。竞品文档更新时，本节的速查表也需同步。
