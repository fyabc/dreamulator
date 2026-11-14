"""Compare source-preserving terrain blends using a saved TD donor on the same grid.

Usage: python scripts/media/td_source_detail_qa.py exports/td-source-detail/20261115

Each case provides input.json, source.meters.npy and donor.meters.npy. The manifest
declares pixel_km, native_km and preserve_wavelength_km; optional truth.meters.npy
is the original finer-resolution DSM reference. Outputs separate frequency blending,
coast preservation, and the old prototype's geometric depression-depth cap.
This is an offline method check; it does not change production inference defaults.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import matplotlib
import numpy as np
from PIL import Image
from scipy.fft import dctn, idctn
from scipy.ndimage import distance_transform_edt, gaussian_filter

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LightSource, Normalize


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def frequency_rows(shape: tuple[int, int], pixel_km: float, start: int, stop: int):
    """DCT-II frequencies, in cycles per km, with reflective frame boundaries."""
    fy = np.arange(start, stop, dtype=np.float64) / (2 * shape[0] * pixel_km)
    fx = np.arange(shape[1], dtype=np.float64) / (2 * shape[1] * pixel_km)
    return np.hypot(fy[:, None], fx[None, :])


def cosine_detail(difference: np.ndarray, pixel_km: float, preserve_km: float) -> np.ndarray:
    coefficients = dctn(difference, norm="ortho", workers=1)
    f0, f1 = 1 / preserve_km, 2 / preserve_km
    for start in range(0, difference.shape[0], 128):
        stop = min(start + 128, difference.shape[0])
        f = frequency_rows(difference.shape, pixel_km, start, stop)
        x = np.clip((f - f0) / (f1 - f0), 0, 1)
        weight = (0.5 - 0.5 * np.cos(np.pi * x)).astype(np.float32)
        coefficients[start:stop] *= weight
    return idctn(coefficients, norm="ortho", workers=1)


def spectrum_metrics(a: np.ndarray, pixel_km: float, preserve_km: float) -> dict:
    coefficients = dctn(a, norm="ortho", workers=1)
    energy = np.zeros(3, dtype=np.float64)
    f0, f1 = 1 / preserve_km, 2 / preserve_km
    for start in range(0, a.shape[0], 128):
        stop = min(start + 128, a.shape[0])
        f = frequency_rows(a.shape, pixel_km, start, stop)
        c = coefficients[start:stop].astype(np.float64)
        for i, mask in enumerate((f <= f0, (f > f0) & (f < f1), f >= f1)):
            energy[i] += np.sum(c[mask] ** 2)
    rms = np.sqrt(energy / a.size)
    return dict(zip(("trusted_band", "transition_band", "short_band"), rms.tolist(), strict=True))


def depression_depth(a: np.ndarray) -> np.ndarray:
    from dreamulator.map.prog_erosion import priority_flood

    filled, _order, _receivers = priority_flood(np.asarray(a, dtype=np.float64), a > 0)
    return (filled.reshape(a.shape) - a).astype(np.float32)


def coast_preserve(
    source: np.ndarray, delta: np.ndarray, pixel_km: float, fade_km: float
) -> tuple[np.ndarray, int]:
    land = source > 0
    # A padded sea frame provides a finite distance even for all-land windows.
    # It also keeps the source frame fixed, avoiding an arbitrary new outlet.
    distance = distance_transform_edt(np.pad(land, 1))[1:-1, 1:-1] * pixel_km
    t = np.clip(np.maximum(distance - pixel_km, 0) / fade_km, 0, 1).astype(np.float32)
    weight = t * t * (3 - 2 * t)
    result = source + weight * delta
    clipped = int(((result <= 0) & land).sum())
    result[land] = np.maximum(result[land], np.nextafter(np.float32(0), np.float32(1)))
    result[~land] = source[~land]
    return result, clipped


def metrics(
    h: np.ndarray,
    source: np.ndarray,
    source_depth: np.ndarray,
    meta: dict,
    truth: np.ndarray | None,
) -> tuple[dict, np.ndarray]:
    pixel_km, preserve_km = meta["pixel_km"], meta["preserve_wavelength_km"]
    land = source > 0
    delta = h - source
    bands = spectrum_metrics(delta, pixel_km, preserve_km)
    texture = spectrum_metrics(h, pixel_km, preserve_km)["short_band"]
    depth = depression_depth(h)
    block = 256
    rows, cols = h.shape
    coarse = delta.reshape(rows // block, block, cols // block, block).mean(axis=(1, 3))
    fine = h.reshape(rows // 8, 8, cols // 8, 8).mean(axis=(1, 3))
    fine_land = source.reshape(rows // 8, 8, cols // 8, 8).mean(axis=(1, 3)) > 0
    sigma = 10 / (2 * np.sqrt(2 * np.log(2))) / (pixel_km * 8)
    mean = gaussian_filter(fine, sigma, mode="nearest")
    sd = np.sqrt(np.maximum(gaussian_filter(fine**2, sigma, mode="nearest") - mean**2, 0))
    sea_delta = np.abs(delta[~land])
    report = {
        "source_rmse_on_land_m": float(np.sqrt(np.mean(delta[land].astype(np.float64) ** 2)))
        if land.any()
        else None,
        "source_bias_m": float(np.mean(delta, dtype=np.float64)),
        "source_error_spectrum_rms_m": bands,
        "source_coarse256_rmse_m": float(np.sqrt(np.mean(coarse.astype(np.float64) ** 2))),
        "short_band_texture_rms_m": texture,
        "changed_land_sea_area_km2": float(((h > 0) != land).sum() * pixel_km**2),
        "sea_max_abs_difference_m": float(sea_delta.max()) if sea_delta.size else 0,
        "basin_gt1m_fraction_of_land": float(((depth > 1) & (h > 0)).sum())
        / max(int((h > 0).sum()), 1),
        "added_basin_area_km2": float(((depth > 1) & (source_depth <= 1) & land).sum())
        * pixel_km**2,
        "local_relief_10km_all_reference_land_median_m": float(np.median(sd[fine_land]))
        if fine_land.any()
        else None,
        "min_m": float(h.min()),
        "max_m": float(h.max()),
    }
    if truth is not None:
        report["withheld_dsm_height_rmse_m"] = float(
            np.sqrt(np.mean((h - truth).astype(np.float64) ** 2))
        )
    return report, depth


def thumbnail(a: np.ndarray, size: int = 700) -> np.ndarray:
    return np.asarray(
        Image.fromarray(np.asarray(a, dtype=np.float32)).resize(
            (size, size), Image.Resampling.BILINEAR
        )
    )


def render(
    case: Path, meta: dict, images: list[np.ndarray], labels: list[str], prefix: str = "comparison"
) -> None:
    lo, hi = float(images[0].min()), float(images[0].max())
    norm = Normalize(lo, hi)
    light = LightSource(azdeg=315, altdeg=45)
    span = meta["pixel_km"] * images[0].shape[0]
    extent = (0, span, 0, span)
    fig, axes = plt.subplots(2, len(images), figsize=(5 * len(images), 9), layout="constrained")
    for i, (a, label) in enumerate(zip(images, labels, strict=True)):
        small = thumbnail(a)
        im = axes[0, i].imshow(small, norm=norm, cmap="terrain", extent=extent)
        rgb = light.shade(
            small,
            cmap=plt.get_cmap("terrain"),
            norm=norm,
            dx=span * 1000 / small.shape[0],
            dy=span * 1000 / small.shape[1],
            blend_mode="soft",
        )
        axes[1, i].imshow(rgb, extent=extent)
        axes[0, i].set_title(label)
        for ax in axes[:, i]:
            ax.set_xlabel("East (km)")
            ax.set_ylabel("North (km)")
    fig.colorbar(im, ax=axes[0, :], shrink=0.75, label="Elevation (m)")
    fig.suptitle(
        f"{case.name}: native {meta['native_km']:.3f} km; "
        f"preserve wavelengths >= {meta['preserve_wavelength_km']:.3f} km"
    )
    fig.savefig(case / f"{prefix}.png", dpi=140)
    plt.close(fig)
    # A saved common crop makes sub-km changes visible without resampling them.
    crop_km = min(30, span / 3)
    crop_px = min(round(crop_km / meta["pixel_km"]), images[0].shape[0])
    cy, cx = meta.get("crop_center_fraction", [0.5, 0.5])
    y0 = min(max(round(cy * images[0].shape[0]) - crop_px // 2, 0), images[0].shape[0] - crop_px)
    x0 = min(max(round(cx * images[0].shape[1]) - crop_px // 2, 0), images[0].shape[1] - crop_px)
    crops = [np.asarray(a[y0 : y0 + crop_px, x0 : x0 + crop_px]) for a in images]
    crop_norm = Normalize(float(crops[0].min()), float(crops[0].max()))
    fig, axes = plt.subplots(1, len(images), figsize=(5 * len(images), 5), layout="constrained")
    for ax, a, label in zip(axes, crops, labels, strict=True):
        rgb = light.shade(
            a,
            cmap=plt.get_cmap("terrain"),
            norm=crop_norm,
            dx=meta["pixel_km"] * 1000,
            dy=meta["pixel_km"] * 1000,
            blend_mode="soft",
        )
        ax.imshow(rgb, extent=(0, crop_km, 0, crop_km))
        ax.set_title(label)
        ax.set_xlabel("East (km)")
    fig.suptitle(f"{case.name}: same {crop_km:.1f} km crop; {prefix}")
    detail_name = "detail" if prefix == "comparison" else prefix + "-detail"
    fig.savefig(case / f"{detail_name}.png", dpi=160)
    plt.close(fig)


def render_saved(case: Path, meta: dict) -> None:
    def saved(filename: str) -> np.ndarray:
        return np.load(case / filename, mmap_mode="r", allow_pickle=False)

    source = saved("source.meters.npy")
    cosine = saved("cosine.meters.npy")
    render(
        case,
        meta,
        [source, saved("donor.meters.npy"), saved("gaussian.meters.npy"), cosine],
        ["Input source", "TD donor", "Gaussian blend", "Cosine blend"],
    )
    render(
        case,
        meta,
        [source, cosine, saved("cosine.depth-capped.meters.npy")],
        ["Input source", "Cosine blend", "After depression-depth cap"],
        prefix="drainage-comparison",
    )
    if (case / "truth.meters.npy").exists():
        render(
            case,
            meta,
            [source, saved("truth.meters.npy"), cosine],
            ["Input source", "Original finer DSM", "Cosine blend"],
            prefix="dsm-comparison",
        )


def run_case(case: Path) -> dict:
    meta = json.loads((case / "input.json").read_text(encoding="utf-8"))
    for filename, expected in meta["hashes"].items():
        if file_hash(case / filename) != expected:
            raise ValueError(f"source hash mismatch: {case / filename}")
    source = np.load(case / "source.meters.npy", mmap_mode="r", allow_pickle=False)
    donor = np.load(case / "donor.meters.npy", mmap_mode="r", allow_pickle=False)
    truth_path = case / "truth.meters.npy"
    truth = np.load(truth_path, mmap_mode="r", allow_pickle=False) if truth_path.exists() else None
    if source.shape != donor.shape or source.ndim != 2 or not np.isfinite(source).all():
        raise ValueError("source and finite donor must share one two-dimensional grid")
    if any(side < 256 or side % 256 for side in source.shape):
        raise ValueError("the QA coarse aggregation requires sides divisible by 256")
    if not np.isfinite(donor).all() or (truth is not None and truth.shape != source.shape):
        raise ValueError("donor must be finite and truth must share the source grid")
    if meta["preserve_wavelength_km"] < 4 * meta["pixel_km"]:
        raise ValueError("the transition must fit within the output sampling bandwidth")
    source_depth = depression_depth(source)
    reports = {}
    reports["source"], _ = metrics(source, source, source_depth, meta, truth)
    reports["donor"], _ = metrics(donor, source, source_depth, meta, truth)
    if truth is not None:
        reports["withheld_dsm"], _ = metrics(truth, source, source_depth, meta, truth)
    difference = donor.astype(np.float32) - source
    sigma_km = meta["preserve_wavelength_km"] * np.sqrt(np.log(2)) / (np.sqrt(2) * np.pi)
    receipts = {}
    for arm in ("gaussian", "cosine"):
        delta = (
            difference - gaussian_filter(difference, sigma_km / meta["pixel_km"], mode="reflect")
            if arm == "gaussian"
            else cosine_detail(difference, meta["pixel_km"], meta["preserve_wavelength_km"])
        )
        before = spectrum_metrics(delta, meta["pixel_km"], meta["preserve_wavelength_km"])
        h, clipped = coast_preserve(
            source, delta, meta["pixel_km"], meta["preserve_wavelength_km"] / 2
        )
        np.save(case / f"{arm}.frequency-delta.npy", delta)
        np.save(case / f"{arm}.meters.npy", h)
        reports[arm], depth = metrics(h, source, source_depth, meta, truth)
        reports[arm]["source_error_spectrum_before_coast_rms_m"] = before
        reports[arm]["land_pixels_clipped"] = clipped
        capped = h + np.maximum(depth - source_depth, 0)
        capped[source <= 0] = source[source <= 0]
        np.save(case / f"{arm}.depth-capped.meters.npy", capped)
        reports[arm + "_depth_capped"], capped_depth = metrics(
            capped, source, source_depth, meta, truth
        )
        reports[arm + "_depth_capped"]["max_depth_above_source_m"] = float(
            np.maximum(capped_depth - source_depth, 0).max()
        )
        reports[arm + "_depth_capped"]["max_height_added_by_cap_m"] = float((capped - h).max())
        receipts[arm] = {
            "output_sha256": file_hash(case / f"{arm}.meters.npy"),
            "depth_capped_sha256": file_hash(case / f"{arm}.depth-capped.meters.npy"),
            "frequency_delta_sha256": file_hash(case / f"{arm}.frequency-delta.npy"),
        }
        print(f"{case.name} {arm} complete", flush=True)
        del delta, h, depth, capped, capped_depth
    render_saved(case, meta)
    record = {"input": meta, "metrics": reports, "receipts": receipts}
    (case / "metrics.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({case.name: reports}), flush=True)
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--cases", nargs="+")
    parser.add_argument(
        "--render-only",
        action="store_true",
        help="Redraw saved fields without recomputing terrain or metrics",
    )
    args = parser.parse_args()
    summary_path = args.directory / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    cases = (
        [args.directory / name for name in args.cases]
        if args.cases
        else sorted(p.parent for p in args.directory.glob("*/input.json"))
    )
    for case in cases:
        if args.render_only:
            meta = json.loads((case / "input.json").read_text(encoding="utf-8"))
            render_saved(case, meta)
            continue
        summary[case.name] = run_case(case)
        summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
