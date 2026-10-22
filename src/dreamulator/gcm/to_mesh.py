"""Project an ExoPlaSim run onto a dreamulator CVT mesh.

Two outputs share one computation (:func:`compute_field_set`):

- a mesh file in the same format as an engine build, with the climate fields
  replaced by the GCM's, so ``dreamulator export layers --mesh`` renders it
  through exactly the frontend palettes and GCM and EBM can be compared pixel
  for pixel (:func:`project_to_mesh`);
- a pinned field set (:mod:`dreamulator.gcm.fields`) for a branch whose climate
  layer is frozen to the GCM result (``climate_source: gcm``).

Method (all on the tail of the run, default last 5 model years):

- **Seasonal climatology.**  Monthly records are binned into 12 equal bins of
  orbital phase (:func:`~dreamulator.gcm.diagnostics.orbital_phase_of_records`),
  because the model calendar drifts against the true orbital year.  Phase 0 is
  the northern vernal equinox, fitted from the records' declination
  (:func:`~dreamulator.gcm.diagnostics.equinox_day_from_declination`), so
  month ``m`` covers the same part of the orbit as the engine's month ``m``.
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
  but its values are Pa.  The SLP field is first smoothed with a Hoskins (1980)
  spectral filter (:func:`spectral_smooth`, damping 0.1 at total wavenumber
  ``SLP_SMOOTHING_N0`` = 21), because the spectral model's sea-level reduction
  over topography rings (Gibbs oscillations) far beyond the terrain.  Over the
  high terrain itself the reduction is a hypothetical extrapolation, so land
  cells whose GCM surface height is at least ``SLP_UNRELIABLE_HEIGHT_M`` get
  ``slp_reduction_unreliable = True`` (the same flag and threshold the
  observed Earth root uses; the frontend and the exporter grey them out).
- **Wind.**  10 m wind (``uas``/``vas``) when the run wrote it, otherwise the
  lowest model level of ``ua``/``va`` (sigma ≈ 0.99, the same kind of
  near-surface wind as the NCEP sigma-0.995 reference the engine is compared
  against); annual mean on the cells, phase-binned in the monthly arrays.

Fields the slab-ocean GCM cannot provide, or that the engine derives
downstream of its own climate (ocean currents, SST anomaly, biome, NPP,
agriculture, habitability), are cleared so they cannot be misread as GCM
output.  Geometry, elevation, geology and land ice are kept.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from dreamulator.gcm.fields import (
    CLEARED_FIELDS,
    GcmFieldSet,
    apply_field_set,
    mesh_fingerprint,
    mesh_reference_geometry,
)

if TYPE_CHECKING:
    from dreamulator.map.models import CVTMesh

LAPSE_K_PER_M = 0.0065
SLP_UNRELIABLE_HEIGHT_M = 1500.0
SLP_SMOOTHING_N0 = 21
SECONDS_PER_EARTH_MONTH = 365.25 / 12.0 * 86400.0


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


def _normalized_legendre(x: np.ndarray, nmax: int) -> np.ndarray:
    """Orthonormal associated Legendre functions ``P[m, n, j]`` on ``x`` (pure).

    Normalized so that ``∫_{-1}^{1} P_n^m(x)² dx = 1``; entries with ``n < m``
    are zero.  Standard stable three-term recursion in ``n`` for each ``m``.
    """
    x = np.asarray(x, dtype=float)
    sx = np.sqrt(np.maximum(1.0 - x * x, 0.0))
    p = np.zeros((nmax + 1, nmax + 1, x.size))
    pmm = np.full(x.size, 1.0 / math.sqrt(2.0))
    for m in range(nmax + 1):
        if m > 0:
            pmm = -math.sqrt((2 * m + 1) / (2 * m)) * sx * pmm
        p[m, m] = pmm
        if m + 1 <= nmax:
            p[m, m + 1] = math.sqrt(2 * m + 3) * x * pmm
        for n in range(m + 2, nmax + 1):
            a_n = math.sqrt((4 * n * n - 1) / (n * n - m * m))
            a_prev = math.sqrt((4 * (n - 1) ** 2 - 1) / ((n - 1) ** 2 - m * m))
            p[m, n] = a_n * (x * p[m, n - 1] - p[m, n - 2] / a_prev)
    return p


def spectral_smooth(field: np.ndarray, lat_deg: np.ndarray, n0: int) -> np.ndarray:
    """Hoskins (1980) spectral filter of ``field[..., nlat, nlon]`` on a Gaussian grid (pure).

    The field is expanded in spherical harmonics up to the grid's triangular
    truncation (``nlat - 1`` and ``nlon // 2``, whichever is smaller), each total
    wavenumber ``n`` is multiplied by ``exp(-ln10 · [n(n+1) / (n0(n0+1))]²)``
    (0.1 at ``n = n0``), and the result is transformed back.  ``lat_deg`` must be
    the ascending Gaussian latitudes of the grid.
    """
    nlat, nlon = field.shape[-2], field.shape[-1]
    nmax = min(nlat - 1, nlon // 2)
    x = np.sin(np.radians(lat_deg))
    _, weights = np.polynomial.legendre.leggauss(nlat)
    leg = _normalized_legendre(x, nmax)  # (m, n, lat)
    n = np.arange(nmax + 1)
    response = np.exp(-math.log(10.0) * (n * (n + 1) / (n0 * (n0 + 1))) ** 2)
    fourier = np.fft.rfft(field, axis=-1)[..., : nmax + 1]  # (..., lat, m)
    coeff = np.einsum("...jm,mnj,j->...mn", fourier, leg, weights)
    smoothed = np.einsum("...mn,n,mnj->...jm", coeff, response, leg)
    full = np.zeros((*field.shape[:-1], nlon // 2 + 1), dtype=complex)
    full[..., : nmax + 1] = smoothed
    out: np.ndarray = np.fft.irfft(full, n=nlon, axis=-1)
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


def compute_field_set(
    nc_path: str | Path,
    mesh: CVTMesh,
    *,
    orbital_year_days: float,
    gravity_m_s2: float,
    steps_per_model_day: float = 32.0,
    tail_years: int = 5,
    sea_level_m: float = 0.0,
) -> GcmFieldSet:
    """Per-cell GCM climate of ``nc_path`` on ``mesh`` (see the module docstring)."""
    import netCDF4

    from dreamulator.engine.climate_physics import koppen_classify
    from dreamulator.engine.climate_seasonality import (
        seasonal_precip_extremes,
        warm_cold_half_precip,
    )
    from dreamulator.gcm.diagnostics import (
        equinox_day_from_declination,
        orbital_phase_of_records,
    )

    ds = netCDF4.Dataset(str(nc_path))
    lat_raw = np.asarray(ds["lat"][:], dtype=float)
    order = np.argsort(lat_raw)
    lat_grid = lat_raw[order]
    lon_grid = np.asarray(ds["lon"][:], dtype=float)
    n_tail = min(tail_years * 12, ds["tas"].shape[0])

    def tail(name: str) -> np.ndarray:
        return np.asarray(ds[name][-n_tail:], dtype=float)[..., order, :]

    time_axis = np.asarray(ds["time"][:], dtype=float)
    if "zdec" in ds.variables:
        equinox_day = equinox_day_from_declination(
            time_axis,
            np.asarray(ds["zdec"][:], dtype=float),
            orbital_year_days=orbital_year_days,
            steps_per_model_day=steps_per_model_day,
        )
        phase_origin = "northern vernal equinox (fitted from zdec)"
    else:
        equinox_day, phase_origin = 0.0, "arbitrary (run has no zdec)"
    phase = orbital_phase_of_records(
        time_axis[-n_tail:],
        orbital_year_days=orbital_year_days,
        steps_per_model_day=steps_per_model_day,
        perihelion_day=equinox_day,
    )
    tas_m = phase_climatology(tail("tas") - 273.15, phase)  # (12, nlat, nlon) °C
    pr_m = phase_climatology(tail("pr") * 1000.0 * SECONDS_PER_EARTH_MONTH, phase)  # mm/month
    psl_m = phase_climatology(
        spectral_smooth(tail("psl") / 100.0, lat_grid, SLP_SMOOTHING_N0), phase
    )  # hPa
    ocean_grid = np.asarray(ds["lsm"][0], dtype=float)[order, :] < 0.5
    dp_m = band_ocean_anomaly(psl_m, ocean_grid)
    if "uas" in ds.variables and "vas" in ds.variables:
        u_m, v_m = phase_climatology(tail("uas"), phase), phase_climatology(tail("vas"), phase)
        wind_source = "uas/vas (10 m)"
    else:  # lowest model level is the last lev index (sigma closest to 1)
        u_m = phase_climatology(tail("ua")[:, -1], phase)
        v_m = phase_climatology(tail("va")[:, -1], phase)
        wind_source = "ua/va lowest model level"
    zsurf = None
    if "sg" in ds.variables:  # surface geopotential (m²/s²) → GCM surface height (m)
        zsurf = np.asarray(ds["sg"][0], dtype=float)[order, :] / gravity_m_s2

    cells = mesh.cells
    lat = np.array([c.lat for c in cells], dtype=float)
    lon = np.array([c.lon for c in cells], dtype=float)
    elev = np.array([c.elevation for c in cells], dtype=float)
    is_land = elev >= sea_level_m
    z_cell = np.where(is_land, np.maximum(elev - sea_level_m, 0.0), 0.0)

    def to_cells(grid_field: np.ndarray) -> np.ndarray:
        return bilinear_to_points(lat_grid, lon_grid, grid_field, lat, lon)

    t_monthly = to_cells(tas_m).T  # (N, 12)
    z_gcm = np.zeros_like(lat)
    if zsurf is not None:
        z_gcm = to_cells(np.maximum(zsurf, 0.0))
        t_monthly = t_monthly + LAPSE_K_PER_M * (z_gcm - z_cell)[:, None]
    slp_unreliable = is_land & (z_gcm >= SLP_UNRELIABLE_HEIGHT_M)
    p_monthly = np.maximum(to_cells(pr_m).T, 0.0)
    dp_monthly = to_cells(dp_m).T
    u_monthly, v_monthly = to_cells(u_m).T, to_cells(v_m).T

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

    return GcmFieldSet(
        num_cells=mesh.num_cells,
        mesh_fingerprint=mesh_fingerprint(mesh),
        annual={
            "temperature_C": t_mean,
            "temperature_hottest_month_C": t_hot,
            "temperature_coldest_month_C": t_cold,
            "precipitation_mm": p_annual,
            "pressure_anomaly_annual_hpa": dp_monthly.mean(axis=1),
            "slp_annual_hpa": to_cells(psl_m.mean(axis=0)),
            "wind_east_m_s": u_monthly.mean(axis=1),
            "wind_north_m_s": v_monthly.mean(axis=1),
        },
        monthly={
            "t_monthly_c": t_monthly,
            "p_monthly_mm": p_monthly,
            "wind_east_monthly": u_monthly,
            "wind_north_monthly": v_monthly,
            "pressure_monthly": dp_monthly,
        },
        koppen=[None if k is None else str(k) for k in koppen],
        slp_reduction_unreliable=slp_unreliable,
        reference_geometry=mesh_reference_geometry(mesh),
        provenance={
            "source_nc": str(nc_path),
            "tail_years": n_tail / 12,
            "grid": [int(lat_grid.size), int(lon_grid.size)],
            "phase_origin": phase_origin,
            "lapse_k_per_m": LAPSE_K_PER_M if zsurf is not None else None,
            "precipitation_basis": "mm per Earth year (365.25/12 days per month)",
            "wind_source": wind_source,
            "slp_smoothing": f"Hoskins spectral filter, 0.1 at n = {SLP_SMOOTHING_N0}",
            "sea_level_m": sea_level_m,
        },
    )


def summarize_field_set(fs: GcmFieldSet, mesh: CVTMesh, sea_level_m: float = 0.0) -> dict[str, Any]:
    """Global and land means plus the land Köppen counts of a field set (pure)."""
    area = np.array([c.area_km2 for c in mesh.cells], dtype=float)
    is_land = np.array([c.elevation for c in mesh.cells], dtype=float) >= sea_level_m
    t_mean, p_annual = fs.annual["temperature_C"], fs.annual["precipitation_mm"]
    koppen = np.array(["" if k is None else k for k in fs.koppen])
    names, counts = np.unique(koppen[is_land], return_counts=True)
    return {
        **fs.provenance,
        "slp_unreliable_cells": int(fs.slp_reduction_unreliable.sum()),
        "cleared_fields": list(CLEARED_FIELDS),
        "global_mean_temperature_c": float(np.average(t_mean, weights=area)),
        "land_mean_temperature_c": float(np.average(t_mean[is_land], weights=area[is_land])),
        "land_mean_precipitation_mm": float(np.average(p_annual[is_land], weights=area[is_land])),
        "koppen_land_counts": {str(k): int(v) for k, v in zip(names, counts, strict=True)},
    }


_GCM_WORKDIR_RE = re.compile(r"[^\s'\"]*private/gcm/")


def public_provenance(value: Any) -> Any:
    """Replace local GCM work-directory paths (``…/private/gcm/``) by ``<gcm-workdir>/``."""
    if isinstance(value, str):
        return _GCM_WORKDIR_RE.sub("<gcm-workdir>/", value)
    if isinstance(value, dict):
        return {k: public_provenance(v) for k, v in value.items()}
    if isinstance(value, list):
        return [public_provenance(v) for v in value]
    return value


def project_to_mesh(
    nc_path: str | Path,
    mesh_path: str | Path,
    out_path: str | Path | None = None,
    *,
    orbital_year_days: float,
    gravity_m_s2: float,
    steps_per_model_day: float = 32.0,
    tail_years: int = 5,
    sea_level_m: float = 0.0,
    fields_out: str | Path | None = None,
    extra_provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Project ``nc_path`` onto the mesh at ``mesh_path``.

    Writes a copy of the mesh with GCM climate to ``out_path`` (plus a
    ``<out>.gcm.json`` summary) and/or the pinned field set to ``fields_out``
    (plus its ``.provenance.json``).  ``extra_provenance`` (for example the
    run's manifest) is merged into the field set's provenance.  Returns the
    summary dict.
    """
    from dreamulator.gcm.fields import save_field_set
    from dreamulator.map.export import load_cvt_mesh_model, save_cvt_mesh

    if out_path is None and fields_out is None:
        raise ValueError("nothing to write: pass out_path and/or fields_out")
    mesh = load_cvt_mesh_model(Path(mesh_path))
    fs = compute_field_set(
        nc_path,
        mesh,
        orbital_year_days=orbital_year_days,
        gravity_m_s2=gravity_m_s2,
        steps_per_model_day=steps_per_model_day,
        tail_years=tail_years,
        sea_level_m=sea_level_m,
    )
    fs.provenance.update(extra_provenance or {})
    summary = {"source_mesh": str(mesh_path), **summarize_field_set(fs, mesh, sea_level_m)}
    if not math.isfinite(summary["global_mean_temperature_c"]):
        raise ValueError("projected temperature is not finite; check the source run")
    if fields_out is not None:
        # the field set's provenance is tracked in the public repository: name the GCM work
        # directory by the runbook's placeholder instead of its local path
        fs.provenance = public_provenance(fs.provenance)
        save_field_set(fields_out, fs)
    if out_path is not None:
        apply_field_set(mesh, fs)
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        save_cvt_mesh(out, mesh)
        sidecar = out.with_name(out.name + ".gcm.json")
        sidecar.write_text(
            json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    return summary


__all__ = [
    "CLEARED_FIELDS",
    "LAPSE_K_PER_M",
    "SLP_SMOOTHING_N0",
    "SLP_UNRELIABLE_HEIGHT_M",
    "band_ocean_anomaly",
    "bilinear_to_points",
    "compute_field_set",
    "phase_climatology",
    "project_to_mesh",
    "spectral_smooth",
    "summarize_field_set",
]
