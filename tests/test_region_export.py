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
    """A land island at (0, 0) surrounded by far-away ocean cells."""
    cells = [
        VoronoiCell(
            id=0,
            lon=0.0,
            lat=0.0,
            elevation=1234.0,
            water_class="land",
            crust_type="continental",
            x=_xyz(0.0, 0.0)[0],
            y=_xyz(0.0, 0.0)[1],
            z=_xyz(0.0, 0.0)[2],
        )
    ]
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
        span_km=500.0,  # ±2.25° → the island owns the whole window
        radius_km=R,
        grid_width=W,
        grid_height=H,
        elev_min_m=-5000.0,
        elev_max_m=2000.0,
        sea_level_m=0.0,
        out_dir=tmp_path,
        source={"world": "test", "planet": "p"},
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
    )
    export_region_pack(mesh, out_dir=tmp_path / "a", **kwargs)  # type: ignore[arg-type]
    export_region_pack(mesh, out_dir=tmp_path / "b", **kwargs)  # type: ignore[arg-type]
    for name in ("meta.json", "height.meters.npy", "height.png", "color.png"):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes(), name


def test_polar_guard_constant() -> None:
    assert MAX_ABS_LAT == 75.0
