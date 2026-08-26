#!/usr/bin/env python3
"""Decompose the precipitation budget into its additive terms (mm/yr).

Runs the climate engine on the Earth (climate-dev) mesh with the shared-physics
validation config and records each additive precipitation term (BFS diffusion,
directional baseline, convergence, storm track, convection, tropical boost,
sub-planet) before the multiplicative coastal/föhn/aridity factors and the
final 11000 mm cap are applied.

Two checks it answers (the "transport magnitude" lever):

1. **Is the global land-mean precipitation inflated by the 11000 mm cap?**
   Reports the number/area of land cells pinned at the cap and the land-mean
   with those cells excluded.

2. **Does the convergence cap (40 mm) underestimate ITCZ precipitation?**
   Reports the convergence term's magnitude in the ITCZ band (equator ±5°) vs
   the observed ~2000 mm/yr ITCZ rainfall, and the tropical zonal-mean precip
   vs GPCP.

Usage::

    uv run python scripts/diagnose_precip_budget.py
    uv run python scripts/diagnose_precip_budget.py --world-dir private/worlds
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

    print(f"Loading Earth mesh ({args.world}, branch={args.branch}) ...")
    mesh = _load_mesh(world_dir, args.planet, args.branch)
    if mesh is None:
        print("  ERROR: no mesh found")
        return

    print(f"Running climate engine on {mesh.num_cells} cells ...")
    from dreamulator.map.climate_simulator import simulate_climate
    from dreamulator.validate_climate import build_earth_validation_config

    debug: dict[str, np.ndarray] = {}
    cfg = build_earth_validation_config(mesh.num_cells)
    simulate_climate(mesh, cfg, debug=debug)

    elevation_m = np.array([c.elevation for c in mesh.cells], dtype=np.float64)
    lat_deg = np.array([c.lat for c in mesh.cells], dtype=np.float64)
    is_land = elevation_m >= 0.0

    final = debug["final"]

    print("\n=== Precipitation budget (additive terms, mm/yr, before mult/cap) ===\n")
    for key, label in [
        ("moisture_budget", "moisture budget P=W/tau"),
        ("storm", "storm track"),
        ("convection", "convection"),
        ("tropical_boost", "tropical boost"),
        ("sub_planet", "sub-planet"),
    ]:
        if key in debug:
            _report_field(label, debug[key], is_land)

    print("\n=== Check 1: does the 11000 mm cap inflate land-mean precip? ===\n")
    land_final = final[is_land]
    at_cap = land_final >= 11000.0 - 1e-6
    n_cap = int(at_cap.sum())
    n_land = int(is_land.sum())
    print(f"  land-mean precip (with cap)   : {np.mean(land_final):.1f} mm/yr")
    print(f"  land-mean precip (excl cap)   : {np.mean(land_final[~at_cap]):.1f} mm/yr")
    print(f"  ocean-mean precip             : {np.mean(final[~is_land]):.1f} mm/yr")
    print(
        f"  capped land cells             : {n_cap}/{n_land} ({100 * n_cap / max(n_land, 1):.1f}%)"
    )

    print("\n=== Check 2: convergence term vs observed ITCZ precip (~2000 mm/yr) ===\n")
    conv = debug.get("convergence")
    if conv is not None:
        itcz_band = np.abs(lat_deg) < 5.0
        itcz_land = itcz_band & is_land
        print(f"  convergence ITCZ band (+-5 deg) mean : {np.mean(conv[itcz_band]):.1f} mm/yr")
        print(f"  convergence ITCZ band max            : {np.max(conv[itcz_band]):.1f} mm/yr")
        print(f"  convergence ITCZ land mean           : {np.mean(conv[itcz_land]):.1f} mm/yr")

        t_itcz = np.array([c.temperature_C for c in mesh.cells])[itcz_land]
        t_k = np.maximum(t_itcz + 273.15, 230.0)
        e_sat = 611.2 * np.exp(17.67 * (t_k - 273.15) / (t_k - 29.65))
        q_sat = 0.622 * e_sat / 101325.0
        col_water = q_sat * 1.2 * 2500.0
        print(f"  ITCZ land mean T                    : {np.mean(t_itcz):.1f} degC")
        print(
            f"  ITCZ column water W(T) mean         : {np.mean(col_water):.1f} mm (cap=40 binding?)"
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
