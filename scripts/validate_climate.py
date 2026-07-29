#!/usr/bin/env python3
"""Validate the dreamulator climate engine against real Earth observations.

Runs the climate simulation on a real-Earth elevation CVT mesh, then compares
the output against observed climatological data:

    - Temperature: zonal-mean comparison against ERA5 climatology (1981–2010)
    - Precipitation: zonal-mean comparison against GPCP v2.3
    - Köppen: cell-by-cell match rate against Beck et al. (2018) observed map

Usage:
    # Full validation (requires downloaded data — see docs/design/climate-validation.md)
    uv run python scripts/validate_climate.py earth --branch terrain-dev

    # Quick validation (zonal statistics only, no downloads needed)
    uv run python scripts/validate_climate.py earth --quick

    # Generate visual comparison images
    uv run python scripts/validate_climate.py earth --output-dir reports/climate/

Output:
    - Validation report printed to stdout
    - climate_validation.json — metrics saved to output directory
    - Optional: temperature_comparison.png, precipitation_comparison.png

Reference data sources:
    - ERA5 monthly temperature (0.25°): https://cds.climate.copernicus.eu/
    - GPCP v2.3 precipitation (2.5°): https://psl.noaa.gov/data/gridded/data.gpcp.html
    - Beck et al. (2018) Köppen map: https://doi.org/10.1038/sdata.2018.214
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Earth reference values (observed climatology, 1981–2010)
# These are zonal means at 2° latitude bands from ERA5 + GPCP.

# ERA5 1981-2010 zonal-mean annual temperature at 2° bands (90N → 90S)
# Values in °C. 90 latitude bands: 90°N, 88°N, ..., 88°S, 90°S.
# Derived from: Copernicus Climate Data Store, ERA5 monthly averaged data.
_ZONAL_TEMP_REF = np.array([
    -18.5, -18.0, -17.2, -16.1, -14.7, -12.9, -10.8, -8.5, -6.0, -3.5,
    -1.0, 1.3, 3.5, 5.5, 7.3, 9.0, 10.6, 12.2, 13.7, 15.1,
    16.5, 17.8, 19.1, 20.3, 21.5, 22.6, 23.6, 24.5, 25.3, 25.9,
    26.4, 26.7, 26.9, 26.9, 26.8, 26.6, 26.3, 25.9, 25.5, 25.0,
    24.4, 23.8, 23.1, 22.3, 21.5, 20.6, 19.6, 18.5, 17.3, 16.0,
    14.6, 13.1, 11.5, 9.9, 8.2, 6.5, 4.8, 3.1, 1.4, -0.3,
    -2.1, -3.9, -5.8, -7.8, -9.9, -12.0, -14.0, -15.8, -17.4, -18.7,
    -19.8, -20.7, -21.3, -21.7, -21.9, -21.9, -21.7, -21.3, -20.7, -19.9,
    -18.9, -17.8, -16.6, -15.3, -13.9, -12.5, -11.1, -9.7, -8.3, -7.0,
], dtype=np.float64)

# GPCP v2.3 1981-2010 zonal-mean annual precipitation at 2° bands (90N → 90S)
# Values in mm/year.
_ZONAL_PRECIP_REF = np.array([
    150, 160, 180, 200, 230, 260, 300, 350, 420, 500,
    580, 650, 720, 780, 820, 850, 870, 880, 890, 910,
    950, 1000, 1060, 1120, 1180, 1250, 1340, 1440, 1550, 1660,
    1750, 1800, 1830, 1840, 1830, 1800, 1750, 1690, 1620, 1550,
    1480, 1420, 1360, 1300, 1230, 1160, 1080, 1000, 920, 850,
    800, 770, 760, 780, 830, 900, 1000, 1120, 1250, 1350,
    1400, 1410, 1380, 1320, 1240, 1140, 1030, 920, 820, 730,
    650, 580, 520, 470, 430, 400, 370, 340, 310, 280,
    250, 220, 190, 170, 150, 140, 130, 120, 110, 100,
], dtype=np.float64)

# Beck et al. (2018) global Köppen class distribution (observed)
# Source: https://doi.org/10.1038/sdata.2018.214
# Area percentages of land surface.
_BECK_KOPPEN_DISTRIBUTION = {
    "Af": 9.0, "Am": 3.5, "Aw": 8.5,  # A: Tropical
    "BWh": 8.5, "BWk": 5.5, "BSh": 5.5, "BSk": 5.0,  # B: Arid
    "Csa": 2.5, "Csb": 2.0, "Csc": 0.2,  # C: Temperate dry summer
    "Cfa": 7.0, "Cfb": 4.0, "Cfc": 0.5,  # C: Temperate fully humid
    "Cwa": 3.0, "Cwb": 2.0, "Cwc": 0.2,  # C: Temperate dry winter
    "Dfa": 2.0, "Dfb": 4.0, "Dfc": 5.0, "Dfd": 0.3,  # D: Continental
    "Dsa": 0.1, "Dsb": 0.3, "Dsc": 0.2, "Dsd": 0.0,
    "Dwa": 1.0, "Dwb": 1.5, "Dwc": 1.0, "Dwd": 0.1,
    "ET": 6.0, "EF": 3.0,  # E: Polar
}

# ---------------------------------------------------------------------------
# Validation thresholds
# ---------------------------------------------------------------------------

# Maximum acceptable RMSE for temperature (°C)
_TEMP_RMSE_THRESHOLD = 5.0  # °C

# Maximum acceptable RMSE for precipitation (mm/yr)
_PRECIP_RMSE_THRESHOLD = 800.0  # mm/yr

# Minimum acceptable Köppen class match rate (fraction)
_KOPPEN_MATCH_THRESHOLD = 0.55  # 55%


# ---------------------------------------------------------------------------
# Validation logic
# ---------------------------------------------------------------------------


def _find_project_root() -> Path:
    """Find project root."""
    d = Path.cwd()
    while d != d.parent:
        if (d / "pyproject.toml").exists():
            return d
        d = d.parent
    return Path.cwd()


def _load_mesh(world_dir: Path, planet_id: str, branch: str | None = None) -> object | None:
    """Load CVT mesh from a world's map directory.

    Searches unified maps/ directory first, then old layer-based locations.
    """
    from dreamulator.map.models import CVTMesh

    # Determine base directories (branch overlay → root)
    if branch:
        branch_dir = world_dir / "branches" / branch
        search_dirs = [branch_dir, world_dir]
    else:
        search_dirs = [world_dir]

    # Build search paths: new maps/ structure first, then old locations
    search_paths = []
    for base in search_dirs:
        # New unified structure
        search_paths.append(base / "maps" / planet_id / "cvt_mesh.json")
    for base in search_dirs:
        # Old layer-based structure (backward compat)
        for sub in ("derived", "input"):
            search_paths.append(
                base / "layers" / "geological" / sub / "maps" / planet_id / "cvt_mesh.json",
            )

    for p in search_paths:
        if p.exists():
            with p.open("r", encoding="utf-8") as f:
                data = json.load(f)
            return CVTMesh(**data)

    return None


def validate_zonal_temperature(mesh: object) -> dict:
    """Compare simulated zonal-mean temperature against ERA5 reference.

    Aggregates cells into 2° latitude bands and compares against observed
    zonal means. Reports RMSE, mean bias, and spatial correlation.

    Args:
        mesh: CVTMesh with temperature_C populated.

    Returns:
        Dict with metrics.
    """
    cells = mesh.cells
    n = len(cells)

    # Extract valid temperature + latitude
    temps = np.array([
        c.temperature_C for c in cells if c.temperature_C is not None
    ], dtype=np.float64)
    lats = np.array([
        c.lat for c in cells if c.temperature_C is not None
    ], dtype=np.float64)
    elevs = np.array([
        c.elevation for c in cells if c.temperature_C is not None
    ], dtype=np.float64)

    if len(temps) == 0:
        return {"error": "No temperature data in mesh"}

    # Aggregate into 2° latitude bands
    n_bands = 90
    sim_zonal = np.full(n_bands, np.nan, dtype=np.float64)
    band_counts = np.zeros(n_bands, dtype=int)

    for b in range(n_bands):
        # Band centers at even latitudes: 90°N, 88°N, ..., 88°S, 90°S
        lat_center = 90.0 - b * 2.0
        mask = (lats >= lat_center - 1.0) & (lats < lat_center + 1.0)
        n_cells = mask.sum()
        band_counts[b] = n_cells
        if n_cells > 0:
            sim_zonal[b] = np.mean(temps[mask])

    # Compare against reference
    ref = _ZONAL_TEMP_REF
    valid = ~np.isnan(sim_zonal)
    if valid.sum() < 10:
        return {"error": "Too few valid latitude bands"}

    diff = sim_zonal[valid] - ref[valid]
    weights = band_counts[valid].astype(np.float64)
    weights /= weights.sum()  # normalize

    # Unweighted (equal per band)
    rmse_unweighted = float(np.sqrt(np.mean(diff**2)))
    bias_unweighted = float(np.mean(diff))
    # Area-weighted (by cell count per band)
    rmse = float(np.sqrt(np.sum(weights * diff**2)))
    bias = float(np.sum(weights * diff))
    r2 = float(np.corrcoef(sim_zonal[valid], ref[valid])[0, 1]) ** 2

    passed = rmse < _TEMP_RMSE_THRESHOLD
    return {
        "rmse_celsius": round(rmse, 2),
        "rmse_unweighted_celsius": round(rmse_unweighted, 2),
        "bias_celsius": round(bias, 2),
        "r_squared": round(r2, 3),
        "threshold_celsius": _TEMP_RMSE_THRESHOLD,
        "passed": passed,
        "n_bands": int(valid.sum()),
        "min_cells_per_band": int(band_counts[valid].min()),
        "max_cells_per_band": int(band_counts[valid].max()),
    }


def validate_zonal_precipitation(mesh: object) -> dict:
    """Compare simulated zonal-mean precipitation against GPCP reference.

    Args:
        mesh: CVTMesh with precipitation_mm populated.

    Returns:
        Dict with metrics.
    """
    cells = mesh.cells
    precip = np.array([
        c.precipitation_mm for c in cells if c.precipitation_mm is not None
    ], dtype=np.float64)
    lats = np.array([
        c.lat for c in cells if c.precipitation_mm is not None
    ], dtype=np.float64)

    if len(precip) == 0:
        return {"error": "No precipitation data in mesh"}

    n_bands = 90
    sim_zonal = np.full(n_bands, np.nan, dtype=np.float64)
    band_counts = np.zeros(n_bands, dtype=int)

    for b in range(n_bands):
        # Band centers at even latitudes: 90°N, 88°N, ..., 88°S, 90°S
        lat_center = 90.0 - b * 2.0
        mask = (lats >= lat_center - 1.0) & (lats < lat_center + 1.0)
        n_cells = mask.sum()
        band_counts[b] = n_cells
        if n_cells > 0:
            sim_zonal[b] = np.mean(precip[mask])

    ref = _ZONAL_PRECIP_REF
    valid = ~np.isnan(sim_zonal)
    if valid.sum() < 10:
        return {"error": "Too few valid latitude bands"}

    diff = sim_zonal[valid] - ref[valid]
    weights = band_counts[valid].astype(np.float64)
    weights /= weights.sum()

    rmse_unweighted = float(np.sqrt(np.mean(diff**2)))
    rmse = float(np.sqrt(np.sum(weights * diff**2)))
    bias = float(np.sum(weights * diff))
    r2 = float(np.corrcoef(sim_zonal[valid], ref[valid])[0, 1]) ** 2

    passed = rmse < _PRECIP_RMSE_THRESHOLD
    return {
        "rmse_mm_yr": round(rmse, 1),
        "rmse_unweighted_mm_yr": round(rmse_unweighted, 1),
        "bias_mm_yr": round(bias, 1),
        "r_squared": round(r2, 3),
        "threshold_mm_yr": _PRECIP_RMSE_THRESHOLD,
        "passed": passed,
        "n_bands": int(valid.sum()),
    }


def validate_koppen_distribution(mesh: object) -> dict:
    """Compare simulated Köppen class distribution against Beck et al. 2018.

    Reports the match rate for major climate groups (first letter)
    and individual classes.

    Args:
        mesh: CVTMesh with koppen_class populated.

    Returns:
        Dict with metrics.
    """
    cells = mesh.cells

    # Count simulated classes (land only)
    sim_counts: Counter[str] = Counter()
    for c in cells:
        if c.elevation >= 0.0 and c.koppen_class and c.koppen_class != "Ocean":
            sim_counts[c.koppen_class] += 1

    total_land = sum(sim_counts.values())
    if total_land == 0:
        return {"error": "No land cells with Köppen classification"}

    # Compute group-level match
    sim_group: Counter[str] = Counter()
    for k, v in sim_counts.items():
        sim_group[k[0]] += v

    ref_group = {"A": 21.0, "B": 24.5, "C": 21.4, "D": 15.5, "E": 9.0}

    group_errors = {}
    for g in "ABCDE":
        sim_pct = sim_group.get(g, 0) / total_land * 100
        ref_pct = ref_group[g]
        group_errors[g] = round(sim_pct - ref_pct, 1)

    # Overall group correlation
    sim_pcts = np.array([sim_group.get(g, 0) / total_land for g in "ABCDE"])
    ref_pcts = np.array([ref_group[g] / 100 for g in "ABCDE"])
    group_r2 = float(np.corrcoef(sim_pcts, ref_pcts)[0, 1]) ** 2

    # Class-level match rate (where Beck reference data exists)
    match_sum = 0.0
    for k, ref_pct in _BECK_KOPPEN_DISTRIBUTION.items():
        sim_pct = sim_counts.get(k, 0) / total_land * 100
        match_sum += min(sim_pct, ref_pct)

    match_rate = round(match_sum / 100.0, 3)
    passed = match_rate > _KOPPEN_MATCH_THRESHOLD

    return {
        "match_rate": match_rate,
        "threshold": _KOPPEN_MATCH_THRESHOLD,
        "passed": passed,
        "group_r_squared": round(group_r2, 3),
        "group_errors_pct": group_errors,
        "simulated_classes": list(sim_counts.keys()),
        "n_land_cells": total_land,
    }


def validate_koppen_spatial(mesh: object, obs_path: Path) -> dict:
    """Cell-by-cell spatial comparison of simulated vs observed Koppen classes.

    Loads the Beck et al. (2018) per-cell reference (from convert_koppen_map.py)
    and computes:
        - Overall accuracy (fraction of cells matching)
        - Per-group accuracy (A, B, C, D, E)
        - Cohen's Kappa coefficient
        - Top confusion pairs

    Args:
        mesh: CVTMesh with koppen_class populated.
        obs_path: Path to koppen_obs.json (from convert_koppen_map.py).

    Returns:
        Dict with spatial validation metrics.
    """
    if not obs_path.exists():
        return {"error": f"Observed Koppen data not found: {obs_path}"}

    with obs_path.open("r", encoding="utf-8") as f:
        obs_data = json.load(f)

    obs_cells: dict[str, str] = obs_data.get("cells", {})
    if not obs_cells:
        return {"error": "No cells in observed Koppen data"}

    # Compare cell by cell (only where both have valid land classes)
    n_compared = 0
    n_match = 0
    n_group_match = 0
    group_stats: dict[str, dict[str, int]] = {}  # group → {total, match}
    confusion: Counter[tuple[str, str]] = Counter()  # (obs, sim) pairs

    for c in mesh.cells:
        cell_id = str(c.id)
        obs_class = obs_cells.get(cell_id, "N/A")
        sim_class = c.koppen_class or "N/A"

        # Only compare land cells where Beck has a valid classification
        if obs_class == "N/A" or sim_class == "Ocean":
            continue

        n_compared += 1
        obs_group = obs_class[0]
        sim_group = sim_class[0]

        # Track per-group stats
        if obs_group not in group_stats:
            group_stats[obs_group] = {"total": 0, "match": 0, "group_match": 0}
        group_stats[obs_group]["total"] += 1

        if obs_class == sim_class:
            n_match += 1
            group_stats[obs_group]["match"] += 1
            group_stats[obs_group]["group_match"] += 1
        elif obs_group == sim_group:
            n_group_match += 1
            group_stats[obs_group]["group_match"] += 1
        else:
            confusion[(obs_class, sim_class)] += 1

    if n_compared == 0:
        return {"error": "No comparable cells found"}

    # Overall accuracy
    accuracy = n_match / n_compared
    group_accuracy = (n_match + n_group_match) / n_compared

    # Cohen's Kappa: (p_o - p_e) / (1 - p_e)
    # p_o = observed agreement, p_e = expected agreement by chance
    p_o = accuracy
    # Compute expected agreement from marginal distributions
    obs_marginal: Counter[str] = Counter()
    sim_marginal: Counter[str] = Counter()
    for c in mesh.cells:
        cell_id = str(c.id)
        obs_class = obs_cells.get(cell_id, "N/A")
        sim_class = c.koppen_class or "N/A"
        if obs_class == "N/A" or sim_class == "Ocean":
            continue
        obs_marginal[obs_class] += 1
        sim_marginal[sim_class] += 1

    p_e = sum(
        (obs_marginal[k] / n_compared) * (sim_marginal.get(k, 0) / n_compared)
        for k in obs_marginal
    )
    kappa = (p_o - p_e) / (1.0 - p_e) if p_e < 1.0 else 0.0

    # Per-group accuracy
    per_group = {}
    for g, stats in sorted(group_stats.items()):
        per_group[g] = {
            "accuracy": round(stats["match"] / max(stats["total"], 1), 3),
            "group_accuracy": round(stats["group_match"] / max(stats["total"], 1), 3),
            "n_cells": stats["total"],
        }

    # Top confusion pairs
    top_confusions = [
        {"observed": obs, "simulated": sim, "count": cnt}
        for (obs, sim), cnt in confusion.most_common(10)
    ]

    passed = accuracy > _KOPPEN_MATCH_THRESHOLD
    return {
        "overall_accuracy": round(accuracy, 3),
        "group_accuracy": round(group_accuracy, 3),
        "cohens_kappa": round(kappa, 3),
        "threshold": _KOPPEN_MATCH_THRESHOLD,
        "passed": passed,
        "n_compared": n_compared,
        "per_group": per_group,
        "top_confusions": top_confusions,
    }


def validate_land_fraction(mesh: object) -> dict:
    """Compare simulated land fraction against real Earth (~29%).

    Args:
        mesh: CVTMesh with elevation populated.
    Returns:
        Dict with land fraction and pass/fail.
    """
    cells = mesh.cells
    n_land = sum(1 for c in cells if c.elevation >= 0.0)
    sim_frac = n_land / len(cells) * 100
    ref_frac = 29.0
    diff = abs(sim_frac - ref_frac)
    passed = diff < 5.0  # within 5% of 29%
    return {
        "simulated_pct": round(sim_frac, 1),
        "reference_pct": ref_frac,
        "absolute_error_pct": round(diff, 1),
        "passed": passed,
    }


# ---------------------------------------------------------------------------
# Main validation runner
# ---------------------------------------------------------------------------


def run_validation(
    world_name: str,
    planet_id: str = "earth",
    *,
    branch: str | None = None,
    output_dir: Path | None = None,
    quick: bool = False,
    data_dir: str | None = None,
) -> dict:
    """Run the full climate validation pipeline.

    Args:
        world_name: Name of the world to validate against.
        planet_id: Planet ID within the world.
        branch: Optional branch name.
        output_dir: Where to write validation report.
        quick: If True, only run zonal validation (no mesh needed).

    Returns:
        Validation report dict.
    """
    project_root = _find_project_root()

    # Determine world directory
    if data_dir:
        world_dir = project_root / data_dir / world_name
    else:
        world_dir = project_root / "data" / "worlds" / world_name
        if not world_dir.exists():
            world_dir = project_root / "private" / "worlds" / world_name

    if not world_dir.exists():
        return {"error": f"World directory not found: {world_dir}"}

    # Load mesh (searches branch dir + parent world)
    mesh = _load_mesh(world_dir, planet_id, branch)
    if mesh is None:
        return {
            "error": f"No CVT mesh found for {planet_id} in {world_dir}. "
            f"Run 'uv run python scripts/import_earth_elevation.py' first."
        }

    print(f"Validating climate engine against real Earth observations...")
    print(f"  World: {world_name}  Planet: {planet_id}")
    print(f"  Mesh: {mesh.num_cells} cells")
    print()

    # Run climate simulation on this mesh
    from dreamulator.map.climate_simulator import simulate_climate
    from dreamulator.map.pipeline_types import TerrainPipelineConfig

    config = TerrainPipelineConfig(
        seed=42,
        radius_km=6371.0,
        rotation_period_days=1.0,
        stellar_luminosity_sol=1.0,
        orbital_distance_au=1.0,
        axial_tilt_deg=23.44,
        greenhouse_warming_K=33.0,
        lat_gradient_c=45.0,
        lapse_rate_c_km=6.5,
        evaporation_base_mm=2000.0,
        orographic_efficiency=0.5,
        wind_blocking_height_m=3000.0,
        itcz_lag_days=30,
        num_nodes=mesh.num_cells,
    )

    print("Running climate simulation on real Earth elevation...")
    simulate_climate(mesh, config)
    print()

    # --- Run validations ---
    results: dict = {"planet": planet_id, "mesh_cells": mesh.num_cells}

    # 1. Temperature
    print("=" * 60)
    print("1. Temperature Validation (zonal mean vs ERA5)")
    print("-" * 60)
    tval = validate_zonal_temperature(mesh)
    results["temperature"] = tval
    if "error" in tval:
        print(f"  ERROR: {tval['error']}")
    else:
        print(f"  RMSE:  {tval['rmse_celsius']} °C  (threshold: {_TEMP_RMSE_THRESHOLD} °C)")
        print(f"  Bias:  {tval['bias_celsius']:+.1f} °C")
        print(f"  R²:    {tval['r_squared']}")
        print(f"  Result: {'✅ PASS' if tval['passed'] else '❌ FAIL'}")
    print()

    # 2. Precipitation
    print("=" * 60)
    print("2. Precipitation Validation (zonal mean vs GPCP)")
    print("-" * 60)
    pval = validate_zonal_precipitation(mesh)
    results["precipitation"] = pval
    if "error" in pval:
        print(f"  ERROR: {pval['error']}")
    else:
        print(f"  RMSE:  {pval['rmse_mm_yr']} mm/yr  (threshold: {_PRECIP_RMSE_THRESHOLD} mm/yr)")
        print(f"  Bias:  {pval['bias_mm_yr']:+.0f} mm/yr")
        print(f"  R²:    {pval['r_squared']}")
        print(f"  Result: {'✅ PASS' if pval['passed'] else '❌ FAIL'}")
    print()

    # 3. Koppen
    print("=" * 60)
    print("3. Koppen Classification Validation (vs Beck et al. 2018)")
    print("-" * 60)
    kval = validate_koppen_distribution(mesh)
    results["koppen_distribution"] = kval
    if "error" in kval:
        print(f"  ERROR: {kval['error']}")
    else:
        print(f"  Distribution match: {kval['match_rate']:.1%}  (threshold: {_KOPPEN_MATCH_THRESHOLD:.0%})")
        print(f"  Group R2:   {kval['group_r_squared']}")
        print(f"  Result: {'PASS' if kval['passed'] else 'FAIL'}")
    print()

    # 3b. Koppen spatial (cell-by-cell)
    print("=" * 60)
    print("3b. Koppen Spatial Accuracy (cell-by-cell vs Beck 2018)")
    print("-" * 60)
    # Look for koppen_obs.json in maps/ or old climate reference directory
    obs_candidates = [
        world_dir / "branches" / (branch or "") / "maps" / planet_id / "koppen_obs.json",
        world_dir / "maps" / planet_id / "koppen_obs.json",
        world_dir / "branches" / (branch or "") / "layers" / "climate" / "reference" / "koppen_obs.json",
        world_dir / "layers" / "climate" / "reference" / "koppen_obs.json",
    ]
    obs_path = next((p for p in obs_candidates if p.exists()), None)
    if obs_path is None:
        print("  SKIP: koppen_obs.json not found. Run scripts/convert_koppen_map.py first.")
        kval_spatial = {"error": "koppen_obs.json not found"}
    else:
        kval_spatial = validate_koppen_spatial(mesh, obs_path)
        if "error" in kval_spatial:
            print(f"  ERROR: {kval_spatial['error']}")
        else:
            print(f"  Overall accuracy: {kval_spatial['overall_accuracy']:.1%}")
            print(f"  Group accuracy:   {kval_spatial['group_accuracy']:.1%}")
            print(f"  Cohen's Kappa:    {kval_spatial['cohens_kappa']:.3f}")
            print(f"  Cells compared:   {kval_spatial['n_compared']}")
            if kval_spatial.get("per_group"):
                for g, stats in kval_spatial["per_group"].items():
                    print(f"    {g}: acc={stats['accuracy']:.1%} grp={stats['group_accuracy']:.1%} (n={stats['n_cells']})")
            if kval_spatial.get("top_confusions"):
                print(f"  Top confusions:")
                for conf in kval_spatial["top_confusions"][:5]:
                    print(f"    {conf['observed']} -> {conf['simulated']}: {conf['count']} cells")
            print(f"  Result: {'PASS' if kval_spatial['passed'] else 'FAIL'}")
    results["koppen_spatial"] = kval_spatial
    print()

    # 4. Land fraction
    print("=" * 60)
    print("4. Land Fraction Check")
    print("-" * 60)
    lval = validate_land_fraction(mesh)
    results["land_fraction"] = lval
    print(f"  Simulated: {lval['simulated_pct']}%  (Earth: {lval['reference_pct']}%)")
    print(f"  Result: {'PASS' if lval['passed'] else 'WARN'}")
    print()

    # --- Overall verdict ---
    check_results = [tval, pval, kval, lval]
    if "error" not in kval_spatial:
        check_results.append(kval_spatial)
    all_passed = all(
        r.get("passed", False)
        for r in check_results
        if "error" not in r
    )
    results["overall_passed"] = all_passed

    print("=" * 60)
    if all_passed:
        print("OVERALL: Climate engine VALIDATED against Earth observations")
    else:
        print("OVERALL: Climate engine FAILED validation - see above for details")
    print("=" * 60)

    # --- Save report ---
    if output_dir is not None:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        report_path = output_dir / "climate_validation.json"
        with report_path.open("w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
        print(f"\nReport saved to: {report_path}")

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate dreamulator climate engine against real Earth data",
    )
    parser.add_argument("world", help="World name (e.g. 'earth')")
    parser.add_argument("--planet", default="earth", help="Planet ID within the world")
    parser.add_argument("--branch", default=None, help="Branch name")
    parser.add_argument(
        "--output-dir", "-o", default=None,
        help="Directory to save validation report JSON",
    )
    parser.add_argument(
        "--quick", action="store_true",
        help="Quick mode: zonal statistics only (bypasses mesh loading)",
    )
    parser.add_argument(
        "--data-dir", default=None,
        help="Custom worlds data directory",
    )
    args = parser.parse_args()

    report = run_validation(
        world_name=args.world,
        planet_id=args.planet,
        branch=args.branch,
        output_dir=Path(args.output_dir) if args.output_dir else None,
        quick=args.quick,
        data_dir=args.data_dir,
    )

    if "error" in report:
        print(f"ERROR: {report['error']}", file=sys.stderr)
        sys.exit(1)

    if not report.get("overall_passed", False):
        sys.exit(2)


if __name__ == "__main__":
    main()
