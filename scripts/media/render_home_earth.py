"""Render the homepage still and looping globe clip from a 16-bit heightmap."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import map_coordinates

from dreamulator.map.elevation_codec import decode_elevation

ELEVATIONS_M = [-11_000, -5700, -3000, -200, -1, 0, 800, 2400, 5000, 9000]
COLORS = [
    (9, 24, 39),
    (19, 48, 67),
    (26, 69, 91),
    (45, 104, 123),
    (60, 125, 137),
    (134, 151, 105),
    (159, 170, 116),
    (194, 176, 131),
    (210, 188, 153),
    (246, 238, 216),
]


def relief_texture(path: Path, min_m: float, max_m: float) -> np.ndarray:
    meters = decode_elevation(path.read_bytes()).astype(np.float32)
    meters = meters * (max_m - min_m) + min_m
    east_slope = (np.roll(meters, -1, axis=1) - np.roll(meters, 1, axis=1)) * 0.5
    south_slope = np.gradient(meters, axis=0)
    relief = 1 + np.clip((east_slope + south_slope) / 900, -0.32, 0.35)
    texture = np.empty((3, *meters.shape), dtype=np.uint8)
    for channel, values in enumerate(zip(*COLORS, strict=True)):
        texture[channel] = np.clip(np.interp(meters, ELEVATIONS_M, values) * relief, 0, 255)
    return texture


class GlobeProjection:
    def __init__(self, texture: np.ndarray, size: int):
        self.texture = texture
        _, self.height, self.width = texture.shape
        radius = size * 0.49
        offsets = (np.arange(size, dtype=np.float32) + 0.5 - size * 0.5) / radius
        east, north = np.meshgrid(offsets, -offsets)
        distance = np.hypot(east, north)
        front = np.sqrt(np.maximum(0, 1 - distance**2))
        camera_lat = np.deg2rad(24.10)
        globe_north = north * np.cos(camera_lat) + front * np.sin(camera_lat)
        globe_front = front * np.cos(camera_lat) - north * np.sin(camera_lat)
        lat = np.arcsin(np.clip(globe_north, -1, 1))
        self.rows = np.clip((0.5 - lat / np.pi) * self.height - 0.5, 0, self.height - 1)
        self.longitude = np.arctan2(east, globe_front) / (2 * np.pi)
        self.light = 0.59 + 0.48 * np.clip(-0.46 * east + 0.45 * north + 0.76 * front, 0, 1)
        self.rim = np.maximum(0, 1 - front) ** 5
        self.alpha = np.round(np.clip((1 - distance) * radius + 0.5, 0, 1) * 255).astype(np.uint8)

    def frame(self, longitude_deg: float) -> np.ndarray:
        cols = (self.longitude + longitude_deg / 360 + 0.5) * self.width - 0.5
        coords = np.stack((self.rows, cols))
        return np.stack(
            [
                np.clip(
                    map_coordinates(channel, coords, order=1, mode="grid-wrap") * self.light
                    + self.rim * rim_light,
                    0,
                    255,
                ).astype(np.uint8)
                for channel, rim_light in zip(self.texture, (12, 23, 36), strict=True)
            ],
            axis=-1,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("heightmap", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--min-m", type=float, required=True)
    parser.add_argument("--max-m", type=float, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    texture = relief_texture(args.heightmap, args.min_m, args.max_m)
    start_lon = 121.45
    poster = GlobeProjection(texture, 960)
    rgba = np.dstack((poster.frame(start_lon), poster.alpha))
    Image.fromarray(rgba).save(args.output_dir / "earth-relief.webp", quality=89)

    globe = GlobeProjection(texture, 640)
    fps = 60
    frames = 32 * fps
    encode = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "rawvideo",
        "-pixel_format",
        "rgb24",
        "-video_size",
        "640x640",
        "-framerate",
        str(fps),
        "-i",
        "pipe:0",
        "-an",
        "-c:v",
        "libx264",
        "-threads",
        "2",
        "-preset",
        "slow",
        "-crf",
        "29",
        "-maxrate",
        "550k",
        "-bufsize",
        "1100k",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(args.output_dir / "earth-rotation.mp4"),
    ]
    with subprocess.Popen(encode, stdin=subprocess.PIPE) as encoder:
        assert encoder.stdin is not None
        for index in range(frames):
            angle = start_lon - index * 360 / frames
            encoder.stdin.write(globe.frame(angle).tobytes())
        encoder.stdin.close()
        if encoder.wait():
            raise SystemExit("ffmpeg could not encode the homepage rotation")


if __name__ == "__main__":
    main()
