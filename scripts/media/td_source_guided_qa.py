"""Render and measure saved source-guided TD experiments on common local windows.

Usage: python scripts/media/td_source_guided_qa.py <export-directory>
Raw generation, coast preservation, and depression measurements remain separate.
DSM error is a withheld observational check; feature scores measure source agreement.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.fft import dctn, idctn
from scipy.ndimage import distance_transform_edt, gaussian_filter, gaussian_laplace, label
from td_source_detail_qa import (
    coast_preserve,
    depression_depth,
    file_hash,
    metrics,
    render,
    spectrum_metrics,
)


def matched_noise(delta: np.ndarray) -> np.ndarray:
    """Randomize each real DCT coefficient's sign, preserving its exact power."""
    coefficients = dctn(delta, norm="ortho", workers=1)
    rng = np.random.default_rng(42)
    coefficients *= rng.choice(np.array([-1, 1], np.float32), size=coefficients.shape)
    return idctn(coefficients, norm="ortho", workers=1)


def structure(h: np.ndarray, source: np.ndarray, meta: dict) -> dict:
    pixel = meta["pixel_km"]
    # A block average measures directions above interpolation's native bandwidth.
    block = 4
    n = h.shape[0] // block
    a = source.reshape(n, block, n, block).mean(axis=(1, 3))
    b = h.reshape(n, block, n, block).mean(axis=(1, 3))
    spacing = pixel * block
    margin = 16
    core = np.zeros(a.shape, bool)
    core[margin:-margin, margin:-margin] = True
    core &= a > 0
    report = {}
    for wavelength in (meta["preserve_wavelength_km"], 5.0, 20.0):
        sigma = max(wavelength * np.sqrt(np.log(2)) / (np.sqrt(2) * np.pi * spacing), 0.5)
        sa, sb = gaussian_filter(a, sigma), gaussian_filter(b, sigma)
        ga, gb = np.gradient(sa), np.gradient(sb)
        norm = np.hypot(*ga) * np.hypot(*gb)
        reliable = core & (np.hypot(*ga) > 1) & (np.hypot(*gb) > 1)
        cosine = (ga[0] * gb[0] + ga[1] * gb[1]) / np.maximum(norm, 1e-12)
        report[f"slope_cosine_{wavelength:.4g}km"] = float(np.mean(cosine[reliable]))
        report[f"source_smoothed_rmse_{wavelength:.4g}km_m"] = float(
            np.sqrt(np.mean((sa[core] - sb[core]).astype(np.float64) ** 2))
        )
    # Curvature extrema are ridge/valley proxies, rather than surveyed feature lines.
    sigma = max(meta["preserve_wavelength_km"] / (4 * spacing), 0.75)
    ca, cb = gaussian_laplace(a, sigma), gaussian_laplace(b, sigma)
    for kind, sign in (("ridge", -1), ("valley", 1)):
        aa, bb = ca * sign, cb * sign
        fa = (aa >= np.percentile(aa[core], 90)) & core
        fb = (bb >= np.percentile(bb[core], 90)) & core
        da, db = distance_transform_edt(~fa) * spacing, distance_transform_edt(~fb) * spacing
        precision = float(np.mean(da[fb] <= spacing))
        recall = float(np.mean(db[fa] <= spacing))
        report[f"{kind}_proxy_f1_within_{spacing:.4g}km"] = (
            2 * precision * recall / max(precision + recall, 1e-12)
        )
        report[f"{kind}_proxy_median_displacement_km"] = float(np.median(db[fa]))
        components, count = label(fb)
        sizes = np.bincount(components.ravel())[1:]
        report[f"{kind}_proxy_components"] = count
        report[f"{kind}_proxy_largest_component_fraction"] = (
            float(sizes.max() / max(fb.sum(), 1)) if sizes.size else 0
        )
    directions = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]

    def downhill(field):
        slopes = np.stack(
            [
                (field - np.roll(field, (dy, dx), axis=(0, 1))) / np.hypot(dy, dx)
                for dy, dx in directions
            ]
        )
        return slopes.argmax(axis=0), slopes.max(axis=0) > 0

    ra, ma = downhill(a)
    rb, mb = downhill(b)
    valid = core & ma & mb
    report["downhill_D8_agreement_at_native_4pixel_grid"] = float(np.mean(ra[valid] == rb[valid]))
    report["downhill_D8_grid_km"] = spacing
    return report


def run(case: Path, refresh_noise: bool = False) -> dict:
    meta = json.loads((case / "input.json").read_text(encoding="utf-8"))
    source = np.load(case / "source.meters.npy", allow_pickle=False)
    source_depth = depression_depth(source)
    truth_path = case / "truth.meters.npy"
    truth = np.load(truth_path, allow_pickle=False) if truth_path.exists() else None
    frequency_delta = np.load(case / "cosine.frequency-delta.npy", allow_pickle=False)
    noise_delta = matched_noise(frequency_delta)
    weight = np.load(case / "parent-coast-weight.npy", allow_pickle=False)
    noise = source + weight * noise_delta
    noise[source > 0] = np.maximum(noise[source > 0], np.nextafter(np.float32(0), np.float32(1)))
    noise[source <= 0] = source[source <= 0]
    np.save(case / "noise.meters.npy", noise, allow_pickle=False)
    known = [
        "source",
        "noise",
        "cosine",
        "donor",
        "ae-roundtrip",
        "decoder",
        "edit-0065",
        "edit-035",
        "unprojected",
        "projected",
        "truth",
    ]
    images, reports = {}, {}
    if refresh_noise:
        reports = json.loads((case / "metrics.json").read_text(encoding="utf-8"))
        known = ["noise"]
        images = {
            k: np.load(case / f"{k}.meters.npy", allow_pickle=False)
            for k in ("source", "cosine", "donor")
        }
    for arm in known:
        path = case / f"{arm}.meters.npy"
        if not path.exists():
            continue
        h = np.load(path, allow_pickle=False)
        report, depth = metrics(h, source, source_depth, meta, truth)
        report.update(structure(h, source, meta))
        report["output_sha256"] = file_hash(path)
        np.save(case / f"{arm}.depression-depth.m.npy", depth, allow_pickle=False)
        images[arm] = h
        reports[arm] = report
        if arm == "noise":
            report["spectrum_before_coast_rms_m"] = spectrum_metrics(
                noise_delta, meta["pixel_km"], meta["preserve_wavelength_km"]
            )
            report["matched_blend_spectrum_before_coast_rms_m"] = spectrum_metrics(
                frequency_delta, meta["pixel_km"], meta["preserve_wavelength_km"]
            )
        if arm in {"decoder", "edit-0065", "edit-035", "unprojected", "projected"}:
            adopted, clipped = coast_preserve(
                source, h - source, meta["pixel_km"], 2 * meta["pixel_km"]
            )
            np.save(case / f"{arm}.coast-preserved.meters.npy", adopted, allow_pickle=False)
            preserved, _ = metrics(adopted, source, source_depth, meta, truth)
            preserved["land_sign_clipped_pixels"] = clipped
            reports[arm + "_coast_preserved"] = preserved
    render(
        case,
        meta,
        [images[k] for k in ("source", "noise", "cosine", "donor")],
        ["Input", "Matched spectrum noise", "Current blend", "Current redraw"],
        prefix="controls",
    )
    fine = [
        k
        for k in ("source", "ae-roundtrip", "decoder", "edit-0065", "edit-035", "truth")
        if k in images
    ]
    if not refresh_noise:
        render(case, meta, [images[k] for k in fine], fine, prefix="fine-candidates")
    if "projected" in images:
        render(
            case,
            meta,
            [images[k] for k in ("source", "donor", "unprojected", "projected")],
            [
                "Input",
                "Current redraw",
                "No projection (training amplitude)",
                "Low frequency projection",
            ],
            prefix="coarse-candidates",
        )
    (case / "metrics.json").write_text(json.dumps(reports, indent=2) + "\n", encoding="utf-8")
    print(case.name, {k: v["source_rmse_on_land_m"] for k, v in reports.items()}, flush=True)
    return reports


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument(
        "--cases", nargs="*", help="Measure only the named cases and merge the summary"
    )
    parser.add_argument(
        "--refresh-noise", action="store_true", help="Recompute only the noise control"
    )
    args = parser.parse_args()
    summary_path = args.directory / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    summary.update(
        {
            case.name: run(case, args.refresh_noise)
            for case in sorted(args.directory.iterdir())
            if case.is_dir()
            and (case / "ae-gate.json").exists()
            and (not args.cases or case.name in args.cases)
        }
    )
    (args.directory / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
