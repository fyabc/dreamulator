"""Render a short full-disk planet rotation video from an ``export globe`` run.

The cloud export directory must contain ``surface.png``, ``clouds.png`` and
``meta.json`` (the L5 atmosphere block is required).  The camera and star stay
fixed, so the terminator does not move; the planet's textures rotate one full
turn, then hold.  This is a rigid rotation: clouds do not evolve (L4).

Usage::

    uv run --with imageio-ffmpeg python scripts/media/spin_video.py \
        <clouds_dir> -o exports/spin/nacrea_spin_720p.mp4 --res 720 --seconds 8

The fast path reuses one atmosphere render for every frame; rendering 240
720p frames takes seconds after the initial preparation.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from dreamulator.map.export import (
    build_export_tree,
    export_cell_index_grid,
    load_cvt_mesh_model,
)
from dreamulator.media.atmosphere_render import AtmosphereModel, EclipseShadow
from dreamulator.media.globe_spin import SpinRenderer


def _load_meta(clouds_dir: Path) -> dict[str, Any]:
    path = clouds_dir / "meta.json"
    if not path.exists():
        raise SystemExit(f"missing {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"{path}: top level must be an object")
    return data


def _load_model(meta: dict[str, Any]) -> AtmosphereModel:
    atmosphere = meta.get("atmosphere")
    if not isinstance(atmosphere, dict):
        raise SystemExit(
            "meta.json has no atmosphere block — re-export with `export globe` "
            "(atmosphere enabled) first"
        )
    return AtmosphereModel(
        planet_radius_km=float(meta["radius_km"]),
        gravity_m_s2=float(atmosphere["gravity_m_s2"]),
        surface_pressure_atm=float(atmosphere["surface_pressure_atm"]),
        atmosphere_temperature_k=float(atmosphere["atmosphere_temperature_k"]),
        mean_molar_mass_kg_mol=float(atmosphere["mean_molar_mass_kg_mol"]),
        star_temperature_k=float(atmosphere["star_temperature_k"]),
        mie_scale=float(atmosphere.get("mie_scale", 1.0)),
        ozone_scale=float(atmosphere.get("ozone_scale", 1.0)),
        ground_albedo=float(atmosphere.get("ground_albedo", 0.3)),
    )


def _load_ocean_mask(
    meta: dict[str, Any], width: int, height: int, sea_level_m: float
) -> np.ndarray | None:
    provenance = meta.get("provenance") or {}
    mesh_path = provenance.get("mesh") if isinstance(provenance, dict) else None
    if not mesh_path:
        return None
    path = Path(str(mesh_path))
    if not path.exists():
        print(f"  ocean mask skipped: mesh not found at {path}", file=sys.stderr)
        return None
    mesh = load_cvt_mesh_model(path)
    indices = export_cell_index_grid(mesh, width, height, tree=build_export_tree(mesh))
    ocean = np.array([c.elevation < sea_level_m for c in mesh.cells], dtype=bool)
    return ocean[indices].astype(np.float64)


def _ffmpeg_exe() -> str:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg

        return str(imageio_ffmpeg.get_ffmpeg_exe())
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise SystemExit(
            "ffmpeg not found; rerun with:\n"
            "  uv run --with imageio-ffmpeg python scripts/media/spin_video.py ..."
        ) from exc


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("clouds_dir", type=Path, help="an export globe output directory")
    parser.add_argument("-o", "--output", type=Path, help="output .mp4 path")
    parser.add_argument("--seconds", type=float, default=8.0, help="clip length")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument(
        "--rotation-seconds",
        type=float,
        default=None,
        help="time for one full turn (default: seconds - 1, leaving a 1 s hold)",
    )
    parser.add_argument("--res", type=int, default=720, help="square globe render resolution")
    parser.add_argument("--width", type=int, default=1280, help="output frame width")
    parser.add_argument("--height", type=int, default=720, help="output frame height")
    parser.add_argument("--crf", type=int, default=18, help="H.264 quality (lower = better)")
    parser.add_argument("--no-ocean", action="store_true", help="skip the ocean mask / sun glint")
    parser.add_argument(
        "--poster", type=Path, help="save first/last frames as PNG next to this path"
    )
    args = parser.parse_args()

    if args.res > args.width or args.res > args.height:
        raise SystemExit("--res must fit inside the output frame")
    clouds_dir: Path = args.clouds_dir
    meta = _load_meta(clouds_dir)
    model = _load_model(meta)
    atmosphere = meta["atmosphere"]
    eclipse_meta = meta.get("eclipse")
    eclipse_shadow = EclipseShadow(**eclipse_meta) if isinstance(eclipse_meta, dict) else None
    globe = meta.get("globe") or {}

    surface = (
        np.asarray(Image.open(clouds_dir / "surface.png").convert("RGB"), dtype=np.float64) / 255.0
    )
    low_path = clouds_dir / "clouds_low.png"
    if not low_path.exists():
        low_path = clouds_dir / "clouds.png"
    cloud_rgba = np.asarray(Image.open(low_path).convert("RGBA"), dtype=np.float64)
    cloud_alpha = cloud_rgba[..., 3] / 255.0
    cirrus_path = clouds_dir / "clouds_cirrus.png"
    cloud_high = None
    if cirrus_path.exists():
        cirrus_rgba = np.asarray(Image.open(cirrus_path).convert("RGBA"), dtype=np.float64)
        cloud_high = cirrus_rgba[..., 3] / 255.0
    height, width = surface.shape[:2]
    sea_level = float(meta.get("sea_level_m", 0.0))
    ocean = None if args.no_ocean else _load_ocean_mask(meta, width, height, sea_level)

    start = time.perf_counter()
    renderer = SpinRenderer(
        surface,
        cloud_alpha,
        cloud_high,
        res=args.res,
        center_lon_deg=float(globe.get("center_lon_deg", 90.0)),
        center_lat_deg=float(globe.get("center_lat_deg", 15.0)),
        sun_lon_deg=float(globe.get("sun_lon_deg", 65.0)),
        sun_lat_deg=float(globe.get("sun_lat_deg", 20.0)),
        model=model,
        cloud_altitude_km=float(atmosphere.get("cloud_altitude_km", 4.0)),
        cirrus_altitude_km=float(atmosphere.get("cirrus_altitude_km", 9.0)),
        cirrus_shadow_strength=float(atmosphere.get("cirrus_shadow_strength", 0.6)),
        eclipse_shadow=eclipse_shadow,
        cloud_shadows=bool(atmosphere.get("cloud_shadows", True)),
        ocean_mask=ocean,
        sun_glint=bool(atmosphere.get("sun_glint", True)),
        water_roughness=float(atmosphere.get("water_roughness", 0.08)),
        multiple_scattering=bool(atmosphere.get("multiple_scattering", True)),
        exposure=str(atmosphere.get("exposure", "white_balance")),
    )
    print(f"prepared in {time.perf_counter() - start:.1f}s")

    total = max(int(round(args.seconds * args.fps)), 2)
    rotation_seconds = (
        args.rotation_seconds if args.rotation_seconds is not None else max(args.seconds - 1.0, 0.1)
    )
    rotation_frames = max(1, min(total - 1, int(round(rotation_seconds * args.fps))))
    out = args.output or Path("exports") / "spin" / f"{clouds_dir.name}_spin_{args.res}p.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)

    canvas = np.zeros((args.height, args.width, 3), dtype=np.uint8)
    y0 = (args.height - args.res) // 2
    x0 = (args.width - args.res) // 2

    exe = _ffmpeg_exe()
    cmd = [
        exe,
        "-y",
        "-loglevel",
        "error",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{args.width}x{args.height}",
        "-r",
        str(args.fps),
        "-i",
        "-",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        str(args.crf),
        "-pix_fmt",
        "yuv420p",
        str(out),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    assert proc.stdin is not None

    start = time.perf_counter()
    poster_frames: list[np.ndarray] = []
    try:
        for i in range(total):
            offset = -360.0 * i / rotation_frames if i < rotation_frames else -360.0
            frame = renderer.frame(offset)
            canvas[y0 : y0 + args.res, x0 : x0 + args.res] = frame
            proc.stdin.write(canvas.tobytes())
            if i in (0, total - 1):
                poster_frames.append(canvas.copy())
            if i % 30 == 0:
                elapsed = time.perf_counter() - start
                print(f"  frame {i}/{total} ({elapsed:.1f}s)")
    finally:
        proc.stdin.close()
        proc.wait()

    if args.poster is not None:
        args.poster.parent.mkdir(parents=True, exist_ok=True)
        stem = args.poster.with_suffix("")
        Image.fromarray(poster_frames[0], "RGB").save(str(stem) + "_first.png")
        Image.fromarray(poster_frames[-1], "RGB").save(str(stem) + "_last.png")

    elapsed = time.perf_counter() - start
    print(f"wrote {out} ({out.stat().st_size / 1024 / 1024:.1f} MB) in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
