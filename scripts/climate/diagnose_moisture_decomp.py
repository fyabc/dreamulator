"""δMCD/δTH moisture-budget decomposition — Ganges/South-China P deficit (D/F line).

Runs *offline* on the archived earth build + NCEP/GPCP climatology (no rebuild).
Question (climate-layer-improvement §5 "D/F 设计输入" #2): is the engine's
monsoon-land precipitation deficit a *dynamic* error (the wind does not
deliver/converge the moisture) or a *thermodynamic* one (the humidity field
is too dry)?  The answer rules whether the D/F fix belongs on the wind side
(ΔP depth / moisture routing) or the humidity side (q generation), and how
much a shallower M4 ΔP actually costs.

Method — the Seager et al. 2014 (J. Climate 27:7921) dynamic/thermodynamic
split applied to the single-level column flux Q = v·W (surface wind ×
precipitable water; the engine's own moisture budget transports column water
with the boundary-layer wind, so this is its native representation):

    P − E ≈ −∇·Q + transients,      Q = (u, v)·W

Model-minus-obs flux difference, split exactly (no residual):

    Q_m − Q_o = v_m·δW + δv·W_o,    δW = W_m − W_o,  δv = v_m − v_o
    δDY = −∇·(δv·W_o)     dynamic share   (wind field wrong)
    δTH = −∇·(v_m·δW)     thermodynamic   (humidity field wrong)

Caveats, stated up front:
* Model W is *slaved* to model P (W = P·τ, τ = 9 d residence — the engine's
  own steady-state definition), so δTH is not an independent error source;
  it measures how much of the convergence deficit the W deficit explains
  *given* the winds.  Causally W itself is set upstream by wind delivery —
  read δDY/δTH as mechanism shares, not root-cause shares.
* Monthly means cannot separate transient eddy flux ⟨v′q′⟩; it lands in the
  obs residual (P − E + ∇·Q).  Over monsoon regions the mean flow dominates
  transport, so the split still answers the routing question.
* NCEP sig995 wind (~50 m above surface) is the project's wind-validation
  reference; pr_wtr is NCEP's column water (wet-biased vs ERA5 by ~10 %,
  shared by both sides of the split's W_o term — biases mostly cancel in
  the comparison).

Usage:
    uv run python scripts/climate/diagnose_moisture_decomp.py
    uv run python scripts/climate/diagnose_moisture_decomp.py --branch climate-dev
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from dreamulator.map.export import find_mesh_file, load_cvt_mesh  # noqa: E402

_ROOT = Path(__file__).resolve().parents[2]
_CLIM = _ROOT / "private" / "tmp" / "climatology"
_EARTH = _ROOT / "data" / "worlds" / "earth"

# Model column-water residence time (climate_simulator
# _MOISTURE_RESIDENCE_DAYS): W [mm] = p_monthly [mm/mo] · 12·τ/365.25.
_W_FROM_P = 12.0 * 9.0 / 365.25

_A_EARTH_KM = 6371.0

# Boxes: (name, lat_lo, lat_hi, lon_lo, lon_hi) + the months to report
# (model convention, 0 = March: 4 = July, 10 = January).
_BOXES = [
    ("Ganges", 20.0, 30.0, 80.0, 95.0, [4]),
    ("SChina", 20.0, 30.0, 105.0, 120.0, [4]),
    ("Meghalaya", 23.0, 28.0, 90.0, 97.0, [4]),
    ("Guinea", 4.0, 12.0, 350.0, 360.0, [4]),
    ("Somali", -5.0, 8.0, 40.0, 55.0, [4]),
    ("Sahara", 18.0, 30.0, 5.0, 30.0, [4]),
    ("Siberia", 55.0, 65.0, 80.0, 110.0, [10]),
]


def _ncep_month(model_month: int) -> int:
    return (model_month + 2) % 12  # model 0 = March; NCEP 0 = January


def _load_ncep() -> dict[str, np.ndarray]:
    import xarray as xr

    def _open(name: str, var: str, level: float | None = None) -> np.ndarray:
        ds = xr.open_dataset(_CLIM / name, decode_times=False)
        data = ds[var]
        if level is not None:
            lev = np.asarray(ds["level"].values, dtype=np.float64)
            data = data.sel(level=lev[np.abs(lev - level).argmin()])
        data = np.asarray(data.values, dtype=np.float64)
        lat = np.asarray(ds["lat"].values, dtype=np.float64)
        lon = np.asarray(ds["lon"].values, dtype=np.float64)
        ds.close()
        return data, lat, lon

    u, lat, lon = _open("ncep_uwnd.mon.ltm.nc", "uwnd")
    v, _, _ = _open("ncep_vwnd.mon.ltm.nc", "vwnd")
    w, _, _ = _open("ncep_prwtr.mon.ltm.nc", "pr_wtr")
    # 850-hPa winds (LLJ level): quantify how much of the moisture-transporting
    # flux sits above the surface layer the engine's budget advects with.
    try:
        u850, _, _ = _open("ncep_uwnd_p.mon.ltm.nc", "uwnd", level=850.0)
        v850, _, _ = _open("ncep_vwnd_p.mon.ltm.nc", "vwnd", level=850.0)
    except FileNotFoundError:
        u850 = v850 = None
    if u850 is not None:
        u850 = np.where(np.abs(u850) > 200, np.nan, u850)
        v850 = np.where(np.abs(v850) > 200, np.nan, v850)

    # GPCP monthly climatology (2.5°, slightly shifted lat centres) → NCEP
    # calendar month, interpolated onto the NCEP lat centres.
    ds = xr.open_dataset(_CLIM / "gpcp_precip.mon.mean.nc", decode_times=False)
    ref = np.datetime64("1800-01-01")
    dates = ref + np.asarray(ds["time"].values, dtype="timedelta64[D]")
    months = dates.astype("datetime64[M]").astype(int) % 12 + 1  # Jan=1 … Dec=12
    gpcp_m = np.asarray(ds["precip"].values, dtype=np.float64)  # (T, 72, 144)
    g_lat = np.asarray(ds["lat"].values, dtype=np.float64)
    ds.close()
    clim = np.stack([gpcp_m[months == m + 1].mean(axis=0) for m in range(12)])

    # GPCP grid (centres at 1.25+2.5k) → NCEP grid (0+2.5k): bilinear along
    # lon (with periodic wrap) then lat.
    g_lon = np.asarray(
        xr.open_dataset(_CLIM / "gpcp_precip.mon.mean.nc", decode_times=False)["lon"].values,
        dtype=np.float64,
    )
    clim_lon = np.stack(
        [
            np.stack(
                [
                    np.interp(
                        lon,
                        np.concatenate([g_lon - 360.0, g_lon, g_lon + 360.0]),
                        np.concatenate([row, row, row]),
                    )
                    for row in clim[m]
                ]
            )
            for m in range(12)
        ]
    )
    # NCEP lat runs 90→−90 (descending); np.interp only needs the *source*
    # axis (g_lat, ascending −88.75→88.75) increasing — the target order
    # follows lat as stored.
    clim_on_ncep = np.stack(
        [
            np.stack(
                [np.interp(lat, g_lat, col, left=np.nan, right=np.nan) for col in clim_lon[m].T]
            ).T
            for m in range(12)
        ]
    )

    return {
        "u": u,
        "v": v,
        "w": w,
        "u850": u850,
        "v850": v850,
        "p": clim_on_ncep,  # (12, lat, lon) mm/day, NCEP calendar
        "lat": lat,
        "lon": lon,
    }


def _div_flux(qu: np.ndarray, qv: np.ndarray, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """−∇·Q on a regular lat-lon grid → mm/day (kg/m²/s × 86400)."""
    a = _A_EARTH_KM * 1000.0
    phi = np.radians(lat)
    cos_phi = np.cos(phi)
    # Zonal derivative with periodic wrap.
    dlon = np.radians(np.abs(np.diff(lon)[0]))
    dqu_dlambda = (np.roll(qu, -1, axis=-1) - np.roll(qu, 1, axis=-1)) / (2.0 * dlon)
    # Meridional: ∂(Qv cosφ)/∂φ / (a cosφ).
    qv_cos = qv * cos_phi[:, None]
    dphi = np.radians(np.abs(np.diff(lat)[0]))
    dqvcos_dphi = np.gradient(qv_cos, dphi, axis=1)
    div = (dqu_dlambda / cos_phi[:, None] + dqvcos_dphi / cos_phi[:, None]) / a
    return -div * 86400.0


def _load_model(branch: str) -> dict[str, np.ndarray]:
    import msgpack

    map_dir = _EARTH / (Path("branches") / branch if branch else Path()) / "maps" / "planet_earth"
    _mf = find_mesh_file(map_dir)
    assert _mf is not None, f"no mesh file under {map_dir}"
    mesh = load_cvt_mesh(_mf)
    cells = mesh["cells"]
    n = len(cells)
    lat = np.array([c["lat"] for c in cells], dtype=np.float64)
    lon = np.array([c["lon"] for c in cells], dtype=np.float64)
    elev = np.array([c["elevation"] for c in cells], dtype=np.float64)

    blob = msgpack.unpackb((map_dir / "climate_monthly.msgpack").read_bytes())

    def _dec(name: str) -> np.ndarray:
        stem = name.split("_monthly")[0]
        q = np.frombuffer(blob[name], dtype="<i2").reshape(n, 12).astype(np.float64)
        return q * blob[f"{stem}_scale"] + blob[f"{stem}_offset"]

    return {
        "lat": lat,
        "lon": lon,
        "elev": elev,
        "p_monthly": _dec("p_monthly"),
        "u_monthly": _dec("wind_east_monthly"),
        "v_monthly": _dec("wind_north_monthly"),
    }


def _nearest_grid(
    g_lat: np.ndarray, g_lon: np.ndarray, m_lat: np.ndarray, m_lon: np.ndarray
) -> np.ndarray:
    """For each NCEP grid point, the index of the nearest mesh cell."""
    from scipy.spatial import cKDTree

    gridded = np.stack(np.meshgrid(g_lon, g_lat, indexing="ij"), axis=-1)  # (nlon, nlat, 2)
    pts = gridded.reshape(-1, 2)
    # Unit vectors in degrees → xyz for true great-circle nearest.
    lam = np.radians(pts[:, 0])
    phi = np.radians(pts[:, 1])
    g_xyz = np.stack([np.cos(phi) * np.cos(lam), np.cos(phi) * np.sin(lam), np.sin(phi)], axis=1)
    lam_m = np.radians(m_lon)
    phi_m = np.radians(m_lat)
    m_xyz = np.stack(
        [np.cos(phi_m) * np.cos(lam_m), np.cos(phi_m) * np.sin(lam_m), np.sin(phi_m)], axis=1
    )
    _, idx = cKDTree(m_xyz).query(g_xyz, workers=-1)
    return idx.reshape(len(g_lon), len(g_lat)).T  # (nlat, nlon)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--branch", default="climate-dev")
    args = parser.parse_args()

    obs = _load_ncep()
    mdl = _load_model(args.branch)
    o_lat, o_lon = obs["lat"], obs["lon"]

    # Model fields → NCEP grid (nearest mesh cell), NCEP calendar month axis.
    idx = _nearest_grid(o_lat, o_lon, mdl["lat"], mdl["lon"])
    land_grid = mdl["elev"][idx] >= 0.0

    def _to_grid(field: np.ndarray, m_month: int) -> np.ndarray:
        return field[idx, m_month]  # field is already in model calendar

    # (nlat, nlon) per selected month handled per box below.
    w_obs = obs["w"]  # (12, nlat, nlon)

    print(
        f"{'box':10s} {'mon':>4s} {'P_obs':>7s} {'P_mod':>7s} {'C_obs':>7s} {'C850':>7s} "
        f"{'C_mod':>7s} {'δDY':>7s} {'δTH':>7s} {'resid':>7s}   |Q|o995/o850/mod"
    )
    for name, la0, la1, lo0, lo1, months in _BOXES:
        for mm in months:
            nm = _ncep_month(mm)
            sel = (
                (o_lat[:, None] >= la0)
                & (o_lat[:, None] <= la1)
                & (o_lon[None, :] >= lo0)
                & (o_lon[None, :] <= lo1)
                & land_grid
            )
            if lo0 < 0:
                sel = (
                    (o_lat[:, None] >= la0)
                    & (o_lat[:, None] <= la1)
                    & ((o_lon[None, :] >= lo0 + 360) | (o_lon[None, :] <= lo1))
                    & land_grid
                )
            if not sel.any():
                print(f"{name:10s} — no land grid points")
                continue

            u_o, v_o = obs["u"][nm], obs["v"][nm]
            w_o = w_obs[nm]
            u_m = _to_grid(mdl["u_monthly"], mm)
            v_m = _to_grid(mdl["v_monthly"], mm)
            p_m = _to_grid(mdl["p_monthly"], mm) / 30.4375  # mm/mo → mm/day
            w_m = _to_grid(mdl["p_monthly"], mm) * _W_FROM_P

            c_obs = _div_flux(u_o * w_o, v_o * w_o, o_lat, o_lon)[sel].mean()
            c_mod = _div_flux(u_m * w_m, v_m * w_m, o_lat, o_lon)[sel].mean()
            d_dy = _div_flux((u_m - u_o) * w_o, (v_m - v_o) * w_o, o_lat, o_lon)[sel].mean()
            d_th = _div_flux(u_m * (w_m - w_o), v_m * (w_m - w_o), o_lat, o_lon)[sel].mean()

            # 850-hPa convergence (LLJ level) + flux magnitudes: the transport
            # supply per level. |Q| = mean |v·W| over the box.
            if obs["u850"] is not None:
                u8, v8 = obs["u850"][nm], obs["v850"][nm]
                c850 = _div_flux(np.nan_to_num(u8) * w_o, np.nan_to_num(v8) * w_o, o_lat, o_lon)[
                    sel
                ].mean()
                q8 = float(
                    np.hypot(
                        np.nan_to_num(u8[sel]) * w_o[sel], np.nan_to_num(v8[sel]) * w_o[sel]
                    ).mean()
                )
            else:
                c850 = float("nan")
                q8 = float("nan")
            q995 = float(np.hypot(u_o[sel] * w_o[sel], v_o[sel] * w_o[sel]).mean())
            qmod = float(np.hypot(u_m[sel] * w_m[sel], v_m[sel] * w_m[sel]).mean())

            p_obs = obs["p"][nm][sel].mean()
            p_mod = p_m[sel].mean()
            resid = p_obs - c_obs  # ≈ E + transients + level/orographic proxy gap

            mon_name = [
                "Jan",
                "Feb",
                "Mar",
                "Apr",
                "May",
                "Jun",
                "Jul",
                "Aug",
                "Sep",
                "Oct",
                "Nov",
                "Dec",
            ][nm]
            print(
                f"{name:10s} {mon_name:>4s} {p_obs:7.2f} {p_mod:7.2f} {c_obs:7.2f} "
                f"{c850:7.2f} {c_mod:7.2f} {d_dy:7.2f} {d_th:7.2f} {resid:7.2f}   "
                f"{q995:5.0f}/{q8:5.0f}/{qmod:5.0f} kg m⁻¹s⁻¹"
            )


if __name__ == "__main__":
    main()
