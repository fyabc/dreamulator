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

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Python 3.12+, Pydantic, FastAPI, Typer |
| 科学计算 | NumPy, SciPy, Astropy |
| 前端 | TypeScript, React, Vite, Tailwind CSS |
| 3D 可视化 | Three.js (@react-three/fiber) |
| 2D 地图 | Leaflet (react-leaflet) |
| 包管理 | uv (Python), npm (Node.js) |

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
```

### 开发

```bash
# 终端 1: 启动 API 服务器
uv run dreamulator serve --reload

# 终端 2: 启动前端开发服务器
cd frontend && npm run dev
```

前端运行在 `http://localhost:5173`，自动将 `/api` 请求代理到 FastAPI 后端 `http://localhost:8000`。

## 项目结构

```
dreamulator/
├── docs/
│   ├── knowledge/           # 各学科科学知识参考文档
│   ├── worldbuilding/       # 架空世界创建思路与方法论
│   └── usage/               # 项目用法指南
├── data/
│   ├── templates/           # 世界模板（minimal, earthlike）
│   └── worlds/              # 世界实例
├── schemas/                 # 自动生成的 JSON Schema
├── src/dreamulator/         # Python 后端
│   ├── models/              # Pydantic 数据模型
│   ├── engine/              # 模拟引擎（DAG pipeline）
│   ├── io/                  # 文件读写层
│   ├── api.py               # FastAPI 应用
│   ├── cli.py               # Typer CLI 入口
│   └── utils/               # 物理常量、单位换算、随机数
├── frontend/                # TypeScript SPA（Vite + React）
│   └── src/
│       ├── api/             # API 客户端
│       ├── components/      # UI 组件
│       ├── pages/           # 页面组件
│       └── stores/          # Zustand 状态管理
└── tests/                   # Python 测试
```

## 核心设计原则

### 输入/衍生分离

每个世界目录严格分离：
- **`input/`**（YAML）— 人类或 LLM 编写的创意设定（恒星类型、行星大小、文明种子等）
- **`derived/`**（JSON）— 引擎计算的物理结果（光度、温度、气候带、生态系统等）

LLM 只修改 input，引擎负责计算 derived——防止 LLM "幻想"物理结果。

### 可复现性

- 所有引擎使用种子化随机数生成器（`numpy.random.Generator`）
- 计算清单（manifest）记录每步的输入/输出校验和
- 相同输入 + 种子 = 相同输出

### 引擎管道

```
stellar → orbital → geological + climate → ecology → civilization
```

引擎继承 `BaseEngine`，声明依赖（`requires`）、输入文件（`input_files`）和输出文件（`output_files`），由 `engine/pipeline.py` 自动拓扑排序并按顺序执行。

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

## 路线图

- [x] **Phase 1** — 项目骨架、数据模型、CLI、世界管理、前端骨架
- [ ] **Phase 2** — 模拟引擎实现 + 学科知识库文档
- [ ] **Phase 3** — 前端可视化（3D 恒星系、多层 2D 地图）

## 许可证

MIT
