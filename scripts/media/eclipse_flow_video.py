"""Eclipse video: Aegis occults the star over one full passage, start to end.

Three motions share one timeline, all driven by the weather pack's own clock
(``hours_since_start``): the sun's position comes from the pack's per-frame
sub-solar point (the solar-day march), the eclipse phase is the sun's angular
distance to the sub-Aegis zenith — nacrea is tidally locked, so Aegis hangs
at longitude 0° on the equator and the impact parameter is
``b = D_MOON · sin(psi)`` with psi that distance — and the clouds advect on
the pack's per-frame winds.  The terrain and camera stay fixed (tidally
locked: no rotation to draw).  Mid-eclipse lands at the video's centre; with
Aegis's shadow wider than the planet, the whole day side drops into totality
around mid-eclipse.

Usage:
    uv run --with imageio-ffmpeg python scripts/media/eclipse_flow_video.py \
        exports/globe/nacrea-gcm-t42-712-f273-clear \
        -o exports/video/eclipse/nacrea_eclipse_flow.mp4 \
        --weather-pack exports/weather/nacrea-gcm-t42-712 \
        --poster exports/video/eclipse/nacrea_eclipse_flow-poster
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

from dreamulator.gcm.weather_pack import load_pack
from dreamulator.media.atmosphere_render import AtmosphereModel, render_globe_atmosphere
from dreamulator.media.cloud_advection import advect_equirect, advection_substeps
from dreamulator.media.eclipse_geometry import eclipse_mask
from dreamulator.media.weather_conditioning import (
    WeatherFrame,
    blend_weather_frames,
    frame_from_pack,
)

# nacrea/Aegis canon (system catalog + design-notes 0005).
R_AEGIS = 71355.0
R_STAR = 426116.0
D_STAR = 54573303.0
D_MOON = 723300.0
#: Sub-Aegis zenith: longitude 0 on the equator (tidally locked; canon).
AEGIS_LON, AEGIS_LAT = 0.0, 0.0
#: The eclipse band runs toward the sub-Aegis point from the sub-solar point.
ALPHA_A = math.asin(R_AEGIS / D_MOON)
ALPHA_S = math.asin(R_STAR / D_STAR)


def _resize(field: np.ndarray, width: int, height: int) -> np.ndarray:
    if field.shape[:2] == (height, width) and (field.ndim == 2 or field.shape[2] == 3):
        return field
    arr = np.clip(field * 255.0, 0.0, 255.0).astype(np.uint8)
    image = Image.fromarray(arr, "L" if field.ndim == 2 else "RGB")
    return np.asarray(image.resize((width, height), Image.LANCZOS), dtype=np.float64) / 255.0


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
            "  uv run --with imageio-ffmpeg python scripts/media/eclipse_flow_video.py ..."
        ) from exc


def _zenith_distance(sun_lon: float, sun_lat: float) -> float:
    """Angular distance (deg) between the sub-solar point and the Aegis zenith."""
    s = _great_circle(sun_lon, sun_lat)
    a = _great_circle(AEGIS_LON, AEGIS_LAT)
    return math.degrees(math.acos(max(-1.0, min(1.0, float(np.dot(s, a))))))


def _great_circle(lon_deg: float, lat_deg: float) -> np.ndarray:
    lon, lat = math.radians(lon_deg), math.radians(lat_deg)
    return np.array([math.cos(lat) * math.cos(lon), math.sin(lat), math.cos(lat) * math.sin(lon)])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("export_dir", type=Path, help="still export dir (meta.json + PNGs)")
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--weather-pack", type=Path, required=True)
    parser.add_argument("--frame", type=float, default=None, help="pack frame at mid-eclipse")
    parser.add_argument("--sim-hours", type=float, default=3.6, help="eclipse window length")
    parser.add_argument("--seconds", type=float, default=8.0)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--res", type=int, default=1600, help="square globe resolution")
    parser.add_argument("--width", type=int, default=1600)
    parser.add_argument("--height", type=int, default=1600)
    parser.add_argument("--texture-width", type=int, default=2048)
    parser.add_argument("--poster", type=Path, default=None)
    args = parser.parse_args()

    export_dir = args.export_dir
    meta: dict[str, Any] = json.loads((export_dir / "meta.json").read_text(encoding="utf-8"))
    atmosphere = meta["atmosphere"]
    model = AtmosphereModel(
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
    surface = np.asarray(Image.open(export_dir / "surface.png").convert("RGB"), dtype=np.float64)
    surface /= 255.0
    tex_w, tex_h = args.texture_width, args.texture_width // 2
    # render_globe_atmosphere requires all layers on one grid; the video works
    # at the advection width, so the 8K surface comes down with the clouds.
    surface = _resize(surface, tex_w, tex_h)
    deck = _resize(
        np.asarray(Image.open(export_dir / "clouds_low.png").convert("RGBA"))[..., 3] / 255.0,
        tex_w,
        tex_h,
    )
    cirrus = _resize(
        np.asarray(Image.open(export_dir / "clouds_cirrus.png").convert("RGBA"))[..., 3] / 255.0,
        tex_w,
        tex_h,
    )

    # Camera fixed on the surface frame (tidally locked: the terrain does not
    # rotate under a surface-bound camera); the sun marches across the view.
    globe = meta.get("globe") or {}
    center_lon = float(globe.get("center_lon_deg", 0.0))
    center_lat = float(globe.get("center_lat_deg", 15.0))

    pack = load_pack(args.weather_pack)
    interval_h = float((pack.meta.get("calendar") or {}).get("frame_interval_h", 6.0))
    n_pack = int(pack.meta["frames"])
    tmeta = pack.meta["time"]
    sun_lons = [((float(v) + 180.0) % 360.0) - 180.0 for v in tmeta["subsolar_lon_deg"]]
    sun_lats = [float(v) for v in tmeta["subsolar_lat_deg"]]

    # Find mid-eclipse: the pack frame where the sun passes closest to the
    # Aegis zenith (the star must clear the disk: psi < ~5.2° for totality).
    if args.frame is not None:
        mid_frame = float(args.frame)
    else:
        zdist = [_zenith_distance(sun_lons[t], sun_lats[t]) for t in range(n_pack)]
        coarse = float(int(np.argmin(zdist)))
        # The pack samples every 6 h but the whole eclipse lasts ~2.6 h, so
        # refine the mid-eclipse on the interpolated sub-solar track.
        grid = coarse + np.linspace(-1.0, 1.0, 201)
        grid = grid[(grid >= 0.0) & (grid <= n_pack - 1)]
        fine = [
            (
                _zenith_distance(
                    (1.0 - f % 1.0) * sun_lons[int(f)] + (f % 1.0) * sun_lons[int(f) + 1],
                    (1.0 - f % 1.0) * sun_lats[int(f)] + (f % 1.0) * sun_lats[int(f) + 1],
                ),
                float(f),
            )
            for f in grid
        ]
        mid_frame = min(fine)[1]
    psi_mid = _zenith_distance(
        (1.0 - mid_frame % 1.0) * sun_lons[int(mid_frame)]
        + (mid_frame % 1.0) * sun_lons[min(int(mid_frame) + 1, n_pack - 1)],
        (1.0 - mid_frame % 1.0) * sun_lats[int(mid_frame)]
        + (mid_frame % 1.0) * sun_lats[min(int(mid_frame) + 1, n_pack - 1)],
    )
    contact_deg = math.degrees(ALPHA_A + ALPHA_S)
    half_frames = args.sim_hours / 2.0 / interval_h
    start_frame = mid_frame - half_frames
    end_frame = mid_frame + half_frames
    if start_frame < 0.0 or end_frame > n_pack - 1:
        raise SystemExit(f"window frames {start_frame:g}…{end_frame:g} leave the pack")
    print(
        f"mid-eclipse frame {mid_frame:g}: sun-zenith distance {psi_mid:.2f}° "
        f"(contact at {contact_deg:.2f}°), window frames {start_frame:g}…{end_frame:g}"
    )

    frame_cache: dict[int, WeatherFrame] = {}

    def pack_frame(f: float) -> WeatherFrame:
        base = int(math.floor(f))
        frac = f - base
        if base not in frame_cache:
            frame_cache[base] = frame_from_pack(pack, base, tex_w, tex_h)
        if frac == 0.0:
            return frame_cache[base]
        if base + 1 not in frame_cache:
            frame_cache[base + 1] = frame_from_pack(pack, base + 1, tex_w, tex_h)
        return blend_weather_frames(frame_cache[base], frame_cache[base + 1], frac)

    total = max(int(round(args.seconds * args.fps)), 2)
    dt_s = args.sim_hours * 3600.0 / (total - 1)
    canvas = np.zeros((args.height, args.width, 3), dtype=np.uint8)
    y0 = x0 = 0
    if args.height > args.res:
        y0 = (args.height - args.res) // 2
    if args.width > args.res:
        x0 = (args.width - args.res) // 2

    out = args.output
    out.parent.mkdir(parents=True, exist_ok=True)
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
        "18",
        str(out),
    ]
    posters: list[np.ndarray] = []
    start = time.perf_counter()
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for i in range(total):
            t_frac = i / (total - 1)
            f = start_frame + t_frac * (end_frame - start_frame)
            f_mid = start_frame + (i + 0.5) / total * (end_frame - start_frame)
            wf = pack_frame(f_mid)
            deck_east = wf.wind_east
            deck_north = wf.wind_north
            high_east = wf.wind_east_high
            high_north = wf.wind_north_high
            substeps = advection_substeps(
                deck_east, deck_north, dt_seconds=dt_s, radius_km=model.planet_radius_km
            )
            deck = advect_equirect(
                deck,
                deck_east,
                deck_north,
                dt_seconds=dt_s,
                radius_km=model.planet_radius_km,
                substeps=substeps,
            )
            cirrus = advect_equirect(
                cirrus,
                high_east,
                high_north,
                dt_seconds=dt_s,
                radius_km=model.planet_radius_km,
                substeps=substeps,
            )

            # Sun at this instant from the pack's own sub-solar track.
            base = int(math.floor(f))
            frac = f - base
            sun_lon = (1.0 - frac) * sun_lons[base] + frac * sun_lons[min(base + 1, n_pack - 1)]
            sun_lat = (1.0 - frac) * sun_lats[base] + frac * sun_lats[min(base + 1, n_pack - 1)]
            psi = _zenith_distance(sun_lon, sun_lat)
            b_km = D_MOON * math.sin(math.radians(psi))
            field = eclipse_mask(
                args.res,
                planet_km=model.planet_radius_km,
                b_km=b_km,
                center_lon_deg=center_lon,
                center_lat_deg=center_lat,
                sun_lon_deg=sun_lon,
                sun_lat_deg=sun_lat,
                shadow_lon_deg=AEGIS_LON,
                shadow_lat_deg=AEGIS_LAT,
                occluder_radius_km=R_AEGIS,
                occluder_distance_km=D_MOON,
                star_radius_km=R_STAR,
                star_distance_km=D_STAR,
            )
            frame = render_globe_atmosphere(
                surface,
                deck,
                cloud_alpha_high=cirrus,
                res=args.res,
                center_lon_deg=center_lon,
                center_lat_deg=center_lat,
                sun_lon_deg=sun_lon,
                sun_lat_deg=sun_lat,
                model=model,
                eclipse_field=field,
                sun_glint=False,
            )
            canvas[y0 : y0 + args.res, x0 : x0 + args.res] = frame
            proc.stdin.write(canvas.tobytes())
            if i in (0, total - 1):
                posters.append(canvas.copy())
            if i % 30 == 0:
                elapsed = time.perf_counter() - start
                print(f"  frame {i}/{total} ({elapsed:.1f}s) psi={psi:5.2f}° b={b_km:8.0f} km")
    finally:
        proc.stdin.close()
        proc.wait()

    if args.poster is not None:
        args.poster.parent.mkdir(parents=True, exist_ok=True)
        stem = args.poster.with_suffix("")
        Image.fromarray(posters[0], "RGB").save(str(stem) + "_first.png")
        Image.fromarray(posters[-1], "RGB").save(str(stem) + "_last.png")
    print(f"wrote {out} in {time.perf_counter() - start:.1f}s")


if __name__ == "__main__":
    main()
