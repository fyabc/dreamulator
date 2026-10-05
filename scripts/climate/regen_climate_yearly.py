"""Regenerate climate_yearly.msgpack for engine-built worlds without a rebuild.

The yearly UCC file is a *derived product* of the persisted monthly series,
but the in-memory ``_t_monthly_c`` stash does not survive a mesh save/load
round trip — so after a classifier/profile change the engine worlds would
otherwise need a full climate rebuild (GW6-scale) just to refresh a
descriptors file.  This script dequantizes ``climate_monthly.msgpack``
(int16, resolution ~0.001 °C / ~0.04 mm — far below the data's own precision)
and re-runs the engine-side writer directly.

Caveat: the regenerated values pass through the monthly quantization, so they
can differ from a fresh full-build export in the last digits (threshold-
adjacent cells can in principle flip; the quantization resolution makes this
rare).  Canonical freshness for a release still comes from a full build.

Solar-System bodies and the earth root are NOT handled here — their yearly
files regenerate through their own importers / ``export_earth_yearly.py``
(``write_ucc_yearly`` reads the monthly file + mesh from disk directly).

Usage:
    uv run python scripts/climate/regen_climate_yearly.py <world> \
        [--planet satellite_nacrea] [--branch some-branch] [--data-dir DIR]

Runs over every planet map dir of the world (or branch) by default; reports
per-planet -H highland and modifier statistics.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import msgpack
import numpy as np

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "src"))

from dreamulator.map.export import (  # noqa: E402
    find_mesh_file,
    load_cvt_mesh_model,
    write_engine_climate_yearly,
)


def _load_monthly(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Dequantize climate_monthly.msgpack → (t (N,12) °C, p (N,12) mm)."""
    with path.open("rb") as f:
        d = msgpack.unpackb(f.read())
    n, m = int(d["num_cells"]), int(d["months"])

    def deq(prefix: str) -> np.ndarray:
        q = np.frombuffer(d[f"{prefix}_monthly"], dtype="<i2").astype(np.float64)
        return (q * float(d[f"{prefix}_scale"]) + float(d[f"{prefix}_offset"])).reshape(n, m)

    return deq("t"), deq("p")


def _modifier_stats(path: Path) -> str:
    with path.open("rb") as f:
        y = msgpack.unpackb(f.read())
    mods = np.frombuffer(y["ucc_modifiers"], dtype=np.uint8)
    n = mods.shape[0]
    supply = np.frombuffer(y["ucc_supply"], dtype=np.uint8)
    return (
        f"continental {np.count_nonzero(mods & 1) / n:.1%}, "
        f"water_stress {np.count_nonzero(mods & 2) / n:.1%}, "
        f"highland(-H) {np.count_nonzero(mods & 4) / n:.1%} "
        f"(of {n} cells, {np.count_nonzero(supply != 255) / n:.0%} with a supply class)"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("world", help="world name, e.g. nacrea or earth")
    parser.add_argument("--planet", default=None, help="restrict to one planet map dir")
    parser.add_argument("--branch", default=None, help="branch name under branches/")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=_ROOT / "data/worlds",
        help="worlds data directory (default: data/worlds)",
    )
    args = parser.parse_args()

    world_dir = args.data_dir / args.world
    base = world_dir / "branches" / args.branch if args.branch else world_dir
    maps_dir = base / "maps"
    if not maps_dir.is_dir():
        sys.exit(f"no maps dir under {base}")

    dirs = sorted(d for d in maps_dir.iterdir() if d.is_dir())
    if args.planet:
        dirs = [d for d in dirs if d.name == args.planet]
    if not dirs:
        sys.exit(f"no planet map dirs under {maps_dir} (filter: {args.planet})")

    for map_dir in dirs:
        monthly = map_dir / "climate_monthly.msgpack"
        mesh_path = find_mesh_file(map_dir)
        if not monthly.exists() or mesh_path is None:
            print(f"[skip] {map_dir.name}: no monthly series or mesh")
            continue
        t, p = _load_monthly(monthly)
        mesh = load_cvt_mesh_model(mesh_path)
        write_engine_climate_yearly(mesh, map_dir, t_monthly=t, p_monthly=p)
        print(
            f"[ok]   {args.world}"
            f"{'/' + args.branch if args.branch else ''}/{map_dir.name}: "
            f"{_modifier_stats(map_dir / 'climate_yearly.msgpack')}"
        )


if __name__ == "__main__":
    main()
