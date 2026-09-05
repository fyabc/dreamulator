"""Monthly temperature & wind validation against NCEP monthly climatology.

Re-runs the climate simulation on the Earth validation mesh, then compares the
model's monthly surface temperature / zonal wind (u) / meridional wind (v)
against the NCEP Reanalysis monthly long-term means (sigma 0.995 surface level,
``private/tmp/climatology/ncep_{air,uwnd,vwnd}.mon.ltm.nc``).  This fills the
"monthly accuracy" gap the annual metrics cannot see: the seasonal cycle shape,
the monsoon wind reversal, and the mid-latitude westerly belt.

Two apertures, combined:

- **Global (zonal-mean)** — model vs NCEP per 2.5° latitude band, 12 months:
  RMSE, R2, and spatial correlation for T / u / v.
- **Station** — the 26 reference stations' monthly T (annual-mean / amplitude /
  phase errors), reusing ``station_diagnostics.py``.

Usage::

    uv run python scripts/diagnose_monthly_validation.py
    uv run python scripts/diagnose_monthly_validation.py --world-dir private/worlds
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from station_diagnostics import STATIONS  # noqa: E402

from dreamulator.map.climate_simulator import simulate_climate  # noqa: E402
from dreamulator.validate_climate import (  # noqa: E402
    _load_mesh,
    build_earth_validation_config,
)

_NCEP_DIR = Path(__file__).resolve().parent.parent / "private" / "tmp" / "climatology"
_NCEP_FILES = {
    "air": _NCEP_DIR / "ncep_air.mon.ltm.nc",
    "uwnd": _NCEP_DIR / "ncep_uwnd.mon.ltm.nc",
    "vwnd": _NCEP_DIR / "ncep_vwnd.mon.ltm.nc",
}


def _load_ncep_zonal(var: str) -> tuple[np.ndarray, np.ndarray]:
    """Return (zonal_mean, lat) from the NCEP monthly file for ``var``.

    ``var`` is the NCEP variable name (air / uwnd / vwnd); zonal_mean shape
    (12, 73) = month × latitude (90 … -90, 2.5° steps).
    """
    import xarray as xr

    # decode_times=False: we index months by array position (0 = January), not
    # by the calendar time axis, and the pre-1582 cftime decoding warns.
    ds = xr.open_dataset(_NCEP_FILES[var], decode_times=False)
    lat = np.asarray(ds["lat"].values, dtype=np.float64)
    zm = ds[var].mean(dim="lon").values  # (12, 73)
    ds.close()
    return np.asarray(zm, dtype=np.float64), lat


def _model_zonal(field: np.ndarray, lat: np.ndarray, n_lat: int) -> np.ndarray:
    """Bin a model monthly field (N, 12) into 2.5° latitude bands → (12, n_lat).

    Bands match the NCEP grid (90 … -90).  Model month 0 = March; the returned
    array is re-indexed to calendar month order (0 = January) for comparison.
    """
    idx = np.clip(((90.0 - lat) / 2.5).astype(int), 0, n_lat - 1)
    out = np.zeros((12, n_lat), dtype=np.float64)
    for m in range(12):
        np.add.at(out[m], idx, field[:, m])
    counts = np.bincount(idx, minlength=n_lat).astype(np.float64)
    out /= np.maximum(counts, 1.0)[None, :]
    # model month m (0=Mar) == calendar (m+2)%12 → calendar j from model (j-2)%12
    return np.asarray([out[(j - 2) % 12] for j in range(12)])


def _rmse_r2(a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    a = a.ravel()
    b = b.ravel()
    m = np.isfinite(a) & np.isfinite(b)
    a, b = a[m], b[m]
    rmse = float(np.sqrt(np.mean((a - b) ** 2)))
    r2 = float(np.corrcoef(a, b)[0, 1] ** 2)
    return rmse, r2


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--world", default="earth")
    parser.add_argument("--planet", default="planet_earth")
    parser.add_argument("--branch", default="climate-dev", help="empty string for root world")
    parser.add_argument("--world-dir", default="private/worlds")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    world_dir = root / args.world_dir / args.world
    mesh = _load_mesh(world_dir, args.planet, args.branch or None)
    if mesh is None:
        print(f"ERROR: no mesh at {world_dir} (branch={args.branch})")
        return

    print(f"Running climate simulation on {mesh.num_cells} cells ...")
    simulate_climate(mesh, build_earth_validation_config(mesh.num_cells))

    t_model = np.asarray(mesh._t_monthly_c, dtype=np.float64)
    u_model = np.asarray(mesh._wind_east_monthly, dtype=np.float64)
    v_model = np.asarray(mesh._wind_north_monthly, dtype=np.float64)
    lat = np.array([c.lat for c in mesh.cells], dtype=np.float64)

    n_lat = 73
    print("\n=== Monthly zonal-mean vs NCEP (RMSE | R2) ===")
    for name, model, var in [
        ("temperature", t_model, "air"),
        ("zonal wind u", u_model, "uwnd"),
        ("meridional wind v", v_model, "vwnd"),
    ]:
        obs, _ = _load_ncep_zonal(var)
        mdl = _model_zonal(model, lat, n_lat)
        rmse, r2 = _rmse_r2(mdl, obs)
        print(f"  {name:<16} RMSE={rmse:>8.2f}  R2={r2:.3f}")

    # Per-month RMSE for temperature (the seasonal-cycle shape).
    obs_t, ncep_lat = _load_ncep_zonal("air")
    mdl_t = _model_zonal(t_model, lat, n_lat)
    print("\n=== Monthly temperature RMSE by month (model vs NCEP) ===")
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    for j in range(12):
        r, _ = _rmse_r2(mdl_t[j], obs_t[j])
        print(f"  {months[j]:<3} RMSE={r:>6.2f} C", end="")
    print()

    # Station aperture (annual-mean / amplitude / phase of monthly T).
    print("\n=== Station monthly T (26 stations, model - observed) ===")
    xyz = np.array([[c.x, c.y, c.z] for c in mesh.cells])
    rows = []
    for s in STATIONS:
        p = np.array(
            [
                np.cos(np.radians(s["lat"])) * np.cos(np.radians(s["lon"])),
                np.sin(np.radians(s["lat"])),
                np.cos(np.radians(s["lat"])) * np.sin(np.radians(s["lon"])),
            ]
        )
        gi = int(np.argmax(xyz @ p))
        mcal = t_model[gi][(np.arange(12) - 2) % 12]
        obs = np.array(s["t"])
        rows.append(
            (
                s["koppen"][0],
                mcal.mean() - obs.mean(),
                (mcal.max() - mcal.min()) / 2 - (obs.max() - obs.min()) / 2,
            )
        )
    for g in "ABCDE":
        sel = [r for r in rows if r[0] == g]
        if sel:
            print(
                f"  {g}: n={len(sel):>2}  meanE={np.mean([r[1] for r in sel]):>6.1f} "
                f"ampE={np.mean([r[2] for r in sel]):>6.1f}"
            )


if __name__ == "__main__":
    main()
