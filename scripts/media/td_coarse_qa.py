"""Compare standard and direct TD coarse statistics against a saved terrain reference.

Usage: uv run python scripts/media/td_coarse_qa.py exports/td-coarse-direct/20261115

Each case directory supplies input.json, statistics.npy, reference.meters.npy,
standard.meters.npy and direct.meters.npy. Reports and figures are written beside
the saved arrays. The case labels distinguish author input, observed DSM and
model terrain; raw geometric depressions are measured before lake-water balance.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib
import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt, gaussian_filter

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LightSource, Normalize

OUT = Path("exports/td-coarse-direct/qa")


def signed_sqrt(z: np.ndarray) -> np.ndarray:
    return np.sign(z) * np.sqrt(np.abs(z))


def invert(z: np.ndarray) -> np.ndarray:
    return np.sign(z) * z**2


def td_stats(a: np.ndarray, n: int) -> tuple[np.ndarray, np.ndarray]:
    s = signed_sqrt(a).reshape(n * 32, 8, n * 32, 8)
    latent = np.median(s, axis=(1, 3))
    blocks = latent.reshape(n, 32, n, 32)
    return blocks.mean(axis=(1, 3), dtype=np.float64), np.quantile(blocks, 0.05, axis=(1, 3))


def field_metrics(a: np.ndarray, reference: np.ndarray, meta: dict) -> dict:
    n = meta["ncell"]
    px = meta["native_output_px_km"]
    h = np.asarray(a, dtype=np.float64)
    r = np.asarray(reference, dtype=np.float64)
    cm = h.reshape(n, 256, n, 256).mean(axis=(1, 3))
    rm = r.reshape(n, 256, n, 256).mean(axis=(1, 3))
    diff = cm - rm
    slope = float(np.polyfit(rm.ravel(), cm.ravel(), 1)[0]) if np.ptp(rm) > 1 else None
    land_slope = float(np.polyfit(rm[rm > 0], cm[rm > 0], 1)[0]) if np.ptp(rm[rm > 0]) > 1 else None
    mismatch = (r > 0) != (h > 0)
    # Local relief: standard deviation in a 10 km FWHM Gaussian window on
    # the 720 m area-mean grid. Evaluate in the reference's land interior.
    lr = h.reshape(n * 32, 8, n * 32, 8).mean(axis=(1, 3))
    rr = r.reshape(n * 32, 8, n * 32, 8).mean(axis=(1, 3))
    sigma = 10.0 / (2 * np.sqrt(2 * np.log(2))) / (px * 8)
    avg = gaussian_filter(lr, sigma, mode="nearest")
    sd = np.sqrt(np.maximum(gaussian_filter(lr**2, sigma, mode="nearest") - avg**2, 0))
    interior = distance_transform_edt(rr > 0) * (px * 8) > 10
    if not interior.any():
        interior = rr > 0
    # Geometric depressions in raw terrain; the ocean and frame are outlets.
    # This precedes heal and lake-water balance; it is not final lake area.
    from dreamulator.map.prog_erosion import priority_flood

    filled, _order, _receivers = priority_flood(h, h > 0)
    depth = filled.reshape(h.shape) - h
    encoded_mean, encoded_p5 = td_stats(h, n)
    target = np.load(OUT / meta["case"] / "statistics.npy", allow_pickle=False)
    return {
        "coarse_rmse_m": float(np.sqrt(np.mean(diff**2))),
        "coarse_bias_m": float(diff.mean()),
        "coarse_slope_all": slope,
        "coarse_slope_reference_land": land_slope,
        "land_fraction": float((h > 0).mean()),
        "changed_land_sea_area_km2": float(mismatch.sum() * px**2),
        "changed_land_sea_fraction": float(mismatch.mean()),
        "local_relief_10km_land_median_m": float(np.median(sd[interior])),
        "geometric_depression_gt1m_fraction_of_generated_land": float(
            ((depth > 1) & (h > 0)).sum() / max((h > 0).sum(), 1)
        ),
        "encoded_mean_rmse": float(np.sqrt(np.mean((encoded_mean - target[0]) ** 2))),
        "encoded_p5_rmse": float(np.sqrt(np.mean((encoded_p5 - target[1]) ** 2))),
        "reference_land_height_q50_q90_q99_m": np.quantile(h[r > 0], [0.5, 0.9, 0.99]).tolist(),
        "min_m": float(h.min()),
        "max_m": float(h.max()),
    }


def closure_check(ref: np.ndarray, n: int) -> dict:
    nodes, weights = np.polynomial.hermite.hermgauss(32)
    # Validate the sole Gaussian hypothesis at 23 and 46 km, using the
    # median720m source; the latter is close to a 50 km engine cell.
    latent_s = np.median(signed_sqrt(ref).reshape(n * 32, 8, n * 32, 8), axis=(1, 3))
    latent_m = invert(latent_s)
    result = {}
    for multiplier in (1, 2):
        nc, b = n // multiplier, 32 * multiplier
        blocks_m = latent_m.reshape(nc, b, nc, b)
        blocks_s = latent_s.reshape(nc, b, nc, b)
        mu = blocks_m.mean(axis=(1, 3), dtype=np.float64)
        std = blocks_m.std(axis=(1, 3), dtype=np.float64)
        truth_m = blocks_s.mean(axis=(1, 3), dtype=np.float64)
        truth_p5 = np.quantile(blocks_s, 0.05, axis=(1, 3))
        estimate_m = np.sum(
            signed_sqrt(mu[..., None] + np.sqrt(2) * std[..., None] * nodes) * weights, axis=-1
        ) / np.sqrt(np.pi)
        estimate_p5 = signed_sqrt(mu - 1.6448536269514722 * std)
        result[str(23 * multiplier) + "km"] = {
            "encoded_mean_rmse": float(np.sqrt(np.mean((estimate_m - truth_m) ** 2))),
            "encoded_p5_rmse": float(np.sqrt(np.mean((estimate_p5 - truth_p5) ** 2))),
            "p5_height_rmse_m": float(
                np.sqrt(np.mean((invert(estimate_p5) - invert(truth_p5)) ** 2))
            ),
            "p5_height_bias_m": float(np.mean(invert(estimate_p5) - invert(truth_p5))),
            "false_below_sea_p5_cells": int(((estimate_p5 < 0) & (truth_p5 >= 0)).sum()),
            "n_cells": nc**2,
        }
    return result


def render_case(name: str, arrays: list[np.ndarray], meta: dict, metrics: dict) -> None:
    thumbnails = [
        np.asarray(
            Image.fromarray(np.asarray(a, dtype=np.float32)).resize(
                (768, 768), Image.Resampling.BILINEAR
            )
        )
        for a in arrays
    ]
    lo, hi = float(arrays[0].min()), float(arrays[0].max())
    norm = Normalize(lo, hi)
    extent = (0, meta["span_km"], 0, meta["span_km"])
    fig, axes = plt.subplots(2, 3, figsize=(14, 9), layout="constrained")
    light = LightSource(azdeg=315, altdeg=45)
    for col, title in enumerate(
        ("Input reference", "Standard coarse diffusion", "Direct coarse statistics")
    ):
        im = axes[0, col].imshow(
            thumbnails[col], cmap="terrain", norm=norm, extent=extent, origin="upper"
        )
        rgb = light.shade(
            thumbnails[col],
            cmap=plt.get_cmap("terrain"),
            norm=norm,
            vert_exag=1,
            dx=meta["span_km"] * 1000 / 768,
            dy=meta["span_km"] * 1000 / 768,
            blend_mode="soft",
        )
        axes[1, col].imshow(rgb, extent=extent, origin="upper")
        axes[0, col].set_title(title)
        axes[1, col].set_title(
            f"10 km relief: {metrics[col]['local_relief_10km_land_median_m']:.1f} m"
        )
        for ax in axes[:, col]:
            ax.set_xlabel("East (km)")
            ax.set_ylabel("North (km)")
    fig.colorbar(im, ax=axes[0, :], shrink=0.7, label="Elevation (m)")
    fig.suptitle(f"{name}: {meta['span_km']:.2f} km; raw terrain before hydrology")
    fig.savefig(OUT / name / "comparison.png", dpi=160)
    plt.close(fig)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument(
        "--cases",
        nargs="+",
        default=["external_350m", "earth_alps", "earth_himalaya", "nacrea_coarse"],
    )
    args = parser.parse_args()
    global OUT
    OUT = args.directory.resolve()
    summary_path = OUT / "summary.json"
    summaries = (
        json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    )
    for name in args.cases:
        case = OUT / name
        meta = json.loads((case / "input.json").read_text(encoding="utf-8"))
        meta["case"] = name
        ref = np.load(case / "reference.meters.npy", mmap_mode="r", allow_pickle=False)
        standard = np.load(case / "standard.meters.npy", mmap_mode="r", allow_pickle=False)
        direct = np.load(case / "direct.meters.npy", mmap_mode="r", allow_pickle=False)
        stats = {
            arm: field_metrics(a, ref, meta)
            for arm, a in (("reference", ref), ("standard", standard), ("direct", direct))
        }
        if name.startswith("earth_"):
            stats["gaussian_closure"] = closure_check(ref, meta["ncell"])
        summaries[name] = {"reference_kind": meta["reference_kind"], "metrics": stats}
        (case / "metrics.json").write_text(
            json.dumps(summaries[name], indent=2) + "\n", encoding="utf-8"
        )
        render_case(
            name,
            [ref, standard, direct],
            meta,
            [stats["reference"], stats["standard"], stats["direct"]],
        )
        print(json.dumps({name: summaries[name]}), flush=True)
        (OUT / "summary.json").write_text(json.dumps(summaries, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
