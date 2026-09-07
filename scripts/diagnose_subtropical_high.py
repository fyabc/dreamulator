"""Sensitivity sweep for the dynamical subtropical high (7-②).

The wind field is purely zonal (three-cell) because the annual-mean land-sea
thermal contrast is dropped (``pressure_anomaly_monthly`` subtracts the annual
mean).  The subtropical ocean is cooler than the subtropical desert in the
annual mean, so it is a persistent HIGH; the geostrophic wind around it is the
subtropical anticyclone (the missing zonal asymmetry).  This script sweeps the
column depth-fraction d/H and reports the subtropical-high magnitude (ocean vs
land ΔP) and the geostrophic wind direction/speed at key points.

Usage:
    uv run python scripts/diagnose_subtropical_high.py --world-dir data/worlds
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import scipy.sparse as sparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from station_diagnostics import _nearest_cell, _wind_dir_compass  # noqa: E402

from dreamulator.engine.climate_physics import coriolis_parameter  # noqa: E402
from dreamulator.engine.monsoon_circulation import zonal_mean_monthly  # noqa: E402
from dreamulator.map.climate_simulator import (  # noqa: E402
    _geostrophic_wind,
    _graph_least_squares_gradient,
    _smooth_graph,
    simulate_climate,
)
from dreamulator.map.ocean_circulation import (  # noqa: E402
    _build_directed_edge_table,
    decompose_tangent,
    east_north_basis,
)
from dreamulator.validate_climate import _load_mesh, build_earth_validation_config  # noqa: E402

# (name, lat, lon): subtropical ocean / land probe points.
_PROBES = [
    ("Azores(Atl)", 33.0, -30.0),
    ("Pacific(E)", 30.0, -150.0),
    ("Sahara", 25.0, 10.0),
    ("Arabia", 25.0, 45.0),
    ("SH-Atlantic", -30.0, -10.0),
    ("SH-Pacific", -30.0, -120.0),
    ("Australia", -25.0, 135.0),
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--world", default="earth")
    parser.add_argument("--planet", default="planet_earth")
    parser.add_argument("--branch", default="climate-dev")
    parser.add_argument("--world-dir", default="data/worlds")
    parser.add_argument("--dh", default="0.5,1.0,1.5")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    mesh = _load_mesh(root / args.world_dir / args.world, args.planet, args.branch or None)
    if mesh is None:
        print("ERROR: no mesh")
        return

    config = build_earth_validation_config(mesh.num_cells)
    simulate_climate(mesh, config)

    n = mesh.num_cells
    lat_deg = np.array([c.lat for c in mesh.cells], dtype=np.float64)
    nodes_xyz = np.array([[c.x, c.y, c.z] for c in mesh.cells], dtype=np.float64)

    # Annual-mean temperature + its zonal mean (the land-sea contrast, WITHOUT
    # the annual-mean removal that the monsoon pressure anomaly applies).
    t_monthly = np.asarray(mesh._t_monthly_c, dtype=np.float64)
    t_annual = t_monthly.mean(axis=1)
    t_zonal_annual = zonal_mean_monthly(t_annual[:, None], lat_deg)[:, 0]
    dt_annual = t_annual - t_zonal_annual
    t_zonal_k = np.maximum(t_zonal_annual + 273.15, 200.0)

    # Synoptic smoothing operator (replicate Stage 2).
    _msrc, _mdst = _build_directed_edge_table(mesh.cells)
    _cell_km = 2.0 * config.radius_km * np.sqrt(np.pi / n)
    _mdeg = np.maximum(np.bincount(_msrc, minlength=n).astype(np.float64), 1.0)
    _avg = sparse.csr_matrix((1.0 / _mdeg[_msrc], (_msrc, _mdst)), shape=(n, n))
    _n_smooth = 2 * int((500.0 / _cell_km) ** 2)
    _radius_m = config.radius_km * 1000.0

    lat_rad = np.radians(lat_deg)
    f_coriolis = coriolis_parameter(lat_rad, config.rotation_period_days)
    east, north = east_north_basis(nodes_xyz)

    print("\n=== Annual-mean land-sea ΔP (hPa) at probes (ocean high / land low) ===\n")
    print(f"{'probe':>16} | {'ΔT(C)':>7} | " + " | ".join(f"dH={d} ΔP" for d in args.dh.split(",")))
    for name, lat, lon in _PROBES:
        gi = _nearest_cell(nodes_xyz, lat, lon)
        dts = dt_annual[gi]
        row = f"{name:>16} | {dts:>7.1f} | "
        for dh in args.dh.split(","):
            dp = -config.surface_pressure_hpa * float(dh) * dts / t_zonal_k[gi]
            row += f"{dp:>8.1f} "
        print(row)

    print("\n=== Geostrophic wind (dir=speed m/s) at probes ===\n")
    for dh in args.dh.split(","):
        dp_hpa = -config.surface_pressure_hpa * float(dh) * dt_annual / t_zonal_k
        dp_hpa = _smooth_graph(dp_hpa, _avg, _n_smooth)
        grad = _graph_least_squares_gradient(mesh, dp_hpa, nodes_xyz) * 100.0 / _radius_m
        vg = _geostrophic_wind(grad, f_coriolis, nodes_xyz)
        we, wn = decompose_tangent(vg, east, north)
        we = -we  # physical east convention (frontend)
        print(f"\n  d/H = {dh}:")
        for name, lat, lon in _PROBES:
            gi = _nearest_cell(nodes_xyz, lat, lon)
            d = _wind_dir_compass(we[gi], wn[gi])
            sp = float(np.hypot(we[gi], wn[gi]))
            print(f"    {name:>16}: {d:>3} {sp:>5.1f} m/s")


if __name__ == "__main__":
    main()
