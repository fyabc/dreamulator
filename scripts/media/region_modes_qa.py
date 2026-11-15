"""Check and render adopted region-mode products under an export root.

Each case contains qa-input.json and pack/input plus pack/refined-out.
Optional depth-cap-pack, redraw-pack and hydrology-pack hold other CLI arms.
The overlapping crops are from one adopted parent. Independent-window DCT
is a negative control, not a supported seamless build path.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image
from td_source_detail_qa import depression_depth, metrics, render, spectrum_metrics

from dreamulator.api_routes import packs
from dreamulator.map.region_inputs import file_sha256
from dreamulator.media.satellite_color import load_inputs
from dreamulator.media.terrain_blend import RefinementMode, detail_difference
from dreamulator.media.terrain_refine import refine_region_pack


def check_case(case: Path) -> dict:
    spec = json.loads((case / "qa-input.json").read_text(encoding="utf-8"))
    pack = case / "pack"
    out = pack / "refined-out"
    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    contract = meta["cache_contract"]
    source = np.load(out / "height.source.npy")
    donor = np.load(out / "height.donor.npy")
    adopted = np.load(out / "height.meters.npy")
    input_meta = json.loads((pack / "input/meta.json").read_text(encoding="utf-8"))
    qmeta = {
        "native_km": spec["native_km"],
        "pixel_km": float(input_meta["extent_km"]["x"]) / source.shape[0],
        "preserve_wavelength_km": contract["preserve_wavelength_km"],
    }
    depth = depression_depth(source)
    report, _ = metrics(adopted, source, depth, qmeta, None)
    delta = np.load(out / "height.frequency-delta.npy")
    report["before_coast_error_spectrum_rms_m"] = spectrum_metrics(
        delta, qmeta["pixel_km"], qmeta["preserve_wavelength_km"]
    )
    np.testing.assert_array_equal(adopted, np.load(out / "height.pre-equilibrium.npy"))
    np.testing.assert_array_equal(adopted > 0, source > 0)
    np.testing.assert_array_equal(adopted[source <= 0], source[source <= 0])
    np.testing.assert_array_equal(np.asarray(Image.open(out / "land.png")) > 0, source > 0)
    inputs = load_inputs(pack / "input", out)
    np.testing.assert_array_equal(inputs.height_m, adopted)
    old_resolver = packs._pack_dir
    probes = []
    try:
        packs._pack_dir = lambda _: pack
        window = packs._window(input_meta)
        for u, v in ((0.25, 0.25), (0.75, 0.25), (0.5, 0.5), (0.75, 0.75)):
            lat, lon = packs._frac_to_ll(window, u, v)
            probe = packs.probe(case.name, lat, lon)["data"]
            assert probe["height_m"] == float(adopted[probe["row"], probe["col"]])
            assert probe["height_source"] == "refined"
            probes.append(probe)
    finally:
        packs._pack_dir = old_resolver
    before = {p.name: file_sha256(p) for p in out.glob("height.*.npy")}
    refine_region_pack(
        pack,
        None,
        mode=RefinementMode.BLEND,
        native_resolution_km=spec["native_km"],
        reuse_height=True,
    )
    assert before == {p.name: file_sha256(p) for p in out.glob("height.*.npy")}
    n = adopted.shape[1]
    # Copy two independently stored crops from the parent; compare actual
    # saved heights and masks at their overlapping global pixel coordinates.
    for filename in ("height.meters.npy", "land.png", "lake.png", "sea-water.png", "rivers.png"):
        a = (
            np.load(out / filename)
            if filename.endswith("npy")
            else np.asarray(Image.open(out / filename))
        )
        left, right = a[:, : 3 * n // 4], a[:, n // 4 :]
        for tag, crop in (("left", left), ("right", right)):
            np.save(case / f"overlap-{tag}-{filename}.npy", crop)
        saved_left = np.load(case / f"overlap-left-{filename}.npy")
        saved_right = np.load(case / f"overlap-right-{filename}.npy")
        np.testing.assert_array_equal(saved_left[:, n // 4 :], saved_right[:, : n // 2])
    independent = detail_difference(
        source[:, : 3 * n // 4],
        donor[:, : 3 * n // 4],
        qmeta["pixel_km"],
        qmeta["preserve_wavelength_km"],
    )
    report.update(
        {
            "routing_height_matches_adopted": True,
            "render_height_matches_adopted": True,
            "probe_height_matches_adopted": True,
            "cache_replay_stage_hashes_identical": True,
            "parent_crop_overlap_height_and_masks_identical": True,
            "independent_window_delta_max_difference_m": float(
                np.abs(independent - delta[:, : 3 * n // 4]).max()
            ),
            "probes": probes,
            "stage_sha256": before,
        }
    )
    images, labels = [source, donor, adopted], ["Source", "TD donor", "Adopted blend"]
    for arm, label in (
        ("depth-cap-pack", "Depth cap"),
        ("redraw-pack", "Redraw"),
        ("hydrology-pack", "Original hydrology"),
    ):
        arm_path = case / arm / "refined-out/height.meters.npy"
        if arm_path.exists():
            height = np.load(arm_path)
            report[arm], arm_depth = metrics(height, source, depth, qmeta, None)
            arm_donor = arm_path.parent / "height.donor.npy"
            if arm_donor.exists():
                assert file_sha256(arm_donor) == file_sha256(out / "height.donor.npy")
                report[arm]["full_inference_donor_hash_identical"] = True
            if arm == "depth-cap-pack":
                excess = float(np.maximum(arm_depth - depth, 0).max())
                assert excess < 0.001
                report[arm]["max_depth_above_source_m"] = excess
                report[arm]["max_raise_above_blend_m"] = float((height - adopted).max())
            if arm == "hydrology-pack":
                np.testing.assert_array_equal(height, source)
            images.append(height)
            labels.append(label)
    render(case, qmeta, images, labels)
    (case / "validation.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    reports = {
        p.name: check_case(p) for p in sorted(args.root.iterdir()) if (p / "qa-input.json").exists()
    }
    (args.root / "validation.json").write_text(
        json.dumps(reports, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
