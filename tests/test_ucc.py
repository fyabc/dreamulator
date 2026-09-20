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
    OUT_OF_DOMAIN,
    PROFILE_V0,
    VALID,
    ClimateDescriptors,
    classify_v0,
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


def test_demand_out_of_domain_below_freeze() -> None:
    # No bin above freezing (ice cap): the Hamon reference demand — an empirical
    # liquid-water formula — leaves its validity domain; AI/deficit report
    # out_of_domain instead of a meaningless inflated ratio (南极「湿润」反例).
    t_cold = np.array([-30.0, -10.0])
    p_some = np.array([5.0, 5.0])
    et_tiny = np.array([0.1, 0.2])
    d = compute_descriptors(t_cold, p_some, et_rate=et_tiny)
    assert d.ai is None and d.ai_status == OUT_OF_DOMAIN
    assert d.deficit is None and d.deficit_status == OUT_OF_DOMAIN
    # t_max exactly at the freeze threshold → still in domain (strict <).
    d = compute_descriptors(np.array([-10.0, 0.0]), p_some, et_rate=et_tiny)
    assert d.ai is not None and d.ai_status == VALID
    # missing PET is the stronger statement — the gate must not overwrite it.
    d = compute_descriptors(t_cold, p_some, et_rate=None)
    assert d.ai_status == MISSING_INPUT and d.deficit_status == MISSING_INPUT


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


# ---------------------------------------------------------------------------
# L1: classification profile v0 (ucc-review §4.3 / §7 第二步 — frozen
# thresholds, boundary behaviour, partial validity)
# ---------------------------------------------------------------------------


def _desc(t: list[float], p: list[float], et: list[float] | None = None) -> ClimateDescriptors:
    et_arr = None if et is None else np.array(et)
    return compute_descriptors(np.array(t), np.array(p), et_arr)


def test_v0_thermal_band_boundaries() -> None:
    # t_max exactly 10 °C is NOT polar (strict <); t_min exactly −3 is NOT cold;
    # t_min exactly 18 IS tropical.
    d = _desc([9.0, 10.0], [1.0, 1.0], [2.0, 2.0])  # t_max=10, t_min=9
    assert classify_v0(d, is_land=True).thermal == "temperate"
    d = _desc([-3.0, 15.0], [1.0, 1.0], [2.0, 2.0])  # t_min=-3 boundary
    assert classify_v0(d, is_land=True).thermal == "temperate"
    d = _desc([18.0, 25.0], [1.0, 1.0], [2.0, 2.0])  # t_min=18 boundary
    assert classify_v0(d, is_land=True).thermal == "tropical"
    d = _desc([-30.0, 9.9], [1.0, 1.0], [0.5, 0.5])  # t_max<10 → polar
    assert classify_v0(d, is_land=True).thermal == "polar"
    d = _desc([-10.0, 15.0], [1.0, 1.0], [1.0, 1.0])  # t_min<−3, t_max≥10 → cold
    assert classify_v0(d, is_land=True).thermal == "cold"


def test_v0_supply_band_boundaries() -> None:
    # AI = P/Eref; boundaries 0.5 and 1.0 (digitize semantics: edge → upper band).
    d = _desc([20.0, 20.0], [0.5, 0.5], [1.0, 1.0])  # AI = 0.5 → transitional
    assert classify_v0(d, is_land=True).supply == "transitional"
    d = _desc([20.0, 20.0], [1.0, 1.0], [1.0, 1.0])  # AI = 1.0 → humid
    assert classify_v0(d, is_land=True).supply == "humid"
    d = _desc([20.0, 20.0], [0.4, 0.4], [1.0, 1.0])  # AI = 0.4 → arid
    assert classify_v0(d, is_land=True).supply == "arid"


def test_v0_ocean_supply_not_applicable() -> None:
    # Ocean keeps its thermal band; the land wet/dry axis is not applicable.
    d = _desc([20.0, 22.0], [0.1, 0.1], [1.0, 1.0])  # would be arid on land
    c = classify_v0(d, is_land=False)
    assert c.thermal == "tropical"
    assert c.supply is None and c.supply_status == NOT_APPLICABLE
    assert c.label == "tropical"
    assert c.water_stress is None


def test_v0_partial_validity_propagates() -> None:
    # Missing PET on land: temperature band survives, supply carries the status.
    d = _desc([5.0, 15.0], [1.0, 1.0], et=None)
    c = classify_v0(d, is_land=True)
    assert c.thermal == "temperate"
    assert c.supply is None and c.supply_status == MISSING_INPUT
    assert c.water_stress is None
    # P=Eref=0 → AI not_applicable propagates (not a fake "arid").
    d = _desc([-5.0, 15.0], [0.0, 0.0], [0.0, 0.0])
    c = classify_v0(d, is_land=True)
    assert c.thermal == "cold"
    assert c.supply is None and c.supply_status == NOT_APPLICABLE
    # Ice cap (no month above freezing): demand out of domain → supply carries it.
    d = _desc([-30.0, -10.0], [5.0, 5.0], [0.1, 0.2])
    c = classify_v0(d, is_land=True)
    assert c.thermal == "polar"
    assert c.supply is None and c.supply_status == OUT_OF_DOMAIN
    assert c.label == "polar"


def test_v0_modifiers() -> None:
    # continental: t_range ≥ 25 °C.
    d = _desc([-5.0, 20.0], [1.0, 1.0], [1.0, 1.0])  # range 25 → boundary True
    assert classify_v0(d, is_land=True).continental is True
    d = _desc([-5.1, 20.0], [1.0, 1.0], [1.0, 1.0])  # range 25.1 → True
    assert classify_v0(d, is_land=True).continental is True
    d = _desc([0.0, 24.9], [1.0, 1.0], [1.0, 1.0])  # range 24.9 → False
    assert classify_v0(d, is_land=True).continental is False
    # water_stress: deficit ≥ 0.5 (P half of Eref, all in the same bins).
    d = _desc([20.0, 20.0], [0.5, 0.5], [1.0, 1.0])  # deficit = 0.5 → True
    assert classify_v0(d, is_land=True).water_stress is True
    d = _desc([20.0, 20.0], [2.0, 2.0], [1.0, 1.0])  # deficit = 0 → False
    assert classify_v0(d, is_land=True).water_stress is False


def test_v0_constant_temperature_classifies() -> None:
    # 恒温 (§3.1): thermal band still applies; continental is False (range 0).
    d = _desc([25.0] * 4, [1.0] * 4, [0.5] * 4)
    c = classify_v0(d, is_land=True)
    assert c.thermal == "tropical"
    assert c.supply == "humid"  # AI = 2
    assert c.continental is False
    assert c.profile == PROFILE_V0
