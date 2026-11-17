#!/usr/bin/env python3
"""S4: check cross-canvas seam consistency at the pairing sample points.

Adjacent canvases are generated independently; ``seam_pairs.json`` records
points where two owners' land cells meet.  This tool samples both canvases at
each point and reports how far they disagree — surface elevation, bedrock
elevation (surface minus ice, with both sides' ice thickness), land/sea
determination, water, river presence and river flow (see
``dreamulator.media.canvas_seam``).

Usage::

    uv run python scripts/dev/check_canvas_seams.py data/worlds/nacrea/canvases/gcm-t42-712
    uv run python scripts/dev/check_canvas_seams.py <dir> --max-delta-m 60 --json out.json

Exit codes: 0 when every category is fully measured and supplied thresholds
hold; without numeric thresholds this only confirms measurement coverage.
Code 1 reports threshold, coordinate or categorical disagreement; 2 reports
missing coverage, including a requested flow ratio with no paired flow sample.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dreamulator.media.canvas_seam import COORD_TOLERANCE_PX, run_seam_check


def _fmt(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f}"


def _stats_text(stats: object) -> str:
    if not isinstance(stats, dict):
        return "—"
    return f"{_fmt(stats['median_abs_m'])}/{_fmt(stats['p95_abs_m'])}/{_fmt(stats['max_abs_m'])}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("canvases_dir", type=Path, help="canvases/ directory of one world branch")
    parser.add_argument(
        "--max-delta-m",
        type=float,
        default=None,
        help="fail when the largest surface elevation disagreement exceeds this many metres",
    )
    parser.add_argument(
        "--max-bed-delta-m",
        type=float,
        default=None,
        help="fail when the largest bedrock elevation disagreement exceeds this many metres",
    )
    parser.add_argument(
        "--max-flow-ratio",
        type=float,
        default=None,
        help="fail when the largest two-sided flow ratio exceeds this value (e.g. 2 = 2x)",
    )
    parser.add_argument(
        "--river-reach-km",
        type=float,
        default=0.5,
        help="a river counts as present within this distance of the sample point",
    )
    parser.add_argument("--json", type=Path, default=None, help="also write the report as JSON")
    args = parser.parse_args()

    report = run_seam_check(args.canvases_dir, river_reach_km=args.river_reach_km)
    pairs = report["pairs"]
    assert isinstance(pairs, list)

    print(f"canvases with terrain on disk: {', '.join(report['canvases_with_chunks']) or '(none)'}")
    print()
    header = (
        f"{'pair':44} {'samples':>7} {'elev':>7} {'|dsurf| p50/p95/max':>18} "
        f"{'|dbed| p50/p95/max':>18} {'land/sea':>11} {'water':>7} {'river':>7} {'flow-max':>9}"
    )
    print(header)
    print("-" * len(header))

    incomplete = not pairs
    breached: list[str] = []
    for pair in pairs:
        assert isinstance(pair, dict)
        counts = pair["counts"]
        surf = pair["surface_delta"]
        bed = pair["bed_delta"]
        flow = pair["flow_ratio"]
        name = " + ".join(pair["canvases"])
        n = int(pair["samples"])
        elev_n = int(counts["elevation"])
        if n == 0 or any(
            int(counts[k]) < n for k in ("elevation", "bedrock", "landsea", "water", "river")
        ):
            incomplete = True
        if float(pair["coord_mismatch_px"]) > COORD_TOLERANCE_PX:
            breached.append(f"{name}: recorded coordinates do not match canvas geometry")
        for field, label in (
            ("landsea_disagree", "land/sea"),
            ("water_disagree", "lake presence"),
            ("river_disagree", "river presence"),
        ):
            if int(pair[field]):
                breached.append(f"{name}: {pair[field]} {label} disagreements")
        if args.max_flow_ratio is not None and not flow:
            incomplete = True
        flow_text = _fmt(flow["max"]) if flow else "—"
        print(
            f"{name:44} {n:>7} {elev_n:>3}/{n:<3} {_stats_text(surf):>18} "
            f"{_stats_text(bed):>18} "
            f"{counts['landsea']:>3}/{n:<3}{'!' if int(pair['landsea_disagree']) else ' '}"
            f"{counts['water']:>3}/{n:<3} {counts['river']:>3}/{n:<3} {flow_text:>9}"
        )
        if (
            args.max_delta_m is not None
            and isinstance(surf, dict)
            and surf["max_abs_m"] > args.max_delta_m
        ):
            breached.append(f"{name}: |dsurf| max {surf['max_abs_m']:.1f} m > {args.max_delta_m} m")
        if (
            args.max_bed_delta_m is not None
            and isinstance(bed, dict)
            and bed["max_abs_m"] > args.max_bed_delta_m
        ):
            breached.append(
                f"{name}: |dbed| max {bed['max_abs_m']:.1f} m > {args.max_bed_delta_m} m"
            )
        if flow and args.max_flow_ratio is not None and flow["max"] > args.max_flow_ratio:
            breached.append(f"{name}: flow ratio {flow['max']:.2f} > {args.max_flow_ratio}")

    worst = [w for pair in pairs for w in pair["worst"]]
    worst.sort(key=lambda w: -abs(float(w["surface_delta_m"])))
    if worst:
        print("\nlargest elevation disagreements (surface; bed in brackets; ice left/right):")
        for w in worst[:5]:
            bed = w["bed_delta_m"]
            bed_text = "—" if bed is None else f"{float(bed):+.1f}"
            ice = w["ice_m"]
            ice_text = "—" if ice is None else f"{float(ice[0]):.0f}/{float(ice[1]):.0f} m"
            print(
                f"  ({w['lat']:+.4f}, {w['lon']:+.4f})  "
                f"{float(w['surface_delta_m']):+.1f} m  [{bed_text}]  ice {ice_text}"
            )

    landsea = [(pair, point) for pair in pairs for point in pair["landsea_points"]]
    if landsea:
        print("\nland/sea determination disagreements (sea=True/land=False per side):")
        for _pair, point in landsea:
            print(f"  ({point['lat']:+.4f}, {point['lon']:+.4f})  {point['sides']}")

    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"\nreport written to {args.json}")

    if breached:
        print("\nFAILED seam checks:")
        for line in breached:
            print(f"  {line}")
    if incomplete:
        print(
            "\nINCOMPLETE: at least one required seam category has no complete paired samples. "
            "Missing terrain, ice, sea or current hydrology is unverified; a requested flow "
            "ratio also requires a two-sided river-flow sample."
        )
        sys.exit(2)
    if breached:
        sys.exit(1)
    if all(v is None for v in (args.max_delta_m, args.max_bed_delta_m, args.max_flow_ratio)):
        print(
            "\nSampling complete. No numeric thresholds were provided; "
            "this is a measurement report."
        )
    else:
        print("\nAll seam categories fully measured and within the supplied thresholds.")


if __name__ == "__main__":
    main()
