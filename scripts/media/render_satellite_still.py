"""Render the chosen Aegis-eclipse satellite still (b = 70,000 km).

Real geometry, not the circular approximation: for every surface normal n,
the perpendicular distance to the star-Aegis axis is

    rho^2 = R^2 + b^2 - 2 b R (n.u) - R^2 (n.s)^2

where s is the sub-stellar direction and u is the axis-offset direction.
The local obscuration is the overlap area of the star and Aegis disks.

Camera: centre 60E/15N, sun 40E/20N.  The small night crescent is on the
right; the shadow centre lies on the terminator, so the shadow band is
adjacent to the night side.

Usage:
    uv run python scripts/media/render_satellite_still.py \
        --export-dir exports/globe/nacrea
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image

from dreamulator.media.atmosphere_render import AtmosphereModel, render_globe_atmosphere

R_AEGIS = 71355.0
R_STAR = 426116.0
D_STAR = 54573303.0
D_MOON = 723300.0
ALPHA_A = math.asin(R_AEGIS / D_MOON)
ALPHA_S = math.asin(R_STAR / D_STAR)

CENTER_LON, CENTER_LAT = 60.0, 15.0
SUN_LON, SUN_LAT = 40.0, 20.0
DEFAULT_EXPORT = Path("exports/globe/nacrea")
DEFAULT_OUT = Path("private/video/eclipse/nacrea_eclipse_b70000.png")
DEFAULT_B_KM = 70000.0


def _unit(lon_deg: float, lat_deg: float) -> np.ndarray:
    lon = math.radians(lon_deg)
    lat = math.radians(lat_deg)
    return np.array([math.cos(lat) * math.cos(lon), math.sin(lat), math.cos(lat) * math.sin(lon)])


def _eclipse_field(res: int, planet_km: float, b_km: float) -> np.ndarray:
    view = _unit(CENTER_LON, CENTER_LAT)
    sun = _unit(SUN_LON, SUN_LAT)
    lam = math.radians(CENTER_LON)
    right = np.array([-math.sin(lam), 0.0, math.cos(lam)])
    up = np.cross(right, view)
    # Offset direction: screen-right projected perpendicular to the star
    # direction, so the shadow centre sits to the right of the view centre.
    u = right - np.dot(right, sun) * sun
    u /= np.linalg.norm(u)

    half = res / 2.0
    py, px = np.mgrid[0:res, 0:res].astype(np.float64)
    x = (px + 0.5 - half) / (half * 0.92)
    y = (half - py - 0.5) / (half * 0.92)
    r2 = x * x + y * y
    inside = r2 <= 1.0
    z = np.sqrt(np.clip(1.0 - r2, 0.0, None))
    n_x = x * right[0] + y * up[0] + z * view[0]
    n_y = x * right[1] + y * up[1] + z * view[1]
    n_z = x * right[2] + y * up[2] + z * view[2]
    cos_sun = n_x * sun[0] + n_y * sun[1] + n_z * sun[2]
    cos_u = n_x * u[0] + n_y * u[1] + n_z * u[2]

    rho2 = planet_km**2 + b_km**2 - 2.0 * b_km * planet_km * cos_u - (planet_km * cos_sun) ** 2
    rho = np.sqrt(np.clip(rho2, 0.0, None))
    sep = np.arctan2(rho, D_MOON)

    cov = np.where(sep <= ALPHA_A - ALPHA_S, 1.0, 0.0)
    partial = (sep > ALPHA_A - ALPHA_S) & (sep < ALPHA_A + ALPHA_S)
    if np.any(partial):
        s = sep[partial]
        big = ALPHA_A
        small = ALPHA_S
        a1 = big * big * np.arccos((s * s + big * big - small * small) / (2 * s * big))
        a2 = small * small * np.arccos((s * s + small * small - big * big) / (2 * s * small))
        a3 = 0.5 * np.sqrt(
            np.clip(
                (-s + big + small) * (s + big - small) * (s - big + small) * (s + big + small),
                0.0,
                None,
            )
        )
        cov[partial] = (a1 + a2 - a3) / (math.pi * small * small)
    cov = np.clip(cov, 0.0, 1.0)
    cov = np.where(inside & (cos_sun > 0.0), cov, 0.0)
    return np.asarray(1.0 - cov, dtype=np.float64)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--export-dir", type=Path, default=DEFAULT_EXPORT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--b-km", type=float, default=DEFAULT_B_KM)
    parser.add_argument("--res", type=int, default=1600)
    args = parser.parse_args()

    export_dir = args.export_dir
    if not (export_dir / "meta.json").exists():
        raise SystemExit(
            f"{export_dir} has no meta.json; run\n"
            "  uv run dreamulator export globe nacrea "
            "--config private/video/satellite/cloud_trio_final.yaml "
            "-o exports/globe/nacrea\n"
            "first."
        )

    meta = json.loads((export_dir / "meta.json").read_text(encoding="utf-8"))
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
    # The renderer expects surface RGB in 0..1; the PNG is 8-bit.
    surface = np.asarray(Image.open(export_dir / "surface.png").convert("RGB"), dtype=np.float64)
    surface /= 255.0
    clouds_low = (
        np.asarray(Image.open(export_dir / "clouds_low.png").convert("RGBA"))[..., 3] / 255.0
    )
    clouds_cirrus = (
        np.asarray(Image.open(export_dir / "clouds_cirrus.png").convert("RGBA"))[..., 3] / 255.0
    )

    field = _eclipse_field(args.res, model.planet_radius_km, args.b_km)
    img = render_globe_atmosphere(
        surface,
        clouds_low,
        cloud_alpha_high=clouds_cirrus,
        res=args.res,
        center_lon_deg=CENTER_LON,
        center_lat_deg=CENTER_LAT,
        sun_lon_deg=SUN_LON,
        sun_lat_deg=SUN_LAT,
        model=model,
        eclipse_field=field,
        sun_glint=False,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(img).save(args.out)
    print(f"saved {args.out}  (b={args.b_km:,.0f} km)")


if __name__ == "__main__":
    main()
