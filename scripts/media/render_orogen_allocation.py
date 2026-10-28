"""Plot finite-source volume allocations and their frozen cross-axis sections."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report_dir", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    results = json.loads((args.report_dir / "results.json").read_text(encoding="utf-8"))
    covered_budget = bool(results.get("source_covered_budget_closed", False))
    figure, axes = plt.subplots(2, 2, figsize=(12.8, 8.5), constrained_layout=True)
    with np.load(args.report_dir / "sections.npz") as samples:
        for column, name in enumerate(("collision:seg_064", "collision:seg_068")):
            row = results["fine_verification"]["sources"][name]
            bars = (
                np.array(
                    [
                        row["accepted_volume_km3"],
                        row["unallocated_volume_km3"],
                        row["unmasked_volume_km3"],
                        row["crust_covered_volume_km3"],
                    ]
                )
                / 1e6
            )
            axis = axes[0, column]
            axis.bar(np.arange(4), bars, color=["#666666", "#ca7f46", "#218883", "#84b5a4"])
            axis.set_xticks(
                np.arange(4), ["Accepted", "Finite", "Allocated", "Allocated\ncrust-covered"]
            )
            axis.axhline(
                row["target_volume_km3"] / 1e6,
                color="#333333",
                ls="--",
                label=(
                    "Fixed crust-covered source budget"
                    if covered_budget
                    else "Fixed nominal axis budget"
                ),
            )
            for index, value in enumerate(bars):
                axis.text(index, value + 0.025, f"{value:.3f}", ha="center", fontsize=9)
            title = (
                f"{name.removeprefix('collision:')}: section allocation = {row['allocation']:.4f}"
            )
            axis.set(
                title=title,
                ylabel="Continuous elevation volume (million km³)",
                ylim=(0, bars.max() * 1.15),
            )
            axis.legend(fontsize=8)
            section = axes[1, column]
            distance = samples[name + "__distance_km"]
            for suffix, label, color in (
                ("accepted_m", "Accepted source", "#666666"),
                ("finite_m", "Finite envelope", "#ca7f46"),
                ("allocated_m", "Allocated finite envelope", "#218883"),
            ):
                section.plot(distance, samples[name + "__" + suffix], color=color, label=label)
            section.set(
                title="Across the largest-input arc midpoint",
                xlabel="Signed cross-axis distance (km)",
                ylabel="Unmasked source relief (m)",
            )
            section.legend(fontsize=8)
    for axis in axes.ravel():
        axis.grid(axis="y", alpha=0.18)
        axis.set_axisbelow(True)
    figure.suptitle(
        (
            "Finite-geometry allocation on crust-covered area; production adoption remains separate"
            if covered_budget
            else (
                "Finite-geometry budget trial; "
                "local transport and production adoption remain separate"
            )
        ),
        fontsize=12,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(args.output, dpi=220)
    plt.close(figure)


if __name__ == "__main__":
    main()
