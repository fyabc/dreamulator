"""Render saved ocean-crust tracer sources, formation fields and removal events.

Run at the repository root with a prepared experiment directory:
    uv run python scripts/media/render_ocean_crust_pilot.py --input-dir <experiment-dir>

The input contains fine-classified.npz, fine.json and coastlines.npz. The renderer
plots samples directly and does not interpolate an unknown global age field.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def lat_lon(xyz: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    return np.degrees(np.arcsin(np.clip(xyz[:, 2], -1, 1))), np.degrees(
        np.arctan2(xyz[:, 1], xyz[:, 0])
    )


def coastline(data: np.ndarray) -> np.ndarray:
    data = data.copy()
    crossings = np.flatnonzero(np.abs(np.diff(data[:, 1])) > 180) + 1
    data[crossings] = np.nan
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path)
    args = parser.parse_args()
    output = args.out_dir or args.input_dir
    output.mkdir(parents=True, exist_ok=True)
    with np.load(args.input_dir / "fine-classified.npz", allow_pickle=False) as saved:
        data = {name: saved[name] for name in saved.files}
    report = json.loads((args.input_dir / "fine.json").read_text(encoding="utf-8"))
    with np.load(args.input_dir / "coastlines.npz", allow_pickle=False) as saved:
        coast = coastline(saved["lat_lon"])
    alive = data["alive"]
    trusted = alive & (data["source"] == "ridge_birth")
    old = alive & (data["source"] == "initial_unknown")
    uncertain = alive & (data["source"] == "ridge_birth_owner_unresolved")
    lat, lon = lat_lon(data["xyz"])

    fig, axes = plt.subplots(2, 2, figsize=(15, 8.7), layout="constrained")
    for ax in axes.flat:
        ax.set(
            xlim=(-180, 180),
            ylim=(-90, 90),
            xlabel="Longitude (degrees)",
            ylabel="Latitude (degrees)",
        )
        ax.grid(alpha=0.15)
        ax.set_axisbelow(True)
    for ax in [axes[0, 0], axes[0, 1], axes[1, 0]]:
        ax.plot(coast[:, 1], coast[:, 0], lw=0.3, color="0.6")
    ax = axes[0, 0]
    for mask, color, label in [
        (old, "0.7", "Initial crust: birth unknown"),
        (trusted, "#138a83", "Ridge birth: first owner matched"),
        (uncertain, "#c87f00", "Ridge birth: first owner unresolved"),
    ]:
        ax.scatter(lon[mask], lat[mask], s=2, color=color, linewidths=0, label=label)
    ax.set_title("Present-day surviving samples by source")
    ax.legend(loc="lower left", fontsize=7, markerscale=3)
    ax = axes[0, 1]
    ages = ax.scatter(
        lon[trusted],
        lat[trusted],
        s=2.5,
        c=data["birth_time_ma"][trusted],
        vmin=0,
        vmax=20,
        cmap="viridis",
        linewidths=0,
    )
    ax.set_title("Age of surviving, matched ridge births")
    fig.colorbar(ages, ax=ax, label="Age (Myr)", shrink=0.75)
    ax = axes[1, 0]
    rate_max = 25 * np.ceil(np.max(data["rate_mm_yr"][trusted]) / 25)
    rates = ax.scatter(
        lon[trusted],
        lat[trusted],
        s=2.5,
        c=data["rate_mm_yr"][trusted],
        vmin=0,
        vmax=rate_max,
        cmap="magma",
        linewidths=0,
    )
    ax.set_title("Full relative spreading speed at birth")
    fig.colorbar(rates, ax=ax, label="Formation speed (mm/yr)", shrink=0.75)
    ax = axes[1, 1]
    for trench, color, label in [
        (True, "#c4413e", "Removed near a trench"),
        (False, "#337eb8", "Removed near another boundary"),
    ]:
        points = np.asarray(
            [
                e["current_xyz"]
                for e in report["detector_events"]
                if (e["nearest_boundary_kind"] == "gpml:SubductionZone") == trench
            ]
        )
        if len(points):
            event_lat, event_lon = lat_lon(points)
            ax.scatter(event_lon, event_lat, s=4, color=color, linewidths=0, label=label)
    ax.set_title("Default removal events at their historical positions")
    ax.legend(loc="lower left", fontsize=7, markerscale=2)
    fig.suptitle("Müller 2019 topology pilot: 20 Ma to present; samples, not a global age grid")
    fig.savefig(output / "topology-pilot.png", dpi=150)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 4.5), layout="constrained")
    kinds = ["active", "retired_near_trench", "retired_other_boundary", "retired_unattributed"]
    labels = ["Active", "Removed near trench", "Removed elsewhere", "Unattributed removal"]
    colors = ["#138a83", "#c4413e", "#337eb8", "#b78e20"]
    sources = ["initial_unknown", "ridge_birth", "ridge_birth_owner_unresolved"]
    bottom = np.zeros(len(sources))
    for kind, label, color in zip(kinds, labels, colors, strict=True):
        values = np.asarray(
            [
                data["reference_area_km2"][
                    (data["source"] == source) & (data["disposition"] == kind)
                ].sum()
                / 1e6
                for source in sources
            ]
        )
        ax.bar(sources, values, bottom=bottom, color=color, label=label)
        bottom += values
    ax.set_xticks(
        range(3), ["Initial birth unknown", "Matched ridge births", "First owner unresolved"]
    )
    ax.set(
        ylabel="Birth reference-area weight (million km²)",
        title="Source inventory: active and removed records are counted separately",
    )
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.15)
    ax.set_axisbelow(True)
    fig.savefig(output / "source-inventory.png", dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    main()
