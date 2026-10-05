#!/usr/bin/env python
"""Generate an ExoPlaSim ``.sra`` land mask from a dreamulator world mesh.

Nearest-cell regrid of the mesh land/ocean classification onto the model's
Gaussian grid (see dreamulator.gcm.surface for the .sra format notes).
Flat land (no topography) — a ``topomap`` (code 129) is a later step.

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

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from dreamulator.gcm.surface import make_landmap  # noqa: E402

RESOLUTIONS = {"T21": (32, 64), "T42": (64, 128), "T63": (96, 192)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--world", required=True, help="label for the log line")
    ap.add_argument("--mesh", required=True, help="path to cvt_mesh.msgpack.gz")
    ap.add_argument("--resolution", default="T21", choices=sorted(RESOLUTIONS))
    ap.add_argument("--out", required=True, help="output .sra path")
    args = ap.parse_args(argv)

    nlat, nlon = RESOLUTIONS[args.resolution]
    out, frac = make_landmap(args.mesh, args.out, nlat=nlat, nlon=nlon)
    print(f"[{args.world}] {args.resolution} land mask -> {out} (land fraction {frac:.3f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
