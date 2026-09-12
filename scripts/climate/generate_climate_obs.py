#!/usr/bin/env python3
"""Generate the per-cell observed climatology (``climate_obs.json``) for a mesh.

Samples real-Earth observation datasets onto each CVT mesh cell and writes
``climate_obs.json`` — the per-cell observed reference that
``diagnose_climate_bias.py`` (and the frontend ΔT/ΔP error layers) compare the
engine output against.  This is the **committed generator**: the previous
``climate_obs.json`` was an ad-hoc artifact with no generator (it silently
rots on any mesh rebuild and carried only T/P).

Fields (all ANNUAL, keyed by cell id):
  t_obs_c       NCEP/NCAR Reanalysis 1 surface air temp, annual mean (°C)
  p_obs_mm      GPCP v2.3 precipitation, annual total (mm/yr)
  slp_obs_hpa   NCEP sea-level pressure, annual mean (hPa)
  uwnd_obs_m_s  NCEP near-surface eastward wind, annual mean (m/s)
  vwnd_obs_m_s  NCEP near-surface northward wind, annual mean (m/s)

Köppen obs live separately in ``koppen_obs.json`` (``convert_koppen_map.py``,
mesh-bound, single source) — the bias tool reads both.

Design notes:
  * Every field here is ANNUAL (mean/sum), hence month-order invariant: this
    generator sidesteps the model(0=Mar)-vs-obs(0=Jan) month-index trap that
    bit the Stage-C pre-flight.  Month-resolved ΔSLP lives in
    ``diagnose_monsoon_dp_shape.py`` (reads the netCDF directly).
  * Sampling reuses ``import_earth_climate``'s bilinear machinery (the same
    datasets, the same ``_sample_monthly``), so the obs values are identical
    to the pure-observation earth-main import — a built-in cross-check.

Usage:
    uv run python scripts/climate/generate_climate_obs.py
    uv run python scripts/climate/generate_climate_obs.py --mesh <mesh> --output <obs.json>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from dreamulator.import_earth_climate import (  # noqa: E402
    _load_gpcp_climatology,
    _load_nc_monthly,
    _sample_monthly,
)
from dreamulator.map.export import decompress_mesh_bytes  # noqa: E402

_DEFAULT_MESH = "data/worlds/earth/branches/climate-dev/maps/planet_earth/cvt_mesh.json"


def _find_project_root() -> Path:
    d = Path.cwd()
    while d != d.parent:
        if (d / "pyproject.toml").exists():
            return d
        d = d.parent
    return Path.cwd()


def _resolve(p: str, root: Path) -> Path:
    path = Path(p)
    return path if path.is_absolute() else root / path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mesh", default=_DEFAULT_MESH, help="path to cvt_mesh.json")
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="output climate_obs.json (default: alongside the mesh)",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="obs netCDF dir (default: private/tmp/climatology)",
    )
    args = parser.parse_args()

    root = _find_project_root()
    mesh_path = _resolve(args.mesh, root)
    if not mesh_path.exists():
        print(f"ERROR: mesh not found: {mesh_path}", file=sys.stderr)
        sys.exit(1)
    output_path = (
        _resolve(args.output, root) if args.output else mesh_path.parent / "climate_obs.json"
    )
    data_dir = (
        _resolve(args.data_dir, root) if args.data_dir else root / "private" / "tmp" / "climatology"
    )

    print(f"Loading mesh: {mesh_path}")
    mesh = json.loads(decompress_mesh_bytes(mesh_path.read_bytes()))
    cells_raw = mesh["cells"]
    lats = np.array([c["lat"] for c in cells_raw], dtype=np.float64)
    lons = np.array([c["lon"] for c in cells_raw], dtype=np.float64)
    ids = [c["id"] for c in cells_raw]
    n = mesh["num_cells"]
    seed = mesh.get("seed")
    print(f"  {n} cells")

    def _annual(arr: np.ndarray, lat: np.ndarray, lon: np.ndarray, agg) -> np.ndarray:
        """(12,lat,lon) grid → per-cell annual aggregate (N,)."""
        monthly = _sample_monthly(arr, lat, lon, lats, lons).T  # (N, 12)
        return np.asarray(agg(monthly, axis=1))

    print(f"Sampling obs from: {data_dir}")
    t_arr, t_lat, t_lon = _load_nc_monthly(data_dir / "ncep_air.mon.ltm.nc", "air")
    t_annual = _annual(t_arr, t_lat, t_lon, np.mean)
    p_arr, p_lat, p_lon = _load_gpcp_climatology(data_dir / "gpcp_precip.mon.mean.nc")
    p_annual = _annual(p_arr, p_lat, p_lon, np.sum)
    slp_arr, slp_lat, slp_lon = _load_nc_monthly(data_dir / "ncep_slp.mon.ltm.nc", "slp")
    slp_annual = _annual(slp_arr, slp_lat, slp_lon, np.mean)
    uw_arr, uw_lat, uw_lon = _load_nc_monthly(data_dir / "ncep_uwnd.mon.ltm.nc", "uwnd")
    uwnd_annual = _annual(uw_arr, uw_lat, uw_lon, np.mean)
    vw_arr, vw_lat, vw_lon = _load_nc_monthly(data_dir / "ncep_vwnd.mon.ltm.nc", "vwnd")
    vwnd_annual = _annual(vw_arr, vw_lat, vw_lon, np.mean)

    # Per-cell records; skip cells with any non-finite obs (polar cells beyond
    # the GPCP/NCEP grid edges bilinear-clamp to fill or NaN).
    cells: dict[str, dict[str, float]] = {}
    for i in range(n):
        vals = (t_annual[i], p_annual[i], slp_annual[i], uwnd_annual[i], vwnd_annual[i])
        if not all(np.isfinite(v) for v in vals):
            continue
        cells[str(ids[i])] = {
            "t_obs_c": round(float(vals[0]), 2),
            "p_obs_mm": round(float(vals[1]), 1),
            "slp_obs_hpa": round(float(vals[2]), 1),
            "uwnd_obs_m_s": round(float(vals[3]), 3),
            "vwnd_obs_m_s": round(float(vals[4]), 3),
        }

    try:
        rel_mesh = str(mesh_path.relative_to(root))
    except ValueError:
        rel_mesh = str(mesh_path)
    out = {
        "source": "NCEP/NCAR Reanalysis 1 (air/slp/uwnd/vwnd, 2.5°) + GPCP v2.3 (precip, 2.5°)",
        "fields": {
            "t_obs_c": "NCEP surface air temperature, annual mean (°C)",
            "p_obs_mm": "GPCP precipitation, annual total (mm/yr)",
            "slp_obs_hpa": "NCEP sea-level pressure, annual mean (hPa)",
            "uwnd_obs_m_s": "NCEP eastward wind, annual mean (m/s)",
            "vwnd_obs_m_s": "NCEP northward wind, annual mean (m/s)",
        },
        "note": (
            "Köppen obs in koppen_obs.json (convert_koppen_map.py). Annual fields "
            "only (month-order invariant). Mesh-bound: regenerate after any rebuild."
        ),
        "num_cells": n,
        "num_sampled": len(cells),
        "seed": seed,
        "mesh_path": rel_mesh,
        "cells": cells,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"))
    print(
        f"  Saved: {output_path} "
        f"({output_path.stat().st_size / 1024 / 1024:.1f} MB, {len(cells)}/{n} cells)"
    )


if __name__ == "__main__":
    main()
