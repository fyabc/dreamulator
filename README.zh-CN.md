# Dreamulator

<div align="center">
  <img src="docs/images/logo.png" alt="Dreamulator logo" width="700">
</div>

**[English](README.md)**

架空世界设定工具——从恒星系和物理定律出发，利用各学科知识进行严谨的架空世界推演。

> **在线演示：** https://fyabc.github.io/dreamulator/ 。你可以浏览已发布的世界，也可以在浏览器中创建自己的项目，不会改动发布数据。

## 特性

- **基于真实科学的世界构建** — 使用真实的天体物理和地质参数定义恒星、行星、大气层和生物圈
- **确定性模拟管线** — 引擎通过 DAG 管道，从你的创意输入计算出物理结果（轨道力学、气候、生态、文明）
- **Git 风格分支系统** — 在任意学科层（天文、地质、气候……）分叉世界，探索 "what-if" 场景而不影响主时间线
- **可复现的结果** — 种子化随机数生成器和带校验和的计算清单确保相同输入始终产生相同输出
- **自校验世界（守护轴 / Harness）** — 与模拟引擎正交的守护轴：对照引擎派生事实拷问设定、通过校验和 + 模板重渲染检测漂移、为每个设计决策保留可追溯的决策记录台账
- **3D 球面 + 恒星系** — 交互式 3D 球面地球视图（带真实地形纹理）、恒星系可视化、类似《戴森球计划》的缩小过渡特效
- **多投影 2D 地图** — 等距圆柱 / Mollweide / Robinson 投影，GPU 加速地形渲染，自适应分层设色，经纬线网格
- **AI 叙述** — 通过 Claude API 生成世界的口语化描述（`dreamulator narrate`）
- **LLM 友好架构** — 结构化的 YAML/JSON 数据、JSON Schema 验证和分层文档，最大限度减少 AI 辅助世界构建时的幻觉

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Python 3.12+, Pydantic, FastAPI, Typer |
| 科学计算 | NumPy, SciPy, Astropy |
| 前端 | TypeScript, React, Vite, Tailwind CSS |
| 3D 可视化 | Three.js (@react-three/fiber) |
| 2D 地图 | Leaflet (react-leaflet) |
| 包管理 | uv (Python), npm (Node.js) |
| AI 叙述 | Anthropic SDK (Claude API) |

## 快速开始

**先在网页里试用。** 点击「新建世界」，可以导入自己的全球高度图、使用地球示例，或从模板开始。如果希望跟着提示操作，可以在首页点击「开始教程」。静态站把你的数据存在当前浏览器里；清理站点数据或更换设备前，请先下载备份。

**需要完整构建时使用本机版。** 本机版可以调整世界参数、构建各层、将气候试算保存为正式分支、细化区域并下载完整世界备份。具体操作和两种版本的区别见[地图工作流](docs/usage/map-workflow.md#从高度图走到完整世界备份)。

### 环境要求

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)（Python 包管理器）
- Node.js 20+ 和 npm

### 安装

```bash
# 克隆仓库
git clone https://github.com/fyabc/dreamulator.git
cd dreamulator

# 安装 Python 依赖
uv sync --all-extras

# 安装前端依赖（锁定版本；`npm ci` 不会重写 package-lock.json——有意新增或
# 升级依赖时用 `npm install <package>`，审阅后提交清单与锁文件变化）
cd frontend && npm ci && cd ..
```

### 创建你的第一个世界

> 第一次使用？跟着 [新手教程](docs/usage/getting-started.md) 一步步走通完整链路。

```bash
# 创建一个类地球世界
uv run dreamulator init myworld --template earthlike

# 查看世界信息
uv run dreamulator info myworld

# 校验世界数据
uv run dreamulator validate myworld

# 列出所有世界
uv run dreamulator list

# 生成 JSON Schema
uv run dreamulator schema

# 用 Claude 生成世界的口语化描述
uv sync --extra narrate                # 安装可选依赖（仅需一次）
uv run dreamulator narrate myworld
uv run dreamulator narrate myworld --branch pangea
```

### 开发

```bash
# 终端 1: 启动 API 服务器
uv run dreamulator serve --reload

# 终端 2: 启动前端开发服务器
cd frontend && npm run dev
```

前端运行在 `http://localhost:5173`，自动将 `/api` 请求代理到 FastAPI 后端 `http://localhost:8000`。

## 项目结构与设计原则

详见 [docs/design/architecture.md](docs/design/architecture.md)。

## 开发

```bash
# 运行测试
uv run pytest

# 代码检查和格式化
uv run ruff check src/ tests/
uv run ruff format src/ tests/

# 类型检查
uv run mypy src/

# 前端
cd frontend
npx tsc --noEmit
npm run build
```

## 部署

前端支持两种部署模式，通过 `VITE_STATIC_MODE` 环境变量控制：

| 模式 | `VITE_STATIC_MODE` | 是否需要后端 | 适用场景 |
|------|--------------------|-------------|---------|
| **API 模式**（默认） | `false` | 需要 (FastAPI) | 本地开发、云服务器 (VPS) |
| **静态模式** | `true` | 不需要 | GitHub Pages、静态托管 |

### 静态站点（GitHub Pages）

静态站不需要后端。支持的已发布地图和用户从高度图创建的世界都可以在浏览器运行并保存能量平衡气候试算。想把自建世界的试算用作细化条件时，先打开已保存的试算，再选取区域。地形扩散（TD）细化需要站点配置模型，并使用支持硬件 WebGPU 的浏览器。完整世界构建、正式分支和 AI 叙述需要本机版。模型配置见[静态站的浏览器细化](docs/usage/map-workflow.md#静态站的浏览器细化)。

```bash
cd frontend

# 1. 导出静态站使用的世界数据
uv run python ../scripts/release/export_static.py

# 2. 以静态模式构建（使用 .env.static 中的 base path）
npx vite build --mode static

# 3. dist/ 目录可部署到任意静态托管服务
```

或使用合并脚本：

```bash
cd frontend && npm run build:static
```

**本地预览**静态构建结果（`build:static:local` 会自动先运行静态导出）：

```bash
cd frontend
npm run build:static:local    # 导出全部世界 + 类型检查 + 以 base path '/' 构建
npm run preview:static        # 在 http://localhost:8026 提供服务
```

打开 `http://localhost:8026/#/worlds/earth/map/planet_earth`，确认地图能加载、所需资源没有返回 404。快速迭代时，可在仓库根目录运行 `uv run python scripts/release/export_static.py --worlds earth`，只导出地球世界。

**GitHub Pages 部署**已通过 GitHub Actions 自动化（`.github/workflows/deploy-pages.yml`）。推送到 `main` 分支后，在仓库设置中启用 Pages（Source: GitHub Actions）即可。

> **注意**：`.env.static` 中的默认 base path 为 `/dreamulator/`——请根据你的仓库名修改，或通过环境变量设置 `VITE_BASE_PATH`。

### 云服务器（全栈部署）

如需完整功能的部署（所有操作均可用），使用普通构建 + Nginx 反向代理：

```bash
# 构建前端（API 模式）
cd frontend && npm run build

# 启动后端（同时提供 API 和前端静态文件）
uv run dreamulator serve
```

详见 `docs/usage/cli.md` 中的部署选项与 `dreamulator serve` 命令。

## 文档

| 文档 | 说明 |
|------|------|
| [新手教程](docs/usage/getting-started.md) | 零基础完整链路：创建世界 → 设参数 → 构建 → 查看 → 出图 |
| [CLI 命令参考](docs/usage/cli.md) | 全部 CLI 命令 (init/build/branch/climate/narrate/serve…) |
| [地图工作流](docs/usage/map-workflow.md) | CVT 网格地形生成 → 查看器检查 → Gaea 精细化 |
| [气候验证工作流](docs/usage/climate-validation-workflow.md) | 真实地球观测数据导入、多数据集验证、回归测试体系 |
| [性能分析工作流](docs/design/profiling.md) | 构建耗时档案、py-spy 火焰图、CI 基准；[优化记录](docs/design/performance-optimizations.md) |
| [文明地图指南](docs/usage/civmap-guide.md) | 真实地球底图、架空国家涂色、时间快照 |
| [3D 可视化器](docs/usage/frontend-3d-viewer.md) | 恒星系视图 + 球面地球操作指南 |
| [架构设计](docs/design/architecture.md) | 项目架构、层级系统、分支管理、input/derived 分离 |
| [守护轴 / Harness](docs/design/proposals/harness.md) | 校验、审计与设定维护：与模拟引擎正交的守护轴 |
| [地形管线](docs/design/pipelines/geological-pipeline.md) | 12 阶段算法、Cortial 2019 板块剖分、geography.yaml 锚定 |
| [气候引擎](docs/design/pipelines/climate-pipeline.md) | 1D 谱解 EBM + Hadley 环流 + 质量守恒水汽预算 + 季风动力学 + Köppen 分类 |

## 路线图

**当前状态**：Phase 1–2.5 已完成（项目骨架、CLI、3D/2D 可视化、地形真实感增强）；Phase 3A 气候引擎核心已合并、精度调优进行中（1D EBM、季节模型、质量守恒水汽预算、季风动力学、月度场、对照 Beck 2018 的真实地球验证）；守护轴 Harness 已实现（`dreamulator guard` CLI + API）；河网已落地、流水侵蚀转局地高清精修（3B）。后续方向：文明半格式化管理（3C）、世界线 Diff（3D）、LLM 叙事桥（3E）。

完整路线图、竞品分析与设计参考见 [docs/design/roadmap.md](docs/design/roadmap.md)；项目长期愿景见 [docs/design/proposals/vision.md](docs/design/proposals/vision.md)。

## 许可证

MIT
