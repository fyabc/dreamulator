#!/usr/bin/env python3
"""Decompose the precipitation budget into its additive terms (mm/yr).

Always re-runs the climate engine (no artifact mode): the budget decomposition
needs solver intermediates (per-cell moisture W and the per-term precipitation
contributions) that build artifacts do not store — see the diagnostic-cache
plan in private/todos/today.md §二-E before adding one.

Runs the climate engine on the Earth (climate-dev) mesh with the shared-physics
validation config and records the precipitation budget terms.  Since the
CLIM-02 mechanism migration the orographic condensation, the coastal /
sub-planet k_rain modulations and the cold-trap upwind routing all live inside
the mass-conserving budget; the only post-budget step left is the convergence
sentinel (per-cell annual cap α·k_rain·W_sat, a declared numerical
stabilisation that warns when it bites).

The check it answers: **does the convergence sentinel clip a material amount of
land precipitation?**  Reports the number of clipped cells and the land-mean
with and without them.

Usage::

    uv run python scripts/climate/diagnose_precip_budget.py
    uv run python scripts/climate/diagnose_precip_budget.py --world-dir data/worlds
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np


def _find_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_mesh(world_dir: Path, planet_id: str, branch: str | None = None):
    from dreamulator.map.export import find_mesh_file, load_cvt_mesh_model

    search_dirs = [world_dir]
    if branch:
        search_dirs.insert(0, world_dir / "branches" / branch)
    for base in search_dirs:
        p = find_mesh_file(base / "maps" / planet_id)
        if p is not None:
            return load_cvt_mesh_model(p)
    return None


def _report_field(label: str, field: np.ndarray, is_land: np.ndarray) -> None:
    land = field[is_land]
    ocean = field[~is_land]
    print(
        f"  {label:<14} global={np.mean(field):>8.1f}  "
        f"land={np.mean(land):>8.1f}  ocean={np.mean(ocean):>8.1f}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--world", default="earth")
    parser.add_argument("--planet", default="planet_earth")
    parser.add_argument("--branch", default="climate-dev")
    parser.add_argument("--world-dir", default="data/worlds")
    args = parser.parse_args()

    root = _find_project_root()
    world_dir = root / args.world_dir / args.world
    branch = args.branch or None  # --branch "" = root world (no branches)

    print(f"Loading mesh ({args.world}, branch={branch}) ...")
    mesh = _load_mesh(world_dir, args.planet, branch)
    if mesh is None:
        print("  ERROR: no mesh found")
        return

    print(f"Running climate engine on {mesh.num_cells} cells ...")
    from dreamulator.map.climate_config import load_climate_config
    from dreamulator.map.climate_simulator import simulate_climate

    debug: dict[str, np.ndarray] = {}
    cfg = load_climate_config(world_dir, args.world, args.planet, branch, mesh.num_cells)
    simulate_climate(mesh, cfg, debug=debug)

    elevation_m = np.array([c.elevation for c in mesh.cells], dtype=np.float64)
    lat_deg = np.array([c.lat for c in mesh.cells], dtype=np.float64)
    is_land = elevation_m >= 0.0

    final = debug["final"]

    print("\n=== Precipitation budget terms (mm/yr) ===\n")
    for key, label in [
        ("moisture_budget", "budget P = k·W + P_oro + P_route"),
        ("storm", "storm-track k_rain component"),
    ]:
        if key in debug:
            _report_field(label, debug[key], is_land)
    if "soil_et_monthly" in debug:
        _report_field("soil bucket ET", debug["soil_et_monthly"].sum(axis=1), is_land)
        _report_field("soil bucket runoff", debug["soil_runoff_monthly"].sum(axis=1), is_land)

    print("\n=== Check: how much does the convergence sentinel clip? ===\n")
    pre_cap = debug["pre_cap"]
    clipped = pre_cap > final + 1e-6
    land_final = final[is_land]
    land_clip = clipped & is_land
    n_clip = int(land_clip.sum())
    n_land = int(is_land.sum())
    print(f"  land-mean precip (final)      : {np.mean(land_final):.1f} mm/yr")
    if n_clip:
        print(
            f"  clipped-cell mean (pre-cap)   : {np.mean(pre_cap[land_clip]):.1f} mm/yr"
        )
    print(f"  ocean-mean precip             : {np.mean(final[~is_land]):.1f} mm/yr")
    print(
        f"  sentinel-clipped land cells   : {n_clip}/{n_land} "
        f"({100 * n_clip / max(n_land, 1):.1f}%)"
    )

    # Zonal precip in the tropics vs GPCP (informational)
    print("\n=== Tropical zonal precip vs GPCP (mm/yr, 5 deg bands) ===\n")
    from dreamulator.validate_climate import _ZONAL_PRECIP_REF

    ref = _ZONAL_PRECIP_REF  # 2 deg bands, 90N -> 88S
    print(f"  {'lat':>5} {'sim':>7} {'gpcp':>7}")
    for latc in range(10, -11, -5):
        mask = (lat_deg >= latc - 2.5) & (lat_deg < latc + 2.5)
        if mask.sum() == 0:
            continue
        sim = np.mean(final[mask])
        idx = int(np.clip(np.round((90.0 - latc) / 2.0), 0, len(ref) - 1))
        print(f"  {latc:>4}d {sim:>7.1f} {ref[idx]:>7.1f}")

    # Ocean evaporation source magnitude + implied ocean->land transport
    print("\n=== Water budget: evaporation source vs precipitation ===\n")
    from dreamulator.engine.climate_physics import evaporation_rate

    t_c = np.array([c.temperature_C for c in mesh.cells], dtype=np.float64)
    ocean_evap = evaporation_rate(t_c, ~is_land, cfg.evaporation_base_mm)
    land_evap = np.where(
        is_land, evaporation_rate(t_c, is_land, cfg.evaporation_base_mm * 0.40), 0.0
    )
    _oe = np.mean(ocean_evap[~is_land])
    _op = np.mean(final[~is_land])
    _le = np.mean(land_evap[is_land])
    _lp = np.mean(final[is_land])
    print(f"  ocean evap  (ocean mean) : {_oe:.1f} mm/yr   (Earth obs ~1143)")
    print(f"  ocean precip (ocean mean): {_op:.1f} mm/yr   (Earth obs ~1033)")
    print(f"  land evap   (land mean)  : {_le:.1f} mm/yr   (Earth obs ~490)")
    print(f"  land precip (land mean)  : {_lp:.1f} mm/yr   (Earth obs ~759)")
    _o_area = int((~is_land).sum())
    _l_area = int(is_land.sum())
    _net = _oe - _op
    _net_land = _net * _o_area / max(_l_area, 1)
    print(
        f"  ocean->land transport: {_net:.1f} mm/yr (ocean mean) = "
        f"{_net_land:.1f} mm/yr (land mean)   (Earth obs ~268 land-mean)"
    )


if __name__ == "__main__":
    main()
