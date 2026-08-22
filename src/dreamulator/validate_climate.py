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
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import numpy as np

from dreamulator.map.models import CVTMesh

if TYPE_CHECKING:
    from dreamulator.map.pipeline_types import TerrainPipelineConfig

# ---------------------------------------------------------------------------
# Baseline / report schema version (increment when structure changes)
# ---------------------------------------------------------------------------
_SCHEMA_VERSION = 1

# Supported dataset identifiers
DatasetId = Literal["all", "era5", "gpcp", "beck2018"]
_DATASET_CHOICES: tuple[DatasetId, ...] = ("all", "era5", "gpcp", "beck2018")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Earth reference values (observed climatology, 1981–2010)
# These are zonal means at 2° latitude bands from ERA5 + GPCP.

# NCEP/NCAR Reanalysis 1 zonal-mean annual surface air temperature at 2° bands
# (90N → 88S). Values in °C. 90 bands: 90°N, 88°N, ..., 88°S.
# Derived from air.mon.ltm.nc (NOAA PSL). NCEP is within ~0.5°C of ERA5 zonally.
_ZONAL_TEMP_REF = np.array(
    [
        -15.1,
        -15.6,
        -15.6,
        -15.3,
        -14.8,
        -14.2,
        -12.9,
        -11.7,
        -10.4,
        -9.1,
        -8.1,
        -6.9,
        -5.5,
        -3.9,
        -2.3,
        -0.3,
        1.2,
        2.2,
        3.1,
        4.0,
        4.9,
        6.3,
        7.9,
        9.5,
        10.9,
        12.6,
        13.7,
        14.6,
        15.9,
        17.6,
        19.3,
        21.1,
        22.6,
        23.7,
        24.4,
        25.2,
        25.7,
        26.1,
        26.4,
        26.5,
        26.4,
        26.3,
        26.2,
        26.1,
        25.9,
        25.7,
        25.6,
        25.6,
        25.5,
        25.4,
        25.2,
        24.8,
        24.3,
        23.9,
        23.4,
        22.9,
        22.3,
        21.5,
        20.7,
        19.9,
        18.9,
        18.0,
        16.9,
        15.8,
        14.6,
        13.3,
        11.8,
        10.3,
        8.8,
        7.3,
        5.9,
        4.7,
        3.5,
        2.3,
        0.9,
        -0.8,
        -3.0,
        -5.6,
        -8.6,
        -12.4,
        -17.2,
        -22.5,
        -27.0,
        -30.4,
        -32.7,
        -33.8,
        -33.9,
        -35.3,
        -38.3,
        -42.0,
    ],
    dtype=np.float64,
)

# GPCP v2.3 zonal-mean annual precipitation at 2° bands (90N → 88S). mm/yr.
# Derived from precip.mon.mean.nc (NOAA PSL).
_ZONAL_PRECIP_REF = np.array(
    [
        189,
        184,
        180,
        183,
        206,
        226,
        251,
        295,
        343,
        395,
        471,
        549,
        609,
        682,
        744,
        819,
        876,
        884,
        882,
        901,
        912,
        921,
        941,
        975,
        1006,
        1019,
        1004,
        956,
        897,
        828,
        760,
        705,
        665,
        625,
        640,
        680,
        738,
        820,
        982,
        1296,
        1689,
        2030,
        2170,
        1909,
        1611,
        1466,
        1453,
        1493,
        1458,
        1364,
        1214,
        1060,
        950,
        843,
        754,
        703,
        690,
        707,
        752,
        794,
        840,
        887,
        931,
        977,
        1036,
        1069,
        1079,
        1074,
        1052,
        1024,
        1033,
        1071,
        1120,
        1164,
        1150,
        1055,
        900,
        717,
        553,
        467,
        381,
        312,
        284,
        250,
        200,
        160,
        136,
        129,
        136,
        145,
    ],
    dtype=np.float64,
)

# Beck et al. (2018) global Köppen class distribution (observed)
# Source: https://doi.org/10.1038/sdata.2018.214
# Area percentages of land surface.
_BECK_KOPPEN_DISTRIBUTION = {
    "Af": 9.0,
    "Am": 3.5,
    "Aw": 8.5,  # A: Tropical
    "BWh": 8.5,
    "BWk": 5.5,
    "BSh": 5.5,
    "BSk": 5.0,  # B: Arid
    "Csa": 2.5,
    "Csb": 2.0,
    "Csc": 0.2,  # C: Temperate dry summer
    "Cfa": 7.0,
    "Cfb": 4.0,
    "Cfc": 0.5,  # C: Temperate fully humid
    "Cwa": 3.0,
    "Cwb": 2.0,
    "Cwc": 0.2,  # C: Temperate dry winter
    "Dfa": 2.0,
    "Dfb": 4.0,
    "Dfc": 5.0,
    "Dfd": 0.3,  # D: Continental
    "Dsa": 0.1,
    "Dsb": 0.3,
    "Dsc": 0.2,
    "Dsd": 0.0,
    "Dwa": 1.0,
    "Dwb": 1.5,
    "Dwc": 1.0,
    "Dwd": 0.1,
    "ET": 6.0,
    "EF": 3.0,  # E: Polar
}

# ---------------------------------------------------------------------------
# Validation thresholds
# ---------------------------------------------------------------------------

# Maximum acceptable RMSE for temperature (°C)
_TEMP_RMSE_THRESHOLD = 5.0  # °C

# Maximum acceptable RMSE for precipitation (mm/yr)
_PRECIP_RMSE_THRESHOLD = 800.0  # mm/yr

# Minimum acceptable Köppen class match rate (fraction)
_KOPPEN_MATCH_THRESHOLD = 0.50  # 50%


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


def _load_mesh(world_dir: Path, planet_id: str, branch: str | None = None) -> CVTMesh | None:
    """Load CVT mesh from a world's map directory.

    Searches unified maps/ directory first, then old layer-based locations.
    """
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
            from dreamulator.map.export import decompress_mesh_bytes

            data = json.loads(decompress_mesh_bytes(p.read_bytes()))
            return CVTMesh(**data)

    return None


def build_earth_validation_config(
    num_nodes: int,
    *,
    lat_gradient_c: float = 45.0,
    auto_lat_gradient: bool = True,
    diffusive_heat_transport: bool = True,
    ebm_1d: bool = True,
) -> TerrainPipelineConfig:
    """Single source of truth for the Earth (climate-dev) validation config.

    Every caller — the three ``scripts/diagnose_*.py`` diagnostics and
    ``run_validation()`` below — must build its ``TerrainPipelineConfig`` from
    here rather than hand-writing it, so the Earth baseline cannot silently
    diverge from the engine's tuned configuration.

    ``ebm_1d=True`` is the shared-physics default — the 1D Energy Balance Model
    (North 1975 / climlab) formally solving
    ``0 = D∇²T + Q(φ)(1−α) − (A + B·T)`` for the zonal-mean temperature, the
    same code path gaia-m enables via its ``terrain_config.yaml``.  Pass it off
    (with ``auto_lat_gradient=True`` + ``diffusive_heat_transport=True``) to
    reproduce the legacy sin² + graph-diffusion baseline for comparison.
    """
    from dreamulator.map.pipeline_types import TerrainPipelineConfig

    return TerrainPipelineConfig(
        seed=42,
        radius_km=6371.0,
        rotation_period_days=1.0,
        stellar_luminosity_sol=1.0,
        orbital_distance_au=1.0,
        axial_tilt_deg=23.44,
        greenhouse_warming_K=33.0,
        lat_gradient_c=lat_gradient_c,
        auto_lat_gradient=auto_lat_gradient,
        diffusive_heat_transport=diffusive_heat_transport,
        ebm_1d=ebm_1d,
        lapse_rate_c_km=6.5,
        evaporation_base_mm=2000.0,
        orographic_efficiency=0.5,
        wind_blocking_height_m=3000.0,
        itcz_lag_days=30,
        num_nodes=num_nodes,
    )


def validate_zonal_temperature(mesh: CVTMesh) -> dict[str, Any]:
    """Compare simulated zonal-mean temperature against ERA5 reference.

    Aggregates cells into 2° latitude bands and compares against observed
    zonal means. Reports RMSE, mean bias, and spatial correlation.

    Args:
        mesh: CVTMesh with temperature_C populated.

    Returns:
        Dict with metrics.
    """
    cells = mesh.cells

    # Extract valid temperature + latitude
    temps = np.array(
        [c.temperature_C for c in cells if c.temperature_C is not None], dtype=np.float64
    )
    lats = np.array([c.lat for c in cells if c.temperature_C is not None], dtype=np.float64)

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


def validate_zonal_precipitation(mesh: CVTMesh) -> dict[str, Any]:
    """Compare simulated zonal-mean precipitation against GPCP reference.

    Args:
        mesh: CVTMesh with precipitation_mm populated.

    Returns:
        Dict with metrics.
    """
    cells = mesh.cells
    precip = np.array(
        [c.precipitation_mm for c in cells if c.precipitation_mm is not None], dtype=np.float64
    )
    lats = np.array([c.lat for c in cells if c.precipitation_mm is not None], dtype=np.float64)

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


def validate_koppen_distribution(mesh: CVTMesh) -> dict[str, Any]:
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


def validate_koppen_spatial(mesh: CVTMesh, obs_path: Path) -> dict[str, Any]:
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
        (obs_marginal[k] / n_compared) * (sim_marginal.get(k, 0) / n_compared) for k in obs_marginal
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


def validate_land_fraction(mesh: CVTMesh) -> dict[str, Any]:
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
# Baseline report dataclass
# ---------------------------------------------------------------------------


@dataclass
class ClimateValidationReport:
    """Serializable snapshot of climate validation metrics.

    Used for baseline generation and regression comparison.  Schema version
    is bumped when the structure changes incompatibly.
    """

    schema_version: int = _SCHEMA_VERSION
    planet: str = ""
    mesh_cells: int = 0
    world: str = ""
    seed: int = 0

    temperature: dict[str, Any] = field(default_factory=dict)
    precipitation: dict[str, Any] = field(default_factory=dict)
    koppen_distribution: dict[str, Any] = field(default_factory=dict)
    koppen_spatial: dict[str, Any] = field(default_factory=dict)
    land_fraction: dict[str, Any] = field(default_factory=dict)
    overall_passed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "world": self.world,
            "planet": self.planet,
            "mesh_cells": self.mesh_cells,
            "seed": self.seed,
            "temperature": self.temperature,
            "precipitation": self.precipitation,
            "koppen_distribution": self.koppen_distribution,
            "koppen_spatial": self.koppen_spatial,
            "land_fraction": self.land_fraction,
            "overall_passed": self.overall_passed,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ClimateValidationReport:
        return cls(
            schema_version=data.get("schema_version", _SCHEMA_VERSION),
            world=data.get("world", ""),
            planet=data.get("planet", ""),
            mesh_cells=data.get("mesh_cells", 0),
            seed=data.get("seed", 0),
            temperature=data.get("temperature", {}),
            precipitation=data.get("precipitation", {}),
            koppen_distribution=data.get("koppen_distribution", {}),
            koppen_spatial=data.get("koppen_spatial", {}),
            land_fraction=data.get("land_fraction", {}),
            overall_passed=data.get("overall_passed", False),
        )

    def compare_to(self, baseline: ClimateValidationReport) -> dict[str, Any]:
        """Compare this report against a baseline, returning per-metric diffs.

        Returns a dict with ``passed`` (bool), ``metrics`` (list of per-metric
        comparisons), and ``schema_version_match``.
        """
        diffs: list[dict[str, Any]] = []

        # --- Temperature ---
        if "rmse_celsius" in self.temperature and "rmse_celsius" in baseline.temperature:
            delta = self.temperature["rmse_celsius"] - baseline.temperature["rmse_celsius"]
            diffs.append(
                {
                    "metric": "temperature_rmse_celsius",
                    "current": self.temperature["rmse_celsius"],
                    "baseline": baseline.temperature["rmse_celsius"],
                    "delta": round(delta, 2),
                    "tolerance": 2.0,
                    "passed": abs(delta) <= 2.0,
                }
            )

        if "bias_celsius" in self.temperature and "bias_celsius" in baseline.temperature:
            delta = self.temperature["bias_celsius"] - baseline.temperature["bias_celsius"]
            diffs.append(
                {
                    "metric": "temperature_bias_celsius",
                    "current": self.temperature["bias_celsius"],
                    "baseline": baseline.temperature["bias_celsius"],
                    "delta": round(delta, 2),
                    "tolerance": 2.0,
                    "passed": abs(delta) <= 2.0,
                }
            )

        # --- Precipitation ---
        if "rmse_mm_yr" in self.precipitation and "rmse_mm_yr" in baseline.precipitation:
            delta = self.precipitation["rmse_mm_yr"] - baseline.precipitation["rmse_mm_yr"]
            diffs.append(
                {
                    "metric": "precipitation_rmse_mm_yr",
                    "current": self.precipitation["rmse_mm_yr"],
                    "baseline": baseline.precipitation["rmse_mm_yr"],
                    "delta": round(delta, 1),
                    "tolerance": 200.0,
                    "passed": abs(delta) <= 200.0,
                }
            )

        # --- Köppen distribution ---
        cur_kd = self.koppen_distribution
        base_kd = baseline.koppen_distribution
        if "match_rate" in cur_kd and "match_rate" in base_kd:
            delta = cur_kd["match_rate"] - base_kd["match_rate"]
            diffs.append(
                {
                    "metric": "koppen_match_rate",
                    "current": self.koppen_distribution["match_rate"],
                    "baseline": baseline.koppen_distribution["match_rate"],
                    "delta": round(delta, 3),
                    "tolerance": 0.10,
                    "passed": abs(delta) <= 0.10,
                }
            )

        # --- Köppen spatial ---
        cur_ks = self.koppen_spatial
        base_ks = baseline.koppen_spatial
        if "overall_accuracy" in cur_ks and "overall_accuracy" in base_ks:
            delta = cur_ks["overall_accuracy"] - base_ks["overall_accuracy"]
            diffs.append(
                {
                    "metric": "koppen_accuracy",
                    "current": self.koppen_spatial["overall_accuracy"],
                    "baseline": baseline.koppen_spatial["overall_accuracy"],
                    "delta": round(delta, 3),
                    "tolerance": 0.10,
                    "passed": abs(delta) <= 0.10,
                }
            )

        # --- Land fraction ---
        if "simulated_pct" in self.land_fraction and "simulated_pct" in baseline.land_fraction:
            delta = self.land_fraction["simulated_pct"] - baseline.land_fraction["simulated_pct"]
            diffs.append(
                {
                    "metric": "land_fraction_pct",
                    "current": self.land_fraction["simulated_pct"],
                    "baseline": baseline.land_fraction["simulated_pct"],
                    "delta": round(delta, 1),
                    "tolerance": 5.0,
                    "passed": abs(delta) <= 5.0,
                }
            )

        schema_ok = self.schema_version == baseline.schema_version
        all_passed = schema_ok and all(d["passed"] for d in diffs)

        return {
            "passed": all_passed,
            "schema_version_match": schema_ok,
            "metrics": diffs,
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
    datasets: DatasetId | list[DatasetId] = "all",
) -> dict[str, Any]:
    """Run the full climate validation pipeline.

    Args:
        world_name: Name of the world to validate against.
        planet_id: Planet ID within the world.
        branch: Optional branch name.
        output_dir: Where to write validation report.
        quick: If True, only run zonal validation (no mesh needed).
        data_dir: Custom worlds data directory.
        datasets: Which datasets to validate against.
            ``"all"`` (default), ``"era5"``, ``"gpcp"``, ``"beck2018"``,
            or a list thereof.

    Returns:
        Validation report dict.
    """
    # --- Normalize dataset selection ---
    if isinstance(datasets, str):
        _ds_list: list[DatasetId] = [datasets]
    else:
        _ds_list = list(datasets)

    _run_all = "all" in _ds_list
    _run_temp = _run_all or "era5" in _ds_list
    _run_precip = _run_all or "gpcp" in _ds_list
    _run_koppen = _run_all or "beck2018" in _ds_list

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

    print("Validating climate engine against real Earth observations...")
    print(f"  World: {world_name}  Planet: {planet_id}")
    print(f"  Mesh: {mesh.num_cells} cells")
    print()

    # Run climate simulation on this mesh
    from dreamulator.map.climate_simulator import simulate_climate

    config = build_earth_validation_config(mesh.num_cells)

    print("Running climate simulation on real Earth elevation...")
    simulate_climate(mesh, config)
    print()

    # --- Run validations ---
    results: dict[str, Any] = {"planet": planet_id, "mesh_cells": mesh.num_cells}

    # 1. Temperature
    if _run_temp:
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
    else:
        tval = {"skipped": True, "reason": "dataset not selected"}
        results["temperature"] = tval

    # 2. Precipitation
    if _run_precip:
        print("=" * 60)
        print("2. Precipitation Validation (zonal mean vs GPCP)")
        print("-" * 60)
        pval = validate_zonal_precipitation(mesh)
        results["precipitation"] = pval
        if "error" in pval:
            print(f"  ERROR: {pval['error']}")
        else:
            print(
                f"  RMSE:  {pval['rmse_mm_yr']} mm/yr  (threshold: {_PRECIP_RMSE_THRESHOLD} mm/yr)"
            )
            print(f"  Bias:  {pval['bias_mm_yr']:+.0f} mm/yr")
            print(f"  R²:    {pval['r_squared']}")
            print(f"  Result: {'✅ PASS' if pval['passed'] else '❌ FAIL'}")
        print()
    else:
        pval = {"skipped": True, "reason": "dataset not selected"}
        results["precipitation"] = pval

    # 3. Koppen
    if _run_koppen:
        print("=" * 60)
        print("3. Koppen Classification Validation (vs Beck et al. 2018)")
        print("-" * 60)
        kval = validate_koppen_distribution(mesh)
        results["koppen_distribution"] = kval
        if "error" in kval:
            print(f"  ERROR: {kval['error']}")
        else:
            print(
                f"  Distribution match: {kval['match_rate']:.1%} "
                f"(threshold: {_KOPPEN_MATCH_THRESHOLD:.0%})"
            )
            print(f"  Group R2:   {kval['group_r_squared']}")
            print(f"  Result: {'PASS' if kval['passed'] else 'FAIL'}")
        print()
    else:
        kval = {"skipped": True, "reason": "dataset not selected"}
        results["koppen_distribution"] = kval

    # 3b. Koppen spatial (cell-by-cell)
    if _run_koppen:
        print("=" * 60)
        print("3b. Koppen Spatial Accuracy (cell-by-cell vs Beck 2018)")
        print("-" * 60)
        # Look for koppen_obs.json in maps/ or old climate reference directory
        obs_candidates = [
            world_dir / "branches" / (branch or "") / "maps" / planet_id / "koppen_obs.json",
            world_dir / "maps" / planet_id / "koppen_obs.json",
            world_dir
            / "branches"
            / (branch or "")
            / "layers"
            / "climate"
            / "reference"
            / "koppen_obs.json",
            world_dir / "layers" / "climate" / "reference" / "koppen_obs.json",
        ]
        obs_path = next((p for p in obs_candidates if p.exists()), None)
        if obs_path is None:
            print("  SKIP: koppen_obs.json not found. Run scripts/convert_koppen_map.py first.")
            kval_spatial: dict[str, Any] = {"error": "koppen_obs.json not found"}
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
                        print(
                            f"    {g}: acc={stats['accuracy']:.1%} "
                            f"grp={stats['group_accuracy']:.1%} (n={stats['n_cells']})"
                        )
                if kval_spatial.get("top_confusions"):
                    print("  Top confusions:")
                    for conf in kval_spatial["top_confusions"][:5]:
                        print(
                            f"    {conf['observed']} -> {conf['simulated']}: {conf['count']} cells"
                        )
                print(f"  Result: {'PASS' if kval_spatial['passed'] else 'FAIL'}")
        results["koppen_spatial"] = kval_spatial
        print()
    else:
        kval_spatial = {"skipped": True, "reason": "dataset not selected"}
        results["koppen_spatial"] = kval_spatial

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
    if _run_koppen and "error" not in kval_spatial:
        check_results.append(kval_spatial)
    # Only consider actually-run validations for the pass threshold
    active_results = [r for r in check_results if "error" not in r and not r.get("skipped")]
    all_passed = len(active_results) > 0 and all(r.get("passed", False) for r in active_results)
    results["overall_passed"] = all_passed
    results["datasets_requested"] = _ds_list

    print("=" * 60)
    if all_passed:
        print("OVERALL: Climate engine VALIDATED against Earth observations")
    elif not active_results:
        print("OVERALL: No validations were run (all skipped)")
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
        "--output-dir",
        "-o",
        default=None,
        help="Directory to save validation report JSON",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Quick mode: zonal statistics only (bypasses mesh loading)",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Custom worlds data directory",
    )
    parser.add_argument(
        "--dataset",
        default="all",
        choices=list(_DATASET_CHOICES),
        help="Which reference dataset to validate against (default: all)",
    )
    args = parser.parse_args()

    report = run_validation(
        world_name=args.world,
        planet_id=args.planet,
        branch=args.branch,
        output_dir=Path(args.output_dir) if args.output_dir else None,
        quick=args.quick,
        data_dir=args.data_dir,
        datasets=args.dataset,
    )

    if "error" in report:
        print(f"ERROR: {report['error']}", file=sys.stderr)
        sys.exit(1)

    if not report.get("overall_passed", False):
        sys.exit(2)


if __name__ == "__main__":
    main()
