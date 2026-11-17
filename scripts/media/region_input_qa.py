"""Plot region input, refined terrain, water and monthly runoff for acceptance.

Usage: uv run python scripts/media/region_input_qa.py PACK --output exports/region-inputs/qa
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
import numpy as np
from PIL import Image

from dreamulator.map.region_inputs import read_refinement_inputs

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pack", type=Path)
    parser.add_argument("--output", type=Path, default=Path("exports/region-inputs/qa"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    inp, refined = args.pack / "input", args.pack / "refined-out"
    meta = json.loads((inp / "meta.json").read_text(encoding="utf-8"))
    fields = read_refinement_inputs(inp, meta["refinement_inputs"])
    height = np.load(inp / "height.meters.npy", mmap_mode="r", allow_pickle=False)
    result = np.load(refined / "height.meters.npy", mmap_mode="r", allow_pickle=False)
    annual = np.load(inp / "runoff.mm.npy", mmap_mode="r", allow_pickle=False)
    monthly = fields["runoff_monthly_mm"]
    land = height > meta["sea_level_m"]
    month_means = [float(monthly[..., month][land].mean(dtype=np.float64)) for month in range(12)]
    max_residual = 0.0
    for start in range(0, height.shape[0], 64):
        rows = slice(start, start + 64)
        residual = monthly[rows].sum(axis=-1, dtype=np.float64) - np.nan_to_num(annual[rows])
        max_residual = max(max_residual, float(np.abs(residual).max()))

    def thumbnail(values: np.ndarray) -> np.ndarray:
        return np.asarray(
            Image.fromarray(np.asarray(values, dtype=np.float32)).resize(
                (768, 768), Image.Resampling.BILINEAR
            )
        )

    sea = Image.open(refined / "sea-water.png").resize((768, 768), Image.Resampling.NEAREST)
    lakes = Image.open(refined / "lake.png").resize((768, 768), Image.Resampling.NEAREST)
    rivers = Image.open(refined / "rivers.png").resize((768, 768), Image.Resampling.BOX)
    water = np.full((768, 768, 3), (231, 229, 215), dtype=np.uint8)
    water[np.asarray(sea) > 0] = (47, 92, 132)
    water[np.asarray(lakes) > 0] = (62, 135, 190)
    water[np.asarray(rivers) > 0] = (22, 95, 185)
    span = float(meta["span_km"])
    extent = (0, span, 0, span)
    fig, axes = plt.subplots(2, 2, figsize=(12, 10), layout="constrained")
    for ax, h, title in (
        (axes[0, 0], height, "Input height"),
        (axes[0, 1], result, "TD terrain with hydrology"),
    ):
        plot = ax.imshow(
            thumbnail(h),
            extent=extent,
            origin="upper",
            cmap="terrain",
            vmin=float(height.min()),
            vmax=float(height.max()),
        )
        ax.set_title(title)
        ax.set_xlabel("East (km)")
        ax.set_ylabel("North (km)")
        fig.colorbar(plot, ax=ax, label="Elevation (m)", shrink=0.8)
    axes[1, 0].imshow(water, extent=extent, origin="upper")
    axes[1, 0].set_title("Connected sea, lakes and rivers")
    axes[1, 0].set_xlabel("East (km)")
    axes[1, 0].set_ylabel("North (km)")
    axes[1, 1].bar(np.arange(1, 13), month_means)
    axes[1, 1].set_title("Runoff over input land")
    axes[1, 1].set_xlabel("Reference month")
    axes[1, 1].set_ylabel("Mean runoff (mm per reference month)")
    axes[1, 1].set_xticks(np.arange(1, 13))
    fig.suptitle(f"Standalone region pack: {span:.2f} km square")
    fig.savefig(args.output / "overview.png", dpi=160)
    plt.close(fig)
    report = {
        "span_km": span,
        "input_shape": list(height.shape),
        "refined_shape": list(result.shape),
        "refined_km_per_px": span / result.shape[0],
        "temperature_basis": meta["refinement_inputs"]["temperature_basis"],
        "monthly_annual_max_residual_mm": max_residual,
        "land_monthly_runoff_mean_mm": month_means,
        "has_biome": (inp / "biome.codes.npy").exists(),
        "has_ice_thickness": (inp / "ice.m.npy").exists(),
        "manifest_validation": "passed",
    }
    (args.output / "checks.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
