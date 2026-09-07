"""Sensitivity sweep for a continentality-aware seasonal-amplitude damping.

4.1-B (continental seasonal amplitude too large): the seasonal EBM's radiative
cosine cycle over-amplifies the deep continental interior (Moscow ~-25 C winter,
amplitude 26.8 vs 12.9 observed) because it carries no *zonal* maritime
moderation — the warm air advected inland by the westerlies / eddy transport
that damps the real continental seasonal cycle.

This is the "smart explicit preset" (not a GCM coupling, not the wind-aware
advection that over-warms East Asia): a damping that scales with continentality
(distance to coast), leaving the already-over-maritime coast untouched and only
shrinking the amplitude of the deep interior.

    amp' = amp / (1 + k_cont * continentality),  continentality = 1 - exp(-d/L)

where d is the isotropic distance to coast (km), k_cont the maximum relative
damping deep inland, L the maritime-penetration e-folding length.

Usage:
    uv run python scripts/climate/diagnose_continental_damping.py --world-dir data/worlds
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from station_diagnostics import STATIONS, _nearest_cell  # noqa: E402

from dreamulator.map.climate_simulator import (  # noqa: E402
    _graph_distance_to_coast,
    simulate_climate,
)
from dreamulator.validate_climate import _load_mesh, build_earth_validation_config  # noqa: E402


def _errors(t_monthly_c, xyz) -> list[tuple[str, str, float, float, float, float]]:
    """(name, koppen, jan_err, jul_err, ann_err, amp_err) per station."""
    rows = []
    for s in STATIONS:
        gi = _nearest_cell(xyz, s["lat"], s["lon"])
        mod_t = t_monthly_c[gi][(np.arange(12) - 2) % 12]
        obs_t = np.array(s["t"])
        jan = float(mod_t[0] - obs_t[0])
        jul = float(mod_t[6] - obs_t[6])
        ann = float(mod_t.mean() - obs_t.mean())
        amp = float((mod_t.max() - mod_t.min()) / 2 - (obs_t.max() - obs_t.min()) / 2)
        rows.append((s["name"], s["koppen"][0], jan, jul, ann, amp))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--world", default="earth")
    parser.add_argument("--planet", default="planet_earth")
    parser.add_argument("--branch", default="climate-dev")
    parser.add_argument("--world-dir", default="data/worlds")
    parser.add_argument("--k", default="0.5,1.0,1.5,2.0")
    parser.add_argument("--L", default="1000,1500,2000")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[2]
    mesh = _load_mesh(root / args.world_dir / args.world, args.planet, args.branch or None)
    if mesh is None:
        print("ERROR: no mesh")
        return

    print(f"Running climate simulation on {mesh.num_cells} cells ...")
    config = build_earth_validation_config(mesh.num_cells)
    simulate_climate(mesh, config)

    n = mesh.num_cells
    is_land = np.array([c.water_class == "land" for c in mesh.cells], dtype=bool)
    nodes_xyz = np.array([[c.x, c.y, c.z] for c in mesh.cells], dtype=np.float64)
    t_monthly = np.asarray(mesh._t_monthly_c, dtype=np.float64)  # (N, 12)
    t_mean = t_monthly.mean(axis=1)

    dist, _ = _graph_distance_to_coast(
        mesh.cells, n, is_land, radius_km=config.radius_km, ocean_value=None
    )

    names = ["Moscow", "Urumqi", "Denver", "Harbin", "Beijing", "Chicago", "Anchorage"]

    def report(label, tm):
        rows = _errors(tm, nodes_xyz)
        err = {nm: (j, ju, a, am) for nm, _, j, ju, a, am in rows}
        print(f"  {label:>12} | " + " | ".join(f"{nm:>9}" for nm in names))
        print(
            f"  {'':>12} | "
            + " | ".join(f"J{err[nm][0]:+6.1f}/j{err[nm][1]:+5.1f}" for nm in names)
        )

    print("\n=== Jan/Jul error (model - observed, C) ===")
    report("baseline", t_monthly)

    ks = [float(x) for x in args.k.split(",")]
    lengths = [float(x) for x in args.L.split(",")]
    for length_km in lengths:
        cont = np.where(is_land, 1.0 - np.exp(-dist / length_km), 0.0)
        for k in ks:
            scale = 1.0 / (1.0 + k * cont)
            tm = t_mean[:, None] + (t_monthly - t_mean[:, None]) * scale[:, None]
            report(f"k={k:.1f},L={length_km:.0f}", tm)


if __name__ == "__main__":
    main()
