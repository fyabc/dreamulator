"""Fortran patch set for ExoPlaSim: anchors, idempotence and the routing Courant rule."""

from __future__ import annotations

import numpy as np
import pytest

from dreamulator.gcm import fortran_patches as fp


def test_patch_id_is_stable_and_content_sensitive() -> None:
    assert fp.patch_id() == fp.patch_id()
    changed = (fp.PATCHES[0], fp.FortranPatch("x", "landmod.f90", "a", "b"))
    assert fp.patch_id(changed) != fp.patch_id()


def test_apply_patch_requires_unique_anchor() -> None:
    patch = fp.FortranPatch("t", "f.f90", "OLD\n", "NEW\n")
    assert fp.apply_patch_text("a\nOLD\nb\n", patch) == "a\nNEW\nb\n"
    with pytest.raises(RuntimeError, match="0 times"):
        fp.apply_patch_text("a\nb\n", patch)
    with pytest.raises(RuntimeError, match="2 times"):
        fp.apply_patch_text("OLD\nOLD\n", patch)


def test_patched_text_no_longer_contains_anchor() -> None:
    for patch in fp.PATCHES:
        assert patch.anchor not in patch.replacement
        assert patch.replacement.count("dreamulator patch") == 1


def test_restart_patch_only_clears_storage_on_cold_start() -> None:
    restart = next(p for p in fp.PATCHES if p.name == "restart-river")
    body = restart.replacement
    assert "if (nrestart == 0) then" in body
    assert body.index("if (nrestart == 0)") < body.index("driver(:)=0.")


def _outflow_rate(u: np.ndarray, v: np.ndarray, land: np.ndarray) -> np.ndarray:
    """Python transcription of roffrate (rows = latitudes north to south)."""
    north = np.zeros_like(v)
    north[1:] = v[:-1]
    rate = (
        np.maximum(u, 0)
        + np.maximum(-np.roll(u, 1, axis=1), 0)
        + np.maximum(-v, 0)
        + np.maximum(north, 0)
    )
    return np.where(land > 0, rate, 0.0)


def _mkradv_step(store: np.ndarray, u: np.ndarray, v: np.ndarray, dt: float) -> np.ndarray:
    """One explicit upwind step on equal-area cells, mirroring mkradv's face rules."""
    flux = np.zeros_like(store)
    east = np.roll(store, -1, axis=1)
    fu = np.where(u > 0, u * store, u * east)  # positive: west cell drains east
    flux -= fu
    flux += np.roll(fu, 1, axis=1)
    south = np.zeros_like(store)
    south[:-1] = store[1:]
    fv = np.where(v < 0, -v * store, -v * south)  # positive: north cell drains south
    flux -= fv
    flux[1:] += fv[:-1]
    return store + dt * flux


def test_substep_count_from_courant_number_keeps_storage_non_negative() -> None:
    rng = np.random.default_rng(7)
    nlat, nlon = 8, 16
    u = rng.normal(0.0, 1e-3, (nlat, nlon))
    v = rng.normal(0.0, 1e-3, (nlat, nlon))
    v[-1] = 0.0
    land = np.ones((nlat, nlon))
    dt = 2400.0
    rate = _outflow_rate(u, v, land).max()
    assert dt * rate > 2.0  # the unpatched step is in the growing regime
    store0 = rng.uniform(0.0, 1e-3, (nlat, nlon))

    plain = store0.copy()
    for _ in range(50):
        plain = _mkradv_step(plain, u, v, dt)
    assert plain.min() < 0.0

    nsub = max(1, int(np.ceil(dt * rate)))
    sub = store0.copy()
    for _ in range(50 * nsub):
        sub = _mkradv_step(sub, u, v, dt / nsub)
    assert sub.min() >= -1e-18
    np.testing.assert_allclose(sub.sum(), store0.sum(), rtol=1e-12)
