#!/usr/bin/env python3
"""Climate build diff tool — compare two nacrea climate outputs.

Usage:
    uv run python private/scripts/climate_diff.py \\
        data/worlds/nacrea/maps/satellite_nacrea \\
        private/worlds/nacrea/maps/satellite_nacrea

Compares the two most recent mesh files and reports:
- Global summaries (T, P, Köppen counts)
- Top-N cells with largest precipitation / temperature changes
- Band averages by latitude

Useful for verifying small climate modifications where frontend
visualisation is too coarse to see the difference.
"""

import argparse
import json
import sys
from collections import Counter

import numpy as np


def load(path: str) -> tuple[list[dict], dict]:
    from dreamulator.map.export import decompress_mesh_bytes

    with open(f"{path}/cvt_mesh.json", "rb") as f:
        mesh = json.loads(decompress_mesh_bytes(f.read()))
    cells = mesh["cells"]
    # Köppen counts
    try:
        with open(f"{path}/koppen.json") as f:
            koppen = json.load(f)
        kc = Counter(koppen.get("cells", {}).values())
    except FileNotFoundError:
        kc = Counter()
    return cells, kc


def main():
    p = argparse.ArgumentParser(description="Diff two nacrea climate builds")
    p.add_argument("old", help="Path to old build (e.g. data/worlds/nacrea/maps/satellite_nacrea)")
    p.add_argument("new", help="Path to new build (e.g. private/worlds/nacrea/maps/satellite_nacrea)")
    p.add_argument("--top", type=int, default=10, help="Top-N cells to show (default 10)")
    p.add_argument("--band-width", type=float, default=10.0, help="Latitude band width (deg)")
    args = p.parse_args()

    old_cells, old_k = load(args.old)
    new_cells, new_k = load(args.new)

    n = len(old_cells)
    if n != len(new_cells):
        print(f"WARNING: cell count mismatch ({len(old_cells)} vs {len(new_cells)})")
        n = min(len(old_cells), len(new_cells))

    # ── arrays ──
    t_old = np.array([c.get("temperature_C", np.nan) for c in old_cells[:n]])
    t_new = np.array([c.get("temperature_C", np.nan) for c in new_cells[:n]])
    p_old = np.array([c.get("precipitation_mm", np.nan) for c in old_cells[:n]])
    p_new = np.array([c.get("precipitation_mm", np.nan) for c in new_cells[:n]])
    lat = np.array([c["lat"] for c in old_cells[:n]])
    lon = np.array([c["lon"] for c in old_cells[:n]])
    crust = np.array([c.get("crust_type", "") for c in old_cells[:n]])
    land = crust == "continental"
    ocean = np.isin(crust, ["oceanic", "transitional"])

    # ── global ──
    print("=" * 60)
    print("  GLOBAL SUMMARY")
    print("=" * 60)
    dT = t_new - t_old
    dP = p_new - p_old
    print(f"  Temperature  : {np.nanmean(t_old):.2f} -> {np.nanmean(t_new):.2f} °C  (Δ={np.nanmean(dT):+.3f})")
    print(f"  T (land)     : {np.nanmean(t_old[land]):.2f} -> {np.nanmean(t_new[land]):.2f} °C")
    print(f"  T (ocean)    : {np.nanmean(t_old[ocean]):.2f} -> {np.nanmean(t_new[ocean]):.2f} °C")
    print(f"  T min/max    : {np.nanmin(t_old):.1f}/{np.nanmax(t_old):.1f} -> "
          f"{np.nanmin(t_new):.1f}/{np.nanmax(t_new):.1f}")
    print(f"  Precipitation: {np.nanmean(p_old):.0f} -> {np.nanmean(p_new):.0f} mm/yr  "
          f"(Δ={np.nanmean(dP):+.1f})")
    print(f"  P (land)     : {np.nanmean(p_old[land]):.0f} -> {np.nanmean(p_new[land]):.0f} mm/yr")

    # ── Köppen ──
    if old_k and new_k:
        all_keys = sorted(set(old_k) | set(new_k))
        print(f"\n  Koppen changes (>10 cells):")
        for k in all_keys:
            dk = new_k.get(k, 0) - old_k.get(k, 0)
            if abs(dk) >= 10:
                print(f"    {k:>6s}: {old_k.get(k,0):>5d} -> {new_k.get(k,0):<5d}  ({dk:+d})")

    # ── Biomes ──
    b_old = Counter(c.get("biome") for c in old_cells[:n])
    b_new = Counter(c.get("biome") for c in new_cells[:n])
    all_b = sorted(set(b_old) | set(b_new))
    print(f"\n  Biome changes (>10 cells):")
    for k in all_b:
        db = b_new.get(k, 0) - b_old.get(k, 0)
        if abs(db) >= 10:
            print(f"    {k:>25s}: {b_old.get(k,0):>5d} -> {b_new.get(k,0):<5d}  ({db:+d})")

    # ── Band averages ──
    bw = args.band_width
    print(f"\n{'='*60}")
    print(f"  BAND AVERAGES ({bw} deg)")
    print(f"{'='*60}")
    for lo in range(-90, 90, int(bw)):
        hi = lo + bw
        mask = (lat >= lo) & (lat < hi)
        if not mask.any():
            continue
        dt_band = float(np.nanmean(dT[mask]))
        dp_band = float(np.nanmean(dP[mask]))
        if abs(dt_band) > 0.01 or abs(dp_band) > 0.5:
            print(f"  {int(lo):+4d} to {int(hi):+4d} deg:  dT={dt_band:+.2f} C  dP={dp_band:+.0f} mm/yr")

    # ── Top-N precipitation changes ──
    print(f"\n{'='*60}")
    print(f"  TOP {args.top} PRECIPITATION CHANGES")
    print(f"{'='*60}")
    abs_dP = np.abs(dP)
    top_idx = np.argsort(abs_dP)[-args.top:][::-1]
    for i in top_idx:
        print(f"  lat={lat[i]:.1f} lon={lon[i]:.1f}  "
              f"P: {p_old[i]:.0f} -> {p_new[i]:.0f} mm/yr  (Δ={dP[i]:+.0f})  "
              f"T: {t_old[i]:.1f} -> {t_new[i]:.1f} °C")

    # ── Top-N temperature changes ──
    print(f"\n  TOP {args.top} TEMPERATURE CHANGES")
    abs_dT = np.abs(dT)
    top_idx = np.argsort(abs_dT)[-args.top:][::-1]
    for i in top_idx:
        print(f"  lat={lat[i]:.1f} lon={lon[i]:.1f}  "
              f"T: {t_old[i]:.1f} -> {t_new[i]:.1f} °C  (Δ={dT[i]:+.2f})  "
              f"P: {p_old[i]:.0f} -> {p_new[i]:.0f} mm/yr")


if __name__ == "__main__":
    main()
