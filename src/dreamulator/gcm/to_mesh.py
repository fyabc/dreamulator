"""Project an ExoPlaSim run onto a dreamulator CVT mesh (GCM-vs-EBM comparison).

The output is a mesh file in the same format as an engine build, with the
climate fields replaced by the GCM's, so ``dreamulator export layers --mesh``
renders it through exactly the frontend palettes and the two can be compared
pixel for pixel.

Method (all on the tail of the run, default last 5 model years):

- **Seasonal climatology.**  Monthly records are binned into 12 equal bins of
  orbital phase (:func:`~dreamulator.gcm.diagnostics.orbital_phase_of_records`),
  because the model calendar drifts against the true orbital year.  The phase
  origin is arbitrary; nothing below depends on it (Köppen uses extremes and
  warm/cold-half rankings).
- **Regridding.**  Bilinear interpolation from the Gaussian grid to each cell's
  lat/lon, periodic in longitude, latitudes clamped at the outermost rows.
- **Temperature.**  2 m air temperature corrected from the GCM's smooth
  surface height to the cell's own elevation with a standard lapse rate
  (epistemic class: approximate derivation; the GCM grid at T21/T42 cannot
  resolve the mesh topography).  Ocean cells use sea level.
- **Precipitation.**  Monthly totals on the Earth-year basis (365.25/12 days per
  month), matching the engine's ``precipitation_mm`` convention; no correction.
- **Köppen.**  The engine's own ``koppen_classify`` with the same seasonal
  inputs (``warm_cold_half_precip``, ``seasonal_precip_extremes``,
  months ≥ 10 °C), so the classifier is identical on both sides.
- **Pressure.**  ``pressure_anomaly_annual_hpa`` uses the engine's definition
  (SLP minus the same-month ocean mean of the latitude band, 12-month mean);
  ``slp_annual_hpa`` is the absolute annual mean.  pyburn labels ``psl`` "hPa"
  but its values are Pa.  Over high terrain the GCM's sea-level reduction is a
  hypothetical extrapolation that rings in spectral space, so land cells whose
  GCM surface height is at least ``SLP_UNRELIABLE_HEIGHT_M`` get
  ``slp_reduction_unreliable = True`` (the same flag and threshold the
  observed Earth root uses; the frontend and the exporter grey them out).
- **Wind.**  Annual-mean 10 m wind (``uas``/``vas``) when the run wrote it,
  otherwise the lowest model level of ``ua``/``va`` (sigma ≈ 0.99, the same
  kind of near-surface wind as the NCEP sigma-0.995 reference the engine is
  compared against).

Fields the slab-ocean GCM cannot provide, or that the engine derives
downstream of its own climate (ocean currents, SST anomaly, biome, NPP,
agriculture, habitability), are cleared so they cannot be misread as GCM
output.  Geometry, elevation, geology and land ice are kept.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np

LAPSE_K_PER_M = 0.0065
SLP_UNRELIABLE_HEIGHT_M = 1500.0
SECONDS_PER_EARTH_MONTH = 365.25 / 12.0 * 86400.0

#: Engine-derived fields that would be inconsistent with GCM climate.
CLEARED_FIELDS = (
    "ocean_current_east_m_s",
    "ocean_current_north_m_s",
    "sst_anomaly_c",
    "biome",
    "npp_gc_m2_yr",
    "agriculture_score",
    "habitability_score",
)


def bilinear_to_points(
    lat_grid: np.ndarray, lon_grid: np.ndarray, field: np.ndarray, lat: np.ndarray, lon: np.ndarray
) -> np.ndarray:
    """Bilinear interpolation of ``field[..., nlat, nlon]`` to points (pure function).

    ``lat_grid`` must be ascending, ``lon_grid`` uniform starting at 0; longitude
    wraps periodically, latitude is clamped to the outermost grid rows.
    Returns an array of shape ``field.shape[:-2] + lat.shape``.
    """
    nlat, nlon = lat_grid.size, lon_grid.size
    dlon = 360.0 / nlon
    x = (np.asarray(lon) % 360.0) / dlon
    i0 = np.floor(x).astype(int) % nlon
    i1 = (i0 + 1) % nlon
    fx = x - np.floor(x)
    la = np.clip(np.asarray(lat), lat_grid[0], lat_grid[-1])
    j1 = np.clip(np.searchsorted(lat_grid, la, side="right"), 1, nlat - 1)
    j0 = j1 - 1
    fy = (la - lat_grid[j0]) / (lat_grid[j1] - lat_grid[j0])
    f00, f01 = field[..., j0, i0], field[..., j0, i1]
    f10, f11 = field[..., j1, i0], field[..., j1, i1]
    out: np.ndarray = (1 - fy) * ((1 - fx) * f00 + fx * f01) + fy * ((1 - fx) * f10 + fx * f11)
    return out


def band_ocean_anomaly(slp: np.ndarray, ocean: np.ndarray) -> np.ndarray:
    """SLP minus the ocean mean of each latitude band (engine ΔP definition, pure).

    ``slp`` has shape ``(..., nlat, nlon)``, ``ocean`` ``(nlat, nlon)`` boolean.
    Bands without ocean use the full band mean.
    """
    weights = ocean.astype(float)
    n_ocean = weights.sum(axis=-1, keepdims=True)
    ocean_mean = (slp * weights).sum(axis=-1, keepdims=True) / np.where(n_ocean > 0, n_ocean, 1.0)
    band_mean = slp.mean(axis=-1, keepdims=True)
    anomaly: np.ndarray = slp - np.where(n_ocean > 0, ocean_mean, band_mean)
    return anomaly


def phase_climatology(values: np.ndarray, phase: np.ndarray, n_bins: int = 12) -> np.ndarray:
    """Average records into ``n_bins`` equal orbital-phase bins (pure function).

    ``values`` has records on axis 0.  Empty bins (possible for very short
    tails) are filled from the nearest non-empty bin.
    """
    bins = np.minimum((np.asarray(phase) * n_bins).astype(int), n_bins - 1)
    out = np.full((n_bins, *values.shape[1:]), np.nan)
    for b in range(n_bins):
        sel = bins == b
        if sel.any():
            out[b] = values[sel].mean(axis=0)
    filled = ~np.isnan(out.reshape(n_bins, -1)[:, 0])
    if not filled.all():
        idx = np.flatnonzero(filled)
        for empty in np.flatnonzero(~filled):
            gap = np.abs(idx - empty)
            out[empty] = out[idx[np.argmin(np.minimum(gap, n_bins - gap))]]
    return out


def project_to_mesh(
    nc_path: str | Path,
    mesh_path: str | Path,
    out_path: str | Path,
    *,
    orbital_year_days: float,
    gravity_m_s2: float,
    steps_per_model_day: float = 32.0,
    tail_years: int = 5,
    sea_level_m: float = 0.0,
) -> dict[str, Any]:
    """Write a copy of ``mesh_path`` whose climate fields come from ``nc_path``.

    Returns a provenance/summary dict, also written next to the output as
    ``<out>.gcm.json``.
    """
    import netCDF4

    from dreamulator.engine.climate_physics import koppen_classify
    from dreamulator.engine.climate_seasonality import (
        seasonal_precip_extremes,
        warm_cold_half_precip,
    )
    from dreamulator.gcm.diagnostics import orbital_phase_of_records
    from dreamulator.map.export import load_cvt_mesh_model, save_cvt_mesh

    ds = netCDF4.Dataset(str(nc_path))
    lat_raw = np.asarray(ds["lat"][:], dtype=float)
    order = np.argsort(lat_raw)
    lat_grid = lat_raw[order]
    lon_grid = np.asarray(ds["lon"][:], dtype=float)
    n_tail = min(tail_years * 12, ds["tas"].shape[0])

    def tail(name: str) -> np.ndarray:
        return np.asarray(ds[name][-n_tail:], dtype=float)[..., order, :]

    phase = orbital_phase_of_records(
        np.asarray(ds["time"][-n_tail:], dtype=float),
        orbital_year_days=orbital_year_days,
        steps_per_model_day=steps_per_model_day,
    )
    tas_m = phase_climatology(tail("tas") - 273.15, phase)  # (12, nlat, nlon) °C
    pr_m = phase_climatology(tail("pr") * 1000.0 * SECONDS_PER_EARTH_MONTH, phase)  # mm/month
    psl = tail("psl") / 100.0  # hPa
    ocean_grid = np.asarray(ds["lsm"][0], dtype=float)[order, :] < 0.5
    dp_annual = band_ocean_anomaly(psl, ocean_grid).mean(axis=0)
    slp_annual = psl.mean(axis=0)
    if "uas" in ds.variables and "vas" in ds.variables:
        uas, vas = tail("uas").mean(axis=0), tail("vas").mean(axis=0)
        wind_source = "uas/vas (10 m)"
    else:  # lowest model level is the last lev index (sigma closest to 1)
        uas, vas = tail("ua")[:, -1].mean(axis=0), tail("va")[:, -1].mean(axis=0)
        wind_source = "ua/va lowest model level"
    zsurf = None
    if "sg" in ds.variables:  # surface geopotential (m²/s²) → GCM surface height (m)
        zsurf = np.asarray(ds["sg"][0], dtype=float)[order, :] / gravity_m_s2

    mesh = load_cvt_mesh_model(Path(mesh_path))
    cells = mesh.cells
    lat = np.array([c.lat for c in cells], dtype=float)
    lon = np.array([c.lon for c in cells], dtype=float)
    elev = np.array([c.elevation for c in cells], dtype=float)
    is_land = elev >= sea_level_m
    z_cell = np.where(is_land, np.maximum(elev - sea_level_m, 0.0), 0.0)

    t_monthly = bilinear_to_points(lat_grid, lon_grid, tas_m, lat, lon).T  # (N, 12)
    z_gcm = np.zeros_like(lat)
    if zsurf is not None:
        z_gcm = bilinear_to_points(lat_grid, lon_grid, np.maximum(zsurf, 0.0), lat, lon)
        t_monthly = t_monthly + LAPSE_K_PER_M * (z_gcm - z_cell)[:, None]
    slp_unreliable = is_land & (z_gcm >= SLP_UNRELIABLE_HEIGHT_M)
    p_monthly = np.maximum(bilinear_to_points(lat_grid, lon_grid, pr_m, lat, lon).T, 0.0)
    dp_cell = bilinear_to_points(lat_grid, lon_grid, dp_annual, lat, lon)
    slp_cell = bilinear_to_points(lat_grid, lon_grid, slp_annual, lat, lon)
    u_cell = bilinear_to_points(lat_grid, lon_grid, uas, lat, lon)
    v_cell = bilinear_to_points(lat_grid, lon_grid, vas, lat, lon)

    t_mean, t_cold, t_hot = t_monthly.mean(axis=1), t_monthly.min(axis=1), t_monthly.max(axis=1)
    p_annual = p_monthly.sum(axis=1)
    p_warm, p_cold = warm_cold_half_precip(t_monthly, p_monthly)
    p_dry_s, p_wet_w, p_dry_w, p_wet_s = seasonal_precip_extremes(t_monthly, p_monthly)
    koppen = koppen_classify(
        t_mean_c=t_mean,
        t_cold_c=t_cold,
        t_hot_c=t_hot,
        p_annual_mm=p_annual,
        p_dry_mm=p_monthly.min(axis=1),
        p_wet_mm=p_monthly.max(axis=1),
        p_warm_mm=p_warm,
        p_cold_mm=p_cold,
        p_dry_summer_mm=p_dry_s,
        p_wet_winter_mm=p_wet_w,
        p_dry_winter_mm=p_dry_w,
        p_wet_summer_mm=p_wet_s,
        is_land=is_land,
        t_months_ge10=(t_monthly >= 10.0).sum(axis=1),
    )

    for i, cell in enumerate(cells):
        cell.temperature_C = float(t_mean[i])
        cell.temperature_hottest_month_C = float(t_hot[i])
        cell.temperature_coldest_month_C = float(t_cold[i])
        cell.precipitation_mm = float(p_annual[i])
        cell.koppen_class = koppen[i]
        cell.pressure_anomaly_annual_hpa = float(dp_cell[i])
        cell.slp_annual_hpa = float(slp_cell[i])
        cell.slp_reduction_unreliable = bool(slp_unreliable[i])
        cell.wind_east_m_s = float(u_cell[i])
        cell.wind_north_m_s = float(v_cell[i])
        for name in CLEARED_FIELDS:
            setattr(cell, name, None)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    save_cvt_mesh(out_path, mesh)

    area = np.array([c.area_km2 for c in cells], dtype=float)
    summary = {
        "source_nc": str(nc_path),
        "source_mesh": str(mesh_path),
        "tail_years": n_tail / 12,
        "grid": [int(lat_grid.size), int(lon_grid.size)],
        "lapse_k_per_m": LAPSE_K_PER_M if zsurf is not None else None,
        "precipitation_basis": "mm per Earth year (365.25/12 days per month)",
        "wind_source": wind_source,
        "slp_unreliable_cells": int(slp_unreliable.sum()),
        "cleared_fields": list(CLEARED_FIELDS),
        "global_mean_temperature_c": float(np.average(t_mean, weights=area)),
        "land_mean_temperature_c": float(np.average(t_mean[is_land], weights=area[is_land])),
        "land_mean_precipitation_mm": float(np.average(p_annual[is_land], weights=area[is_land])),
        "koppen_land_counts": {
            k: int(v)
            for k, v in zip(
                *np.unique(np.asarray(koppen)[is_land], return_counts=True), strict=True
            )
        },  # fmt: skip
    }
    sidecar = out_path.with_name(out_path.name + ".gcm.json")
    sidecar.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if not math.isfinite(summary["global_mean_temperature_c"]):
        raise ValueError("projected temperature is not finite; check the source run")
    return summary


__all__ = [
    "CLEARED_FIELDS",
    "LAPSE_K_PER_M",
    "SLP_UNRELIABLE_HEIGHT_M",
    "band_ocean_anomaly",
    "bilinear_to_points",
    "phase_climatology",
    "project_to_mesh",
]
