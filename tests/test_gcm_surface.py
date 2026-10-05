"""Tests for the ExoPlaSim .sra surface-file writer (dreamulator.gcm.surface)."""

from __future__ import annotations

import numpy as np
import pytest

from dreamulator.gcm.surface import (
    KCODE_LAND_MASK,
    gaussian_latitudes,
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
