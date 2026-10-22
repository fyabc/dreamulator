#!/usr/bin/env python3
"""Geological timeline: render a plate-motion video from a ``paleo_solve.py`` run.

Windows reference render (delivery summary 2026-10-20 §3): Mollweide projection,
1920×1080, 20 fps, one frame every 0.5 Myr from ``--start`` back to the present.
Plate attribution is majority-voted across the surrounding frames (``--vote``,
default a ±2-frame window) to suppress resampling flicker; boundaries are
resampled and smoothed (``paleo_topology.prepare``), typed from each point's
local relative motion by the snapshot itself, and drawn per kind: transform
faults gold on a dark casing, ridges and trenches cased in white.  Oceanic
crust is shaded by elevation so fresh seafloor at ridges reads brighter.

Reads a solve directory (``summary.json`` + ``solve.npz``) and the built map it
was solved on (read-only), exactly like ``paleo_snapshot.py``.

Outputs into ``--out-dir``: ``frames/frame_%05d.png`` (chronological),
``manifest.json`` (epochs, settings, per-frame seconds), and unless
``--no-encode`` the video ``plate_motion.mp4`` (H.264 via the ffmpeg binary
from ``imageio-ffmpeg``; run ``uv run --with imageio-ffmpeg ... --encode-only``
to encode existing frames without re-rendering).

Usage::

    uv run python scripts/geology/paleo_render.py data/worlds/nacrea/maps/satellite_nacrea \\
        --solve-dir <workdir>/paleo_solve --out-dir <workdir>/paleo_video
"""

from __future__ import annotations

import argparse
import colorsys
import json
import shutil
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
from paleo_rewind import World, ocean_params
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage
from scipy.spatial import cKDTree

from dreamulator.map import paleo_topology as pt
from dreamulator.map.paleo_blocks import build_blocks
from dreamulator.map.paleo_history import active_orogens
from dreamulator.map.paleo_kinematics import (
    boundary_cells,
    boundary_opening_rates,
    continental_speed_poles,
    no_net_rotation,
    ridge_half_rates,
    synthesize_seafloor_age,
)
from dreamulator.map.paleo_snapshot import DepthLaw, snapshot
from dreamulator.map.paleo_solver import SolverConfig, build_setup, seafloor_welds
from dreamulator.map.paleo_sutures import load_sutures
from dreamulator.map.paleo_walk import continental_rifts

_SQRT2 = np.sqrt(2.0)
_BG = np.array([8, 10, 16], dtype=np.uint8)
_GRAT = (48, 54, 66)
_EDGE = (90, 98, 112)
# kind → (casing colour, core colour, casing width, core width)
_STYLES = {
    "diffuse": ((140, 140, 140), (140, 140, 140), 1, 1),
    "transform": ((38, 30, 8), (255, 196, 40), 5, 3),
    "trench": ((245, 245, 245), (30, 34, 92), 5, 3),
    "ridge": ((245, 245, 245), (214, 64, 48), 5, 3),
}
_DRAW_ORDER = ("diffuse", "transform", "trench", "ridge")


def moll_theta(lat_rad: np.ndarray) -> np.ndarray:
    """Auxiliary angle of the Mollweide projection: 2θ + sin 2θ = π sin φ."""
    target = np.pi * np.sin(lat_rad)
    th = np.clip(lat_rad, -np.pi / 2, np.pi / 2).copy()
    for _ in range(24):
        f = 2 * th + np.sin(2 * th) - target
        d = np.maximum(2 + 2 * np.cos(2 * th), 1e-6)
        th = np.clip(th - f / d, -np.pi / 2, np.pi / 2)
    return th


def moll_forward(lon_deg: np.ndarray, lat_deg: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Degrees → normalised Mollweide (x ∈ [−2√2, 2√2], y ∈ [−√2, √2])."""
    th = moll_theta(np.radians(lat_deg))
    x = (2 * _SQRT2 / np.pi) * np.radians(lon_deg) * np.cos(th)
    y = _SQRT2 * np.sin(th)
    return x, y


def build_pixel_map(xyz: np.ndarray, width: int, height: int, margin: int) -> dict:
    """One-time nearest-cell lookup for every pixel inside the Mollweide ellipse."""
    scale = min((width - 2 * margin) / (4 * _SQRT2), (height - 2 * margin) / (2 * _SQRT2))
    cx, cy = width / 2.0, height / 2.0
    xs = (np.arange(width) + 0.5 - cx) / scale
    ys = (cy - (np.arange(height) + 0.5)) / scale
    gx, gy = np.meshgrid(xs, ys)
    inside = (gx**2 / 8 + gy**2 / 2) <= 1.0
    theta = np.arcsin(np.clip(gy / _SQRT2, -1, 1))
    lat = np.arcsin(np.clip((2 * theta + np.sin(2 * theta)) / np.pi, -1, 1))
    cos_t = np.maximum(np.cos(theta), 1e-12)
    lon = np.pi * gx / (2 * _SQRT2 * cos_t)
    pts = np.stack([np.cos(lat) * np.cos(lon), np.sin(lat), np.cos(lat) * np.sin(lon)], axis=-1)[
        inside
    ]
    _, idx = cKDTree(xyz).query(pts, workers=-1)
    cellidx = np.zeros(width * height, dtype=np.int32)  # 0 = background sentinel
    cellidx[np.flatnonzero(inside.ravel())] = idx + 1
    return {
        "cellidx": cellidx.reshape(height, width),
        "inside": inside,
        "scale": scale,
        "cx": cx,
        "cy": cy,
    }


def vote_labels(stack: list[np.ndarray], centre_at: int) -> np.ndarray:
    """Per-cell strict-majority label across the window; centre frame on ties."""
    centre = stack[centre_at]
    if len(stack) < 3:
        return centre
    s = np.sort(np.stack(stack), axis=0)
    m = s.shape[0]
    eq = s[:-1] == s[1:]
    run = np.ones((m, s.shape[1]), dtype=np.int32)
    for o in range(m - 2, -1, -1):
        run[o] = 1 + np.where(eq[o], run[o + 1], 0)
    cnt = run.max(axis=0)
    start = run.argmax(axis=0)
    val = s[start, np.arange(s.shape[1])]
    return np.where(cnt >= m // 2 + 1, val, centre)


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def graticule_polylines(pm: dict) -> list[list[tuple[float, float]]]:
    """Meridians every 30° and parallels every 30°, as pixel polylines."""
    scale, cx, cy = pm["scale"], pm["cx"], pm["cy"]

    def to_px(x: np.ndarray, y: np.ndarray) -> list[tuple[float, float]]:
        return list(zip(np.atleast_1d(cx + x * scale), np.atleast_1d(cy - y * scale), strict=True))

    lines = []
    th = np.linspace(-np.pi / 2, np.pi / 2, 181)
    for lon in range(-150, 180, 30):
        lam = np.radians(lon)
        lines.append(to_px((2 * _SQRT2 / np.pi) * lam * np.cos(th), _SQRT2 * np.sin(th)))
    for lat in (-60, -30, 0, 30, 60):
        t0 = float(moll_theta(np.array([np.radians(lat)]))[0])
        xs = np.linspace(-2 * _SQRT2, 2 * _SQRT2, 2) * np.cos(t0)
        lines.append(to_px(xs, np.full(2, _SQRT2 * np.sin(t0))))
    return lines


def project_segment(points: np.ndarray, pm: dict) -> list[list[tuple[float, float]]]:
    """Unit vectors → pixel polylines, split at the antimeridian."""
    lon = np.degrees(np.arctan2(points[:, 2], points[:, 0]))
    lat = np.degrees(np.arcsin(np.clip(points[:, 1], -1, 1)))
    x, y = moll_forward(lon, lat)
    px, py = pm["cx"] + x * pm["scale"], pm["cy"] - y * pm["scale"]
    cuts = np.flatnonzero(np.abs(np.diff(lon)) > 180) + 1
    out = []
    for lo, la in zip(np.split(px, cuts), np.split(py, cuts), strict=True):
        if len(lo) > 1:
            out.append(list(zip(lo, la, strict=True)))
    return out


def render_frame(
    snap,
    label: np.ndarray,
    pm: dict,
    grat: list,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    pal: np.ndarray,
) -> Image.Image:
    """One video frame: plate colours, coast, boundaries, graticule, time label."""
    height, width = pm["cellidx"].shape
    col = pal[np.minimum(label, len(pal) - 1)].astype(np.float32)
    ocean = ~snap.continental
    shade = np.clip((snap.elevation_m + 7000) / 13000, 0, 1)
    col[ocean] *= (0.80 + 0.28 * shade[ocean])[:, None]
    col[~ocean] *= 0.72
    rgb = np.empty((len(col) + 1, 3), dtype=np.uint8)
    rgb[0] = _BG
    rgb[1:] = np.clip(col, 0, 1) * 255
    arr = rgb[pm["cellidx"].ravel()].reshape(height, width, 3)

    land_px = np.zeros(height * width, dtype=bool)
    ci = pm["cellidx"].ravel()
    inner = ci > 0
    land_px[inner] = snap.land[ci[inner] - 1]
    land_px &= pm["inside"].ravel()
    land = land_px.reshape(height, width)
    band = ndimage.binary_dilation(land) & ~ndimage.binary_erosion(land)
    arr[band] = (arr[band] * 0.45).astype(np.uint8)

    im = Image.fromarray(arr)
    draw = ImageDraw.Draw(im)
    for line in grat:
        draw.line(line, fill=_GRAT, width=1)
    half_w, half_h = 2 * _SQRT2 * pm["scale"], _SQRT2 * pm["scale"]
    draw.ellipse(
        [pm["cx"] - half_w, pm["cy"] - half_h, pm["cx"] + half_w, pm["cy"] + half_h],
        outline=_EDGE,
        width=2,
    )

    topo = pt.prepare(snap.topology, np.radians(0.5))
    for kind in _DRAW_ORDER:
        for seg in topo.segments:
            if seg.kind != kind:
                continue
            casing, core, cw, kw = _STYLES[kind]
            for line in project_segment(seg.points, pm):
                if cw != kw:
                    draw.line(line, fill=casing, width=cw, joint="curve")
                draw.line(line, fill=core, width=kw, joint="curve")

    t = snap.t_myr
    when = "Present" if abs(t) < 1e-9 else f"-{t:g} Myr"
    text = f"nacrea   {when}   |   {snap.check.plates} plates"
    draw.text(
        (26, height - 56),
        text,
        font=font,
        fill=(240, 242, 246),
        stroke_width=2,
        stroke_fill=(0, 0, 0),
    )
    return im


def encode_video(frames_dir: Path, out_mp4: Path, fps: int) -> bool:
    exe = shutil.which("ffmpeg")
    if exe is None:
        try:
            import imageio_ffmpeg

            exe = imageio_ffmpeg.get_ffmpeg_exe()
        except ImportError:
            exe = None
    if exe is None:
        print(
            "ffmpeg not found; encode manually or rerun with:\n"
            "  uv run --with imageio-ffmpeg python scripts/geology/paleo_render.py "
            "... --encode-only",
            file=sys.stderr,
        )
        return False
    cmd = [
        exe,
        "-y",
        "-framerate",
        str(fps),
        "-i",
        str(frames_dir / "frame_%05d.png"),
        "-c:v",
        "libx264",
        "-preset",
        "slow",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(out_mp4),
    ]
    subprocess.run(cmd, check=True)
    return True


def epoch_list(start: float, end: float, step: float) -> list[float]:
    out, i = [], 0
    while True:
        t = round(start - i * step, 6)
        if t < end - 1e-9:
            break
        out.append(t)
        i += 1
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("map_dir", type=Path)
    ap.add_argument("--solve-dir", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--start", type=float, default=150.0)
    ap.add_argument("--end", type=float, default=0.0)
    ap.add_argument("--step", type=float, default=0.5)
    ap.add_argument(
        "--epochs",
        type=float,
        nargs="+",
        default=None,
        help="explicit epoch list (overrides --start/--end/--step)",
    )
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--fps", type=int, default=20)
    ap.add_argument("--vote", type=int, default=2, help="frames voted on each side")
    ap.add_argument("--sea-level-m", type=float, default=0.0)
    ap.add_argument("--plate-history", type=Path, default=None)
    ap.add_argument("--no-encode", action="store_true")
    ap.add_argument("--encode-only", action="store_true")
    args = ap.parse_args()

    frames_dir = args.out_dir / "frames"
    out_mp4 = args.out_dir / "plate_motion.mp4"
    epochs = args.epochs if args.epochs else epoch_list(args.start, args.end, args.step)

    if args.encode_only:
        encode_video(frames_dir, out_mp4, args.fps)
        return

    # --- solve + present-day setup (same as paleo_snapshot.py) ---
    summary = json.loads((args.solve_dir / "summary.json").read_text(encoding="utf-8"))
    config = SolverConfig(**summary["config"])
    solved = np.load(args.solve_dir / "solve.npz")
    w = World(args.map_dir)
    w.kin = replace(w.kin, omega=no_net_rotation(w.kin))
    kin = replace(w.kin, omega=continental_speed_poles(w.kin))
    hist = args.plate_history or (
        args.map_dir.resolve().parents[1] / "layers" / "geological" / "input" / "plate_history.yaml"
    )
    _, onsets = continental_rifts(w.kin, 300.0)
    blocks = build_blocks(kin, load_sutures(hist), onsets)
    half, offset = ridge_half_rates(w.kin, boundary_cells(w.kin))
    age, source = synthesize_seafloor_age(w.kin, half, offset)
    setup = build_setup(kin, blocks, w.kin.omega, kin.omega, age, source, half, config)
    blocks, _ = seafloor_welds(blocks, setup)
    opening, _ = boundary_opening_rates(w.kin, boundary_cells(w.kin))
    orogens = active_orogens(w.kin, w.elevation, opening, w.cumulative_convergence_km)
    params = ocean_params(args.map_dir, None)
    depth = DepthLaw(params["ridge_depth_m"], params["subsidence_coeff"], params["max_depth_m"])

    # --- pixel map (cached across runs with the same geometry) ---
    frames_dir.mkdir(parents=True, exist_ok=True)
    cache = args.out_dir / f"pixel_map_{args.width}x{args.height}.npz"
    if cache.exists():
        z = np.load(cache)
        pm = {
            "cellidx": z["cellidx"],
            "inside": z["inside"],
            "scale": float(z["scale"]),
            "cx": float(z["cx"]),
            "cy": float(z["cy"]),
        }
    else:
        pm = build_pixel_map(w.kin.xyz, args.width, args.height, margin=20)
        np.savez(cache, **pm)
    grat = graticule_polylines(pm)
    font = load_font(34)
    pal = np.array([colorsys.hls_to_rgb((i * 0.618034) % 1.0, 0.62, 0.55) for i in range(512)])

    def compute(t: float):
        return snapshot(
            w.kin,
            blocks,
            age,
            solved["stage_omega"],
            solved["groups"],
            config.stage_myr,
            t,
            w.kin.omega,
            w.elevation,
            depth,
            orogens,
            args.sea_level_m,
        )

    half_w = args.vote
    computed: dict[int, object] = {}
    next_i = 0
    timings = []
    t_start = time.time()
    for j, t in enumerate(epochs):
        while next_i <= min(j + half_w, len(epochs) - 1):
            computed[next_i] = compute(epochs[next_i])
            next_i += 1
        lo = max(0, j - half_w)
        idxs = [k for k in range(lo, min(len(epochs), j + half_w + 1)) if k in computed]
        snap = computed[j]
        label = vote_labels([computed[k].label for k in idxs], j - lo)
        im = render_frame(snap, label, pm, grat, font, pal)
        im.save(frames_dir / f"frame_{j:05d}.png", compress_level=6)
        timings.append(round(time.time() - t_start, 1))
        for k in list(computed):
            if k < j - half_w:
                del computed[k]
        if j % 20 == 0 or j == len(epochs) - 1:
            el = time.time() - t_start
            print(f"frame {j + 1}/{len(epochs)} (t=-{t:g} Myr) {el:.0f}s elapsed", flush=True)

    manifest = {
        "epochs": epochs,
        "fps": args.fps,
        "width": args.width,
        "height": args.height,
        "vote_window": 2 * half_w + 1,
        "sea_level_m": args.sea_level_m,
        "solve_seconds": summary.get("seconds"),
        "frame_times_s": timings,
    }
    (args.out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"rendered {len(epochs)} frames in {time.time() - t_start:.0f}s")
    if not args.no_encode:
        encode_video(frames_dir, out_mp4, args.fps)


if __name__ == "__main__":
    main()
