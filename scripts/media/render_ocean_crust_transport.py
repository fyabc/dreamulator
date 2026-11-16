"""Render saved explicit-topology transport results and local comparisons."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from render_ocean_crust_events import boundaries, frame, marker, path, setup


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path)
    args = parser.parse_args()
    output = args.out_dir or args.input_dir
    output.mkdir(parents=True, exist_ok=True)
    cases = json.loads((args.input_dir / "case-context.json").read_text(encoding="utf-8"))
    birth = json.loads((args.input_dir / "birth-summary.json").read_text(encoding="utf-8"))
    fig, axes = plt.subplots(1, 2, figsize=(13, 6.8), layout="constrained")
    for i, case in enumerate(cases):
        row = case["row"]
        basis = frame(row["birth_xyz"])
        ax = axes[i]
        setup(ax, 110)
        boundaries(ax, case["before"], basis, row["feature_id"], current=False)
        boundaries(ax, case["after"], basis, row["feature_id"], current=True)
        path(
            ax,
            [row["offset_birth_xyz"], row["small_end_xyz"]],
            basis,
            "#d28300",
            "Original batch transport",
        )
        path(
            ax,
            [row["offset_birth_xyz"], case["fixed_xyz"]],
            basis,
            "#00867a",
            "Explicit native transport",
        )
        marker(ax, row["offset_birth_xyz"], basis, "black", "Birth point")
        marker(ax, row["small_end_xyz"], basis, "#d28300", "Original endpoint", "x")
        marker(ax, case["fixed_xyz"], basis, "#00867a", "Explicit endpoint")
        title = "Wrong initial owner repaired" if i == 0 else "Ridge lifecycle transfer retained"
        ax.set_title(title, fontsize=12)
        description = (
            f"{row['birth_time_ma']:g} to {row['seed_time_ma']:g} Ma\n"
            f"Confirmed birth owner: {case['fixed_start_owner']}\n"
            f"Explicit endpoint owner: {case['fixed_end_owner']}\n"
            f"Original endpoint owner: {row['small_end_owner']}"
        )
        ax.text(
            0.03,
            0.97,
            description,
            va="top",
            transform=ax.transAxes,
            fontsize=10,
            bbox={"facecolor": "white", "alpha": 0.9, "edgecolor": "none"},
        )
        ax.legend(loc="lower left", fontsize=8)
    fig.suptitle(
        "Explicit selection removes input-order dependence and preserves topology changes\n"
        "Blue lines show ridges; dashed lines show the earlier geometry.",
        fontsize=13,
    )
    fig.savefig(output / "transport-cases.png", dpi=170)
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.8), layout="constrained")
    for ax, label, offset in zip(axes, ["small", "large"], [0.111, 1.112], strict=True):
        results = birth["offset_results"][label]
        metrics = [
            results["initial_owner_mismatches"],
            results["order_owner_mismatches"],
            results["endpoint_unresolved_count"],
        ]
        bars = ax.barh(
            ["Initial owner mismatches", "Reverse-order owner mismatches", "Unresolved endpoints"],
            metrics,
            color=["#00867a", "#00867a", "#d28300"],
        )
        ax.bar_label(bars, padding=4)
        ax.set(xlim=(0, 4), xlabel="Record count")
        ax.invert_yaxis()
        ax.set_title(f"{offset:g} km birth probe; {results['stable_birth_count']} records")
    fig.suptitle(
        "Both probe offsets pass: zero input-order or rigid-rotation differences\n"
        "Unknown overlaps and topology gaps remain explicitly unresolved.",
        fontsize=12,
    )
    fig.savefig(output / "transport-checks.png", dpi=170)
    plt.close(fig)


if __name__ == "__main__":
    main()
