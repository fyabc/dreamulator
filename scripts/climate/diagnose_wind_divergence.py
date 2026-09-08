#!/usr/bin/env python3
"""Zonal-mean surface-wind divergence diagnostic.

Computes the horizontal divergence ∇·u of the surface wind field on the CVT
graph (finite-volume flux through each Voronoi cell boundary) and reports its
zonal-mean latitude profile.  The pattern is the physical check for the
first-principles precipitation direction:

    divergence < 0  →  convergence → rising air → rain (ITCZ, polar front)
    divergence > 0  →  divergence → sinking air → dry (subtropical high)

Expected Earth signature: convergence at the equator and ~±60°, divergence at
~±30° (the Hadley descending branch).

Modes: by default diverges the **last build's stored wind field**
(``wind_east/north_m_s``, artifact mode, seconds — the field that actually
drove the build's precipitation); ``--rebuild`` re-derives the wind
analytically (1D EBM → pressure → geostrophic + three-cell blend) and accepts
the parameter sweeps below (``--itcz`` shifts the circulation with the seasonal
thermal equator).  The two modes use different wind sources — compare band
*structure*, not exact values.  (Zonal-mean divergence is invariant to the
east-component sign convention; see roadmap tech debt 24.)

Usage::

    uv run python scripts/climate/diagnose_wind_divergence.py             # last build
    uv run python scripts/climate/diagnose_wind_divergence.py --rebuild   # analytical
    uv run python scripts/climate/diagnose_wind_divergence.py --rebuild --itcz 14
"""

from __future__ import annotations

import argparse
import time
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--world", default="earth")
    parser.add_argument("--planet", default="planet_earth")
    parser.add_argument("--world-dir", default="data/worlds")
    parser.add_argument("--branch", default="climate-dev")
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="re-derive the wind analytically (parameter sweeps below) instead of "
        "diverging the last build's stored wind field",
    )
    parser.add_argument(
        "--itcz", type=float, default=0.0, help="ITCZ latitude (°) for the wind (--rebuild only)"
    )
    parser.add_argument("--n-band", type=int, default=9, help="latitude bands for the report")
    parser.add_argument("--hadley-extent", type=float, default=30.0, help="--rebuild only")
    parser.add_argument("--polar-cell-start", type=float, default=60.0, help="--rebuild only")
    parser.add_argument("--rotation-period", type=float, default=1.0, help="--rebuild only")
    parser.add_argument("--obliquity", type=float, default=23.44, help="--rebuild only")
    parser.add_argument("--albedo", type=float, default=0.306, help="--rebuild only")
    parser.add_argument("--radius", type=float, default=6371.0)
    args = parser.parse_args()
    t_start = time.time()

    root = _find_project_root()
    world_dir = root / args.world_dir / args.world
    mesh = _load_mesh(world_dir, args.planet, args.branch)
    if mesh is None:
        print("ERROR: no mesh found")
        return
    n = mesh.num_cells
    print(f"Loaded {n} cells ({args.world}, branch={args.branch})")

    from dreamulator.map.climate_simulator import _surface_divergence

    lat_deg = np.array([c.lat for c in mesh.cells], dtype=np.float64)
    lat_rad = np.radians(lat_deg)
    elevation_m = np.array([c.elevation for c in mesh.cells], dtype=np.float64)
    nodes_xyz = np.zeros((n, 3), dtype=np.float64)
    for i, c in enumerate(mesh.cells):
        nodes_xyz[i, 0] = c.x
        nodes_xyz[i, 1] = c.y
        nodes_xyz[i, 2] = c.z

    neighbors = [list(c.neighbors) for c in mesh.cells]

    if args.rebuild:
        from dreamulator.engine.climate_physics import (
            coriolis_parameter,
            hadley_cell_wind,
            pressure_from_temperature,
            terrain_wind_blocking,
        )
        from dreamulator.engine.climate_seasonality import solve_1d_ebm_temperature
        from dreamulator.map.climate_simulator import (
            _compute_graph_gradient,
            _geostrophic_wind,
        )
        from dreamulator.map.pipeline_types import TerrainPipelineConfig

        config = TerrainPipelineConfig(
            ebm_1d=True,
            hadley_extent_deg=args.hadley_extent,
            polar_cell_start_deg=args.polar_cell_start,
            rotation_period_days=args.rotation_period,
            axial_tilt_deg=args.obliquity,
            albedo=args.albedo,
            radius_km=args.radius,
        )

        # Zonal temperature (1D EBM) → pressure → geostrophic wind.
        t_zonal = solve_1d_ebm_temperature(
            lat_rad, 15.0, albedo=config.albedo, obliquity_deg=config.axial_tilt_deg
        )
        pressure = pressure_from_temperature(t_zonal, elevation_m, config.gravity_m_s2, 1013.25)
        grad_p = _compute_graph_gradient(mesh, pressure, nodes_xyz)
        f_cor = coriolis_parameter(lat_rad, config.rotation_period_days)
        wind_geo = _geostrophic_wind(grad_p, f_cor, nodes_xyz)
        wind_cell = hadley_cell_wind(
            lat_rad,
            nodes_xyz,
            hadley_extent_deg=config.hadley_extent_deg,
            polar_cell_start_deg=config.polar_cell_start_deg,
            rotation_period_days=config.rotation_period_days,
            itcz_lat_deg=args.itcz,
        )
        wind = 0.4 * wind_geo + 0.6 * wind_cell
        wind = terrain_wind_blocking(wind, elevation_m, config.wind_blocking_height_m)
    else:
        print(
            "Artifact mode: diverging the last build's stored wind field "
            "(--rebuild for the analytical probe with parameter sweeps)"
        )
        if not any(c.wind_east_m_s is not None for c in mesh.cells[:5000]):
            print(
                "  ERROR: mesh carries no built wind field — run "
                f"`dreamulator build {args.world} --branch {args.branch} --only climate` "
                "first, or pass --rebuild"
            )
            return
        from dreamulator.map.ocean_circulation import east_north_basis

        # Stored components are true-east/true-north (climate_simulator flips
        # the internal mirrored basis before storage); east_north_basis is the
        # matching true basis, so this composition is the physical wind.
        we = np.array([c.wind_east_m_s or 0.0 for c in mesh.cells], dtype=np.float64)
        wn = np.array([c.wind_north_m_s or 0.0 for c in mesh.cells], dtype=np.float64)
        east, north = east_north_basis(nodes_xyz)
        wind = we[:, None] * east + wn[:, None] * north

    areas_ster = np.array([c.area_km2 for c in mesh.cells], dtype=np.float64) / (args.radius**2)
    div = _surface_divergence(nodes_xyz, wind, neighbors, areas_ster)

    # Zonal-mean divergence in latitude bands.
    mode = "rebuild" if args.rebuild else "artifact"
    print(f"\nSurface-wind divergence div(u) (1/radian), mode={mode}, ITCZ = {args.itcz:+g} deg")
    print(f"{'lat':>6} {'divergence':>12}   sign")
    for b in range(args.n_band):
        lo = -90.0 + b * (180.0 / args.n_band)
        hi = lo + 180.0 / args.n_band
        m = (lat_deg >= lo) & (lat_deg < hi)
        if m.sum() == 0:
            continue
        d = float(div[m].mean())
        sign = "convergence (rising/rain)" if d < 0 else "divergence (sinking/dry)"
        print(f"{(lo + hi) / 2:>+6.1f} {d:>+12.3e}   {sign}")

    print(f"\n(total {time.time() - t_start:.1f}s, {mode} mode)")


if __name__ == "__main__":
    main()
