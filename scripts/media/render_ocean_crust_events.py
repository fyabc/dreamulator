"""Render saved ocean-crust birth and removal diagnostics.

Run with --input-dir pointing to a directory containing figure-context.json,
birth-audit-final.json and event-audit-final.json. The renderer uses saved model
geometry and requires no plate reconstruction dependency. Output is PNG.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def frame(center: list[float]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    origin = np.asarray(center)
    east = np.cross([0.0, 0.0, 1.0], origin)
    east /= np.linalg.norm(east)
    north = np.cross(origin, east)
    return origin, east, north


def project(xyz: Any, basis: tuple[np.ndarray, np.ndarray, np.ndarray]) -> np.ndarray:
    points = np.atleast_2d(np.asarray(xyz, dtype=float))
    result = 6371.009 * np.column_stack((points @ basis[1], points @ basis[2]))
    result[points @ basis[0] < 0] = np.nan
    return result


def boundaries(
    ax: Any,
    sections: list[dict[str, Any]],
    basis: tuple[np.ndarray, np.ndarray, np.ndarray],
    target: str,
    current: bool,
) -> None:
    for section in sections:
        color = "#b7bec6"
        if section["kind"] == "gpml:MidOceanRidge":
            color = "#3872b0"
        elif section["kind"] == "gpml:SubductionZone":
            color = "#c84640"
        highlighted = section["feature_id"] == target
        xy = project(section["xyz"], basis)
        ax.plot(
            xy[:, 0],
            xy[:, 1],
            color=color,
            linestyle="-" if current else "--",
            linewidth=1.8 if highlighted else 0.7,
            alpha=1 if highlighted else 0.65,
        )


def marker(
    ax: Any,
    xyz: Any,
    basis: tuple[np.ndarray, np.ndarray, np.ndarray],
    color: str,
    label: str,
    shape: str = "o",
) -> None:
    xy = project(xyz, basis)[0]
    ax.scatter(*xy, color=color, s=60, marker=shape, label=label, zorder=6)


def path(
    ax: Any,
    xyz: Any,
    basis: tuple[np.ndarray, np.ndarray, np.ndarray],
    color: str,
    label: str,
) -> None:
    xy = project(xyz, basis)
    ax.plot(xy[:, 0], xy[:, 1], color=color, linewidth=2, label=label, zorder=5)
    ax.annotate(
        "",
        xy=xy[-1],
        xytext=xy[-2],
        arrowprops={"arrowstyle": "->", "color": color, "lw": 2},
        zorder=5,
    )


def setup(ax: Any, span: float) -> None:
    ax.set(
        xlim=(-span, span),
        ylim=(-span, span),
        xlabel="East of initial point (km)",
        ylabel="North of initial point (km)",
    )
    ax.set_aspect("equal")
    ax.grid(alpha=0.2)
    ax.set_axisbelow(True)


def render_births(cases: list[dict[str, Any]], output: Path) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(13, 11), layout="constrained")
    for i, case in enumerate(cases[:2]):
        row = case["row"]
        basis = frame(row["birth_xyz"])
        title = "Batch initialization artifact" if i == 0 else "Ridge lifecycle changes ownership"
        ax = axes[i, 0]
        setup(ax, 2)
        boundaries(ax, case["before"], basis, row["feature_id"], current=True)
        marker(ax, row["birth_xyz"], basis, "black", "Ridge axis", "x")
        marker(ax, row["offset_birth_xyz"], basis, "#00867a", "Birth probe: 0.111 km")
        ax.set_title(f"{title}: birth at {row['birth_time_ma']:g} Ma", fontsize=11)
        ax.text(
            0.03,
            0.97,
            f"Snapshot and single start: {row['small_birth_owner']}\n"
            f"Batch start: {row['batch_initial_owner']}",
            transform=ax.transAxes,
            va="top",
            fontsize=9,
            bbox={"facecolor": "white", "alpha": 0.9, "edgecolor": "none"},
        )
        ax.legend(loc="lower left", fontsize=8)
        ax = axes[i, 1]
        setup(ax, 115)
        boundaries(ax, case["before"], basis, row["feature_id"], current=False)
        boundaries(ax, case["after"], basis, row["feature_id"], current=True)
        trajectory = row["variants"][1]["trajectory"]
        path(ax, [step["xyz"] for step in trajectory], basis, "#00867a", "Single-point transport")
        path(
            ax,
            [row["offset_birth_xyz"], row["small_end_xyz"]],
            basis,
            "#d28300",
            "Original batch transport",
        )
        marker(ax, trajectory[-1]["xyz"], basis, "#00867a", "Single-point endpoint")
        marker(ax, row["small_end_xyz"], basis, "#d28300", "Batch endpoint", "x")
        ax.set_title(f"Half-step endpoint at {row['seed_time_ma']:g} Ma", fontsize=11)
        ax.text(
            0.03,
            0.97,
            f"Single endpoint: {trajectory[-1]['span_owner']}\n"
            f"Batch endpoint: {row['small_end_owner']}\n"
            f"Old ridge still active: {row['ridge_still_present']}\n"
            f"Single-step refinement difference: {row['endpoint_timestep_difference_km']:.3g} km",
            transform=ax.transAxes,
            va="top",
            fontsize=9,
            bbox={"facecolor": "white", "alpha": 0.9, "edgecolor": "none"},
        )
        ax.legend(loc="lower left", fontsize=8)
    fig.suptitle(
        "Birth assignment, batch initialization and later transfer are separate checks\n"
        "Blue lines mark ridges; dashed lines show the earlier boundary geometry.",
        fontsize=13,
    )
    fig.savefig(output / "birth-cases.png", dpi=170)
    plt.close(fig)


def render_events(cases: list[dict[str, Any]], output: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(13, 6.7), layout="constrained")
    for i, case in enumerate(cases[2:]):
        row = case["row"]
        basis = frame(row["previous_xyz"])
        ax = axes[i]
        setup(ax, 80)
        target = row.get("trench_id", row["boundary_id"])
        boundaries(ax, case["before"], basis, target, current=False)
        boundaries(ax, case["after"], basis, target, current=True)
        path(
            ax,
            [row["previous_xyz"], row["current_xyz"]],
            basis,
            "#00867a",
            "Saved model displacement",
        )
        marker(ax, row["previous_xyz"], basis, "black", "Before removal")
        marker(ax, row["current_xyz"], basis, "#00867a", "Removed endpoint", "x")
        title = "Supported subduction" if i == 0 else "Default removal near a ridge"
        ax.set_title(
            f"{title}: {row['previous_time']:g} to {row['current_time']:g} Ma", fontsize=11
        )
        details = f"{row['previous_owner']} to {row['current_owner']}\n"
        if i == 0:
            details += (
                f"Native trench pair and polarity confirmed\n"
                f"Normal closing: {row['normal_closing_km_myr']:.2f} km/Myr\n"
                f"Previous trench distance: {row['distance_before_km']:.2f} km"
            )
        else:
            details += (
                "No active shared trench for this plate pair\n"
                f"Nearest ridge distance: {row['nearest_boundary_distance_km']:.2f} km\n"
                "This removal does not establish subduction."
            )
        ax.text(
            0.03,
            0.97,
            details,
            transform=ax.transAxes,
            va="top",
            fontsize=9,
            bbox={"facecolor": "white", "alpha": 0.9, "edgecolor": "none"},
        )
        ax.legend(loc="lower left", fontsize=8)
    fig.suptitle(
        "A numerical removal needs a separate physical event audit\n"
        "Red lines mark trenches; blue lines mark ridges; dashed lines show earlier geometry.",
        fontsize=13,
    )
    fig.savefig(output / "removal-cases.png", dpi=170)
    plt.close(fig)


def render_summary(birth: dict[str, Any], events: dict[str, Any], output: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.8), layout="constrained")
    total = birth["total_birth_reference_area_km2"]
    values = [
        100 * birth["baseline_endpoint_mismatch_area_km2"] / total,
        100 * birth["incorrect_snapshot_birth_area_km2"]["large"] / total,
        100 * birth["incorrect_snapshot_birth_area_km2"]["small"] / total,
    ]
    ax = axes[0]
    bars = ax.barh(
        ["Original endpoint check", "Birth check: 1.112 km probe", "Birth check: 0.111 km probe"],
        values,
        color=["#d28300", "#00867a", "#00867a"],
    )
    ax.bar_label(bars, fmt="%.3f%%", padding=4)
    ax.set(xlim=(0, 5.8), xlabel="Share of emitted birth reference area (%)")
    ax.invert_yaxis()
    ax.set_title("The endpoint check overstates birth failure")
    groups = [
        ("Supported subduction", ["supported_subduction"], "#00867a"),
        ("No active shared trench", ["no_active_trench_shared_by_the_two_plates"], "#3872b0"),
        ("Network or topology gap", ["network_or_gap_needs_separate_contract"], "#919ca5"),
        (
            "Other unconfirmed events",
            [
                key
                for key in events["counts"]
                if key
                not in {
                    "supported_subduction",
                    "no_active_trench_shared_by_the_two_plates",
                    "network_or_gap_needs_separate_contract",
                }
            ],
            "#d28300",
        ),
    ]
    ax = axes[1]
    areas = [sum(events["reference_areas_km2"][key] for key in keys) / 1e6 for _, keys, _ in groups]
    bars = ax.barh([name for name, _, _ in groups], areas, color=[color for _, _, color in groups])
    labels = [
        f"{value:.2f}; {sum(events['counts'][key] for key in keys)} events"
        for value, (_, keys, _) in zip(areas, groups, strict=True)
    ]
    ax.bar_label(bars, labels=labels, padding=4, fontsize=9)
    ax.set(xlim=(0, 40), xlabel="Removed reference area (million km²)")
    ax.invert_yaxis()
    ax.set_title("3913 saved removals, classified by evidence")
    fig.suptitle(
        "Reference-area inventories measure sample bookkeeping; "
        "geographic coverage is a separate check.",
        fontsize=12,
    )
    fig.savefig(output / "audit-summary.png", dpi=170)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path)
    args = parser.parse_args()
    output = args.out_dir or args.input_dir
    output.mkdir(parents=True, exist_ok=True)
    cases = read(args.input_dir / "figure-context.json")
    render_births(cases, output)
    render_events(cases, output)
    render_summary(
        read(args.input_dir / "birth-audit-final.json"),
        read(args.input_dir / "event-audit-final.json"),
        output,
    )


if __name__ == "__main__":
    main()
