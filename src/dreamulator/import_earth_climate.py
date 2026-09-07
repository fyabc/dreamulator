"""Import real Earth climate observation into the earth base world.

The earth base world is a "real Earth" ground-truth reference — it is *never*
built through the simulation pipeline (`elevation_source: imported`).  Its
climate fields should therefore be real observation, not engine output.  This
module samples four observation datasets onto the CVT mesh and writes:

- ``cvt_mesh.json`` per-cell fields — ``koppen_class`` (Beck), ``temperature_C``
  (NCEP annual mean), ``precipitation_mm`` (GPCP annual total), wind / SLP
  (NCEP), and ``ocean_current_east/north_m_s`` (SODA v3.15.2 observed
  climatology, annual mean; engine Stommel-solver fallback when SODA is
  absent).  These are the only climate fields the frontend reads for the
  annual layers.
- ``climate_monthly.msgpack`` — monthly ``t_monthly`` / ``p_monthly`` /
  ``pressure_monthly`` (the seasonal SLP anomaly), in the same quantized-int16
  format the engine exports (``export._quantize_int16``), so the frontend's
  ``monthlyClimate.ts`` decodes it unchanged.
- Secondary exports the frontend ignores but external tools/validation use:
  ``koppen.json``, ``temperature.png``, ``precipitation.png``,
  ``climate_metadata.json``.

Data provenance:
- Köppen — Beck et al. (2018), Present Köppen-Geiger, 5 arc-min
  (doi:10.1038/sdata.2018.214).
- Temperature — NCEP/NCAR Reanalysis 1 ``air.mon.ltm.nc`` (2.5°, 12-month
  climatology).
- Precipitation — GPCP v2.3 ``precip.mon.mean.nc`` (2.5°, monthly mean).
- Sea-level pressure — NCEP/NCAR Reanalysis 1 ``slp.mon.ltm.nc`` (2.5°).
- Ocean currents — SODA v3.15.2 (Carton et al. 2018, doi:10.1175/JCLI-D-18-0149.1)
  surface (~5 m) monthly climatology 1993–2022, annual mean per cell
  (``soda_currents_mon_clim.nc``, built by ``scripts/earth/download_validation_data.py``
  from the APDRC OPeNDAP server).  Fallback when that file is absent: the
  engine's Stommel barotropic solver driven by the NCEP wind below (modelled,
  not observed — the earth world then gets the same current physics as built
  worlds instead).

Usage mirrors the other importers::

    uv run python scripts/earth/import_earth_climate.py \
        --output-dir data/worlds/earth/maps/planet_earth
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from dreamulator.map.models import CVTMesh, VoronoiCell

# Beck class code → Köppen string (from scripts/climate/convert_koppen_map.py).
_BECK_LEGEND: dict[int, str] = {
    0: "N/A",
    1: "Af",
    2: "Am",
    3: "Aw",
    4: "BWh",
    5: "BWk",
    6: "BSh",
    7: "BSk",
    8: "Csa",
    9: "Csb",
    10: "Csc",
    11: "Cwa",
    12: "Cwb",
    13: "Cwc",
    14: "Cfa",
    15: "Cfb",
    16: "Cfc",
    17: "Dsa",
    18: "Dsb",
    19: "Dsc",
    20: "Dsd",
    21: "Dwa",
    22: "Dwb",
    23: "Dwc",
    24: "Dwd",
    25: "Dfa",
    26: "Dfb",
    27: "Dfc",
    28: "Dfd",
    29: "ET",
    30: "EF",
}

_DAYS_PER_MONTH = np.array([31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31], dtype=np.float64)

# The engine orders months from the March vernal equinox (month 0 = March); the
# frontend hardcodes this.  Observation files are January-first, so reorder.
_MARCH_FIRST = [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 0, 1]

# Local observation data under private/tmp/climatology/ (gitignored).
_NCEP_AIR = "private/tmp/climatology/ncep_air.mon.ltm.nc"
_NCEP_SLP = "private/tmp/climatology/ncep_slp.mon.ltm.nc"
_GPCP = "private/tmp/climatology/gpcp_precip.mon.mean.nc"
_SODA_CURRENTS_NC = "soda_currents_mon_clim.nc"


# ---------------------------------------------------------------------------
# Grid sampling (bilinear on a regular lat/lon grid)
# ---------------------------------------------------------------------------


def _bilinear(
    grid: np.ndarray, lat: np.ndarray, lon: np.ndarray, lats: np.ndarray, lons: np.ndarray
) -> np.ndarray:
    """Bilinear-interpolate a ``(lat, lon)`` grid at ``(lats, lons)`` points.

    Handles monotonic lat (ascending or descending) and a 0..360 lon axis by
    wrapping the target longitudes into the grid's convention.
    """
    lat = np.asarray(lat, dtype=np.float64)
    lon = np.asarray(lon, dtype=np.float64)
    lats = np.asarray(lats, dtype=np.float64)
    lons = np.asarray(lons, dtype=np.float64)

    # Wrap target lon into the grid's range (e.g. -180..180 → 0..360).
    if lon.max() > 180 and lons.min() < 0:
        lons = np.where(lons < 0, lons + 360.0, lons)

    lat_idx = _interp_index(lat, lats)
    lon_idx = _interp_index(lon, lons)

    i0 = np.floor(lat_idx).astype(np.int64)
    j0 = np.floor(lon_idx).astype(np.int64)
    i1 = np.minimum(i0 + 1, len(lat) - 1)
    j1 = np.minimum(j0 + 1, len(lon) - 1)
    w_i = lat_idx - i0
    w_j = lon_idx - j0

    v00 = grid[i0, j0]
    v01 = grid[i0, j1]
    v10 = grid[i1, j0]
    v11 = grid[i1, j1]
    return np.asarray(
        (1 - w_i) * ((1 - w_j) * v00 + w_j * v01) + w_i * ((1 - w_j) * v10 + w_j * v11)
    )


def _interp_index(coord: np.ndarray, target: np.ndarray) -> np.ndarray:
    """Fractional index of *target* along a monotonic *coord* axis (either direction)."""
    c0 = float(coord[0])
    c1 = float(coord[-1])
    ascending = c1 >= c0
    if ascending:
        idx = (target - c0) / (c1 - c0) * (len(coord) - 1)
    else:
        idx = (c0 - target) / (c0 - c1) * (len(coord) - 1)
    return np.asarray(np.clip(idx, 0.0, len(coord) - 1))


def _sample_monthly(
    monthly: np.ndarray, lat: np.ndarray, lon: np.ndarray, lats: np.ndarray, lons: np.ndarray
) -> np.ndarray:
    """Sample a ``(12, lat, lon)`` monthly grid → ``(12, N)`` at cell centers."""
    n = len(lats)
    out = np.empty((monthly.shape[0], n), dtype=np.float64)
    for m in range(monthly.shape[0]):
        out[m] = _bilinear(monthly[m], lat, lon, lats, lons)
    return out


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def _load_nc_monthly(path: Path, var: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Load a ``(12, lat, lon)`` monthly NetCDF → (array, lat, lon)."""
    import xarray as xr

    ds = xr.open_dataset(path)
    da = ds[var]
    arr = np.asarray(da.values, dtype=np.float64)
    lat = np.asarray(da["lat"].values, dtype=np.float64)
    lon = np.asarray(da["lon"].values, dtype=np.float64)
    ds.close()
    return arr, lat, lon


def _load_gpcp_climatology(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """GPCP monthly-mean → 12-month climatology (mm/day → mm/month)."""
    import xarray as xr

    ds = xr.open_dataset(path, decode_times=False)
    da = ds["precip"]
    arr = np.asarray(da.values, dtype=np.float64)  # (time, lat, lon), mm/day
    lat = np.asarray(da["lat"].values, dtype=np.float64)
    lon = np.asarray(da["lon"].values, dtype=np.float64)
    ds.close()

    # Take 47 full years (564 months) and fold to a 12-month climatology.
    n_years = arr.shape[0] // 12
    monthly = arr[: n_years * 12].reshape(n_years, 12, arr.shape[1], arr.shape[2]).mean(axis=0)
    # mm/day → mm/month (days per calendar month).
    monthly_mm = monthly * _DAYS_PER_MONTH[:, None, None]
    return monthly_mm, lat, lon


def _load_beck_koppen(path: Path) -> np.ndarray:
    """Load the Beck Köppen GeoTIFF as a uint8 (lat N→S, lon W→E) array."""
    import tifffile

    return np.asarray(tifffile.imread(str(path)))


def _sample_beck(beck: np.ndarray, lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    """Sample Beck at cell centers → per-cell class code (int)."""
    h, w = beck.shape
    row = np.clip(((90.0 - lats) / 180.0 * h).astype(np.int64), 0, h - 1)
    col = np.clip(((lons + 180.0) / 360.0 * w).astype(np.int64), 0, w - 1)
    return np.asarray(beck[row, col], dtype=np.int64)


# ---------------------------------------------------------------------------
# Ocean currents (engine solver driven by observed wind)
# ---------------------------------------------------------------------------

#: Basins smaller than this contribute no visible surface currents; same
#: cutoff as the engine (``climate_simulator`` stage 2.5).
_MIN_BASIN_CELLS = 20


def _compute_ocean_currents(
    cells: list[VoronoiCell], wind_east: np.ndarray, wind_north: np.ndarray
) -> None:
    """Write per-cell surface currents from the engine's Stommel gyre solver.

    The earth world never runs the climate engine, so its ``ocean_current_*``
    fields would stay empty.  Here we drive the same solver the engine uses
    (``map/ocean_circulation.py``) with the *observed* NCEP annual-mean wind:
    wind stress curl → per-basin Stommel streamfunction (GMRES) → tangent
    velocity.  Physical parameters are the engine's Earth defaults
    (``TerrainPipelineConfig``: rotation 1 day, radius 6371 km; solver
    defaults: C_D 1.2e-3, H_ml 50 m, R 1e-6 s⁻¹).

    Deliberately **not** done here: SST advection / upwelling corrections.
    Earth's temperature field is pure observation — advecting a model SST
    anomaly onto it would mix model output into ground truth, and
    ``sst_anomaly_c`` is left unset (frontend arrows render neutral-coloured).
    """
    from dreamulator.map.ocean_circulation import (
        _build_directed_edge_table,
        _extract_areas_km2,
        _extract_lat_rad,
        _extract_nodes_xyz,
        compute_curl_z,
        compute_wind_stress,
        detect_ocean_basins,
        east_north_basis,
        solve_ocean_gyre,
    )

    nodes_xyz = _extract_nodes_xyz(cells)
    east, north = east_north_basis(nodes_xyz)

    # Tangent wind vectors (m/s) from the imported east/north components —
    # composed on the engine's *internal* wind convention: hadley_cell_wind
    # builds vectors on a mirrored east basis (``east = north × r̂`` = physical
    # west; the stored ``wind_east_m_s`` is flipped back by the FIXME at
    # climate_simulator.py:517), and the whole Stommel chain is calibrated
    # against that convention — engine-built worlds store physically correct
    # currents (Gulf Stream NE-ward, SEC W-ward, verified on earth/climate-dev)
    # while feeding true-east vectors mirrors the entire current field.  So
    # negate the imported (true-east) component to reproduce the internal
    # convention.  If that FIXME is ever resolved, this negation must go too.
    wind = -wind_east[:, None] * east + wind_north[:, None] * north
    tau = compute_wind_stress(wind)
    src, dst = _build_directed_edge_table(cells)
    curl_z = compute_curl_z(tau, nodes_xyz, src, dst, east, north)

    # Planetary β = 2Ω cos(φ) / a, Earth defaults (ω for a 1-day rotation).
    omega = 2.0 * np.pi / 86400.0
    radius_m = 6371.0e3
    beta = 2.0 * omega * np.cos(_extract_lat_rad(cells)) / radius_m

    _, basins = detect_ocean_basins(cells, sea_level_m=0.0)
    if not basins:
        print("  Ocean currents: no ocean basins detected — skipped")
        return

    areas_km2 = _extract_areas_km2(cells)
    filled = 0
    solved = 0
    for b_idx, b_cells in enumerate(basins):
        n_b = len(b_cells)
        if n_b < _MIN_BASIN_CELLS:
            continue
        print(f"    Basin {b_idx + 1}/{len(basins)} ({n_b} cells)...")
        _, vel = solve_ocean_gyre(
            b_cells,
            cells,
            nodes_xyz,
            areas_km2,
            curl_z,
            beta,
            east=east,
            sea_level_m=0.0,
        )
        for li, gi in enumerate(b_cells):
            c = cells[gi]
            c.ocean_current_east_m_s = float(np.dot(vel[li], east[gi]))
            c.ocean_current_north_m_s = float(np.dot(vel[li], north[gi]))
        filled += n_b
        solved += 1
    print(f"  Ocean currents (Stommel gyres): {solved}/{len(basins)} basins, {filled} cells")


# ---------------------------------------------------------------------------
# Observed ocean currents (SODA monthly climatology)
# ---------------------------------------------------------------------------


def _load_soda_climatology(
    path: Path,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, dict[str, str]]:
    """Load the SODA surface-current monthly climatology netCDF.

    Returns ``(u, v, lat, lon, attrs)`` with u/v as ``(12, lat, lon)`` arrays
    in m/s, January-first, NaN over land/ice and SODA's uncovered
    far-southern ocean (grid starts at 74.5°S).
    """
    import xarray as xr

    ds = xr.open_dataset(path)
    u = np.asarray(ds["u"].values, dtype=np.float64)
    v = np.asarray(ds["v"].values, dtype=np.float64)
    lat = np.asarray(ds["lat"].values, dtype=np.float64)
    lon = np.asarray(ds["lon"].values, dtype=np.float64)
    attrs = {str(k): str(val) for k, val in ds.attrs.items()}
    ds.close()
    return u, v, lat, lon, attrs


def _sample_monthly_nan_tolerant(
    monthly: np.ndarray, lat: np.ndarray, lon: np.ndarray, lats: np.ndarray, lons: np.ndarray
) -> np.ndarray:
    """``_sample_monthly`` with a nearest-grid-point fallback at NaN.

    Bilinear interpolation bleeds SODA's land/ice NaN one source-grid step
    into the ocean, blanking coastal mesh cells; where the bilinear result is
    NaN, sample the nearest source grid point instead (itself possibly NaN —
    those cells stay empty).  Assumes a regular lat/lon grid (SODA is 0.5°
    linear), so the nearest index is arithmetic rather than a search.
    """
    out = np.asarray(_sample_monthly(monthly, lat, lon, lats, lons))
    if np.isfinite(out).all():
        return out
    lons_w = lons.copy()
    if float(lon.max()) > 180.0 and float(lons.min()) < 0.0:
        lons_w = np.where(lons_w < 0, lons_w + 360.0, lons_w)
    dlat = float(lat[1] - lat[0])
    dlon = float(lon[1] - lon[0])
    i = np.clip(np.round((lats - float(lat[0])) / dlat).astype(np.int64), 0, len(lat) - 1)
    j = np.clip(np.round((lons_w - float(lon[0])) / dlon).astype(np.int64), 0, len(lon) - 1)
    nearest = monthly[:, i, j]
    return np.asarray(np.where(np.isfinite(out), out, nearest))


def _apply_observed_currents(
    cells: list[VoronoiCell],
    lats: np.ndarray,
    lons: np.ndarray,
    u_clim: np.ndarray,
    v_clim: np.ndarray,
    cur_lat: np.ndarray,
    cur_lon: np.ndarray,
) -> int:
    """Write the observed annual-mean surface currents onto ocean cells.

    Samples the ``(12, lat, lon)`` SODA climatology at cell centres and stores
    the 12-month mean per ocean cell; cells whose sample stays NaN (SODA land
    mask or the uncovered far-southern ocean) keep ``None``.  Returns the
    number of cells written.
    """
    u_mon = _sample_monthly_nan_tolerant(u_clim, cur_lat, cur_lon, lats, lons)
    v_mon = _sample_monthly_nan_tolerant(v_clim, cur_lat, cur_lon, lats, lons)
    written = 0
    for i, c in enumerate(cells):
        if c.water_class != "ocean":
            continue
        u_col, v_col = u_mon[:, i], v_mon[:, i]
        if not np.isfinite(u_col).any() or not np.isfinite(v_col).any():
            continue
        c.ocean_current_east_m_s = float(np.nanmean(u_col))
        c.ocean_current_north_m_s = float(np.nanmean(v_col))
        written += 1
    return written


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def import_earth_climate(output_dir: Path, *, data_dir: Path | None = None) -> None:
    """Sample real climate onto the mesh and write the climate files."""
    from dreamulator.map.export import compress_mesh_bytes, decompress_mesh_bytes
    from dreamulator.map.models import CVTMesh

    project_root = _find_project_root()
    data_dir = data_dir or (project_root / "private/tmp/climatology")
    beck_path = (
        Path(__import__("tempfile").gettempdir())
        / "dreamulator_koppen"
        / "Beck_KG_V1_present_0p083.tif"
    )

    mesh_path = output_dir / "cvt_mesh.json"
    if not mesh_path.exists():
        raise FileNotFoundError(f"{mesh_path} not found — run the ETOPO1 elevation importer first.")
    mesh = CVTMesh.model_validate(json.loads(decompress_mesh_bytes(mesh_path.read_bytes())))
    lats = np.array([c.lat for c in mesh.cells], dtype=np.float64)
    lons = np.array([c.lon for c in mesh.cells], dtype=np.float64)

    # 1. Köppen (Beck) → per-cell koppen_class (ocean cells → "Ocean").
    beck = _load_beck_koppen(beck_path)
    beck_codes = _sample_beck(beck, lats, lons)
    for c, code in zip(mesh.cells, beck_codes, strict=True):
        cls = _BECK_LEGEND.get(int(code), "N/A")
        c.koppen_class = "Ocean" if c.water_class == "ocean" else cls

    # 2. Temperature (NCEP) → _t_monthly_c (N×12) + temperature_C (annual mean).
    t_arr, t_lat, t_lon = _load_nc_monthly(data_dir / "ncep_air.mon.ltm.nc", "air")
    t_monthly = _sample_monthly(t_arr, t_lat, t_lon, lats, lons).T  # (N, 12), cell-major
    t_annual = t_monthly.mean(axis=1)

    # 3. Precipitation (GPCP) → _p_monthly_mm (N×12) + precipitation_mm (annual).
    p_arr, p_lat, p_lon = _load_gpcp_climatology(data_dir / "gpcp_precip.mon.mean.nc")
    p_monthly = _sample_monthly(p_arr, p_lat, p_lon, lats, lons).T  # (N, 12), mm/month
    p_annual = p_monthly.sum(axis=1)

    # 4. Pressure (NCEP SLP) → _pressure_monthly (N×12, seasonal anomaly) +
    #    per-cell slp_annual_hpa (annual-mean SLP, the subtropical-high field).
    slp_arr, slp_lat, slp_lon = _load_nc_monthly(data_dir / "ncep_slp.mon.ltm.nc", "slp")
    slp_monthly = _sample_monthly(slp_arr, slp_lat, slp_lon, lats, lons).T  # (N, 12), hPa
    pressure_monthly = slp_monthly - slp_monthly.mean(axis=1, keepdims=True)
    slp_annual = slp_monthly.mean(axis=1)

    # Hottest / coldest month from the monthly temperature (order-independent).
    t_hottest = t_monthly.max(axis=1)
    t_coldest = t_monthly.min(axis=1)

    # Ice-cap override: Köppen "EF" is defined by warmest month < 0°C.  Beck's map
    # leaves the Antarctic ice margin as "N/A" (floating shelf treated as ocean)
    # and mis-labels a few high-latitude cells BSk/BWk; any land cell whose warmest
    # month is below freezing is physically EF, whatever Beck says.
    for c, t_hot in zip(mesh.cells, t_hottest, strict=True):
        if c.water_class == "land" and t_hot < 0.0:
            c.koppen_class = "EF"

    # 5. Wind (NCEP uwnd/vwnd, near-surface) → annual-mean east/north components.
    uw_arr, uw_lat, uw_lon = _load_nc_monthly(data_dir / "ncep_uwnd.mon.ltm.nc", "uwnd")
    vw_arr, vw_lat, vw_lon = _load_nc_monthly(data_dir / "ncep_vwnd.mon.ltm.nc", "vwnd")
    wind_east = _sample_monthly(uw_arr, uw_lat, uw_lon, lats, lons).T.mean(axis=1)
    wind_north = _sample_monthly(vw_arr, vw_lat, vw_lon, lats, lons).T.mean(axis=1)

    # Reorder observation months (Jan-first) to the engine's March-first order.
    t_monthly = t_monthly[:, _MARCH_FIRST]
    p_monthly = p_monthly[:, _MARCH_FIRST]
    pressure_monthly = pressure_monthly[:, _MARCH_FIRST]

    # Coast distance from the water mask (graph Dijkstra from ocean cells).
    from dreamulator.map.climate_simulator import _graph_distance_to_coast

    is_land_arr = np.array([c.water_class == "land" for c in mesh.cells], dtype=bool)
    dist_to_coast, _ = _graph_distance_to_coast(mesh.cells, len(mesh.cells), is_land_arr)

    for i, c in enumerate(mesh.cells):
        c.temperature_C = float(t_annual[i])
        c.precipitation_mm = float(p_annual[i])
        c.temperature_hottest_month_C = float(t_hottest[i])
        c.temperature_coldest_month_C = float(t_coldest[i])
        c.wind_east_m_s = float(wind_east[i])
        c.wind_north_m_s = float(wind_north[i])
        c.slp_annual_hpa = float(slp_annual[i])
        _d = dist_to_coast[i]
        c.distance_to_coast_km = float(_d) if np.isfinite(_d) else None

    # 6. Ocean currents — observed where possible: SODA v3.15.2 monthly
    #    climatology (annual mean into ocean cells).  Fallback when the SODA
    #    file is absent: the engine's Stommel gyre solver driven by the
    #    observed NCEP wind above (modelled).  Either way the observed T/P
    #    fields stay untouched (no SST advection onto ground truth).
    soda_path = data_dir / _SODA_CURRENTS_NC
    if soda_path.exists():
        u_clim, v_clim, cur_lat, cur_lon, cur_attrs = _load_soda_climatology(soda_path)
        n_cur = _apply_observed_currents(mesh.cells, lats, lons, u_clim, v_clim, cur_lat, cur_lon)
        print(f"  Ocean currents (observed SODA v3.15.2, annual mean): {n_cur} cells")
        currents_source = (
            "observed — SODA v3.15.2 surface (~5 m) monthly climatology "
            f"{cur_attrs.get('climatology_years', '')}, annual mean; APDRC OPeNDAP "
            "(Carton et al. 2018, doi:10.1175/JCLI-D-18-0149.1)"
        )
    else:
        print(f"  SODA climatology not found ({soda_path.name}) — Stommel fallback")
        _compute_ocean_currents(mesh.cells, wind_east, wind_north)
        currents_source = (
            "modelled — Stommel barotropic gyres (engine solver, "
            "map/ocean_circulation.py) driven by NCEP annual-mean wind"
        )

    # Attach monthly fields for the msgpack export (runtime attrs, not pydantic).
    object.__setattr__(mesh, "_t_monthly_c", t_monthly.astype(np.float32))
    object.__setattr__(mesh, "_p_monthly_mm", p_monthly.astype(np.float32))
    object.__setattr__(mesh, "_pressure_monthly", pressure_monthly.astype(np.float32))

    # Write cvt_mesh.json (per-cell annual climate fields).
    mesh_path.write_bytes(
        compress_mesh_bytes(json.dumps(mesh.model_dump(mode="json")).encode("utf-8"))
    )
    print(f"  Updated cvt_mesh.json: {mesh_path}")

    # Write climate_monthly.msgpack (quantized int16, same as the engine).
    _write_monthly_msgpack(mesh, output_dir)

    # Secondary exports the frontend ignores but keep for consistency.
    _write_secondary_exports(mesh, output_dir, project_root, currents_source)


def _write_monthly_msgpack(mesh: CVTMesh, output_dir: Path) -> None:
    from dreamulator.map.export import _quantize_int16

    t_monthly = getattr(mesh, "_t_monthly_c", None)
    p_monthly = getattr(mesh, "_p_monthly_mm", None)
    pr_monthly = getattr(mesh, "_pressure_monthly", None)
    assert t_monthly is not None and p_monthly is not None and pr_monthly is not None

    _t_q, _t_s, _t_o = _quantize_int16(t_monthly)
    _p_q, _p_s, _p_o = _quantize_int16(p_monthly)
    _pr_q, _pr_s, _pr_o = _quantize_int16(pr_monthly)
    import msgpack

    monthly = {
        "num_cells": mesh.num_cells,
        "months": 12,
        "dtype": "int16",
        "t_monthly": _t_q,
        "t_scale": _t_s,
        "t_offset": _t_o,
        "p_monthly": _p_q,
        "p_scale": _p_s,
        "p_offset": _p_o,
        "pressure_monthly": _pr_q,
        "pressure_scale": _pr_s,
        "pressure_offset": _pr_o,
        "temperature_range_c": [float(np.min(t_monthly)), float(np.max(t_monthly))],
        "precipitation_range_mm": [float(np.min(p_monthly)), float(np.max(p_monthly))],
        "pressure_range_hpa": [float(np.min(pr_monthly)), float(np.max(pr_monthly))],
        "month_0": "vernal_equinox",
    }
    (output_dir / "climate_monthly.msgpack").write_bytes(msgpack.packb(monthly))
    print(f"  Wrote climate_monthly.msgpack: {output_dir / 'climate_monthly.msgpack'}")


def _write_secondary_exports(
    mesh: CVTMesh, output_dir: Path, project_root: Path, currents_source: str
) -> None:
    from collections import Counter

    from dreamulator.map.export import export_equirectangular, export_layer_png

    width, height = 4096, 2048

    # koppen.json — {cells, summary, num_cells} (simulated-export schema).
    koppen_by_cell = {str(c.id): c.koppen_class for c in mesh.cells if c.koppen_class}
    koppen_counter = Counter(koppen_by_cell.values())
    koppen_data = {
        "cells": koppen_by_cell,
        "summary": dict(koppen_counter),
        "num_cells": mesh.num_cells,
    }
    (output_dir / "koppen.json").write_text(json.dumps(koppen_data), encoding="utf-8")

    # temperature.png / precipitation.png rasters (annual fields).
    temp_grid = export_equirectangular(mesh, width, height, field="temperature_C")
    precip_grid = export_equirectangular(mesh, width, height, field="precipitation_mm")
    export_layer_png(
        temp_grid, output_dir / "temperature.png", float(temp_grid.min()), float(temp_grid.max())
    )
    export_layer_png(
        precip_grid,
        output_dir / "precipitation.png",
        float(precip_grid.min()),
        float(precip_grid.max()),
    )

    # climate_metadata.json — minimal real-data provenance + ranges.
    meta = {
        "source": "NCEP/NCAR Reanalysis 1 + GPCP v2.3 + Beck et al. (2018)",
        "ocean_currents": currents_source,
        "temperature_range_c": [float(temp_grid.min()), float(temp_grid.max())],
        "precipitation_range_mm": [float(precip_grid.min()), float(precip_grid.max())],
        "koppen_classes": sorted(koppen_counter.keys()),
        "export_resolution": [width, height],
    }
    (output_dir / "climate_metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print("  Wrote koppen.json / temperature.png / precipitation.png / climate_metadata.json")


def _find_project_root() -> Path:
    d = Path.cwd()
    while d != d.parent:
        if (d / "pyproject.toml").exists():
            return d
        d = d.parent
    return Path.cwd()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import real Earth climate observation into the earth base world",
    )
    parser.add_argument(
        "--output-dir",
        default="data/worlds/earth/maps/planet_earth",
        help="Map output directory (must contain cvt_mesh.json)",
    )
    args = parser.parse_args()
    output_dir = _find_project_root() / args.output_dir
    import_earth_climate(output_dir)
    print("\nDone! Real Earth climate imported.")


if __name__ == "__main__":
    main()
