#!/usr/bin/env python
"""Project an ExoPlaSim run onto a world's CVT mesh.

``--out`` writes a mesh file in the engine's format with the climate fields
replaced by the GCM's (see dreamulator.gcm.to_mesh), plus a ``.gcm.json``
summary; render it with ``dreamulator export layers <world> --mesh <out>``.
``--emit-fields`` writes the pinned field set of a frozen-climate branch
(``climate_source: gcm``), plus its tracked ``.provenance.json``.  Needs the
``[gcm]`` environment (netCDF4).

Examples:
    python scripts/climate/gcm/gcm_to_mesh.py --world data/worlds/nacrea \
        --planet satellite_nacrea --nc <gcm-workdir>/runs/t42n/cold_712/MOST.00000.nc \
        --out <gcm-workdir>/mesh/nacrea_t42_712/cvt_mesh.msgpack.gz
    python scripts/climate/gcm/gcm_to_mesh.py --world data/worlds/nacrea \
        --planet satellite_nacrea --nc <gcm-workdir>/runs/t42n/cold_712/MOST.00000.nc \
        --emit-fields \
        data/worlds/nacrea/branches/gcm-t42-712/layers/climate/input/gcm_fields.msgpack.gz
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
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


def run_provenance(run_dir: Path) -> dict[str, object]:
    """The run's manifest (configuration, pCO₂ in ppm, versions) and the code commit."""
    prov: dict[str, object] = {}
    manifest_file = run_dir / "manifest.json"
    if manifest_file.exists():
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        prov["run_manifest"] = {k: v for k, v in manifest.items() if k != "params"}
        kwargs = manifest.get("configure_kwargs", {})
        if kwargs.get("pCO2") and kwargs.get("pressure"):
            prov["pco2_ppm"] = round(kwargs["pCO2"] / kwargs["pressure"] * 1e6, 1)
    try:
        commit = subprocess.run(
            ["git", "describe", "--always", "--dirty", "--abbrev=12"],
            capture_output=True,
            text=True,
            check=True,
            cwd=SRC,
        ).stdout.strip()
        prov["code_commit"] = commit
    except (OSError, subprocess.CalledProcessError):
        pass
    return prov


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--world", required=True, help="world directory, e.g. data/worlds/nacrea")
    ap.add_argument("--planet", required=True, help="planet id, e.g. satellite_nacrea")
    ap.add_argument("--nc", required=True, help="postprocessed MOST.00000.nc")
    ap.add_argument("--mesh", default=None, help="source mesh (default: the world's built mesh)")
    ap.add_argument("--out", default=None, help="output mesh path (…/cvt_mesh.msgpack.gz)")
    ap.add_argument(
        "--emit-fields",
        default=None,
        help="output field-set path for a frozen-climate branch (…/gcm_fields.msgpack.gz)",
    )
    ap.add_argument("--tail-years", type=int, default=5)
    ap.add_argument("--sea-level", type=float, default=0.0)
    args = ap.parse_args(argv)
    if args.out is None and args.emit_fields is None:
        ap.error("pass --out and/or --emit-fields")

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
        fields_out=args.emit_fields,
        extra_provenance=run_provenance(nc.parent),
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
