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

### 引擎设计纪律（最高优先级）

1. **第一性计算 > 先验启发式**：每个引擎决策优先从物理推导，尽量少引入启发式自变量。新增参数必须是可推导量（从自转/光度/倾角/海陆分布等物理量推出），不接受「为让结果像一点」的裸调。
2. **同物理（所有世界同一套物理引擎）**：只差输入参数，不做单世界特调。改完必须在其他世界（如 gaia-m）回归验证，指标不能退化。
3. **不因一时变差而放弃第一性**：当第一性改动让验证指标暂时变差时，先判断「指标变差是物理错了，还是标定/口径没跟上」——物理错了才回退，标定没跟上就修标定或整体重推，而不是退回启发式。
4. **避免过早优化**：为了第一性可适当放弃运行速度，先建立准确的模型，之后再回头优化。交互性（秒级~分钟级）是硬约束，但不能以牺牲正确性为代价去满足它。

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

## 开发注意事项

### 文档/设定更新：只写当前设定，不写历史

文档或设定更新时，直接写「当前设定」，不残留之前设定、也不写「XX已修正/翻案/原XX」
这类历史表述——历史由 git 管理，git commit message 才是记录历史的地方。涉及推导参数表，
只放「当前值 + 参数范围」，不放「旧值 → 新值」叙事。

### 开发流程纪律

1. **新任务默认开 feature 分支**：`git checkout -b feature/<描述>`，不在 main 上直接开发；合入 main 前清理 commits（squash 为语义清晰的少量提交）。
2. **开发分支不推远程**：`git push` 仅用于 `main` 分支。
3. **每次 commit/push 前需用户确认**：先展示改动摘要（`git diff --stat` 或关键 diff），等用户明确说「提交/推送」再执行。
4. **提交前先在 `private/worlds` 上构建验证**：改动涉及引擎/管线时，先跑
   ```bash
   uv run dreamulator build gaia-m --data-dir private/worlds --force
   ```
   让用户检查结果后再合并。
5. **mypy/ruff 本地检查是硬门槛**：准备 commit 前至少跑 `uv run mypy src/` + `uv run ruff check src/ tests/`，零错误才能提交（发版前再加 `uv run ruff format --check src/ tests/`）。
6. **合并到 main 后再推送**：用户验证通过 → merge 到 main → `git push`。
7. **LFS 大文件纪律**：`cvt_mesh.json`（已 gzip 存储，~31.6MB）、PNG 等大文件走 Git LFS，
   LFS 存完整对象不做增量。调参期间**只在 `private/worlds` 构建**，发版前最后一次才同步
   `data/worlds` 并 commit，否则反复重建+commit 会撑爆 LFS 配额（v0.27.0、v0.33.0 两次踩坑）。
   读取 mesh 用 `decompress_mesh_bytes`（透明解压，兼容纯 JSON）；push 被 `GH008 unknown LFS
   objects` 拒绝时，先 `git lfs push --all origin` 再 `git push`。

### 气候修改差异对比

改气候引擎后，用小差异难以在前端看出效果。使用 `scripts/climate_diff.py` 对比两次构建：

```bash
# 改前保存基线
cp -r private/worlds/gaia-m/maps/satellite_gaiam private/worlds/gaia-m/maps/_baseline

# 改代码 → 构建
uv run dreamulator build gaia-m --data-dir private/worlds --only climate --force

# 对比
uv run python scripts/climate_diff.py \
    private/worlds/gaia-m/maps/_baseline \
    private/worlds/gaia-m/maps/satellite_gaiam
```

输出：全局摘要（T/P/Köppen/biome）、纬度带平均差异、Top-N 变化最大的细胞。

### 静态导出同步

新增 API 端点或数据字段时，**必须同步更新**以下三个文件，否则 GitHub Pages 部署后对应功能不可用：
1. `scripts/export_static.py` — 添加新数据到导出流程
2. `frontend/src/api/staticClient.ts` — 添加对应的静态数据读取方法
3. `frontend/src/api/client.ts` — 确保 unified API 在静态模式下委托给 staticClient

**改动后必须本地验证静态站**（历史教训：v0.10.0 的 `maps/` 目录迁移未同步到导出脚本，
导致 Pages 地图长期 404）：

```bash
cd frontend && npm run build:static:local && npm run preview:static
# 打开 http://localhost:4173，确认页面功能正常、控制台无 404
```

### 3D 球面矢量可视化（风场/洋流箭头）

1. **切空间投影不要用数值差分**。`atan2(v,u)` 在局部切空间是对的，但映射到屏幕
   必须通过相机矩阵。数值偏移 `project(lon+de, lat)` 依赖偏移量选择（不同缩放/视角下
   偏移量对应的屏幕像素数不同，极地附近经度偏移退化），会产生方向跳变。正确做法是让
   `project()` 返回切空间基底在屏幕的像（`ex,ey,nx,ny`），在 `GlobeViewer.tsx` 中
   用 THREE.js `camera.project()` 解析计算，不与缩放耦合。

2. **速度和方向要分离**。洋流速度（~0.002 m/s）和风速（~5 m/s）差 2500 倍。
   直接将 (u,v) 乘以切空间基底 → 洋流矢量趋近零被后续阈值过滤。方向用单位向量、
   长度用速度，两者独立。

### 知识库与设计模式文档同步

引入新的学科知识（公式、参数、模型）或设计模式时，**必须同步更新**对应文档：

1. **学科知识** → `docs/knowledge/<discipline>/`：
   - 新的物理公式、化学方程式、地质参数、气候模型、生态分类等
   - 参考现有格式：公式 + 参数表 + 源码引用 + 学术参考
   - 各学科子目录的 `CLAUDE.md` 索引文件也需更新

2. **设计模式** → `docs/worldbuilding/design_patterns.md`：
   - 新的 YAML/JSON 配置模板、分支工作流、数据编码方式
   - 每个模式包含：概念说明 + YAML 示例 + 源码引用路径

3. **路线图/架构变更** → `docs/design/roadmap.md`：
   - 竞品分析更新、Phase 优先级调整、新功能提案

**原则**：代码是"实现"，文档是"解释"。代码变更无文档同步 = 技术债务。

### 竞品参照：实现前先调研

`docs/design/competitor-analysis.md` 记录了各 DAG 层级的对标专业软件和开源项目。
**在实现或修改某个层级的引擎/算法时，必须先调研相关竞品的实现方案**：

1. **查阅竞品文档** — 找到对应层级（天文/地质/气候/生态/文明）的专业工具列表
2. **搜索论文** — 用 `WebSearch` 检索该工具的发表论文（arXiv、MNRAS、JGR 等），提取关键公式、参数表和验证方法
3. **阅读开源源码**（如果可用）— 用 `WebFetch` 抓取 GitHub 仓库中的核心算法文件。重点关注：
   - 输入参数和默认值
   - 数值方法和求解器选择
   - 输出数据结构和可视化方式
   - 单元测试中的验证基准

**各层级参照工具速查**：

| 层级 | 优先参照 | 开源 |
|------|---------|:--:|
| 天文 | MESA（恒星演化）、REBOUND（N 体轨道） | ✅ |
| 地质 | GPlates（板块重建）、Landlab（地表过程）、Fastscape（河流侵蚀） | ✅ |
| 气候 | ExoPlaSim（系外行星 GCM）、climlab（Python 气候工具箱） | ✅ |
| 生态 | Madingley Model（通用生态系统）、Biblaridion Alien Biosphere（方法论） | ✅ |
| 文明 | Seshat Databank（历史验证数据）、HANDY（人口-资源 ODE） | ✅ |

**原则**：不在真空中设计算法。每个引擎决策都应有"论文/源码/数据"三者至少其一的支撑。
竞品文档更新时，本节的速查表也需同步。

### i18n：多语言字符串

项目使用 `react-i18next` 做国际化。配置入口 `src/i18n/index.ts`，locale 文件在 `src/i18n/locales/<lang>/`。

**命名空间**：`common`（通用 UI）、`map`（地图/球面）、`worlds`（世界管理）、`civmap`（文明地图）、`help`（帮助页内容）。

**新增可翻译字符串时**：
1. 选择正确的命名空间 JSON 文件
2. 添加 key（中文值写到 `zh-CN/`，英文写到 `en/`）
3. 在组件中使用 `useTranslation()` hook：`const { t } = useTranslation('map')`
4. 硬编码中文是技术债——新代码一律走 `t()`。

**约定（2026-08 i18n 扫尾后确立）**：
- **自包含命名空间**：每个 namespace 自带它需要的 action/status/label，不跨 ns 复用
  （`worlds.action.create` 与 `common.action.create` 并存是约定，不是重复）。
- **词典表 → i18n key**：Köppen 群系/土纲这类「code → 中文名」的模块级映射表存 i18n
  key（如 `'koppen.Af'`），在使用处 `t(key)` 解析——不能模块级直接 `t()`，否则语言切换不生效。
- **类组件用 `i18n.t()`**（import i18n 单例），函数组件用 `useTranslation`。
- **跨命名空间引用**：用绝对 key `t('help:layer.terrain.label')`（`ns:` 前缀）。
- **扫描命令**：`grep -rnE '[一-龥]' frontend/src --include='*.ts' --include='*.tsx'`
  （注释、语言名、死代码除外）。
- **语言切换器**：Sidebar 页脚（`components/LanguageSwitcher.tsx`），localStorage
  `dreamulator-lang` + 浏览器语言兜底。

**添加新语言**：复制 `zh-CN/` → `<code>/`，翻译 JSON 值（key 结构保持不变），在 `index.ts` 的 `resources` 中注册。

### React StrictMode + Three.js/R3F 纹理上传（2026-08 调试经验）

React StrictMode 开发模式下对函数组件体、state updater、useMemo/useReducer 等双重调用。与 R3F/Three.js 交互时存在以下反模式：

1. **`texture.needsUpdate` 被 StrictMode 消耗**：第一次 mount 时 Three.js 检测到 `needsUpdate=true` → 上传纹理到 GPU → 设 `needsUpdate=false`。StrictMode 卸载 WebGL 上下文后第二次 mount（真正的渲染），纹理对象被缓存复用但 `needsUpdate=false` → 纹理永远不再上传 → 显示 fallback 色。

   **解决**：不依赖 `needsUpdate`。要么确保 GlobeViewer 只在纹理数据完全就绪后才挂载（避免材质切换），要么用 `key` 强制 Canvas 重建 WebGL 上下文。

2. **R3F `<meshStandardMaterial>` 三元切换不可靠**：`{tex ? <M map={tex}/> : <M color/>}` 从 null→Texture 切换时，R3F 卸载旧材料挂载新材料，但纹理的 `needsUpdate` 状态可能已被前次渲染消耗。

3. **`useGPUTerrain` 返回 1px 占位纹理**：该 hook 在真实地形烘焙完成前先返回一个 1px DataTexture。若在此阶段挂载 GlobeViewer，会先渲染黑球（占位纹理），真纹理到达后再切换材料——受 #1 和 #2 影响几乎必定失败。

   **调试方法**：用 `performance.now()` 打时间戳日志追踪异步事件顺序。`[Violation] 'message' handler took Xms` 是 React scheduler 用 `MessageChannel.postMessage` 调度同步 work loop 的标志——这段时间内 KD-tree 构建和纹理烘焙在主线程阻塞执行。

4. **生产模式无 StrictMode** → 本地开发通过不代表生产通过。`npm run build` 后的构建产物不会双重调用。

### React Hooks 规则

React 组件中的 hooks（`useState`、`useEffect`、`useMemo`、`useQuery` 等）**必须在每次渲染中以相同顺序调用**。禁止在 hooks 之间放置条件 `return`：

```tsx
// ❌ 错误：hooks 之间有 early return，导致 hook 调用顺序不一致
if (!data) return null
const computed = useMemo(() => ..., [data])  // 当 data 为 null 时不会被调用

// ✅ 正确：所有 hooks 在 early return 之前调用
const computed = useMemo(() => ..., [data])
if (!data) return null
```
