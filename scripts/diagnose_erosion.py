#!/usr/bin/env python3
"""侵蚀大尺度诊断（Phase 3B P0 验收口径工具）。

用法:
    uv run python scripts/diagnose_erosion.py <map_dir> [--time-myr 100]

从已构建地图（含 ``cvt_mesh.json``）读取侵蚀产物，输出大尺度验收指标：

- 侵蚀量：``net_erosion_m`` 分布、总侵蚀体积、平均剥蚀速率
- 高程分布：侵蚀前后 hypsometry（陆域分位数、平均海拔、起伏度）
- 坡度统计：侵蚀前后陆域坡度中位/极值
- 水系统计：最终表面的流量累积 → 河流分级、河网密度

验收哲学（2026-08-25 调研结论，见 docs/design/competitor-analysis.md §4.2.1）：
51 km 网格上侵蚀的合法产物是**大尺度地貌改造与物质再分配**，不是可见河谷；
本脚本只报大尺度指标，不作为「河道是否好看」的依据。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import yaml


def _load_mesh(map_dir: Path):
    """Load the CVT mesh (gzip-transparent) as a typed CVTMesh."""
    from pydantic import TypeAdapter

    from dreamulator.map.export import decompress_mesh_bytes
    from dreamulator.map.models import CVTMesh

    raw = (map_dir / "cvt_mesh.json").read_bytes()
    data = json.loads(decompress_mesh_bytes(raw))
    return TypeAdapter(CVTMesh).validate_python(data)


def _load_map_meta(map_dir: Path) -> tuple[float, float]:
    """Return (sea_level_m, radius_km) from map.yaml (defaults 0.0 / 6371)."""
    map_yaml = map_dir / "map.yaml"
    if map_yaml.exists():
        meta = yaml.safe_load(map_yaml.read_text(encoding="utf-8"))
        return float(meta.get("sea_level_m", 0.0)), float(meta.get("radius_km", 6371.0))
    return 0.0, 6371.0


def _slope_stats(
    h: np.ndarray, is_land: np.ndarray, neighbors: list[list[int]], dists_km: list[list[float]]
) -> tuple[float, float, float]:
    """Median / p95 / max land slope (m/km) over land-land edges."""
    slopes: list[float] = []
    for i in range(len(h)):
        if not is_land[i]:
            continue
        for k, j in enumerate(neighbors[i]):
            if not is_land[j]:
                continue
            d = dists_km[i][k]
            if d > 0:
                slopes.append(abs(h[i] - h[j]) / d)
    if not slopes:
        return 0.0, 0.0, 0.0
    s = np.array(slopes)
    return float(np.median(s)), float(np.percentile(s, 95)), float(s.max())


def main() -> int:
    # Windows 控制台默认 GBK，强制 UTF-8 输出（中文 + 特殊符号）
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("map_dir", help="地图目录（含 cvt_mesh.json）")
    parser.add_argument(
        "--time-myr",
        type=float,
        default=None,
        help="侵蚀总时长（Myr），给了才换算平均剥蚀速率",
    )
    args = parser.parse_args()

    map_dir = Path(args.map_dir)
    if not (map_dir / "cvt_mesh.json").exists():
        print(f"错误：{map_dir}/cvt_mesh.json 不存在", file=sys.stderr)
        return 1

    print(f"加载 {map_dir} ...")
    mesh = _load_mesh(map_dir)
    sea_level, radius_km = _load_map_meta(map_dir)

    from dreamulator.map.hydrology import (
        RIVER_ORDER_THRESHOLDS,
        build_adjacency,
        compute_flow_accumulation,
        compute_flow_directions,
        priority_flood_fill,
        route_flat_cells,
    )

    n = mesh.num_cells
    elev = np.array([c.elevation for c in mesh.cells], dtype=np.float64)
    net = np.array([c.net_erosion_m for c in mesh.cells], dtype=np.float64)
    area = np.array([c.area_km2 for c in mesh.cells], dtype=np.float64)
    is_land = elev >= sea_level
    h_after = elev
    h_before = elev - net  # net_erosion_m = h_after − h_before（侵蚀为负）

    neighbors, dists_km = build_adjacency(mesh.cells, radius_km, mesh.cell_xyz)

    # ── 1. 概览 ─────────────────────────────────────────────────────────────
    print("\n== 概览 ==")
    print(f"cell 数: {n}  海平面: {sea_level:.1f} m  陆地占比: {is_land.mean() * 100:.1f}%")
    eroded = is_land & (net < -1e-6)
    eroded_pct = eroded.sum() / max(is_land.sum(), 1) * 100
    print(f"被侵蚀陆域 cell: {eroded.sum()}（陆域 {eroded_pct:.1f}%）")

    # ── 2. 侵蚀量与质量平衡 ────────────────────────────────────────────────
    print("\n== 侵蚀量（net_erosion_m，陆域；负=侵蚀、正=沉积）==")
    if eroded.any():
        e = net[eroded]
        pct = np.percentile(e, [1, 10, 50, 90])
        print(
            f"侵蚀分位: min {e.min():.1f} / p1 {pct[0]:.1f} / p10 {pct[1]:.1f} / "
            f"中位 {pct[2]:.1f} / p90 {pct[3]:.1f} m"
        )
        gross_ero_m3 = float(np.sum(-net[is_land & (net < 0)] * area[is_land & (net < 0)])) * 1e6
        dep_mask = is_land & (net > 1e-6)
        dep_land_m3 = float(np.sum(net[dep_mask] * area[dep_mask])) * 1e6
        net_land_m3 = float(np.sum(-net[is_land] * area[is_land])) * 1e6
        mean_net_m = float(np.mean(-net[is_land]))
        print(
            f"陆域平均净变: {mean_net_m:.1f} m   净体积变化: {net_land_m3 / 1e9:,.0f} km³"
        )
        print(f"侵蚀总量: {gross_ero_m3 / 1e9:,.0f} km³（{eroded.sum()} cells）")
        print(
            f"沉积: 陆域 {dep_land_m3 / 1e9:,.0f} km³（{dep_mask.sum()} cells）；"
            f"水体（三角洲/湖泊充填，侵蚀量−陆域沉积） "
            f"{(gross_ero_m3 - dep_land_m3) / 1e9:,.0f} km³"
        )
        if args.time_myr:
            rate = mean_net_m / args.time_myr  # m/Myr
            print(
                f"平均净变速率: {rate:.2f} m/Myr = {rate * 1e-3:.5f} mm/yr"
                f"（@ {args.time_myr} Myr；地球大陆均值 ~0.03–0.07 mm/yr 含构造供给）"
            )
    else:
        print("无侵蚀记录（net_erosion_m 全零——未启用侵蚀或构建早于 3B）")

    # ── 3. 高程分布（侵蚀前后）─────────────────────────────────────────────
    print("\n== 高程分布（陆域，侵蚀前 → 后）==")
    pts = [1, 5, 25, 50, 75, 95, 99]
    qb = np.percentile(h_before[is_land], pts)
    qa = np.percentile(h_after[is_land], pts)
    for p, b, a in zip(pts, qb, qa, strict=True):
        print(f"p{p:<2}: {b:8.1f} → {a:8.1f} m   (Δ {a - b:+.1f})")
    print(
        f"平均: {h_before[is_land].mean():8.1f} → {h_after[is_land].mean():8.1f} m   "
        f"起伏度 p95−p50: {qb[5] - qb[3]:.0f} → {qa[5] - qa[3]:.0f} m"
    )

    # ── 4. 坡度统计 ─────────────────────────────────────────────────────────
    print("\n== 坡度统计（陆-陆边，m/km；侵蚀前 → 后）==")
    for label, h in (("前", h_before), ("后", h_after)):
        med, p95, mx = _slope_stats(h, is_land, neighbors, dists_km)
        print(
            f"{label}: 中位 {med:6.1f} (≈{np.degrees(np.arctan(med / 1000)):.2f}°)  "
            f"p95 {p95:6.1f}  max {mx:6.1f} m/km"
        )

    # ── 5. 水系统计（最终表面）──────────────────────────────────────────────
    # 注：RIVER_ORDER_THRESHOLDS 的固定阈值（100–1e5 km²）在 200k 分辨率下
    # 低于单 cell 面积（~2900 km²），无分辨力；此处改用 cell 面积相对阈值。
    print("\n== 水系统计（最终表面，D8 + priority flood）==")
    filled, connected = priority_flood_fill(h_after, is_land, neighbors)
    flow_dir = compute_flow_directions(filled, is_land, neighbors, dists_km)
    flow_dir = route_flat_cells(filled, is_land, connected, neighbors, flow_dir)
    accum = compute_flow_accumulation(flow_dir, is_land, area)

    land_area = float(area[is_land].sum())
    a_cell = float(np.median(area[is_land]))
    acc_land = accum[is_land]
    pct = np.percentile(acc_land, [50, 75, 90, 99])
    print(
        f"汇水面积分位（陆域）: p50 {pct[0]:,.0f} / p75 {pct[1]:,.0f}"
        f" / p90 {pct[2]:,.0f} / p99 {pct[3]:,.0f} km²"
    )
    print(f"（单 cell 面积中位 {a_cell:,.0f} km²；阈值按 cell 面积倍数分级）")
    for k in (2, 5, 20, 100):
        m = is_land & (accum >= k * a_cell)
        frac = float(area[m].sum()) / land_area * 100
        print(f"汇水 ≥ {k:>3}×cell: 陆域 {frac:5.2f}%（{m.sum()} cells）")
    fixed = dict(sorted(RIVER_ORDER_THRESHOLDS.items()))
    print(f"参考：固定阈值分级 {fixed} km² —— 低于本分辨率单 cell 面积，仅供细网格使用")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
