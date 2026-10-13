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
    MAX_ABS_LAT,
    RegionWindowError,
    export_region_pack,
    region_window,
)

R = 6371.0
W, H = 360, 180  # ~1°/px grid keeps the arithmetic obvious


# ---------------------------------------------------------------------------
# Window math
# ---------------------------------------------------------------------------


def test_window_equator_square_in_km() -> None:
    win = region_window(0.0, 0.0, 2500.0, R, W, H)
    # 2500 km at 111.19 km/deg → ±11.24° on both axes at the equator.
    assert win.lon_min == pytest.approx(-11.24, abs=0.05)
    assert win.lat_min == pytest.approx(-11.24, abs=0.05)
    # Snapped pixel box stays square in kilometres — the floor/ceil snapping
    # adds at most one pixel per side, so allow just over ±2 px total.
    kx = win.grid_w * win.km_per_px_x
    ky = win.grid_h * win.km_per_px_y
    assert kx == pytest.approx(2500.0, abs=2.1 * win.km_per_px_x)
    assert ky == pytest.approx(2500.0, abs=2.1 * win.km_per_px_y)


def test_window_high_latitude_widens_in_longitude() -> None:
    w_eq = region_window(0.0, 0.0, 2500.0, R, W, H)
    w_60 = region_window(60.0, 0.0, 2500.0, R, W, H)
    # cos(60°) = 0.5 → degrees-per-km double, pixels shrink to half the km size.
    assert w_60.km_per_px_x == pytest.approx(w_eq.km_per_px_x / 2.0, rel=0.01)
    assert w_60.grid_w == pytest.approx(2.0 * w_eq.grid_w, abs=2)
    assert w_60.grid_h == pytest.approx(w_eq.grid_h, abs=2)


def test_window_rejects_polar() -> None:
    with pytest.raises(RegionWindowError, match="75"):
        region_window(80.0, 0.0, 1000.0, R, W, H)
    # A huge span from the equator also reaches the polar band.
    with pytest.raises(RegionWindowError, match="lat"):
        region_window(0.0, 0.0, 30_000.0, R, W, H)


def test_window_rejects_antimeridian() -> None:
    with pytest.raises(RegionWindowError, match="antimeridian"):
        region_window(0.0, 179.0, 2500.0, R, W, H)


def test_window_rejects_bad_span() -> None:
    with pytest.raises(RegionWindowError, match="positive"):
        region_window(0.0, 0.0, 0.0, R, W, H)


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
    assert meta["pack_version"] == 3

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
    # Ocean filler cells sit at ±45°; an 11 000 km span (half ≈ 49.5°) covers
    # them while staying inside the polar-band guard.
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


def test_polar_guard_constant() -> None:
    assert MAX_ABS_LAT == 75.0
