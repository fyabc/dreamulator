"""Physical units, observed closure fitting, and unchanged sediment transport."""

from __future__ import annotations

import numpy as np
import pytest

from dreamulator.map import _surface_process_kernels as kernels
from dreamulator.map.surface_process import SurfaceProcessParams, run_surface_process
from scripts.geology.channel_geometry import (
    MeanChannelCalibration,
    fit_mean_channel_geometry,
    mean_channel_geometry,
    reference_accumulation_to_discharge,
)


def test_mean_geometry_conserves_discharge_and_marks_extrapolation() -> None:
    calibration = MeanChannelCalibration(5.0, 0.5, 1.0, 100.0)
    q = np.array([0.0, 0.1, 1.0, 100.0, 1000.0])
    result = mean_channel_geometry(q, calibration)
    np.testing.assert_allclose(result.width_m * result.mean_depth_m * result.velocity_m_s, q)
    assert result.outside_calibration.tolist() == [True, True, False, False, True]
    assert result.velocity_m_s[0] == 0


def test_discharge_conversion_preserves_the_same_physical_catchment() -> None:
    coarse = reference_accumulation_to_discharge(np.array([400.0]), 180.0, 300.0)
    fine = reference_accumulation_to_discharge(np.array([1600.0]), 90.0, 300.0)
    np.testing.assert_array_equal(coarse, fine)
    assert coarse[0] == pytest.approx(400 * 180**2 * 0.3 / (365.25 * 86400))


def test_calibration_rejects_missing_or_nonphysical_observations() -> None:
    with pytest.raises(ValueError, match="matching"):
        fit_mean_channel_geometry(np.ones(2), np.ones(3), np.ones(2))
    with pytest.raises(ValueError, match="positive"):
        fit_mean_channel_geometry(np.array([0.0, 1.0]), np.ones(2), np.ones(2))
    with pytest.raises(ValueError, match="nonnegative"):
        mean_channel_geometry(np.array([np.nan]), MeanChannelCalibration(5, 0.5, 1, 100))


@pytest.mark.parametrize("pit,ice", [(False, False), (True, False), (True, True)])
def test_export_inventory_leaves_surface_and_budgets_identical(pit: bool, ice: bool) -> None:
    yy, xx = np.mgrid[:40, :40]
    height = np.minimum(xx * 35.0, 800.0) + 2 * np.sin(yy / 3)
    height[:, :2] = -100.0
    if pit:
        height -= 180 * np.exp(-((xx - 27) ** 2 + (yy - 20) ** 2) / 18)
    land = height > 0
    erodible = ~((xx > 23) & (xx < 30) & (yy > 15) & (yy < 23)) if ice else land
    climate = [np.full(height.shape, x) for x in (600.0, 1200.0, 15.0)]
    kwargs = {"anchor": height, "erodible": erodible}
    params = SurfaceProcessParams(fixed_steps=8, parallel_flood=False)
    baseline = run_surface_process(height, land, *climate, 720.0, 1e5, params, **kwargs)
    traced = run_surface_process(
        height, land, *climate, 720.0, 1e5, params, track_sediment_exports=True, **kwargs
    )
    assert traced.ledger == baseline.ledger
    np.testing.assert_array_equal(traced.h, baseline.h)
    np.testing.assert_array_equal(traced.discharge_m3_yr, baseline.discharge_m3_yr)
    assert traced.exported_sediment_m3 is not None
    assert baseline.exported_sediment_m3 is None
    assert traced.exported_sediment_m3.min() >= 0
    assert traced.exported_sediment_m3.sum() / 1e9 == pytest.approx(
        traced.ledger["exported_km3"], rel=1e-12, abs=1e-12
    )


def test_export_destinations_keep_frame_ice_and_missing_receiver_separate() -> None:
    # Four independent reaches have distinct absorbing boundaries. No deposition
    # is allowed, so their known source volumes must arrive in separate accounts.
    n = 8
    receiver = np.array([4, 5, 6, -1, -1, -1, -1, -1], dtype=np.int64)
    mutable = np.array([True] * 4 + [False] * 4)
    routed = np.array([True] * 4 + [False] * 4)
    codes = np.array([3, 3, 3, 3, 0, 1, 2, 3], dtype=np.int8)
    sources = np.array([2.0, 3.0, 5.0, 7.0, 0, 0, 0, 0])
    exports = np.zeros((4, n))
    _river, _lake, total, _playa = kernels._route_sediment(
        np.arange(n, dtype=float),
        np.arange(n - 1, -1, -1, dtype=np.int64),
        receiver,
        np.ones(n),
        sources,
        np.zeros(n, dtype=np.int64),
        np.array([0], dtype=np.int64),
        np.empty(0, dtype=np.int64),
        np.empty(0),
        np.zeros(n, dtype=bool),
        np.empty(0, dtype=bool),
        mutable,
        routed,
        0.0,
        1.0,
        1.0,
        np.full(n, np.inf),
        exports,
        codes,
    )
    assert total == 17
    np.testing.assert_array_equal(exports.sum(axis=1), [2, 3, 5, 7])


def test_optional_inventory_checks_memory_before_allocating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dreamulator.utils import resources

    monkeypatch.setattr(resources, "available_memory_bytes", lambda: 1)
    height = np.ones((8, 8))
    with pytest.raises(MemoryError, match="sediment-export"):
        run_surface_process(
            height,
            height > 0,
            height,
            height,
            height,
            90,
            1,
            track_sediment_exports=True,
        )
    np.testing.assert_array_equal(height, np.ones((8, 8)))
