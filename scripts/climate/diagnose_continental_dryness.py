#!/usr/bin/env python3
"""Diagnose interior aridity: precipitation vs upwind distance to coast.

① directional dryness — the deep continental interior (Taklamakan, Gobi, Sahara
interior) is far too wet (Taklamakan ~310 mm vs ~30 mm observed; classified Dfa
instead of BWk).  The moisture budget advects moisture ~u·τ ≈ 3900 km inland,
so the interior never dries out the way it should.

This script runs the climate engine once and reports the precipitation decay
profile binned by upwind distance to coast, plus the Budyko land-E feedback, so
we can see whether the interior dries fast enough (and whether the dryness is
directional — upwind — or effectively isotropic).

Usage::

    uv run python scripts/climate/diagnose_continental_dryness.py --world-dir data/worlds
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np


def _find_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_mesh(world_dir: Path, planet_id: str, branch: str | None = None):
    from pydantic import TypeAdapter

    from dreamulator.map.models import CVTMesh

    search_dirs = [world_dir]
    if branch:
        search_dirs.insert(0, world_dir / "branches" / branch)
    for base in search_dirs:
        p = base / "maps" / planet_id / "cvt_mesh.json"
        if p.exists():
            from dreamulator.map.export import decompress_mesh_bytes

            return TypeAdapter(CVTMesh).validate_json(decompress_mesh_bytes(p.read_bytes()))
    return None


# Interior deserts: (name, lat_lo, lat_hi, lon_lo, lon_hi, obs_mm).
_INTERIOR_DESERTS = [
    ("Taklamakan", 37.0, 40.0, 80.0, 90.0, 30.0),
    ("Gobi", 40.0, 45.0, 100.0, 110.0, 100.0),
    ("Sahara interior", 20.0, 28.0, 0.0, 15.0, 30.0),
    ("Central Australia", -30.0, -22.0, 125.0, 140.0, 250.0),
    ("Great Basin", 38.0, 42.0, -118.0, -112.0, 250.0),
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--world", default="earth")
    parser.add_argument("--planet", default="planet_earth")
    parser.add_argument("--branch", default="climate-dev")
    parser.add_argument("--world-dir", default="data/worlds")
    args = parser.parse_args()

    root = _find_project_root()
    world_dir = root / args.world_dir / args.world

    print(f"Loading mesh ({args.world}, branch={args.branch}) ...")
    mesh = _load_mesh(world_dir, args.planet, args.branch)
    if mesh is None:
        print("  ERROR: no mesh found")
        return

    print(f"Running climate engine on {mesh.num_cells} cells ...")
    from dreamulator.map.climate_config import load_climate_config
    from dreamulator.map.climate_simulator import simulate_climate

    debug: dict[str, np.ndarray] = {}
    cfg = load_climate_config(world_dir, args.world, args.planet, args.branch, mesh.num_cells)
    simulate_climate(mesh, cfg, debug=debug)

    n = mesh.num_cells
    elevation_m = np.array([c.elevation for c in mesh.cells], dtype=np.float64)
    lat_deg = np.array([c.lat for c in mesh.cells], dtype=np.float64)
    lon_deg = np.array([c.lon for c in mesh.cells], dtype=np.float64)
    is_land = np.array([c.water_class == "land" for c in mesh.cells], dtype=bool)
    nodes_xyz = np.array([[c.x, c.y, c.z] for c in mesh.cells], dtype=np.float64)
    final = debug["final"]

    # Reconstruct the physical annual wind from the stored cell components
    # (wind_east_m_s is already physical — flipped at write time in simulate_climate).
    from dreamulator.map.ocean_circulation import east_north_basis

    east, north = east_north_basis(nodes_xyz)
    we = np.array([c.wind_east_m_s for c in mesh.cells], dtype=np.float64)
    wn = np.array([c.wind_north_m_s for c in mesh.cells], dtype=np.float64)
    wind_phys = we[:, None] * east + wn[:, None] * north

    from dreamulator.map.climate_simulator import _upwind_distance_to_coast

    updist, _ = _upwind_distance_to_coast(
        mesh.cells, n, is_land, wind_phys, nodes_xyz, radius_km=cfg.radius_km
    )

    print("\n=== Precipitation / evaporation vs upwind distance (land) ===\n")
    bins = [0.0, 500.0, 1000.0, 2000.0, 3000.0, 4000.0, np.inf]
    labels = ["0-500", "500-1k", "1k-2k", "2k-3k", "3k-4k", "4k+"]
    land_et = debug["land_et"]
    land_epot = debug["land_epot"]
    print(f"  {'upwind':<9} {'n':>6} {'P':>6} {'E_land':>7} {'E_pot':>6} {'E/E_pot':>8}")
    for lo, hi, lab in zip(bins[:-1], bins[1:], labels):
        m = is_land & (updist >= lo) & (updist < hi)
        if not m.any():
            print(f"  {lab:<9} {'(none)':>6}")
            continue
        ratio = np.mean(land_et[m]) / max(np.mean(land_epot[m]), 1e-9)
        print(f"  {lab:<9} {m.sum():>6} {np.mean(final[m]):>6.0f} "
              f"{np.mean(land_et[m]):>7.0f} {np.mean(land_epot[m]):>6.0f} {ratio:>8.3f}")

    print("\n=== Interior deserts (model vs observed, mm/yr) ===\n")
    print(f"  {'region':<20} {'model':>7} {'obs':>6} {'upwind':>7}")
    for name, lo, hi, wlo, elo, obs in _INTERIOR_DESERTS:
        m = is_land & (lat_deg >= lo) & (lat_deg <= hi) & (lon_deg >= wlo) & (lon_deg <= elo)
        if not m.any():
            print(f"  {name:<20} {'(no cells)':>7}")
            continue
        print(f"  {name:<20} {np.mean(final[m]):>7.0f} {obs:>6.0f} {np.mean(updist[m]):>7.0f}")


if __name__ == "__main__":
    main()
