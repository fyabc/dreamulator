"""Local continuous descent trajectories on one interpolated elevation surface.

The vector-grid idea follows GRASS r.flow and Mitasova/Hofierka (1993).
This original pilot uses an exact nodal cubic spline and midpoint descent;
it neither copies r.flow nor changes the accepted D-infinity water budget.
Spline critical points are reported as stops, never bridged by a D8 fallback.
Coordinates are floating-point (row, column), in grid-cell units.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.interpolate import RectBivariateSpline
from scipy.ndimage import distance_transform_edt

MIN_PROGRESS_PX = 1e-4


@dataclass
class Flowline:
    """A descent path, its sampled height, and its explicit termination reason."""

    points_rc: np.ndarray
    height_m: np.ndarray
    status: str
    sink_cell: tuple[int, int] | None
    rejected_steps: int


class CubicSurface:
    """Interpolate nodal heights exactly; expose gradient of the same surface."""

    def __init__(self, height_m: np.ndarray) -> None:
        h = np.asarray(height_m, dtype=np.float64)
        if h.ndim != 2 or min(h.shape) < 4 or max(h.shape) > 1024:
            raise ValueError("local surface requires 4 to 1024 rows and columns")
        self.valid = np.isfinite(h)
        if not self.valid.any():
            raise ValueError("surface has no finite height samples")
        self.shape = h.shape
        self.all_valid = bool(self.valid.all())
        if not self.all_valid:
            # Only supplies finite interpolation coefficients. Traces stop before
            # entering a missing-data stencil; filled holes remain explicit barriers.
            nearest = distance_transform_edt(
                ~self.valid, return_distances=False, return_indices=True
            )
            h = h[tuple(nearest)]
        self.spline = RectBivariateSpline(
            np.arange(h.shape[0]), np.arange(h.shape[1]), h, kx=3, ky=3, s=0
        )
        self.derivative_row = self.spline.partial_derivative(1, 0)
        self.derivative_col = self.spline.partial_derivative(0, 1)

    def supported(self, point: np.ndarray) -> bool:
        row, col = point
        nr, nc = self.shape
        if not (0 <= row <= nr - 1 and 0 <= col <= nc - 1):
            return False
        if self.all_valid:
            return True
        r, c = int(np.floor(row)), int(np.floor(col))
        return bool(
            self.valid[max(0, r - 1) : min(nr, r + 3), max(0, c - 1) : min(nc, c + 3)].all()
        )

    def height(self, point: np.ndarray) -> float:
        return float(self.spline.ev(point[0], point[1]).item())

    def gradient(self, point: np.ndarray) -> np.ndarray:
        return np.array(
            [
                self.derivative_row(point[0], point[1], grid=False).item(),
                self.derivative_col(point[0], point[1], grid=False).item(),
            ],
            dtype=np.float64,
        )


def first_absorber(
    start: np.ndarray, end: np.ndarray, absorbing: np.ndarray
) -> tuple[np.ndarray, tuple[int, int]] | None:
    """Intersect the segment with pixel boxes and return the first absorbing entry."""
    delta = end - start
    cuts = [0.0, 1.0]
    for axis in range(2):
        if delta[axis] == 0:
            continue
        lo, hi = sorted((start[axis], end[axis]))
        edges = np.arange(np.floor(lo) - 1, np.ceil(hi) + 1) + 0.5
        cuts.extend(float(t) for t in (edges - start[axis]) / delta[axis] if 0 < t < 1)
    cuts = sorted(set(cuts))
    for t0, t1 in zip(cuts[:-1], cuts[1:], strict=True):
        point = start + ((t0 + t1) / 2) * delta
        row, col = np.floor(point + 0.5).astype(int)
        if not (0 <= row < absorbing.shape[0] and 0 <= col < absorbing.shape[1]):
            continue
        if absorbing[row, col]:
            return start + t0 * delta, (int(row), int(col))
    # An endpoint exactly on an entering pixel edge is a valid first touch.
    row, col = np.floor(end + 0.5).astype(int)
    if 0 <= row < absorbing.shape[0] and 0 <= col < absorbing.shape[1] and absorbing[row, col]:
        return end.copy(), (int(row), int(col))
    return None


def trace(
    surface: CubicSurface,
    seed_rc: tuple[float, float],
    absorbing: np.ndarray,
    *,
    step_px: float = 0.5,
    max_steps: int = 10000,
) -> Flowline:
    """Follow normalized negative gradient; accept only strictly descending steps."""
    if absorbing.shape != surface.shape:
        raise ValueError("absorbing shape differs from surface")
    if not np.isfinite(step_px) or not (0 < step_px <= 0.5):
        raise ValueError("step_px must be finite, positive and at most half a pixel")
    if max_steps < 1:
        raise ValueError("max_steps must be positive")
    point = np.array(seed_rc, dtype=np.float64)
    if point.shape != (2,) or not np.isfinite(point).all() or not surface.supported(point):
        raise ValueError("seed is outside supported height samples")
    points, heights = [point.copy()], [surface.height(point)]
    rejected, status, sink = 0, "step_limit", None
    row, col = np.floor(point + 0.5).astype(int)
    if absorbing[row, col]:
        return Flowline(np.array(points), np.array(heights), "absorbed", (int(row), int(col)), 0)
    for _ in range(max_steps):
        grad = surface.gradient(point)
        norm = float(np.linalg.norm(grad))
        if not np.isfinite(norm) or norm <= 1e-12:
            status = "critical_point"
            break
        accepted = False
        attempted_support = False
        for halving in range(20):
            step = step_px / 2**halving
            if step < MIN_PROGRESS_PX:
                break
            middle = point - grad / norm * (step / 2)
            if not surface.supported(middle):
                rejected += 1
                continue
            gmid = surface.gradient(middle)
            normmid = float(np.linalg.norm(gmid))
            if not np.isfinite(normmid) or normmid <= 1e-12:
                rejected += 1
                continue
            candidate = point - step * gmid / normmid
            hit = first_absorber(point, candidate, absorbing)
            if hit is not None:
                candidate, sink_candidate = hit
            if not surface.supported(candidate):
                rejected += 1
                continue
            attempted_support = True
            znew = surface.height(candidate)
            if not znew < heights[-1]:
                rejected += 1
                continue
            points.append(candidate.copy())
            heights.append(znew)
            point = candidate
            accepted = True
            if hit is not None:
                status, sink = "absorbed", sink_candidate
            break
        if status == "absorbed":
            break
        if not accepted:
            status = "stagnated" if attempted_support else "missing_support"
            break
    return Flowline(np.asarray(points), np.asarray(heights), status, sink, rejected)


def export_segments(path: Flowline, shape: tuple[int, int], spacing_km: float) -> np.ndarray:
    """Preserve subpixel coordinates in the existing (N,2,2) east/north vector format."""
    if not np.isfinite(spacing_km) or spacing_km <= 0:
        raise ValueError("spacing_km must be finite and positive")
    pts = np.column_stack(
        (path.points_rc[:, 1] * spacing_km, (shape[0] - 1 - path.points_rc[:, 0]) * spacing_km)
    )
    return np.stack((pts[:-1], pts[1:]), axis=1)
