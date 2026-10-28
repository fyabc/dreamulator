"""Plot frozen incoming-stage paths for finite mountain-source diagnostics."""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--radius-km", type=float, required=True)
    args = parser.parse_args()
    if args.radius_km <= 0 or not np.isfinite(args.radius_km):
        parser.error("radius must be finite and positive")
    cases = (
        ("contour-failure-path", "Open endpoint"),
        ("endcap-contour-failure-path", "Competing finite arcs"),
    )
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6), constrained_layout=True)
    with np.load(args.archive) as saved:
        for axis, (key, title) in zip(axes, cases, strict=True):
            xyz = saved[key + "__xyz"]
            separation = np.linalg.norm(np.diff(xyz, axis=0), axis=1)
            distance = np.concatenate([[0], np.cumsum(separation)]) * args.radius_km * 1000
            distance -= distance[len(distance) // 2]
            for suffix, label, color in (
                ("previous_m", "Accepted source", "#555555"),
                ("saved_m", "Saved endpoint diagnostic", "#cd7845"),
                ("candidate_m", "Continuous finite-arc envelope", "#188b89"),
            ):
                axis.plot(distance, saved[key + "__" + suffix], label=label, color=color, lw=1.6)
            axis.axhline(0, color="#999999", lw=0.8, linestyle="--")
            axis.set(
                title=title, xlabel="Distance along saved path (m)", ylabel="Incoming elevation (m)"
            )
            axis.grid(alpha=0.18)
            axis.legend(fontsize=8)
    fig.suptitle("Mountain source before the coastal stage", fontsize=12)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output, dpi=220)
    plt.close(fig)


if __name__ == "__main__":
    main()
