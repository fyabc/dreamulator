#!/usr/bin/env python3
"""Zonal T/P profile diagnostic — vs ERA5 / GPCP, with land/ocean split.

Runs the climate engine on the Earth (baseline) mesh and compares the simulated
zonal-mean temperature (vs ERA5) and precipitation (vs GPCP).  The reference is
a *full* zonal mean (land + ocean), so the clean comparison is against the
combined model mean; land-only and ocean-only model means are printed as
additional diagnostic columns (they show where the land-ocean contrast drives
the gradient, but have no separate reference).

Interpretation (the core of the "engine bug vs parameter tuning" separation):
  - a **shape** error in the zonal gradient (wrong position of the ITCZ peak,
    wrong subtropical dry zone, wrong pole-equator temperature slope) is an
    *engine* (physics) problem, since it appears on the Earth baseline too;
  - an **amplitude-only** error (same shape, wrong magnitude) is a *parameter*
    (calibration) problem.

Usage::

    uv run python scripts/diagnose_latitudinal_profile.py
    uv run python scripts/diagnose_latitudinal_profile.py --band 5
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np


def _find_project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _load_mesh(world_dir: Path, planet_id: str, branch: str | None = None) -> object | None:
    from pydantic import TypeAdapter

    from dreamulator.map.models import CVTMesh

    search_dirs = [world_dir]
    if branch:
        search_dirs.insert(0, world_dir / "branches" / branch)
    for base in search_dirs:
        p = base / "maps" / planet_id / "cvt_mesh.json"
        if p.exists():
            from dreamulator.map.export import decompress_mesh_bytes

            return TypeAdapter(CVTMesh).validate_json(decompress_mesh_bytes(p.read_bytes()))
    return None


def _zonal_means(
    mesh, field: str, band_deg: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Zonal-mean of `field` in latitude bands: (combined, land, ocean, centers)."""
    n_bands = int(round(180.0 / band_deg))
    comb_sum = np.zeros(n_bands)
    comb_cnt = np.zeros(n_bands, dtype=int)
    land_sum = np.zeros(n_bands)
    land_cnt = np.zeros(n_bands, dtype=int)
    ocean_sum = np.zeros(n_bands)
    ocean_cnt = np.zeros(n_bands, dtype=int)
    centers = np.array([90.0 - band_deg * (b + 0.5) for b in range(n_bands)])

    for c in mesh.cells:
        v = getattr(c, field, None)
        if v is None:
            continue
        b = int(np.clip((90.0 - c.lat) / band_deg, 0, n_bands - 1))
        comb_sum[b] += v
        comb_cnt[b] += 1
        if c.elevation >= 0.0:
            land_sum[b] += v
            land_cnt[b] += 1
        else:
            ocean_sum[b] += v
            ocean_cnt[b] += 1

    def _mean(s, c):
        return np.where(c > 0, s / np.maximum(c, 1), np.nan)

    return (
        _mean(comb_sum, comb_cnt),
        _mean(land_sum, land_cnt),
        _mean(ocean_sum, ocean_cnt),
        centers,
    )


def _ref_at_centers(ref_2deg: np.ndarray, centers: np.ndarray) -> np.ndarray:
    """Look up the 2°-band reference (index i → latitude 90−2i, 90N→90S) at `centers`."""
    idx = np.clip(np.round((90.0 - centers) / 2.0).astype(int), 0, len(ref_2deg) - 1)
    return ref_2deg[idx]


def _report(
    name: str,
    sim: np.ndarray,
    land: np.ndarray,
    ocean: np.ndarray,
    ref: np.ndarray,
    centers: np.ndarray,
    unit: str,
) -> dict:
    valid = ~np.isnan(sim)
    diff = sim[valid] - ref[valid]
    rmse = float(np.sqrt(np.mean(diff**2)))
    bias = float(np.mean(diff))
    r = float(np.corrcoef(sim[valid], ref[valid])[0, 1])

    print(f"\n--- {name} ({unit}) ---")
    print(f"  combined: RMSE={rmse:.1f}  bias={bias:+.1f}  corr={r:.3f}")
    print(f"  {'lat':>6} {'comb':>8} {'ref':>8} {'bias':>8} {'land':>8} {'ocean':>8}")
    for i in range(len(centers)):
        if not np.isnan(sim[i]):
            lv = f"{land[i]:>8.1f}" if not np.isnan(land[i]) else f"{'—':>8}"
            ov = f"{ocean[i]:>8.1f}" if not np.isnan(ocean[i]) else f"{'—':>8}"
            print(
                f"  {centers[i]:>5.0f}° {sim[i]:>8.1f} {ref[i]:>8.1f} "
                f"{sim[i] - ref[i]:>+8.1f} {lv} {ov}"
            )

    verdict = (
        "shape OK (amplitude/calibration issue)"
        if abs(r) > 0.9
        else "shape WRONG (physics/engine issue)"
    )
    print(f"  → {verdict}")
    return {"rmse": round(rmse, 1), "bias": round(bias, 1), "corr": round(r, 3), "verdict": verdict}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--world", default="earth")
    parser.add_argument("--planet", default="planet_earth")
    parser.add_argument("--branch", default="climate-dev")
    parser.add_argument("--band", type=float, default=5.0)
    parser.add_argument(
        "--no-auto-lat-gradient",
        action="store_false",
        dest="auto_lat_gradient",
        default=True,
        help="disable auto_lat_gradient (fall back to manual --lat-gradient-c)",
    )
    parser.add_argument(
        "--no-diffusive-heat-transport",
        action="store_false",
        dest="diffusive_heat_transport",
        default=True,
        help="disable graph-Laplacian diffusive heat transport",
    )
    parser.add_argument(
        "--lat-gradient-c",
        type=float,
        default=45.0,
        help="manual equator-pole ΔT when auto_lat_gradient is off",
    )
    args = parser.parse_args()

    from dreamulator.validate_climate import _ZONAL_PRECIP_REF, _ZONAL_TEMP_REF

    root = _find_project_root()
    world_dir = root / "data" / "worlds" / args.world

    print(f"Loading Earth mesh ({args.world}, branch={args.branch}) ...")
    mesh = _load_mesh(world_dir, args.planet, args.branch)
    if mesh is None:
        print("  ERROR: no mesh found")
        return

    print(f"Running climate engine on {mesh.num_cells} cells ...")
    from dreamulator.map.climate_simulator import simulate_climate
    from dreamulator.validate_climate import build_earth_validation_config

    simulate_climate(
        mesh,
        build_earth_validation_config(
            mesh.num_cells,
            lat_gradient_c=args.lat_gradient_c,
            auto_lat_gradient=args.auto_lat_gradient,
            diffusive_heat_transport=args.diffusive_heat_transport,
        ),
    )

    # Temperature
    t_comb, t_land, t_ocean, centers = _zonal_means(mesh, "temperature_C", args.band)
    t_ref = _ref_at_centers(_ZONAL_TEMP_REF, centers)
    _report("Temperature", t_comb, t_land, t_ocean, t_ref, centers, "°C")

    # Precipitation
    p_comb, p_land, p_ocean, _ = _zonal_means(mesh, "precipitation_mm", args.band)
    p_ref = _ref_at_centers(_ZONAL_PRECIP_REF, centers)
    _report("Precipitation", p_comb, p_land, p_ocean, p_ref, centers, "mm/yr")


if __name__ == "__main__":
    main()
