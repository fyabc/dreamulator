"""Sensitivity sweep for the wind-aware monthly maritime temperature advection.

4.1-B (winter continental cold): the seasonal EBM's radiative cosine cycle
over-amplifies continental winter cold (Moscow ~-25 C vs ~-9 observed) because
it lacks the *advective* warming of continental interiors by maritime air
masses carried in on the prevailing wind.  This script quantifies whether a
wind-aware monthly relaxation — relax each land cell's monthly temperature
toward its *upwind* ocean's monthly temperature, decaying over the upwind
distance — warms Moscow (downwind of the warm Atlantic) without warming Chicago
(downwind of the cold continental interior).

Mechanism (reuses the unused ``_upwind_distance_to_coast`` ray-tracer):

    for each month m:
        t_land[i, m] += exp(-dist_upwind[i, m] / L) * (t_ocean[source[i,m], m] - t_land[i, m])

where ``dist_upwind``/``source`` trace, against the *monthly* surface wind, the
path maritime air travels from the ocean to each land cell, and L is the
maritime air-mass decay length (the single free parameter).

Usage:
    uv run python scripts/diagnose_maritime_advection.py --world-dir private/worlds
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from station_diagnostics import STATIONS, _nearest_cell  # noqa: E402

from dreamulator.engine.climate_seasonality import itcz_latitude_monthly  # noqa: E402
from dreamulator.map.climate_simulator import (  # noqa: E402
    _seasonal_mean_cell_wind,
    _upwind_distance_to_coast,
    simulate_climate,
)
from dreamulator.map.ocean_circulation import east_north_basis, recompose_tangent  # noqa: E402
from dreamulator.validate_climate import _load_mesh, build_earth_validation_config  # noqa: E402

_NCEP_AIR = (
    Path(__file__).resolve().parent.parent
    / "private"
    / "tmp"
    / "climatology"
    / "ncep_air.mon.ltm.nc"
)


def _recompute_annual_wind(mesh, config) -> tuple[np.ndarray, np.ndarray]:
    lat_rad = np.radians(np.array([c.lat for c in mesh.cells], dtype=np.float64))
    nodes_xyz = np.array([[c.x, c.y, c.z] for c in mesh.cells], dtype=np.float64)
    itcz = itcz_latitude_monthly(
        obliquity_deg=config.axial_tilt_deg,
        orbital_period_days=config.orbital_period_days,
        eccentricity=config.eccentricity,
        perihelion_day=config.perihelion_day,
    )
    wind = _seasonal_mean_cell_wind(lat_rad, nodes_xyz, config, itcz)
    return nodes_xyz, wind


def _reconstruct_monthly_wind(mesh, nodes_xyz) -> np.ndarray:
    """Reconstruct the (N,12,3) monthly wind from the stored east/north fields."""
    we = np.asarray(mesh._wind_east_monthly, dtype=np.float64)  # (N, 12)
    wn = np.asarray(mesh._wind_north_monthly, dtype=np.float64)  # (N, 12)
    east, north = east_north_basis(nodes_xyz)
    wind_monthly = np.empty((we.shape[0], 12, 3), dtype=np.float64)
    for m in range(12):
        # write-back stored wind_east = -vec.east (line 610 sign flip) and
        # wind_north = vec.north.
        wind_monthly[:, m] = recompose_tangent(-we[:, m], wn[:, m], east, north)
    return wind_monthly


def _station_winter_errors(t_monthly_c, xyz) -> list[tuple[str, str, float]]:
    """Coldest-month temperature error (model - observed) per station."""
    rows = []
    for s in STATIONS:
        gi = _nearest_cell(xyz, s["lat"], s["lon"])
        # model month m (0=Mar) -> calendar Jan-Dec via calendar j = (m+2)%12,
        # i.e. m = (j-2)%12.
        mod_t = t_monthly_c[gi][(np.arange(12) - 2) % 12]
        obs_t = np.array(s["t"])
        cm = int(np.argmin(obs_t))
        rows.append((s["name"], s["koppen"][0], mod_t[cm] - obs_t[cm]))
    return rows


def _global_t_zonal(t_monthly_c, lat_deg) -> tuple[float, float] | None:
    """Zonal-mean RMSE/R2 vs NCEP monthly air (if the file is present)."""
    if not _NCEP_AIR.exists():
        return None
    import xarray as xr

    ds = xr.open_dataset(_NCEP_AIR, decode_times=False)
    obs = np.asarray(ds["air"].mean(dim="lon").values, dtype=np.float64)  # (12, 73)
    ds.close()
    idx = np.clip(((90.0 - lat_deg) / 2.5).astype(int), 0, 72)
    mdl = np.zeros((12, 73), dtype=np.float64)
    for m in range(12):
        np.add.at(mdl[m], idx, t_monthly_c[:, m])
    counts = np.bincount(idx, minlength=73).astype(np.float64)
    mdl /= np.maximum(counts, 1.0)[None, :]
    mdl = np.asarray([mdl[(j - 2) % 12] for j in range(12)])
    a, b = mdl.ravel(), obs.ravel()
    m = np.isfinite(a) & np.isfinite(b)
    a, b = a[m], b[m]
    return float(np.sqrt(np.mean((a - b) ** 2))), float(np.corrcoef(a, b)[0, 1] ** 2)


def _apply_relaxation(t_base, dist, src, valid, length_km, monthly) -> np.ndarray:
    t = t_base.copy()
    if monthly:
        for m in range(12):
            w = np.where(valid[:, m], np.exp(-dist[:, m] / length_km), 0.0)
            t_src = np.where(valid[:, m], t_base[np.maximum(src[:, m], 0), m], 0.0)
            t[:, m] += w * (t_src - t[:, m])
    else:
        w = np.where(valid, np.exp(-dist / length_km), 0.0)
        for m in range(12):
            t_src = np.where(valid, t_base[np.maximum(src, 0), m], 0.0)
            t[:, m] += w * (t_src - t[:, m])
    return t


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--world", default="earth")
    parser.add_argument("--planet", default="planet_earth")
    parser.add_argument("--branch", default="climate-dev")
    parser.add_argument("--world-dir", default="private/worlds")
    parser.add_argument("--sweep", default="500,1000,1500,2000,2500")
    parser.add_argument("--mode", choices=["annual", "monthly", "both"], default="monthly")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    world_dir = root / args.world_dir / args.world
    mesh = _load_mesh(world_dir, args.planet, args.branch or None)
    if mesh is None:
        print(f"ERROR: no mesh at {world_dir}")
        return

    print(f"Running climate simulation on {mesh.num_cells} cells ...")
    config = build_earth_validation_config(mesh.num_cells)
    simulate_climate(mesh, config)

    n = mesh.num_cells
    lat_deg = np.array([c.lat for c in mesh.cells], dtype=np.float64)
    is_land = np.array([c.water_class == "land" for c in mesh.cells], dtype=bool)
    nodes_xyz = np.array([[c.x, c.y, c.z] for c in mesh.cells], dtype=np.float64)

    t_base = np.asarray(mesh._t_monthly_c, dtype=np.float64)  # (N, 12)

    sweep = [float(x) for x in args.sweep.split(",")]
    names = ["Moscow", "Denver", "Chicago", "Harbin", "Urumqi", "Anchorage", "Beijing"]

    modes = ["annual", "monthly"] if args.mode == "both" else [args.mode]

    for mode in modes:
        if mode == "annual":
            _, wind = _recompute_annual_wind(mesh, config)
            dist, src = _upwind_distance_to_coast(
                mesh.cells, n, is_land, wind, nodes_xyz, radius_km=config.radius_km
            )
            valid = is_land & (src >= 0)
        else:
            wind_monthly = _reconstruct_monthly_wind(mesh, nodes_xyz)
            dist = np.full((n, 12), np.inf, dtype=np.float64)
            src = np.full((n, 12), -1, dtype=np.int64)
            for m in range(12):
                d, s = _upwind_distance_to_coast(
                    mesh.cells,
                    n,
                    is_land,
                    wind_monthly[:, m],
                    nodes_xyz,
                    radius_km=config.radius_km,
                )
                dist[:, m] = d
                src[:, m] = s
            valid = is_land[:, None] & (src >= 0)

        print(f"\n=== [{mode}] winter (coldest-month) error: model - observed (C) ===")
        print(f"{'L(km)':>7} | " + " | ".join(f"{nm:>9}" for nm in names) + " | Dg   Bg   Cg")
        for length_km in sweep:
            t = _apply_relaxation(t_base, dist, src, valid, length_km, monthly=(mode == "monthly"))
            rows = _station_winter_errors(t, nodes_xyz)
            err = {nm: v for nm, _, v in rows}
            grp = {}
            for _, k, v in rows:
                grp.setdefault(k, []).append(v)
            line = " | ".join(f"{err[nm]:>9.1f}" for nm in names)
            g = " | ".join(f"{np.mean(grp[k]):>4.1f}" for k in "DBC" if k in grp)
            print(f"{length_km:>7.0f} | {line} | {g}")

        rows0 = _station_winter_errors(t_base, nodes_xyz)
        err0 = {nm: v for nm, _, v in rows0}
        grp0 = {}
        for _, k, v in rows0:
            grp0.setdefault(k, []).append(v)
        line0 = " | ".join(f"{err0[nm]:>9.1f}" for nm in names)
        g0 = " | ".join(f"{np.mean(grp0[k]):>4.1f}" for k in "DBC" if k in grp0)
        print(f"{'base':>7} | {line0} | {g0}")

        g0 = _global_t_zonal(t_base, lat_deg)
        print(f"=== [{mode}] global zonal-mean T vs NCEP (RMSE | R2) ===")
        if g0 is None:
            print("  (ncep_air.mon.ltm.nc not found — skipping global metric)")
        else:
            print(f"{'base':>7} | RMSE={g0[0]:.2f}  R2={g0[1]:.3f}")
            for length_km in sweep:
                t = _apply_relaxation(
                    t_base, dist, src, valid, length_km, monthly=(mode == "monthly")
                )
                g = _global_t_zonal(t, lat_deg)
                print(f"{length_km:>7.0f} | RMSE={g[0]:.2f}  R2={g[1]:.3f}")


if __name__ == "__main__":
    main()
