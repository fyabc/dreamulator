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

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12+, Pydantic, FastAPI, Typer |
| Scientific computing | NumPy, SciPy, Astropy |
| Frontend | TypeScript, React, Vite, Tailwind CSS |
| 3D visualization | Three.js via @react-three/fiber |
| 2D maps | Leaflet via react-leaflet |
| Package management | uv (Python), npm (Node.js) |

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
```

### Development

```bash
# Terminal 1: Start the API server
uv run dreamulator serve --reload

# Terminal 2: Start the frontend dev server
cd frontend && npm run dev
```

The frontend runs at `http://localhost:5173` and proxies `/api` requests to the FastAPI backend at `http://localhost:8000`.

## Project Structure

```
dreamulator/
├── docs/
│   ├── knowledge/           # Scientific reference docs by discipline
│   ├── worldbuilding/       # World building methodology
│   └── usage/               # Usage guides
├── data/
│   ├── templates/           # World templates (minimal, earthlike)
│   └── worlds/              # World instances
├── schemas/                 # Auto-generated JSON Schemas
├── src/dreamulator/         # Python backend
│   ├── models/              # Pydantic data models
│   ├── engine/              # Simulation engines (DAG pipeline)
│   ├── io/                  # File I/O layer
│   ├── api.py               # FastAPI application
│   ├── cli.py               # Typer CLI
│   └── utils/               # Constants, units, RNG
├── frontend/                # TypeScript SPA (Vite + React)
│   └── src/
│       ├── api/             # API client
│       ├── components/      # UI components
│       ├── pages/           # Page components
│       └── stores/          # Zustand state management
└── tests/                   # Python tests
```

## Core Design Principles

### Input / Derived Separation

Each world directory strictly separates:
- **`input/`** (YAML) — Creative settings authored by humans or LLMs
- **`derived/`** (JSON) — Physical results computed by engines

LLMs only modify inputs; engines compute derived data — preventing AI "hallucinations" of physical results.

### Reproducibility

- All engines use seeded RNG (`numpy.random.Generator`)
- Computation manifests record checksums for every step
- Same inputs + seed = same outputs

### Engine Pipeline

```
stellar → orbital → geological + climate → ecology → civilization
```

Engines inherit from `BaseEngine`, declaring dependencies (`requires`), `input_files`, and `output_files`. The pipeline runner (`engine/pipeline.py`) performs topological sorting and executes in order.

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

## Roadmap

- [x] **Phase 1** — Project scaffolding, data models, CLI, world management, frontend skeleton
- [ ] **Phase 2** — Simulation engines + knowledge base documents
- [ ] **Phase 3** — Frontend visualization (3D star system, multi-layer 2D maps)

## License

MIT
