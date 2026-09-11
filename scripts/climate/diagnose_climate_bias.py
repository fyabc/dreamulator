#!/usr/bin/env python3
"""Per-cell model-vs-observed bias audit (temperature + precipitation).

Reads the built mesh (``cvt_mesh.json``) and the sampled per-cell observed
climatology (``climate_obs.json``, produced alongside the mesh — NCEP surface
air temperature and GPCP precipitation sampled at each cell), then ranks the
dominant residuals three ways so the "big items" are visible at a glance:

  * global T/P metrics (RMSE / bias / R²),
  * 10° zonal bands (land only) — the latitudinal structure of the bias,
  * a region scorecard — the proposal §0 residual regions, each with ΔT/ΔP,
  * the top-20 cells by |ΔT| and |ΔP| — spot-check outliers.

ΔT = model − observed (positive = too warm / too wet).  This is the systematic
form of the cell-by-cell spatial-map discipline: it quantifies, per region,
exactly which residuals are the "big items" worth fixing next.

Usage::

    uv run python scripts/climate/diagnose_climate_bias.py \
        data/worlds/earth/branches/climate-dev/maps/planet_earth
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
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
]


def _load_mesh(map_dir: Path) -> dict[str, np.ndarray]:
    mesh = json.load(gzip.open(map_dir / "cvt_mesh.json", "rb"))
    cells = mesh["cells"]
    return {
        "lat": np.array([c["lat"] for c in cells]),
        "lon": np.array([c["lon"] for c in cells]),
        "elev": np.array([c["elevation"] for c in cells]),
        "t_mod": np.array([c["temperature_C"] for c in cells], dtype=np.float64),
        "p_mod": np.array([c["precipitation_mm"] for c in cells], dtype=np.float64),
        "water": np.array([c["water_class"] for c in cells], dtype=str),
        "id": np.arange(len(cells)),
    }


def _load_obs(map_dir: Path, n: int) -> tuple[np.ndarray, np.ndarray]:
    obs = json.load(open(map_dir / "climate_obs.json", encoding="utf-8"))
    t_obs = np.full(n, np.nan)
    p_obs = np.full(n, np.nan)
    for cid, v in obs["cells"].items():
        i = int(cid)
        t_obs[i] = v["t_obs_c"]
        p_obs[i] = v["p_obs_mm"]
    return t_obs, p_obs


def _region_mask(d: dict[str, np.ndarray], r: dict) -> np.ndarray:
    m = (
        (d["lat"] >= r["lat"][0]) & (d["lat"] <= r["lat"][1])
        & (d["lon"] >= r["lon"][0]) & (d["lon"] <= r["lon"][1])
    )
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
    t_obs, p_obs = _load_obs(map_dir, n)

    land = (d["water"] == "land") & np.isfinite(t_obs) & np.isfinite(p_obs)
    dt = d["t_mod"] - t_obs
    dp = d["p_mod"] - p_obs

    def _rmse(x: np.ndarray) -> float:
        return float(np.sqrt(np.mean(x[land] ** 2)))

    def _r2(x: np.ndarray, y: np.ndarray) -> float:
        m = land
        return float(1 - np.sum((x[m] - y[m]) ** 2) / np.sum((y[m] - y[m].mean()) ** 2))

    print(f"cells={n}  land(with obs)={int(land.sum())}\n")
    print("== global (land) ==")
    print(f"  T: RMSE {_rmse(dt):5.2f} °C   bias {np.mean(dt[land]):+5.2f} °C   R² {_r2(d['t_mod'], t_obs):.3f}")
    print(f"  P: RMSE {_rmse(dp):6.0f} mm   bias {np.mean(dp[land]):+6.0f} mm   R² {_r2(d['p_mod'], p_obs):.3f}\n")

    # ---- zonal bands (10°) ------------------------------------------------
    print("== zonal bands (land) ==")
    print(f"{'band':>8} {'ΔT':>6} {'ΔP':>7}")
    for lo in range(-90, 90, 10):
        m = land & (d["lat"] >= lo) & (d["lat"] < lo + 10)
        if m.sum() == 0:
            continue
        print(f"{lo:>5}..{lo+9:<3} {np.mean(dt[m]):>+6.1f} {np.mean(dp[m]):>+7.0f}")

    # ---- region scorecard --------------------------------------------------
    def _region_table(regions, dx, unit):
        print(f"\n== region scorecard — Δ{unit} = model − observed ==")
        print(f"{'region':<16} {'n':>6} {'mod':>7} {'obs':>7} {'Δ':>8}")
        print("-" * 46)
        for r in regions:
            m = land & _region_mask(d, r)
            if m.sum() == 0:
                continue
            f = d["t_mod"] if unit == "T" else d["p_mod"]
            o = t_obs if unit == "T" else p_obs
            print(f"{r['name']:<16} {int(m.sum()):>6} {np.mean(f[m]):>7.1f} "
                  f"{np.mean(o[m]):>7.1f} {np.mean(dx[m]):>+8.1f}")

    _region_table(TEMP_REGIONS, dt, "T")
    _region_table(PRECIP_REGIONS, dp, "P")

    # ---- top outliers -------------------------------------------------------
    def _top(dx, unit, k=15):
        print(f"\n== top-{k} |Δ{unit}| cells (land) ==")
        idx = np.where(land)[0]
        order = idx[np.argsort(-np.abs(dx[idx]))][:k]
        print(f"{'lat':>6} {'lon':>7} {'elev':>6} {'mod':>7} {'obs':>7} {'Δ':>8}")
        for i in order:
            f = d["t_mod"] if unit == "T" else d["p_mod"]
            o = t_obs if unit == "T" else p_obs
            print(f"{d['lat'][i]:>6.1f} {d['lon'][i]:>7.1f} {d['elev'][i]:>6.0f} "
                  f"{f[i]:>7.1f} {o[i]:>7.1f} {dx[i]:>+8.1f}")

    _top(dt, "T")
    _top(dp, "P")


if __name__ == "__main__":
    main()
