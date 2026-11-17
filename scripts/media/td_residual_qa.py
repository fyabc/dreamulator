"""Compare residual-channel editing with fixed source-guided controls on common windows."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from td_source_detail_qa import depression_depth, file_hash, metrics, render
from td_source_guided_qa import matched_noise, structure


def run(case: Path) -> dict:
    meta = json.loads((case / "input.json").read_text(encoding="utf-8"))
    source = np.load(case / "source.meters.npy", allow_pickle=False)
    depth = depression_depth(source)
    truth_path = case / "truth.meters.npy"
    truth = np.load(truth_path, allow_pickle=False) if truth_path.exists() else None
    weight = np.load(case / "parent-coast-weight.npy", allow_pickle=False)
    images, reports = {}, {}
    for arm in ["source", "decoder", "edit-035", "residual-035", "truth"]:
        path = case / f"{arm}.meters.npy"
        if not path.exists():
            continue
        h = np.load(path, allow_pickle=False)
        report, basin = metrics(h, source, depth, meta, truth)
        report.update(structure(h, source, meta))
        report["output_sha256"] = file_hash(path)
        images[arm], reports[arm] = h, report
        if arm == "residual-035":
            np.save(case / f"{arm}.depression-depth.m.npy", basin, allow_pickle=False)
        if arm in {"decoder", "edit-035", "residual-035"}:
            # Use exactly the same mother-map fade as the accepted blend control.
            adopted = source + weight * (h - source)
            land = source > 0
            clipped = int(((adopted <= 0) & land).sum())
            adopted[land] = np.maximum(adopted[land], np.nextafter(np.float32(0), np.float32(1)))
            adopted[~land] = source[~land]
            np.save(case / f"{arm}.mother-coast-preserved.meters.npy", adopted, allow_pickle=False)
            adopted_report, _ = metrics(adopted, source, depth, meta, truth)
            adopted_report["land_sign_clipped_pixels"] = clipped
            reports[arm + "_mother_coast_preserved"] = adopted_report
    delta = images["residual-035"] - source
    noise = source + matched_noise(delta)
    noise_report, _ = metrics(noise, source, depth, meta, truth)
    noise_report.update(structure(noise, source, meta))
    reports["residual_matched_spectrum_noise_raw"] = noise_report
    np.save(case / "residual-matched-noise.meters.npy", noise, allow_pickle=False)
    noise = source + weight * (noise - source)
    noise[source <= 0] = source[source <= 0]
    noise[source > 0] = np.maximum(noise[source > 0], np.nextafter(np.float32(0), np.float32(1)))
    reports["residual_matched_spectrum_noise_mother_coast_preserved"], _ = metrics(
        noise, source, depth, meta, truth
    )
    render(case, meta, list(images.values()), list(images), prefix="residual-candidates")
    render(
        case,
        meta,
        [source, images["residual-035"], np.load(case / "residual-matched-noise.meters.npy")],
        ["Input", "Residual edit", "Same spectrum, random signs"],
        prefix="organization-control",
    )
    parent = np.load(case / "source.latent.npy", allow_pickle=False)
    generated = np.load(case / "residual-035.latent.npy", allow_pickle=False)
    report = dict(
        background_channel_max_abs=float(np.abs(generated[4] - parent[4]).max()),
        detail_channels_rms=float(np.sqrt(np.mean((generated[:4] - parent[:4]) ** 2))),
        long_band_error_ratio_to_edit035=reports["residual-035"]["source_error_spectrum_rms_m"][
            "trusted_band"
        ]
        / reports["edit-035"]["source_error_spectrum_rms_m"]["trusted_band"],
        short_texture_ratio_to_decoder=reports["residual-035"]["short_band_texture_rms_m"]
        / reports["decoder"]["short_band_texture_rms_m"],
    )
    slope_key = f"slope_cosine_{meta['preserve_wavelength_km']:.4g}km"
    report["slope_cosine_change_from_edit035"] = (
        reports["residual-035"][slope_key] - reports["edit-035"][slope_key]
    )
    report["screen_passed"] = (
        report["long_band_error_ratio_to_edit035"] <= 0.5
        and report["short_texture_ratio_to_decoder"] >= 1
        and report["slope_cosine_change_from_edit035"] >= -0.02
    )
    result = dict(
        metrics=reports,
        screening=report,
        coast_weight_sha256=file_hash(case / "parent-coast-weight.npy"),
    )
    (case / "residual-metrics.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    print(case.name, report, flush=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    result = {
        case.name: run(case)
        for case in sorted(args.directory.iterdir())
        if case.is_dir() and (case / "residual-035.receipt.json").exists()
    }
    if len(result) != 3:
        raise ValueError("All three predeclared cases must be completed")
    (args.directory / "summary.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
