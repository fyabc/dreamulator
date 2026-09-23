"""Monsoon ΔP calibration check vs NCEP SLP (M4/B0b full-contrast convention).

Runs *offline* on archived build outputs (no rebuild).  Since B0b + M4
(2026-09-14) the engine's ``pressure_anomaly_monthly`` carries the *full*
monthly land-sea contrast (annual mean included) with the derived BL
projection factor E ≈ 0.10, so the matching reference is the **full**
NCEP land-vs-same-latitude-ocean SLP contrast C = SLP_box,m − SLP_oceanZonal,m
(the old "seasonal anomaly" reference D = C − ⟨C⟩ belonged to the removed
annual-mean subtraction).

Per box it reports

  model ΔP (archived ``pressure_monthly``), C (full NCEP contrast),
  ratio = ΔP/C (target 0.8-1.25 for the dry/winter boxes), and the
  implied projection factor E = −C·T̄/(P_sfc·ΔT_full) for anchor drift.

Known accepted residual (δMCD/δTH decomposition 2026-09-14, proposal §5
#2): the wet deep-convective monsoon boxes (India/South-China summer lows,
latent heating through the whole column, E ≈ 0.37-0.40 needed) are
undershot ~4× by the single dry-BL factor — no Stage-2-available,
non-circular discriminator separates them (supply geography, model P,
background-wind tracing all falsified; see proposal §2/§5), so their
amplitude moves to the moisture-routing line (D) instead of a per-region
ΔP retune.

History (2026-09-13 Stage C, pre-M4): the monsoon ΔP amplitude was
calibrated 0.73-1.29 against the *seasonal* reference with f_deep = 0.25;
the Sahara 5× / Siberia 2.4× residuals led to the g(W)/aridity-keep/
_dt_subsidence discriminator hunt, all falsified (proposal §2 已否证 —
equal-W opposite-need, P-circular gate, zonal symmetry).

Usage:
    uv run python scripts/climate/diagnose_monsoon_dp_shape.py
    uv run python scripts/climate/diagnose_monsoon_dp_shape.py --branch climate-dev
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from dreamulator.engine.monsoon_circulation import (  # noqa: E402
    _MONSOON_PROJECTION_FRACTION,
    zonal_mean_monthly,
)
from dreamulator.map.export import find_mesh_file, load_cvt_mesh  # noqa: E402

_ROOT = Path(__file__).resolve().parents[2]
_NCEP_SLP = _ROOT / "private" / "tmp" / "climatology" / "ncep_slp.mon.ltm.nc"

# Boxes: (name, lat_lo, lat_hi, lon_lo, lon_hi, ncep_month) with month in NCEP
# index (Jan=0 … Jul=6).  Model month = (ncep_month + 10) % 12 (month 0 =
# March): Jul(6) → 4, Jan(0) → 10.
_BOXES = [
    ("印度低压", 22.0, 30.0, 75.0, 90.0, 6),
    ("哈萨克/图兰", 42.0, 48.0, 60.0, 75.0, 6),
    ("华南", 22.0, 28.0, 108.0, 118.0, 6),
    ("撒哈拉", 20.0, 28.0, 5.0, 25.0, 6),
    ("西伯利亚", 55.0, 65.0, 80.0, 110.0, 0),
    ("蒙古", 42.0, 50.0, 95.0, 115.0, 0),
]


def _model_month(ncep_month: int) -> int:
    return (ncep_month + 10) % 12


def _load_model(branch: str) -> dict[str, np.ndarray]:
    """Decode the archived monthly fields + mesh geometry for earth."""
    import msgpack

    base = _ROOT / "data" / "worlds" / "earth"
    map_dir = base / (Path("branches") / branch if branch else Path()) / "maps" / "planet_earth"
    _mf = find_mesh_file(map_dir)
    assert _mf is not None, "no mesh file under {map_dir}"
    mesh = load_cvt_mesh(_mf)
    cells = mesh["cells"]
    lat = np.array([c["lat"] for c in cells], dtype=np.float64)
    lon = np.array([c["lon"] for c in cells], dtype=np.float64)
    elev = np.array([c["elevation"] for c in cells], dtype=np.float64)

    blob = msgpack.unpackb((map_dir / "climate_monthly.msgpack").read_bytes())
    n = blob["num_cells"]

    def _dec(name: str) -> np.ndarray:
        stem = name.split("_monthly")[0]
        q = np.frombuffer(blob[name], dtype="<i2").reshape(n, 12).astype(np.float64)
        return q * blob[f"{stem}_scale"] + blob[f"{stem}_offset"]

    return {
        "lat": lat,
        "lon": lon,
        "elev": elev,
        "t_monthly": _dec("t_monthly"),
        "dp": _dec("pressure_monthly"),
    }


def _load_ncep() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """NCEP SLP climatology → (slp [12, lat, lon] hPa, lat, lon)."""
    import xarray as xr

    ds = xr.open_dataset(_NCEP_SLP, decode_times=False)
    slp = np.asarray(ds["slp"].values, dtype=np.float64)  # millibars = hPa
    lat = np.asarray(ds["lat"].values, dtype=np.float64)
    lon = np.asarray(ds["lon"].values, dtype=np.float64)
    ds.close()
    return slp, lat, lon


def _ncep_full_contrast(
    slp: np.ndarray,
    nlat: np.ndarray,
    nlon: np.ndarray,
    box: tuple,
    ocean: np.ndarray,
) -> tuple[float, float, float]:
    """(box mean SLP at month m, full land-ocean contrast at m, annual mean of contrast)."""
    _, la0, la1, lo0, lo1, m = box
    lat_m = (nlat >= la0) & (nlat <= la1)
    lon_m = (nlon >= lo0) & (nlon <= lo1)
    sub = slp[:, lat_m][:, :, lon_m]  # (12, nla, nlo)
    land_m = sub.mean(axis=(1, 2))  # (12,) box land mean per month
    # Same-latitude ocean zonal mean (crude ocean mask: cells whose annual SLP
    # sits within 4 hPa of the latitude's median — excludes the large land
    # thermal extremes), averaged over the box's latitude band.
    oc = np.where(ocean[lat_m], slp[:, lat_m], np.nan)  # (12, nla, nlon)
    oc_zon = np.nanmean(oc, axis=2).mean(axis=1)  # (12,)
    contrast = land_m - oc_zon
    return float(land_m[m]), float(contrast[m]), float(contrast.mean())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--branch", default="climate-dev")
    args = parser.parse_args()

    mdl = _load_model(args.branch)
    lat, lon, elev = mdl["lat"], mdl["lon"], mdl["elev"]
    t_monthly, dp = mdl["t_monthly"], mdl["dp"]
    is_ocean = elev < 0.0

    # Engine-exact land-vs-ocean ΔT (B2 ocean reference), full value (B0b —
    # no annual-mean removal), and the monthly zonal reference temperature.
    t_zonal = zonal_mean_monthly(t_monthly, lat, mask=is_ocean)
    dt = t_monthly - t_zonal
    tbar_k = np.maximum(t_zonal + 273.15, 200.0)

    slp, nlat, nlon = _load_ncep()
    ann_slp = slp.mean(axis=0)
    ocean_ncep = np.abs(ann_slp - np.median(ann_slp, axis=1, keepdims=True)) < 4.0

    print(f"engine E (module constant) = {_MONSOON_PROJECTION_FRACTION:.4f}")
    print("=== Model ΔP vs NCEP full land-sea contrast (target 0.8–1.25 on dry/winter) ===")
    print(
        f"{'box':<12}{'mon':>4}{'ΔP_mod':>9}{'C_full':>9}{'ratio':>8}{'ΔT_full':>9}{'E_impl':>8}"
    )
    for box in _BOXES:
        name, la0, la1, lo0, lo1, m = box
        lon_c = np.where(lon < 0.0, lon + 360.0, lon)
        sel = (lat >= la0) & (lat <= la1) & (lon_c >= lo0) & (lon_c <= lo1) & ~is_ocean
        if sel.sum() == 0:
            print(f"{name:<12}  no land cells")
            continue
        mm = _model_month(m)
        _, c_full, c_ann = _ncep_full_contrast(slp, nlat, nlon, box, ocean_ncep)
        mdl_dp = float(dp[sel, mm].mean())
        dt_box = float(dt[sel, mm].mean())
        tb = float(tbar_k[sel, mm].mean())
        ratio = mdl_dp / c_full if abs(c_full) > 1e-9 else float("nan")
        # Implied projection factor from the obs contrast and the model's own
        # land-sea ΔT (anchor drift monitor for recalibration).
        e_impl = -c_full * tb / (1013.25 * dt_box) if abs(dt_box) > 1e-6 else float("nan")
        mon_name = "Jan" if m == 0 else "Jul"
        print(
            f"{name:<12}{mon_name:>4}{mdl_dp:>9.2f}{c_full:>9.2f}{ratio:>8.2f}"
            f"{dt_box:>9.1f}{e_impl:>8.3f}"
        )


if __name__ == "__main__":
    main()
