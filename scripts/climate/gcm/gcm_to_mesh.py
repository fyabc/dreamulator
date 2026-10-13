#!/usr/bin/env python
"""Project an ExoPlaSim run onto a world's CVT mesh for GCM-vs-EBM comparison.

Writes a mesh file in the engine's format with the climate fields replaced by
the GCM's (see dreamulator.gcm.to_mesh), plus a ``.gcm.json`` provenance file.
Render it with ``dreamulator export layers <world> --mesh <out>``.  Needs the
``[gcm]`` environment (netCDF4).

Example:
    python scripts/climate/gcm/gcm_to_mesh.py --world data/worlds/nacrea \
        --planet satellite_nacrea --nc private/gcm/runs/t42f/cold/MOST.00000.nc \
        --out private/gcm/mesh/nacrea_t42_712/cvt_mesh.msgpack.gz
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[3] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from dreamulator.gcm.mapping import map_world  # noqa: E402
from dreamulator.gcm.to_mesh import project_to_mesh  # noqa: E402


def steps_per_model_day(run_dir: Path) -> float:
    """Integration steps per model day from the run's MPSTEP (minutes), default 45."""
    namelist = run_dir / "plasim_namelist"
    mpstep = 45.0
    if namelist.exists():
        match = re.search(r"MPSTEP\s*=\s*([0-9.]+)", namelist.read_text(encoding="utf-8"))
        if match:
            mpstep = float(match.group(1))
    return 1440.0 / mpstep


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--world", required=True, help="world directory, e.g. data/worlds/nacrea")
    ap.add_argument("--planet", required=True, help="planet id, e.g. satellite_nacrea")
    ap.add_argument("--nc", required=True, help="postprocessed MOST.00000.nc")
    ap.add_argument("--mesh", default=None, help="source mesh (default: the world's built mesh)")
    ap.add_argument("--out", required=True, help="output mesh path (…/cvt_mesh.msgpack.gz)")
    ap.add_argument("--tail-years", type=int, default=5)
    ap.add_argument("--sea-level", type=float, default=0.0)
    args = ap.parse_args(argv)

    world = Path(args.world)
    if args.mesh:
        mesh = Path(args.mesh)
    else:
        from dreamulator.map.export import find_mesh_file

        found = find_mesh_file(world / "maps" / args.planet)
        if found is None:
            ap.error(f"no built mesh under {world / 'maps' / args.planet}; build the world first")
        mesh = found
    params = map_world(world, args.planet)
    nc = Path(args.nc)
    summary = project_to_mesh(
        nc,
        mesh,
        args.out,
        orbital_year_days=params.year,
        gravity_m_s2=params.gravity,
        steps_per_model_day=steps_per_model_day(nc.parent),
        tail_years=args.tail_years,
        sea_level_m=args.sea_level,
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
