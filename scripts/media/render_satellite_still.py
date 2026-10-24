"""Render the chosen Aegis-eclipse satellite still (b = 70,000 km).

The eclipse geometry lives in :mod:`dreamulator.media.eclipse_geometry`
(exact disk-overlap coverage, impact-parameter shadow placement).  This
script pins the nacrea/Aegis constants and the framing: camera centre
60E/15N, sun 40E/20N, the shadow offset toward 60E so the band runs to the
right of the sub-stellar point, adjacent to the night crescent.

Usage:
    uv run python scripts/media/render_satellite_still.py \
        --export-dir exports/globe/nacrea
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

from dreamulator.media.atmosphere_render import AtmosphereModel, render_globe_atmosphere
from dreamulator.media.eclipse_geometry import eclipse_mask

R_AEGIS = 71355.0
R_STAR = 426116.0
D_STAR = 54573303.0
D_MOON = 723300.0

CENTER_LON, CENTER_LAT = 60.0, 15.0
SUN_LON, SUN_LAT = 40.0, 20.0
DEFAULT_EXPORT = Path("exports/globe/nacrea")
DEFAULT_OUT = Path("exports/video/eclipse/nacrea_eclipse_b70000.png")
DEFAULT_B_KM = 70000.0


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

    field = eclipse_mask(
        args.res,
        planet_km=model.planet_radius_km,
        b_km=args.b_km,
        center_lon_deg=CENTER_LON,
        center_lat_deg=CENTER_LAT,
        sun_lon_deg=SUN_LON,
        sun_lat_deg=SUN_LAT,
        shadow_lon_deg=CENTER_LON,
        shadow_lat_deg=SUN_LAT,
        occluder_radius_km=R_AEGIS,
        occluder_distance_km=D_MOON,
        star_radius_km=R_STAR,
        star_distance_km=D_STAR,
    )
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
