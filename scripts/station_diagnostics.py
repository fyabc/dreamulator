"""Station diagnostics — model vs observed monthly climate at reference stations.

Reads the model's monthly temperature / precipitation / wind from a world's map
directory (``cvt_mesh.json`` + ``climate_monthly.msgpack``) and samples them at a
set of reference stations, then prints a per-station comparison against observed
monthly climatology.

This complements the spatial metrics (Cohen's Kappa / accuracy): it checks the
*seasonal behaviour at specific locations* — annual mean, seasonal amplitude,
monsoon wind direction, wet/dry season — which a spatial classification metric
cannot see.  It is the concrete form of the "东亚季风强度 / 地中海冬雨 / 亚马逊
水分路由" acceptance anchors.

Observed climatology (monthly temperature °C and precipitation mm) is HARDCODED
below as standard 1961–1990 / 1991–2020 normals from WMO and national
meteorological services (Beijing/Shanghai/Guangzhou/Chengdu/Harbin/Urumqi: CMA;
Delhi/Mumbai/Dhaka: IMD; the rest: WMO 1961–1990), rounded to ~0.5 °C / ~5 mm.
Wind is the dominant surface direction for July and January (qualitative).
TODO: replace with a packaged monthly-normals file (ERA5 or CRU) for more stations
and quantitative wind.

Station selection follows the GCOS Surface Network (GSN) idea — even spatial
distribution, representativeness across environments — but stratified here by
Köppen type so *every* climate type is sampled (a model could nail the tropics
while failing the deserts or the subarctic; Cohen's Kappa would not tell you
which).  Roughly one to three stations per type, biased toward the monsoon
regions that are the current acceptance anchors.

The model's month 0 is March (vernal equinox); observed normals are Jan–Dec, so
the script aligns them explicitly.  Sampling is nearest-cell on the CVT mesh
(~50–100 km), so a "station" maps to a ~1-cell area — resolution caveat.

Usage:
    uv run python scripts/station_diagnostics.py \
        private/worlds/earth/branches/climate-dev/maps/planet_earth
"""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

import msgpack
import numpy as np

# ---------------------------------------------------------------------------
# Reference stations, stratified by Köppen type.  `t` and `p` are Jan–Dec
# (12 values), °C / mm.  `wind_jul` / `wind_jan` are the dominant surface wind
# direction (qualitative).  `koppen` is the climate type (for grouping only).
# ---------------------------------------------------------------------------
STATIONS: list[dict] = [
    # A — tropical
    dict(name="Manaus", koppen="Af", lat=-3.1, lon=-60.0,
         t=[26.1, 26.0, 26.1, 26.3, 26.4, 26.4, 26.5, 27.0, 27.5, 27.6, 27.3, 26.7],
         p=[264, 290, 313, 287, 216, 114, 89, 67, 80, 124, 176, 224],
         wind_jul="E", wind_jan="E"),
    dict(name="Singapore", koppen="Af", lat=1.3, lon=103.8,
         t=[26.5, 27.0, 27.5, 27.9, 28.2, 28.0, 27.8, 27.7, 27.6, 27.4, 27.0, 26.5],
         p=[198, 154, 171, 154, 164, 131, 146, 151, 156, 169, 252, 269],
         wind_jul="S", wind_jan="N"),
    dict(name="Lagos", koppen="Am", lat=6.5, lon=3.4,
         t=[27.3, 28.5, 28.8, 28.5, 27.5, 26.2, 25.2, 25.0, 25.6, 26.4, 27.4, 27.3],
         p=[13, 42, 77, 140, 200, 312, 257, 112, 167, 210, 70, 20],
         wind_jul="SW", wind_jan="NE"),
    dict(name="Miami", koppen="Am", lat=25.8, lon=-80.2,
         t=[20.1, 21.2, 22.6, 24.8, 26.6, 28.0, 28.9, 28.9, 28.3, 26.4, 23.8, 21.3],
         p=[46, 53, 63, 78, 137, 245, 165, 201, 218, 172, 83, 52],
         wind_jul="SE", wind_jan="E"),
    dict(name="Bangkok", koppen="Aw", lat=13.8, lon=100.5,
         t=[26.7, 28.0, 29.5, 30.5, 30.0, 29.4, 28.8, 28.6, 28.3, 28.3, 27.8, 26.5],
         p=[9, 30, 29, 65, 220, 149, 155, 197, 344, 242, 48, 10],
         wind_jul="SW", wind_jan="NE"),
    dict(name="Darwin", koppen="Aw", lat=-12.5, lon=130.8,
         t=[28.5, 28.3, 28.4, 27.8, 26.3, 25.0, 24.8, 25.8, 27.4, 28.6, 29.0, 28.9],
         p=[393, 330, 260, 100, 20, 2, 1, 5, 15, 70, 140, 245],
         wind_jul="SE", wind_jan="W"),
    # B — arid
    dict(name="Cairo", koppen="BWh", lat=30.0, lon=31.2,
         t=[14.0, 15.0, 17.6, 21.5, 25.5, 28.0, 29.0, 29.5, 28.0, 24.5, 20.0, 15.5],
         p=[5, 4, 4, 1, 0, 0, 0, 0, 0, 1, 3, 6],
         wind_jul="N", wind_jan="SW"),
    dict(name="Riyadh", koppen="BWh", lat=24.7, lon=46.7,
         t=[14.4, 16.9, 21.1, 26.9, 32.9, 35.4, 36.7, 36.5, 33.2, 28.0, 21.4, 16.1],
         p=[12, 8, 25, 28, 5, 0, 0, 0, 0, 2, 11, 14],
         wind_jul="N", wind_jan="S"),
    dict(name="Dakar", koppen="BSh", lat=14.7, lon=-17.4,
         t=[22.0, 21.8, 22.3, 22.8, 24.0, 26.0, 27.4, 27.6, 27.6, 27.5, 26.0, 23.5],
         p=[1, 1, 0, 0, 0, 9, 68, 147, 138, 37, 3, 1],
         wind_jul="SW", wind_jan="N"),
    dict(name="Delhi", koppen="BSh", lat=28.6, lon=77.2,
         t=[13.9, 17.0, 22.6, 28.8, 33.0, 33.5, 31.1, 30.0, 29.6, 26.3, 20.7, 15.6],
         p=[19, 22, 16, 13, 18, 82, 207, 235, 128, 19, 4, 10],
         wind_jul="SW", wind_jan="NW"),
    dict(name="Urumqi", koppen="BWk", lat=43.8, lon=87.6,
         t=[-12.0, -8.5, -0.5, 10.0, 17.0, 22.5, 24.5, 23.0, 16.5, 8.0, -2.0, -9.0],
         p=[10, 12, 18, 28, 32, 30, 24, 20, 18, 16, 12, 10],
         wind_jul="W", wind_jan="W"),
    dict(name="Denver", koppen="BSk", lat=39.7, lon=-105.0,
         t=[-1.0, 0.5, 4.0, 8.5, 13.5, 19.0, 23.0, 22.0, 17.0, 10.5, 3.5, -0.5],
         p=[13, 14, 24, 43, 59, 48, 53, 46, 30, 24, 18, 14],
         wind_jul="S", wind_jan="W"),
    # C — temperate
    dict(name="Shanghai", koppen="Cfa", lat=31.2, lon=121.5,
         t=[4.8, 6.2, 9.7, 15.4, 20.3, 24.2, 28.0, 27.8, 24.4, 19.2, 13.0, 7.1],
         p=[51, 57, 98, 88, 94, 157, 148, 152, 117, 64, 51, 39],
         wind_jul="SE", wind_jan="N"),
    dict(name="BuenosAires", koppen="Cfa", lat=-34.6, lon=-58.4,
         t=[24.9, 23.6, 21.9, 17.9, 14.5, 11.6, 11.1, 12.7, 14.2, 17.0, 20.3, 23.2],
         p=[121, 123, 153, 107, 92, 50, 57, 62, 78, 119, 103, 97],
         wind_jul="N", wind_jan="E"),
    dict(name="London", koppen="Cfb", lat=51.5, lon=-0.1,
         t=[5.2, 5.3, 7.6, 9.9, 13.3, 16.2, 18.5, 18.4, 15.5, 11.9, 8.2, 5.8],
         p=[55, 40, 42, 44, 49, 46, 46, 50, 50, 68, 59, 55],
         wind_jul="SW", wind_jan="SW"),
    dict(name="Melbourne", koppen="Cfb", lat=-37.8, lon=145.0,
         t=[20.0, 20.0, 18.0, 15.0, 12.0, 9.5, 9.0, 10.0, 12.0, 14.0, 16.0, 18.0],
         p=[47, 48, 50, 57, 56, 49, 48, 50, 58, 66, 60, 59],
         wind_jul="N", wind_jan="S"),
    dict(name="Athens", koppen="Csa", lat=38.0, lon=23.7,
         t=[9.9, 10.7, 12.9, 16.6, 21.6, 26.2, 28.7, 28.5, 24.6, 19.6, 14.9, 11.3],
         p=[51, 47, 46, 29, 21, 9, 6, 6, 14, 53, 57, 61],
         wind_jul="N", wind_jan="N"),
    dict(name="Guangzhou", koppen="Cwa", lat=23.1, lon=113.3,
         t=[13.6, 15.0, 18.1, 22.1, 25.5, 27.6, 28.6, 28.4, 27.1, 24.2, 19.6, 15.3],
         p=[43, 65, 86, 183, 285, 318, 227, 221, 176, 70, 37, 31],
         wind_jul="SE", wind_jan="N"),
    dict(name="Dhaka", koppen="Cwa", lat=23.8, lon=90.4,
         t=[19.0, 21.5, 26.0, 28.5, 29.0, 28.8, 28.6, 28.7, 28.5, 27.5, 24.0, 20.5],
         p=[7, 25, 61, 144, 246, 358, 371, 327, 277, 166, 33, 8],
         wind_jul="SE", wind_jan="N"),
    # D — continental
    dict(name="Chicago", koppen="Dfa", lat=41.9, lon=-87.6,
         t=[-4.0, -2.0, 3.5, 9.5, 15.5, 21.0, 24.0, 23.0, 19.0, 12.0, 5.0, -1.5],
         p=[46, 44, 64, 86, 94, 103, 94, 90, 78, 64, 66, 55],
         wind_jul="SW", wind_jan="W"),
    dict(name="Moscow", koppen="Dfb", lat=55.8, lon=37.6,
         t=[-6.5, -6.7, -1.0, 6.7, 13.2, 17.0, 19.2, 17.0, 11.3, 5.6, -1.2, -5.2],
         p=[52, 41, 35, 37, 51, 80, 85, 82, 68, 71, 54, 51],
         wind_jul="NW", wind_jan="SW"),
    dict(name="Beijing", koppen="Dwa", lat=39.9, lon=116.4,
         t=[-3.7, -0.7, 5.8, 14.2, 19.9, 24.0, 26.2, 24.9, 20.0, 13.1, 4.6, -1.5],
         p=[2.7, 4.9, 8.3, 21.2, 34.2, 78.1, 185.2, 159.7, 45.5, 21.8, 7.4, 2.8],
         wind_jul="S", wind_jan="NW"),
    dict(name="Harbin", koppen="Dwa", lat=45.8, lon=126.5,
         t=[-17.0, -12.0, -3.0, 8.0, 15.0, 20.0, 23.0, 21.0, 14.0, 6.0, -5.0, -14.0],
         p=[5, 7, 10, 20, 40, 90, 150, 120, 60, 25, 10, 7],
         wind_jul="S", wind_jan="W"),
    dict(name="Anchorage", koppen="Dfc", lat=61.2, lon=-149.9,
         t=[-8.0, -6.0, -2.0, 3.0, 9.0, 13.5, 15.5, 14.0, 10.0, 3.0, -3.0, -7.0],
         p=[18, 18, 16, 13, 18, 27, 43, 61, 68, 51, 28, 26],
         wind_jul="SW", wind_jan="E"),
    # E — polar
    dict(name="Reykjavik", koppen="ET", lat=64.1, lon=-21.9,
         t=[0.0, 0.4, 0.5, 2.9, 6.3, 9.0, 10.6, 10.3, 7.4, 4.4, 1.1, 0.2],
         p=[76, 72, 82, 58, 44, 50, 52, 62, 67, 86, 73, 79],
         wind_jul="SE", wind_jan="E"),
]

# Model month indices (month 0 = March vernal equinox).
_MONTH_JULY = 4
_MONTH_JANUARY = 10

_COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def _wind_dir_compass(u: float, v: float) -> str:
    """Meteorological direction the wind blows FROM, as an 8-point compass."""
    if abs(u) < 1e-9 and abs(v) < 1e-9:
        return "calm"
    deg = (np.degrees(np.arctan2(-u, -v)) + 360.0) % 360.0
    return _COMPASS[int(np.round(deg / 45.0)) % 8]


def _nearest_cell(xyz: np.ndarray, lat: float, lon: float) -> int:
    pt = np.array([
        np.cos(np.radians(lat)) * np.cos(np.radians(lon)),
        np.sin(np.radians(lat)),
        np.cos(np.radians(lat)) * np.sin(np.radians(lon)),
    ])
    return int(np.argmax(xyz @ pt))


def _dequant(m: dict, name: str, n: int) -> np.ndarray:
    """Decode an int16-quantized monthly field (with scale/offset)."""
    a = np.frombuffer(bytes(m[name]), dtype=np.int16).reshape(n, 12).astype(np.float64)
    key = name.replace("_monthly", "")
    return a * m[key + "_scale"] + m[key + "_offset"]


def main() -> None:
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    map_dir = Path(sys.argv[1])
    mesh_path = map_dir / "cvt_mesh.json"
    monthly_path = map_dir / "climate_monthly.msgpack"
    if not mesh_path.exists() or not monthly_path.exists():
        print(f"missing {mesh_path} or {monthly_path}")
        sys.exit(1)

    with gzip.open(mesh_path, "rb") as f:
        mesh = json.load(f)
    cells = mesh["cells"]
    n = mesh["num_cells"]
    xyz = np.array([[c["x"], c["y"], c["z"]] for c in cells])

    with open(monthly_path, "rb") as f:
        m = msgpack.unpackb(f.read(), raw=False)
    t = _dequant(m, "t_monthly", n)
    p = _dequant(m, "p_monthly", n)
    we = _dequant(m, "wind_east_monthly", n)
    wn = _dequant(m, "wind_north_monthly", n)

    print("station (koppen) | T_ann mod/obs  T_rng mod/obs | P_ann mod/obs   | Jul wind  Jan wind")
    print("                 |   (°C)          (°C)        |   (mm)          | mod/obs   mod/obs")
    print("-" * 100)

    d_t, d_p = [], []
    for s in STATIONS:
        i = _nearest_cell(xyz, s["lat"], s["lon"])
        obs_t = np.array(s["t"])
        obs_p = np.array(s["p"])
        # Model monthly → Jan-Dec order to compare directly.
        # model month m (0=Mar) == calendar month (m+2) % 12.
        mod_t = t[i][(np.arange(12) + 2) % 12]
        mod_p = p[i][(np.arange(12) + 2) % 12]

        t_ann_mod, t_ann_obs = mod_t.mean(), obs_t.mean()
        t_rng_mod, t_rng_obs = mod_t.max() - mod_t.min(), obs_t.max() - obs_t.min()
        p_ann_mod, p_ann_obs = mod_p.sum(), obs_p.sum()

        wind_jul = _wind_dir_compass(we[i, _MONTH_JULY], wn[i, _MONTH_JULY])
        wind_jan = _wind_dir_compass(we[i, _MONTH_JANUARY], wn[i, _MONTH_JANUARY])

        d_t.append(abs(t_ann_mod - t_ann_obs))
        d_p.append(abs(p_ann_mod - p_ann_obs))

        print(f"{s['name'] + ' (' + s['koppen'] + ')':<16} | "
              f"{t_ann_mod:>5.1f}/{t_ann_obs:<5.1f} {t_rng_mod:>5.1f}/{t_rng_obs:<5.1f} | "
              f"{p_ann_mod:>5.0f}/{p_ann_obs:<5.0f}   | "
              f"{wind_jul:>3}/{s['wind_jul']:<4} {wind_jan:>3}/{s['wind_jan']:<4}")

    print("-" * 100)
    print(f"mean |ΔT_ann| = {np.mean(d_t):.1f} °C   "
          f"mean |ΔP_ann| = {np.mean(d_p):.0f} mm")


if __name__ == "__main__":
    main()
