"""Tiled parallel Priority-Flood: the serial fill exactly, and a valid drainage tree."""

from __future__ import annotations

import numpy as np
import pytest

from dreamulator.map import prog_erosion as pe
from dreamulator.map._parallel_flood import priority_flood_tiled


def _surfaces() -> list[tuple[str, np.ndarray, np.ndarray]]:
    rng = np.random.default_rng(7)
    out = []
    for h, w in ((61, 47), (130, 157)):
        dem = rng.normal(size=(h, w)).cumsum(0) * 0.3 + rng.normal(size=(h, w)) * 2
        out.append((f"rough {h}x{w}", dem, dem > -4))
        quant = np.round(dem)  # integer metres: wide exact flats and tied slopes
        out.append((f"integer {h}x{w}", quant, quant > -4))
    return out


@pytest.mark.parametrize("tile", [8, 16, 50, 1000])
def test_fill_equals_the_serial_fill(tile: int) -> None:
    for name, dem, land in _surfaces():
        ref, _o, _r = pe.priority_flood(dem, land, eps=0.0)
        filled, _order, _rec = priority_flood_tiled(dem, land, 0.0, tile=tile)
        assert np.array_equal(filled, ref.reshape(dem.shape)), name


@pytest.mark.parametrize("tile", [8, 33])
def test_drainage_tree_is_valid(tile: int) -> None:
    eps = 1e-4
    for name, dem, land in _surfaces():
        filled, order, rec = priority_flood_tiled(dem, land, eps, tile=tile)
        fill0, _o, _r = pe.priority_flood(dem, land, eps=0.0)
        inner = land.copy()
        inner[0, :] = inner[-1, :] = False
        inner[:, 0] = inner[:, -1] = False
        k = int((order >= 0).sum())
        assert k == int(inner.sum()), name  # every land cell once
        assert np.array_equal(np.sort(order[:k]), np.flatnonzero(inner)), name
        assert (order[k:] == -1).all()
        pos = np.full(dem.size, -1)
        pos[order[:k]] = np.arange(k)
        r = rec[order[:k]]
        assert (r >= 0).all(), name  # every land cell drains
        r_land = inner.reshape(-1)[r]
        assert (pos[r[r_land]] < np.flatnonzero(r_land)).all(), name  # receiver first
        f = filled.reshape(-1)
        assert (f[r] < f[order[:k]]).all(), name  # strictly downhill on the eps surface
        # the eps surface is the serial recursion f = max(fill, f(receiver) + eps)
        np.testing.assert_allclose(
            f[order[:k]], np.maximum(fill0.reshape(-1)[order[:k]], f[r] + eps), atol=1e-9
        )
        assert (rec[~inner.reshape(-1)] == -1).all()


def test_parallel_flag_routes_to_the_tiled_variant() -> None:
    _name, dem, land = _surfaces()[0]
    a = pe.priority_flood(dem, land, parallel=True)
    b = priority_flood_tiled(dem, land, pe.PF_EPS_M)
    for x, y in zip(a, b, strict=True):
        assert np.array_equal(x, y)
    with pytest.raises(ValueError, match="breach"):
        pe.priority_flood(dem, land, breach=True, parallel=True)


def test_result_does_not_depend_on_the_thread_count() -> None:
    import numba

    _name, dem, land = _surfaces()[3]
    before = numba.get_num_threads()
    try:
        numba.set_num_threads(1)
        one = priority_flood_tiled(dem, land, pe.PF_EPS_M, tile=16)
        numba.set_num_threads(max(1, min(4, numba.config.NUMBA_NUM_THREADS)))
        many = priority_flood_tiled(dem, land, pe.PF_EPS_M, tile=16)
    finally:
        numba.set_num_threads(before)
    for x, y in zip(one, many, strict=True):
        assert np.array_equal(x, y)
