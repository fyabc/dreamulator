"""Render a verified bed-elevation update while retaining the reference ice surface."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
import yaml
from PIL import Image

from dreamulator.map.export import (
    export_cell_index_grid,
    load_cvt_mesh_model,
    render_terrain_layer,
    save_rgba_png,
)
from dreamulator.map.ice_sheets import ICE_LOAD_DEPRESSION
from dreamulator.map.palettes import build_adaptive_terrain_lut


def sha(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mesh", required=True, type=Path)
    parser.add_argument("--baseline-bed", required=True, type=Path)
    parser.add_argument("--new-source", required=True, type=Path)
    parser.add_argument("--geometry", required=True, type=Path)
    parser.add_argument("--metadata", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--record", required=True, type=Path)
    args = parser.parse_args()
    sources = [args.mesh, args.baseline_bed, args.new_source, args.geometry, args.metadata]
    hashes = {str(path): sha(path) for path in sources}
    mesh = load_cvt_mesh_model(args.mesh)
    with np.load(args.baseline_bed) as data:
        baseline = data["legacy_m"]
        accepted = data["tectonic_m"]
    with np.load(args.new_source) as data:
        new_bed = data["final_elevation_m"]
    np.testing.assert_array_equal(new_bed, accepted)
    if baseline.shape != (mesh.num_cells,):
        raise ValueError("Bed and map have different cell counts")
    with np.load(args.geometry) as data:
        for axis in ["lat", "lon"]:
            np.testing.assert_allclose(
                [getattr(cell, axis) for cell in mesh.cells], data[axis], atol=1.1e-4, rtol=0
            )
    surface = np.array([cell.elevation for cell in mesh.cells])
    ice = np.array([cell.ice_thickness_m or 0.0 for cell in mesh.cells])
    np.testing.assert_allclose(
        surface - baseline, ice * (1 - ICE_LOAD_DEPRESSION), atol=2e-4, rtol=0
    )
    updated = surface + new_bed - baseline
    assert np.isfinite(updated).all()
    for cell, elevation in zip(mesh.cells, updated, strict=True):
        cell.elevation = float(elevation)
    meta = yaml.safe_load(args.metadata.read_text())
    width, height = int(meta["width"]), int(meta["height"])
    lo, hi, sea = [
        float(meta[key]) for key in ["elevation_min_m", "elevation_max_m", "sea_level_m"]
    ]
    lut = build_adaptive_terrain_lut(lo, hi, sea)
    indices = export_cell_index_grid(mesh, width, height)
    rgba = render_terrain_layer(mesh, indices, lut, lo, hi, sea)
    args.record.parent.mkdir(parents=True, exist_ok=True)
    backup = args.record.parent / "before/terrain.png"
    before_hash = None
    if args.output.exists():
        backup.parent.mkdir(parents=True, exist_ok=True)
        if backup.exists():
            raise FileExistsError(f"Backup already exists: {backup}")
        before_hash = sha(args.output)
        shutil.copy2(args.output, backup)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name("terrain.pending.png")
    save_rgba_png(rgba, temporary)
    with Image.open(temporary) as saved:
        np.testing.assert_array_equal(np.asarray(saved), rgba)
    temporary.replace(args.output)
    assert {str(path): sha(path) for path in sources} == hashes
    record = {
        "scope": "geological preview for the accepted bed update; reference ice retained",
        "source_sha256": hashes,
        "baseline_render_sha256": before_hash,
        "output": str(args.output),
        "output_sha256": sha(args.output),
        "grid_size_px": [width, height],
        "cells": mesh.num_cells,
        "new_bed_matches_accepted_200k_rebuild": True,
        "reference_ice_surface_relation_max_error_m": float(
            np.max(abs(surface - baseline - ice * (1 - ICE_LOAD_DEPRESSION)))
        ),
        "bed_delta_abs_max_m": float(np.max(abs(new_bed - baseline))),
        "render_roundtrip_equal": True,
        "canonical_mesh_updated": False,
        "climate_recomputed": False,
        "pending": (
            "joint geology, engine climate, canonical T42 GCM and climate downscaling refresh"
        ),
    }
    args.record.write_text(json.dumps(record, indent=2) + "\n")
    args.output.with_suffix(".png.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record, ensure_ascii=False))


if __name__ == "__main__":
    main()
