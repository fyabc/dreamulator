#!/usr/bin/env python3
"""Generate the per-grid observed-climatology reference for the Δ* layers.

The frontend's error heatmaps diff each cell against a **per-grid** observed
climatology — NCEP/NCAR Reanalysis-1 (surface air temperature, SLP, near-surface
u/v wind) + GPCP v2.3 (precipitation) + SODA v3.15.2 (surface ocean currents) —
bundled on their **native grids**, which the frontend bilinearly samples at each
cell's (lat, lon).

Each dataset keeps its own grid (they are offset from each other): resampling one
onto another's grid introduces large error in steep-gradient regions (the
Bangladesh monsoon coast reads ~20 % low).  So the TS module carries independent
grids + a sampler parameterised by each.

Outputs ``frontend/src/viewers/map/spatialReference.ts``.  Regenerate whenever the
source climatology changes (rare — fixed Earth reference):

    uv run python scripts/earth/generate_spatial_reference.py \\
        --temp private/tmp/climatology/ncep_air.mon.ltm.nc \\
        --precip private/tmp/climatology/gpcp_precip.mon.mean.nc \\
        --slp private/tmp/climatology/ncep_slp.mon.ltm.nc \\
        --wind-u private/tmp/climatology/ncep_uwnd.mon.ltm.nc \\
        --wind-v private/tmp/climatology/ncep_vwnd.mon.ltm.nc \\
        --current private/tmp/climatology/soda_currents_mon_clim.nc

The extra fields (SLP / wind / currents) are optional: omit them to regenerate
only the temperature/precipitation reference.

Earth-only: a fictional world has no observed climatology to diff against.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import xarray as xr


def _fmt_ints(values: np.ndarray, per_line: int = 12) -> str:
    lines = []
    for i in range(0, len(values), per_line):
        lines.append("  " + ", ".join(str(int(v)) for v in values[i : i + per_line]) + ",")
    return "\n".join(lines)


def _load_annual(nc_path: Path, var: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(12, lat, lon) monthly climatology → annual mean + native grid."""
    ds = xr.open_dataset(nc_path, decode_times=False)
    data = ds[var].mean(dim="time")
    lat = np.asarray(data.lat.values)
    lon = np.asarray(data.lon.values)
    arr = np.asarray(data.values)
    ds.close()
    return arr, lat, lon


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--temp", required=True, help="NCEP air.mon.ltm.nc")
    parser.add_argument("--precip", required=True, help="GPCP precip.mon.mean.nc")
    parser.add_argument("--slp", help="NCEP slp.mon.ltm.nc (monthly ΔSLP)")
    parser.add_argument("--wind-u", help="NCEP uwnd.mon.ltm.nc (annual mean u)")
    parser.add_argument("--wind-v", help="NCEP vwnd.mon.ltm.nc (annual mean v)")
    parser.add_argument("--current", help="SODA soda_currents_mon_clim.nc (annual mean u/v)")
    parser.add_argument(
        "--output",
        default="frontend/src/viewers/map/spatialReference.ts",
        help="output TS module path",
    )
    args = parser.parse_args()

    # Temperature: NCEP air (°C), monthly climatology → annual mean, native grid
    # (lat 90 → −90 descending, lon 0 → 357.5).
    ncep = xr.open_dataset(args.temp, decode_times=False)
    air = ncep["air"]
    if air.attrs.get("units", "").lower().startswith("k"):
        air = air - 273.15
    t = air.mean(dim="time")
    t_lat = np.asarray(t.lat.values)  # 90 → −90
    t_lon = np.asarray(t.lon.values)  # 0 → 357.5
    temp = np.asarray(t.values)  # (nlat, nlon) lat-major, north→south
    ncep.close()

    # Precipitation: GPCP (mm/day), monthly → annual → mm/yr, native grid
    # (lat −88.75 → 88.75 ascending, lon 1.25 → 358.75).
    gpcp = xr.open_dataset(args.precip, decode_times=False)
    p = gpcp["precip"].mean(dim="time") * 365.25
    p_lat = np.asarray(p.lat.values)  # −88.75 → 88.75
    p_lon = np.asarray(p.lon.values)  # 1.25 → 358.75
    precip = np.asarray(p.values)  # (nlat, nlon) lat-major, south→north
    gpcp.close()

    # ── Optional extra fields (climate-development diagnostics) ───────────────
    # Monthly ΔSLP = SLP − same-month OCEAN band mean (M2-A0③, 2026-09-18): the
    # canonical pressure-anomaly definition, matching the engine's
    # pressure_anomaly_monthly ΔT reference (land–sea contrast, annual mean
    # included) and the obs importer.  The ocean mask comes from the SODA
    # current field's validity (NaN = land), so --slp requires --current.
    slp_anom = slp_lat = slp_lon = None
    if args.slp:
        if not args.current:
            parser.error(
                "--slp requires --current (the SODA field is the ocean-mask "
                "source for the canonical ΔSLP reference)"
            )
        ds = xr.open_dataset(args.slp, decode_times=False)
        slp = ds["slp"]
        slp_lat = np.asarray(slp.lat.values)
        slp_lon = np.asarray(slp.lon.values)
        slp_arr = np.asarray(slp.values)  # (12, nlat, nlon)
        ds.close()

        from dreamulator.import_earth_climate import ocean_band_anomaly_monthly

        soda = xr.open_dataset(args.current, decode_times=False)
        soda_u0 = np.asarray(soda["u"].isel(month=0).values)  # land = NaN
        soda_lat = np.asarray(soda["u"].lat.values)
        soda_lon = np.asarray(soda["u"].lon.values)
        soda.close()
        soda_valid = np.isfinite(soda_u0)
        # Nearest SODA gridpoint per SLP grid row/column (circular in lon).
        ii = np.abs(slp_lat[:, None] - soda_lat[None, :]).argmin(axis=1)
        _dlon = np.abs(((slp_lon[:, None] - soda_lon[None, :] + 180.0) % 360.0) - 180.0)
        jj = _dlon.argmin(axis=1)
        ocean_grid = soda_valid[np.ix_(ii, jj)]  # (nlat, nlon)

        _nlat, _nlon = slp_arr.shape[1], slp_arr.shape[2]
        _members = slp_arr.transpose(1, 2, 0).reshape(-1, 12)
        _member_lats = np.repeat(slp_lat, _nlon)
        _anom = ocean_band_anomaly_monthly(_members, _member_lats, ocean_grid.ravel())
        slp_anom = _anom.reshape(_nlat, _nlon, 12).transpose(2, 0, 1)  # (12, nlat, nlon)

    # NCEP annual-mean u/v wind (m/s).
    uwnd = uw_lat = uw_lon = None
    vwnd = vw_lat = vw_lon = None
    if args.wind_u and args.wind_v:
        uwnd, uw_lat, uw_lon = _load_annual(Path(args.wind_u), "uwnd")
        vwnd, vw_lat, vw_lon = _load_annual(Path(args.wind_v), "vwnd")

    # SODA annual-mean surface (lev 0 ≈ 5 m) u/v currents (m/s).
    cur_u = cur_lat = cur_lon = None
    cur_v = None
    if args.current:
        ds = xr.open_dataset(args.current, decode_times=False)
        cu = ds["u"].mean(dim="month")
        cv = ds["v"].mean(dim="month")
        cur_lat = np.asarray(cu.lat.values)
        cur_lon = np.asarray(cu.lon.values)
        # SODA has NaN over land/missing cells — cast them to 0 m/s (land has no
        # surface current to diff against; the frontend draws only ocean cells).
        cur_u = np.nan_to_num(np.asarray(cu.values), nan=0.0)
        cur_v = np.nan_to_num(np.asarray(cv.values), nan=0.0)
        ds.close()

    # Encode (compact ints): temp ×10 (0.1 °C), precip ×1 (mm/yr), ΔSLP ×10
    # (0.1 hPa), wind ×100 (0.01 m/s), current ×1000 (0.001 m/s).
    temp_flat = np.rint(temp * 10).astype(np.int32).ravel()
    precip_flat = np.rint(precip).astype(np.int32).ravel()

    def grid_meta(lat: np.ndarray, lon: np.ndarray) -> str:
        dlat = float(lat[1] - lat[0])
        dlon = float(lon[1] - lon[0])
        return (
            f"{{ nlat: {len(lat)}, nlon: {len(lon)}, lat0: {float(lat[0])}, dlat: {dlat}, "
            f"lon0: {float(lon[0])}, dlon: {dlon} }}"
        )

    # Assemble the optional-field TS blocks (arrays + samplers + grids).
    extra_arrays = ""
    extra_samplers = ""

    if slp_anom is not None:
        # 12 × (nlat × nlon), month-major.
        slp_flat = np.rint(slp_anom * 10).astype(np.int32).ravel()
        extra_arrays += f"""
// monthly ΔSLP ×10 (0.1 hPa), month-major (month 0..11 → nlat × nlon), {slp_lat[0]}→{slp_lat[-1]}
// Canonical ΔP (M2-A0③): SLP − same-month 5°-band OCEAN mean (land–sea contrast,
// annual mean included — matches the engine's pressure_anomaly_monthly).
export const OBS_SLP_ANOM_X10: number[] = [
{_fmt_ints(slp_flat)}
]

export const OBS_SLP_GRID = {grid_meta(slp_lat, slp_lon)}
export const OBS_SLP_MONTHS = 12
"""
        extra_samplers += """
/** Bilinear-sample the observed monthly ΔSLP (hPa) at (lat, lon, month 0..11). */
export function observedSlpAnomAt(latDeg: number, lonDeg: number, month: number): number {
  return _sample(latDeg, lonDeg, OBS_SLP_ANOM_X10, OBS_SLP_GRID, month) / 10
}
"""

    if uwnd is not None and vwnd is not None:
        uw_flat = np.rint(uwnd * 100).astype(np.int32).ravel()
        vw_flat = np.rint(vwnd * 100).astype(np.int32).ravel()
        extra_arrays += f"""
// annual-mean near-surface wind ×100 (0.01 m/s), lat-major
export const OBS_UWND_X100: number[] = [
{_fmt_ints(uw_flat)}
]
export const OBS_VWND_X100: number[] = [
{_fmt_ints(vw_flat)}
]

export const OBS_WIND_GRID = {grid_meta(uw_lat, uw_lon)}
"""
        extra_samplers += """
/** Bilinear-sample the observed annual-mean wind (m/s) at (lat, lon) → [u, v]. */
export function observedWindAt(latDeg: number, lonDeg: number): [number, number] {
  return [
    _sample(latDeg, lonDeg, OBS_UWND_X100, OBS_WIND_GRID, 0) / 100,
    _sample(latDeg, lonDeg, OBS_VWND_X100, OBS_WIND_GRID, 0) / 100,
  ]
}
"""

    if cur_u is not None and cur_v is not None:
        cu_flat = np.rint(cur_u * 1000).astype(np.int32).ravel()
        cv_flat = np.rint(cur_v * 1000).astype(np.int32).ravel()
        extra_arrays += f"""
// annual-mean surface ocean current ×1000 (0.001 m/s), lat-major
export const OBS_CUR_U_X1000: number[] = [
{_fmt_ints(cu_flat)}
]
export const OBS_CUR_V_X1000: number[] = [
{_fmt_ints(cv_flat)}
]

export const OBS_CUR_GRID = {grid_meta(cur_lat, cur_lon)}
"""
        extra_samplers += """
/** Bilinear-sample the observed annual-mean surface current (m/s) at (lat, lon) → [u, v]. */
export function observedCurrentAt(latDeg: number, lonDeg: number): [number, number] {
  return [
    _sample(latDeg, lonDeg, OBS_CUR_U_X1000, OBS_CUR_GRID, 0) / 1000,
    _sample(latDeg, lonDeg, OBS_CUR_V_X1000, OBS_CUR_GRID, 0) / 1000,
  ]
}
"""

    body = f"""/**
 * Earth per-grid observed climatology (native grids).
 *
 * Generated by ``scripts/earth/generate_spatial_reference.py`` from NCEP/NCAR
 * Reanalysis-1 (surface air temperature, SLP, near-surface u/v wind), GPCP v2.3
 * (precipitation) and SODA v3.15.2 (surface ocean currents).  This is the
 * per-grid reference for the Δ* error heatmaps — unlike the old zonal mean it
 * carries the real orography (Tibet ≈ −5.5 °C, not the +18 °C zonal mean) and
 * land/ocean contrast, so the deviation reflects the *model's* error, not
 * elevation.
 *
 * The datasets keep their native grids (offset from each other); resampling one
 * onto another corrupts steep-gradient regions.  Each sampler is parameterised
 * by its own grid metadata.
 *
 * Earth-only: a fictional world has no observed climatology to diff against.
 * Do not hand-edit; regenerate with the script.
 */

// temperature ×10 (0.1 °C), lat-major, north→south
export const OBS_TEMP_X10: number[] = [
{_fmt_ints(temp_flat)}
]

// precipitation (mm/yr), lat-major, south→north
export const OBS_PRECIP_MM: number[] = [
{_fmt_ints(precip_flat)}
]

export const OBS_TEMP_GRID = {grid_meta(t_lat, t_lon)}
export const OBS_PRECIP_GRID = {grid_meta(p_lat, p_lon)}
{extra_arrays}
interface Grid {{
  nlat: number
  nlon: number
  lat0: number
  dlat: number
  lon0: number
  dlon: number
}}

/** Bilinear-sample the observed annual temperature (°C) at (lat, lon). */
export function observedTempAt(latDeg: number, lonDeg: number): number {{
  return _sample(latDeg, lonDeg, OBS_TEMP_X10, OBS_TEMP_GRID, 0) / 10
}}

/** Bilinear-sample the observed annual precipitation (mm/yr) at (lat, lon). */
export function observedPrecipAt(latDeg: number, lonDeg: number): number {{
  return _sample(latDeg, lonDeg, OBS_PRECIP_MM, OBS_PRECIP_GRID, 0)
}}
{extra_samplers}
function _sample(
  latDeg: number, lonDeg: number, grid: number[], g: Grid, month: number,
): number {{
  // Grid row index in the array's native lat order (ascending or descending).
  const fi = (latDeg - g.lat0) / g.dlat
  let fj = ((lonDeg - g.lon0) / g.dlon) % g.nlon
  if (fj < 0) fj += g.nlon
  const i0 = Math.max(0, Math.min(g.nlat - 2, Math.floor(fi)))
  const j0 = Math.floor(fj)
  const j1 = (j0 + 1) % g.nlon
  const di = fi - i0
  const dj = fj - j0
  const base = month * g.nlat * g.nlon
  const v00 = grid[base + i0 * g.nlon + j0]
  const v01 = grid[base + i0 * g.nlon + j1]
  const v10 = grid[base + (i0 + 1) * g.nlon + j0]
  const v11 = grid[base + (i0 + 1) * g.nlon + j1]
  const top = v00 + (v01 - v00) * dj
  const bot = v10 + (v11 - v10) * dj
  return top + (bot - top) * di
}}
"""
    out = Path(args.output)
    out.write_text(body, encoding="utf-8")
    extras = []
    if slp_anom is not None:
        extras.append(f"ΔSLP {float(slp_anom.min()):.1f}..{float(slp_anom.max()):.1f} hPa")
    if uwnd is not None:
        extras.append(f"wind u {float(uwnd.min()):.1f}..{float(uwnd.max()):.1f} m/s")
    if cur_u is not None:
        extras.append(f"current u {float(cur_u.min()):.2f}..{float(cur_u.max()):.2f} m/s")
    extra_str = "; ".join(extras)
    print(
        f"[OK] {out} ({out.stat().st_size / 1e3:.0f} KB) — "
        f"temp {float(temp.min()):.1f}..{float(temp.max()):.1f} °C on {len(t_lat)}×{len(t_lon)}, "
        f"precip {float(precip.min()):.0f}..{float(precip.max()):.0f} mm/yr "
        f"on {len(p_lat)}×{len(p_lon)}" + (f"; {extra_str}" if extra_str else "")
    )


if __name__ == "__main__":
    main()
