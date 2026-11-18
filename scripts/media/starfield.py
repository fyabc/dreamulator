"""Real-catalog star field geometry for procedural night skies.

The module turns a star catalog (HYG CSV columns ``ra_deg``, ``dec_deg``,
``vmag``, ``ci``) into the quantities a renderer needs: unit directions,
apparent radii in pixels, emission strength and a black-body-ish colour palette.
It deliberately stops before Blender: the same geometry serves Cycles, EEVEE,
WebGL or a 2D compositor.

The look calibration (``BRIGHT_SCALE``/``BRIGHT_GAMMA`` and the size gain) was
tuned against a Stellarium reference under AgX; treat the numbers as starting
values, not physics.

Usage (repo root)::

    uv run python scripts/media/starfield.py --catalog stars.csv --fov-deg 35

The HYG catalog is public domain and can be obtained from the upstream project;
this repository does not bundle it.
"""

from __future__ import annotations

import argparse
import csv
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

#: Emission strength ``S = BRIGHT_SCALE * flux ** BRIGHT_GAMMA``; flux is
#: normalised to the brightest star in the selected catalog slice.
BRIGHT_SCALE = 600.0
BRIGHT_GAMMA = 0.79

#: Colour palette from O to M (blue to orange), indexed by linear ``ci`` map.
PALETTE = np.array(
    [
        [0.62, 0.74, 1.00],
        [0.78, 0.84, 1.00],
        [1.00, 1.00, 1.00],
        [1.00, 0.95, 0.80],
        [1.00, 0.85, 0.55],
        [1.00, 0.62, 0.30],
    ]
)


@dataclass(frozen=True)
class StarGeometry:
    """Per-star render primitives, all aligned arrays."""

    directions: np.ndarray  # (N, 3) unit vectors on the sky
    radius_px: np.ndarray  # (N,) apparent radius in pixels
    strength: np.ndarray  # (N,) emission strength for the shader
    colours: np.ndarray  # (N, 3) linear RGB


def load_hyg(
    path: Path,
    *,
    mag_floor: float = -1.5,
    mag_limit: float = 6.0,
    center_ra_dec: tuple[float, float] | None = None,
    view_dir: tuple[float, float, float] = (0.0, 0.0, 1.0),
    up_hint: tuple[float, float, float] | None = None,
) -> StarGeometry:
    """Read an HYG CSV and keep stars in ``(mag_floor, mag_limit]``."""
    ra: list[float] = []
    dec: list[float] = []
    mags: list[float] = []
    ci: list[float] = []
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            mag = float(row["vmag"])
            if not (mag_floor < mag <= mag_limit):
                continue
            ra.append(float(row["ra_deg"]))
            dec.append(float(row["dec_deg"]))
            mags.append(mag)
            ci.append(float(row["ci"]))
    return from_arrays(
        np.array(ra),
        np.array(dec),
        np.array(mags),
        np.array(ci),
        center_ra_dec=center_ra_dec,
        view_dir=view_dir,
        up_hint=up_hint,
    )


def from_arrays(
    ra_deg: np.ndarray,
    dec_deg: np.ndarray,
    mags: np.ndarray,
    ci: np.ndarray,
    *,
    center_ra_dec: tuple[float, float] | None = None,
    view_dir: tuple[float, float, float] = (0.0, 0.0, 1.0),
    up_hint: tuple[float, float, float] | None = None,
    size_gain: float = 1.12,
    px_floor: float = 0.85,
    px_cap: float = 12.0,
    bright_scale: float = BRIGHT_SCALE,
    bright_gamma: float = BRIGHT_GAMMA,
) -> StarGeometry:
    """Build render primitives from catalog arrays.

    ``center_ra_dec`` rotates the whole sky so that this direction lands on
    ``view_dir``; ``up_hint`` fixes the roll (a celestial-north tangent).
    """
    if not (len(ra_deg) == len(dec_deg) == len(mags) == len(ci)):
        raise ValueError("catalog arrays must have the same length")
    if len(mags) == 0:
        raise ValueError("catalog slice is empty")
    dirs = equatorial_directions(ra_deg, dec_deg)
    if center_ra_dec is not None:
        dirs = dirs @ sky_orientation(center_ra_dec, view_dir, up_hint).T
    flux = 10.0 ** (-0.4 * mags)
    flux = flux / float(flux.max())
    radius = 6.0 * flux**0.4
    strength = bright_scale * flux**bright_gamma
    keep = strength >= 0.03
    radius = np.clip(radius[keep] * size_gain, px_floor, px_cap)
    colours = palette_from_ci(ci[keep])
    return StarGeometry(dirs[keep], radius, strength[keep], colours)


def equatorial_directions(ra_deg: np.ndarray, dec_deg: np.ndarray) -> np.ndarray:
    """RA/Dec (degrees) to unit vectors on the celestial sphere."""
    ra = np.radians(ra_deg)
    dec = np.radians(dec_deg)
    return np.stack([np.cos(dec) * np.cos(ra), np.cos(dec) * np.sin(ra), np.sin(dec)], axis=1)


def sky_orientation(
    center_ra_dec: tuple[float, float],
    view_dir: tuple[float, float, float] | None = None,
    up_hint: tuple[float, float, float] | None = None,
) -> np.ndarray:
    """Rotation matrix mapping the sky centre to ``view_dir`` (Rodrigues).

    ``up_hint`` aligns the rotated celestial north with a screen-up vector, so
    several camera directions share one continuous sky pattern.
    """
    c_ra, c_dec = np.radians(center_ra_dec[0]), np.radians(center_ra_dec[1])
    cvec = np.array([np.cos(c_dec) * np.cos(c_ra), np.cos(c_dec) * np.sin(c_ra), np.sin(c_dec)])
    vdir = np.asarray(view_dir if view_dir is not None else (0.0, 0.0, 1.0), dtype=float)
    vdir = vdir / np.linalg.norm(vdir)
    axis = np.cross(cvec, vdir)
    s = np.linalg.norm(axis)
    if s < 1e-9:
        rot = np.eye(3) if np.dot(cvec, vdir) > 0 else -np.eye(3)
    else:
        axis = axis / s
        angle = math.atan2(s, np.dot(cvec, vdir))
        cross = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
        rot = np.eye(3) + np.sin(angle) * cross + (1 - np.cos(angle)) * (cross @ cross)
    if up_hint is not None:
        up = np.asarray(up_hint, dtype=float)
        pole = rot @ np.array([0.0, 0.0, 1.0])
        tangent = pole - np.dot(pole, vdir) * vdir
        up_tangent = up - np.dot(up, vdir) * vdir
        tn, un = np.linalg.norm(tangent), np.linalg.norm(up_tangent)
        if tn > 1e-6 and un > 1e-6:
            tangent, up_tangent = tangent / tn, up_tangent / un
            axis2 = np.cross(tangent, up_tangent)
            s2 = np.linalg.norm(axis2)
            if s2 > 1e-9:
                axis2 = axis2 / s2
                angle2 = math.atan2(s2, np.dot(tangent, up_tangent))
                cross2 = np.array(
                    [[0, -axis2[2], axis2[1]], [axis2[2], 0, -axis2[0]], [-axis2[1], axis2[0], 0]]
                )
                roll = (
                    np.eye(3) + np.sin(angle2) * cross2 + (1 - np.cos(angle2)) * (cross2 @ cross2)
                )
                rot = roll @ rot
    return rot


def palette_from_ci(ci: np.ndarray) -> np.ndarray:
    """Map colour index ``ci`` (-0.3..1.7) to six linear RGB buckets."""
    clipped = np.clip(ci, -0.3, 1.7)
    index = np.clip(((clipped + 0.3) / 2.0) * 5.999, 0, 5).astype(int)
    return np.asarray(PALETTE[index], dtype=float)


def main() -> int:
    ap = argparse.ArgumentParser(description="Summarise an HYG star catalog slice.")
    ap.add_argument("--catalog", type=Path, required=True)
    ap.add_argument("--mag-limit", type=float, default=6.0)
    ap.add_argument("--mag-floor", type=float, default=-1.5)
    ap.add_argument("--fov-deg", type=float, default=35.0)
    ap.add_argument("--height-px", type=int, default=720)
    ap.add_argument("--center-ra", type=float, default=None)
    ap.add_argument("--center-dec", type=float, default=None)
    args = ap.parse_args()
    center = (
        (args.center_ra, args.center_dec)
        if args.center_ra is not None and args.center_dec is not None
        else None
    )
    geometry = load_hyg(
        args.catalog,
        mag_floor=args.mag_floor,
        mag_limit=args.mag_limit,
        center_ra_dec=center,
    )
    px_per_deg = args.fov_deg / max(args.height_px, 1)
    print(f"stars: {len(geometry.strength)}")
    print(f"radius_px: {geometry.radius_px.min():.2f}..{geometry.radius_px.max():.2f}")
    print(f"strength:  {geometry.strength.min():.2f}..{geometry.strength.max():.2f}")
    print(f"px_per_deg (vertical): {px_per_deg:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
