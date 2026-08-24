#!/usr/bin/env python3
"""Spatial Köppen accuracy diagnostic — by lat/lon grid with polar merging.

Runs the climate engine on the Earth (baseline) mesh, compares the simulated
Köppen class against the Beck et al. (2018) per-cell reference, and reports the
accuracy broken down by a latitude/longitude grid.  The two polar caps
(|lat| > 60°) are merged across longitude (longitude is ill-defined near the
poles), while the rest of the globe is split into regular lon bins.

This is a diagnostic for distinguishing *engine bugs* (systematic biases that
appear on the Earth baseline too) from *world-specific parameter tuning* (issues
that only appear on non-Earth worlds like nacrea).

Usage::

    uv run python scripts/diagnose_koppen_spatial.py
    uv run python scripts/diagnose_koppen_spatial.py --lat-band 15 --lon-bin 30
    uv run python scripts/diagnose_koppen_spatial.py --polar-bound 66.5
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np


def _find_project_root() -> Path:
    d = Path(__file__).resolve().parent.parent
    return d


def _load_mesh(world_dir: Path, planet_id: str, branch: str | None = None) -> dict | None:
    from pydantic import TypeAdapter

    from dreamulator.map.models import CVTMesh

    search_dirs = [world_dir]
    if branch:
        search_dirs.insert(0, world_dir / "branches" / branch)
    for base in search_dirs:
        mesh_path = base / "maps" / planet_id / "cvt_mesh.json"
        if mesh_path.exists():
            from dreamulator.map.export import decompress_mesh_bytes

            return TypeAdapter(CVTMesh).validate_json(decompress_mesh_bytes(mesh_path.read_bytes()))
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--world", default="earth")
    parser.add_argument("--planet", default="planet_earth")
    parser.add_argument(
        "--branch", default="climate-dev", help="branch whose mesh matches koppen_obs.json"
    )
    parser.add_argument("--lat-band", type=float, default=15.0)
    parser.add_argument("--lon-bin", type=float, default=30.0)
    parser.add_argument("--polar-bound", type=float, default=60.0)
    parser.add_argument("--top", type=int, default=10, help="number of best/worst bins to show")
    args = parser.parse_args()

    root = _find_project_root()
    world_dir = root / "data" / "worlds" / args.world

    print(f"Loading Earth mesh from {world_dir} (branch={args.branch}) ...")
    mesh = _load_mesh(world_dir, args.planet, args.branch)
    if mesh is None:
        print(f"  ERROR: no mesh at {world_dir}/maps/{args.planet}/cvt_mesh.json")
        return

    # Run the climate engine on the Earth baseline
    print(f"Running climate engine on {mesh.num_cells} cells ...")
    from dreamulator.map.climate_simulator import simulate_climate
    from dreamulator.validate_climate import build_earth_validation_config

    config = build_earth_validation_config(mesh.num_cells)
    simulate_climate(mesh, config)

    # Load Beck 2018 reference
    obs_path = world_dir / "branches" / args.branch / "maps" / args.planet / "koppen_obs.json"
    if not obs_path.exists():
        print(f"  ERROR: koppen_obs.json not found at {obs_path}")
        return
    with obs_path.open("r", encoding="utf-8") as f:
        obs_cells = json.load(f).get("cells", {})

    # Aggregate accuracy per grid bin
    # bin: (lat_band, lon_bin) for non-polar; ("N polar"/"S polar", None) for polar caps
    stats: dict[tuple, list[int]] = {}  # (lat_lo, lon_lo) -> [match, total]

    for c in mesh.cells:
        obs = obs_cells.get(str(c.id), "N/A")
        sim = c.koppen_class or "Ocean"
        if obs == "N/A" or sim == "Ocean":
            continue

        lat = c.lat
        if abs(lat) > args.polar_bound:
            key = ("N polar" if lat > 0 else "S polar", None)
        else:
            lat_lo = float(np.floor(lat / args.lat_band) * args.lat_band)
            lon_lo = float(
                np.floor(((c.lon + 180.0) % 360.0) / args.lon_bin) * args.lon_bin - 180.0
            )
            key = (lat_lo, lon_lo)

        if key not in stats:
            stats[key] = [0, 0]
        stats[key][1] += 1
        if obs == sim:
            stats[key][0] += 1

    # Report: sorted by accuracy
    rows = []
    for (lat_key, lon_key), (match, total) in stats.items():
        acc = match / total if total else 0.0
        rows.append((acc, match, total, lat_key, lon_key))

    rows.sort(key=lambda r: -r[0])

    print(
        f"\n=== Koppen spatial accuracy by grid (lat band {args.lat_band} deg, "
        f"lon bin {args.lon_bin} deg, polar merged |lat|>{args.polar_bound} deg) ===\n"
    )
    print(f"{'lat':>10} {'lon':>8} {'acc':>6} {'n':>6}")

    def _fmt(lat_key, lon_key):
        if lon_key is None:
            return f"{lat_key:>10} {'—':>8}"
        return f"{lat_key:>8.0f}° {lon_key:>7.0f}°"

    print("  — best bins —")
    for acc, _match, total, lat_key, lon_key in rows[: args.top]:
        print(f"  {_fmt(lat_key, lon_key)} {acc:>5.1%} {total:>6}")

    print("  — worst bins —")
    for acc, _match, total, lat_key, lon_key in rows[-args.top :]:
        print(f"  {_fmt(lat_key, lon_key)} {acc:>5.1%} {total:>6}")

    # Overall accuracy for reference
    total_match = sum(m for m, _ in stats.values())
    total_n = sum(t for _, t in stats.values())
    print(
        f"\n  Overall spatial accuracy: {total_match / total_n:.1%} ({total_match}/{total_n} cells)"
    )


if __name__ == "__main__":
    main()
