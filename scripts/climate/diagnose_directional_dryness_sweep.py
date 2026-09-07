#!/usr/bin/env python3
"""Sensitivity sweep for ① directional dryness (continentality).

Sweeps ``L_cont`` (continentality e-folding length, km) × ``k_dry`` (max drying)
for the directional dryness factor applied to land precipitation:

    p *= 1 − k_dry · sqrt(1 − exp(−upwind_dist / L_cont))

Runs the climate engine once, then applies the factor analytically (no engine
re-run) and reports the zonal P R²/RMSE/bias vs GPCP plus the interior-desert
precipitation for each (L_cont, k_dry) combo — the same zonal scoring as
``validate_zonal_precipitation``.

Usage::

    uv run python scripts/climate/diagnose_directional_dryness_sweep.py --world-dir data/worlds
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


_INTERIOR_DESERTS = [
    ("Taklamakan", 37.0, 40.0, 80.0, 90.0, 30.0),
    ("Gobi", 40.0, 45.0, 100.0, 110.0, 100.0),
    ("Sahara", 20.0, 28.0, 0.0, 15.0, 30.0),
    ("Australia", -30.0, -22.0, 125.0, 140.0, 250.0),
]


def _zonal_score(precip: np.ndarray, lats: np.ndarray, ref: np.ndarray) -> tuple[float, float, float]:
    """(r2, rmse, bias) — replicate validate_zonal_precipitation's zonal scoring."""
    n_bands = 90
    sim_zonal = np.full(n_bands, np.nan, dtype=np.float64)
    counts = np.zeros(n_bands, dtype=int)
    for b in range(n_bands):
        lat_center = 90.0 - b * 2.0
        mask = (lats >= lat_center - 1.0) & (lats < lat_center + 1.0)
        counts[b] = mask.sum()
        if mask.sum() > 0:
            sim_zonal[b] = np.mean(precip[mask])
    valid = ~np.isnan(sim_zonal)
    diff = sim_zonal[valid] - ref[valid]
    weights = counts[valid].astype(np.float64)
    weights /= weights.sum()
    rmse = float(np.sqrt(np.sum(weights * diff**2)))
    bias = float(np.sum(weights * diff))
    r2 = float(np.corrcoef(sim_zonal[valid], ref[valid])[0, 1]) ** 2
    return r2, rmse, bias


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
        print("  ERROR: no mesh")
        return

    print(f"Running climate engine on {mesh.num_cells} cells ...")
    from dreamulator.map.climate_config import load_climate_config
    from dreamulator.map.climate_simulator import _upwind_distance_to_coast, simulate_climate

    debug: dict[str, np.ndarray] = {}
    cfg = load_climate_config(world_dir, args.world, args.planet, args.branch, mesh.num_cells)
    simulate_climate(mesh, cfg, debug=debug)

    n = mesh.num_cells
    is_land = np.array([c.water_class == "land" for c in mesh.cells], dtype=bool)
    lat = np.array([c.lat for c in mesh.cells], dtype=np.float64)
    lon = np.array([c.lon for c in mesh.cells], dtype=np.float64)
    nodes_xyz = np.array([[c.x, c.y, c.z] for c in mesh.cells], dtype=np.float64)
    base_p = debug["final"]

    from dreamulator.map.ocean_circulation import east_north_basis

    east, north = east_north_basis(nodes_xyz)
    we = np.array([c.wind_east_m_s for c in mesh.cells], dtype=np.float64)
    wn = np.array([c.wind_north_m_s for c in mesh.cells], dtype=np.float64)
    wind_phys = we[:, None] * east + wn[:, None] * north
    updist, _ = _upwind_distance_to_coast(
        mesh.cells, n, is_land, wind_phys, nodes_xyz, radius_km=cfg.radius_km
    )

    from dreamulator.validate_climate import _ZONAL_PRECIP_REF

    ref = _ZONAL_PRECIP_REF

    # Baseline (k_dry=0) metrics.
    base_r2, base_rmse, base_bias = _zonal_score(base_p, lat, ref)

    desert_masks = []
    for name, lo, hi, wlo, elo, obs in _INTERIOR_DESERTS:
        desert_masks.append((name, is_land & (lat >= lo) & (lat <= hi) & (lon >= wlo) & (lon <= elo)))

    print(f"\nBaseline: R2={base_r2:.3f}  RMSE={base_rmse:.0f}  bias={base_bias:.0f}\n")
    header = "  " + " | ".join(
        [f"{'L_cont':>6} {'k':>4} {'R2':>6} {'RMSE':>6} {'bias':>6}"]
        + [f"{d[0][:5]:>5}" for d in desert_masks]
    )
    print(header)
    print("  " + "-" * (len(header) - 2))

    # Latitude modulation (A): protect the deep tropics (ITCZ keeps the Amazon/
    # Congo wet) — ramp the drying from 0 at |lat|<10° to full at |lat|>25°.
    lat_factor = np.clip((np.abs(lat) - 10.0) / 15.0, 0.0, 1.0)

    for length in (1000.0, 1500.0, 2000.0, 3000.0):
        cont = np.where(is_land, 1.0 - np.exp(-updist / length), 0.0)
        for k in (0.3, 0.5, 0.7, 0.9):
            factor = np.where(is_land, 1.0 - k * np.sqrt(cont) * lat_factor, 1.0)
            p_new = base_p * factor
            r2, rmse, bias = _zonal_score(p_new, lat, ref)
            desert_p = [f"{np.mean(p_new[m]):>5.0f}" for _, m in desert_masks]
            print(
                f"  {length:>6.0f} {k:>4.1f} {r2:>6.3f} {rmse:>6.0f} {bias:>6.0f} | "
                + " | ".join(desert_p)
            )


if __name__ == "__main__":
    main()
