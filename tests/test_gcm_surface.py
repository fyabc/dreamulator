"""Tests for the ExoPlaSim .sra surface-file writer (dreamulator.gcm.surface)."""

from __future__ import annotations

import numpy as np
import pytest

from dreamulator.gcm.surface import (
    KCODE_LAND_MASK,
    gaussian_latitudes,
    grid_land_elevation,
    land_mask_from_mesh,
    uniform_longitudes,
    write_sra,
)


def test_gaussian_latitudes_ascending_symmetric() -> None:
    lat = gaussian_latitudes(32)
    assert lat.shape == (32,)
    assert np.all(np.diff(lat) > 0)
    assert np.allclose(lat, -lat[::-1], atol=1e-6)
    assert abs(lat[-1]) < 90.0  # Gaussian nodes exclude the poles


def test_uniform_longitudes() -> None:
    lon = uniform_longitudes(64)
    assert lon[0] == 0.0
    assert np.allclose(np.diff(lon), 360.0 / 64)


def test_write_sra_header_and_north_first_order(tmp_path) -> None:
    nlat, nlon = 4, 8
    # latitude-ascending field: value = latitude index (0 = south)
    field = np.repeat(np.arange(nlat, dtype=float)[:, None], nlon, axis=1)
    out = tmp_path / "N004_surf_0172.sra"
    write_sra(out, KCODE_LAND_MASK, field, nlat, nlon)

    text = out.read_text(encoding="utf-8")
    lines = text.strip().split("\n")
    header = [int(x) for x in lines[0].split()]
    assert header == [KCODE_LAND_MASK, 0, 20170927, 0, nlon, nlat, 0, 0]
    values = [float(v) for line in lines[1:] for v in line.split()]
    assert len(values) == nlat * nlon
    # file order is north → south: first row of values = northernmost latitude
    first_row = values[:nlon]
    assert np.allclose(first_row, nlat - 1)
    assert np.allclose(values[-nlon:], 0.0)


def test_write_sra_rejects_wrong_shape(tmp_path) -> None:
    with pytest.raises(ValueError, match="field shape"):
        write_sra(tmp_path / "x.sra", KCODE_LAND_MASK, np.zeros((3, 3)), 4, 8)


def test_land_mask_from_earth_mesh() -> None:
    import pathlib

    mesh = (
        pathlib.Path(__file__).resolve().parents[1]
        / "data"
        / "worlds"
        / "earth"
        / "maps"
        / "planet_earth"
        / "cvt_mesh.msgpack.gz"
    )
    if not mesh.exists():
        pytest.skip("earth root mesh not present")
    mask, frac = land_mask_from_mesh(mesh, 32, 64)
    assert mask.shape == (32, 64)
    assert set(np.unique(mask)) <= {0.0, 1.0}
    # Earth's land fraction is ~0.29; nearest-cell T21 regrid should be close
    assert 0.2 < frac < 0.4
    # Northern hemisphere mid-latitudes are land-heavy, southern ocean-heavy
    lat = gaussian_latitudes(32)
    nh = mask[lat > 20].mean()
    sh = mask[lat < -40].mean()
    assert nh > sh


def _synthetic_cells(nlat: int, nlon: int) -> dict[str, np.ndarray]:
    """Four cells per Gaussian box, placed inside the box around its centre."""
    glat = gaussian_latitudes(nlat)
    glon = uniform_longitudes(nlon)
    lat, lon = np.meshgrid(glat, glon, indexing="ij")
    offsets = [(-0.3, -1.0), (-0.3, 1.0), (0.3, -1.0), (0.3, 1.0)]
    return {
        "lat": np.concatenate([(lat + dy).ravel() for dy, _ in offsets]),
        "lon": np.concatenate([((lon + dx) % 360.0).ravel() for _, dx in offsets]),
    }


def test_grid_land_elevation_area_weighted_land_only() -> None:
    nlat, nlon = 4, 8
    cells = _synthetic_cells(nlat, nlon)
    n = cells["lat"].size
    per_box = n // 4
    # In every box: two land cells (1000 m with area 1, 3000 m with area 3),
    # one ocean cell at −4000 m and one land cell below sea level (−50 m, area 0).
    elevation = np.concatenate([np.full(per_box, 1000.0), np.full(per_box, 3000.0),
                                np.full(per_box, -4000.0), np.full(per_box, -50.0)])  # fmt: skip
    area = np.concatenate([np.ones(per_box), np.full(per_box, 3.0),
                           np.ones(per_box), np.full(per_box, 1e-9)])  # fmt: skip
    is_land = np.concatenate([np.ones(per_box, bool), np.ones(per_box, bool),
                              np.zeros(per_box, bool), np.ones(per_box, bool)])  # fmt: skip
    mask = np.ones((nlat, nlon))
    mask[0, :] = 0.0  # southernmost row is ocean in the model mask
    elev = grid_land_elevation(cells["lat"], cells["lon"], area, elevation, is_land, mask)
    assert elev.shape == (nlat, nlon)
    # (1·1000 + 3·3000) / 4 = 2500 m; the ocean cell and the clipped depression do not count
    assert np.allclose(elev[1:], 2500.0, atol=1e-3)
    assert np.allclose(elev[0], 0.0)


def test_grid_land_elevation_fills_land_boxes_without_land_cells() -> None:
    nlat, nlon = 4, 8
    cells = _synthetic_cells(nlat, nlon)
    n = cells["lat"].size
    elevation = np.full(n, 500.0)
    is_land = np.zeros(n, bool)
    is_land[0] = True  # a single land cell somewhere
    mask = np.ones((nlat, nlon))  # but the model mask calls every box land
    elev = grid_land_elevation(cells["lat"], cells["lon"], np.ones(n), elevation, is_land, mask)
    assert np.allclose(elev, 500.0)
