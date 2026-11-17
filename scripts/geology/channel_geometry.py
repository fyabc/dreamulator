"""Research estimates for channel dimensions at mean annual discharge.

Leopold & Maddock (1953), USGS Professional Paper 252, pp. 16 and 54.
Coefficients must be calibrated on observations at the same discharge statistic.
These are mean-flow dimensions, not bankfull geometry or an incision model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from numpy.typing import NDArray

SECONDS_PER_EARTH_YEAR = 365.25 * 86400.0


@dataclass(frozen=True)
class MeanChannelCalibration:
    """One observational geometry closure, with explicit calibration limits."""

    width_at_1_m3s_m: float
    depth_at_1_m3s_m: float
    min_discharge_m3s: float
    max_discharge_m3s: float

    def __post_init__(self) -> None:
        values = np.array(
            [
                self.width_at_1_m3s_m,
                self.depth_at_1_m3s_m,
                self.min_discharge_m3s,
                self.max_discharge_m3s,
            ]
        )
        if not np.isfinite(values).all() or (values <= 0).any():
            raise ValueError("Calibration dimensions and discharge limits must be positive.")
        if self.max_discharge_m3s < self.min_discharge_m3s:
            raise ValueError("The discharge calibration range must be ordered.")


@dataclass(frozen=True)
class MeanChannelGeometry:
    width_m: NDArray[np.float64]
    mean_depth_m: NDArray[np.float64]
    velocity_m_s: NDArray[np.float64]
    outside_calibration: NDArray[np.bool_]


def fit_mean_channel_geometry(
    discharge_m3s: NDArray[np.float64],
    width_m: NDArray[np.float64],
    mean_depth_m: NDArray[np.float64],
) -> MeanChannelCalibration:
    """Fit log intercepts with the published downstream exponents 0.5 and 0.4."""
    q, w, d = (np.asarray(a, dtype=np.float64) for a in (discharge_m3s, width_m, mean_depth_m))
    if q.ndim != 1 or q.size < 2 or q.shape != w.shape or q.shape != d.shape:
        raise ValueError("Calibration needs matching one-dimensional observations.")
    if any(not np.isfinite(a).all() or (a <= 0).any() for a in (q, w, d)):
        raise ValueError("Calibration observations must be finite and positive.")
    return MeanChannelCalibration(
        float(np.exp(np.mean(np.log(w) - 0.5 * np.log(q)))),
        float(np.exp(np.mean(np.log(d) - 0.4 * np.log(q)))),
        float(q.min()),
        float(q.max()),
    )


def mean_channel_geometry(
    discharge_m3s: NDArray[np.float64], calibration: MeanChannelCalibration
) -> MeanChannelGeometry:
    """Estimate mean-flow width and depth; continuity determines velocity."""
    q = np.asarray(discharge_m3s, dtype=np.float64)
    if not np.isfinite(q).all() or (q < 0).any():
        raise ValueError("Discharge must be finite and nonnegative.")
    w = calibration.width_at_1_m3s_m * q**0.5
    d = calibration.depth_at_1_m3s_m * q**0.4
    velocity = np.divide(q, w * d, out=np.zeros_like(q), where=q > 0)
    outside = (q < calibration.min_discharge_m3s) | (q > calibration.max_discharge_m3s)
    return MeanChannelGeometry(w, d, velocity, outside)


def reference_accumulation_to_discharge(
    accumulation: NDArray[np.float64], pixel_m: float, runoff_reference_mm: float
) -> NDArray[np.float64]:
    """Convert the canvas's annual reference-runoff cells into m³/s.

    This follows its existing projected pixel-area convention. It does not
    replace that convention with spherical area or infer event-scale floods.
    """
    if not np.isfinite(pixel_m) or pixel_m <= 0:
        raise ValueError("The pixel spacing must be finite and positive.")
    if not np.isfinite(runoff_reference_mm) or runoff_reference_mm <= 0:
        raise ValueError("The runoff reference must be finite and positive.")
    a = np.asarray(accumulation, dtype=np.float64)
    if not np.isfinite(a).all() or (a < 0).any():
        raise ValueError("Accumulation must be finite and nonnegative.")
    return np.asarray(a * (runoff_reference_mm * 1e-3 * pixel_m**2 / SECONDS_PER_EARTH_YEAR))
