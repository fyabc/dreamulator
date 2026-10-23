"""QA probe: rerun the 24-h cloud-flow advection standalone and measure drift.

Reproduces cloud_flow_video.py's exact advection (same dt schedule, wind
interpolation, substeps, cubic+BFECC) from the f400 still's cloud alphas,
logging per-shell pixel-mean and cos-lat area-mean every 10 steps, saving the
final fields as PNGs, and cross-correlating t0 vs t24 zonal displacement per
latitude band against the pack's own band-mean winds.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image

from dreamulator.gcm.weather_pack import load_pack
from dreamulator.media.cloud_advection import advect_equirect, advection_substeps
from dreamulator.media.weather_conditioning import blend_weather_frames, frame_from_pack

STILL = Path("exports/globe/nacrea-gcm-t42-712-f400")
PACK = Path("exports/weather/nacrea-gcm-t42-712")
OUT = Path("exports/globe")
W, H = 2048, 1024
RADIUS_KM = 6816.97
SIM_H = 24.0
FRAMES = 240


def resize(field: np.ndarray) -> np.ndarray:
    im = Image.fromarray(np.clip(field * 255.0, 0.0, 255.0).astype(np.uint8), "L")
    return np.asarray(im.resize((W, H), Image.LANCZOS), dtype=np.float64) / 255.0


def load_alpha(name: str) -> np.ndarray:
    rgba = np.asarray(Image.open(STILL / name).convert("RGBA"), dtype=np.float64)
    return rgba[..., 3] / 255.0


def main() -> None:
    deck0 = resize(load_alpha("clouds_low.png"))
    cirrus0 = resize(load_alpha("clouds_cirrus.png"))
    deck, cirrus = deck0.copy(), cirrus0.copy()

    pack = load_pack(PACK)
    interval = float((pack.meta.get("calendar") or {}).get("frame_interval_h", 6.0))
    cache: dict[int, object] = {}

    def wf(f: float):
        base = int(math.floor(f))
        frac = f - base
        if base not in cache:
            cache[base] = frame_from_pack(pack, base, W, H)
        if frac == 0.0:
            return cache[base]
        if base + 1 not in cache:
            cache[base + 1] = frame_from_pack(pack, base + 1, W, H)
        return blend_weather_frames(cache[base], cache[base + 1], frac)

    lat_deg = 90.0 - (np.arange(H) + 0.5) / H * 180.0
    coslat = np.cos(np.radians(lat_deg))[:, None]
    area_w = np.broadcast_to(coslat, (H, W)).sum()

    def stats(tag: str) -> None:
        for nm, arr in (("deck", deck), ("cirrus", cirrus)):
            pix = arr.mean()
            area = float((arr * coslat).sum() / area_w)
            print(f"{tag} {nm}: pixel-mean={pix:.4f} area-mean={area:.4f}")

    stats("t=0.0h")

    dt = SIM_H * 3600.0 / (FRAMES - 1)
    for i in range(1, FRAMES):
        cur = wf(400 + (i - 0.5) * dt / (3600.0 * interval))
        sub = advection_substeps(cur.wind_east, cur.wind_north, dt_seconds=dt, radius_km=RADIUS_KM)
        deck = advect_equirect(
            deck,
            cur.wind_east,
            cur.wind_north,
            dt_seconds=dt,
            radius_km=RADIUS_KM,
            substeps=sub,
            bfecc=True,
            interp="cubic",
        )
        cirrus = advect_equirect(
            cirrus,
            cur.wind_east_high,
            cur.wind_north_high,
            dt_seconds=dt,
            radius_km=RADIUS_KM,
            substeps=sub,
            bfecc=True,
            interp="cubic",
        )
        if i % 20 == 0:
            stats(f"t={i * dt / 3600.0:.1f}h")

    for nm, arr in (("deck", deck), ("cirrus", cirrus)):
        Image.fromarray(np.clip(arr * 255.0, 0, 255).astype(np.uint8), "L").save(
            str(OUT / f"_flow-probe-final-{nm}.png")
        )

    # Zonal displacement per band: circular cross-correlation of row pairs.
    deg_per_px = 360.0 / W
    bands = [(-60, -30, "SH midlat"), (-15, 15, "tropics"), (30, 60, "NH midlat")]
    u_mid = np.asarray(pack.field("u_mid")[402], float)
    plat = np.asarray(pack.lat, float)
    print("\nband displacement (deck, t0 vs t24, positive = east):")
    for lo, hi, name in bands:
        rows = (lat_deg >= lo) & (lat_deg < hi)
        shifts = []
        for r in np.nonzero(rows)[0][::4]:
            a, b = deck0[r], deck[r]
            a = a - a.mean()
            b = b - b.mean()
            corr = np.fft.irfft(np.fft.rfft(a) * np.conj(np.fft.rfft(b)), n=W)
            shift = int(np.argmax(corr))  # peak sits at -displacement
            if shift > W // 2:
                shift -= W
            shifts.append(-shift)  # positive = pattern moved east
        px = float(np.median(shifts))
        deg = px * deg_per_px
        band_u = float(u_mid[(plat >= lo) & (plat < hi)].mean())
        expect_deg = math.degrees(band_u * SIM_H * 3600.0 / (RADIUS_KM * 1000.0)) / max(
            math.cos(math.radians((lo + hi) / 2.0)), 0.05
        )
        print(
            f"  {name:9s}: measured {deg:+7.1f} deg (median {px:+.1f} px); "
            f"zonal-mean u_mid {band_u:+6.1f} m/s -> expect ~{expect_deg:+7.1f} deg"
        )


if __name__ == "__main__":
    main()
