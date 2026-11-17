"""Research mean-flow depth from independently supplied width, slope and resistance.

The wide-channel Manning approximation uses hydraulic radius approximately equal
to mean depth. HyG (Enzminger et al., 2024) applies it to width/depth ratios above 10.
The resistance coefficient is empirical and uses SI units, s / m**(1/3).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from numpy.typing import NDArray


def manning_mean_depth(
    discharge_m3s: NDArray[np.float64],
    width_m: NDArray[np.float64],
    slope_m_m: NDArray[np.float64],
    manning_n_s_m13: float,
) -> NDArray[np.float64]:
    """Solve Q = W D**(5/3) sqrt(S) / n for a wide, approximately uniform flow.

    Zero discharge returns zero depth. Flowing cells require positive width and
    slope; missing or flat slopes are not replaced with an arbitrary minimum.
    This estimates mean water depth, not bankfull depth or terrain incision.
    """
    q, w, s = (np.asarray(a, dtype=np.float64) for a in (discharge_m3s, width_m, slope_m_m))
    if q.shape != w.shape or q.shape != s.shape:
        raise ValueError("Discharge, width and slope must have matching shapes.")
    if any(not np.isfinite(a).all() or (a < 0).any() for a in (q, w, s)):
        raise ValueError("Discharge, width and slope must be finite and nonnegative.")
    if not np.isfinite(manning_n_s_m13) or manning_n_s_m13 <= 0:
        raise ValueError("Manning resistance must be finite and positive.")
    active = q > 0
    if np.any(active & ((w <= 0) | (s <= 0))):
        raise ValueError("Positive discharge requires positive width and slope.")
    depth = np.zeros_like(q)
    depth[active] = (manning_n_s_m13 * q[active] / (w[active] * np.sqrt(s[active]))) ** (3.0 / 5.0)
    return depth


def fit_manning_resistance(
    discharge_m3s: NDArray[np.float64],
    width_m: NDArray[np.float64],
    observed_mean_depth_m: NDArray[np.float64],
    slope_m_m: NDArray[np.float64],
) -> float:
    """Fit one geometric-mean resistance on calibration observations only.

    Width may be an independently predicted width; in that case this fitted
    coefficient also absorbs its errors and is an effective resistance.
    """
    q, w, d, s = (
        np.asarray(a, dtype=np.float64)
        for a in (discharge_m3s, width_m, observed_mean_depth_m, slope_m_m)
    )
    if q.ndim != 1 or q.size < 2 or any(a.shape != q.shape for a in (w, d, s)):
        raise ValueError("Calibration needs matching one-dimensional observations.")
    if any(not np.isfinite(a).all() or (a <= 0).any() for a in (q, w, d, s)):
        raise ValueError("Calibration observations must be finite and positive.")
    inferred_n = w * d ** (5.0 / 3.0) * np.sqrt(s) / q
    return float(np.exp(np.mean(np.log(inferred_n))))
