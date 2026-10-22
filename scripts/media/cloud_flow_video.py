"""Render a short cloud-evolution clip (L4 prototype) from an ``export clouds`` run.

The cloud alpha is advected with the engine's annual-mean wind field
(semi-Lagrangian + BFECC) while the camera and star stay fixed, so the
terminator does not move.  This is look-dev: the wind is a placeholder until
the L1 layer pack supplies 6-hourly winds; cloud condensation/evaporation are
not modelled, only the existing texture is transported.

Usage::

    uv run --with imageio-ffmpeg python scripts/media/cloud_flow_video.py \
        <clouds_dir> -o exports/spin/nacrea_cloudflow_720p.mp4 \
        --res 720 --seconds 8 --sim-hours 24
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
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
from dreamulator.media.atmosphere_render import AtmosphereModel
from dreamulator.media.cloud_advection import advect_equirect, advection_substeps
from dreamulator.media.cloud_render import conditioning_grids
from dreamulator.media.cyclone_render import Cyclone, cyclone_wind_field
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
        raise SystemExit("meta.json has no atmosphere block — re-export with `export clouds` first")
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


def _mesh_path(meta: dict[str, Any]) -> Path:
    provenance = meta.get("provenance") or {}
    mesh_path = provenance.get("mesh") if isinstance(provenance, dict) else None
    if not mesh_path:
        raise SystemExit("meta.json has no provenance.mesh; cannot build the wind field")
    path = Path(str(mesh_path))
    if not path.exists():
        raise SystemExit(f"mesh not found at {path}")
    return path


def _resize(field: np.ndarray, width: int, height: int) -> np.ndarray:
    if field.shape == (height, width):
        return field
    image = Image.fromarray(np.clip(field * 255.0, 0.0, 255.0).astype(np.uint8), "L")
    return np.asarray(image.resize((width, height), Image.LANCZOS), dtype=np.float64) / 255.0


def _load_cyclones(meta: dict[str, Any]) -> list[Cyclone]:
    tracks = (meta.get("cyclones") or {}).get("tracks") or []
    return [Cyclone(**track) for track in tracks if isinstance(track, dict)]


def _sample_wind(field: np.ndarray, latitude_deg: float, longitude_deg: float) -> float:
    """Bilinear sample of an equirectangular field at one point."""
    height, width = field.shape
    row = (90.0 - latitude_deg) / 180.0 * height - 0.5
    col = (longitude_deg + 180.0) / 360.0 * width - 0.5
    r0 = int(math.floor(row))
    c0 = int(math.floor(col))
    fr = row - r0
    fc = col - c0
    r0c = min(max(r0, 0), height - 1)
    r1c = min(max(r0 + 1, 0), height - 1)
    c0w = c0 % width
    c1w = (c0 + 1) % width
    return float(
        field[r0c, c0w] * (1.0 - fr) * (1.0 - fc)
        + field[r1c, c0w] * fr * (1.0 - fc)
        + field[r0c, c1w] * (1.0 - fr) * fc
        + field[r1c, c1w] * fr * fc
    )


def _advance_centres(
    centres: list[tuple[float, float]],
    wind_east: np.ndarray,
    wind_north: np.ndarray,
    *,
    dt_seconds: float,
    radius_km: float,
) -> list[tuple[float, float]]:
    """Move each storm centre with the local environment wind (Lagrangian)."""
    radius_m = radius_km * 1000.0
    moved: list[tuple[float, float]] = []
    for latitude, longitude in centres:
        u = _sample_wind(wind_east, latitude, longitude)
        v = _sample_wind(wind_north, latitude, longitude)
        cos_lat = max(math.cos(math.radians(latitude)), 1e-3)
        longitude = (
            longitude + math.degrees(u * dt_seconds / (radius_m * cos_lat)) + 180.0
        ) % 360.0 - 180.0
        latitude = min(max(latitude + math.degrees(v * dt_seconds / radius_m), -89.5), 89.5)
        moved.append((latitude, longitude))
    return moved


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
            "  uv run --with imageio-ffmpeg python scripts/media/cloud_flow_video.py ..."
        ) from exc


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("clouds_dir", type=Path, help="an export clouds output directory")
    parser.add_argument("-o", "--output", type=Path, help="output .mp4 path")
    parser.add_argument("--seconds", type=float, default=8.0, help="clip length")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--sim-hours", type=float, default=24.0, help="simulated cloud time")
    parser.add_argument("--res", type=int, default=720, help="square globe render resolution")
    parser.add_argument("--width", type=int, default=1280, help="output frame width")
    parser.add_argument("--height", type=int, default=720, help="output frame height")
    parser.add_argument(
        "--texture-width",
        type=int,
        default=2048,
        help="cloud/wind advection grid width (height = width / 2)",
    )
    parser.add_argument(
        "--substeps",
        type=int,
        default=None,
        help="advection substeps per frame (default: automatic, capped at 8)",
    )
    parser.add_argument("--no-bfecc", action="store_true", help="plain semi-Lagrangian step")
    parser.add_argument(
        "--no-vortex",
        action="store_true",
        help="advect with the environment wind only (no storm circulation)",
    )
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
    globe = meta.get("globe") or {}
    mesh = load_cvt_mesh_model(_mesh_path(meta))
    tree = build_export_tree(mesh)
    sea_level = float(meta.get("sea_level_m", 0.0))

    surface = (
        np.asarray(Image.open(clouds_dir / "surface.png").convert("RGB"), dtype=np.float64) / 255.0
    )
    height, width = surface.shape[:2]
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

    tex_width = max(2, args.texture_width // 2 * 2)
    tex_height = tex_width // 2
    indices = export_cell_index_grid(mesh, tex_width, tex_height, tree=tree)
    _, wind_east, wind_north, _, _ = conditioning_grids(mesh, indices)
    cloud = _resize(cloud_alpha, tex_width, tex_height)
    if cloud_high is not None:
        cloud_high = _resize(cloud_high, tex_width, tex_height)
    cyclones = [] if args.no_vortex else _load_cyclones(meta)
    centres = [(cyc.lat_deg, cyc.lon_deg) for cyc in cyclones]
    if cyclones:
        print(f"vortex: {len(cyclones)} storm circulation(s) added to the advection wind")

    ocean = None
    if not args.no_ocean:
        surface_indices = export_cell_index_grid(mesh, width, height, tree=tree)
        ocean_cells = np.array([c.elevation < sea_level for c in mesh.cells], dtype=bool)
        ocean = ocean_cells[surface_indices].astype(np.float64)

    start = time.perf_counter()
    renderer = SpinRenderer(
        surface,
        cloud,
        cloud_high,
        res=args.res,
        center_lon_deg=float(globe.get("center_lon_deg", 90.0)),
        center_lat_deg=float(globe.get("center_lat_deg", 15.0)),
        sun_lon_deg=float(globe.get("sun_lon_deg", 65.0)),
        sun_lat_deg=float(globe.get("sun_lat_deg", 20.0)),
        model=model,
        cloud_altitude_km=float(atmosphere.get("cloud_altitude_km", 4.0)),
        cirrus_altitude_km=float(atmosphere.get("cirrus_altitude_km", 9.0)),
        cloud_shadows=bool(atmosphere.get("cloud_shadows", True)),
        ocean_mask=ocean,
        sun_glint=bool(atmosphere.get("sun_glint", True)),
        water_roughness=float(atmosphere.get("water_roughness", 0.08)),
        multiple_scattering=bool(atmosphere.get("multiple_scattering", True)),
        exposure=str(atmosphere.get("exposure", "white_balance")),
    )
    print(f"prepared renderer in {time.perf_counter() - start:.1f}s")

    total = max(int(round(args.seconds * args.fps)), 2)
    dt = args.sim_hours * 3600.0 / (total - 1)
    print(
        f"advection: {args.sim_hours:g} h over {total} frames at "
        f"{tex_width}x{tex_height}, vortex={'on' if cyclones else 'off'}, "
        f"cirrus={'on' if cloud_high is not None else 'off'}"
    )

    out = args.output or Path("exports") / "spin" / f"{clouds_dir.name}_cloudflow_{args.res}p.mp4"
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
    posters: list[np.ndarray] = []
    try:
        for i in range(total):
            if i > 0:
                if cyclones:
                    centres = _advance_centres(
                        centres,
                        wind_east,
                        wind_north,
                        dt_seconds=dt,
                        radius_km=model.planet_radius_km,
                    )
                    vortex_east, vortex_north = cyclone_wind_field(
                        cyclones,
                        height=tex_height,
                        width=tex_width,
                        radius_km=model.planet_radius_km,
                        centers=centres,
                    )
                    total_east = wind_east + vortex_east
                    total_north = wind_north + vortex_north
                else:
                    total_east = wind_east
                    total_north = wind_north
                substeps = args.substeps or advection_substeps(
                    total_east,
                    total_north,
                    dt_seconds=dt,
                    radius_km=model.planet_radius_km,
                )
                cloud = advect_equirect(
                    cloud,
                    total_east,
                    total_north,
                    dt_seconds=dt,
                    radius_km=model.planet_radius_km,
                    substeps=substeps,
                    bfecc=not args.no_bfecc,
                )
                if cloud_high is not None:
                    cloud_high = advect_equirect(
                        cloud_high,
                        total_east,
                        total_north,
                        dt_seconds=dt,
                        radius_km=model.planet_radius_km,
                        substeps=substeps,
                        bfecc=not args.no_bfecc,
                    )
            renderer.set_cloud(cloud, cloud_high)
            frame = renderer.frame(0.0)
            canvas[y0 : y0 + args.res, x0 : x0 + args.res] = frame
            proc.stdin.write(canvas.tobytes())
            if i in (0, total - 1):
                posters.append(canvas.copy())
            if i % 30 == 0:
                elapsed = time.perf_counter() - start
                print(f"  frame {i}/{total} ({elapsed:.1f}s)")
    finally:
        proc.stdin.close()
        proc.wait()

    if args.poster is not None:
        args.poster.parent.mkdir(parents=True, exist_ok=True)
        stem = args.poster.with_suffix("")
        Image.fromarray(posters[0], "RGB").save(str(stem) + "_first.png")
        Image.fromarray(posters[-1], "RGB").save(str(stem) + "_last.png")

    elapsed = time.perf_counter() - start
    print(f"wrote {out} ({out.stat().st_size / 1024 / 1024:.1f} MB) in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
