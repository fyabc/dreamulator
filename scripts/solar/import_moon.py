#!/usr/bin/env python3
"""Import the Moon reference body (UCC-01 4d, earth anchor world): LDEM + Diviner.

The Moon (``satellite_moon`` inside the earth anchor world) is the Solar-System
reference bodies' **observation exception**: LRO
Diviner is observation-grade (like earth's NCEP/GPCP), but its temperature is
SURFACE (skin) temperature, not near-surface air — there is no atmosphere.
Declared semantics (they travel in provenance / file metadata):

- ``temperature_kind: surface`` — Diviner bolometric brightness temperature
  (``tbol``) as the surface-temperature proxy (Williams et al. 2017, Icarus
  283:300 derive SPT by multi-channel Boltzmann fitting; tbol is the published
  bolometric column of the same GCP product).
- **Bins are local-time bins, not months**: the GCP cumulative climatology
  (nadir observations 2009-07-05…2015-04-01) is binned 0.25 h local time ×
  0.5° lat/lon; aggregated here to 12 × 2 h bins over one synodic rotation
  (29.5306 Earth-days; ``bin_days`` = 2.4609).  Consequence: ``t_range`` is the
  DIURNAL range (equator ~280 °C) and the ``continental`` modifier flags
  diurnal extremes, not seasonality; seasonal information is averaged out in
  the cumulative product.
- No atmosphere → P ≡ 0 (declared; exercises the concentration-undefined path)
  and demand_model=None → AI/deficit = missing_input.

Data: PDS ``LRO-L-DLRE-5-GCP-V1.0`` (pds-geosciences.wustl.edu, registration-
free), 18 latitude bands × ~156 MB ASCII ``global_cumul_avg_cyl_<band>_002.tab``
(columns clon/clat/ltim/t3…t9/tbol; −9999 = no observation; negative tbol =
below channel sensitivity → invalid).  Cache: ``private/tmp/solar/*.tab``.

Usage:
    uv run python scripts/solar/import_moon.py [--mesh-nodes 100000]
    uv run python scripts/solar/import_moon.py --skip-climate   # terrain only
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "src"))

from dreamulator.import_solar_common import (  # noqa: E402
    apply_climate_to_mesh,
    build_mesh_from_dem,
    register_solar_planet,
    sample_regular_grid,
    write_climate_monthly,
    write_climate_secondary,
    write_ucc_yearly,
)

_CACHE = _ROOT / "private/tmp/solar"
_LDEM_TIF = "moon_ldem_4.tif"
_LDEM_URL = "https://svs.gsfc.nasa.gov/vis/a000000/a004700/a004720/ldem_4.tif"
_GCP_BASE = (
    "https://pds-geosciences.wustl.edu/lro/"
    "urn-nasa-pds-lro_diviner_derived1/data_derived_gcp/global_cumul_avg_cyl_{band}_002.tab"
)
_BANDS = [
    "90s80s",
    "80s70s",
    "70s60s",
    "60s50s",
    "50s40s",
    "40s30s",
    "30s20s",
    "20s10s",
    "10s00s",
    "00n10n",
    "10n20n",
    "20n30n",
    "30n40n",
    "40n50n",
    "50n60n",
    "60n70n",
    "70n80n",
    "80n90n",
]

# LDEM_4 geometry (landmark-verified 2026-09-21): pixel-centre registration,
# rows north→south from +89.875°, cols west→east from −179.875°, 0.25°/px.
_LDEM_LAT_START, _LDEM_DLAT = 89.875, -0.25
_LDEM_LON_START, _LDEM_DLON = -179.875, 0.25

MOON_RADIUS_KM = 1737.4  # mean radius (LDEM datum)
SYNODIC_DAYS = 29.530588  # Earth days per synodic rotation (solar day)
MOON_BIN_DAYS = SYNODIC_DAYS / 12.0  # 2 h local-time bins

# GCP grid: 0.5° pixels, centres at −89.75…+89.75 / −179.75…+179.75.
_GCP_LAT0, _GCP_LON0, _GCP_D = -89.75, -179.75, 0.5
_NLAT, _NLON, _NLT = 360, 720, 96

# Landmark verification anchors: (name, lat, lon(−180..180), min_m, max_m)
_LANDMARKS = [
    ("Nearside centre (mare)", 0.0, 0.0, -3_000.0, 500.0),
    ("Farside centre (highlands)", 0.0, 180.0, 1_000.0, 6_000.0),
    ("South Pole–Aitken floor", -53.0, -169.0, -9_000.0, -4_000.0),
]


def load_ldem(path: Path) -> np.ndarray:
    """LDEM GeoTIFF (km) → metres; landmark-verified orientation."""
    import tifffile

    raw = np.asarray(tifffile.imread(str(path))).astype(np.float64)
    if raw.shape != (720, 1440):
        raise ValueError(f"{path.name}: expected 720×1440, got {raw.shape}")
    dem = raw * 1_000.0  # km → m
    for name, la, lo, lo_min, lo_max in _LANDMARKS:
        v = float(
            sample_regular_grid(
                dem,
                lat_start=_LDEM_LAT_START,
                dlat=_LDEM_DLAT,
                lon_start=_LDEM_LON_START,
                dlon=_LDEM_DLON,
                lats=np.array([la]),
                lons=np.array([lo]),
            )[0]
        )
        if not (lo_min <= v <= lo_max):
            raise ValueError(f"{name}: sampled {v:.0f} m, expected {lo_min}..{lo_max} m")
        print(f"  Landmark check: {name} = {v:.0f} m ✓")
    return dem


def aggregate_gcp(cache: Path) -> tuple[np.ndarray, float]:
    """Aggregate the 18 GCP bands → (T (12 bins, 360 lat, 720 lon) °C, fill fraction).

    tbol valid where 0 < tbol < 1000 and ≠ −9999.  Missing bin values fall
    back to (1) the cell's all-LT mean, (2) the bin's zonal (lat-circle) mean,
    (3) the bin's global mean — fills are counted and reported.
    """
    import pandas as pd

    tsum = np.zeros(12 * _NLAT * _NLON)
    tcnt = np.zeros(12 * _NLAT * _NLON)
    for band in _BANDS:
        path = cache / f"global_cumul_avg_cyl_{band}_002.tab"
        if not path.exists():
            raise FileNotFoundError(f"{path} missing — download the GCP band (see docstring)")
        print(f"  parsing {path.name} …")
        df = pd.read_csv(path, skipinitialspace=True)
        df.columns = [str(c).strip() for c in df.columns]
        clon = df["clon"].to_numpy(np.float64)
        clat = df["clat"].to_numpy(np.float64)
        ltim = df["ltim"].to_numpy(np.float64)
        tbol = df["tbol"].to_numpy(np.float64)
        lat_i = np.rint((clat - _GCP_LAT0) / _GCP_D).astype(np.int64)
        lon_i = np.rint((clon - _GCP_LON0) / _GCP_D).astype(np.int64) % _NLON
        lt_i = np.clip((ltim // 0.25).astype(np.int64), 0, _NLT - 1)
        bin_i = lt_i // 8  # 8 × 0.25 h = 2 h bins
        ok = np.isfinite(tbol) & (tbol > 0.0) & (tbol < 1000.0) & (lat_i >= 0) & (lat_i < _NLAT)
        flat = (bin_i * _NLAT + lat_i) * _NLON + lon_i
        tsum += np.bincount(flat[ok], weights=tbol[ok], minlength=tsum.size)
        tcnt += np.bincount(flat[ok], minlength=tcnt.size)

    with np.errstate(invalid="ignore", divide="ignore"):
        t_kelvin = np.where(tcnt > 0, tsum / np.maximum(tcnt, 1), np.nan).reshape(12, _NLAT, _NLON)

    # Fallback chain for missing bins: cell all-LT mean → zonal mean → global.
    import warnings

    nan = ~np.isfinite(t_kelvin)
    n_missing = int(nan.sum())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN slices
        cell_mean = np.nanmean(t_kelvin, axis=0, keepdims=True)
        t_kelvin = np.where(nan, np.broadcast_to(cell_mean, t_kelvin.shape), t_kelvin)
        nan = ~np.isfinite(t_kelvin)
        if nan.any():
            zonal = np.nanmean(t_kelvin, axis=2, keepdims=True)
            t_kelvin = np.where(nan, np.broadcast_to(zonal, t_kelvin.shape), t_kelvin)
        nan = ~np.isfinite(t_kelvin)
        if nan.any():
            gmean = np.nanmean(t_kelvin, axis=(1, 2), keepdims=True)
            t_kelvin = np.where(nan, np.broadcast_to(gmean, t_kelvin.shape), t_kelvin)
    fill_frac = n_missing / t_kelvin.size
    return t_kelvin - 273.15, fill_frac


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    # Mesh scaled to the Diviner GCP grid (0.5°): 100k cells ≈ 0.64° spacing
    # — closest solar body to its data-native resolution (GCP is the finest
    # climate source in the set; LDEM topo is even finer at 0.25°).
    parser.add_argument("--mesh-nodes", type=int, default=100_000)
    parser.add_argument("--skip-climate", action="store_true", help="terrain/mesh only")
    parser.add_argument("--data-dir", type=Path, default=_ROOT / "data/worlds")
    args = parser.parse_args()

    map_dir = register_solar_planet(args.data_dir, "satellite_moon")

    ldem_path = _CACHE / _LDEM_TIF
    if not ldem_path.exists():
        print("Downloading LDEM_4 from NASA SVS …")
        import subprocess

        subprocess.run(
            [
                "curl",
                "-sSL",
                "--proxy",
                "http://127.0.0.1:10808",
                "-o",
                str(ldem_path),
                _LDEM_URL,
            ],
            check=False,
        )
        if not ldem_path.exists() or ldem_path.stat().st_size == 0:
            subprocess.run(["curl", "-sSL", "-o", str(ldem_path), _LDEM_URL], check=True)
    print(f"Loading LDEM from {ldem_path} …")
    dem = load_ldem(ldem_path)

    mesh = build_mesh_from_dem(
        dem,
        lat_start=_LDEM_LAT_START,
        dlat=_LDEM_DLAT,
        lon_start=_LDEM_LON_START,
        dlon=_LDEM_DLON,
        radius_km=MOON_RADIUS_KM,
        num_nodes=args.mesh_nodes,
        output_dir=map_dir,
        planet_id="satellite_moon",
        source="LRO LDEM_4 (NASA SVS Moon Kit, ldem_4.tif)",
        source_resolution="0.25° (~7.6 km at equator); datum = 1737.4 km mean radius",
    )
    # No hydrosphere, no atmosphere — every cell is land.
    print(f"  Land cells: {mesh.num_cells}/{mesh.num_cells} (all land)")

    if args.skip_climate:
        print("--skip-climate: terrain done; climate steps skipped.")
        return

    print("Aggregating Diviner GCP (18 bands × 156 MB) …")
    t_bins, fill_frac = aggregate_gcp(_CACHE)
    print(f"  GCP bin fill fraction: {fill_frac:.2%} (fallback chain applied)")
    # Sanity prints: equator day/night, south-pole cold trap.
    eq = t_bins[:, _NLAT // 2, _NLON // 2]
    print(f"  Equator (0,0) bins °C: min {eq.min():.0f}, max {eq.max():.0f}")
    sp = t_bins[:, 2, _NLON // 2]
    print(f"  Near south pole bins °C: min {sp.min():.0f}, max {sp.max():.0f}")

    lats = np.array([c.lat for c in mesh.cells], dtype=np.float64)
    lons = np.array([c.lon for c in mesh.cells], dtype=np.float64)
    gcp_meta = {"lat_start": _GCP_LAT0, "dlat": _GCP_D, "lon_start": _GCP_LON0, "dlon": _GCP_D}
    t_monthly = np.empty((mesh.num_cells, 12))
    for b in range(12):
        t_monthly[:, b] = sample_regular_grid(t_bins[b], **gcp_meta, lats=lats, lons=lons)
    p_monthly = np.zeros((mesh.num_cells, 12))  # vacuum — declared zero

    write_climate_monthly(
        map_dir,
        t_monthly,
        p_monthly,
        bin_days=MOON_BIN_DAYS,
        month_0="local_time_00h",
        extra_metadata={
            "time_basis": (
                f"12 × 2 h local-time bins over one synodic rotation "
                f"({SYNODIC_DAYS:.4f} Earth-days); t_range is the DIURNAL range; "
                "seasonality averaged out in the cumulative product"
            ),
            "temperature_kind": "surface (Diviner tbol, observation-grade)",
            "gcp_fill_fraction": fill_frac,
        },
    )
    apply_climate_to_mesh(map_dir, t_monthly.mean(axis=1), p_monthly.sum(axis=1))
    write_climate_secondary(
        map_dir, source="LRO Diviner GCP cumulative climatology (Williams et al. 2017)"
    )

    combos = write_ucc_yearly(
        map_dir,
        data_source="observation",
        provenance={
            "temperature": "LRO Diviner GCP (PDS LRO-L-DLRE-5-GCP-V1.0), bolometric "
            "brightness temperature tbol as SPT proxy; nadir observations "
            "2009-07-05…2015-04-01, 0.5° × 0.25 h LT bins aggregated to 12 × 2 h LT",
            "temperature_kind": "SURFACE temperature (no atmosphere) — declared "
            "exception to the near-surface-air contract",
            "precipitation": "declared zero — vacuum; no precipitation "
            "(concentration undefined by contract)",
            "demand_model_note": "NOT applied (demand_model=None) — no atmosphere, "
            "no PET model applies; AI/deficit = missing_input",
            "topography": "LRO LDEM_4 (NASA SVS Moon Kit)",
            "epistemic_status": "observation-grade (like earth root), NOT a GCM — "
            "but surface-temperature semantics differ from air temperature",
            "time_basis": f"bin = {MOON_BIN_DAYS:.4f} Earth-days (2 h local time); "
            "window = 1 synodic rotation, not a year",
        },
        demand_model=None,
    )
    print("Land classes:", sorted(combos.items(), key=lambda kv: -kv[1]))


if __name__ == "__main__":
    main()
