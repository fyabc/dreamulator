#!/usr/bin/env python3
"""Monsoon regional diagnosis — monthly precipitation against observed climatology.

Loads a built climate map (cvt_mesh.json + climate_monthly.msgpack; run
`dreamulator build` first) and compares the model's monthly precipitation in
key monsoon / control regions against observed climatology.  This is the
primary debug tool for the monsoon mechanism (tech debt 23/24): it shows
whether the seasonal cycle, phase, and magnitude of monsoon rainfall come out
in each region, and where tropical moisture transport is mis-routed.

Usage::

    uv run python scripts/diagnose_monsoon_regional.py
    uv run python scripts/diagnose_monsoon_regional.py \\
        --world nacrea --branch "" --map satellite_nacrea
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np


def _find_project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _load_mesh(world_dir: Path, planet_id: str, branch: str | None = None) -> object | None:
    from pydantic import TypeAdapter

    from dreamulator.map.export import decompress_mesh_bytes
    from dreamulator.map.models import CVTMesh

    search_dirs = [world_dir]
    if branch:
        search_dirs.insert(0, world_dir / "branches" / branch)
    for base in search_dirs:
        p = base / "maps" / planet_id / "cvt_mesh.json"
        if p.exists():
            return TypeAdapter(CVTMesh).validate_json(decompress_mesh_bytes(p.read_bytes()))
    return None


# Month labels: month_0 = vernal equinox (March).
_MONTHS = ["Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb"]

# Regions of interest: (name, lat_lo, lat_hi, lon_lo, lon_hi,
#                       observed wet-month P mm, observed dry-month P mm,
#                       observed annual P mm, observed Koeppen class).
# Observed values are station-scale climatology (order-of-magnitude anchors,
# not exact grid means) — enough to tell "monsoon present/absent/mis-phased".
REGIONS: list[tuple[str, float, float, float, float, float, float, float, str]] = [
    ("South China   23-28N 105-118E", 23, 28, 105, 118, 230, 40, 1700, "Cwa/Cfa"),
    ("North China   36-41N 112-120E", 36, 41, 112, 120, 170, 3, 570, "Cwa/Dwa"),
    ("Mediterranean 37-43N 5-15E   ", 37, 43, 5, 15, 110, 20, 800, "Csa"),
    ("Congo          3S-3N 15-28E  ", -3, 3, 15, 28, 160, 100, 1800, "Af"),
    ("India         15-25N 72-82E  ", 15, 25, 72, 82, 270, 15, 1000, "Aw/Am/Cwa"),
    ("Sahel         12-15N 10W-10E ", 12, 15, -10, 10, 180, 1, 550, "Aw/BSh"),
    ("Sahara        20-25N 5-15E   ", 20, 25, 5, 15, 10, 0, 30, "BWh"),
    ("Amazon         8S-0  70-55W  ", -8, 0, -70, -55, 250, 100, 2200, "Af"),
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--world", default="earth")
    parser.add_argument("--map", default="planet_earth", help="map/planet id under maps/")
    parser.add_argument("--world-dir", default="private/worlds")
    parser.add_argument("--branch", default="climate-dev", help="empty string for root world")
    args = parser.parse_args()

    root = _find_project_root()
    world_dir = root / args.world_dir / args.world
    branch = args.branch or None

    print(f"Loading mesh ({args.world}, branch={branch or '-'}, map={args.map}) ...")
    mesh = _load_mesh(world_dir, args.map, branch)
    if mesh is None:
        print("  ERROR: no mesh found (build the world first)")
        return

    import msgpack

    mdir = world_dir / (f"branches/{args.branch}/" if branch else "") / "maps" / args.map
    monthly_path = mdir / "climate_monthly.msgpack"
    if not monthly_path.exists():
        print(f"  ERROR: {monthly_path} not found")
        return
    raw = msgpack.unpackb(monthly_path.read_bytes(), raw=False)
    n = raw["num_cells"]
    p_monthly = np.frombuffer(raw["p_monthly"], dtype=np.float32).reshape(n, 12)

    lat = np.array([c.lat for c in mesh.cells])
    lon = np.array([c.lon for c in mesh.cells])
    is_land = np.array([c.elevation >= 0.0 for c in mesh.cells])
    koppen = [c.koppen_class or "Ocean" for c in mesh.cells]

    header = f"{'region':<34} {'n':>5} {'sim ann':>8} {'sim wet':>12} {'sim dry':>12}"
    print(f"\n{header}  obs ann/wet/dry")
    for name, la0, la1, lo0, lo1, ob_wet, ob_dry, ob_ann, ob_cls in REGIONS:
        m = is_land & (lat >= la0) & (lat <= la1) & (lon >= lo0) & (lon <= lo1)
        if not m.any():
            print(f"{name:<34} no land cells")
            continue
        pm = p_monthly[m].mean(axis=0)
        i_max, i_min = int(pm.argmax()), int(pm.argmin())
        # dominant simulated Koeppen class in the region
        classes: dict[str, int] = {}
        for i in np.flatnonzero(m):
            classes[koppen[i]] = classes.get(koppen[i], 0) + 1
        dom = max(classes, key=classes.get)  # type: ignore[arg-type]
        print(
            f"{name:<34} {int(m.sum()):>5} {pm.sum():>8.0f} "
            f"{pm[i_max]:>5.0f}@{_MONTHS[i_max]:<3} {pm[i_min]:>5.0f}@{_MONTHS[i_min]:<3}"
            f"   {ob_ann:>4.0f}/{ob_wet:.0f}/{ob_dry:.0f} ({ob_cls})"
        )
        mix = ", ".join(f"{k}:{v}" for k, v in sorted(classes.items(), key=lambda kv: -kv[1])[:4])
        print(f"{'':<34} {'':>5} {'':>8} sim classes: {dom} ({classes[dom]}/{int(m.sum())}); {mix}")


if __name__ == "__main__":
    main()
