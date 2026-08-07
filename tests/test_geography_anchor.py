"""Tests for authored-geography continent anchoring (map/geography.py)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from dreamulator.map.cvt_mesh import generate_cvt_mesh
from dreamulator.map.geography import (
    GeographyFeature,
    GeographySpec,
    apply_geography_crust,
    build_elevation_pins,
    build_land_bias_field,
    load_geography_spec,
)
from dreamulator.map.pipeline_types import TerrainPipelineConfig
from dreamulator.map.terrain_synthesizer import (
    _apply_island_arcs,
    _apply_sea_level_calibration,
    _asymmetric_boundary_effects,
    apply_boundary_effects,
    synthesize_terrain,
)

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


# ---------------------------------------------------------------------------
# Elevation pins (build_elevation_pins)
# ---------------------------------------------------------------------------


def _nearest(mesh, lon: float, lat: float) -> int:
    """Index of the cell nearest to the probe point."""
    lon_r, lat_r = np.radians(lon), np.radians(lat)
    p = np.array([np.cos(lat_r) * np.cos(lon_r), np.sin(lat_r), np.cos(lat_r) * np.sin(lon_r)])
    dots = np.array([c.x * p[0] + c.y * p[1] + c.z * p[2] for c in mesh.cells])
    return int(np.argmax(dots))


def test_pins_none_without_targets(mesh) -> None:
    spec = GeographySpec(features=[GeographyFeature(name="c", lat=0.0, radius_deg=30.0)])
    assert build_elevation_pins(mesh, spec) is None


def test_pins_core_target_and_weight(mesh) -> None:
    spec = GeographySpec(
        features=[
            GeographyFeature(
                name="s",
                lat=0.0,
                radius_deg=20.0,
                strength=-0.5,
                elevation_target_m=-120.0,
            )
        ]
    )
    pins = build_elevation_pins(mesh, spec)
    assert pins is not None
    weight, target, strength = pins
    core = _nearest(mesh, 0.0, 0.0)
    assert weight[core] == pytest.approx(1.0, abs=0.1)
    assert target[core] == pytest.approx(-120.0)
    assert strength[core] == pytest.approx(1.0)
    far = _nearest(mesh, 90.0, 0.0)
    assert weight[far] == 0.0


def test_pins_overlap_blends(mesh) -> None:
    spec = GeographySpec(
        features=[
            GeographyFeature(name="a", lon=-5.0, lat=0.0, radius_deg=20.0, elevation_target_m=0.0),
            GeographyFeature(
                name="b", lon=5.0, lat=0.0, radius_deg=20.0, elevation_target_m=-200.0
            ),
        ]
    )
    pins = build_elevation_pins(mesh, spec)
    assert pins is not None
    _, target, _ = pins
    mid = _nearest(mesh, 0.0, 0.0)
    assert target[mid] == pytest.approx(-100.0, abs=20.0)


def test_pin_field_validation() -> None:
    with pytest.raises(ValidationError):
        GeographyFeature(name="x", lat=0.0, radius_deg=10.0, pin_strength=1.5)
    ok = GeographyFeature(name="x", lat=0.0, radius_deg=10.0, elevation_target_m=-80.0)
    assert ok.elevation_target_m == -80.0


# ---------------------------------------------------------------------------
# Convergent uplift suppression (roadmap #9)
# ---------------------------------------------------------------------------


def _small_mesh():
    return generate_cvt_mesh(TerrainPipelineConfig(seed=7, num_nodes=800, lloyd_iterations=2))


def _mark_boundaries(mesh) -> tuple[int, int]:
    """Hand-stamp one convergent and one divergent cell (no real plates)."""
    a = 0
    ca = mesh.cells[a]
    ca.boundary_type = "convergent"
    ca.distance_to_boundary_km = 0.0
    ca.convergence_rate_cm_yr = 5.0
    ca.crust_type = "continental"
    ca.plate_id = "p1"
    c = 1
    cc = mesh.cells[c]
    cc.boundary_type = "divergent"
    cc.distance_to_boundary_km = 0.0
    cc.convergence_rate_cm_yr = 5.0
    cc.crust_type = "continental"
    cc.plate_id = "p1"
    return a, c


def test_convergent_uplift_suppressed_gaussian() -> None:
    mesh = _small_mesh()
    a, _ = _mark_boundaries(mesh)
    cfg = TerrainPipelineConfig(seed=7)
    n = mesh.num_cells
    d_none = apply_boundary_effects(mesh, cfg)
    d_m1 = apply_boundary_effects(mesh, cfg, geography_bias=np.full(n, -1.0))
    assert d_none[a] > 0.0
    assert d_m1[a] == pytest.approx(0.1 * d_none[a])


def test_asymmetric_uplift_suppressed() -> None:
    mesh = _small_mesh()
    a, c = _mark_boundaries(mesh)
    cfg = TerrainPipelineConfig(seed=7)
    n = mesh.num_cells
    d0, _ = _asymmetric_boundary_effects(mesh, cfg)
    d1, _ = _asymmetric_boundary_effects(mesh, cfg, geography_bias=np.full(n, -1.0))
    assert d0[a] > 0.0
    assert d1[a] == pytest.approx(0.1 * d0[a])
    # Divergent (negative) term is untouched by the damping.
    assert d1[c] == pytest.approx(d0[c])


def _stamp_oceanic_arc(mesh) -> int:
    a = 0
    b = mesh.cells[a].neighbors[0]
    for idx, pid in ((a, "p1"), (b, "p2")):
        cell = mesh.cells[idx]
        cell.boundary_type = "convergent"
        cell.crust_type = "oceanic"
        cell.plate_id = pid
        cell.distance_to_boundary_km = 0.0
        cell.convergence_rate_cm_yr = 5.0
    return a


def test_island_arc_suppressed() -> None:
    # Fresh meshes per call: the first call re-stamps crust to transitional,
    # which would exclude the cell from the O-O arc selection on a rerun.
    cfg = TerrainPipelineConfig(seed=7)
    m0 = _small_mesh()
    a0 = _stamp_oceanic_arc(m0)
    n = m0.num_cells
    e0 = _apply_island_arcs(m0, np.zeros(n), cfg)
    m1 = _small_mesh()
    a1 = _stamp_oceanic_arc(m1)
    e1 = _apply_island_arcs(m1, np.zeros(n), cfg, geography_bias=np.full(n, -1.0))
    assert e0[a0] > 0.0
    assert e1[a1] == pytest.approx(0.1 * e0[a0])


def test_suppression_noop_without_geography() -> None:
    mesh = _small_mesh()
    _mark_boundaries(mesh)
    cfg = TerrainPipelineConfig(seed=7)
    n = mesh.num_cells
    d0 = apply_boundary_effects(mesh, cfg)
    # bias above the threshold (-0.3 > -0.5) must be a no-op, bit for bit.
    d_m03 = apply_boundary_effects(mesh, cfg, geography_bias=np.full(n, -0.3))
    assert np.array_equal(d0, d_m03)


# ---------------------------------------------------------------------------
# End-to-end pinning through synthesize_terrain
# ---------------------------------------------------------------------------


def _e2e_run(spec, offset: float = 0.0):
    cfg = TerrainPipelineConfig(
        seed=7,
        num_nodes=1200,
        lloyd_iterations=2,
        hotspot_count=0,
        shelf_width_km=0.0,
        coastal_plain_width_km=0.0,
        interior_orogeny_count=0,
        sea_level_offset_m=offset,
    )
    cfg.geography = spec
    mesh = generate_cvt_mesh(cfg)
    apply_geography_crust(mesh, cfg)
    synthesize_terrain(mesh, [], cfg)
    return mesh


def test_elevation_pin_pulls_core_to_target() -> None:
    spec = GeographySpec(
        features=[
            GeographyFeature(name="c", lat=0.0, radius_deg=30.0),
            GeographyFeature(
                name="s",
                lon=180.0,
                lat=0.0,
                radius_deg=20.0,
                strength=-1.0,
                elevation_target_m=-120.0,
            ),
        ]
    )
    mesh = _e2e_run(spec)
    core = mesh.cells[_nearest(mesh, 180.0, 0.0)]
    assert core.elevation == pytest.approx(-120.0, abs=1e-6)
    assert core.elevation < 0.0


def test_pin_noop_when_strength_zero() -> None:
    base = dict(lon=180.0, lat=0.0, radius_deg=20.0, strength=-1.0)
    spec_a = GeographySpec(
        features=[
            GeographyFeature(name="c", lat=0.0, radius_deg=30.0),
            GeographyFeature(name="s", elevation_target_m=-120.0, pin_strength=0.0, **base),
        ]
    )
    spec_b = GeographySpec(
        features=[
            GeographyFeature(name="c", lat=0.0, radius_deg=30.0),
            GeographyFeature(name="s", **base),
        ]
    )
    ea = np.array([c.elevation for c in _e2e_run(spec_a).cells])
    eb = np.array([c.elevation for c in _e2e_run(spec_b).cells])
    assert np.allclose(ea, eb)


def test_pin_deterministic() -> None:
    spec = GeographySpec(
        features=[
            GeographyFeature(name="c", lat=0.0, radius_deg=30.0),
            GeographyFeature(
                name="s",
                lon=180.0,
                lat=0.0,
                radius_deg=20.0,
                strength=-1.0,
                elevation_target_m=-120.0,
            ),
        ]
    )
    e1 = np.array([c.elevation for c in _e2e_run(spec).cells])
    e2 = np.array([c.elevation for c in _e2e_run(spec).cells])
    assert np.allclose(e1, e2)


# ---------------------------------------------------------------------------
# Sea-level calibration & offset knob
# ---------------------------------------------------------------------------


def test_calibration_surface_at_zero(mesh) -> None:
    rng = np.random.default_rng(3)
    n = mesh.num_cells
    elevation = rng.normal(0.0, 3000.0, n)
    cfg = TerrainPipelineConfig(seed=7, target_land_fraction=0.3)
    out = _apply_sea_level_calibration(mesh, elevation, cfg)
    diff = elevation - out
    assert np.allclose(diff, diff[0])  # pure datum shift
    areas = np.array([c.area_km2 for c in mesh.cells])
    frac = float(np.sum(areas[out > 0.0]) / np.sum(areas))
    assert frac == pytest.approx(0.3, abs=0.02)


def test_sea_level_offset_surface_at_offset() -> None:
    spec = GeographySpec(features=[GeographyFeature(name="c", lat=0.0, radius_deg=40.0)])
    m0 = _e2e_run(spec, offset=0.0)
    m120 = _e2e_run(spec, offset=-120.0)
    e0 = np.array([c.elevation for c in m0.cells])
    e120 = np.array([c.elevation for c in m120.cells])
    areas = np.array([c.area_km2 for c in m0.cells])
    frac0 = float(np.sum(areas[e0 > 0.0]) / np.sum(areas))
    exposed = float(np.sum(areas[e120 > -120.0]) / np.sum(areas))
    assert frac0 == pytest.approx(0.29, abs=0.03)
    # The lowstand surface exposes at least the calibrated land.  On a coarse
    # mesh the shallow band (-120, 0] may be empty (all ocean far below the
    # lowstand surface), so equality is allowed; a large surplus would mean
    # the offset leaked into the terrain array itself.
    assert exposed >= frac0 - 1e-9
    assert exposed <= frac0 + 0.2


def test_offset_shoals_strait_closes() -> None:
    """A -80 m strait pin emerges under a -120 m glacial offset (closure)."""
    spec = GeographySpec(
        features=[
            GeographyFeature(name="c", lat=0.0, radius_deg=40.0),
            GeographyFeature(
                name="strait",
                lon=180.0,
                lat=0.0,
                radius_deg=10.0,
                strength=-1.0,
                elevation_target_m=-80.0,
            ),
        ]
    )
    mesh = _e2e_run(spec, offset=-120.0)
    cell = mesh.cells[_nearest(mesh, 180.0, 0.0)]
    assert cell.elevation == pytest.approx(-80.0, abs=1e-6)
    assert cell.elevation > -120.0  # above the glacial sea surface
    # 40 m above the surface <= 50 m buffer -> transitional crust.
    assert cell.crust_type == "transitional"


def test_authored_ocean_base_override() -> None:
    """Continental crust leaked into an authored sea must not form plateaus.

    The top-N crust threshold leaks a few continental cells into any authored
    ocean; the base override (|bias| > 0.5) keeps them at the oceanic base so
    no +2000 m plateaus appear inside the rift (roadmap #9).
    """
    spec = GeographySpec(
        features=[
            GeographyFeature(name="c", lat=0.0, radius_deg=30.0),
            GeographyFeature(name="sea", lon=180.0, lat=0.0, radius_deg=30.0, strength=-3.0),
        ]
    )
    mesh = _e2e_run(spec)
    xs = np.array([c.x for c in mesh.cells])
    sea_core = [c.elevation for i, c in enumerate(mesh.cells) if xs[i] < -0.9]
    assert sea_core
    assert max(sea_core) < 0.0
