#!/usr/bin/env python3
"""Measure grid alignment in exported river segments without rebuilding hydrology.

The input is rivers.line.npy (N, 2, 2), in local Cartesian kilometres. Bearings
are axial: reversing a segment leaves its orientation unchanged. Statistics are
weighted by length so subdivision and smoothing do not inflate short segments.
Inputs are memory mapped and processed in bounded batches. --plane-control also
passes rotated analytical slopes through the existing D8 and river export code.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


@dataclass
class DirectionStats:
    """Additive length-weighted orientation statistics, in kilometres and degrees."""

    count: int = 0
    length_km: float = 0.0
    aligned_km: float = 0.0
    cosine_km: float = 0.0
    sine_km: float = 0.0
    histogram_km: np.ndarray = field(default_factory=lambda: np.zeros(180))

    def add(self, vectors: np.ndarray) -> None:
        length = np.linalg.norm(vectors, axis=1)
        valid = np.isfinite(vectors).all(axis=1) & (length > 0)
        length = length[valid]
        theta = np.arctan2(vectors[valid, 1], vectors[valid, 0])
        angle = np.degrees(theta) % 180.0
        distance = np.abs((angle + 22.5) % 45.0 - 22.5)
        self.count += int(length.size)
        self.length_km += float(length.sum())
        self.aligned_km += float(length[distance <= 5.0].sum())
        self.cosine_km += float(np.dot(length, np.cos(8 * theta)))
        self.sine_km += float(np.dot(length, np.sin(8 * theta)))
        # Centre the bins on whole degrees, including zero at the wrap-around.
        self.histogram_km += np.bincount(
            np.floor((angle + 0.5) % 180).astype(int), weights=length, minlength=180
        )

    def report(self) -> dict[str, object]:
        if not self.length_km:
            return {"segments": self.count, "length_km": 0.0, "status": "no_valid_segments"}
        cosine = self.cosine_km / self.length_km
        sine = self.sine_km / self.length_km
        return {
            "status": "measured",
            "segments": self.count,
            "length_km": self.length_km,
            "within_5deg_of_grid_percent": 100 * self.aligned_km / self.length_km,
            "uniform_orientation_percent": 100 * 10 / 45,
            "cos8": cosine,
            "sin8": sine,
            "harmonic8_magnitude": float(np.hypot(cosine, sine)),
            "histogram_1deg_length_km": self.histogram_km.tolist(),
        }


def summarize(path: Path, *, batch_size: int = 131072) -> dict[str, object]:
    """Scan a whole vector product with batch-bounded working memory."""
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    lines = np.load(path, mmap_mode="r", allow_pickle=False)
    if lines.ndim != 3 or lines.shape[1:] != (2, 2):
        raise ValueError("Expected rivers.line.npy with shape (N, 2, 2)")
    meta_path = path.with_name("rivers.meta.json")
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    pitch = meta.get("km_per_px")
    groups = {"all": DirectionStats(), "at_least_1km": DirectionStats()}
    if pitch is not None:
        if not np.isfinite(pitch) or pitch <= 0:
            raise ValueError("km_per_px must be finite and positive")
        groups.update(subpixel=DirectionStats(), at_least_4pixels=DirectionStats())
    invalid = 0
    degenerate = 0
    for start in range(0, len(lines), batch_size):
        block = np.asarray(lines[start : start + batch_size], dtype=np.float64)
        valid = np.isfinite(block).all(axis=(1, 2))
        invalid += int((~valid).sum())
        vectors = block[valid, 1] - block[valid, 0]
        length = np.linalg.norm(vectors, axis=1)
        degenerate += int((length == 0).sum())
        groups["all"].add(vectors)
        groups["at_least_1km"].add(vectors[length >= 1])
        if pitch is not None:
            groups["subpixel"].add(vectors[length < pitch])
            groups["at_least_4pixels"].add(vectors[length >= 4 * pitch])
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {
        "file": str(path.resolve()),
        "sha256": digest,
        "input_segments": int(len(lines)),
        "nonfinite_segments": invalid,
        "zero_length_segments": degenerate,
        "hydrology_metadata": meta,
        "groups": {name: stats.report() for name, stats in groups.items()},
    }


def plane_control() -> list[dict[str, float]]:
    """Measure directional error against a known gradient, before and after export."""
    from dreamulator.map.prog_erosion import ChannelGraph, river_segments_from_graph
    from dreamulator.media.canvas_hydrology import CanvasTiles, ChunkGrid, flow_directions

    n = 17
    yy, xx = np.mgrid[:n, :n]
    rows = []
    # Avoid the exact bisectors: equal D8 slopes can alternate directions
    # because of floating-point round-off, obscuring the quantization control.
    for angle in np.arange(0.25, 180.0, 2.5):
        theta = np.radians(angle)
        # Array rows run southward; exported y runs northward.
        dem = 1000.0 - (xx * np.cos(theta) - yy * np.sin(theta))
        tiles = CanvasTiles({(0, 0): dem}, ChunkGrid(1, 1, n), {(0, 0): dem})
        receiver = flow_directions(tiles)[(0, 0)].ravel()
        # Trace one interior streamline; avoid boundary-selected directions.
        cells = []
        c = (n // 2) * n + n // 2
        while 1 <= c // n < n - 1 and 1 <= c % n < n - 1:
            cells.append(c)
            c = int(receiver[c])
            if c < 0:
                break
        if c >= 0:
            cells.append(c)
        order = np.sort(cells)
        route = receiver[order].copy()
        route[~np.isin(route, order)] = -1
        graph = ChannelGraph(
            cells=order,
            is_river=np.ones(len(order), dtype=bool),
            is_lake=np.zeros(len(order), dtype=bool),
            receiver=route,
            acc=np.ones(len(order)),
            month=np.full(len(order), 12, dtype=np.uint8),
            descend=np.full(len(order), -1),
            width=n,
            rows=n,
            km_per_px=1.0,
        )
        line, _, _ = river_segments_from_graph(graph)
        vector = line[-1, 1] - line[0, 0]
        exported = float(np.degrees(np.arctan2(vector[1], vector[0])) % 180)
        raw0, raw1 = cells[:2]
        raw = float(np.degrees(np.arctan2(raw0 // n - raw1 // n, raw1 % n - raw0 % n)) % 180)
        rows.append(
            {
                "gradient_angle_deg": float(angle),
                "raw_d8_angle_deg": raw,
                "exported_angle_deg": exported,
                "raw_error_deg": abs((raw - angle + 90) % 180 - 90),
                "exported_error_deg": abs((exported - angle + 90) % 180 - 90),
            }
        )
    return rows


def plot(report: dict[str, object], out: Path) -> None:
    """Write a length-weighted orientation figure for the measured products."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    products = report["products"]
    fig, axes = plt.subplots(len(products), 1, figsize=(11, 3 * len(products)), squeeze=False)
    for axis, product in zip(axes[:, 0], products, strict=True):
        groups = product["groups"]
        for key, label in (("all", "All final segments"), ("at_least_4pixels", ">= 4 pixels")):
            row = groups.get(key, {})
            if row.get("status") != "measured":
                continue
            hist = np.asarray(row["histogram_1deg_length_km"])
            axis.plot(np.arange(180), hist / hist.sum() * 100, label=label)
        for bearing in (0, 45, 90, 135):
            axis.axvline(bearing, color="gray", alpha=0.35)
        axis.set(
            title=Path(product["file"]).parent.parent.name,
            xlabel="Local axial bearing (degrees, east = 0)",
            ylabel="River length (%)",
        )
        axis.legend()
    fig.tight_layout()
    fig.savefig(out / "orientation-histograms.png", dpi=160)
    plt.close(fig)
    control = report.get("plane_control")
    if control:
        fig, axis = plt.subplots(figsize=(9, 4))
        axis.plot(
            [r["gradient_angle_deg"] for r in control],
            [r["exported_angle_deg"] for r in control],
            label="Existing D8 + export",
        )
        axis.plot([0, 180], [0, 180], linestyle="--", label="Analytical downslope direction")
        axis.set(xlabel="Analytical gradient (degrees)", ylabel="Exported orientation (degrees)")
        axis.legend()
        fig.tight_layout()
        fig.savefig(out / "rotated-plane-control.png", dpi=160)
        plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lines", nargs="+", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=131072)
    parser.add_argument("--plane-control", action="store_true")
    parser.add_argument("--plot", action="store_true")
    args = parser.parse_args()
    report = {
        "method": "axial bearings in canvas Cartesian coordinates; river-length weighting",
        "grid_window_halfwidth_deg": 5.0,
        "interpretation": (
            "A uniform orientation distribution has 22.222% of length within these windows. "
            "Positive cos8 measures alignment to multiples of 45 degrees. Natural terrain "
            "can also have preferred orientations; the analytical plane is the causal control."
        ),
        "products": [summarize(path, batch_size=args.batch_size) for path in args.lines],
    }
    if args.plane_control:
        report["plane_control"] = plane_control()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    if args.plot:
        plot(report, args.out_dir)
    for product in report["products"]:
        summary = {
            key: value
            for key, value in product["groups"]["all"].items()
            if key != "histogram_1deg_length_km"
        }
        print(product["file"], json.dumps(summary))


if __name__ == "__main__":
    main()
