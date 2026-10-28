"""Render a physical window of verified TD chunks at their native overview scale."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from pathlib import Path

import numpy as np
from PIL import Image

from dreamulator.map.td_canvas_mosaic import render_mosaic


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("canvas", type=Path)
    parser.add_argument("--view", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--receipt", required=True, action="append", type=Path)
    parser.add_argument("--centre-x-km", required=True, type=float)
    parser.add_argument("--centre-y-km", required=True, type=float)
    parser.add_argument("--width-km", default=1000.5, type=float)
    parser.add_argument("--step", default=4, type=int)
    parser.add_argument("--workers", default=8, type=int)
    args = parser.parse_args()
    if args.output.exists() or args.view.exists():
        raise FileExistsError("Choose a fresh view and output path")
    meta = json.loads((args.canvas / "canvas.json").read_text(encoding="utf-8"))
    geometry = meta["geometry"]
    chunk_px = int(geometry["chunk_px"])
    pixel_km = float(geometry["px_km"]) * args.step
    if args.width_km <= 0 or args.step < 1 or chunk_px % args.step:
        raise ValueError("Width must be positive and step must divide the chunk size")
    half_km = float(geometry["half_km"])
    r0 = round((half_km - args.centre_y_km - args.width_km / 2) / pixel_km)
    c0 = round((half_km + args.centre_x_km - args.width_km / 2) / pixel_km)
    side_px = round(args.width_km / pixel_km)
    r1, c1 = r0 + side_px, c0 + side_px
    render_chunk_px = chunk_px // args.step
    hashes: dict[str, str] = {}
    for receipt in args.receipt:
        for name, value in json.loads(receipt.read_text())["chunk_sha256"].items():
            if name in hashes and hashes[name] != value:
                raise ValueError(f"Conflicting receipt hashes for {name}")
            hashes[name] = value
    core = {
        (i, j)
        for i in range(r0 // render_chunk_px, math.ceil(r1 / render_chunk_px))
        for j in range(c0 // render_chunk_px, math.ceil(c1 / render_chunk_px))
    }
    # Retain a surrounding chunk for the renderer's shading halo where available.
    nearby = {(i + di, j + dj) for i, j in core for di in (-1, 0, 1) for dj in (-1, 0, 1)}
    verified = {}
    for i, j in sorted(nearby):
        name = f"r{i:03d}_c{j:03d}.npy"
        source = args.canvas / "chunks" / name
        if not source.exists() and (i, j) not in core:
            continue
        if not source.exists():
            raise FileNotFoundError(f"Missing window chunk: {source}")
        actual = digest(source)
        if hashes.get(name) != actual:
            raise ValueError(f"Chunk receipt mismatch: {source}")
        if (i, j) in core and not np.isfinite(np.load(source, mmap_mode="r")).all():
            raise ValueError(f"Nonfinite terrain inside window: {source}")
        verified[name] = actual
    (args.view / "chunks").mkdir(parents=True)
    for name in verified:
        (args.view / "chunks" / name).symlink_to((args.canvas / "chunks" / name).resolve())
    meta["chunks"] = [[int(name[1:4]), int(name[6:9])] for name in verified]
    (args.view / "canvas.json").write_text(json.dumps(meta, indent=2) + "\n")
    mosaic_path = args.output.with_name(args.output.stem + "-uncropped.png")
    started = time.perf_counter()
    side = render_mosaic(
        args.view,
        mosaic_path,
        step=args.step,
        style="relief",
        palette="pastel",
        sea="carto",
        exaggeration=4,
        workers=args.workers,
    )
    left = c0 - side["canvas_cols"][0] // args.step
    top = r0 - side["canvas_rows"][0] // args.step
    Image.MAX_IMAGE_PIXELS = None
    with Image.open(mosaic_path) as mosaic:
        if not (
            0 <= left < left + side_px <= mosaic.width and 0 <= top < top + side_px <= mosaic.height
        ):
            raise ValueError("Requested crop lies outside the rendered window")
        crop = mosaic.crop((left, top, left + side_px, top + side_px))
        crop.save(args.output)
        with Image.open(args.output) as saved:
            if not np.array_equal(np.asarray(crop), np.asarray(saved)):
                raise ValueError("Saved crop differs from rendered pixels")
        crop.thumbnail((1400, 1400), Image.Resampling.LANCZOS)
        preview = args.output.with_name(args.output.stem + "-preview.jpg")
        crop.save(preview, quality=95)
    record = {
        "canvas": str(args.canvas),
        "canvas_metadata_sha256": digest(args.canvas / "canvas.json"),
        "chunk_sha256": verified,
        "receipts": [str(p) for p in args.receipt],
        "requested_centre_xy_km": [args.centre_x_km, args.centre_y_km],
        "actual_bounds_xy_km": [
            c0 * pixel_km - half_km,
            half_km - r1 * pixel_km,
            c1 * pixel_km - half_km,
            half_km - r0 * pixel_km,
        ],
        "pixel_m": pixel_km * 1000,
        "image_size_px": [side_px, side_px],
        "crop_matches_rendered_pixels": True,
        "td_regenerated": False,
        "render_wall_s": time.perf_counter() - started,
        "render": side,
        "output_sha256": digest(args.output),
        "preview_sha256": digest(preview),
    }
    Path(str(args.output) + ".json").write_text(json.dumps(record, indent=2) + "\n")
    mosaic_path.unlink()
    Path(str(mosaic_path) + ".json").unlink()
    print(json.dumps({k: v for k, v in record.items() if k not in {"chunk_sha256", "render"}}))


if __name__ == "__main__":
    main()
