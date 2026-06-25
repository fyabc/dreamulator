# Dreamulator

<div align="center">
  <img src="docs/images/logo.png" alt="Dreamulator logo" width="700">
</div>

**[English](README.md)**

架空世界设定工具——从恒星系和物理定律出发，利用各学科知识进行严谨的架空世界推演。

## 特性

- **基于真实科学的世界构建** — 使用真实的天体物理和地质参数定义恒星、行星、大气层和生物圈
- **确定性模拟管线** — 引擎通过 DAG 管道，从你的创意输入计算出物理结果（轨道力学、气候、生态、文明）
- **可复现的结果** — 种子化随机数生成器和带校验和的计算清单确保相同输入始终产生相同输出
- **LLM 友好架构** — 结构化的 YAML/JSON 数据、JSON Schema 验证和分层 `CLAUDE.md` 文档，最大限度减少 AI 辅助世界构建时的幻觉
- **命令行 + Web 界面** — 通过命令行管理世界，或通过 TypeScript SPA 前端探索世界（3D 恒星系可视化 + 多层 2D 地图）
- **AI 叙述** — 通过 Claude API 生成世界的口语化描述（`dreamulator narrate`）

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

### 环境要求

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)（Python 包管理器）
- Node.js 18+ 和 npm

### 安装

```bash
# 克隆仓库
git clone https://github.com/your-username/dreamulator.git
cd dreamulator

# 安装 Python 依赖
uv sync --all-extras

# 安装前端依赖
cd frontend && npm install && cd ..
```

### 创建你的第一个世界

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

详见 [docs/usage/project-structure.md](docs/usage/project-structure.md)。

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

静态模式在构建时将所有世界数据预导出为 JSON。生成的站点为只读——创建世界、运行引擎、AI 叙述等功能不可用。

```bash
cd frontend

# 1. 将世界数据导出为静态 JSON
python ../scripts/export_static.py

# 2. 以静态模式构建（使用 .env.static 中的 base path）
npx vite build --mode static

# 3. dist/ 目录可部署到任意静态托管服务
```

或使用合并脚本：

```bash
cd frontend && npm run build:static
```

**本地预览**静态构建结果：

```bash
cd frontend
npm run build:static:local    # 以 base path '/' 构建
npm run preview:static         # 在 http://localhost:4173 提供服务
```

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

详见 `private/plans/deploy-plan-b-china-cloud.md` 中的 Docker + Nginx 部署指南。

## 路线图

- [x] **Phase 1** — 项目骨架、数据模型、CLI、世界管理、前端骨架
- [ ] **Phase 2** — 模拟引擎实现 + 学科知识库文档
- [ ] **Phase 3** — 前端可视化（3D 恒星系、多层 2D 地图）

## 许可证

MIT
