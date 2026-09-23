#!/usr/bin/env python3
"""Per-cell model-vs-observed bias audit (T / P / wind / Köppen).

Reads the built mesh file, the sampled per-cell observed
climatology (``climate_obs.json``, from ``generate_climate_obs.py`` — NCEP
T/SLP/wind + GPCP P at each cell), and the observed Köppen
(``koppen_obs.json``, from ``convert_koppen_map.py``), then ranks the dominant
residuals so the "big items" are visible at a glance:

  * global metrics per field (RMSE / bias / R²),
  * 10° zonal bands (land) — the latitudinal structure of each bias,
  * a region scorecard — the proposal §0 residual regions (ΔT / ΔP),
  * the top cells by |Δ| per field — spot-check outliers,
  * Köppen agreement rate + the top model→obs class mismatch pairs.

Δ = model − observed (positive = too warm / too wet / too strong).  This is the
systematic form of the cell-by-cell spatial-map discipline: it quantifies, per
region and per field, exactly which residuals are the "big items" worth fixing.

Wind convention: post root-unification (tech debt 24) the model's
``wind_east/north_m_s`` are the *physical* east/north components, directly
comparable to NCEP ``uwnd``/``vwnd`` — no sign mapping needed.

Pressure note: the engine archives only the monthly SLP *anomaly*
(``pressure_monthly``), never an absolute annual SLP (``slp_annual_hpa`` is
importer-only), so an annual ΔSLP is not defined for engine worlds.  The
month-resolved ΔP (model ΔP vs NCEP SLP seasonal anomaly) lives in
``diagnose_monsoon_dp_shape.py``.  ``slp_obs_hpa`` is carried in
``climate_obs.json`` for reference / the imported earth-main world.

Usage::

    uv run python scripts/climate/diagnose_climate_bias.py \
        data/worlds/earth/branches/climate-dev/maps/planet_earth
"""

from __future__ import annotations

import argparse
import gzip
import json
from collections import Counter
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Region scorecard.  lon is degrees East (negative = West).  ``elev_min`` is
# an optional elevation floor (metres) so mountain boxes exclude the lowland.
# ---------------------------------------------------------------------------
TEMP_REGIONS: list[dict] = [
    dict(name="青藏高原", lat=(28, 40), lon=(75, 105), elev_min=3000),
    dict(name="华南", lat=(20, 30), lon=(105, 122)),
    dict(name="高加索", lat=(40, 45), lon=(40, 48), elev_min=1000),
    dict(name="天山", lat=(40, 45), lon=(75, 90), elev_min=1500),
    dict(name="落基山脉", lat=(35, 50), lon=(-115, -105), elev_min=1500),
    dict(name="西欧", lat=(45, 55), lon=(-5, 15)),
    dict(name="东欧/西伯利亚", lat=(50, 60), lon=(40, 90)),
    dict(name="蒙古", lat=(42, 50), lon=(90, 110)),
    dict(name="哈得孙湾沿岸", lat=(50, 60), lon=(-95, -75)),
    dict(name="安第斯山麓", lat=(-30, -18), lon=(-73, -67)),
    dict(name="南极", lat=(-90, -65), lon=(-180, 180)),
]

PRECIP_REGIONS: list[dict] = [
    dict(name="刚果盆地", lat=(-5, 5), lon=(15, 30)),
    dict(name="赤道安第斯西岸", lat=(-5, 5), lon=(-80, -72)),
    dict(name="非洲之角/索马里", lat=(0, 12), lon=(40, 50)),
    dict(name="爪哇", lat=(-10, -5), lon=(105, 115)),
    dict(name="孟加拉", lat=(20, 25), lon=(88, 92)),
    dict(name="阿拉斯加海岸", lat=(55, 62), lon=(-150, -130)),
    # C→B 最大错配流三区（2026-09-13 审计，季风幅度攻关验收框）
    dict(name="恒河流域", lat=(20, 30), lon=(77, 92)),
    dict(name="华南", lat=(20, 30), lon=(105, 122)),
    dict(name="美国东南", lat=(25, 35), lon=(-90, -75)),
]


def _load_mesh(map_dir: Path) -> dict[str, np.ndarray]:
    from dreamulator.map.export import find_mesh_file, load_cvt_mesh

    mesh_path = find_mesh_file(map_dir)
    if mesh_path is None:
        raise FileNotFoundError(f"no mesh file under {map_dir}")
    mesh = load_cvt_mesh(mesh_path)
    cells = mesh["cells"]

    def _f(key: str) -> np.ndarray:
        # None → NaN, but keep legitimate 0.0 (a falsy wind component is real).
        return np.array([np.nan if c.get(key) is None else c[key] for c in cells], dtype=np.float64)

    return {
        "lat": np.array([c["lat"] for c in cells]),
        "lon": np.array([c["lon"] for c in cells]),
        "elev": np.array([c["elevation"] for c in cells]),
        "t_mod": _f("temperature_C"),
        "p_mod": _f("precipitation_mm"),
        "ue_mod": _f("wind_east_m_s"),
        "vn_mod": _f("wind_north_m_s"),
        "koppen_mod": np.array([c.get("koppen_class") or "" for c in cells], dtype=object),
        "water": np.array([c["water_class"] for c in cells], dtype=str),
        "id": np.arange(len(cells)),
    }


def _load_obs(map_dir: Path, n: int) -> dict[str, np.ndarray]:
    """Scatter the per-cell obs (keyed by cell id) into positional arrays."""
    out: dict[str, np.ndarray] = {}
    obs_path = map_dir / "climate_obs.json"
    with open(obs_path, encoding="utf-8") as f:
        obs = json.load(f)
    fields = ("t_obs_c", "p_obs_mm", "slp_obs_hpa", "uwnd_obs_m_s", "vwnd_obs_m_s")
    arrs = {f: np.full(n, np.nan) for f in fields}
    for cid, v in obs["cells"].items():
        i = int(cid)
        for f in fields:
            if f in v:
                arrs[f][i] = v[f]
    out.update(arrs)
    # Köppen obs (separate mesh-bound file).
    kop_path = map_dir / "koppen_obs.json"
    kop = np.full(n, "", dtype=object)
    if kop_path.exists():
        with open(kop_path, encoding="utf-8") as f:
            kobs = json.load(f)
        for cid, cls in kobs["cells"].items():
            kop[int(cid)] = cls
    out["koppen_obs"] = kop
    out["_has_koppen"] = np.array(kop_path.exists())
    return out


def _region_mask(d: dict[str, np.ndarray], r: dict) -> np.ndarray:
    m = (d["lat"] >= r["lat"][0]) & (d["lat"] <= r["lat"][1])
    m &= (d["lon"] >= r["lon"][0]) & (d["lon"] <= r["lon"][1])
    if "elev_min" in r:
        m &= d["elev"] >= r["elev_min"]
    return m


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("map_dir", help="path to maps/<planet_id>/")
    args = parser.parse_args()
    map_dir = Path(args.map_dir)

    d = _load_mesh(map_dir)
    n = len(d["lat"])
    o = _load_obs(map_dir, n)
    t_obs, p_obs = o["t_obs_c"], o["p_obs_mm"]

    land = (d["water"] == "land") & np.isfinite(t_obs) & np.isfinite(p_obs)
    dt = d["t_mod"] - t_obs
    dp = d["p_mod"] - p_obs

    def _metrics(dx: np.ndarray, mod: np.ndarray, obs: np.ndarray, m: np.ndarray) -> str:
        rmse = float(np.sqrt(np.mean(dx[m] ** 2)))
        bias = float(np.mean(dx[m]))
        r2 = float(1 - np.sum((mod[m] - obs[m]) ** 2) / np.sum((obs[m] - obs[m].mean()) ** 2))
        return f"RMSE {rmse:6.2f}   bias {bias:+6.2f}   R² {r2:+.3f}"

    print(f"cells={n}  land(with obs)={int(land.sum())}\n")
    print("== global (land) ==")
    print(f"  T  [°C]  : {_metrics(dt, d['t_mod'], t_obs, land)}")
    print(f"  P  [mm]  : {_metrics(dp, d['p_mod'], p_obs, land)}")

    # ---- wind (physical east/north; model annual = vector mean, B0a) -------
    has_wind = (
        np.isfinite(o["uwnd_obs_m_s"])
        & np.isfinite(o["vwnd_obs_m_s"])
        & np.isfinite(d["ue_mod"])
        & np.isfinite(d["vn_mod"])
    )
    wmask = land & has_wind
    if wmask.any():
        du = d["ue_mod"] - o["uwnd_obs_m_s"]
        dv = d["vn_mod"] - o["vwnd_obs_m_s"]
        sp_mod = np.hypot(d["ue_mod"], d["vn_mod"])
        sp_obs = np.hypot(o["uwnd_obs_m_s"], o["vwnd_obs_m_s"])
        dsp = sp_mod - sp_obs
        print(f"  |wind| [m/s]: {_metrics(dsp, sp_mod, sp_obs, wmask)}")
        print(
            f"  u/v bias [m/s]: Δu {np.mean(du[wmask]):+.2f}  Δv {np.mean(dv[wmask]):+.2f}"
            f"   (mod |U| {np.mean(sp_mod[wmask]):.2f} vs obs {np.mean(sp_obs[wmask]):.2f})"
        )
    print()

    # ---- zonal bands (10°) ------------------------------------------------
    print("== zonal bands (land) ==")
    hdr = f"{'band':>9} {'ΔT':>6} {'ΔP':>7}"
    if wmask.any():
        hdr += f" {'Δ|U|':>6}"
    print(hdr)
    for lo in range(-90, 90, 10):
        m = land & (d["lat"] >= lo) & (d["lat"] < lo + 10)
        if m.sum() == 0:
            continue
        line = f"{lo:>5}..{lo + 9:<3} {np.mean(dt[m]):>+6.1f} {np.mean(dp[m]):>+7.0f}"
        if wmask.any():
            mw = m & wmask
            line += f" {np.mean(dsp[mw]):>+6.2f}" if mw.any() else f" {'—':>6}"
        print(line)

    # ---- region scorecard (T / P) -----------------------------------------
    def _region_table(
        regions: list[dict], dx: np.ndarray, mod: np.ndarray, obs: np.ndarray, unit: str
    ):
        print(f"\n== region scorecard — Δ{unit} = model − observed ==")
        print(f"{'region':<16} {'n':>6} {'mod':>8} {'obs':>8} {'Δ':>8}")
        print("-" * 48)
        for r in regions:
            m = land & _region_mask(d, r)
            if m.sum() == 0:
                continue
            print(
                f"{r['name']:<16} {int(m.sum()):>6} {np.mean(mod[m]):>8.1f} "
                f"{np.mean(obs[m]):>8.1f} {np.mean(dx[m]):>+8.1f}"
            )

    _region_table(TEMP_REGIONS, dt, d["t_mod"], t_obs, "T")
    _region_table(PRECIP_REGIONS, dp, d["p_mod"], p_obs, "P")

    # ---- Köppen agreement --------------------------------------------------
    if bool(o["_has_koppen"]):
        ko = o["koppen_obs"]
        km = d["koppen_mod"]
        both = land & (ko != "") & (ko != "N/A") & (km != "")
        if both.any():
            agree = km[both] == ko[both]
            print("\n== Köppen agreement (land, obs valid) ==")
            print(f"  n={int(both.sum())}  agree={float(agree.mean()) * 100:.1f}%")
            mism = Counter(f"{km[i]}→{ko[i]}" for i in np.where(both)[0] if km[i] != ko[i])
            print("  top model→obs mismatches:")
            for pair, cnt in mism.most_common(12):
                print(f"    {pair:<12} {cnt:>6}")
            # zonal agreement
            print(f"  {'band':>9} {'agree%':>7}")
            for lo in range(-90, 90, 15):
                m = both & (d["lat"] >= lo) & (d["lat"] < lo + 15)
                if m.sum() == 0:
                    continue
                print(f"  {lo:>5}..{lo + 14:<3} {float((km[m] == ko[m]).mean()) * 100:>7.1f}")

    # ---- top outliers -------------------------------------------------------
    def _top(
        dx: np.ndarray, mod: np.ndarray, obs: np.ndarray, m0: np.ndarray, unit: str, k: int = 15
    ):
        print(f"\n== top-{k} |Δ{unit}| cells (land) ==")
        idx = np.where(m0)[0]
        order = idx[np.argsort(-np.abs(dx[idx]))][:k]
        print(f"{'lat':>6} {'lon':>7} {'elev':>6} {'mod':>8} {'obs':>8} {'Δ':>8}")
        for i in order:
            print(
                f"{d['lat'][i]:>6.1f} {d['lon'][i]:>7.1f} {d['elev'][i]:>6.0f} "
                f"{mod[i]:>8.1f} {obs[i]:>8.1f} {dx[i]:>+8.1f}"
            )

    _top(dt, d["t_mod"], t_obs, land, "T")
    _top(dp, d["p_mod"], p_obs, land, "P")
    if wmask.any():
        _top(dsp, sp_mod, sp_obs, wmask, "|U|")


if __name__ == "__main__":
    main()
