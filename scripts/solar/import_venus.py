#!/usr/bin/env python3
"""Import the Venus reference body (UCC-01 4d, earth anchor world): Magellan + VCD.

Venus is the UCC contract's **hot-side stress case** (knowledge doc §8): a
~737 K near-isothermal surface where the Hamon demand model is far outside its
liquid-water calibration domain — the out_of_domain gate currently only covers
the cold side, so Venus' AI is arithmetic extrapolation and must be read as
such (declared in provenance; a hot-side domain gate is registered as future
work).

- **Topography** — USGS ``Venus_Magellan_Topography_Global_4641m_v02.tif``:
  GeoTIFF int16 metres vs the 6051.8 km mean radius, 4096×8192 (0.044°/px),
  row 0 = 90°N, col 0 = −180°E (ModelTiepoint/landmark verified: Maxwell
  Montes 65°N 5°E → +9.9 km).  ±3.8° polar caps are NODATA (−32768, no
  Magellan coverage) → filled by per-column nearest-valid copy.
- **Climate** — Venus Climate Database v2.3 (LMD), standard cloud-albedo
  scenario / average solar EUV, fetched registration-free from the web
  interface (same architecture as MCD; recipe in
  ``scripts/solar/fetch_lmd_slices.py``): 12 ``tsurf`` maps at the Ls-bin
  centres, cached as ``vcd_tsurf_ls{015..345}.txt`` (+ ``vcd_ps_*`` for
  context).  **Fixed local-time slices (12 Vhrs), NOT diurnal averages** — the
  VCD CGI hangs on ``averaging=loct`` (observed 2026-09-21); under the 92-bar
  atmosphere the surface diurnal range is negligible (~K-level), declared in
  provenance.  Precipitation is **declared zero** — no precipitation reaches
  the surface (H₂SO₄ cloud rain evaporates as virga).  Demand model: Hamon is
  KEPT (``demand_model="hamon-1961"``) as the registered **hot-side
  extrapolation demonstration** (knowledge doc §8): at ~737 K the formula is
  arithmetic extrapolation far outside its liquid-water calibration; the
  resulting AI=0/deficit=1 (Ra-w planet-wide) is contract-valid but physically
  meaningless, and the provenance says so loudly.  A hot-side out_of_domain
  gate is registered as future work.

Usage:
    uv run python scripts/solar/import_venus.py [--mesh-nodes 10000]
    uv run python scripts/solar/import_venus.py --skip-climate   # terrain only
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
    load_lmd_slices,
    register_solar_planet,
    sample_regular_grid,
    write_climate_monthly,
    write_climate_secondary,
    write_ucc_yearly,
)

_CACHE = _ROOT / "private/tmp/solar"
_TOPO_TIF = "venus_magellan_topo.tif"
_TOPO_URL = "https://planetarymaps.usgs.gov/mosaic/Venus_Magellan_Topography_Global_4641m_v02.tif"

# Grid geometry (geotag + landmark verified 2026-09-21): pixel-centre
# registration, 8192×4096 over 360°×180°.
_DPIX = 360.0 / 8192
_LAT_START, _DLAT = 90.0 - _DPIX / 2, -_DPIX
_LON_START, _DLON = -180.0 + _DPIX / 2, _DPIX

VENUS_RADIUS_KM = 6051.8  # mean radius (topo datum)
VENUS_YEAR_DAYS = 224.701  # Earth days (sidereal orbit)
VENUS_BIN_DAYS = VENUS_YEAR_DAYS / 12.0
_NODATA = -32768.0

# Landmark verification anchors: (name, lat, lon(−180..180), min_m, max_m)
_LANDMARKS = [
    ("Maxwell Montes (Ishtar Terra)", 65.0, 5.0, 8_000.0, 11_500.0),
    ("Aphrodite Terra", -10.0, -160.0, 500.0, 4_500.0),
    ("Equatorial lowlands (0°, 0°)", 0.0, 0.0, -1_500.0, 1_500.0),
]


def _fill_nan_columns(dem: np.ndarray) -> np.ndarray:
    """Fill NaN runs (polar Magellan gaps) per column with the nearest valid row."""
    out = dem.copy()
    h, w = out.shape
    rows = np.arange(h)[:, None]
    valid = np.isfinite(out)
    fwd = np.maximum.accumulate(np.where(valid, rows, -1), axis=0)  # nearest above
    bwd = np.minimum.accumulate(np.where(valid, rows, h)[::-1], axis=0)[::-1]  # below
    dist_f = np.where(fwd >= 0, rows - fwd, np.inf)
    dist_b = np.where(bwd < h, bwd - rows, np.inf)
    idx = np.where(dist_f <= dist_b, fwd, bwd)
    ok = (idx >= 0) & (idx < h)
    cols = np.broadcast_to(np.arange(w), (h, w))
    filled = out[idx[ok], cols[ok]]
    out[ok] = filled
    return out


def load_magellan(path: Path) -> np.ndarray:
    """USGS Magellan GeoTIFF → metres, NODATA-filled, landmark-verified."""
    import tifffile

    raw = np.asarray(tifffile.imread(str(path))).astype(np.float64)
    if raw.shape != (4096, 8192):
        raise ValueError(f"{path.name}: expected 4096×8192, got {raw.shape}")
    raw[raw == _NODATA] = np.nan
    n_nan = int(np.isnan(raw).sum())
    dem = _fill_nan_columns(raw)
    print(f"  NODATA polar gap: {n_nan / raw.size:.1%} of pixels column-filled")
    for name, la, lo, lo_min, lo_max in _LANDMARKS:
        v = float(
            sample_regular_grid(
                dem,
                lat_start=_LAT_START,
                dlat=_DLAT,
                lon_start=_LON_START,
                dlon=_DLON,
                lats=np.array([la]),
                lons=np.array([lo]),
            )[0]
        )
        if not (lo_min <= v <= lo_max):
            raise ValueError(f"{name}: sampled {v:.0f} m, expected {lo_min}..{lo_max} m")
        print(f"  Landmark check: {name} = {v:.0f} m ✓")
    return dem


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    # Mesh scaled to the VCD web grid (~1.9°): 10k cells ≈ 2.0° spacing —
    # data-native.  (Magellan topo is 0.044° but only feeds visualization.)
    parser.add_argument("--mesh-nodes", type=int, default=10_000)
    parser.add_argument("--skip-climate", action="store_true", help="terrain/mesh only")
    parser.add_argument("--data-dir", type=Path, default=_ROOT / "data/worlds")
    parser.add_argument("--proxy", default=None, help="HTTP proxy for curl downloads")
    args = parser.parse_args()

    map_dir = register_solar_planet(args.data_dir, "planet_venus")

    topo_path = _CACHE / _TOPO_TIF
    if not topo_path.exists():
        print("Downloading Magellan topography from USGS (~64 MB) …")
        import subprocess

        attempts = []
        if args.proxy:
            attempts.append(
                ["curl", "-sSL", "--proxy", args.proxy, "-o", str(topo_path), _TOPO_URL]
            )
        attempts.append(["curl", "-sSL", "-o", str(topo_path), _TOPO_URL])
        for cmd in attempts:
            r = subprocess.run(cmd, capture_output=True)
            if r.returncode == 0 and topo_path.exists() and topo_path.stat().st_size > 1_000_000:
                break
            topo_path.unlink(missing_ok=True)
        if not topo_path.exists():
            raise RuntimeError(f"download failed: {_TOPO_URL}")
    print(f"Loading Magellan DEM from {topo_path} …")
    dem = load_magellan(topo_path)

    mesh = build_mesh_from_dem(
        dem,
        lat_start=_LAT_START,
        dlat=_DLAT,
        lon_start=_LON_START,
        dlon=_DLON,
        radius_km=VENUS_RADIUS_KM,
        num_nodes=args.mesh_nodes,
        output_dir=map_dir,
        planet_id="planet_venus",
        source="USGS Venus Magellan Global Topography 4641m v02",
        source_resolution=(
            "0.044° (~4.6 km); datum = 6051.8 km mean radius; ±3.8° polar gaps filled"
        ),
    )

    if args.skip_climate:
        print("--skip-climate: terrain done; climate steps skipped.")
        return

    t_kelvin, vcd_meta, header = load_lmd_slices(_CACHE / "venus", "vcd_tsurf")
    t_bins = t_kelvin - 273.15  # (12, nlat, nlon) °C  (~+460 °C)
    ps_pa, _, _ = load_lmd_slices(_CACHE / "venus", "vcd_ps")
    ls_line = next((h for h in header if h.startswith("Ls ")), "Ls ?")
    version_line = next((h for h in header if "VCD" in h), "VCD (version unknown)")

    lats = np.array([c.lat for c in mesh.cells], dtype=np.float64)
    lons = np.mod(np.array([c.lon for c in mesh.cells], dtype=np.float64), 360.0)
    t_monthly = np.empty((mesh.num_cells, 12))
    for m in range(12):
        t_monthly[:, m] = sample_regular_grid(t_bins[m], **vcd_meta, lats=lats, lons=lons)
    # No precipitation reaches the Venus surface (H₂SO₄ virga) — declared zero.
    p_monthly = np.zeros((mesh.num_cells, 12))

    write_climate_monthly(
        map_dir,
        t_monthly,
        p_monthly,
        bin_days=VENUS_BIN_DAYS,
        month_0="ls_15_first_bin_center",
        extra_metadata={
            "time_basis": (
                f"12 Ls-bin centres (30° bins), {VENUS_YEAR_DAYS} d Venus year; "
                "fixed local-time (12 Vhrs) slices"
            ),
            "gcm_slice_header": ls_line,
            "surface_pressure_pa_mean": float(ps_pa.mean()),
        },
    )
    apply_climate_to_mesh(map_dir, t_monthly.mean(axis=1), p_monthly.sum(axis=1))
    write_climate_secondary(map_dir, source=f"{version_line}; fixed-LT Ls-bin climatology")

    combos = write_ucc_yearly(
        map_dir,
        data_source="gcm-climatology",
        provenance={
            "gcm": f"{version_line} — web-interface 2D ASCII slices "
            f"(standard cloud albedo / average EUV; fixed local time 12 Vhrs, "
            f"NOT diurnal-averaged — surface diurnal range negligible), {ls_line}",
            "temperature": "VCD `tsurf` surface temperature (K→°C); with the 92-bar "
            "atmosphere surface ≈ near-surface air (near-isothermal ~737 K)",
            "precipitation": "declared zero — no precipitation reaches the surface "
            "(H₂SO₄ cloud rain evaporates as virga)",
            "surface_pressure": f"VCD `ps` diurnal mean; global mean {ps_pa.mean() / 1000:.0f} kPa",
            "topography": "USGS Venus Magellan Global Topography 4641m v02",
            "epistemic_status": "L4 GCM climatology (ucc-review §6.2): a model, "
            "not error-free truth",
            "demand_model_warning": "HOT-SIDE EXTRAPOLATION (knowledge doc §8 "
            "registered gap): Hamon at ~737 K is arithmetic extrapolation far "
            "outside its liquid-water calibration domain; AI=0 (arid) / deficit=1 "
            "(water_stress) are contract-valid but physically meaningless here. "
            "The cold-side out_of_domain gate does NOT cover the hot side; a "
            "hot-side gate is future work.",
            "time_basis": f"bin = {VENUS_BIN_DAYS:.2f} Earth-days (Venus month); "
            f"p_total per Venus year ({VENUS_YEAR_DAYS} d)",
        },
        demand_model="hamon-1961",
    )
    print("Land classes:", sorted(combos.items(), key=lambda kv: -kv[1]))


if __name__ == "__main__":
    main()
