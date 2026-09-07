"""Seasonal temperature decomposition — mean / amplitude / phase errors per station.

Decomposes the model's station-level temperature bias into three independent
components against the hardcoded observed monthly climatology of the 26
reference stations (shared with ``station_diagnostics.py``):

  - mean error   — annual-mean bias (radiative-equilibrium / continentality)
  - amplitude    — seasonal-range error (winter-vs-summer damping)
  - winter/summer split — which half of the cycle carries the error

Also reproduces the model's own EBM amplitude formula per station
(``monthly_temperature``: ΔQ_ω(1−α)/√(B_eff²+(ωC)²)) so a formula-vs-mesh
mismatch (hidden amplification) is distinguishable from a genuine
physical misfit.  See proposals/climate-layer-improvement.md §4.

Usage::

    uv run python scripts/diagnose_seasonal_decomposition.py
    uv run python scripts/diagnose_seasonal_decomposition.py --world-dir data/worlds
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import msgpack
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from station_diagnostics import STATIONS  # noqa: E402

from dreamulator.engine.climate_seasonality import (  # noqa: E402
    monthly_insolation,
    seasonal_heat_capacity,
)

# Earth seasonal-EBM parameters (pipeline defaults; keep in sync with
# pipeline_types.TerrainPipelineConfig).
_B_EFF = 2.0 + 6 * 0.35  # B_rad + 6D (quadrupole seasonal mode)
_OMEGA = 2.0 * np.pi / (365.25 * 86400.0)
_ALBEDO = 0.306
_SOLAR = 1361.0
_OBLIQUITY = 23.44
_COASTAL_SCALE_KM = 250.0  # seasonal_coastal_scale_km (NOT the 500 fn default)


def _find_project_root() -> Path:
    d = Path.cwd()
    while d != d.parent:
        if (d / "pyproject.toml").exists():
            return d
        d = d.parent
    return Path.cwd()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--world", default="earth")
    parser.add_argument("--planet", default="planet_earth")
    parser.add_argument("--branch", default="climate-dev", help="empty string for root world")
    parser.add_argument("--world-dir", default="data/worlds")
    args = parser.parse_args()

    root = _find_project_root()
    base = root / args.world_dir / args.world
    if args.branch:
        base = base / "branches" / args.branch
    mdir = base / "maps" / args.planet

    mesh_path = mdir / "cvt_mesh.json"
    monthly_path = mdir / "climate_monthly.msgpack"
    if not mesh_path.exists() or not monthly_path.exists():
        print(f"missing {mesh_path} or {monthly_path} — build the world first")
        return

    from dreamulator.map.export import decompress_mesh_bytes

    mesh = json.loads(decompress_mesh_bytes(mesh_path.read_bytes()))
    cells = mesh["cells"]
    n = len(cells)
    lat = np.array([c["lat"] for c in cells])
    xyz = np.array([[c["x"], c["y"], c["z"]] for c in cells])
    dcoast = np.array(
        [c["distance_to_coast_km"] if c["distance_to_coast_km"] is not None else 0.0 for c in cells]
    )
    land = np.array([c.get("water_class", "ocean") == "land" for c in cells])

    raw = msgpack.unpackb(monthly_path.read_bytes(), raw=False)
    t = (
        np.frombuffer(raw["t_monthly"], dtype=np.int16).reshape(n, 12).astype(np.float64)
        * raw["t_scale"]
        + raw["t_offset"]
    )

    heat_capacity = seasonal_heat_capacity(land, ~land, dcoast, coastal_scale_km=_COASTAL_SCALE_KM)
    q_all = monthly_insolation(np.radians(lat), _OBLIQUITY, _SOLAR)
    months = np.arange(12.0)
    a1 = (2 / 12) * np.sum(q_all * np.cos(2 * np.pi * months / 12), axis=1)
    b1 = (2 / 12) * np.sum(q_all * np.sin(2 * np.pi * months / 12), axis=1)
    dq = np.sqrt(a1**2 + b1**2)
    amp_formula = dq * (1 - _ALBEDO) / np.sqrt(_B_EFF**2 + (_OMEGA * heat_capacity) ** 2)

    header = (
        f"{'station':<11}{'grp':<5}{'meanE':>6}{'ampM':>6}{'ampO':>6}"
        f"{'ampE':>6}{'ampFor':>7}{'winE':>6}{'sumE':>6}{'phM':>4}{'phO':>4}"
    )
    print(header)
    rows: list[tuple[str, float, float, float, float]] = []
    p_xyz = np.stack(
        [
            np.array(
                [
                    np.cos(np.radians(s["lat"])) * np.cos(np.radians(s["lon"])),
                    np.sin(np.radians(s["lat"])),
                    np.cos(np.radians(s["lat"])) * np.sin(np.radians(s["lon"])),
                ]
            )
            for s in STATIONS
        ]
    )
    for i, s in enumerate(STATIONS):
        gi = int(np.argmax(xyz @ p_xyz[i]))
        # model month m (0=Mar) == calendar (m+2)%12 → calendar j from m=(j-2)%12
        mcal = t[gi][(np.arange(12) - 2) % 12]
        obs = np.array(s["t"])
        mean_e = float(mcal.mean() - obs.mean())
        # semi-amplitude (half peak-to-peak) for model / obs / formula
        amp_m = float((mcal.max() - mcal.min()) / 2)
        amp_o = float((obs.max() - obs.min()) / 2)
        amp_f = float(amp_formula[gi])
        win_idx = 0 if s["lat"] >= 0 else 6  # Jan (NH) / Jul (SH) = cold month
        sum_idx = 6 if s["lat"] >= 0 else 0
        win_e = float(mcal[win_idx] - obs[win_idx])
        sum_e = float(mcal[sum_idx] - obs[sum_idx])
        ph_m, ph_o = int(np.argmax(mcal)), int(np.argmax(obs))
        rows.append((s["koppen"][0], mean_e, amp_m - amp_o, win_e, sum_e))
        print(
            f"{s['name']:<11}{s['koppen']:<5}{mean_e:>6.1f}{amp_m:>6.1f}{amp_o:>6.1f}"
            f"{amp_m - amp_o:>6.1f}{amp_f:>7.1f}{win_e:>6.1f}{sum_e:>6.1f}{ph_m:>4}{ph_o:>4}"
        )

    print("\n== group aggregates (mean of station errors) ==")
    print(f"  {'grp':<4}{'n':>3}{'meanE':>8}{'ampE':>8}{'winE':>8}{'sumE':>8}")
    for g in "ABCDE":
        sel = [r for r in rows if r[0] == g]
        if not sel:
            continue
        print(
            f"  {g:<4}{len(sel):>3}{np.mean([r[1] for r in sel]):>8.1f}"
            f"{np.mean([r[2] for r in sel]):>8.1f}"
            f"{np.mean([r[3] for r in sel]):>8.1f}{np.mean([r[4] for r in sel]):>8.1f}"
        )


if __name__ == "__main__":
    main()
