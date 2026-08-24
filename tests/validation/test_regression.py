"""Tier 1 (regression gate) — baseline comparison for nacrea 200k.

Compares the current climate engine output against a committed baseline
snapshot (``tests/validation/baselines/nacrea-200k.json``).  Fails when
key metrics drift beyond tolerance — this is the CI safety net.

These tests are marked ``slow`` because they load the full 200k-cell CVT
mesh and run the climate simulation (~90 s).  Run with::

    pytest tests/validation/test_regression.py -m slow
"""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Tolerance thresholds
# ---------------------------------------------------------------------------

_TOLERANCES: dict[str, float] = {
    "temperature_global_mean_c": 2.0,  # °C  — wide: EBM can shift with physics changes
    "temperature_land_mean_c": 3.0,
    "temperature_ocean_mean_c": 2.0,
    "precipitation_global_mean_mm": 200.0,  # mm/yr — wide: precip is noisy
    "precipitation_land_mean_mm": 200.0,
    "land_fraction": 0.02,  # absolute (2%)
}

# Maximum absolute percentage-point change per Köppen group
_KOPPEN_GROUP_TOLERANCE = 0.08  # 8 pp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_project_root() -> Path:
    d = Path(__file__).resolve().parent
    while d != d.parent:
        if (d / "pyproject.toml").exists():
            return d
        d = d.parent
    return Path.cwd()


def _data_dir() -> Path:
    """Resolve the worlds data directory."""
    env = os.environ.get("DREAMULATOR_DATA_DIR")
    if env:
        return Path(env)
    root = _find_project_root()
    # Prefer private/ over data/ for local dev (mirrors CLI default)
    private = root / "private" / "worlds"
    if private.exists():
        return private
    return root / "data" / "worlds"


def _load_baseline() -> dict[str, Any]:
    """Load the nacrea 200k baseline snapshot."""
    baseline_path = _find_project_root() / "tests" / "validation" / "baselines" / "nacrea-200k.json"
    if not baseline_path.exists():
        pytest.skip(f"Baseline not found at {baseline_path}")
    with baseline_path.open("r", encoding="utf-8") as f:
        return json.load(f)  # type: ignore[no-any-return]


def _run_climate_on_world(
    world: str = "nacrea",
    planet: str = "satellite_nacrea",
    seed: int = 42,
) -> tuple[dict[str, Any], Any]:
    """Load a world's CVT mesh (from committed data) and run climate."""
    from dreamulator.map.climate_simulator import simulate_climate
    from dreamulator.map.models import CVTMesh
    from dreamulator.map.pipeline_types import TerrainPipelineConfig

    world_dir = _data_dir() / world
    mesh_path = world_dir / "maps" / planet / "cvt_mesh.json"
    if not mesh_path.exists():
        pytest.skip(f"Mesh not found at {mesh_path} — run 'dreamulator build {world}' first")

    from dreamulator.map.export import decompress_mesh_bytes

    mesh_data = json.loads(decompress_mesh_bytes(mesh_path.read_bytes()))

    num_cells = mesh_data.get("num_cells", len(mesh_data.get("cells", [])))
    mesh = CVTMesh(**mesh_data)

    # Resolve climate parameters from map.yaml if available
    map_yaml = world_dir / "maps" / planet / "map.yaml"
    radius_km = 6371.0
    if map_yaml.exists():
        import yaml

        with map_yaml.open("r", encoding="utf-8") as f:
            _mm = yaml.safe_load(f) or {}
        radius_km = float(_mm.get("radius_km", radius_km))

    # Resolve climate parameters from terrain_config.yaml (world-specific tuning:
    # auto_lat_gradient, Hadley/polar cell boundaries, ice-albedo feedback, etc.).
    # Fall back to defaults when the file is missing.
    terrain_cfg_path = world_dir / "layers" / "geological" / "input" / "terrain_config.yaml"
    if terrain_cfg_path.exists():
        config = TerrainPipelineConfig.from_yaml(terrain_cfg_path)
    else:
        config = TerrainPipelineConfig()

    # Apply world physical parameters over climate defaults
    cm_path = world_dir / "maps" / planet / "climate_metadata.json"
    if cm_path.exists():
        with cm_path.open("r", encoding="utf-8") as f:
            cm = json.load(f)
        for k in (
            "stellar_luminosity_sol",
            "orbital_distance_au",
            "orbital_period_days",
            "axial_tilt_deg",
            "greenhouse_warming_K",
            "rotation_period_days",
            "eccentricity",
        ):
            if k in cm:
                setattr(config, k, float(cm[k]))
        if "albedo" in cm:
            config.albedo = float(cm["albedo"])

    config.seed = seed
    config.radius_km = radius_km
    config.num_nodes = num_cells

    simulate_climate(mesh, config)
    return mesh_data, mesh


def _compute_metrics(mesh: Any) -> dict[str, Any]:
    """Compute the same metrics that appear in the baseline snapshot."""
    temps = np.array([c.temperature_C for c in mesh.cells if c.temperature_C is not None])
    precip = np.array([c.precipitation_mm for c in mesh.cells if c.precipitation_mm is not None])
    elev = np.array([c.elevation for c in mesh.cells])
    land_mask = elev >= 0.0

    koppen_counts: Counter[str] = Counter()
    for c in mesh.cells:
        if land_mask[c.id] and c.koppen_class and c.koppen_class != "Ocean":
            koppen_counts[c.koppen_class] += 1
    total_land = max(sum(koppen_counts.values()), 1)

    group_counts: Counter[str] = Counter()
    for k, v in koppen_counts.items():
        group_counts[k[0]] += v

    return {
        "temperature": {
            "global_mean_c": round(float(np.nanmean(temps)), 2),
            "land_mean_c": round(
                float(np.nanmean(temps[land_mask])) if land_mask.any() else float("nan"), 2
            ),
            "ocean_mean_c": round(
                float(np.nanmean(temps[~land_mask])) if (~land_mask).any() else float("nan"),
                2,
            ),
            "min_c": round(float(np.nanmin(temps)), 2),
            "max_c": round(float(np.nanmax(temps)), 2),
        },
        "precipitation": {
            "global_mean_mm": round(float(np.nanmean(precip)), 1),
            "land_mean_mm": round(
                float(np.nanmean(precip[land_mask])) if land_mask.any() else float("nan"), 1
            ),
        },
        "koppen": {
            "class_counts": dict(sorted(koppen_counts.items())),
            "group_distribution": {
                g: round(group_counts.get(g, 0) / total_land, 3) for g in "ABCDE"
            },
            "n_classes": len(koppen_counts),
            "n_land_cells": total_land,
        },
        "land_fraction": round(float(land_mask.sum() / len(land_mask)), 4),
    }


# ---------------------------------------------------------------------------
# Regression tests
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestNacrea200kRegression:
    """Compare current climate output against the nacrea-200k baseline.

    These tests load the full 200k-cell mesh and run the climate simulation
    (~90 s).  Run selectively with ``pytest -m slow``.
    """

    @pytest.fixture(scope="class")
    def baseline(self) -> dict[str, Any]:
        return _load_baseline()

    @pytest.fixture(scope="class")
    def current(self) -> dict[str, Any]:
        _, mesh = _run_climate_on_world()
        return _compute_metrics(mesh)

    # -- Temperature ---------------------------------------------------------

    def test_temp_global_mean(self, baseline, current):
        bt = baseline["temperature"]["global_mean_c"]
        ct = current["temperature"]["global_mean_c"]
        delta = abs(ct - bt)
        assert delta <= _TOLERANCES["temperature_global_mean_c"], (
            f"Global mean temp drifted: baseline={bt}°C, current={ct}°C, delta={delta:.2f}°C"
        )

    def test_temp_land_mean(self, baseline, current):
        delta = abs(current["temperature"]["land_mean_c"] - baseline["temperature"]["land_mean_c"])
        assert delta <= _TOLERANCES["temperature_land_mean_c"], (
            f"Land mean temp drifted: baseline={baseline['temperature']['land_mean_c']}°C, "
            f"current={current['temperature']['land_mean_c']}°C, delta={delta:.2f}°C"
        )

    def test_temp_ocean_mean(self, baseline, current):
        bt = baseline["temperature"]["ocean_mean_c"]
        ct = current["temperature"]["ocean_mean_c"]
        delta = abs(ct - bt)
        assert delta <= _TOLERANCES["temperature_ocean_mean_c"], (
            f"Ocean mean temp drifted: baseline={bt}°C, current={ct}°C, delta={delta:.2f}°C"
        )

    def test_temp_range_ok(self, current):
        """Sanity: temperature range is within physically plausible bounds."""
        t_min = current["temperature"]["min_c"]
        t_max = current["temperature"]["max_c"]
        assert t_min > -100.0, f"T_min={t_min}°C implausibly cold"
        assert t_max < 60.0, f"T_max={t_max}°C implausibly hot"

    # -- Precipitation -------------------------------------------------------

    def test_precip_global_mean(self, baseline, current):
        bp = baseline["precipitation"]["global_mean_mm"]
        cp = current["precipitation"]["global_mean_mm"]
        delta = abs(cp - bp)
        assert delta <= _TOLERANCES["precipitation_global_mean_mm"], (
            f"Global mean precip drifted: baseline={bp} mm/yr, "
            f"current={cp} mm/yr, delta={delta:.1f}"
        )

    def test_precip_land_mean(self, baseline, current):
        bp = baseline["precipitation"]["land_mean_mm"]
        cp = current["precipitation"]["land_mean_mm"]
        delta = abs(cp - bp)
        assert delta <= _TOLERANCES["precipitation_land_mean_mm"], (
            f"Land mean precip drifted: baseline={bp} mm/yr, current={cp} mm/yr, delta={delta:.1f}"
        )

    # -- Land fraction -------------------------------------------------------

    def test_land_fraction(self, baseline, current):
        delta = abs(current["land_fraction"] - baseline["land_fraction"])
        assert delta <= _TOLERANCES["land_fraction"], (
            f"Land fraction drifted: baseline={baseline['land_fraction']:.1%}, "
            f"current={current['land_fraction']:.1%}, delta={delta:.3f}"
        )

    # -- Köppen groups -------------------------------------------------------

    def test_koppen_group_distribution(self, baseline, current):
        """Each Köppen group (A-E) must stay within tolerance of baseline."""
        failures = []
        for g in "ABCDE":
            bl = baseline["koppen"]["group_distribution"].get(g, 0.0)
            cu = current["koppen"]["group_distribution"].get(g, 0.0)
            delta = abs(cu - bl)
            if delta > _KOPPEN_GROUP_TOLERANCE:
                failures.append(
                    f"  Group {g}: baseline={bl:.1%}, current={cu:.1%}, delta={delta:.1%}"
                )
        assert not failures, (
            f"Köppen group distribution drifted beyond {_KOPPEN_GROUP_TOLERANCE:.0%} tolerance:\n"
            + "\n".join(failures)
        )

    def test_koppen_has_expected_classes(self, current):
        """Sanity: at least some Köppen classes are present."""
        n = current["koppen"]["n_classes"]
        assert n >= 5, f"Only {n} Köppen classes — likely a simulation error"

    def test_land_cell_count_consistent(self, baseline, current):
        """Land cell count should not change dramatically (mesh is fixed)."""
        bl = baseline["koppen"]["n_land_cells"]
        cu = current["koppen"]["n_land_cells"]
        # Land cell count depends on elevation — should be identical for same mesh
        assert cu == bl, f"Land cell count changed: {bl} → {cu} (mesh should be identical)"


@pytest.mark.slow
def test_mesh_cell_count_matches_baseline():
    """The committed mesh must have the same cell count as the baseline."""
    baseline = _load_baseline()
    expected = baseline["mesh_cells"]

    world_dir = _data_dir() / baseline["world"]
    mesh_path = world_dir / "maps" / baseline["planet"] / "cvt_mesh.json"
    if not mesh_path.exists():
        pytest.skip(f"Mesh not found at {mesh_path}")

    from dreamulator.map.export import decompress_mesh_bytes

    mesh_data = json.loads(decompress_mesh_bytes(mesh_path.read_bytes()))
    actual = mesh_data.get("num_cells", len(mesh_data.get("cells", [])))
    assert actual == expected, f"Mesh cell count mismatch: baseline={expected}, disk={actual}"
