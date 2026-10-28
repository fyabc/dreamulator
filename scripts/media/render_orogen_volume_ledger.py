"""Plot a native mountain-volume ledger and paired geological-stage responses."""

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
    volume = json.loads((args.report_dir / "volume-results.json").read_text())
    stages = json.loads((args.report_dir / "stage-analysis.json").read_text())
    nominal = volume["nominal_axis"]["collision:seg_068"]["axis_extrusion_volume_km3"]
    native = stages["declared_native_cell_mean_source_volumes_km3"]
    comparison = stages["comparisons"]["accepted__finite"]["stages"]
    names = ("Native engine", "Accepted source", "Finite-arc candidate")
    values = [
        native[key]["orogen.segment.seg_068"] / 1e6 for key in ("canonical", "accepted", "finite")
    ]
    sequence = (
        ("active_relief_m", "Mountain"),
        ("apply_orogen_cap_1__after_m", "Height cap"),
        ("continental_shelf_1__after_m", "Shelf"),
        ("coastal_plain_1__after_m", "Coast"),
        ("_clamp_deep_ocean_floors_1__before_m", "Forearc"),
        ("final_elevation_m", "Author pins"),
    )
    difference = [comparison[key]["signed_volume_difference_km3"] / 1e3 for key, _ in sequence]
    fig, axes = plt.subplots(1, 2, figsize=(12.2, 4.8), constrained_layout=True)
    axes[0].bar(names, values, color=["#666666", "#508a9b", "#c47746"])
    axes[0].axhline(nominal / 1e6, color="#333333", ls="--", label="Nominal axis extrusion")
    axes[0].set(title="seg_068: declared native-cell source volume", ylabel="Million km³")
    axes[0].legend(fontsize=8)
    for index, value in enumerate(values):
        axes[0].text(index, value + 0.04, f"{value:.3f}", ha="center", fontsize=9)
    axes[0].set_ylim(0, max(values) * 1.17)
    axes[1].bar(np.arange(len(sequence)), difference, color="#508a9b")
    axes[1].set_xticks(np.arange(len(sequence)), [label for _, label in sequence], rotation=20)
    axes[1].set(
        title="Candidate minus accepted: actual stage response",
        ylabel="Net elevation-volume difference (thousand km³)",
    )
    for axis in axes:
        axis.grid(axis="y", alpha=0.18)
        axis.set_axisbelow(True)
    fig.suptitle(
        "Fixed tectonic inputs; numerical and physical adoption assessed separately", fontsize=11
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output, dpi=220)
    plt.close(fig)


if __name__ == "__main__":
    main()
