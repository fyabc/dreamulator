#!/usr/bin/env python3
"""Diagnose the Föhn rain shadow: point-effect extent + regional dryness.

The current Föhn (climate_simulator Step 6.7) dries a land cell only when its
*immediate* upwind neighbour is a higher barrier — a "point effect" that puts the
rain shadow one cell (~50 km) deep, whereas a real rain shadow extends hundreds
of km downwind of a range (Atacama, Patagonia, Great Basin, Taklamakan).

This script runs the climate engine once (with the debug Föhn fields) and reports:

1. The Föhn factor / drop distribution over land — how many cells are dried and
   by how much (and, by inspection of the drop field, that the shadow is a single
   cell deep).
2. Modelled vs observed precipitation in classic rain-shadow regions (lee of the
   Andes / Sierra Nevada / Tibetan Plateau / Western Ghats).
3. East-coast-wet / west-coast-dry asymmetry at a couple of latitude bands — the
   "directional dryness" (①) anchor.

Usage::

    uv run python scripts/diagnose_rain_shadow.py --world-dir data/worlds
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np


def _find_project_root() -> Path:
    return Path(__file__).resolve().parent.parent


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


# Classic rain-shadow regions: (name, lat_lo, lat_hi, lon_lo, lon_hi, obs_mm).
# obs_mm is the rough regional mean annual precipitation (GPCP / CRU order).
_RAIN_SHADOW_REGIONS = [
    ("Patagonia (lee Andes)", -50.0, -40.0, -72.0, -65.0, 250.0),
    ("Atacama (lee Andes)", -27.0, -18.0, -71.0, -68.0, 50.0),
    ("Great Basin (lee Sierra)", 38.0, 42.0, -118.0, -112.0, 250.0),
    ("Taklamakan (lee Tibet)", 37.0, 40.0, 80.0, 90.0, 30.0),
    ("Deccan lee (lee W. Ghats)", 15.0, 20.0, 76.0, 80.0, 650.0),
]

# East-coast-wet / west-coast-dry pairs at similar latitude (① directional dryness).
_COAST_PAIRS = [
    # (name_west, lat, lon_west, name_east, lon_east)
    ("California (west)", 34.0, -120.0, "US SE (east)", -78.0),
    ("Chile (west)", -35.0, -72.0, "Argentina (east)", -58.0),
    ("Iberia (west)", 39.0, -9.0, "China E (east)", 120.0),
]


def _mean_in_box(field: np.ndarray, lat: np.ndarray, lon: np.ndarray, is_land: np.ndarray,
                 lat_lo, lat_hi, lon_lo, lon_hi) -> float:
    m = is_land & (lat >= lat_lo) & (lat <= lat_hi) & (lon >= lon_lo) & (lon <= lon_hi)
    return float(np.mean(field[m])) if m.any() else float("nan")


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

    elevation_m = np.array([c.elevation for c in mesh.cells], dtype=np.float64)
    lat_deg = np.array([c.lat for c in mesh.cells], dtype=np.float64)
    lon_deg = np.array([c.lon for c in mesh.cells], dtype=np.float64)
    is_land = elevation_m >= 0.0

    fohn = debug["fohn_factor"]
    drop = debug["fohn_drop"]
    final = debug["final"]

    print("\n=== Fohn factor / drop distribution (land) ===\n")
    land_fohn = fohn[is_land]
    land_drop = drop[is_land]
    for thresh in (0.99, 0.9, 0.7, 0.5, 0.3):
        n = int((land_fohn < thresh).sum())
        pct = 100 * n / max(is_land.sum(), 1)
        print(f"  factor < {thresh:.2f}: {n:>6} cells  ({pct:.1f}% of land)")
    print(f"  min factor       : {land_fohn.min():.3f}")
    print(f"  mean factor      : {land_fohn.mean():.4f}")
    for thresh in (500.0, 1500.0, 3000.0):
        n = int((land_drop > thresh).sum())
        print(f"  barrier drop > {thresh:>5.0f} m : {n:>6} cells")
    print(f"  max barrier drop : {land_drop.max():.0f} m")

    print("\n=== Rain-shadow regions (barrier / drop / since / wind) ===\n")
    barrier = debug["fohn_barrier"]
    since = debug["fohn_since"]
    wind_e = np.array([c.wind_east_m_s for c in mesh.cells], dtype=np.float64)
    wind_n = np.array([c.wind_north_m_s for c in mesh.cells], dtype=np.float64)
    print(f"  {'region':<24} {'P_mod':>6} {'obs':>5} {'fohn':>6} "
          f"{'barr':>6} {'drop':>6} {'since':>6} {'uE':>7} {'uN':>7}")
    for name, lo, hi, wlo, elo, obs in _RAIN_SHADOW_REGIONS:
        m = is_land & (lat_deg >= lo) & (lat_deg <= hi) & (lon_deg >= wlo) & (lon_deg <= elo)
        if not m.any():
            print(f"  {name:<24} {'(no cells)':>6}")
            continue
        print(f"  {name:<24} {np.mean(final[m]):>6.0f} {obs:>5.0f} "
              f"{np.mean(fohn[m]):>6.3f} {np.mean(barrier[m]):>6.0f} "
              f"{np.mean(drop[m]):>6.0f} {np.mean(since[m]):>6.0f} "
              f"{np.mean(wind_e[m]):>7.1f} {np.mean(wind_n[m]):>7.1f}")

    print("\n=== East-coast-wet / west-coast-dry pairs (directional dryness) ===\n")
    xyz = np.array([[c.x, c.y, c.z] for c in mesh.cells], dtype=np.float64)

    def _nearest(lat: float, lon: float) -> int:
        pt = np.array([
            np.cos(np.radians(lat)) * np.cos(np.radians(lon)),
            np.sin(np.radians(lat)),
            np.cos(np.radians(lat)) * np.sin(np.radians(lon)),
        ])
        return int(np.argmax(xyz @ pt))

    for wname, lat, wlon, ename, elon in _COAST_PAIRS:
        wi = _nearest(lat, wlon)
        ei = _nearest(lat, elon)
        print(f"  {wname:<16} P={final[wi]:>6.0f} mm  |  {ename:<16} P={final[ei]:>6.0f} mm")


if __name__ == "__main__":
    main()
