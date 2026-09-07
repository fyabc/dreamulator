"""Winter-monsoon wind diagnosis — East Asian winter outflow direction.

§7 (winter monsoon / Siberian high outflow): the annual westerly background wind
traces East Asian land cells (Harbin, Beijing) upwind to a *warm* maritime
source (Caspian / Bohai) when it should be the cold Siberian interior — the
Siberian high's winter anticyclone drives a cold NW/N outflow that overrides the
westerlies at the surface.  This script inspects, at key stations, the monthly
surface wind (annual background + monsoon anomaly) in January vs July: its
compass direction, speed, and the upwind ocean cell it traces to (with that
cell's January temperature), so we can see whether the winter monsoon direction
is already present or must be fixed before switching 4.1-B to monthly wind.

Usage:
    uv run python scripts/diagnose_winter_monsoon.py --world-dir data/worlds
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from station_diagnostics import STATIONS, _nearest_cell, _wind_dir_compass  # noqa: E402

from dreamulator.map.climate_simulator import (  # noqa: E402
    _upwind_distance_to_coast,
    simulate_climate,
)
from dreamulator.map.ocean_circulation import east_north_basis  # noqa: E402
from dreamulator.validate_climate import _load_mesh, build_earth_validation_config  # noqa: E402

_NAMES = ["Harbin", "Beijing", "Moscow", "Denver", "Urumqi", "Chicago", "Anchorage"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--world", default="earth")
    parser.add_argument("--planet", default="planet_earth")
    parser.add_argument("--branch", default="climate-dev")
    parser.add_argument("--world-dir", default="data/worlds")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    mesh = _load_mesh(root / args.world_dir / args.world, args.planet, args.branch or None)
    if mesh is None:
        print("ERROR: no mesh")
        return

    print(f"Running climate simulation on {mesh.num_cells} cells ...")
    config = build_earth_validation_config(mesh.num_cells)
    simulate_climate(mesh, config)

    n = mesh.num_cells
    lat_deg = np.array([c.lat for c in mesh.cells], dtype=np.float64)
    lon_deg = np.array([c.lon for c in mesh.cells], dtype=np.float64)
    is_land = np.array([c.water_class == "land" for c in mesh.cells], dtype=bool)
    nodes_xyz = np.array([[c.x, c.y, c.z] for c in mesh.cells], dtype=np.float64)

    t_monthly = np.asarray(mesh._t_monthly_c, dtype=np.float64)  # (N, 12)
    # Stored monthly wind is already in the physical (frontend) convention.
    we_monthly = np.asarray(mesh._wind_east_monthly, dtype=np.float64)  # (N, 12)
    wn_monthly = np.asarray(mesh._wind_north_monthly, dtype=np.float64)  # (N, 12)

    east, north = east_north_basis(nodes_xyz)

    # Annual background wind (physical) for comparison: stored per-cell annual.
    we_ann = np.array([c.wind_east_m_s for c in mesh.cells], dtype=np.float64)
    wn_ann = np.array([c.wind_north_m_s for c in mesh.cells], dtype=np.float64)

    # Model month 0=Mar … 10=Jan, 11=Feb.  Calendar month j0 ∈ {0..11}
    # (Jan..Dec) → model m = (j0-2)%12.  So Jan(j0=0)→10, Jul(j0=6)→4.
    m_jan = (0 - 2) % 12  # Jan → 10
    m_jul = (6 - 2) % 12  # Jul → 4

    print(f"\n{'station':>10} | {'obs jan wind':>12} | annual | Jan model | Jul model")
    print("-" * 110)
    for name in _NAMES:
        s = next(x for x in STATIONS if x["name"] == name)
        gi = _nearest_cell(nodes_xyz, s["lat"], s["lon"])
        obs_jan = s.get("wind_jan", "?")

        # Annual wind (physical): we_ann is wind_east_m_s (physical east).
        d_ann = _wind_dir_compass(we_ann[gi], wn_ann[gi])
        d_jan = _wind_dir_compass(we_monthly[gi, m_jan], wn_monthly[gi, m_jan])
        d_jul = _wind_dir_compass(we_monthly[gi, m_jul], wn_monthly[gi, m_jul])

        # Speed
        sp_jan = float(np.hypot(we_monthly[gi, m_jan], wn_monthly[gi, m_jan]))
        sp_jul = float(np.hypot(we_monthly[gi, m_jul], wn_monthly[gi, m_jul]))
        sp_ann = float(np.hypot(we_ann[gi], wn_ann[gi]))

        print(
            f"{name:>10} | {obs_jan:>12} | {d_ann}({sp_ann:.1f}) | "
            f"{d_jan}({sp_jan:.1f}) | {d_jul}({sp_jul:.1f})"
        )

    # Upwind ocean trace for the annual wind vs the January monthly wind.
    print("\n=== upwind ocean source (annual vs January monthly wind) ===")
    print(f"{'station':>10} | {'ann src(lat,lon,Tjan)':>34} | {'Jan src(lat,lon,Tjan)':>34}")
    print("-" * 90)
    for name in _NAMES:
        s = next(x for x in STATIONS if x["name"] == name)
        gi = _nearest_cell(nodes_xyz, s["lat"], s["lon"])

        def fmt_src(src, tjan):
            if src < 0:
                return "no-ocean(-)"
            return f"({lat_deg[src]:+.0f},{lon_deg[src]:+.0f},{tjan[src]:+.0f}C)"

        # Annual wind (physical): we_ann (east), wn_ann (north) → recompose.
        wind_ann = we_ann[:, None] * east + wn_ann[:, None] * north
        dist_a, src_a = _upwind_distance_to_coast(
            mesh.cells, n, is_land, wind_ann, nodes_xyz, radius_km=config.radius_km
        )
        # January monthly wind
        wind_jan = we_monthly[:, m_jan, None] * east + wn_monthly[:, m_jan, None] * north
        dist_j, src_j = _upwind_distance_to_coast(
            mesh.cells, n, is_land, wind_jan, nodes_xyz, radius_km=config.radius_km
        )

        print(
            f"{name:>10} | {fmt_src(src_a[gi], t_monthly[:, m_jan]):>34} | "
            f"{fmt_src(src_j[gi], t_monthly[:, m_jan]):>34}"
        )


if __name__ == "__main__":
    main()
