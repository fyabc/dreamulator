#!/usr/bin/env python3
"""Bounded local D8/D-infinity experiment with explicit sources and sink budgets.

Run as a module from the repository: python -m scripts.media.compare_dinf_routing
--out <exports directory> --pack name=/path/to/region-pack [--pack ...].
The local reference uses whole-grid elevation sorting for accumulation. Halo
direction equality and both cross-seam transfers are checked independently;
an external-memory split-flow solver and final river lines are future work.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import label

from scripts.media.dinf_local import (
    Routing,
    accumulate,
    directions,
    displacement_angle,
    tiled_directions,
)


def plane(shape: tuple[int, int], angle_deg: float) -> np.ndarray:
    row, col = np.indices(shape)
    theta = np.radians(angle_deg)
    return row * np.sin(theta) - col * np.cos(theta)


def frame(shape: tuple[int, int]) -> np.ndarray:
    mask = np.zeros(shape, dtype=bool)
    mask[[0, -1], :] = True
    mask[:, [0, -1]] = True
    return mask


def error_deg(actual: np.ndarray, expected: np.ndarray | float) -> np.ndarray:
    return np.abs(np.degrees(np.angle(np.exp(1j * (actual - expected)))))


def budget(route: Routing, accumulated: np.ndarray, source: np.ndarray) -> dict[str, float]:
    terminal = route.proportion.sum(axis=2) == 0
    incoming, outgoing = float(source.sum()), float(accumulated[terminal].sum())
    residual = abs(outgoing - incoming) / max(incoming, np.finfo(float).tiny)
    if residual > 1e-10:
        raise ValueError(f"sink budget failed: {residual}")
    return {"source_total": incoming, "sink_total": outgoing, "relative_residual": residual}


def analytical_controls(out: Path) -> dict:
    import matplotlib.pyplot as plt

    rows = []
    for angle in np.arange(0.25, 180, 2.5):
        h = plane((33, 33), angle)
        a, b = directions(h, 1, method="d8"), directions(h, 1)
        expected = np.radians(angle)
        rows.append(
            {
                "input_deg": float(angle),
                "d8_error_deg": float(error_deg(a.angle_rad[16, 16], expected)),
                "dinf_error_deg": float(error_deg(b.angle_rad[16, 16], expected)),
                "dinf_displacement_error_deg": float(
                    error_deg(displacement_angle(b)[16, 16], expected)
                ),
            }
        )
    if max(r["dinf_error_deg"] for r in rows) > 1e-7:
        raise ValueError("analytical continuous direction gate failed")
    fig, ax = plt.subplots(figsize=(10, 4.5))
    for key, title in [
        ("d8_error_deg", "D8 direction"),
        ("dinf_error_deg", "D-infinity continuous direction"),
        ("dinf_displacement_error_deg", "D-infinity water displacement"),
    ]:
        ax.plot([r["input_deg"] for r in rows], [r[key] for r in rows], label=title)
    ax.set(xlabel="Analytical downslope azimuth (deg)", ylabel="Absolute direction error (deg)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out / "plane-direction.png", dpi=170)
    plt.close(fig)
    row, col = np.indices((129, 129))
    radius = np.hypot(row - 64, col - 64)
    cone = radius
    stop = frame(cone.shape) | (radius <= 1)
    expected = np.arctan2(row - 64, 64 - col) % (2 * np.pi)
    evaluate = (radius >= 16) & ~stop
    source = (~stop).astype(float)
    cone_results = {}
    for method in ("d8", "dinf"):
        route = directions(cone, 1, stop, method=method)
        accumulated = accumulate(cone, route, source)
        cone_results[method] = {
            "direction_mean_error_deg": float(
                error_deg(route.angle_rad[evaluate], expected[evaluate]).mean()
            ),
            "displacement_mean_error_deg": float(
                error_deg(displacement_angle(route)[evaluate], expected[evaluate]).mean()
            ),
            **budget(route, accumulated, source),
            "central_sink_total": float(accumulated[radius <= 1].sum()),
        }
    return {
        "planes": rows,
        "cone": cone_results,
        "cone_evaluation": "r >= 16 pixels; outer frame excluded; center r <= 1 absorbs",
    }


def impulse_control(out: Path) -> dict:
    import matplotlib.pyplot as plt
    from matplotlib.colors import LogNorm

    h = plane((129, 129), 30)
    stop = frame(h.shape)
    source = np.zeros_like(h)
    source[96, 16] = 1
    fig, axes = plt.subplots(1, 2, figsize=(10, 5), sharex=True, sharey=True)
    report = {}
    for ax, method in zip(axes, ("d8", "dinf"), strict=True):
        route = directions(h, 1, stop, method=method)
        accumulated = accumulate(h, route, source)
        image = ax.imshow(
            np.ma.masked_where(accumulated < 1e-4, accumulated),
            cmap="viridis",
            norm=LogNorm(vmin=1e-4, vmax=1),
        )
        ax.plot(
            [16, 128],
            [96, 96 - 112 * np.tan(np.radians(30))],
            "r--",
            linewidth=1.3,
            label="Analytical streamline",
        )
        ax.set(title=f"{method.upper()} impulse transfer", xlabel="Column (pixels)")
        ax.legend(loc="upper left")
        sinks = accumulated * stop
        row, col = np.indices(h.shape)
        x, y = float(((col - 16) * sinks).sum()), float(((96 - row) * sinks).sum())
        report[method] = {
            **budget(route, accumulated, source),
            "exit_centroid_azimuth_deg": float(np.degrees(np.arctan2(y, x))),
            "receiving_frame_cells": int(np.count_nonzero(sinks > 1e-10)),
        }
    axes[0].set_ylabel("Row (pixels; southward)")
    fig.colorbar(image, ax=axes, shrink=0.65, label="Fraction of unit impulse passing cell")
    fig.savefig(out / "plane-impulse.png", dpi=170, bbox_inches="tight")
    plt.close(fig)
    return report


def lake_control() -> dict:
    """Hold two lake footprints/spills fixed and route each release on both edges."""
    from dreamulator.map.prog_erosion import monthly_outflow_cascade

    h = plane((65, 49), 22.5)
    labels = np.zeros(h.shape, dtype=np.int32)
    labels[:, 14], labels[:, 26] = 1, 2
    stop = frame(h.shape) | (labels > 0)
    route = directions(h, 1, stop)
    source = np.zeros_like(h)
    source[50, 5], source[50, 18] = 100, 20
    accumulated = accumulate(h, route, source)
    initial = [float(accumulated[labels == lake].sum()) for lake in (1, 2)]
    np.testing.assert_allclose(initial, [100, 20], atol=1e-10)
    released1 = np.zeros_like(h)
    released1[45, 15] = initial[0] - 3
    stage1 = accumulate(h, route, released1)
    second_inflow = initial[1] + float(stage1[labels == 2].sum())
    released2 = np.zeros_like(h)
    released2[38, 27] = second_inflow - 7
    stage2 = accumulate(h, route, released2)
    final = float(stage2[frame(h.shape) & (labels == 0)].sum())
    residual = abs(source.sum() - 10 - final) / source.sum()
    if residual > 1e-10:
        raise ValueError("lake cascade budget failed")
    # Independent periodic monthly expectation: totals 100,20, losses 3,7 => outlet 110.
    monthly_in = np.array(initial)[:, None] * np.ones((2, 12)) / 12
    demand = np.array([3.0, 7.0])[:, None] * np.ones((2, 12)) / 12
    monthly, _ = monthly_outflow_cascade(np.array([0, 1]), np.array([1, -1]), 2, monthly_in, demand)
    np.testing.assert_allclose(monthly.sum(axis=1), [97, 110], atol=1e-10)
    return {
        "first_touch_inflow": initial,
        "first_lake_release": float(released1.sum()),
        "second_lake_total_inflow": second_inflow,
        "net_lake_loss": 10,
        "final_outlet": final,
        "relative_residual": float(residual),
        "monthly_outlet_sum": float(monthly[1].sum()),
        "scope": "prescribed footprints and one-way spill cascade; periodic constant forcing",
    }


def seam_control() -> dict:
    h = plane((17, 17), 22.5)
    stop = frame(h.shape)
    route = tiled_directions(h, 1, stop, 8)
    source = np.zeros_like(h)
    source[8, 7] = 8
    total = accumulate(h, route, source)
    np.testing.assert_allclose(total[[8, 7], [8, 8]], [4, 4], atol=1e-10)
    return {
        "source": 8,
        "east_receiver": float(total[8, 8]),
        "northeast_receiver": float(total[7, 8]),
        **budget(route, total, source),
    }


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compare_pack(name: str, pack: Path, out: Path) -> dict:
    import matplotlib.pyplot as plt

    from dreamulator.map.prog_erosion import priority_flood

    height_path = pack / "refined-out/height.pre-equilibrium.npy"
    h = np.load(height_path, mmap_mode="r")
    if h.ndim != 2 or max(h.shape) > 1024 or not np.isfinite(h).all():
        raise ValueError("pilot packs must be finite 2-D grids, at most 1024 on each axis")
    meta = json.loads((pack / "input/meta.json").read_text(encoding="utf-8"))
    nr, nc = h.shape
    if nr != nc or meta["extent_km"]["x"] != meta["extent_km"]["y"]:
        raise ValueError("this pilot requires square grid cells")
    spacing_m = meta["extent_km"]["x"] * 1000 / nc
    land = np.asarray(Image.open(pack / "refined-out/land.png")) > 0
    lake = np.asarray(Image.open(pack / "refined-out/lake.png")) > 0
    if land.shape != h.shape or lake.shape != h.shape:
        raise ValueError("held classification masks differ from height shape")
    lake_labels, lake_count = label(lake, np.ones((3, 3)))
    runoff = np.load(pack / "input/runoff.mm.npy")
    if nr % runoff.shape[0] or nc % runoff.shape[1]:
        raise ValueError("source runoff must align by an integer grid refinement")
    runoff = np.repeat(
        np.repeat(runoff, nr // runoff.shape[0], axis=0), nc // runoff.shape[1], axis=1
    )
    stop = frame(h.shape) | ~land | lake
    # Fixed runoff depth gives m3/reference-year via the actual fine-cell area.
    source = runoff.astype(np.float64) / 1000 * spacing_m**2
    source[stop] = 0
    prepared, _, _ = priority_flood(h, land, eps=1e-4)
    routes = {
        method: directions(prepared, spacing_m, stop, method=method) for method in ("d8", "dinf")
    }
    tiled = tiled_directions(prepared, spacing_m, stop, 256)
    for field in ("receiver", "proportion", "angle_rad", "slope"):
        np.testing.assert_array_equal(getattr(routes["dinf"], field), getattr(tiled, field))
    fig, axes = plt.subplots(1, 3, figsize=(15, 5), sharex=True, sharey=True)
    q99 = None
    report = {
        "shape": list(h.shape),
        "spacing_m": spacing_m,
        "source_units": "m3 per reference year; held pack forcing",
        "held_lake_components": int(lake_count),
        "halo_fields_equal": True,
        "flat_epsilon_m": 1e-4,
        "input_sha256": {
            str(path.relative_to(pack)): hash_file(path)
            for path in (
                height_path,
                pack / "input/meta.json",
                pack / "input/runoff.mm.npy",
                pack / "refined-out/land.png",
                pack / "refined-out/lake.png",
            )
        },
    }
    axes[0].imshow(h, cmap="terrain")
    axes[0].set_title(f"{name}: held height (m)")
    for ax, method in zip(axes[1:], ("d8", "dinf"), strict=True):
        route = routes[method]
        total = accumulate(prepared, route, source)
        sinks = route.proportion.sum(axis=2) == 0
        if q99 is None:
            q99 = float(np.percentile(np.log10(1 + total[land]), 99.7))
        image = ax.imshow(np.log10(1 + total), vmin=0, vmax=q99, cmap="magma")
        ax.set_title(f"{method.upper()}: accumulated runoff")
        ax.contour(lake, levels=[0.5], colors="cyan", linewidths=0.4) if lake.any() else None
        p = route.proportion.reshape(-1, 2)
        rec = route.receiver.reshape(-1, 2)
        src_id = np.broadcast_to(np.arange(h.size)[:, None], p.shape)
        active = p > 0
        sr, sc = src_id // nc // 256, src_id % nc // 256
        tr, tc = rec // nc // 256, rec % nc // 256
        crossed = active & ((sr != tr) | (sc != tc))
        report[method] = {
            **budget(route, total, source),
            "boundary_and_ocean_outflow": float(
                total[sinks & (frame(h.shape) | ~land) & ~lake].sum()
            ),
            "held_lake_first_touch_inflow": float(total[lake].sum()),
            "unclassified_interior_sink_outflow": float(
                total[sinks & land & ~lake & ~frame(h.shape)].sum()
            ),
            "split_cell_percent": float(
                100 * np.mean((p[active.any(axis=1)] > 0).sum(axis=1) == 2)
            ),
            "cross_tile_edges": int(crossed.sum()),
            "cross_tile_transfer_m3_per_year": float((total.ravel()[:, None] * p)[crossed].sum()),
            "first_touch_by_lake_m3_per_year": np.bincount(
                lake_labels.ravel(), weights=total.ravel(), minlength=lake_count + 1
            )[1:].tolist(),
        }
    fig.colorbar(image, ax=axes[1:], shrink=0.65, label="log10(1 + m3/reference-year)")
    fig.savefig(out / f"{name}-accumulation.png", dpi=170, bbox_inches="tight")
    plt.close(fig)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pack", action="append", default=[], metavar="NAME=PATH")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    report = {
        "stage": "local numerical pilot",
        "production_routing": "D8",
        "references": [
            "https://doi.org/10.1029/96WR03137",
            "https://hydrology.usu.edu/taudem/taudem5/help53/DInfinityFlowDirections.html",
            "https://github.com/landlab/landlab/blob/master/src/landlab/components/flow_director/flow_direction_dinf.py",
        ],
        "analytical": analytical_controls(args.out),
        "impulse": impulse_control(args.out),
        "lake": lake_control(),
        "seam": seam_control(),
        "packs": {},
        "remaining": [
            "external-memory two-receiver accumulation",
            "automatic lake spill fraction network and terminal lake equilibrium",
            "full seasonal routing with variable lake demand",
            "continuous final river geometry",
        ],
    }
    for entry in args.pack:
        name, path = entry.split("=", 1)
        if not name.replace("-", "").replace("_", "").isalnum():
            raise ValueError("pack name must contain only letters, numbers, - or _")
        report["packs"][name] = compare_pack(name, Path(path), args.out)
    (args.out / "summary.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "stage": report["stage"],
                "packs": list(report["packs"]),
                "lake_residual": report["lake"]["relative_residual"],
            }
        )
    )


if __name__ == "__main__":
    main()
