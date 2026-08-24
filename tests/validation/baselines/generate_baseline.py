#!/usr/bin/env python3
"""Generate a climate validation baseline snapshot for a world.

Usage::

    # Generate baseline for nacrea 200k (from committed data/worlds/)
    uv run python tests/validation/baselines/generate_baseline.py nacrea

    # With custom planet ID and data dir
    uv run python tests/validation/baselines/generate_baseline.py nacrea \\
        --planet satellite_nacrea --data-dir private/worlds

    # Specify output path
    uv run python tests/validation/baselines/generate_baseline.py nacrea \\
        --output tests/validation/baselines/nacrea-200k.json

The generated JSON snapshot is committed to the repo and used by
``tests/validation/test_regression.py`` as the regression gate.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_project_root() -> Path:
    d = Path(__file__).resolve().parent
    while d != d.parent:
        if (d / "pyproject.toml").exists():
            return d
        d = d.parent
    return Path.cwd()


def _load_mesh(world_dir: Path, planet_id: str) -> dict | None:
    """Load CVT mesh JSON from a world's maps/ directory."""
    mesh_path = world_dir / "maps" / planet_id / "cvt_mesh.json"
    if not mesh_path.exists():
        print(f"ERROR: Mesh not found at {mesh_path}", file=sys.stderr)
        return None
    from dreamulator.map.export import decompress_mesh_bytes

    return json.loads(decompress_mesh_bytes(mesh_path.read_bytes()))  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a climate validation baseline snapshot",
    )
    parser.add_argument("world", help="World name (e.g. 'nacrea')")
    parser.add_argument(
        "--planet",
        default="satellite_nacrea",
        help="Planet ID within the world",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="RNG seed for climate simulation",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output path (default: tests/validation/baselines/<world>-<cells>.json)",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Custom worlds data directory",
    )
    # Climate parameter overrides (read from world config if available)
    parser.add_argument("--stellar-luminosity-sol", type=float, default=None)
    parser.add_argument("--orbital-distance-au", type=float, default=None)
    parser.add_argument("--axial-tilt-deg", type=float, default=None)
    parser.add_argument("--greenhouse-warming-K", type=float, default=None)
    parser.add_argument("--rotation-period-days", type=float, default=None)
    parser.add_argument("--albedo", type=float, default=None)
    args = parser.parse_args()

    project_root = _find_project_root()
    baselines_dir = project_root / "tests" / "validation" / "baselines"

    # Resolve world directory
    if args.data_dir:
        world_dir = project_root / args.data_dir / args.world
    else:
        world_dir = project_root / "data" / "worlds" / args.world
        if not world_dir.exists():
            world_dir = project_root / "private" / "worlds" / args.world

    if not world_dir.exists():
        print(f"ERROR: World directory not found: {world_dir}", file=sys.stderr)
        sys.exit(1)

    # Load the pre-built CVT mesh
    mesh_data = _load_mesh(world_dir, args.planet)
    if mesh_data is None:
        sys.exit(1)

    num_cells = mesh_data.get("num_cells", len(mesh_data.get("cells", [])))
    print(f"Loading CVT mesh: {num_cells:,} cells from {world_dir}")

    from dreamulator.map.models import CVTMesh

    mesh = CVTMesh(**mesh_data)

    # Run climate simulation
    print("Running climate simulation...")
    from dreamulator.map.climate_simulator import simulate_climate
    from dreamulator.map.pipeline_types import TerrainPipelineConfig

    # Load climate configuration from terrain_config.yaml (respects world-specific
    # tuning: auto_lat_gradient, Hadley/polar cell boundaries, ice-albedo
    # feedback, etc.).  Fall back to defaults when the file is missing.
    _terrain_cfg_path = world_dir / "layers" / "geological" / "input" / "terrain_config.yaml"
    if _terrain_cfg_path.exists():
        config = TerrainPipelineConfig.from_yaml(_terrain_cfg_path)
        print(f"  Loaded climate config from {_terrain_cfg_path}")
    else:
        config = TerrainPipelineConfig()
        print("  WARNING: terrain_config.yaml not found, using Earth defaults")

    # Override physical parameters with world-specific resolved values.
    #  - map.yaml        → planet radius
    #  - climate_metadata.json → stellar/orbital/atmosphere (post-resolution)
    #  - CLI args         → manual overrides
    radius_km = float(mesh_data.get("radius_km", 6371.0))
    map_yaml_path = world_dir / "maps" / args.planet / "map.yaml"
    if map_yaml_path.exists():
        import yaml as _yaml

        with map_yaml_path.open("r", encoding="utf-8") as _f:
            _map_meta = _yaml.safe_load(_f) or {}
        radius_km = float(_map_meta.get("radius_km", radius_km))

    climate_meta_path = world_dir / "maps" / args.planet / "climate_metadata.json"
    if climate_meta_path.exists():
        with climate_meta_path.open("r", encoding="utf-8") as _f:
            _cm = json.load(_f)
        for _k in (
            "stellar_luminosity_sol",
            "orbital_distance_au",
            "orbital_period_days",
            "axial_tilt_deg",
            "greenhouse_warming_K",
            "rotation_period_days",
            "eccentricity",
        ):
            if _k in _cm:
                setattr(config, _k, float(_cm[_k]))
        if "albedo" in _cm:
            config.albedo = float(_cm["albedo"])

    # Apply CLI overrides (highest priority)
    if args.stellar_luminosity_sol is not None:
        config.stellar_luminosity_sol = args.stellar_luminosity_sol
    if args.orbital_distance_au is not None:
        config.orbital_distance_au = args.orbital_distance_au
    if args.axial_tilt_deg is not None:
        config.axial_tilt_deg = args.axial_tilt_deg
    if getattr(args, "greenhouse_warming_K", None) is not None:
        config.greenhouse_warming_K = args.greenhouse_warming_K
    if args.rotation_period_days is not None:
        config.rotation_period_days = args.rotation_period_days
    if args.albedo is not None:
        config.albedo = args.albedo

    config.seed = args.seed
    config.radius_km = radius_km
    config.num_nodes = num_cells

    simulate_climate(mesh, config)
    print("  Done.")

    # Collect metrics
    from collections import Counter

    import numpy as np

    temps = np.array([c.temperature_C for c in mesh.cells if c.temperature_C is not None])
    precip = np.array([c.precipitation_mm for c in mesh.cells if c.precipitation_mm is not None])
    elev = np.array([c.elevation for c in mesh.cells])
    land_mask = elev >= 0.0

    koppen_counts: Counter[str] = Counter()
    for c in mesh.cells:
        if land_mask[c.id] and c.koppen_class and c.koppen_class != "Ocean":
            koppen_counts[c.koppen_class] += 1
    total_land = sum(koppen_counts.values())

    # Köppen group distribution
    group_counts: Counter[str] = Counter()
    for k, v in koppen_counts.items():
        group_counts[k[0]] += v

    report = {
        "schema_version": 1,
        "world": args.world,
        "planet": args.planet,
        "seed": args.seed,
        "mesh_cells": num_cells,
        "temperature": {
            "global_mean_c": round(float(np.nanmean(temps)), 2),
            "land_mean_c": round(
                float(np.nanmean(temps[land_mask])) if land_mask.any() else float("nan"), 2
            ),
            "ocean_mean_c": round(
                float(np.nanmean(temps[~land_mask])) if (~land_mask).any() else float("nan"),
                2,
            ),
            "min_c": round(float(np.nanmin(temps)), 2),
            "max_c": round(float(np.nanmax(temps)), 2),
        },
        "precipitation": {
            "global_mean_mm": round(float(np.nanmean(precip)), 1),
            "land_mean_mm": round(
                float(np.nanmean(precip[land_mask])) if land_mask.any() else float("nan"), 1
            ),
        },
        "koppen": {
            "class_counts": dict(sorted(koppen_counts.items())),
            "group_distribution": {
                g: round(group_counts.get(g, 0) / max(total_land, 1), 3) for g in "ABCDE"
            },
            "n_classes": len(koppen_counts),
            "n_land_cells": total_land,
        },
        "land_fraction": round(float(land_mask.sum() / len(land_mask)), 4),
    }

    # Determine output path
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = baselines_dir / f"{args.world}-{num_cells // 1000}k.json"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"\nBaseline saved to: {output_path}")
    print(f"  Temperature mean: {report['temperature']['global_mean_c']} C")
    print(f"  Precipitation mean: {report['precipitation']['global_mean_mm']} mm/yr")
    print(f"  Koppen classes: {report['koppen']['n_classes']}")
    print(f"  Land fraction: {report['land_fraction']:.1%}")


if __name__ == "__main__":
    main()
