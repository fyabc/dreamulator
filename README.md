# Dreamulator

<div align="center">
  <img src="docs/images/logo.png" alt="Dreamulator logo" width="700">
</div>

**[中文文档](README.zh-CN.md)**

A fantasy world building and simulation tool grounded in real science. Starting from stellar systems and physical laws, Dreamulator leverages knowledge across scientific disciplines to rigorously design and simulate fictional worlds.

## Features

- **Science-based world building** — Define stars, planets, atmospheres, and biospheres using real astrophysical and geological parameters
- **Deterministic simulation pipeline** — Engines compute physical consequences (orbital mechanics, climate, ecology, civilizations) from your creative inputs via a DAG-based pipeline
- **Reproducible results** — Seeded RNG and checksum-tracked computation manifests ensure the same inputs always produce the same outputs
- **LLM-friendly architecture** — Structured YAML/JSON data, JSON Schema validation, and hierarchical `CLAUDE.md` documentation minimize hallucinations during AI-assisted world building
- **CLI + Web UI** — Manage worlds from the command line or explore them through a TypeScript SPA frontend with 3D star system visualization and multi-layer 2D maps
- **AI narration** — Generate conversational descriptions of your worlds via the Claude API (`dreamulator narrate`)

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12+, Pydantic, FastAPI, Typer |
| Scientific computing | NumPy, SciPy, Astropy |
| Frontend | TypeScript, React, Vite, Tailwind CSS |
| 3D visualization | Three.js via @react-three/fiber |
| 2D maps | Leaflet via react-leaflet |
| Package management | uv (Python), npm (Node.js) |
| AI narration | Anthropic SDK (Claude API) |

## Quick Start

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- Node.js 18+ and npm

### Installation

```bash
# Clone the repository
git clone https://github.com/your-username/dreamulator.git
cd dreamulator

# Install Python dependencies
uv sync --all-extras

# Install frontend dependencies
cd frontend && npm install && cd ..
```

### Create Your First World

```bash
# Create a new Earth-like world
uv run dreamulator init myworld --template earthlike

# View world information
uv run dreamulator info myworld

# Validate world data
uv run dreamulator validate myworld

# List all worlds
uv run dreamulator list

# Generate JSON schemas
uv run dreamulator schema

# Generate a conversational world description using Claude
uv sync --extra narrate                # install optional dependency (one-time)
uv run dreamulator narrate myworld
uv run dreamulator narrate myworld --branch pangea
```

### Development

```bash
# Terminal 1: Start the API server
uv run dreamulator serve --reload

# Terminal 2: Start the frontend dev server
cd frontend && npm run dev
```

The frontend runs at `http://localhost:5173` and proxies `/api` requests to the FastAPI backend at `http://localhost:8000`.

## Project Structure & Design Principles

See [docs/usage/project-structure.md](docs/usage/project-structure.md).

## Development

```bash
# Run tests
uv run pytest

# Lint and format
uv run ruff check src/ tests/
uv run ruff format src/ tests/

# Type check
uv run mypy src/

# Frontend
cd frontend
npx tsc --noEmit
npm run build
```

## Deployment

The frontend supports two deployment modes controlled by the `VITE_STATIC_MODE` environment variable:

| Mode | `VITE_STATIC_MODE` | Backend required | Use case |
|------|--------------------|------------------|----------|
| **API mode** (default) | `false` | Yes (FastAPI) | Local dev, cloud server (VPS) |
| **Static mode** | `true` | No | GitHub Pages, static hosting |

### Static site (GitHub Pages)

The static mode pre-exports all world data as JSON at build time. The resulting site is read-only — world creation, simulation, and AI narration are disabled.

```bash
cd frontend

# 1. Export world data to static JSON
python ../scripts/export_static.py

# 2. Build with static mode (uses .env.static for base path)
npx vite build --mode static

# 3. The output in dist/ can be deployed to any static host
```

Or use the combined script:

```bash
cd frontend && npm run build:static
```

**Local preview** of the static build:

```bash
cd frontend
npm run build:static:local    # builds with base path '/'
npm run preview:static         # serves dist/ at http://localhost:4173
```

**GitHub Pages deployment** is automated via GitHub Actions (`.github/workflows/deploy-pages.yml`). Push to `main` and enable Pages in repository settings (Source: GitHub Actions).

> **Note:** The default base path in `.env.static` is `/dreamulator/` — update it to match your repository name, or set `VITE_BASE_PATH` in your environment.

### Cloud server (full-stack)

For a full-featured deployment with all operations available, build normally and serve behind Nginx:

```bash
# Build frontend (API mode)
cd frontend && npm run build

# Start backend (serves both API and frontend dist/)
uv run dreamulator serve
```

See `private/plans/deploy-plan-b-china-cloud.md` for a detailed Docker + Nginx deployment guide.

## Roadmap

- [x] **Phase 1** — Project scaffolding, data models, CLI, world management, frontend skeleton
- [x] **Phase 2** — Frontend visualization (3D star system, multi-layer 2D maps)
- [ ] **Phase 3** — Simulation engines + knowledge base documents

## License

MIT
