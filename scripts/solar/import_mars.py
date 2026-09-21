#!/usr/bin/env python3
"""Import the Mars reference body (UCC-01 4d, earth anchor world): MOLA + MCD climate.

Mars lives inside the real-world reference anchor (``earth`` world, planet_id
``planet_mars``, never built), data imported from:

- **Topography** — MOLA MEGDR 4 ppd (PDS MGS-MOLA-TOPO-DERIVED,
  ``megt90n000cb.img``): raw big-endian int16, 720×1440 (0.25°/px), metres
  relative to the areoid (MOLA radius 3396 km).  Grid geometry landmark-
  verified: row 0 = 90°N, **col 0 = 0°E** (Olympus Mons 226°E → +20.0 km,
  Hellas 70°E → −6.6 km).
- **Climate** — Mars Climate Database v6.1 (LMD), climatology average-solar
  scenario (dust=1), fetched registration-free from the web interface.  Each
  file is one POST to ``https://www-mars.lmd.jussieu.fr/mcd_python/cgi-bin/
  mcdcgi.py`` (Referer: ``/mcd_python/``) with fields::

      var1=t  var2=  datekeyhtml=1  ls=<bin centre>  localtime=12.
      latitude=-90 90  longitude=0 360  zkey=3  altitude=1.  dust=1  hrkey=0
      averaging=loct  zonmean=off  diumean=off  animation=off  proj=cyl
      colorm=jet  dpi=80

  where ``averaging=loct`` = **diurnal mean over all local times** (verified in
  the file headers) and ``ls`` runs over the 12 bin centres 15°, 45°, …, 345°.
  The response HTML links ``../txt/<hash>.txt``; files are cached as
  ``mcd_t_ls{015..345}.txt`` (+ ``mcd_ps_*`` surface pressure for context).
  Precipitation is **declared zero** — no liquid precipitation on present-day
  Mars (trace H₂O frost, ``surf_h2o_ice``, is recorded as context metadata, not
  as precipitation).  GCM climatology = ucc-review §6.2 **L4** epistemic
  status: a model, NOT error-free truth; the provenance dict travels inside the
  exported files.

Time contract: bins are Martian months = 686.98/12 ≈ 57.25 Earth-days each;
``p_total`` is per Martian year; AI/deficit are window-invariant.

Data cache: ``private/tmp/solar/mars/`` (re-download when missing).

Usage:
    uv run python scripts/solar/import_mars.py [--mesh-nodes 10000]
    uv run python scripts/solar/import_mars.py --skip-climate   # terrain only
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "src"))

from dreamulator.import_solar_common import (  # noqa: E402
    LMD_LS_CENTERS,
    apply_climate_to_mesh,
    build_mesh_from_dem,
    load_lmd_slices,
    register_solar_planet,
    sample_regular_grid,
    write_climate_monthly,
    write_climate_secondary,
    write_ucc_yearly,
)

_CACHE = _ROOT / "private/tmp/solar/mars"
_MOLA_IMG = "megt90n000cb.img"
_MOLA_URL = (
    "https://pds-geosciences.wustl.edu/mgs/"
    "urn-nasa-pds-mgs_mola_topography_derived/meg004/" + _MOLA_IMG
)

# MOLA MEGDR 4 ppd grid geometry (landmark-verified 2026-09-21):
# rows north→south starting at +89.875° centre; cols 0°E→360°E, first centre
# +0.125°.  Half-pixel convention is within sampling noise at 0.25°.
_MOLA_LAT_START, _MOLA_DLAT = 89.875, -0.25
_MOLA_LON_START, _MOLA_DLON = 0.125, 0.25

MARS_RADIUS_KM = 3389.5  # IAU mean radius (mesh geometry)
MARS_YEAR_DAYS = 686.98  # Earth days (668.6 sols)
MARS_BIN_DAYS = MARS_YEAR_DAYS / 12.0

# Landmark verification anchors: (name, lat, lon_E, min_expected_m, max_expected_m)
_LANDMARKS = [
    ("Olympus Mons", 18.65, 226.2, 19_000.0, 22_000.0),
    ("Hellas Planitia", -42.7, 70.0, -8_500.0, -5_000.0),
    ("Elysium Mons", 25.0, 147.2, 8_000.0, 13_000.0),
]


def _download(url: str, dest: Path, proxy: str | None = None) -> None:
    """curl download; proxy is explicit (--proxy) or via curl's env handling."""
    import subprocess

    dest.parent.mkdir(parents=True, exist_ok=True)
    attempts = []
    if proxy:
        attempts.append(["curl", "-sSL", "--proxy", proxy, "-o", str(dest), url])
    attempts.append(["curl", "-sSL", "-o", str(dest), url])
    for cmd in attempts:
        r = subprocess.run(cmd, capture_output=True)
        if r.returncode == 0 and dest.exists() and dest.stat().st_size > 0:
            return
        dest.unlink(missing_ok=True)
    raise RuntimeError(f"download failed: {url}")


def load_mola(path: Path) -> np.ndarray:
    """PDS IMG → (720, 1440) float metres; landmark-verified orientation."""
    raw = np.fromfile(path, dtype=">i2")
    if raw.size != 720 * 1440:
        raise ValueError(f"{path.name}: expected 720×1440 >i2, got {raw.size} values")
    dem = raw.reshape(720, 1440).astype(np.float64)
    for name, la, lo, lo_min, lo_max in _LANDMARKS:
        v = float(
            sample_regular_grid(
                dem,
                lat_start=_MOLA_LAT_START,
                dlat=_MOLA_DLAT,
                lon_start=_MOLA_LON_START,
                dlon=_MOLA_DLON,
                lats=np.array([la]),
                lons=np.array([lo]),
            )[0]
        )
        if not (lo_min <= v <= lo_max):
            raise ValueError(f"{name}: sampled {v:.0f} m, expected {lo_min}..{lo_max} m")
        print(f"  Landmark check: {name} = {v:.0f} m ✓")
    return dem


# The LMD ASCII slice parser/loader lives in import_solar_common (shared with
# the Venus importer): parse_lmd_slice / load_lmd_slices / LMD_LS_CENTERS.


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    # Mesh scaled to the CLIMATE data (MCD web grid ~5.7°×3.8°): 10k cells
    # ≈ 2.0° spacing — mild oversampling for rendering without inventing
    # detail the GCM climatology doesn't have.  (MOLA topo is 0.25° but only
    # feeds visualization.)
    parser.add_argument("--mesh-nodes", type=int, default=10_000)
    parser.add_argument("--skip-climate", action="store_true", help="terrain/mesh only")
    parser.add_argument("--data-dir", type=Path, default=_ROOT / "data/worlds")
    parser.add_argument("--proxy", default=None, help="HTTP proxy for curl downloads")
    args = parser.parse_args()

    map_dir = register_solar_planet(args.data_dir, "planet_mars")

    mola_path = _CACHE / _MOLA_IMG
    if not mola_path.exists():
        print("Downloading MOLA 4ppd from PDS …")
        _download(_MOLA_URL, mola_path, proxy=args.proxy)
    print(f"Loading MOLA DEM from {mola_path} …")
    dem = load_mola(mola_path)

    mesh = build_mesh_from_dem(
        dem,
        lat_start=_MOLA_LAT_START,
        dlat=_MOLA_DLAT,
        lon_start=_MOLA_LON_START,
        dlon=_MOLA_DLON,
        radius_km=MARS_RADIUS_KM,
        num_nodes=args.mesh_nodes,
        output_dir=map_dir,
        planet_id="planet_mars",
        source="MOLA MEGDR 4ppd (PDS urn-nasa-pds-mgs_mola_topography_derived, megt90n000cb.img)",
        source_resolution="0.25° (~15 km at equator); datum = areoid (MOLA radius 3396 km)",
    )
    # Mars: no surface hydrosphere — every cell is land (polar caps are
    # surface ice over regolith; the UCC freeze gate handles their AI).
    print(f"  Land cells: {mesh.num_cells}/{mesh.num_cells} (all land)")

    if args.skip_climate:
        print("--skip-climate: terrain done; climate steps skipped.")
        return

    t_kelvin, mcd_meta, header = load_lmd_slices(_CACHE, "mcd_t")
    t_bins = t_kelvin - 273.15  # (12, nlat, nlon) °C

    # Context variables (provenance only, not mesh fields): surface pressure
    # (seasonal CO₂ cycle) and the H₂O frost layer that backs the P≡0 note.
    ps_pa, _, _ = load_lmd_slices(_CACHE, "mcd_ps")
    ps_note = (
        f"MCD `ps` diurnal mean; global mean {ps_pa.mean():.0f} Pa "
        f"(range {ps_pa.min():.0f}–{ps_pa.max():.0f}, seasonal CO₂ cycle)"
    )
    ice_note = "surf_h2o_ice not fetched"
    try:
        ice_kg, _, _ = load_lmd_slices(_CACHE, "mcd_surfh2oice")
        ice_note = (
            f"MCD `surf_h2o_ice`: mean {ice_kg.mean():.4f} kg/m², max {ice_kg.max():.2f} kg/m² "
            "(kg/m² ≡ mm w.e.) — trace frost, declared NOT precipitation"
        )
    except FileNotFoundError:
        pass
    lats = np.array([c.lat for c in mesh.cells], dtype=np.float64)
    lons = np.array([c.lon for c in mesh.cells], dtype=np.float64)
    # MCD grids are 0..360 east; mesh lons are -180..180 — shift into 0..360.
    lons_e = np.mod(lons, 360.0)
    t_monthly = np.empty((mesh.num_cells, 12))
    for m in range(12):
        t_monthly[:, m] = sample_regular_grid(t_bins[m], **mcd_meta, lats=lats, lons=lons_e)
    # Present-day Mars has no liquid precipitation; trace H₂O/CO₂ frost deposition
    # is NOT represented as precipitation.  P ≡ 0 is the declared, honest value —
    # it exercises the contract paths ucc §8 predicts (AI=0 valid → arid where any
    # bin thaws; concentration undefined; OOD where t_max < 0).
    p_monthly = np.zeros((mesh.num_cells, 12))

    ls_line = next((h for h in header if h.startswith("Ls ")), "Ls ?")
    version_line = next((h for h in header if "MCD" in h), "MCD (version unknown)")

    write_climate_monthly(
        map_dir,
        t_monthly,
        p_monthly,
        bin_days=MARS_BIN_DAYS,
        month_0="ls_15_first_bin_center",
        extra_metadata={
            "time_basis": (
                f"12 Ls-bin centres ({LMD_LS_CENTERS[0]}°…{LMD_LS_CENTERS[-1]}°, 30° bins), "
                f"{MARS_YEAR_DAYS} d Martian year; each bin diurnal-averaged"
            ),
            "gcm_slice_header": ls_line,
            "surface_pressure_pa_mean": float(ps_pa.mean()),
        },
    )
    apply_climate_to_mesh(map_dir, t_monthly.mean(axis=1), p_monthly.sum(axis=1))
    write_climate_secondary(map_dir, source=f"{version_line}; diurnal-mean Ls-bin climatology")

    combos = write_ucc_yearly(
        map_dir,
        data_source="gcm-climatology",
        provenance={
            "gcm": f"{version_line} — web-interface 2D ASCII slices "
            f"(diurnal-averaged, dust=1 climatology scenario), {ls_line}",
            "temperature": "near-surface air temperature (MCD `t`), diurnal mean at "
            "12 Ls-bin centres; K→°C",
            "precipitation": "declared zero — no liquid precipitation on present-day "
            "Mars; trace frost deposition not represented (ucc §8 exercise path)",
            "surface_pressure": ps_note,
            "frost_context": ice_note,
            "topography": "MOLA MEGDR 4ppd (PDS)",
            "epistemic_status": "L4 GCM climatology (ucc-review §6.2): a model, "
            "not error-free truth",
            "time_basis": f"bin = {MARS_BIN_DAYS:.2f} Earth-days (Martian month); "
            f"p_total per Martian year ({MARS_YEAR_DAYS} d)",
        },
        demand_model="hamon-1961",
    )
    print("Land classes:", sorted(combos.items(), key=lambda kv: -kv[1]))


if __name__ == "__main__":
    main()
