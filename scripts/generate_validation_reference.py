#!/usr/bin/env python3
"""Regenerate the zonal-mean reference arrays in ``validate_climate.py``.

``_ZONAL_TEMP_REF`` / ``_ZONAL_PRECIP_REF`` are hard-coded 2° zonal means
(90 bands, 90N → 88S) used to score the climate engine against observed
climatology.  They are derived from:

    - temperature : NCEP/NCAR Reanalysis 1 ``air.mon.ltm.nc`` (long-term monthly mean)
    - precipitation: GPCP v2.3 ``precip.mon.mean.nc`` (mm/day)

Download both first (see docs/usage/climate-validation-workflow.md §3–4), then run::

    uv run python scripts/generate_validation_reference.py \
        --temp data/earth/NCEP_air_mon_ltm.nc \
        --precip data/earth/GPCP_precip_mon_mean.nc

and paste the printed lists into ``_ZONAL_TEMP_REF`` / ``_ZONAL_PRECIP_REF``.
"""

from __future__ import annotations

import argparse

import numpy as np
import xarray as xr

# 2° bands 90N .. 88S (90 values), matching _ZONAL_TEMP_REF indexing:
#   array[0]=90N, array[45]=0, array[89]=88S
_TARGET_LATS = np.array([90.0 - 2.0 * i for i in range(90)])


def _zonal_2deg(da: xr.DataArray) -> np.ndarray:
    z = da.mean(dim="lon")
    out = z.interp(lat=_TARGET_LATS, kwargs={"fill_value": "extrapolate"})
    return np.asarray(out.values)


def _print_array(name: str, values: np.ndarray, fmt: str) -> None:
    lines = []
    for i in range(0, len(values), 10):
        chunk = values[i : i + 10]
        lines.append("        " + ", ".join(fmt.format(v) for v in chunk) + ",")
    print(f"{name} = np.array(")
    print("    [")
    print("\n".join(lines))
    print("    ],")
    print("    dtype=np.float64,")
    print(")")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--temp", required=True, help="NCEP air.mon.ltm.nc path")
    parser.add_argument("--precip", required=True, help="GPCP precip.mon.mean.nc path")
    args = parser.parse_args()

    # Temperature (NCEP surface air is in °C; convert if stored in K)
    ncep = xr.open_dataset(args.temp, decode_times=False)
    air = ncep["air"]
    if air.attrs.get("units", "").lower().startswith("k"):
        air = air - 273.15
    temp = _zonal_2deg(air.mean(dim="time"))
    t_mean = np.average(temp, weights=np.cos(np.radians(_TARGET_LATS)))
    print(f"# global mean temp = {t_mean:.1f} °C\n")
    _print_array("_ZONAL_TEMP_REF", temp, "{:.1f}")

    # Precipitation (mm/day -> mm/yr)
    gpcp = xr.open_dataset(args.precip, decode_times=False)
    precip = _zonal_2deg(gpcp["precip"].mean(dim="time") * 365.25)
    p_mean = np.average(precip, weights=np.cos(np.radians(_TARGET_LATS)))
    print(f"# global mean precip = {p_mean:.0f} mm/yr\n")
    _print_array("_ZONAL_PRECIP_REF", precip, "{:.0f}")


if __name__ == "__main__":
    main()
