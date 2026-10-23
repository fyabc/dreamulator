"""Canvas geometry conventions of map/td_canvas."""

from __future__ import annotations

import math

import numpy as np
import pytest

from dreamulator.map import td_canvas as tc


@pytest.fixture
def geom() -> tc.CanvasGeometry:
    return tc.CanvasGeometry(center_lat=18.77, center_lon=37.36, radius_km=6816.97, ncell=464)


def test_grid_constants(geom: tc.CanvasGeometry) -> None:
    assert geom.px_km == pytest.approx(23.0 / 256)
    assert geom.size_px == 464 * 256
    assert geom.nchunk == 58
    assert geom.half_km == pytest.approx(464 * 23.0 / 2)


def test_centre_pixel_corner_is_canvas_centre(geom: tc.CanvasGeometry) -> None:
    # pixel coordinates are corner based: (size/2, size/2) is the shared corner at the centre
    lat, lon = geom.pixel_to_latlon(np.array(geom.size_px / 2), np.array(geom.size_px / 2))
    assert float(lat) == pytest.approx(geom.center_lat, abs=1e-9)
    assert float(lon) == pytest.approx(geom.center_lon, abs=1e-9)


def test_row_zero_is_north_and_col_zero_is_west(geom: tc.CanvasGeometry) -> None:
    mid = geom.size_px / 2
    lat_n, _ = geom.pixel_to_latlon(np.array(0.5), np.array(mid))
    lat_s, _ = geom.pixel_to_latlon(np.array(geom.size_px - 0.5), np.array(mid))
    _, lon_w = geom.pixel_to_latlon(np.array(mid), np.array(0.5))
    _, lon_e = geom.pixel_to_latlon(np.array(mid), np.array(geom.size_px - 0.5))
    assert lat_n > geom.center_lat > lat_s
    assert lon_w < geom.center_lon < lon_e


def test_pixel_latlon_round_trip(geom: tc.CanvasGeometry) -> None:
    rng = np.random.default_rng(0)
    r = rng.uniform(0, geom.size_px, 1000)
    c = rng.uniform(0, geom.size_px, 1000)
    lat, lon = geom.pixel_to_latlon(r, c)
    r2, c2 = geom.latlon_to_pixel(lat, lon)
    np.testing.assert_allclose(r2, r, atol=1e-5)
    np.testing.assert_allclose(c2, c, atol=1e-5)


def test_radial_distance_is_true_geodesic(geom: tc.CanvasGeometry) -> None:
    # equidistant: planar distance from the centre equals the great-circle distance
    x, y = np.array([1000.0, -2500.0, 4000.0]), np.array([3000.0, 500.0, -1000.0])
    lat, lon = geom.xy_to_latlon(x, y)
    v0 = tc.unit_vectors(np.array(geom.center_lat), np.array(geom.center_lon))
    d = np.arccos(np.clip(tc.unit_vectors(lat, lon) @ v0, -1, 1)) * geom.radius_km
    np.testing.assert_allclose(d, np.hypot(x, y), rtol=1e-9)


def test_coarse_cell_covers_256_pixels(geom: tc.CanvasGeometry) -> None:
    # centre of coarse cell (i, j) = centre of its 256-px block
    la, lo = geom.coarse_centres_latlon()
    i, j = 100, 300
    lat, lon = geom.pixel_to_latlon(np.array((i + 0.5) * 256), np.array((j + 0.5) * 256))
    assert float(lat) == pytest.approx(la[i, j], abs=1e-9)
    assert float(lon) == pytest.approx(lo[i, j], abs=1e-9)


def test_anisotropy() -> None:
    assert tc.anisotropy(0.0) == 1.0
    assert tc.anisotropy(1.0) == pytest.approx(1.0 / math.sin(1.0))


def test_owner_is_nearest_member_land() -> None:
    pts = tc.unit_vectors(np.array([0.0, 0.0]), np.array([0.0, 20.0]))
    owner = tc.owner_of(np.array([1.0, 2.0]), np.array([4.0, 15.0]), pts, np.array([0, 1]))
    assert owner.tolist() == [0, 1]


def test_sample_mesh_field_block_mean_and_monthly_axis() -> None:
    geom = tc.CanvasGeometry(center_lat=0.0, center_lon=0.0, radius_km=6371.0, ncell=16)
    # a dense "mesh" of points; value = longitude, so the field increases eastward
    lat, lon = np.meshgrid(
        np.linspace(-20.125, 20.125, 162), np.linspace(-20.125, 20.125, 162), indexing="ij"
    )
    xyz = tc.unit_vectors(lat.ravel(), lon.ravel())
    out = tc.sample_mesh_field(geom, lon.ravel(), xyz)
    assert out.shape == (16, 16)
    assert np.all(np.diff(out, axis=1) > 0)
    monthly = tc.sample_mesh_field(geom, np.stack([lon.ravel()] * 12, axis=1), xyz)
    assert monthly.shape == (12, 16, 16)
    np.testing.assert_allclose(monthly[5], out)
    codes = tc.sample_mesh_field(geom, (lon.ravel() > 0).astype(np.uint8), xyz, categorical=True)
    assert codes.dtype == np.uint8 and codes[:, :8].max() == 0 and codes[:, 8:].min() == 1


def test_land_cut_splits_a_component() -> None:
    from types import SimpleNamespace

    # a 1-cell-wide equatorial land strip (1 deg spacing) with ocean at both ends
    n = 41
    cells = [
        SimpleNamespace(
            lat=0.0,
            lon=float(i),
            area_km2=1.0e4,
            water_class="ocean" if i in (0, n - 1) else "land",
            neighbors=[j for j in (i - 1, i + 1) if 0 <= j < n],
        )
        for i in range(n)
    ]
    mesh = SimpleNamespace(cells=cells)
    whole = tc.land_components(mesh, 6371.0)  # type: ignore[arg-type]
    assert len(whole.component_km2) == 1
    cut = tc.land_components(mesh, 6371.0, (tc.LandCut(0.0, 20.0, 60.0),))  # type: ignore[arg-type]
    assert len(cut.component_km2) == 2
    assert cut.labels[20] == -2 and cut.labels[0] == -1
    assert cut.labels[19] != cut.labels[21]


def test_reattached_cut_splits_then_returns_its_land() -> None:
    from types import SimpleNamespace

    n = 41
    cells = [
        SimpleNamespace(
            lat=0.0,
            lon=float(i),
            area_km2=1.0e4,
            water_class="ocean" if i in (0, n - 1) else "land",
            neighbors=[j for j in (i - 1, i + 1) if 0 <= j < n],
        )
        for i in range(n)
    ]
    mesh = SimpleNamespace(cells=cells)
    cut = tc.land_components(mesh, 6371.0, (tc.LandCut(0.0, 20.0, 300.0, reattach=True),))  # type: ignore[arg-type]
    assert len(cut.component_km2) == 2
    assert (cut.labels[1:-1] >= 0).all()  # no land left outside a piece
    assert cut.labels[18] == cut.labels[1] and cut.labels[22] == cut.labels[39]
    assert cut.component_km2.sum() == 39 * 1.0e4


def _blend_case(offset_b: float = 0.0):
    rng = np.random.default_rng(0)
    n = 800
    x = (np.arange(n) - n / 2) * 0.5  # km, 0.5 km pixels; ownership line at x = 0
    dist_a = np.tile(np.maximum(x, 0.0), (n, 1))
    dist_b = np.tile(np.maximum(-x, 0.0), (n, 1))
    base = 500.0 + np.zeros((n, n))
    a = base + rng.normal(0, 30, (n, n))
    b = base + offset_b + rng.normal(0, 30, (n, n))
    return a, b, dist_a, dist_b


def test_blend_overlap_removes_the_step_and_keeps_one_sides_detail() -> None:
    from scipy.ndimage import gaussian_filter

    a, b, da, db = _blend_case(offset_b=200.0)
    h = tc.blend_overlap(a, b, da, db, 0.5)
    hard = np.where(da <= db, a, b)
    mid = h.shape[1] // 2 + 1  # first column owned by B
    step = np.abs(h[:, mid] - h[:, mid - 1]).mean()
    hard_step = np.abs(hard[:, mid] - hard[:, mid - 1]).mean()
    assert step < 0.3 * hard_step
    detail = h - gaussian_filter(h, 4)
    raw = a - gaussian_filter(a, 4)
    sl = np.s_[:, mid - 80 : mid - 12]  # inside the low band, outside the detail band
    assert detail[sl].std() > 0.9 * raw[sl].std()
    far = np.s_[:, :20]  # 200 km from the line: beyond every band
    assert np.allclose(h[far], a[far], atol=0.5)


def test_blend_overlap_falls_back_to_linear_on_land_sea_disagreement() -> None:
    a, b, da, db = _blend_case()
    b = b - 1000.0  # B is sea where A is land
    h = tc.blend_overlap(a, b, da, db, 0.5)
    w = tc.blend_weight(da, db, tc.BLEND_LINEAR_KM)
    mid = h.shape[1] // 2
    lin = w * a + (1 - w) * b
    assert np.abs(h[:, mid] - lin[:, mid]).max() < 1e-6


def test_plan_layout_join_overrides_the_gap_rule() -> None:
    from types import SimpleNamespace

    # two land strips on the equator ~1100 km apart (beyond two buffer widths)
    lons = [float(i) for i in range(0, 12)] + [float(i) for i in range(22, 26)]
    cells = []
    for k, lo in enumerate(lons):
        nb = [j for j in (k - 1, k + 1) if 0 <= j < len(lons) and abs(lons[j] - lo) == 1.0]
        cells.append(
            SimpleNamespace(lat=0.0, lon=lo, area_km2=5.0e4, water_class="land", neighbors=nb)
        )
    land = tc.land_components(SimpleNamespace(cells=cells), 6371.0)  # type: ignore[arg-type]
    assert len(land.component_km2) == 2
    plans, _ = tc.plan_layout(land)
    assert len(plans) == 2
    big, small = int(np.argmax(land.component_km2)), int(np.argmin(land.component_km2))
    joined, _ = tc.plan_layout(land, joins={small: big})
    assert len(joined) == 1 and sorted(joined[0].components) == sorted([big, small])
