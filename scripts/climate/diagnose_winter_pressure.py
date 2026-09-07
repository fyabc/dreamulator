"""Winter-monsoon pressure-anomaly diagnosis — why the January wind is wrong.

§7 (winter monsoon): the January surface wind at Beijing/Harbin blows *from* the
warm ocean (SE/E) instead of *from* the cold Siberian interior (NW).  This
script inspects the pressure-anomaly chain that drives that wind —
``pressure_anomaly_monthly``: ΔT = T − T_zonal, then the annual mean removed,
then ΔP = −P·(d/H)·ΔT/T̄ — to see where the sign goes wrong.  It prints, at a
set of East-Asian probe cells, the January temperature, zonal-mean temperature,
raw vs seasonal land-sea anomaly, and the resulting pressure anomaly, for both
the current (annual-mean-removed) form and a raw (land-sea contrast) form.

Loads the built monthly temperature (no full simulation), so it runs in seconds.

Usage:
    uv run python scripts/climate/diagnose_winter_pressure.py --world-dir data/worlds
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import msgpack
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from station_diagnostics import _nearest_cell  # noqa: E402

from dreamulator.engine.monsoon_circulation import zonal_mean_monthly  # noqa: E402
from dreamulator.validate_climate import _load_mesh  # noqa: E402

# (name, lat, lon) probes across East Asia and the adjacent ocean.
_PROBES = [
    ("Harbin", 45.8, 126.5),
    ("Beijing", 39.9, 116.4),
    ("Siberia(Baikal)", 52.0, 105.0),
    ("Mongolia", 47.0, 100.0),
    ("Bohai", 39.0, 120.0),
    ("SeaOfJapan", 40.0, 135.0),
    ("NPacific", 40.0, 160.0),
    ("Kuroshio", 30.0, 140.0),
]


def _load_monthly_t(world_dir: Path, planet: str, branch: str | None) -> np.ndarray | None:
    mdir = world_dir / (f"branches/{branch}/" if branch else "") / "maps" / planet
    p = mdir / "climate_monthly.msgpack"
    if not p.exists():
        return None
    raw = msgpack.unpackb(p.read_bytes(), raw=False)
    n = raw["num_cells"]
    if raw.get("dtype") == "int16":
        t = (
            np.frombuffer(raw["t_monthly"], dtype=np.int16).reshape(n, 12).astype(np.float64)
            * raw["t_scale"]
            + raw["t_offset"]
        )
    else:
        t = np.frombuffer(raw["t_monthly"], dtype=np.float32).reshape(n, 12).astype(np.float64)
    return t


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--world", default="earth")
    parser.add_argument("--planet", default="planet_earth")
    parser.add_argument("--branch", default="climate-dev")
    parser.add_argument("--world-dir", default="data/worlds")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[2]
    world_dir = root / args.world_dir / args.world
    mesh = _load_mesh(world_dir, args.planet, args.branch or None)
    if mesh is None:
        print("ERROR: no mesh")
        return

    t_monthly = _load_monthly_t(world_dir, args.planet, args.branch or None)
    if t_monthly is None:
        print("ERROR: climate_monthly.msgpack not found (build first)")
        return

    lat_deg = np.array([c.lat for c in mesh.cells], dtype=np.float64)
    nodes_xyz = np.array([[c.x, c.y, c.z] for c in mesh.cells], dtype=np.float64)

    # month index: 0=Mar … 10=Jan.
    m_jan = 10
    m_jul = 4

    t_zonal = zonal_mean_monthly(t_monthly, lat_deg, band_deg=5.0)
    dt_raw = t_monthly - t_zonal
    dt_seasonal = dt_raw - dt_raw.mean(axis=1, keepdims=True)

    # Raw land-sea contrast pressure anomaly (no annual-mean removal) — the
    # form the seasonal monsoon should physically use.
    t_zonal_k = np.maximum(t_zonal.mean(axis=1, keepdims=True) + 273.15, 200.0)
    dp_raw = -1013.25 * 0.25 * dt_raw / t_zonal_k
    dp_seasonal = -1013.25 * 0.25 * dt_seasonal / t_zonal_k

    print(f"\n{'probe':>16} | {'Tjan':>6} | {'Tzonal':>7} | {'dT_raw':>7} | {'dT_seas':>8} "
          f"| {'dP_raw':>7} | {'dP_seas':>8}")
    print("-" * 85)
    for name, lat, lon in _PROBES:
        gi = _nearest_cell(nodes_xyz, lat, lon)
        print(
            f"{name:>16} | {t_monthly[gi, m_jan]:>6.1f} | {t_zonal[gi, m_jan]:>7.1f} "
            f"| {dt_raw[gi, m_jan]:>7.1f} | {dt_seasonal[gi, m_jan]:>8.1f} "
            f"| {dp_raw[gi, m_jan]:>7.1f} | {dp_seasonal[gi, m_jan]:>8.1f}"
        )

    # The same for July, to show the seasonal reversal.
    print(f"\n{'probe':>16} | {'Tjul':>6} | {'Tzonal':>7} | {'dT_raw':>7} | {'dT_seas':>8} "
          f"| {'dP_raw':>7} | {'dP_seas':>8}")
    print("-" * 85)
    for name, lat, lon in _PROBES:
        gi = _nearest_cell(nodes_xyz, lat, lon)
        print(
            f"{name:>16} | {t_monthly[gi, m_jul]:>6.1f} | {t_zonal[gi, m_jul]:>7.1f} "
            f"| {dt_raw[gi, m_jul]:>7.1f} | {dt_seasonal[gi, m_jul]:>8.1f} "
            f"| {dp_raw[gi, m_jul]:>7.1f} | {dp_seasonal[gi, m_jul]:>8.1f}"
        )


if __name__ == "__main__":
    main()
