#!/usr/bin/env python3
"""Generate monthly (seasonal-cycle) zonal-mean reference from GPCP + NCEP.

Turns the two NetCDF climatologies into 12-month zonal-mean arrays at 2° latitude
bands (90 bands, 90N → 88S) for seasonal validation of the climate engine:

    - temperature   : NCEP/NCAR Reanalysis 1 ``air.mon.ltm.nc`` (12-month ltm, °C)
    - precipitation : GPCP v2.3 ``precip.mon.mean.nc`` (monthly mean, mm/day → mm/month)

Both files live in ``private/tmp/climatology/``. Output is a JSON reference
(``monthly_zonal_reference.json``) plus printed Python literals for pasting into
``validate_climate.py``.

Usage::

    uv run python scripts/generate_monthly_reference.py \
        --temp private/tmp/climatology/ncep_air.mon.ltm.nc \
        --precip private/tmp/climatology/gpcp_precip.mon.mean.nc \
        --output private/tmp/climatology/monthly_zonal_reference.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import xarray as xr

# 2° bands 90N .. 88S (90 values), matching _ZONAL_TEMP_REF indexing:
#   array[0]=90N, array[45]=0, array[89]=88S
_TARGET_LATS = np.array([90.0 - 2.0 * i for i in range(90)])

# Days per calendar month (Feb averaged for leap years over a climatology).
_DAYS = np.array([31, 28.25, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31])

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _zonal_2deg(da: xr.DataArray) -> np.ndarray:
    z = da.mean(dim="lon")
    out = z.interp(lat=_TARGET_LATS, kwargs={"fill_value": "extrapolate"})
    return np.asarray(out.values)


def _print_array(name: str, values: np.ndarray, fmt: str) -> None:
    lines = []
    for i in range(values.shape[0]):
        chunk = values[i]
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
    parser.add_argument("--output", default=None, help="Output JSON path (optional)")
    args = parser.parse_args()

    # --- Temperature (NCEP monthly long-term mean; time already = 12 months) ---
    ncep = xr.open_dataset(args.temp, decode_times=False)
    air = ncep["air"]
    if air.attrs.get("units", "").lower().startswith("k"):
        air = air - 273.15
    if air.sizes.get("time") != 12:
        raise SystemExit(f"NCEP air.mon.ltm.nc expected 12 months, got {air.sizes.get('time')}")
    temp_monthly = np.stack([_zonal_2deg(air.isel(time=m)) for m in range(12)])  # (12, 90)

    # --- Precipitation (GPCP monthly series → 12-month climatology, mm/month) ---
    gpcp = xr.open_dataset(args.precip, decode_times=False)
    precip = gpcp["precip"]  # mm/day, time = N contiguous months since 1979-01
    n_months = precip.sizes["time"]
    # Drop a trailing partial year so the series is a whole number of years
    n_years = n_months // 12
    precip = precip.isel(time=slice(0, n_years * 12))
    reshaped = precip.values.reshape(n_years, 12, -1, precip.sizes["lon"])
    clim = reshaped.mean(axis=0)  # (12, lat, lon)
    precip_da = xr.DataArray(
        clim,
        dims=("time", "lat", "lon"),
        coords={"time": np.arange(12), "lat": precip["lat"], "lon": precip["lon"]},
    )
    # mm/day → mm/month (using calendar month lengths)
    precip_monthly = np.stack(
        [_zonal_2deg(precip_da.isel(time=m)) * _DAYS[m] for m in range(12)]
    )  # (12, 90)

    # --- Report ---
    temp_annual = temp_monthly.mean(axis=0)
    precip_annual = precip_monthly.sum(axis=0)
    t_mean = np.average(temp_annual, weights=np.cos(np.radians(_TARGET_LATS)))
    p_mean = np.average(precip_annual, weights=np.cos(np.radians(_TARGET_LATS)))
    print(f"# NCEP  : 12 months (ltm); global annual mean temp = {t_mean:.1f} °C")
    print(f"# GPCP  : {n_months} months → {n_years} full years; annual precip = {p_mean:.0f} mm/yr")
    print()

    _print_array("_ZONAL_TEMP_MONTHLY_REF", temp_monthly, "{:.1f}")
    _print_array("_ZONAL_PRECIP_MONTHLY_REF", precip_monthly, "{:.0f}")

    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "description": "Monthly zonal-mean climatology at 2° bands (90N→88S)",
            "lat_bands_deg": _TARGET_LATS.tolist(),
            "months": _MONTHS,
            "temperature_c": temp_monthly.round(1).tolist(),
            "precipitation_mm_per_month": precip_monthly.round(0).tolist(),
            "sources": {
                "temperature": "NCEP/NCAR Reanalysis 1 air.mon.ltm.nc (1981-2010)",
                "precipitation": "GPCP v2.3 precip.mon.mean.nc (1979-present)",
            },
        }
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"# JSON saved: {out}")


if __name__ == "__main__":
    main()
