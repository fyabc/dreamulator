"""Weather layer pack: instantaneous GCM frames for the orbital weather-globe chain (L1).

The pack turns an ExoPlaSim snapshot file (instantaneous output every few time
steps, ``snapshots=N`` in the run configuration) into what the media chain
needs to draw clouds and storms from the model's own weather:

- ``fields/<name>.npy``: one float32 array per variable, shape
  ``(frames, nlat, nlon)`` on the GCM Gaussian grid (latitudes ascending, see
  ``meta.json``; longitudes uniform from 0° eastward).  Arrays are written so
  ``np.load(..., mmap_mode="r")`` can read single frames.
- ``tracks.json``: cyclone tracks (:mod:`dreamulator.gcm.cyclones`), with the
  per-point fields named like ``media.cyclone_render.Cyclone``.
- ``meta.json``: grid, variables with units, per-frame time, orbital phase and
  sub-solar point, the calendar conversion and the detection thresholds.

Derived variables:

- **Cloud levels** are the ISCCP levels of :func:`~dreamulator.gcm.to_mesh.cloud_levels`
  (random overlap within each level).
- **Cloud-top pressure and height** weight each layer by the probability that it
  is the highest cloud seen from space under random overlap,
  ``c_k · Π_{j above k} (1 − c_j)``, normalised by the total of those weights
  (a diagnostic definition, the same overlap assumption as the levels).  Clear
  columns (total weight below 0.01) are NaN.
- **Heights** are integrated from the surface with the hypsometric equation,
  ``dz = (R_d T / g) d ln p`` on the sigma half levels, using the layer
  temperature ``ta`` (dry air, no virtual-temperature correction: an
  approximate derivation good to about 1%).  ExoPlaSim's snapshot ``zg`` is not
  used: pyburn writes values that are not geopotential heights.
- **Winds** are taken on the model levels nearest sigma 0.82, 0.57 and 0.32,
  roughly the boundary layer top, the low and mid cloud shell (about 4–5 km)
  and the cirrus shell (about 9 km).
- **Sub-solar point** is the unit-vector mean of the grid weighted by
  ``max(cos z, 0)⁸``, which peaks sharply at the sub-solar cell.

All values are instantaneous; nothing is time-averaged.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from dreamulator.gcm.cyclones import (
    EARTH_ROTATION_RAD_S,
    DetectionParams,
    GridGeometry,
    detect_candidates,
    stitch_tracks,
)
from dreamulator.gcm.to_mesh import bilinear_to_points, cloud_levels

PACK_FORMAT = "weather-pack-v1"
R_DRY_J_KG_K = 287.05

#: Target sigma levels for the wind and vorticity fields (see the module docstring).
WIND_SIGMAS = {"low": 0.82, "mid": 0.57, "high": 0.32}

#: name -> (units, description)
FIELDS: dict[str, tuple[str, str]] = {
    "cloud_total": ("1", "total cloud cover (model clt)"),
    "cloud_low": ("1", "low cloud cover, p > 680 hPa"),
    "cloud_mid": ("1", "mid cloud cover, 440-680 hPa"),
    "cloud_high": ("1", "high cloud cover, p < 440 hPa"),
    "cloud_top_pressure": ("hPa", "cloud-top pressure (random-overlap weighting; NaN = clear)"),
    "cloud_top_height": ("km", "cloud-top height above sea level (NaN = clear)"),
    "precip": ("mm/h", "total precipitation rate"),
    "precip_convective": ("mm/h", "convective precipitation rate"),
    "slp": ("hPa", "sea-level pressure"),
    "u_low": ("m/s", "eastward wind near sigma 0.82"),
    "v_low": ("m/s", "northward wind near sigma 0.82"),
    "u_mid": ("m/s", "eastward wind near sigma 0.57"),
    "v_mid": ("m/s", "northward wind near sigma 0.57"),
    "u_high": ("m/s", "eastward wind near sigma 0.32"),
    "v_high": ("m/s", "northward wind near sigma 0.32"),
    "vorticity_low": ("1/s", "relative vorticity near sigma 0.82"),
    "sea_ice": ("1", "sea-ice cover"),
    "surface_temperature": ("degC", "surface temperature"),
}

#: Written only when the run had storm climatology on (``stormclim``): name -> (source, units,
#: description).  ExoPlaSim's genesis potential index (Emanuel & Nolan 2004) and maximum
#: potential intensity (Bister & Emanuel 2002) say where the large-scale environment could
#: sustain a tropical cyclone, independently of whether T42 resolves one.
OPTIONAL_FIELDS: dict[str, tuple[str, str, str]] = {
    "tc_genesis_potential": ("gpi", "1", "tropical-cyclone genesis potential index"),
    "tc_potential_intensity": ("umax", "m/s", "tropical-cyclone maximum potential intensity"),
}


def cloud_top(cl: np.ndarray, p_hpa: np.ndarray, z_km: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Cloud-top pressure and height under random overlap (pure function).

    ``cl``, ``p_hpa`` and ``z_km`` have shape ``(..., nlev, nlat, nlon)`` with the
    level axis ordered from the model top downward (sigma ascending).
    """
    c = np.clip(cl, 0.0, 1.0)
    clear_above = np.cumprod(1.0 - c, axis=-3)
    clear_above = np.concatenate([np.ones_like(c[..., :1, :, :]), clear_above[..., :-1, :, :]], -3)
    w = c * clear_above
    total = w.sum(axis=-3)
    with np.errstate(invalid="ignore", divide="ignore"):
        ctp = np.where(total > 0.01, (w * p_hpa).sum(axis=-3) / total, np.nan)
        cth = np.where(total > 0.01, (w * z_km).sum(axis=-3) / total, np.nan)
    return ctp, cth


def hypsometric_heights(
    ta_k: np.ndarray, sigma_half: np.ndarray, zs_m: np.ndarray, gravity_m_s2: float
) -> tuple[np.ndarray, np.ndarray]:
    """Full- and half-level heights (m) from layer temperatures (pure function).

    ``ta_k`` has shape ``(..., nlev, nlat, nlon)`` ordered top to surface,
    ``sigma_half`` the ``nlev + 1`` interface sigmas (last = 1) and ``zs_m`` the
    surface height.  Pressure ratios are surface-pressure independent in sigma,
    so ``ln(p_a / p_b) = ln(sigma_a / sigma_b)``.
    """
    nlev = ta_k.shape[-3]
    scale = R_DRY_J_KG_K / gravity_m_s2
    half = np.empty((*ta_k.shape[:-3], nlev + 1, *ta_k.shape[-2:]))
    half[..., nlev, :, :] = zs_m
    full = np.empty_like(ta_k, dtype=float)
    for k in range(nlev - 1, -1, -1):
        lower, upper = sigma_half[k + 1], sigma_half[k]
        mid = math.sqrt(lower * upper)
        full[..., k, :, :] = half[..., k + 1, :, :] + scale * ta_k[..., k, :, :] * math.log(
            lower / mid
        )
        half[..., k, :, :] = half[..., k + 1, :, :] + scale * ta_k[..., k, :, :] * math.log(
            lower / upper
        )
    return full, half


def subsolar_point(
    czen: np.ndarray, lat_deg: np.ndarray, lon_deg: np.ndarray
) -> tuple[float, float]:
    """Sub-solar latitude and longitude (degrees, lon in [0, 360)) from cos(zenith) (pure)."""
    la, lo = np.meshgrid(np.radians(lat_deg), np.radians(lon_deg), indexing="ij")
    w = np.clip(czen, 0.0, None) ** 8 * np.cos(la)
    x, y, z = (
        (w * np.cos(la) * np.cos(lo)).sum(),
        (w * np.cos(la) * np.sin(lo)).sum(),
        (w * np.sin(la)).sum(),
    )
    return math.degrees(math.atan2(z, math.hypot(x, y))), math.degrees(math.atan2(y, x)) % 360.0


def nearest_level(sigma: np.ndarray, target: float) -> int:
    return int(np.argmin(np.abs(np.asarray(sigma) - target)))


@dataclass
class PackCalendar:
    """Model time to physical time (see :func:`build_pack`).

    ``hours_per_step`` is the real-time step (PlaSim's ``MPSTEP`` in minutes / 60);
    the model day is the sidereal rotation, so a slow rotator has many steps per
    model day (nacrea: 101 steps of 45 min in 3.13 Earth days).
    """

    hours_per_step: float
    sidereal_day_h: float
    orbital_year_days: float


def build_pack(
    snapshot_nc: str | Path,
    out_dir: str | Path,
    *,
    calendar: PackCalendar,
    radius_km: float,
    gravity_m_s2: float,
    rotation_rad_s: float,
    provenance: dict[str, Any] | None = None,
    stride: int = 1,
    batch: int = 64,
) -> dict[str, Any]:
    """Write a weather pack from an ExoPlaSim snapshot NetCDF file; returns ``meta``.

    ``stride`` keeps every ``stride``-th snapshot (detection and tracking run on
    the kept frames, so the TempestExtremes thresholds apply at that cadence).
    """
    import netCDF4

    from dreamulator.gcm.diagnostics import equinox_day_from_declination

    out = Path(out_dir)
    (out / "fields").mkdir(parents=True, exist_ok=True)
    ds = netCDF4.Dataset(str(snapshot_nc))
    lat_raw = np.asarray(ds["lat"][:], dtype=float)
    order = np.argsort(lat_raw)
    lat = lat_raw[order]
    lon = np.asarray(ds["lon"][:], dtype=float)
    sigma = np.asarray(ds["lev"][:], dtype=float)
    sigma_half = np.asarray(ds["levp"][:], dtype=float)
    keep = np.arange(0, ds["time"].shape[0], max(stride, 1))
    steps = np.asarray(ds["time"][:], dtype=float)[keep]
    n = steps.size
    nlat, nlon = lat.size, lon.size
    k = {name: nearest_level(sigma, s) for name, s in WIND_SIGMAS.items()}
    k300, k500 = nearest_level(sigma_half, 0.30), nearest_level(sigma_half, 0.50)
    zsurf = np.asarray(ds["sg"][0], dtype=float)[order, :] / gravity_m_s2
    lsm = np.asarray(ds["lsm"][0], dtype=float)[order, :]

    optional = {k: v for k, v in OPTIONAL_FIELDS.items() if v[0] in ds.variables}
    arrays = {
        name: np.lib.format.open_memmap(
            out / "fields" / f"{name}.npy", mode="w+", dtype=np.float32, shape=(n, nlat, nlon)
        )
        for name in (*FIELDS, *optional)
    }
    geom = GridGeometry(lat, lon, radius_km)
    params = DetectionParams(rotation_scale=EARTH_ROTATION_RAD_S / rotation_rad_s)
    candidates = []
    subsolar = []
    mean_cth = np.zeros(sigma.size)

    def read(name: str, sl: slice) -> np.ndarray:
        return np.asarray(ds[name][keep[sl]], dtype=float)[..., order, :]

    for start in range(0, n, batch):
        sl = slice(start, min(start + batch, n))
        cl, ps = read("cl", sl), read("ps", sl)
        z_full, z_half = hypsometric_heights(read("ta", sl), sigma_half, zsurf, gravity_m_s2)
        p_full = sigma[None, :, None, None] * ps[:, None, :, :]
        z_full_km = z_full / 1000.0
        low, mid, high = cloud_levels(cl, ps, sigma)
        ctp, cth = cloud_top(cl, p_full, z_full_km)
        mean_cth += z_full_km.mean(axis=(0, 2, 3)) * (sl.stop - sl.start)
        ua, va, zeta = read("ua", sl), read("va", sl), read("zeta", sl)
        psl = read("psl", sl) / 100.0  # pyburn labels psl hPa but writes Pa
        arrays["cloud_total"][sl] = read("clt", sl)
        arrays["cloud_low"][sl], arrays["cloud_mid"][sl], arrays["cloud_high"][sl] = low, mid, high
        arrays["cloud_top_pressure"][sl], arrays["cloud_top_height"][sl] = ctp, cth
        arrays["precip"][sl] = read("pr", sl) * 1000.0 * 3600.0
        arrays["precip_convective"][sl] = read("prc", sl) * 1000.0 * 3600.0
        arrays["slp"][sl] = psl
        for lvl, kk in k.items():
            arrays[f"u_{lvl}"][sl], arrays[f"v_{lvl}"][sl] = ua[:, kk], va[:, kk]
        arrays["vorticity_low"][sl] = zeta[:, k["low"]]
        arrays["sea_ice"][sl] = read("sic", sl)
        arrays["surface_temperature"][sl] = read("ts", sl) - 273.15
        for name, (source, _, _) in optional.items():
            arrays[name][sl] = read(source, sl)
        czen = read("czen", sl)
        sic_now = arrays["sea_ice"][sl]
        speed = np.hypot(ua[:, -1], va[:, -1])
        thickness = z_half[:, k300] - z_half[:, k500]
        for t in range(sl.stop - sl.start):
            subsolar.append(subsolar_point(czen[t], lat, lon))
            candidates.append(
                detect_candidates(
                    psl[t],
                    speed[t],
                    thickness[t],
                    geom,
                    params,
                    vorticity_s=zeta[t, k["low"]],
                    surface_height_m=zsurf,
                    ocean=(lsm < 0.5) & (sic_now[t] < 0.5),
                )
            )
    for a in arrays.values():
        a.flush()

    hours = (steps - steps[0]) * calendar.hours_per_step
    tracks = stitch_tracks(candidates, hours, params, radius_km)
    steps_per_day = 24.0 / calendar.hours_per_step  # steps per Earth day
    declination = np.asarray(ds["zdec"][:], dtype=float)[keep]
    equinox_day = equinox_day_from_declination(
        steps,
        declination,
        orbital_year_days=calendar.orbital_year_days,
        steps_per_model_day=steps_per_day,
    )
    days = steps / steps_per_day
    phase = ((days - equinox_day) % calendar.orbital_year_days) / calendar.orbital_year_days
    sub_lon = np.unwrap(np.radians([s[1] for s in subsolar]))
    drift = np.polyfit(hours, sub_lon, 1)[0] if n > 2 else float("nan")
    solar_day_h = abs(2 * math.pi / drift) if drift else float("nan")

    meta: dict[str, Any] = {
        "format": PACK_FORMAT,
        "frames": int(n),
        "grid": {
            "lat_deg": [round(float(v), 5) for v in lat],
            "lon_deg": [round(float(v), 5) for v in lon],
            "lat_order": "ascending (south to north)",
            "lon_convention": "degrees east from 0, uniform",
        },
        "levels": {
            name: {
                "sigma": round(float(sigma[kk]), 4),
                "mean_height_km": round(float(mean_cth[kk] / n), 2),
            }
            for name, kk in k.items()
        },
        "fields": {
            **{name: {"units": u, "description": d} for name, (u, d) in FIELDS.items()},
            **{name: {"units": u, "description": d} for name, (_, u, d) in optional.items()},
        },
        "time": {
            "hours_since_start": [round(float(h), 3) for h in hours],
            "orbital_phase": [round(float(p), 5) for p in phase],
            "phase_origin": "northern vernal equinox (fitted from zdec)",
            "declination_deg": [round(float(v), 4) for v in declination],
            "subsolar_lat_deg": [round(s[0], 3) for s in subsolar],
            "subsolar_lon_deg": [round(s[1], 3) for s in subsolar],
        },
        "calendar": {
            "hours_per_step": calendar.hours_per_step,
            "stride": int(max(stride, 1)),
            "frame_interval_h": round(float(np.median(np.diff(hours))), 4) if n > 1 else None,
            "sidereal_day_h": calendar.sidereal_day_h,
            "solar_day_h_diagnosed": round(solar_day_h, 3),
            "orbital_year_days": calendar.orbital_year_days,
        },
        "cyclones": {
            "count": len(tracks),
            "by_kind": {
                kind: sum(t.kind == kind for t in tracks) for kind in ("tropical", "extratropical")
            },
            "stationary": sum(t.stationary for t in tracks),
            "detection": params.describe(),
        },
        "provenance": provenance or {},
    }
    (out / "tracks.json").write_text(
        json.dumps({"tracks": [t.to_dict() for t in tracks]}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (out / "meta.json").write_text(
        json.dumps(meta, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return meta


@dataclass
class WeatherPack:
    """A loaded pack; fields are memory-mapped ``(frames, nlat, nlon)`` arrays."""

    path: Path
    meta: dict[str, Any]
    tracks: list[dict[str, Any]]

    @property
    def lat(self) -> np.ndarray:
        return np.asarray(self.meta["grid"]["lat_deg"], dtype=float)

    @property
    def lon(self) -> np.ndarray:
        return np.asarray(self.meta["grid"]["lon_deg"], dtype=float)

    def field(self, name: str) -> np.ndarray:
        out: np.ndarray = np.load(self.path / "fields" / f"{name}.npy", mmap_mode="r")
        return out

    def frame_equirect(self, name: str, frame: int, width: int, height: int) -> np.ndarray:
        """One frame resampled to an equirectangular ``(height, width)`` grid.

        Rows run north to south and columns from −180° to 180° (pixel centres),
        the convention of ``map.export`` and the media chain.
        """
        lat = 90.0 - (np.arange(height) + 0.5) / height * 180.0
        lon = (np.arange(width) + 0.5) / width * 360.0 - 180.0
        la, lo = np.meshgrid(lat, lon, indexing="ij")
        values = np.asarray(self.field(name)[frame], dtype=float)
        out: np.ndarray = bilinear_to_points(self.lat, self.lon, values, la, lo)
        return out


def load_pack(path: str | Path) -> WeatherPack:
    p = Path(path)
    meta = json.loads((p / "meta.json").read_text(encoding="utf-8"))
    if meta.get("format") != PACK_FORMAT:
        raise ValueError(f"{p} is not a {PACK_FORMAT} pack (format {meta.get('format')!r})")
    tracks = json.loads((p / "tracks.json").read_text(encoding="utf-8"))["tracks"]
    return WeatherPack(path=p, meta=meta, tracks=tracks)


__all__ = [
    "FIELDS",
    "OPTIONAL_FIELDS",
    "PACK_FORMAT",
    "WIND_SIGMAS",
    "PackCalendar",
    "WeatherPack",
    "build_pack",
    "cloud_top",
    "hypsometric_heights",
    "load_pack",
    "nearest_level",
    "subsolar_point",
]
