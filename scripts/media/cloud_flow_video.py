"""Render a short cloud-evolution clip (L4 prototype) from an ``export globe`` run.

The cloud alpha is advected (semi-Lagrangian + BFECC) while the camera and
star stay fixed, so the terminator does not move.  With ``--weather-pack``
the advection follows the model's own 6-hourly winds: the low/mid cloud shell
rides the mid-level flow (``u_mid``/``v_mid``, sigma ≈ 0.57), the cirrus
shell the high-level flow (``u_high``/``v_high``, sigma ≈ 0.32), both
linearly interpolated between pack frames at the clip's time step and
evaluated at each step's midpoint.  Without a pack the annual-mean mesh wind
is the placeholder.  Cloud condensation/evaporation are not modelled, only
the existing texture is transported.

``--storm-mode`` picks the storm treatment.  ``rigid`` (default) advects the
ambient deck with the environment wind only and re-composites the pack's
storms every frame at their track positions: the template rotates rigidly at
the cloud-pattern rate (``pattern_spin_rate_rad_s``), so the spiral keeps its
shape instead of being differentially wound by the eye-wall wind (a passive
tracer there turns ~5 revolutions/day) — feed it a storm-free (``export
globe`` without ``--cyclones``) still.  ``vortex`` is the older path: the
storms' circulation is added to the advection wind and the input still's
stamped templates shear with it.  ``none`` draws no storms at all.

Usage::

    uv run --with imageio-ffmpeg python scripts/media/cloud_flow_video.py \
        <clouds_dir> -o exports/video/cloudflow/<name>.mp4 \
        --res 720 --seconds 8 --sim-hours 24 \
        --weather-pack exports/weather/nacrea-gcm-t42-712
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from dreamulator.gcm.weather_pack import load_pack
from dreamulator.map.export import (
    build_export_tree,
    export_cell_index_grid,
    load_cvt_mesh_model,
)
from dreamulator.media.atmosphere_render import AtmosphereModel, EclipseShadow
from dreamulator.media.cloud_advection import advect_equirect, advection_substeps
from dreamulator.media.cloud_render import cloud_erosion_field, conditioning_grids
from dreamulator.media.cyclone_render import (
    Cyclone,
    cyclone_alpha,
    cyclone_clear,
    cyclone_envelope,
    cyclone_wind_field,
    pattern_spin_rate_rad_s,
    template_fbm_stack,
)
from dreamulator.media.cyclone_tracks import (
    TropicalCycloneSource,
    weather_cyclones_at_frame,
)
from dreamulator.media.globe_spin import SpinRenderer
from dreamulator.media.weather_conditioning import (
    WeatherFrame,
    blend_weather_frames,
    frame_from_pack,
)


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
        raise SystemExit("meta.json has no atmosphere block — re-export with `export globe` first")
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


def _composite_storms(
    base: np.ndarray,
    storms: list[Cyclone],
    *,
    radius_km: float,
    seed: int,
    fbm_stack: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray],
) -> np.ndarray:
    """Re-composite the pack's storms over the advected ambient deck.

    Mirrors the still export's L3 pass (eye/slot clearing, extratropical
    envelope lerp, tropical screen) with the storms' current positions,
    intensities and rigid pattern spin.  The ambient deck is not pre-warped:
    ``warp_cyclone_texture`` is a still-image treatment and re-warping a
    re-composited template every frame would double-deform it.
    """
    height, width = base.shape
    clear = cyclone_clear(storms, height=height, width=width, radius_km=radius_km)
    out = base * (1.0 - clear)
    extras = [c for c in storms if c.kind != "tropical"]
    if extras:
        env = cyclone_envelope(
            extras, height=height, width=width, radius_km=radius_km, noise=fbm_stack[0]
        )
        tmpl = cyclone_alpha(
            extras,
            height=height,
            width=width,
            radius_km=radius_km,
            seed=seed,
            erosion=cloud_erosion_field(base),
            fbm_stack=fbm_stack,
        )
        out = out * (1.0 - 0.90 * env) + 0.90 * env * tmpl
    trop = [c for c in storms if c.kind == "tropical"]
    if trop:
        env = cyclone_envelope(
            trop, height=height, width=width, radius_km=radius_km, noise=fbm_stack[0]
        )
        tmpl = cyclone_alpha(
            trop, height=height, width=width, radius_km=radius_km, seed=seed, fbm_stack=fbm_stack
        )
        out = 1.0 - (1.0 - out) * (1.0 - 0.95 * env * tmpl)
    return np.clip(out, 0.0, 1.0)


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
    parser.add_argument("clouds_dir", type=Path, help="an export globe output directory")
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
        "--interp",
        choices=["linear", "cubic"],
        default="cubic",
        help="semi-Lagrangian interpolation (cubic limits diffusion; linear is faster)",
    )
    parser.add_argument(
        "--storm-mode",
        choices=["rigid", "vortex", "none"],
        default="rigid",
        help="storm treatment: 'rigid' re-composites the pack's storms every "
        "frame at their track positions, rotating rigidly at the pattern rate "
        "(input: a storm-free still); 'vortex' adds the storm circulations to "
        "the advection wind (input: the cyclone still); 'none' draws no storms",
    )
    parser.add_argument(
        "--no-vortex",
        action="store_true",
        help="deprecated alias for --storm-mode none",
    )
    parser.add_argument(
        "--storm-seed",
        type=int,
        default=None,
        help="override the tropical-cyclone sampler seed (default: the still's "
        "cyclone seed, or 31); pick a seed whose storms sit where the clip "
        "wants them — all draws are still ocean-gated and shear-sized",
    )
    parser.add_argument(
        "--weather-pack",
        type=Path,
        default=None,
        help="weather pack directory; advection uses its 6-hourly winds "
        "(deck u_mid/v_mid, cirrus u_high/v_high, interpolated between frames)",
    )
    parser.add_argument(
        "--frame",
        type=float,
        default=None,
        help="pack frame at clip start (default: the still's own frame, else 0)",
    )
    parser.add_argument("--crf", type=int, default=18, help="H.264 quality (lower = better)")
    parser.add_argument("--no-ocean", action="store_true", help="skip the ocean mask / sun glint")
    parser.add_argument(
        "--poster", type=Path, help="save first/last frames as PNG next to this path"
    )
    args = parser.parse_args()

    if args.res > args.width or args.res > args.height:
        raise SystemExit("--res must fit inside the output frame")
    if args.no_vortex:
        if args.storm_mode != "none":
            raise SystemExit("--no-vortex is deprecated; use --storm-mode none")
        args.storm_mode = "none"
    clouds_dir: Path = args.clouds_dir
    meta = _load_meta(clouds_dir)
    model = _load_model(meta)
    atmosphere = meta["atmosphere"]
    eclipse_meta = meta.get("eclipse")
    eclipse_shadow = EclipseShadow(**eclipse_meta) if isinstance(eclipse_meta, dict) else None
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
    # Wind source: the pack's own 6-hourly flow when given, else the annual
    # mesh mean (placeholder).
    pack = None
    frame_interval_h = 6.0
    start_frame = 0.0
    if args.weather_pack is not None:
        pack = load_pack(args.weather_pack)
        calendar = pack.meta.get("calendar") or {}
        frame_interval_h = float(calendar.get("frame_interval_h", 6.0))
        still_frame = (meta.get("weather_pack") or {}).get("frame")
        start_frame = args.frame if args.frame is not None else float(still_frame or 0.0)
        n_frames = int(pack.meta["frames"])
        end_frame = start_frame + args.sim_hours / frame_interval_h
        if end_frame > n_frames - 1:
            raise SystemExit(
                f"--sim-hours {args.sim_hours:g} h runs past the pack: "
                f"frames {start_frame:g}…{end_frame:g} outside 0…{n_frames - 1}"
            )
        frame_cache: dict[int, WeatherFrame] = {}

        def pack_frame(f: float) -> WeatherFrame:
            """Integer frames are processed once; fractional steps blend."""
            base = int(math.floor(f))
            frac = f - base
            if base not in frame_cache:
                frame_cache[base] = frame_from_pack(pack, base, tex_width, tex_height)
            if frac == 0.0:
                return frame_cache[base]
            if base + 1 not in frame_cache:
                nxt = frame_from_pack(pack, base + 1, tex_width, tex_height)
                frame_cache[base + 1] = nxt
            return blend_weather_frames(frame_cache[base], frame_cache[base + 1], frac)

        print(
            f"wind: weather pack frames {start_frame:g}…{end_frame:g} "
            f"(deck u_mid, cirrus u_high, {frame_interval_h:g} h frames, interpolated)"
        )
    else:
        _, wind_east, wind_north, _, _ = conditioning_grids(mesh, indices)
        print("wind: annual mesh mean (placeholder)")
    cloud = _resize(cloud_alpha, tex_width, tex_height)
    if cloud_high is not None:
        cloud_high = _resize(cloud_high, tex_width, tex_height)
    storm_mode = args.storm_mode
    # Template-noise and tropical-sampler seed: match the still export's
    # cyclone seed so a rigid clip shows the same storms as the cyclone still.
    storm_seed = int(args.storm_seed or (meta.get("cyclones") or {}).get("seed") or 31)
    # Ocean mask written next to the still by `export globe`: tropical
    # cyclogenesis is an ocean phenomenon, and the GCM's genesis-potential
    # field does not know surface type.
    ocean_mask_path = clouds_dir / "ocean_fraction.npy"
    ocean_fraction = (
        np.load(ocean_mask_path) if ocean_mask_path.exists() and pack is not None else None
    )
    if ocean_fraction is not None:
        print("  genesis: constrained to ocean by the still's ocean_fraction.npy")
    tropical_source = None
    cyclones: list[Cyclone] = []
    centres: list[tuple[float, float]] = []
    rigid_storms = storm_mode == "rigid" and pack is not None
    if storm_mode == "vortex":
        cyclones = _load_cyclones(meta)
        centres = [(cyc.lat_deg, cyc.lon_deg) for cyc in cyclones]
        if cyclones:
            print(f"vortex: {len(cyclones)} storm circulation(s) added to the advection wind")
        if pack is not None and cyclones:
            # The still was rendered with pack cyclones: follow the real tracks
            # frame by frame instead of drifting the exported snapshot with the wind.
            tropical_source = TropicalCycloneSource(
                pack,
                seed=storm_seed,
                radius_km=model.planet_radius_km,
                ocean_fraction=ocean_fraction,
            )
            print("  storms follow the weather pack's tracks (incl. canon tropical)")
    elif rigid_storms:
        if (meta.get("cyclones") or {}).get("tracks"):
            print(
                "  note: the input still already has storms stamped in; rigid mode "
                "draws fresh ones from the pack — prefer a storm-free still"
            )
        tropical_source = TropicalCycloneSource(
            pack,
            seed=storm_seed,
            radius_km=model.planet_radius_km,
            ocean_fraction=ocean_fraction,
        )
        print("  storms: rigid per-frame compositing from the pack's tracks")

    ocean = None
    if not args.no_ocean:
        surface_indices = export_cell_index_grid(mesh, width, height, tree=tree)
        ocean_cells = np.array([c.elevation < sea_level for c in mesh.cells], dtype=bool)
        ocean = ocean_cells[surface_indices].astype(np.float64)

    fbm_stack = None
    if rigid_storms:
        # Template noise fields are grid+seed dependent only; compute once.
        fbm_stack = template_fbm_stack(tex_height, tex_width, storm_seed)

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
        cirrus_shadow_strength=float(atmosphere.get("cirrus_shadow_strength", 0.6)),
        eclipse_shadow=eclipse_shadow,
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
        f"cirrus={'on' if cloud_high is not None else 'off'}, storms={storm_mode}"
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
                # Winds at the step midpoint — half a step into the interval.
                if pack is not None:
                    cur = pack_frame(start_frame + (i - 0.5) * dt / (3600.0 * frame_interval_h))
                    deck_east, deck_north = cur.wind_east, cur.wind_north
                    high_east, high_north = cur.wind_east_high, cur.wind_north_high
                else:
                    deck_east = high_east = wind_east
                    deck_north = high_north = wind_north
                if storm_mode == "vortex":
                    storm_list: list[Cyclone] = []
                    if pack is not None and cyclones:
                        # Real tracks: the storm set and positions at the step midpoint.
                        f_mid = start_frame + (i - 0.5) * dt / (3600.0 * frame_interval_h)
                        storm_list = weather_cyclones_at_frame(
                            pack,
                            f_mid,
                            seed=storm_seed,
                            radius_km=model.planet_radius_km,
                            tropical=tropical_source,
                        )
                        centres = [(s.lat_deg, s.lon_deg) for s in storm_list]
                    elif cyclones:
                        centres = _advance_centres(
                            centres,
                            deck_east,
                            deck_north,
                            dt_seconds=dt,
                            radius_km=model.planet_radius_km,
                        )
                        storm_list = list(cyclones)
                    if storm_list:
                        vortex_east, vortex_north = cyclone_wind_field(
                            storm_list,
                            height=tex_height,
                            width=tex_width,
                            radius_km=model.planet_radius_km,
                            centers=centres,
                        )
                        deck_east = deck_east + vortex_east
                        deck_north = deck_north + vortex_north
                        high_east = high_east + vortex_east
                        high_north = high_north + vortex_north
                substeps = args.substeps or advection_substeps(
                    deck_east,
                    deck_north,
                    dt_seconds=dt,
                    radius_km=model.planet_radius_km,
                )
                cloud = advect_equirect(
                    cloud,
                    deck_east,
                    deck_north,
                    dt_seconds=dt,
                    radius_km=model.planet_radius_km,
                    substeps=substeps,
                    bfecc=not args.no_bfecc,
                    interp=args.interp,
                )
                if cloud_high is not None:
                    cloud_high = advect_equirect(
                        cloud_high,
                        high_east,
                        high_north,
                        dt_seconds=dt,
                        radius_km=model.planet_radius_km,
                        substeps=substeps,
                        bfecc=not args.no_bfecc,
                        interp=args.interp,
                    )
            # Rigid mode: composite the pack's storms over the advected deck
            # every frame — position at this frame's own time, spin from the
            # elapsed simulated time (deterministic, not accumulated float),
            # intensity from the track's life cycle.
            deck_render = cloud
            if rigid_storms:
                f_i = start_frame + i * dt / (3600.0 * frame_interval_h)
                storms = weather_cyclones_at_frame(
                    pack,
                    f_i,
                    seed=storm_seed,
                    radius_km=model.planet_radius_km,
                    tropical=tropical_source,
                )
                if storms:
                    elapsed_s = i * dt
                    storms = [
                        replace(
                            s,
                            spin_deg=math.degrees(pattern_spin_rate_rad_s(s) * elapsed_s),
                        )
                        for s in storms
                    ]
                    deck_render = _composite_storms(
                        cloud,
                        storms,
                        radius_km=model.planet_radius_km,
                        seed=storm_seed,
                        fbm_stack=fbm_stack,
                    )
            renderer.set_cloud(deck_render, cloud_high)
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
