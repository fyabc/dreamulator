#!/usr/bin/env python3
"""Export UCC yearly descriptors + classification for the earth reference root —
from OBSERVED monthly climate, never from the engine.

The earth root world is the real-data anchor and is never built (CLAUDE.md
"模型态 vs obs 态分离").  This importer-side script is the obs-derived
counterpart of the engine's ``export_climate_layers`` yearly block: the shared
machinery (``import_solar_common.write_ucc_yearly``) reads the root's
``climate_monthly.msgpack`` (NCEP/NCAR R1 temperature + GPCP v2.3
precipitation, written by ``import_earth_climate``) and the mesh's
``water_class``, computes UCC descriptors (``compute_descriptors``) and the
current profile's classification (``classify_v1``), and writes
``climate_yearly.msgpack`` into the root maps dir.

Epistemic status: a declared, frozen transformation of observations — the same
class as the Beck 2018 Köppen column already on root (a published algorithm
over observed T/P), NOT engine output.  The file says so itself via
``data_source: "observation"`` + the ``provenance`` block; engine-built exports
carry ``data_source: "model"`` instead.

Usage:
    uv run python scripts/earth/export_earth_yearly.py
    uv run python scripts/earth/export_earth_yearly.py --output-dir <maps dir>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from dreamulator.import_solar_common import write_ucc_yearly  # noqa: E402

_DEFAULT_MAP = Path("data/worlds/earth/maps/planet_earth")

_PROVENANCE = {
    "temperature": "NCEP/NCAR R1 air.mon.ltm (2.5°, monthly climatology)",
    "precipitation": "GPCP v2.3 precip.mon.mean (2.5°, monthly climatology)",
    "note": "UCC descriptors + current-profile classification computed from the "
    "observed monthly series; no engine output involved.",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_DEFAULT_MAP,
        help="Earth root map dir containing climate_monthly.msgpack + the mesh file",
    )
    args = parser.parse_args()

    # data_source="observation" — the distinction the reference-anchor rule
    # cares about (root = real-data anchor, not engine output).
    combos = write_ucc_yearly(
        args.output_dir,
        data_source="observation",
        provenance=_PROVENANCE,
    )

    total_land = sum(combos.values())
    print(f"Land classes (top 8 of {total_land} land cells):")
    for k, v in sorted(combos.items(), key=lambda kv: -kv[1])[:8]:
        print(f"  {k:<28} {v:7d} ({v / total_land * 100:.1f}%)")


if __name__ == "__main__":
    main()
