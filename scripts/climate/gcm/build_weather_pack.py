#!/usr/bin/env python
"""Build a weather layer pack (dreamulator.gcm.weather_pack) from an ExoPlaSim run.

The run must have written instantaneous snapshots (``"snapshots": N`` in
``--configure`` of run_exoplasim.py); the pack reads ``snapshots/MOST_SNAP.*.nc``
and the run's ``manifest.json`` (radius, gravity, rotation period, orbital year)
and ``plasim_namelist`` (time step).  Needs the ``[gcm]`` environment (netCDF4).

Example:
    python scripts/climate/gcm/build_weather_pack.py <gcm-workdir>/runs/t42r/hf_712 \
        --out exports/weather/nacrea-gcm-t42-712
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

from dreamulator.gcm.to_mesh import public_provenance  # noqa: E402
from dreamulator.gcm.weather_pack import PackCalendar, build_pack  # noqa: E402

EARTH_RADIUS_KM = 6371.0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("run", type=Path, help="ExoPlaSim run directory with snapshots/")
    ap.add_argument("--out", type=Path, required=True, help="pack directory to write")
    ap.add_argument("--snapshot", type=Path, default=None, help="snapshot file (default: newest)")
    ap.add_argument(
        "--interval-h",
        type=float,
        default=None,
        help="keep one frame per this many hours (rounded to whole snapshots; default: all)",
    )
    args = ap.parse_args(argv)

    manifest = json.loads((args.run / "manifest.json").read_text(encoding="utf-8"))
    kw = manifest["configure_kwargs"]
    namelist = (args.run / "plasim_namelist").read_text(encoding="utf-8")
    match = re.search(r"MPSTEP\s*=\s*([0-9.]+)", namelist)
    mpstep_min = float(match.group(1)) if match else 45.0
    sidereal_day_h = float(kw["rotationperiod"]) * 24.0
    hours_per_step = mpstep_min / 60.0
    match = re.search(r"NSTPS\s*=\s*([0-9]+)", namelist)
    snap_h = hours_per_step * (int(match.group(1)) if match else 1)
    stride = max(1, round(args.interval_h / snap_h)) if args.interval_h else 1
    snapshot = args.snapshot or sorted((args.run / "snapshots").glob("MOST_SNAP.*.nc"))[-1]
    rotation = 2.0 * 3.141592653589793 / (sidereal_day_h * 3600.0)
    meta = build_pack(
        snapshot,
        args.out,
        calendar=PackCalendar(
            hours_per_step=hours_per_step,
            sidereal_day_h=sidereal_day_h,
            orbital_year_days=float(kw["year"]),
        ),
        radius_km=float(kw["radius"]) * EARTH_RADIUS_KM,
        gravity_m_s2=float(kw["gravity"]),
        rotation_rad_s=rotation,
        stride=stride,
        provenance=public_provenance(
            {
                "source_nc": str(snapshot),
                "pco2_ppm": round(float(kw.get("pCO2", 0.0)) / 1.01325e-6, 1),
                "run_command": manifest.get("command"),
                "code_version": manifest.get("code_version"),
                "configure_kwargs": kw,
            }
        ),
    )
    cal = meta["calendar"]
    print(
        f"wrote {args.out}: {meta['frames']} frames every {cal['frame_interval_h']} h, "
        f"solar day {cal['solar_day_h_diagnosed']} h, {meta['cyclones']['count']} cyclone tracks "
        f"{meta['cyclones']['by_kind']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
