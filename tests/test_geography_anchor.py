"""Tests for authored-geography continent anchoring (map/geography.py)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from dreamulator.map.cvt_mesh import generate_cvt_mesh
from dreamulator.map.geography import (
    GeographyFeature,
    GeographySpec,
    apply_geography_crust,
    build_land_bias_field,
    load_geography_spec,
)
from dreamulator.map.pipeline_types import TerrainPipelineConfig

REPO_ROOT = Path(__file__).resolve().parents[1]
GAIA_M_GEOGRAPHY = REPO_ROOT / "data/worlds/gaia-m/layers/geological/input/geography.yaml"


@pytest.fixture(scope="module")
def mesh():
    """Small CVT mesh shared by the tests (built once)."""
    cfg = TerrainPipelineConfig(seed=7, num_nodes=2500, lloyd_iterations=3)
    return generate_cvt_mesh(cfg)


def _config_with(spec: GeographySpec) -> TerrainPipelineConfig:
    cfg = TerrainPipelineConfig(seed=7)
    cfg.geography = spec
    return cfg


# ---------------------------------------------------------------------------
# Spec loading
# ---------------------------------------------------------------------------


def test_load_gaia_m_spec() -> None:
    spec = load_geography_spec(GAIA_M_GEOGRAPHY)
    assert spec is not None
    assert spec.features, "gaia-m geography.yaml must define features"
    assert spec.land_fraction_target == pytest.approx(0.28)
    kinds = {f.kind for f in spec.features}
    assert "continent" in kinds
    assert "ocean_basin" in kinds


def test_load_missing_returns_none() -> None:
    assert load_geography_spec(None) is None
    assert load_geography_spec(Path("nonexistent-geography.yaml")) is None


# ---------------------------------------------------------------------------
# Field construction
# ---------------------------------------------------------------------------


def test_land_anchor_positive_core_zero_falloff(mesh) -> None:
    spec = GeographySpec(features=[GeographyFeature(name="c", lon=0.0, lat=0.0, radius_deg=30.0)])
    field = build_land_bias_field(mesh, spec)
    assert field.shape == (len(mesh.cells),)

    def field_at(lon: float, lat: float) -> float:
        # nearest cell to the probe point
        lon_r, lat_r = np.radians(lon), np.radians(lat)
        p = np.array([np.cos(lat_r) * np.cos(lon_r), np.sin(lat_r), np.cos(lat_r) * np.sin(lon_r)])
        dots = np.array([c.x * p[0] + c.y * p[1] + c.z * p[2] for c in mesh.cells])
        return float(field[int(np.argmax(dots))])

    assert field_at(0.0, 0.0) > 0.9  # anchor core ≈ +1
    assert field_at(15.0, 0.0) > field_at(28.0, 0.0)  # monotone falloff
    assert abs(field_at(60.0, 0.0)) < 1e-9  # outside radius → 0


def test_ocean_anchor_negative(mesh) -> None:
    spec = GeographySpec(
        features=[
            GeographyFeature(name="land", lon=0.0, lat=0.0, radius_deg=30.0),
            GeographyFeature(name="sea", lon=180.0, lat=0.0, radius_deg=30.0, strength=-1.0),
        ]
    )
    field = build_land_bias_field(mesh, spec)
    xs = np.array([c.x for c in mesh.cells])
    west = field[xs > 0.9]  # near lon 0 (25.8° cap; kernel decays to edge)
    east = field[xs < -0.9]  # near lon 180
    assert west.mean() > 0.3
    assert east.mean() < -0.3


def test_elongated_feature_extends_along_axis(mesh) -> None:
    # N–S elongated feature at the equator: field farther out along the
    # meridian than along the parallel.
    spec = GeographySpec(
        features=[
            GeographyFeature(
                name="r", lon=0.0, lat=0.0, radius_deg=5.0, elongation=4.0, bearing_deg=0.0
            )
        ]
    )
    field = build_land_bias_field(mesh, spec)

    def field_at(lon: float, lat: float) -> float:
        lon_r, lat_r = np.radians(lon), np.radians(lat)
        p = np.array([np.cos(lat_r) * np.cos(lon_r), np.sin(lat_r), np.cos(lat_r) * np.sin(lon_r)])
        dots = np.array([c.x * p[0] + c.y * p[1] + c.z * p[2] for c in mesh.cells])
        return float(field[int(np.argmax(dots))])

    # Extends along the N–S axis (still strong at 8°) but is cut off across
    # the short axis (semi-minor 5°): this is what proves elongation.
    along_axis = field_at(0.0, 8.0)  # 8° north along the axis
    across_axis = field_at(8.0, 0.0)  # 8° east, beyond semi-minor (5°)
    assert along_axis > 0.3
    assert abs(across_axis) < 1e-9  # beyond semi-minor → 0


def test_polar_anchor(mesh) -> None:
    spec = GeographySpec(features=[GeographyFeature(name="p", lon=0.0, lat=90.0, radius_deg=20.0)])
    field = build_land_bias_field(mesh, spec)
    ys = np.array([c.y for c in mesh.cells])
    # ys > 0.94 = 20° polar cap (matches feature radius): all field > 0.
    assert field[ys > 0.94].mean() > 0.3  # north polar cap → land bias
    assert abs(field[ys < 0.0].mean()) < 0.15  # southern half ~ unaffected


def test_hemisphere_bias(mesh) -> None:
    spec = GeographySpec(hemisphere_land_bias=0.5, features=[])
    field = build_land_bias_field(mesh, spec)
    ys = np.array([c.y for c in mesh.cells])
    assert field[ys > 0.5].mean() > field[ys < -0.5].mean()


# ---------------------------------------------------------------------------
# Crust assignment
# ---------------------------------------------------------------------------


def test_apply_crust_matches_target_fraction(mesh) -> None:
    spec = GeographySpec(
        land_fraction_target=0.3,
        features=[GeographyFeature(name="c", lon=0.0, lat=0.0, radius_deg=40.0)],
    )
    cfg = _config_with(spec)
    apply_geography_crust(mesh, cfg)
    n_land = sum(1 for c in mesh.cells if c.crust_type == "continental")
    assert n_land / len(mesh.cells) == pytest.approx(0.3, abs=0.01)


def test_apply_crust_respects_anchors(mesh) -> None:
    spec = GeographySpec(
        land_fraction_target=0.3,
        features=[
            GeographyFeature(name="land", lon=0.0, lat=0.0, radius_deg=35.0),
            GeographyFeature(name="sea", lon=180.0, lat=0.0, radius_deg=35.0, strength=-1.0),
        ],
    )
    cfg = _config_with(spec)
    apply_geography_crust(mesh, cfg)

    xs = np.array([c.x for c in mesh.cells])
    west = [c for i, c in enumerate(mesh.cells) if xs[i] > 0.85]
    east = [c for i, c in enumerate(mesh.cells) if xs[i] < -0.85]
    land_w = sum(1 for c in west if c.crust_type == "continental") / len(west)
    land_e = sum(1 for c in east if c.crust_type == "continental") / len(east)
    assert land_w > 0.8
    assert land_e < 0.2


def test_apply_crust_noop_without_spec(mesh) -> None:
    cfg = TerrainPipelineConfig(seed=7)
    cfg.geography = None
    for c in mesh.cells:
        c.crust_type = "oceanic"
    apply_geography_crust(mesh, cfg)  # must not raise / change anything
    assert all(c.crust_type == "oceanic" for c in mesh.cells)


def test_apply_crust_deterministic(mesh) -> None:
    spec = GeographySpec(
        land_fraction_target=0.3,
        features=[GeographyFeature(name="c", lon=0.0, lat=0.0, radius_deg=40.0)],
    )
    cfg = _config_with(spec)
    apply_geography_crust(mesh, cfg)
    first = [c.crust_type for c in mesh.cells]
    apply_geography_crust(mesh, cfg)
    second = [c.crust_type for c in mesh.cells]
    assert first == second
