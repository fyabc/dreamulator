"""Evaluate one Manning depth closure against independently held-out river sections."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import NullFormatter

from scripts.geology.channel_geometry import fit_mean_channel_geometry, mean_channel_geometry
from scripts.geology.manning_channel_depth import fit_manning_resistance, manning_mean_depth


def metrics(observed: np.ndarray, predicted: np.ndarray) -> dict[str, Any]:
    ratio = predicted / observed
    error = float(np.median(np.abs(ratio - 1)))
    within = float(np.mean((ratio >= 0.5) & (ratio <= 2)))
    return {
        "stations": int(observed.size),
        "median_absolute_relative_error": error,
        "within_factor_two_fraction": within,
        "rough_estimate_pass": error <= 0.5 and within >= 0.8,
    }


def evaluate(observations: Path, slopes: Path, out: Path) -> dict[str, Any]:
    with observations.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    with slopes.open(encoding="utf-8", newline="") as stream:
        slope_rows = list(csv.DictReader(stream))
    by_station = {r["station"]: r for r in slope_rows}
    if len(by_station) != len(slope_rows) or set(by_station) != {r["station"] for r in rows}:
        raise ValueError("Each observation needs exactly one slope or documented exclusion.")
    q = np.array([float(r["discharge_cfs"]) * 0.3048**3 for r in rows])
    width = np.array([float(r["width_ft"]) * 0.3048 for r in rows])
    depth = np.array([float(r["mean_depth_ft"]) * 0.3048 for r in rows])
    train_all = np.array([r["use"] == "calibration" for r in rows])
    test_all = np.array([r["use"] == "validation" for r in rows])
    eligible = np.array([by_station[r["station"]]["status"] == "eligible" for r in rows])
    slope = np.array([float(by_station[r["station"]]["slope_m_m"] or "nan") for r in rows])
    train, test = train_all & eligible, test_all & eligible
    if train.sum() < 2 or test.sum() < 2 or np.any(eligible & (slope <= 1e-5 + 1e-12)):
        raise ValueError("Usable independent slope observations are required for both groups.")
    accepted_width = fit_mean_channel_geometry(q[train_all], width[train_all], depth[train_all])
    matched_baseline = fit_mean_channel_geometry(q[train], width[train], depth[train])
    original = mean_channel_geometry(q, accepted_width)
    matched = mean_channel_geometry(q, matched_baseline)
    # Preserve the previously accepted width calibration. Only the resistance
    # and the matched Q-only depth baseline use the 20 sections with usable slope.
    resistance = fit_manning_resistance(
        q[train], original.width_m[train], depth[train], slope[train]
    )
    predicted = np.full(q.shape, np.nan)
    predicted[eligible] = manning_mean_depth(
        q[eligible], original.width_m[eligible], slope[eligible], resistance
    )
    reconstructed = (
        original.width_m[eligible]
        * predicted[eligible] ** (5 / 3)
        * np.sqrt(slope[eligible])
        / resistance
    )
    residual = float(np.max(np.abs(reconstructed / q[eligible] - 1)))
    assert residual < 1e-12
    extrapolated = eligible & (
        (q < q[train].min())
        | (q > q[train].max())
        | (slope < slope[train].min())
        | (slope > slope[train].max())
    )
    groups = {}
    for use, mask in (("calibration", train), ("validation", test)):
        groups[use] = {
            "original_q_only": metrics(depth[mask], original.mean_depth_m[mask]),
            "matched_training_q_only": metrics(depth[mask], matched.mean_depth_m[mask]),
            "manning": metrics(depth[mask], predicted[mask]),
        }
    evidence = []
    for i, r in enumerate(rows):
        s = by_station[r["station"]]
        evidence.append(
            {
                "station": r["station"],
                "use": r["use"],
                "usgs_site_no": s["usgs_site_no"],
                "status": s["status"],
                "discharge_m3s": float(q[i]),
                "observed_width_m": float(width[i]),
                "observed_mean_depth_m": float(depth[i]),
                "predicted_width_m": float(original.width_m[i]),
                "slope_m_m": None if not np.isfinite(slope[i]) else float(slope[i]),
                "original_q_only_depth_m": float(original.mean_depth_m[i]),
                "matched_q_only_depth_m": float(matched.mean_depth_m[i]),
                "manning_depth_m": None if not eligible[i] else float(predicted[i]),
                "outside_training_q_or_slope_range": bool(extrapolated[i]),
            }
        )
    report = {
        "acceptance_rule": "Median absolute relative error <= 50%; at least 80% within factor two.",
        "groups": groups,
        "original_all23_validation": metrics(depth[test_all], original.mean_depth_m[test_all]),
        "calibration": {
            "manning_n_s_m13": resistance,
            "depth_training_stations": int(train.sum()),
            "width_training_stations": int(train_all.sum()),
            "discharge_range_m3s": [float(q[train].min()), float(q[train].max())],
            "slope_range_m_m": [float(slope[train].min()), float(slope[train].max())],
        },
        "excluded_natural_sections": [
            by_station[r["station"]]
            for r in rows
            if r["use"] != "excluded" and by_station[r["station"]]["status"] != "eligible"
        ],
        "wide_channel_check": {
            "min_observed_width_depth_ratio": float(np.min(width[eligible] / depth[eligible])),
            "min_predicted_width_depth_ratio": float(
                np.min(original.width_m[eligible] / predicted[eligible])
            ),
        },
        "manning_equation_relative_residual_max": residual,
        "heldout_extrapolated_stations": int(np.count_nonzero(test & extrapolated)),
        "heldout_outside_factor_two": [
            evidence[i]
            for i in np.flatnonzero(test)
            if predicted[i] / depth[i] < 0.5 or predicted[i] / depth[i] > 2
        ],
        "depth_validation_state": "rough_estimate_pass"
        if groups["validation"]["manning"]["rough_estimate_pass"]
        else "failed",
        "terrain_carving_state": "not_implemented",
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with (out / "station-results.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(evidence[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(evidence)
    plot_comparison(depth, matched.mean_depth_m, predicted, train, test, out)
    plot_examples(evidence, out)
    return report


def plot_comparison(
    depth: np.ndarray,
    baseline: np.ndarray,
    predicted: np.ndarray,
    train: np.ndarray,
    test: np.ndarray,
    out: Path,
) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.7), layout="constrained")
    limits = np.geomspace(0.07, 8, 100)
    ticks = [0.1, 0.2, 0.5, 1, 2, 5]
    for ax, values, title in zip(
        axes,
        (baseline, predicted),
        (
            f"Q only: same {int(train.sum())} calibration sections",
            "Manning: flow, predicted width and slope",
        ),
        strict=True,
    ):
        ax.fill_between(limits, limits / 2, limits * 2, color="#eeeeee", zorder=0)
        ax.plot(limits, limits, color="black", lw=1)
        for mask, label, color in (
            (train, f"Calibration (n={int(train.sum())})", "#248bcc"),
            (test, f"Held out (n={int(test.sum())})", "#e57c27"),
        ):
            ax.scatter(depth[mask], values[mask], label=label, color=color, s=24, alpha=0.9)
        ax.set(
            xscale="log",
            yscale="log",
            xlim=(0.07, 8),
            ylim=(0.07, 8),
            xlabel="Observed mean depth (m)",
            ylabel="Estimated mean depth (m)",
            title=title,
        )
        ax.set_xticks(ticks, [f"{v:g}" for v in ticks])
        ax.set_yticks(ticks, [f"{v:g}" for v in ticks])
        ax.xaxis.set_minor_formatter(NullFormatter())
        ax.yaxis.set_minor_formatter(NullFormatter())
        ax.grid(alpha=0.25)
        ax.legend(fontsize=8)
    fig.savefig(out / "depth-comparison.png", dpi=180)
    plt.close(fig)


def plot_examples(evidence: list[dict[str, Any]], out: Path) -> None:
    names = ["Wind near Burris", "Yellowstone at Corwin Springs", "Bighorn at Thermopolis"]
    examples = [next(r for r in evidence if r["station"] == name) for name in names]
    fig, ax = plt.subplots(figsize=(9, 4), layout="constrained")
    x = np.arange(len(examples))
    for shift, key, label, color in (
        (-0.25, "observed_mean_depth_m", "Observed", "#666666"),
        (0, "matched_q_only_depth_m", "Q only: same calibration group", "#e57c27"),
        (0.25, "manning_depth_m", "Manning", "#248bcc"),
    ):
        bars = ax.bar(x + shift, [r[key] for r in examples], width=0.25, label=label, color=color)
        ax.bar_label(bars, fmt="%.2f", fontsize=8, padding=3)
    ax.set_xticks(
        x,
        [
            "Wind River\nat Burris",
            "Yellowstone River\nat Corwin Springs",
            "Bighorn River\nat Thermopolis",
        ],
    )
    ax.set(
        ylabel="Mean depth (m)",
        ylim=(0, 3.7),
        title="Held-out examples, including the largest remaining error",
    )
    ax.legend(fontsize=8)
    fig.savefig(out / "depth-examples.png", dpi=180)
    plt.close(fig)


def main() -> None:
    data = Path(__file__).parents[1] / "geology/data"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--observations", type=Path, default=data / "usgs_mean_channel_geometry.csv"
    )
    parser.add_argument("--slopes", type=Path, default=data / "usgs_mean_channel_slopes.csv")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = evaluate(args.observations, args.slopes, args.out)
    paths = [
        args.observations,
        args.slopes,
        Path(__file__),
        data.parent / "manning_channel_depth.py",
    ]
    manifest = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["groups"], indent=2))


if __name__ == "__main__":
    main()
