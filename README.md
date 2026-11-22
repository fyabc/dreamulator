# Dreamulator

<div align="center">
  <img src="docs/images/logo.png" alt="Dreamulator logo" width="700">
</div>

**[中文文档](README.zh-CN.md)**

A fantasy world building and simulation tool grounded in real science. Starting from stellar systems and physical laws, Dreamulator leverages knowledge across scientific disciplines to rigorously design and simulate fictional worlds.

> **Live Demo:** https://fyabc.github.io/dreamulator/ — Explore published worlds or create a project in your browser without changing the published data.

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

**Start in the browser.** Select **New World** to import a global heightmap, use the Earth sample, or start from a template. For a guided walkthrough, choose **Start tutorial** on the home page. The static site keeps your work in your browser, so download a backup before clearing site data or moving to another device.

**Use the local app for a full build.** The local app lets you set world parameters, build the layers, save a climate trial as a branch, refine a region, and back up the entire world. See the [complete map workflow](docs/usage/map-workflow.md#从高度图走到完整世界备份) for the steps and the differences between the two modes.

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- Node.js 20+ and npm

### Installation

```bash
# Clone the repository
git clone https://github.com/fyabc/dreamulator.git
cd dreamulator

# Install Python dependencies
uv sync --all-extras

# Install frontend dependencies (locked versions; `npm ci` does not rewrite
# package-lock.json — use `npm install <package>` when intentionally adding
# or upgrading dependencies, then review and commit the lockfile changes)
cd frontend && npm ci && cd ..
```

### Create Your First World

> New here? Follow the step-by-step tutorial: [Getting Started](docs/usage/getting-started.md) (中文).

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

The static site needs no backend. You can run and save an energy-balance climate trial on supported published maps or on a world you created from a heightmap. On your own world, open the saved trial before selecting a region to use that climate for refinement. Terrain Diffusion requires a configured model and a browser with hardware WebGPU support. Full world builds, official branches, and AI narration require the local app. See [browser terrain refinement](docs/usage/map-workflow.md#静态站的浏览器细化) for model setup.

```bash
cd frontend

# 1. Export world data for the static site
uv run python ../scripts/release/export_static.py

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
npm run preview:static        # serves dist/ at http://localhost:8026
```

Open `http://localhost:8026/#/worlds/earth/map/planet_earth` and check that the map loads without missing assets. For quick iteration, export just one world with `uv run python scripts/release/export_static.py --worlds earth` from the repository root.

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
| [Getting Started](docs/usage/getting-started.md) | Step-by-step tutorial: create a world, set parameters, build, view, export (中文) |
| [CLI Reference](docs/usage/cli.md) | All CLI commands (init/build/branch/climate/narrate/serve…) |
| [Map Workflow](docs/usage/map-workflow.md) | CVT mesh terrain generation → viewer inspection → Gaea refinement |
| [Climate Validation](docs/usage/climate-validation-workflow.md) | Real-Earth observation data import, multi-dataset validation, regression test suite |
| [ExoPlaSim GCM](docs/usage/exoplasim-gcm.md) | Running the ExoPlaSim GCM as an offline reference for the climate engine (setup, land mask, run, diagnostics) |
| [Profiling](docs/design/profiling.md) | Build timing profiles, py-spy flamegraphs, CI benchmarks; [optimization log](docs/design/performance-optimizations.md) |
| [CivMap Guide](docs/usage/civmap-guide.md) | Real-Earth basemap, fictional territory coloring, temporal snapshots |
| [3D Viewer](docs/usage/frontend-3d-viewer.md) | Star system view + globe interaction guide |
| [Architecture](docs/design/architecture.md) | Project architecture, layer system, branching, input/derived separation |
| [Harness / Guard Axis](docs/design/proposals/harness.md) | Validation, audit, and setting-maintenance: the guard axis orthogonal to the simulation engine |
| [Terrain Pipeline](docs/design/pipelines/geological-pipeline.md) | 12-stage algorithm, Cortial 2019 plate partitioning, geography.yaml anchoring |
| [Climate Engine](docs/design/pipelines/climate-pipeline.md) | 1D spectral EBM + Hadley circulation + mass-conserving moisture budget + monsoon dynamics + Köppen classification |

## Roadmap

**Current status**: Phases 1–2.5 complete (scaffolding, CLI, 3D/2D visualization, terrain realism enhancement); Phase 3A climate engine core merged and under accuracy tuning (1D EBM, seasonal model, mass-conserving moisture budget, monsoon dynamics, monthly fields, real-Earth validation against Beck 2018); the Harness guard axis is implemented (`dreamulator guard` CLI + API). River networks landed with fluvial erosion deferred to local high-res refinement (3B). Up next: civilization semi-structured modeling (3C), world-line diff visualization (3D), LLM narrative bridge (3E).

See [docs/design/roadmap.md](docs/design/roadmap.md) for the full roadmap, competitive analysis and design references, and [docs/design/proposals/vision.md](docs/design/proposals/vision.md) for the project's long-term vision and design philosophy.

## License

MIT
