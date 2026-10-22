"""Tests for the region pack export (window math + pack round-trip)."""

from __future__ import annotations

import json
import math
from typing import TYPE_CHECKING

import numpy as np
import pytest

if TYPE_CHECKING:
    from pathlib import Path

from dreamulator.map.models import CVTMesh, VoronoiCell
from dreamulator.map.region_export import (
    RegionWindowError,
    export_region_pack,
    region_window,
)

R = 6371.0
W, H = 360, 180  # ~1°/px grid keeps the arithmetic obvious


# ---------------------------------------------------------------------------
# Window math (azimuthal equidistant)
# ---------------------------------------------------------------------------


def test_window_square_in_km_at_equator() -> None:
    win = region_window(0.0, 0.0, 2500.0, R)
    x_grid, y_grid = win.out_xy(101)
    # The raster spans exactly the window: pixel centres from −half+p/2 to
    # +half−p/2, uniform pitch, row 0 at the north edge.
    pitch = win.span_km / 101
    assert x_grid[0, 0] == pytest.approx(-win.half_km + pitch / 2)
    assert x_grid[0, -1] == pytest.approx(win.half_km - pitch / 2)
    assert y_grid[0, 0] == pytest.approx(win.half_km - pitch / 2)
    assert y_grid[-1, 0] == pytest.approx(-win.half_km + pitch / 2)
    # The AEQ plane keeps centre distances true: the north-edge midpoint is
    # exactly half a span from the centre in great-circle terms too.
    lat, lon = win.xy_to_latlon(np.array([0.0]), np.array([win.half_km]))
    assert float(lat[0]) == pytest.approx(math.degrees(1250.0 / R), abs=1e-6)
    assert float(lon[0]) == pytest.approx(0.0, abs=1e-9)


def test_window_high_latitude_is_true_distance() -> None:
    win = region_window(60.0, 0.0, 2500.0, R)
    # At 60° the north edge must still sit 1250 km away, i.e. 11.24° of
    # latitude north of the centre — the old equirect crop kept that but
    # stretched the east–west scale unevenly across the window.
    lat, _ = win.xy_to_latlon(np.array([0.0]), np.array([win.half_km]))
    assert float(lat[0]) == pytest.approx(60.0 + math.degrees(1250.0 / R), abs=1e-6)
    # The east edge is 1250 km of true (great-circle) distance; on a sphere
    # that is Δlon = atan2(sin c, cos φ₀ · cos c), not the flat 1250/(R cos φ₀).
    c = 1250.0 / R
    _, lon = win.xy_to_latlon(np.array([win.half_km]), np.array([0.0]))
    expected_dlon = math.degrees(
        math.atan2(math.sin(c), math.cos(math.radians(60.0)) * math.cos(c))
    )
    assert float(lon[0]) == pytest.approx(expected_dlon, abs=1e-6)


def test_window_accepts_polar_centres() -> None:
    win = region_window(85.0, 0.0, 1000.0, R)
    lon_grid, lat_grid = win.out_latlon(33)
    assert np.all(np.abs(lat_grid) <= 90.0 + 1e-9)
    # The north edge of a 1 000 km window centred at 85°N comes within a
    # degree of the pole — a region the old equirect crop refused outright.
    assert float(np.max(lat_grid)) > 89.0
    assert float(lat_grid[16, 16]) == pytest.approx(85.0, abs=1e-9)


def test_window_accepts_antimeridian_centres() -> None:
    win = region_window(0.0, 179.0, 2500.0, R)
    lon_grid, lat_grid = win.out_latlon(33)
    # Normalised longitudes straddle ±180°; round-tripping the plane recovers
    # the same points (no longitude unwrap tearing at the seam).
    assert float(lon_grid.min()) < -170.0 and float(lon_grid.max()) > 170.0
    x, y = win.out_xy(33)
    x_back, y_back = win.latlon_to_xy(lat_grid, lon_grid)
    assert np.allclose(x, x_back, atol=1e-6)
    assert np.allclose(y, y_back, atol=1e-6)


def test_window_rejects_bad_span() -> None:
    with pytest.raises(RegionWindowError, match="positive"):
        region_window(0.0, 0.0, 0.0, R)
    with pytest.raises(RegionWindowError, match="antipode"):
        region_window(0.0, 0.0, math.pi * R, R)


# ---------------------------------------------------------------------------
# Pack round-trip on a synthetic mesh
# ---------------------------------------------------------------------------


def _xyz(lon: float, lat: float) -> tuple[float, float, float]:
    """Unit-sphere coordinates for (lon, lat) in degrees."""
    lam, phi = math.radians(lon), math.radians(lat)
    return (math.cos(phi) * math.cos(lam), math.sin(phi), math.cos(phi) * math.sin(lam))


def _patch_mesh() -> CVTMesh:
    """A 4-cell land plateau at (0, 0) surrounded by far-away ocean cells.

    The plateau's four cells share elevation and climate values, so the
    Delaunay-interpolated height reads exactly 1234 m on the plateau interior
    (any convex combination of equals is exact).
    """
    plateau = [  # (id, lon, lat) — convex hull spans ±3° around the origin
        (0, 0.0, 0.0),
        (8, 3.0, 2.0),
        (9, -3.0, 2.0),
        (10, 0.0, -3.0),
    ]
    cells = []
    for cid, lon, lat in plateau:
        x, y, z = _xyz(lon, lat)
        cells.append(
            VoronoiCell(
                id=cid,
                lon=lon,
                lat=lat,
                elevation=1234.0,
                water_class="land",
                crust_type="continental",
                x=x,
                y=y,
                z=z,
                temperature_C=24.5,
                precipitation_mm=2100.0,
                koppen_class="Af",
                biome="tropical_rainforest",
                ice_thickness_m=0.0,
            )
        )
    fillers = [  # (id, lon, lat): all ≥ 40° away from the island
        (1, 45.0, 45.0),
        (2, -45.0, 45.0),
        (3, 45.0, -45.0),
        (4, -45.0, -45.0),
        (5, 180.0, 0.0),
        (6, 0.0, 89.0),
        (7, 0.0, -89.0),
    ]
    for cid, lon, lat in fillers:
        x, y, z = _xyz(lon, lat)
        cells.append(
            VoronoiCell(
                id=cid,
                lon=lon,
                lat=lat,
                elevation=-4000.0,
                water_class="ocean",
                crust_type="oceanic",
                x=x,
                y=y,
                z=z,
            )
        )
    return CVTMesh(seed=42, num_cells=len(cells), cells=cells, adjacency={})


def test_pack_roundtrip(tmp_path: Path) -> None:
    mesh = _patch_mesh()
    meta = export_region_pack(
        mesh,
        center_lat=0.0,
        center_lon=0.0,
        span_km=500.0,  # ±2.25° → the plateau owns the whole window
        radius_km=R,
        grid_width=W,
        grid_height=H,
        elev_min_m=-5000.0,
        elev_max_m=2000.0,
        sea_level_m=0.0,
        out_dir=tmp_path,
        source={"world": "test", "planet": "p"},
        out_res=64,
    )

    height = np.load(tmp_path / "height.meters.npy")
    assert height.dtype == np.float32
    assert height.shape == (meta["grid"]["h"], meta["grid"]["w"])
    # The island is the nearest cell everywhere in this small window.
    assert float(height.min()) == pytest.approx(1234.0)

    # Land island → ocean_fraction 0; heights drive the colour PNG too.
    assert meta["ocean_fraction"] == pytest.approx(0.0)
    assert (tmp_path / "color.png").exists()
    assert (tmp_path / "height.png").exists()

    written = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
    assert written["source"]["world"] == "test"
    assert written["elevation_m"]["min"] == pytest.approx(1234.0)


def test_pack_is_deterministic(tmp_path: Path) -> None:
    mesh = _patch_mesh()
    kwargs = dict(
        center_lat=10.0,
        center_lon=20.0,
        span_km=500.0,
        radius_km=R,
        grid_width=W,
        grid_height=H,
        elev_min_m=-5000.0,
        elev_max_m=2000.0,
        sea_level_m=0.0,
        out_res=64,
    )
    export_region_pack(mesh, out_dir=tmp_path / "a", **kwargs)  # type: ignore[arg-type]
    export_region_pack(mesh, out_dir=tmp_path / "b", **kwargs)  # type: ignore[arg-type]
    names = sorted(p.name for p in (tmp_path / "a").iterdir())
    assert len(names) > 4  # the climate channels must actually be there
    for name in names:
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes(), name


# ---------------------------------------------------------------------------
# Climate channels (satellite-imagery contract)
# ---------------------------------------------------------------------------


def _clim_kwargs() -> dict[str, object]:
    return dict(
        center_lat=0.0,
        center_lon=0.0,
        span_km=500.0,
        radius_km=R,
        grid_width=W,
        grid_height=H,
        elev_min_m=-5000.0,
        elev_max_m=2000.0,
        sea_level_m=0.0,
        out_res=64,  # small grids keep the pack tests fast
    )


def test_climate_channels_roundtrip(tmp_path: Path) -> None:
    meta = export_region_pack(
        _patch_mesh(),
        out_dir=tmp_path,
        **(_clim_kwargs()),  # type: ignore[arg-type]
    )
    assert meta["pack_version"] == 4
    assert meta["projection"] == "azimuthal_equidistant"
    assert meta["extent_km"] == {"x": 500.0, "y": 500.0}
    assert meta["km_per_px"] == {"x": 500.0 / 64, "y": 500.0 / 64}
    assert "pixel_box" not in meta

    # The island owns the whole window → every channel is uniform on its value.
    precip = np.load(tmp_path / "precipitation.mm.npy")
    assert precip.dtype == np.float32
    assert float(precip[0, 0]) == pytest.approx(2100.0)
    assert meta["climate"]["precipitation_mm"]["png_range"] == pytest.approx([0.0, 2100.0])
    assert meta["climate"]["precipitation_mm"]["missing"] == 0

    temp = np.load(tmp_path / "temperature.C.npy")
    assert float(temp[0, 0]) == pytest.approx(24.5)

    ice = np.load(tmp_path / "ice.m.npy")
    assert float(ice.max()) == pytest.approx(0.0)

    koppen_codes = np.load(tmp_path / "koppen.codes.npy")
    assert koppen_codes.dtype == np.uint8
    assert int(koppen_codes[0, 0]) == 1

    # The written meta.json is the real contract — legends serialise with
    # string keys there.
    written = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
    assert written["climate"]["koppen"]["legend"] == {"1": "Af"}
    assert written["climate"]["biome"]["legend"] == {"1": "tropical_rainforest"}

    for name in (
        "precipitation.mm.png",
        "temperature.C.png",
        "ice.m.png",
        "koppen.png",
        "biome.png",
    ):
        assert (tmp_path / name).exists(), name


def test_climate_channels_missing_values(tmp_path: Path) -> None:
    # Ocean filler cells sit 45° away (~6 670 km along the diagonal → AEQ
    # x = y ≈ 4 718 km); an 11 000 km span (half 5 500 km) covers them.
    mesh = _patch_mesh()
    meta = export_region_pack(
        mesh,
        out_dir=tmp_path,
        **{**_clim_kwargs(), "span_km": 11_000.0},  # type: ignore[arg-type]
    )
    h, w = meta["grid"]["h"], meta["grid"]["w"]
    precip = np.load(tmp_path / "precipitation.mm.npy")
    assert precip.shape == (h, w)
    assert np.isnan(precip).sum() == meta["climate"]["precipitation_mm"]["missing"] > 0
    koppen_missing = int((np.load(tmp_path / "koppen.codes.npy") == 0).sum())
    assert koppen_missing == meta["climate"]["koppen"]["missing"] > 0


def test_climate_channels_disabled(tmp_path: Path) -> None:
    meta = export_region_pack(
        _patch_mesh(),
        out_dir=tmp_path,
        include_climate=False,
        **(_clim_kwargs()),  # type: ignore[arg-type]
    )
    assert "climate" not in meta
    assert not (tmp_path / "precipitation.mm.npy").exists()
    assert (tmp_path / "height.meters.npy").exists()


def test_headwaters_mask(tmp_path: Path) -> None:
    # Plateau: T 24.5 °C, P 2100 mm.  Hamon PET at 24.5 °C ≈ 1350 mm/yr
    # → P > PET → the whole window is headwater.
    export_region_pack(
        _patch_mesh(),
        out_dir=tmp_path,
        **(_clim_kwargs()),  # type: ignore[arg-type]
    )
    import json as _json

    from PIL import Image

    hw = np.asarray(Image.open(tmp_path / "headwaters.png"))
    assert hw.dtype == np.uint16  # 16-bit: Gaea misreads 8-bit mask PNGs
    assert (hw == 65535).all()
    written = _json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
    assert written["climate"]["headwaters"]["count"] == hw.shape[0] * hw.shape[1]

    # A dry variant (P = 100 mm ≪ PET) must produce no headwaters.
    mesh = _patch_mesh()
    for c in mesh.cells:
        if c.water_class == "land":
            c.precipitation_mm = 100.0
    export_region_pack(mesh, out_dir=tmp_path / "dry", **(_clim_kwargs()))  # type: ignore[arg-type]
    hw_dry = np.asarray(Image.open(tmp_path / "dry" / "headwaters.png"))
    assert (hw_dry == 0).all()


def test_glacier_mask(tmp_path: Path) -> None:
    """glacier.mask.png = ice_thickness>0 ∪ biome==ice; empty when neither."""
    from PIL import Image

    # Baseline: rainforest biome + zero ice → empty mask.
    export_region_pack(_patch_mesh(), out_dir=tmp_path, **(_clim_kwargs()))  # type: ignore[arg-type]
    assert not np.asarray(Image.open(tmp_path / "glacier.mask.png")).any()

    # One plateau cell switched to the ice biome → mask covers the window.
    mesh = _patch_mesh()
    mesh.cells[0].biome = "ice"
    meta = export_region_pack(mesh, out_dir=tmp_path / "icy", **(_clim_kwargs()))  # type: ignore[arg-type]
    gm = np.asarray(Image.open(tmp_path / "icy" / "glacier.mask.png"))
    assert gm.any()
    assert meta["climate"]["glacier_mask"]["count"] == int((gm > 0).sum())


def test_gaea_seafloor_clamp(tmp_path: Path) -> None:
    # Window covers the island (1234 m) and deep ocean fillers (−4000 m).
    meta = export_region_pack(
        _patch_mesh(),
        out_dir=tmp_path,
        **{**_clim_kwargs(), "span_km": 11_000.0, "include_climate": False},  # type: ignore[arg-type]
    )
    assert (tmp_path / "height.gaea.png").exists()
    # Clamped range: −400 m floor, true land max.
    assert meta["height_gaea_png_range_m"] == pytest.approx([-400.0, 1234.0])
    assert meta["seafloor_clamp_m"] == -400.0
    # The untouched twin keeps the true −4000 m floor.
    assert meta["height_png_range_m"] == pytest.approx([-4000.0, 1234.0])


def test_gaea_clamp_noop_when_shallow(tmp_path: Path) -> None:
    # Region with no cell deeper than the clamp → range keeps the true min.
    meta = export_region_pack(
        _patch_mesh(),
        out_dir=tmp_path,
        **(_clim_kwargs()),  # type: ignore[arg-type]  # 500 km window: island only
    )
    assert meta["height_gaea_png_range_m"] == pytest.approx([1234.0, 1234.0])


# ---------------------------------------------------------------------------
# Runoff channel (the hydrology legs' water-balance weight)
# ---------------------------------------------------------------------------


def test_runoff_channel_known_answer(tmp_path: Path) -> None:
    # Monthly climate built from the plateau's own values (constant months):
    # the channel must equal the Turc–Pike curve on the same forcing,
    # cell-exact on the plateau (the island owns the window).
    from dreamulator.engine.climate_physics import (
        annual_runoff_turc_pike,
        potential_evapotranspiration_hamon,
    )

    mesh = _patch_mesh()
    n = mesh.num_cells
    t12 = np.full((n, 12), 24.5)
    p12 = np.full((n, 12), 2100.0 / 12.0)  # mm/month basis: the annual sum is 2100
    meta = export_region_pack(
        mesh,
        out_dir=tmp_path,
        climate_monthly=(t12, p12),
        **(_clim_kwargs()),  # type: ignore[arg-type]
    )
    runoff = np.load(tmp_path / "runoff.mm.npy")
    assert runoff.dtype == np.float32
    pet_annual = potential_evapotranspiration_hamon(t12[:1], 365.25 / 12.0)
    expected = float(annual_runoff_turc_pike(p12[:1].sum(axis=1), pet_annual)[0])
    # Humid forcing (P 2100 vs PET ≈ 1348): R/P ≈ 0.46, between P − PET and P.
    assert 700.0 < expected < 2100.0
    assert np.allclose(runoff, expected, rtol=2e-3)  # fp32 channel tolerance
    clim = meta["climate"]["runoff_mm"]
    assert clim["demand_model"] == "hamon-1961"
    assert "Turc-Pike" in clim["criterion"]
    assert clim["png_range"][0] == 0.0
    assert (tmp_path / "runoff.mm.png").exists()
    # Lake freeze regime rides the same monthly input: a warm year (24.5 °C
    # in every month) freezes no month.
    lake_ice = np.load(tmp_path / "lake_ice.months.npy")
    assert lake_ice.dtype == np.uint8
    assert int(lake_ice.max()) == 0
    assert meta["climate"]["lake_ice_months"]["perennial_threshold"] == 12


def test_runoff_channel_absent_without_monthly(tmp_path: Path) -> None:
    meta = export_region_pack(
        _patch_mesh(),
        out_dir=tmp_path,
        **(_clim_kwargs()),  # type: ignore[arg-type]
    )
    assert not (tmp_path / "runoff.mm.npy").exists()
    assert not (tmp_path / "lake_ice.months.npy").exists()
    assert "runoff_mm" not in meta["climate"]
    assert "lake_ice_months" not in meta["climate"]
    # The rest of the climate block still ran.
    assert (tmp_path / "headwaters.png").exists()


# ---------------------------------------------------------------------------
# Planet radius resolution (branch maps lack the hand-written map.yaml)
# ---------------------------------------------------------------------------


def test_read_radius_km_falls_back_to_root_map(tmp_path: Path) -> None:
    from dreamulator.map.region_export import read_radius_km

    root_map = tmp_path / "maps" / "satellite_x"
    root_map.mkdir(parents=True)
    (root_map / "map.yaml").write_text("radius_km: 6816.97\n", encoding="utf-8")
    branch_map = tmp_path / "branches" / "gcm-1" / "maps" / "satellite_x"
    branch_map.mkdir(parents=True)

    # Branch maps dir has build products but no map.yaml → root wins.
    assert read_radius_km(branch_map, tmp_path) == 6816.97
    # Without the world root the caller cannot resolve it → Earth default.
    assert read_radius_km(branch_map) == 6371.0


def test_read_radius_km_own_map_wins_over_root(tmp_path: Path) -> None:
    from dreamulator.map.region_export import read_radius_km

    root_map = tmp_path / "maps" / "satellite_x"
    root_map.mkdir(parents=True)
    (root_map / "map.yaml").write_text("radius_km: 6816.97\n", encoding="utf-8")
    own_map = tmp_path / "other"
    own_map.mkdir()
    (own_map / "map.yaml").write_text("radius_km: 3000.0\n", encoding="utf-8")

    assert read_radius_km(own_map, tmp_path) == 3000.0
