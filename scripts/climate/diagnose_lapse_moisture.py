#!/usr/bin/env python3
"""Diagnose the lapse-rate dry/wet dimension (read-only feasibility check).

Physics
-------
The surface lapse rate that converts a sea-level temperature into the surface
temperature over topography sits between two adiabatic bounds:

  * moist (saturated) adiabatic  Γ_m(T) ≈ 4.5–6.5 °C/km  — latent heat release
    during ascent shallows the lapse, and the value depends on temperature
    (warm air holds more vapour → more latent heat → shallower);
  * dry / environmental            Γ_d ≈ 6.5 °C/km        — no latent heat.

Himalayan SELR observations show the *presence or absence of moisture* is the
single dominant control, not temperature (monsoon regime 1.9–9.0 °C/km vs
cold-arid Ladakh 2.8–17 °C/km).  The engine's current ``moist_lapse_rate`` keys
Γ on **sea-level temperature** alone, which is a proxy for *potential* moisture
(saturation capacity via Clausius–Clapeyron) — it implicitly assumes every
column is saturated.  A dry highland at a warm latitude (Tibet, ~20 °C at sea
level → Γ_m ≈ 4.9) therefore gets a too-shallow lapse and comes out ~+10 °C too
warm.

Proposed scheme (this script evaluates it, *without* touching the engine):

    Γ_new = Γ_m(T_sl)·φ + Γ_d·(1−φ)     φ = P / (P + P₀)

  * wet cell (φ→1) → Γ_m(T_sl) (unchanged), dry cell (φ→0) → Γ_d = 6.5 (steeper).

This is a P→T feedback (φ is the downstream precipitation field), i.e. the
missing edge ``climate-steady-coupling.md`` describes; this script hand-computes
the *one-pass* version (φ from the model's current P) as the feasibility step
the coupling proposal recommends before any engine change.  The final engine
signal should be column relative humidity W/W_sat (first-principles), for which
the model's own P is a stand-in here because W is a solver intermediate and not
stored in the mesh.

Usage (earth climate-dev only — a fictional world has no observed reference)::

    uv run python scripts/climate/diagnose_lapse_moisture.py \
        data/worlds/earth/branches/climate-dev/maps/planet_earth \
        --temp private/tmp/climatology/ncep_air.mon.ltm.nc
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

import numpy as np
import xarray as xr

from dreamulator.engine.climate_physics import moist_lapse_rate

# ---------------------------------------------------------------------------
# Regions of interest (the lapse-rate residual anomalies from proposal §1).
# lon is degrees East (negative = West); a cell matches when lat/lon fall in
# the box AND elevation exceeds ``elev_min`` (metres).
# ---------------------------------------------------------------------------
REGIONS: list[dict] = [
    dict(name="青藏高原 (Tibet)", lat=(28, 40), lon=(75, 105), elev_min=3000),
    dict(name="华南 (S. China)", lat=(20, 30), lon=(105, 122), elev_min=0),
    dict(name="高加索 (Caucasus)", lat=(40, 45), lon=(40, 48), elev_min=1000),
    dict(name="天山 (Tianshan)", lat=(40, 45), lon=(75, 90), elev_min=1500),
    dict(name="落基山脉 (Rockies)", lat=(35, 50), lon=(-115, -105), elev_min=1500),
    dict(name="安第斯高原 (Altiplano)", lat=(-22, -14), lon=(-70, -64), elev_min=3000),
    dict(name="热带湿润高地 (Quito)", lat=(-2, 2), lon=(-80, -76), elev_min=1500),
]

P0_DEFAULT = 500.0  # mm/yr — arid/humid threshold used for the wetness sigmoid
GAMMA_DRY_DEFAULT = 6.5  # °C/km — environmental (dry) lapse rate


def _bilinear(
    lat_deg: np.ndarray,
    lon_deg: np.ndarray,
    field: np.ndarray,
    lat_axis: np.ndarray,
    lon_axis: np.ndarray,
) -> np.ndarray:
    """Bilinear-sample ``field[nlat, nlon]`` at (lat, lon); axes any order.

    Mirrors the frontend ``_sample`` in ``generate_spatial_reference.py``.
    ``lat_axis`` may be ascending or descending; ``lon_axis`` is regular and
    wraps at 360° (NCEP lon 0 → 357.5, dlon 2.5).
    """
    nlat, nlon = field.shape
    fi = (lat_deg - lat_axis[0]) / (lat_axis[-1] - lat_axis[0]) * (nlat - 1)
    dlon = lon_axis[1] - lon_axis[0]
    fj = ((lon_deg - lon_axis[0]) / dlon) % nlon

    i0 = np.clip(np.floor(fi).astype(np.int64), 0, nlat - 2)
    j0 = np.floor(fj).astype(np.int64)
    j1 = (j0 + 1) % nlon
    di = fi - i0
    dj = fj - j0

    v00 = field[i0, j0]
    v01 = field[i0, j1]
    v10 = field[i0 + 1, j0]
    v11 = field[i0 + 1, j1]
    top = v00 + (v01 - v00) * dj
    bot = v10 + (v11 - v10) * dj
    return top + (bot - top) * di


def _sea_level_temp(t_surface: np.ndarray, elev_km: np.ndarray) -> np.ndarray:
    """Invert the lapse correction to recover the sea-level temperature.

    ``t_surface = t_sl − moist_lapse_rate(t_sl)·elev_km`` (fixed point in t_sl;
    the map is contractive because ∂Γ/∂T is small, so a few iterations converge).
    """
    t_sl = t_surface + GAMMA_DRY_DEFAULT * elev_km
    for _ in range(8):
        t_sl = t_surface + moist_lapse_rate(t_sl) * elev_km
    return t_sl


def _wetness(precip_mm: np.ndarray, p0: float) -> np.ndarray:
    """Moisture signal φ ∈ [0, 1]: 1 = saturated (moist lapse), 0 = dry."""
    return precip_mm / (precip_mm + p0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("map_dir", help="path to maps/<planet_id>/ (holds cvt_mesh.json)")
    parser.add_argument("--temp", required=True, help="NCEP air.mon.ltm.nc (observed T)")
    parser.add_argument("--p0", type=float, default=P0_DEFAULT, help="wetness threshold (mm/yr)")
    parser.add_argument("--gamma-dry", type=float, default=GAMMA_DRY_DEFAULT,
                        help="dry/environmental lapse rate (°C/km)")
    args = parser.parse_args()

    mesh_path = Path(args.map_dir) / "cvt_mesh.json"
    if not mesh_path.exists():
        print(f"missing {mesh_path} (build earth climate-dev first)")
        sys.exit(1)

    with gzip.open(mesh_path, "rb") as f:
        mesh = json.load(f)
    cells = mesh["cells"]
    lat = np.array([c["lat"] for c in cells], dtype=np.float64)
    lon = np.array([c["lon"] for c in cells], dtype=np.float64)
    elev = np.array([c["elevation"] for c in cells], dtype=np.float64)
    t_mod = np.array([c["temperature_C"] for c in cells], dtype=np.float64)
    p_mod = np.array([c["precipitation_mm"] for c in cells], dtype=np.float64)
    water = np.array([c["water_class"] for c in cells], dtype=str)

    # Observed annual temperature: NCEP air (native grid lat 90→−90, lon 0→357.5).
    ncep = xr.open_dataset(args.temp, decode_times=False)
    air = ncep["air"]
    if air.attrs.get("units", "").lower().startswith("k"):
        air = air - 273.15
    t_obs_grid = air.mean(dim="time").values
    t_lat = np.asarray(air.lat.values)
    t_lon = np.asarray(air.lon.values)

    land = (water == "land") & np.isfinite(t_mod) & np.isfinite(p_mod)
    print(f"cells={len(cells)}  land={int(land.sum())}  "
          f"P₀={args.p0:g} mm/yr  Γ_dry={args.gamma_dry:g} °C/km\n")

    t_obs = _bilinear(lat, lon, t_obs_grid, t_lat, t_lon)

    # Recover sea-level temperature, current lapse, and the dry/wet replacement.
    elev_km = np.maximum(elev, 0.0) / 1000.0
    t_sl = _sea_level_temp(t_mod, elev_km)
    gamma_m = moist_lapse_rate(t_sl)          # current lapse (moist, T-keyed)
    phi = _wetness(p_mod, args.p0)            # moisture signal (dry/wet)
    gamma_new = gamma_m * phi + args.gamma_dry * (1.0 - phi)
    t_new = t_sl - gamma_new * elev_km        # surface T under the new lapse

    # ---- global summary (land only) ---------------------------------------
    d_before = t_mod - t_obs
    d_after = t_new - t_obs
    def _rmse(d: np.ndarray) -> float:
        return float(np.sqrt(np.mean(d[land] ** 2)))
    print("global (land):")
    print(f"  RMSE  before {_rmse(d_before):5.2f} °C  →  after {_rmse(d_after):5.2f} °C")
    print(f"  bias  before {np.mean(d_before[land]):+5.2f} °C  →  after {np.mean(d_after[land]):+5.2f} °C")
    print(f"  Γ     mean {np.mean(gamma_m[land]):.2f} → {np.mean(gamma_new[land]):.2f} °C/km   "
          f"φ mean {np.mean(phi[land]):.2f}\n")

    # ---- per-region table --------------------------------------------------
    print(f"{'region':<22} {'n':>5} {'T_mod':>6} {'T_obs':>6} {'ΔT_before':>9} {'ΔT_after':>8} "
          f"{'Γ_cur':>5} {'Γ_new':>5} {'φ':>4}")
    print("-" * 78)
    for r in REGIONS:
        m = (
            land
            & (lat >= r["lat"][0]) & (lat <= r["lat"][1])
            & (lon >= r["lon"][0]) & (lon <= r["lon"][1])
            & (elev >= r["elev_min"])
        )
        if m.sum() == 0:
            print(f"{r['name']:<22} {'—':>5}  (no cells in box)")
            continue
        print(
            f"{r['name']:<22} {int(m.sum()):>5} {np.mean(t_mod[m]):>6.1f} {np.mean(t_obs[m]):>6.1f} "
            f"{np.mean(d_before[m]):>+9.1f} {np.mean(d_after[m]):>+8.1f} "
            f"{np.mean(gamma_m[m]):>5.2f} {np.mean(gamma_new[m]):>5.2f} {np.mean(phi[m]):>4.2f}"
        )

    # ---- sensitivity scan ---------------------------------------------------
    print("\nsensitivity (青藏 ΔT_after and global RMSE_after):")
    tibet = (
        land & (lat >= 28) & (lat <= 40) & (lon >= 75) & (lon <= 105) & (elev >= 3000)
    )
    print(f"{'P₀ (mm/yr)':<12} {'Γ_dry (°C/km)':<14} {'青藏 ΔT_after':>12} {'global RMSE_after':>18}")
    for p0 in (250.0, 500.0, 1000.0):
        for gd in (6.5, 8.0):
            ph = _wetness(p_mod, p0)
            gn = gamma_m * ph + gd * (1.0 - ph)
            tn = t_sl - gn * elev_km
            da = tn - t_obs
            print(
                f"{p0:<12g} {gd:<14g} {np.mean(da[tibet]):>+12.1f} {_rmse(da):>18.2f}"
            )


if __name__ == "__main__":
    main()
