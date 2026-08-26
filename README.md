# Dreamulator

<div align="center">
  <img src="docs/images/logo.png" alt="Dreamulator logo" width="700">
</div>

**[中文文档](README.zh-CN.md)**

A fantasy world building and simulation tool grounded in real science. Starting from stellar systems and physical laws, Dreamulator leverages knowledge across scientific disciplines to rigorously design and simulate fictional worlds.

> **Live Demo:** https://fyabc.github.io/dreamulator/ (read-only static version — world creation, simulation, and AI narration are disabled)

## Features

- **Science-based world building** — Define stars, planets, atmospheres, and biospheres using real astrophysical and geological parameters
- **Deterministic simulation pipeline** — Engines compute physical consequences from your creative inputs via a DAG-based pipeline
- **Git-style branching** — Fork worlds at any layer (astronomy, geology, climate...) and explore "what-if" scenarios without affecting the main timeline
- **Reproducible results** — Seeded RNG and checksum-tracked manifests ensure identical inputs always produce identical outputs
- **Self-verifying worlds (Harness)** — A guard axis orthogonal to the simulation engine: cross-examine settings against engine-derived facts, detect drift via checksums + template re-render, and keep a traceable decision-record ledger of every design decision
- **3D globe & star system** — Interactive 3D globe view with terrain textures, star system visualization, and a Dyson-Sphere-Program-style zoom-out transition between planet and system views
- **Multi-projection 2D maps** — Equirectangular / Mollweide / Robinson projections with GPU-accelerated terrain rendering, adaptive hypsometric coloring, and graticule overlays
- **AI narration** — Generate conversational descriptions of your worlds via the Claude API (`dreamulator narrate`)
- **LLM-friendly architecture** — Structured YAML/JSON data, JSON Schema validation, and hierarchical documentation minimize hallucinations during AI-assisted world building

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

See [docs/design/architecture.md](docs/design/architecture.md).

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

**Local preview** of the static build (`build:static:local` runs the static export automatically):

```bash
cd frontend
npm run build:static:local    # export all worlds + typecheck + build with base path '/'
npm run preview:static        # serves dist/ at http://localhost:4173
```

Open e.g. `http://localhost:4173/#/worlds/earth/map?branch=terrain-dev` to verify maps and other features (check the console for 404s). For quick iteration, export a single world only: `uv run python scripts/export_static.py --worlds earth` (from the repo root).

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

See `docs/usage/cli.md` for deployment options and the `dreamulator serve` command.

## Documentation

| Document | Description |
|----------|-------------|
| [CLI Reference](docs/usage/cli.md) | All CLI commands (init/build/branch/climate/narrate/serve…) |
| [Map Workflow](docs/usage/map-workflow.md) | CVT mesh terrain generation → viewer inspection → Gaea refinement |
| [Climate Validation](docs/usage/climate-validation-workflow.md) | Real-Earth observation data import, multi-dataset validation, regression test suite |
| [Profiling](docs/usage/profiling.md) | Build timing profiles, py-spy flamegraphs, Scalene, CI benchmarks; [optimization log](docs/usage/performance-optimizations.md) |
| [CivMap Guide](docs/usage/civmap-guide.md) | Real-Earth basemap, fictional territory coloring, temporal snapshots |
| [3D Viewer](docs/usage/frontend-3d-viewer.md) | Star system view + globe interaction guide |
| [Architecture](docs/design/architecture.md) | Project architecture, layer system, branching, input/derived separation |
| [Harness / Guard Axis](docs/design/harness.md) | Validation, audit, and setting-maintenance: the guard axis orthogonal to the simulation engine |
| [Terrain Pipeline](docs/design/terrain-pipeline.md) | 12-stage algorithm, Cortial 2019 plate partitioning, geography.yaml anchoring |
| [Climate Engine](docs/design/climate-engine.md) | EBM + three-cell circulation + BFS moisture + Köppen classification |

## Roadmap

**Current status**: Phases 1–2.5 complete (scaffolding, CLI, 3D/2D visualization, terrain realism enhancement); Phase 3A climate engine core merged (EBM, three-cell wind belts, orographic precipitation, Köppen classification, seasonality module, real-Earth validation) with accuracy tuning in progress. Up next: erosion & rivers (3B), civilization semi-structured modeling (3C), world-line diff visualization (3D), LLM narrative bridge (3E), and the Harness guard axis (validation / audit / setting-maintenance).

See [docs/design/roadmap.md](docs/design/roadmap.md) for the full roadmap, competitive analysis and design references, and [docs/design/vision.md](docs/design/vision.md) for the project's long-term vision and design philosophy.

## License

MIT
