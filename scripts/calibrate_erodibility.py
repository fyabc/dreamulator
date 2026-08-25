#!/usr/bin/env python3
"""Measure fluvial erodibility K₀ against Earth's instantaneous denudation rate.

Applies erosion to the imported ETOPO1 Earth terrain with Earth parameters
and reports the K₀ that reproduces the observed mean continental denudation
rate ~0.03–0.07 mm/yr (target default 0.05).

WARNING (2026-08-26 calibration history): Earth's ~0.05 mm/yr is a STEADY-
STATE rate maintained by continuous tectonic supply.  The sequential pipeline
(tectonics stage → erosion stage, no uplift compensation) is a post-orogenic
decay configuration — using this steady-state K₀ (=52) planates nacrea in
100 Myr (p50 695→1 m).  The shipped default K₀=2 is instead anchored to
post-orogenic survival evidence (Urals/Appalachians keep ~1 km relief after
~300 Myr; Cortial's own in-loop decay e-folds at ~333 Myr).  Keep this script
as the instantaneous-rate measurement tool; see erosion.md §6.1 and
competitor-analysis.md §4.2.2.

Usage:
    uv run python scripts/calibrate_erodibility.py [--target 0.05]
        [--time-myr 1.0] [--candidates 1e-3,3e-3,1e-2,3e-2,1e-1,3e-1]

Prints a K → rate table and the log-interpolated K₀ hitting the target.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

# Windows 控制台默认 GBK，强制 UTF-8 输出（K₀ 下标等特殊字符）
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

EARTH_MESH = Path("data/worlds/earth/maps/planet_earth/cvt_mesh.json")


def _load_earth_mesh():
    from pydantic import TypeAdapter

    from dreamulator.map.export import decompress_mesh_bytes
    from dreamulator.map.models import CVTMesh

    raw = EARTH_MESH.read_bytes()
    return TypeAdapter(CVTMesh).validate_json(decompress_mesh_bytes(raw))


def _measure_rate(
    mesh, elev0: list[float], k: float, time_myr: float, steps: int
) -> float:
    """Run erosion with erodibility k and return the mean land denudation
    rate in mm/yr (volume-weighted over land cells).

    ``mesh`` is modified in place; ``elev0`` restores it before the run.
    """
    from dreamulator.map.erosion import apply_erosion
    from dreamulator.map.pipeline_types import TerrainPipelineConfig

    for c, h in zip(mesh.cells, elev0, strict=True):
        c.elevation = h
        c.net_erosion_m = 0.0
    config = TerrainPipelineConfig(
        erosion_algorithm="stream_power",
        surface_evolution_time_myr=time_myr,
        stream_power_steps=steps,
        fluvial_erodibility=k,
        # Earth parameters (shared-physics calibration anchor)
        radius_km=6371.0,
        rotation_period_days=1.0,
        sea_level_offset_m=0.0,
        climate_coupling="proxy",
    )
    t0 = time.time()
    apply_erosion(mesh, config)
    dt = time.time() - t0

    elev = np.array([c.elevation for c in mesh.cells])
    net = np.array([c.net_erosion_m for c in mesh.cells])
    area = np.array([c.area_km2 for c in mesh.cells])
    # Land mask from the ORIGINAL surface (net_erosion only set on land).
    h0 = elev - net
    land = h0 >= 0.0

    eroded_m3 = float(np.sum(-net[land & (net < 0)] * area[land & (net < 0)])) * 1e6
    land_area_m2 = float(area[land].sum()) * 1e6
    mean_depth_m = eroded_m3 / land_area_m2  # gross denudation depth
    rate_mm_yr = mean_depth_m / (time_myr * 1e6) * 1e3
    print(
        f"  K={k:.4g}: {rate_mm_yr:.5f} mm/yr  "
        f"(gross {eroded_m3 / 1e9:,.0f} km³ / {time_myr} Myr, {dt:.0f}s)"
    )
    return rate_mm_yr


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--target", type=float, default=0.05,
                        help="Target mean denudation rate (mm/yr; Earth 0.03–0.07)")
    parser.add_argument("--time-myr", type=float, default=1.0,
                        help="Simulated duration for the rate measurement")
    parser.add_argument("--steps", type=int, default=5)
    parser.add_argument("--candidates", type=str,
                        default="1e-3,3e-3,1e-2,3e-2,1e-1,3e-1",
                        help="Comma-separated K candidates")
    args = parser.parse_args()

    if not EARTH_MESH.exists():
        print(f"错误：{EARTH_MESH} 不存在")
        return 1

    print(f"加载 {EARTH_MESH} ...")
    mesh = _load_earth_mesh()
    elev0 = [c.elevation for c in mesh.cells]

    print(f"\n== K₀ 扫描（Earth，{args.time_myr} Myr × {args.steps} 步）==")
    results: list[tuple[float, float]] = []
    for k in [float(x) for x in args.candidates.split(",")]:
        results.append((k, _measure_rate(mesh, elev0, k, args.time_myr, args.steps)))

    # Log-log interpolation: rate ≈ a·K^b → solve K for the target rate.
    lk = np.log([r[0] for r in results])
    lr = np.log([max(r[1], 1e-12) for r in results])
    b, lna = np.polyfit(lk, lr, 1)
    k_target = float(np.exp((np.log(args.target) - lna) / b))

    print(f"\n拟合: rate ∝ K^{b:.2f}")
    print(f"目标 {args.target} mm/yr → 推荐 K₀ = {k_target:.4g}")
    print("\n注意：地球实测 0.03–0.07 mm/yr 含构造供给；无抬升的弛豫场景积分")
    print("自然衰减（rate ∝ S），不会按此速率持续削平地形。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
