#!/usr/bin/env python
"""Generate an ExoPlaSim ``.sra`` land mask from a dreamulator world mesh.

Nearest-cell regrid of the mesh land/ocean classification onto the model's
Gaussian grid (see dreamulator.gcm.surface for the .sra format notes).
With ``--topo-out`` it also writes the surface-geopotential file (code 129):
grid-box mean land elevation × the planet's gravity, which is taken from the
world inputs (``--planet``) so it cannot drift from the run's gravity.

Examples:
    python scripts/climate/gcm/make_landmap.py --world earth \
        --mesh data/worlds/earth/maps/planet_earth/cvt_mesh.msgpack.gz \
        --out gcm_surf/earth_N032_surf_0172.sra
    python scripts/climate/gcm/make_landmap.py --world nacrea \
        --mesh data/worlds/nacrea/maps/satellite_nacrea/cvt_mesh.msgpack.gz \
        --out gcm_surf/nacrea_N032_surf_0172.sra
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[3] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from dreamulator.gcm.surface import make_landmap, make_topomap  # noqa: E402

RESOLUTIONS = {
    "T21": (32, 64),
    "T42": (64, 128),
    "T63": (96, 192),
    "T85": (128, 256),
    "T106": (160, 320),
    "T127": (192, 384),
    "T170": (256, 512),
}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--world",
        required=True,
        help="world name or directory (log label; resolved for gravity with --topo-out)",
    )
    ap.add_argument("--mesh", required=True, help="path to cvt_mesh.msgpack.gz")
    ap.add_argument("--resolution", default="T21", choices=sorted(RESOLUTIONS))
    ap.add_argument("--out", required=True, help="output .sra path")
    ap.add_argument("--topo-out", default=None, help="also write the code-129 geopotential .sra")
    ap.add_argument("--planet", default=None, help="planet id for gravity (needed by --topo-out)")
    args = ap.parse_args(argv)

    nlat, nlon = RESOLUTIONS[args.resolution]
    out, frac = make_landmap(args.mesh, args.out, nlat=nlat, nlon=nlon)
    print(f"[{args.world}] {args.resolution} land mask -> {out} (land fraction {frac:.3f})")
    if args.topo_out:
        if not args.planet:
            ap.error("--topo-out needs --planet (gravity comes from the world inputs)")
        from dreamulator.gcm.mapping import map_world

        world = Path(args.world)
        if not world.is_dir():
            world = Path(__file__).resolve().parents[3] / "data" / "worlds" / args.world
        gravity = map_world(world, args.planet).gravity
        topo, stats = make_topomap(args.mesh, args.topo_out, gravity, nlat=nlat, nlon=nlon)
        print(
            f"[{args.world}] {args.resolution} geopotential -> {topo} (g={gravity:.3f} m/s², "
            f"mean land {stats['mean_land_elevation_m']:.0f} m, "
            f"max {stats['max_elevation_m']:.0f} m)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
