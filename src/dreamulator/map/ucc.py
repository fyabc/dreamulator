"""UCC continuous climate descriptors (ucc-review §4.2 — "freeze semantics").

The first step of UCC-01 is to *freeze the semantics* of a climate sequence
without committing to a classification alphabet: define the time/flux contract
(§4.1) and compute a few independent, complementary *continuous* descriptions
(§4.2).  Classification profiles and their thresholds are a later step (§4.3).

Key review constraints honoured here:

- Time is first: bins carry durations ``dt``; nothing is hard-wired to 12 equal
  "months" (§4.1).  Precipitation is a *rate*, and totals are ``Σ P_i·Δt_i``.
- Missing demand / missing precipitation must NOT drop the other valid fields —
  a field is either ``"valid"`` or carries an applicability status (§4.4).
- ``P=0, Eref>0`` → AI=0; ``P=Eref=0`` → AI undefined; ``P>0, Eref=0`` →
  "no positive reference demand", never an ``inf`` smuggled into a wet class.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Applicability states (§4.4).  A None value is only meaningful when paired with
# a non-``valid`` status — the field is absent/undefined, not the whole record.
VALID = "valid"
MISSING_INPUT = "missing_input"  # e.g. no PET model → AI not computable
NOT_APPLICABLE = "not_applicable"  # e.g. P=Eref=0 → AI undefined
NO_POSITIVE_DEMAND = "no_positive_demand"  # P>0, Eref=0 → not a finite wet/dry ratio


@dataclass
class ClimateDescriptors:
    """The continuous descriptions of one climate sequence (§4.2)."""

    # Temperature — duration-weighted over the window.
    t_mean: float  # °C, Σ w_i·t_i
    t_min: float  # °C, min bin-mean
    t_max: float  # °C, max bin-mean
    t_range: float  # °C, t_max − t_min (explicitly a *range*, not half-amplitude)
    t_below_frac: float  # time-fraction of bin means below the threshold (§4.2 note)

    # Precipitation — mean rate and window total.
    p_mean_rate: float  # mean flux over the window
    p_total: float  # Σ P_i·Δt_i

    # Supply–demand: AI = P_total / Eref_total over the *same* window.
    ai: float | None
    ai_status: str

    # Same-period seasonal deficit: Σ max(Eref_i − P_i, 0)·Δt_i / Σ Eref_i·Δt_i.
    deficit: float | None
    deficit_status: str

    # Precipitation concentration C_TV = 0.5 Σ |q_i − w_i| (None when P_total=0).
    concentration: float | None


def compute_descriptors(
    t: np.ndarray,
    p_rate: np.ndarray,
    et_rate: np.ndarray | None = None,
    dt: np.ndarray | None = None,
    *,
    freeze_threshold_c: float = 0.0,
) -> ClimateDescriptors:
    """Compute the continuous descriptors from a climate sequence.

    Args:
        t: (M,) bin-mean temperature (°C).
        p_rate: (M,) precipitation *rate* (mm per unit time) — not cumulative.
        et_rate: (M,) reference-demand *rate* (mm per unit time); None = no PET.
        dt: (M,) positive bin durations; None = equal bins.
        freeze_threshold_c: threshold for the time-fraction-below statistic.

    Returns:
        ClimateDescriptors — undefined fields carry a status and a None value.
    """
    t = np.asarray(t, dtype=np.float64)
    p_rate = np.asarray(p_rate, dtype=np.float64)
    m = t.shape[0]
    dt = np.ones(m, dtype=np.float64) if dt is None else np.asarray(dt, dtype=np.float64)
    if dt.shape != (m,) or p_rate.shape != (m,):
        raise ValueError("t, p_rate, dt must share the same bin count")

    w = dt / dt.sum()  # time weights

    t_mean = float(np.sum(w * t))
    t_min = float(np.min(t))
    t_max = float(np.max(t))
    t_range = t_max - t_min
    t_below_frac = float(np.sum(w[t < freeze_threshold_c]))

    p_total = float(np.sum(p_rate * dt))
    p_mean_rate = float(np.sum(w * p_rate))

    ai, ai_status = _supply_demand(p_rate, et_rate, dt)
    deficit, deficit_status = _seasonal_deficit(p_rate, et_rate, dt)
    concentration = _concentration(p_rate, dt, p_total)

    return ClimateDescriptors(
        t_mean=t_mean,
        t_min=t_min,
        t_max=t_max,
        t_range=t_range,
        t_below_frac=t_below_frac,
        p_mean_rate=p_mean_rate,
        p_total=p_total,
        ai=ai,
        ai_status=ai_status,
        deficit=deficit,
        deficit_status=deficit_status,
        concentration=concentration,
    )


def _supply_demand(
    p_rate: np.ndarray, et_rate: np.ndarray | None, dt: np.ndarray
) -> tuple[float | None, str]:
    p_total = float(np.sum(p_rate * dt))
    if et_rate is None:
        return None, MISSING_INPUT
    et_total = float(np.sum(np.asarray(et_rate, dtype=np.float64) * dt))
    if et_total <= 0.0:
        # P>0, Eref=0 → "no positive demand"; P=Eref=0 → undefined.  Neither is a
        # finite AI; do not smuggle an inf into a wet class (§4.4).
        return None, NO_POSITIVE_DEMAND if p_total > 0.0 else NOT_APPLICABLE
    return p_total / et_total, VALID


def _seasonal_deficit(
    p_rate: np.ndarray, et_rate: np.ndarray | None, dt: np.ndarray
) -> tuple[float | None, str]:
    if et_rate is None:
        return None, MISSING_INPUT
    et_rate = np.asarray(et_rate, dtype=np.float64)
    et_total = float(np.sum(et_rate * dt))
    if et_total <= 0.0:
        return None, NOT_APPLICABLE
    deficit = np.sum(np.maximum(et_rate - p_rate, 0.0) * dt) / et_total
    return float(deficit), VALID


def _concentration(
    p_rate: np.ndarray, dt: np.ndarray, p_total: float
) -> float | None:
    if p_total <= 0.0:
        return None  # undefined when there is no precipitation (§4.2)
    q = p_rate * dt / p_total  # precipitation mass fraction per bin
    w = dt / dt.sum()  # uniform-rate reference
    return float(0.5 * np.sum(np.abs(q - w)))
