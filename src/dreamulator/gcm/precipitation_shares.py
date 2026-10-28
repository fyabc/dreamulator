"""Area-weighted monthly component shares with a fixed native parent budget.

The caller supplies a complete partition of one parent, including land and sea,
and a conservative long-term component baseline. High-frequency rainfall is
split into states supported by the physical response and unresolved states.
Only the supported share of the long-term quota is redistributed. Convective
and large-scale components, parents and phase months are closed independently.

This is a numerical closure, not a weather-domain model. The intensive weighted
simplex projection minimizes area-weighted squared changes; splitting a constant
child into smaller pieces leaves the answer unchanged. Its denominators are
parent component totals, so locally dry or weak-rain children stay well defined.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]


@dataclass(frozen=True)
class ComponentDriver:
    """Accumulated depths (mm) on the same parent partition and phase month."""

    supported_baseline_mm: FloatArray
    supported_adjusted_mm: FloatArray
    unresolved_mm: FloatArray


@dataclass(frozen=True)
class ShareClosure:
    """Closed depths and diagnostics for one parent component budget."""

    depth_mm: FloatArray
    supported_quota_fraction: float
    negative_candidate_mass_fraction: float
    projection_rms: float
    budget_residual_mm_m2: float
    reason: str


def _vector(value: FloatArray, shape: tuple[int, ...], name: str) -> FloatArray:
    result = np.asarray(value, dtype=np.float64)
    if result.shape != shape or not np.isfinite(result).all() or (result < 0).any():
        raise ValueError(f"{name} must be finite, non-negative and match the parent partition")
    return result


def _project(values: FloatArray, weights: FloatArray) -> FloatArray:
    """Project intensive shares onto x >= 0 and sum(area_weight*x) = 1."""
    order = np.argsort(values)[::-1]
    ordered, weight = values[order], weights[order]
    cumulative_weight = np.cumsum(weight)
    threshold = (np.cumsum(weight * ordered) - 1) / cumulative_weight
    active = np.flatnonzero(ordered > threshold)
    projected: FloatArray = np.asarray(
        np.maximum(values - float(threshold[active[-1]]), 0.0), dtype=np.float64
    )
    # Enforce the constraint at floating-point summation precision.
    projected /= np.dot(weights, projected)
    return projected


def monthly_component_shares(
    long_term_mm: FloatArray,
    area_m2: FloatArray,
    *,
    parent_area_m2: float,
    parent_budget_mm_m2: float,
    driver: ComponentDriver | None,
) -> ShareClosure:
    """Close one month's component without moving water across parents.

    ``parent_budget_mm_m2`` is water depth times area, before converting mm to m.
    Areas must cover the complete native parent and the long-term input must
    already integrate to its quota. The operation preserves that baseline
    exactly when the response is zero or supported high-frequency information
    is absent. It does not repair an unconservative spatial remapping.

    Supported and unresolved quotas use their shares of the high-frequency
    baseline precipitation. The unresolved quota retains the long-term spatial
    baseline. Applying a representative event-year share to a long-term month
    is the closure hypothesis and requires separate observational acceptance.
    """
    area = np.asarray(area_m2, dtype=np.float64)
    if area.ndim != 1 or not area.size or not np.isfinite(area).all() or (area <= 0).any():
        raise ValueError("area_m2 must contain positive finite areas for the complete parent")
    baseline = _vector(long_term_mm, area.shape, "long_term_mm")
    if not np.isfinite(parent_area_m2) or parent_area_m2 <= 0:
        raise ValueError("parent_area_m2 must be positive and finite")
    if not np.isfinite(parent_budget_mm_m2) or parent_budget_mm_m2 < 0:
        raise ValueError("parent_budget_mm_m2 must be non-negative and finite")
    total_area = float(area.sum())
    baseline_budget = float(np.dot(area, baseline))
    tolerance = 32 * np.finfo(np.float64).eps
    if abs(total_area - parent_area_m2) > tolerance * parent_area_m2:
        raise ValueError("child areas must cover the complete native parent")
    if abs(baseline_budget - parent_budget_mm_m2) > tolerance * parent_budget_mm_m2:
        raise ValueError("the long-term baseline must already conserve the native parent budget")

    def unchanged(reason: str, fraction: float = 0.0) -> ShareClosure:
        return ShareClosure(
            baseline.copy(), fraction, 0.0, 0.0, baseline_budget - parent_budget_mm_m2, reason
        )

    if parent_budget_mm_m2 == 0:
        return unchanged("zero-parent-budget")
    if driver is None:
        return unchanged("missing-high-frequency-driver")
    supported = _vector(driver.supported_baseline_mm, area.shape, "supported_baseline_mm")
    adjusted = _vector(driver.supported_adjusted_mm, area.shape, "supported_adjusted_mm")
    unresolved = _vector(driver.unresolved_mm, area.shape, "unresolved_mm")
    weight = area / total_area
    supported_mean = float(np.dot(weight, supported))
    unresolved_mean = float(np.dot(weight, unresolved))
    if supported_mean == 0:
        return unchanged("no-supported-precipitation")
    scale = max(supported_mean, unresolved_mean)
    fraction = (supported_mean / scale) / (supported_mean / scale + unresolved_mean / scale)
    if np.array_equal(supported, adjusted):
        return unchanged("zero-response", fraction)
    adjusted_mean = float(np.dot(weight, adjusted))
    if adjusted_mean == 0:
        return unchanged("no-adjusted-spatial-shape", fraction)
    mean = parent_budget_mm_m2 / total_area
    proposed = baseline / mean + adjusted / adjusted_mean - supported / supported_mean
    projected = _project(proposed, weight)
    depth = (1 - fraction) * baseline + fraction * mean * projected
    return ShareClosure(
        depth,
        fraction,
        float(np.dot(weight, np.maximum(-proposed, 0))),
        float(np.sqrt(np.dot(weight, (projected - proposed) ** 2))),
        float(np.dot(area, depth)) - parent_budget_mm_m2,
        "projected-supported-shares",
    )
