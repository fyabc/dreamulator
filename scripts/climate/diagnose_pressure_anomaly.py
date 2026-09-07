"""Pressure-anomaly / zonal-asymmetry validation vs NCEP (7-②).

The wind field is purely zonal (three-cell) because the annual-mean land-sea
thermal contrast is dropped, so there is no subtropical high / stationary wave.
This script quantifies the gap against NCEP long-term means:

  1. **Subtropical-high strength** — the zonal std of the annual-mean SLP
     anomaly (departure from the zonal mean) averaged over 20-40°, both
     hemispheres.  The subtropical highs (Azores / Pacific) live in this band.
  2. **Zonal-wind asymmetry** — the zonal std of the annual-mean zonal wind
     (uwnd) over 20-40°.  The subtropical anticyclones imprint east-west wind
     variation here.
  3. **SLP-anomaly spatial correlation** — the model's ΔP (land-sea pressure
     contrast) correlated against NCEP's SLP anomaly over 20-40°.

The model's ΔP is computed from the annual-mean land-sea temperature contrast
ΔT = T − T_zonal (no annual-mean removal), with a configurable column
depth-fraction d/H; the geostrophic wind follows `_geostrophic_wind`.

Usage:
    uv run python scripts/climate/diagnose_pressure_anomaly.py --world-dir data/worlds
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import scipy.sparse as sparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dreamulator.engine.climate_physics import coriolis_parameter  # noqa: E402
from dreamulator.engine.monsoon_circulation import zonal_mean_monthly  # noqa: E402
from dreamulator.map.climate_simulator import (  # noqa: E402
    _geostrophic_wind,
    _graph_least_squares_gradient,
    _smooth_graph,
    simulate_climate,
)
from dreamulator.map.ocean_circulation import (  # noqa: E402
    _build_directed_edge_table,
    decompose_tangent,
    east_north_basis,
)
from dreamulator.validate_climate import _load_mesh, build_earth_validation_config  # noqa: E402

_NCEP_DIR = Path(__file__).resolve().parents[2] / "private" / "tmp" / "climatology"


def _ncep_annual(var: str) -> tuple[np.ndarray, np.ndarray]:
    """Return (annual-mean field, latitude) for the NCEP variable."""
    import xarray as xr

    ds = xr.open_dataset(_NCEP_DIR / f"ncep_{var}.mon.ltm.nc", decode_times=False)
    field = np.asarray(ds[var].mean(dim="time").values, dtype=np.float64)  # (lat, lon)
    lat = np.asarray(ds["lat"].values, dtype=np.float64)
    ds.close()
    return field, lat


def _zonal_std_band(field: np.ndarray, lat: np.ndarray, lo: float, hi: float) -> float:
    """Mean zonal std of a (lat, lon) field over |lat| in [lo, hi]."""
    band = np.abs(lat) >= lo
    band &= np.abs(lat) <= hi
    anom = field - field.mean(axis=1, keepdims=True)  # departure from zonal mean
    std = anom.std(axis=1)  # per-latitude zonal std
    return float(np.mean(std[band]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--world", default="earth")
    parser.add_argument("--planet", default="planet_earth")
    parser.add_argument("--branch", default="climate-dev")
    parser.add_argument("--world-dir", default="data/worlds")
    parser.add_argument("--dh", default="1.0")
    args = parser.parse_args()

    # --- NCEP reference ---
    slp, nlat = _ncep_annual("slp")
    uwnd, _ = _ncep_annual("uwnd")
    print("\n=== NCEP reference (annual-mean, 20-40 deg) ===")
    ncep_slp_std = _zonal_std_band(slp, nlat, 20.0, 40.0)
    ncep_u_std = _zonal_std_band(uwnd, nlat, 20.0, 40.0)
    print(f"  SLP anomaly zonal std  : {ncep_slp_std:.2f} hPa")
    print(f"  uwnd zonal std         : {ncep_u_std:.2f} m/s")

    # --- Model ---
    root = Path(__file__).resolve().parents[2]
    mesh = _load_mesh(root / args.world_dir / args.world, args.planet, args.branch or None)
    if mesh is None:
        print("ERROR: no mesh")
        return
    config = build_earth_validation_config(mesh.num_cells)
    simulate_climate(mesh, config)

    n = mesh.num_cells
    lat_deg = np.array([c.lat for c in mesh.cells], dtype=np.float64)
    lon_deg = np.array([c.lon for c in mesh.cells], dtype=np.float64)
    nodes_xyz = np.array([[c.x, c.y, c.z] for c in mesh.cells], dtype=np.float64)

    t_monthly = np.asarray(mesh._t_monthly_c, dtype=np.float64)
    t_annual = t_monthly.mean(axis=1)
    t_zonal_annual = zonal_mean_monthly(t_annual[:, None], lat_deg)[:, 0]
    dt_annual = t_annual - t_zonal_annual
    t_zonal_k = np.maximum(t_zonal_annual + 273.15, 200.0)

    # Synoptic smoothing + gradient (replicate Stage 2).
    _msrc, _mdst = _build_directed_edge_table(mesh.cells)
    _cell_km = 2.0 * config.radius_km * np.sqrt(np.pi / n)
    _mdeg = np.maximum(np.bincount(_msrc, minlength=n).astype(np.float64), 1.0)
    _avg = sparse.csr_matrix((1.0 / _mdeg[_msrc], (_msrc, _mdst)), shape=(n, n))
    _n_smooth = 2 * int((500.0 / _cell_km) ** 2)
    _radius_m = config.radius_km * 1000.0

    lat_rad = np.radians(lat_deg)
    f_coriolis = coriolis_parameter(lat_rad, config.rotation_period_days)
    east, north = east_north_basis(nodes_xyz)

    dh = float(args.dh)
    dp_hpa = -config.surface_pressure_hpa * dh * dt_annual / t_zonal_k
    dp_hpa = _smooth_graph(dp_hpa, _avg, _n_smooth)
    grad = _graph_least_squares_gradient(mesh, dp_hpa, nodes_xyz) * 100.0 / _radius_m
    vg = _geostrophic_wind(grad, f_coriolis, nodes_xyz)
    we, wn = decompose_tangent(vg, east, north)
    we = -we  # physical east (frontend) convention

    print(f"\n=== Model (annual-mean, d/H={dh}, 20-40 deg) ===")
    # Zonal std on the CVT mesh: bin into 5° bands, std of the field per band.
    def _cell_zonal_std(field: np.ndarray) -> float:
        bands = np.arange(20.0, 40.0, 5.0)
        vals = []
        for b in bands:
            m = (np.abs(lat_deg) >= b) & (np.abs(lat_deg) < b + 5.0)
            if m.sum() > 1:
                vals.append(float(np.std(field[m])))
        return float(np.mean(vals)) if vals else 0.0

    mdl_slp_std = _cell_zonal_std(dp_hpa)
    mdl_u_std = _cell_zonal_std(we)
    print(f"  dP anomaly zonal std   : {mdl_slp_std:.2f} hPa  (NCEP {ncep_slp_std:.2f})")
    print(f"  geostrophic u zonal std: {mdl_u_std:.2f} m/s  (NCEP {ncep_u_std:.2f})")

    # Spatial correlation of the model dP vs NCEP SLP anomaly (interp to mesh).
    from scipy.interpolate import RegularGridInterpolator  # noqa: E402

    slp_anom = slp - slp.mean(axis=1, keepdims=True)
    nlon = np.linspace(0.0, 357.5, slp.shape[1])
    interp = RegularGridInterpolator((nlat, nlon), slp_anom, bounds_error=False, fill_value=0.0)
    pts = np.stack(
        [
            lat_deg,
            np.where(lon_deg >= 0.0, lon_deg, lon_deg + 360.0),
        ],
        axis=1,
    )
    ncep_at_cells = interp(pts)
    band = (np.abs(lat_deg) >= 20.0) & (np.abs(lat_deg) <= 40.0)
    a, b = dp_hpa[band], ncep_at_cells[band]
    corr = float(np.corrcoef(a, b)[0, 1])
    print(f"  dP vs NCEP SLP anomaly spatial correlation: {corr:+.3f}")


if __name__ == "__main__":
    main()
