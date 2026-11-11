"""Effective incision time of orogen relief, from a replay of the engine's own orogen profile.

The incision clock of a mountain cell starts when its surface stands at its
present height, not at collision onset (author ruling 2026-11-08,
canvas-erosion-deposition proposal §3.3).  The orogen contract gives each
convergent segment its onset age and retained shortening; replaying
``orogen_profile.orogen_relief`` with the shortening scaled back linearly in
time (``f(τ) = max(0, 1 − τ / onset)`` at τ Myr before present) gives the
relief history of every cell.  With n = 1 stream power the cumulative
incision scales with elevation, so the time at full present height is

    T_eff = ∫ min(h(τ) / h(0), 1) dτ.

A capped plateau interior reaches its height early (old surface); margins
added by later widening are young; a still-rising wedge counts its
time-weighted fraction.  Cells without orogen relief (below ``h_min_m``) are
platform and get NaN; the caller treats them as steady state.  The forearc
shift of Andean crests is omitted: it moves crests inland without changing the
ratio h/h0 the replay uses.

Epistemic class: approximation (linear shortening history; the contract
records the integral, not the time series).
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from .models import CVTMesh
    from .orogen_contract import OrogenContract

#: Cells with less present orogen relief than this are platform (m).
PLATFORM_RELIEF_M = 100.0


def effective_incision_time_myr(
    mesh: CVTMesh,
    contract: OrogenContract,
    radius_km: float,
    gravity_m_s2: float,
    base_m: float,
    *,
    dtau_myr: float = 1.0,
    h_min_m: float = PLATFORM_RELIEF_M,
) -> np.ndarray:
    """Per-cell effective incision time (Myr) in mesh-cell order; NaN on platform cells."""
    from .orogen_profile import orogen_relief

    # retained shortening is per contact cell; a cell shared by segments follows the oldest
    onset: dict[int, float] = {}
    for seg in contract.segments:
        for cid in seg.cell_ids:
            onset[int(cid)] = max(onset.get(int(cid), 0.0), float(seg.onset_age_myr))
    retained0 = dict(contract.retained_km)
    tmax = max((v for v in onset.values() if v > 0), default=0.0)
    n = len(mesh.cells)
    if tmax <= 0.0:
        return np.full(n, np.nan)
    taus = np.arange(0.0, tmax + dtau_myr, dtau_myr)
    h0: np.ndarray | None = None
    integral = np.zeros(n)
    prev: np.ndarray | None = None
    for i, tau in enumerate(taus):
        c = copy.copy(contract)
        c.retained_km = {
            k: v * max(0.0, 1.0 - tau / onset[k]) if onset.get(k, 0.0) > 0 else 0.0
            for k, v in retained0.items()
        }
        relief, _cap = orogen_relief(mesh, c, radius_km, gravity_m_s2, base_m)
        if h0 is None:
            h0 = np.asarray(relief, dtype=np.float64)
        ratio = np.where(h0 >= h_min_m, np.minimum(relief / np.maximum(h0, 1e-9), 1.0), 0.0)
        if prev is not None:  # trapezoidal rule, as numpy.trapezoid over the τ grid
            integral += 0.5 * (prev + ratio) * (taus[i] - taus[i - 1])
        prev = ratio
    assert h0 is not None
    return np.asarray(np.where(h0 >= h_min_m, integral, np.nan))
