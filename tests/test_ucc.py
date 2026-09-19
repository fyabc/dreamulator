"""L0 tests for the UCC continuous descriptors (ucc-review §4.2 / §7 第一步).

These pin the *semantics* (time weights, rate→total, supply–demand edge cases,
applicability states) so the descriptors do not silently drop valid fields or
smuggle infinities into a class.
"""

from __future__ import annotations

import numpy as np
import pytest

from dreamulator.map.ucc import (
    MISSING_INPUT,
    NO_POSITIVE_DEMAND,
    NOT_APPLICABLE,
    VALID,
    compute_descriptors,
)


def test_equal_bins_and_weighted_mean() -> None:
    # Unequal bins: the duration-weighted mean must use dt, not the plain mean.
    d = compute_descriptors(
        t=np.array([10.0, 20.0]),
        p_rate=np.array([1.0, 1.0]),
        dt=np.array([1.0, 3.0]),
    )
    assert d.t_mean == pytest.approx((10.0 * 1 + 20.0 * 3) / 4.0)  # 17.5, not 15.0
    assert d.t_range == 10.0
    assert d.p_total == pytest.approx(1.0 * 4.0)  # Σ P·Δt


def test_constant_temperature_keeps_precipitation_seasonality() -> None:
    # 恒温 (constant T): temperature stats are valid and flat, but the
    # precipitation concentration (seasonality) is preserved (§7 完成条件).
    t = np.full(4, 15.0)
    p = np.array([0.0, 0.0, 10.0, 10.0])  # strongly seasonal precipitation
    d = compute_descriptors(t, p)
    assert d.t_mean == 15.0
    assert d.t_range == 0.0
    assert d.concentration is not None and d.concentration > 0.0


def test_missing_pet_does_not_drop_temperature() -> None:
    # 缺需求 (§4.4): AI/deficit are missing, but temperature/precipitation stay.
    d = compute_descriptors(np.array([10.0, 20.0]), np.array([1.0, 1.0]), et_rate=None)
    assert d.ai is None and d.ai_status == MISSING_INPUT
    assert d.deficit is None and d.deficit_status == MISSING_INPUT
    assert d.t_mean == 15.0 and d.p_total == 2.0  # valid fields survive


def test_supply_demand_edge_cases() -> None:
    # P=0, Eref>0 → AI=0 (valid).
    d = compute_descriptors(np.array([10.0]), np.array([0.0]), et_rate=np.array([1.0]))
    assert d.ai == 0.0 and d.ai_status == VALID
    # P=Eref=0 → AI undefined.
    d = compute_descriptors(np.array([10.0]), np.array([0.0]), et_rate=np.array([0.0]))
    assert d.ai is None and d.ai_status == NOT_APPLICABLE
    # P>0, Eref=0 → "no positive demand", not inf.
    d = compute_descriptors(np.array([10.0]), np.array([1.0]), et_rate=np.array([0.0]))
    assert d.ai is None and d.ai_status == NO_POSITIVE_DEMAND


def test_seasonal_deficit() -> None:
    # P >= Eref everywhere → deficit 0 (no same-period shortfall).
    d = compute_descriptors(np.array([10.0]), np.array([2.0]), et_rate=np.array([1.0]))
    assert d.deficit == 0.0 and d.deficit_status == VALID
    # P=0, Eref=1 → deficit 1 (full shortfall).
    d = compute_descriptors(np.array([10.0]), np.array([0.0]), et_rate=np.array([1.0]))
    assert d.deficit == 1.0


def test_concentration_uniform_and_undefined() -> None:
    # Uniform precipitation → concentration 0.
    d = compute_descriptors(np.array([10.0] * 4), np.array([1.0] * 4))
    assert d.concentration == pytest.approx(0.0)
    # No precipitation → concentration undefined (not 0).
    d = compute_descriptors(np.array([10.0] * 4), np.array([0.0] * 4))
    assert d.concentration is None


def test_below_freeze_fraction() -> None:
    d = compute_descriptors(np.array([-5.0, -1.0, 5.0, 15.0]), np.array([1.0] * 4))
    assert d.t_below_frac == pytest.approx(0.5)  # two of four bins below 0°C
