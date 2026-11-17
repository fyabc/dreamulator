"""Continuous descent on a conforming piecewise-linear DEM, local extension.

Tarboton's eight overlapping facets determine nodal directions, not a global
TIN. This separate geometry candidate splits each square along the diagonal
with lexicographically lower endpoint heights. Facet, edge and vertex events
are solved explicitly. Equal-height paths use the prepared D8 flat receivers.
No spline, uphill bridge, or arbitrary coordinate jump is used.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from scripts.media.continuous_flowline import Flowline, first_absorber

if TYPE_CHECKING:
    from scripts.media.dinf_original import Prepared

GEOMETRY_TOL_PX = 1e-10
HEIGHT_TOL_M = 1e-9

# Vertices within a unit square, and derivatives of barycentric coordinates.
VERTICES = np.array(
    [
        [[0, 0], [0, 1], [1, 1]],
        [[0, 0], [1, 1], [1, 0]],
        [[0, 0], [0, 1], [1, 0]],
        [[0, 1], [1, 1], [1, 0]],
    ],
    dtype=float,
)
WEIGHT_GRAD = np.array(
    [
        [[0, -1], [-1, 1], [1, 0]],
        [[-1, 0], [0, 1], [1, -1]],
        [[-1, -1], [0, 1], [1, 0]],
        [[-1, 0], [1, 1], [0, -1]],
    ],
    dtype=float,
)
WEIGHT_OFFSET = np.array([[1, 0, 0], [1, 0, 0], [1, 0, 0], [1, -1, 1]], dtype=float)


class TriangularSurface:
    """Exact nodal interpolation with no triangle-interior extrema."""

    def __init__(self, prepared: Prepared) -> None:
        self.prepared = prepared
        self.h = prepared.height_m
        self.shape = self.h.shape
        a, b, c, d = self.h[:-1, :-1], self.h[:-1, 1:], self.h[1:, :-1], self.h[1:, 1:]
        low_ad, low_bc = np.minimum(a, d), np.minimum(b, c)
        self.backslash = (low_ad < low_bc) | (
            (low_ad == low_bc) & (np.maximum(a, d) <= np.maximum(b, c))
        )

    def incident(self, point: np.ndarray) -> list[tuple[np.ndarray, np.ndarray, np.ndarray, int]]:
        """Return containing triangles, heights, barycentric weights and local type."""
        row, col = point
        if not (0 <= row <= self.shape[0] - 1 and 0 <= col <= self.shape[1] - 1):
            return []
        r, c = int(np.rint(row)), int(np.rint(col))
        rows = [r, r - 1] if abs(row - r) < GEOMETRY_TOL_PX else [int(np.floor(row))]
        cols = [c, c - 1] if abs(col - c) < GEOMETRY_TOL_PX else [int(np.floor(col))]
        triangles = []
        for rr in rows:
            for cc in cols:
                if not (0 <= rr < self.shape[0] - 1 and 0 <= cc < self.shape[1] - 1):
                    continue
                types = (0, 1) if self.backslash[rr, cc] else (2, 3)
                for kind in types:
                    weights = WEIGHT_OFFSET[kind] + WEIGHT_GRAD[kind] @ (point - [rr, cc])
                    if np.min(weights) < -GEOMETRY_TOL_PX:
                        continue
                    weights[abs(weights) < GEOMETRY_TOL_PX] = 0
                    weights /= weights.sum()
                    vertices = VERTICES[kind] + [rr, cc]
                    indices = vertices.astype(int)
                    z = self.h[indices[:, 0], indices[:, 1]]
                    if np.isfinite(z).all():
                        triangles.append((vertices, z, weights, kind))
        return triangles

    def height(self, point: np.ndarray) -> float:
        triangles = self.incident(point)
        if not triangles:
            return float("nan")
        _, z, weights, _ = triangles[0]
        return float(z @ weights)

    def next_event(self, point: np.ndarray) -> tuple[np.ndarray, bool] | None:
        """Choose the steepest feasible local ray, including valley-edge sliding."""
        triangles = self.incident(point)
        best_slope = 0.0
        best = None
        flat_choices = []
        for vertices, z, weights, kind in triangles:
            gradient = z @ WEIGHT_GRAD[kind]
            norm = float(np.linalg.norm(gradient))
            candidates = []
            if norm > 0:
                direction = -gradient / norm
                dw = WEIGHT_GRAD[kind] @ direction
                if (dw[weights <= GEOMETRY_TOL_PX] >= -GEOMETRY_TOL_PX).all():
                    candidates.append(direction)
            # A constrained gradient can run along a valley edge or from a node.
            for vertex in vertices:
                delta = vertex - point
                length = float(np.linalg.norm(delta))
                if length > GEOMETRY_TOL_PX:
                    candidates.append(delta / length)
            for direction in candidates:
                slope = float(-gradient @ direction)
                if slope <= best_slope or slope <= 1e-14:
                    continue
                dw = WEIGHT_GRAD[kind] @ direction
                leaving = dw < -GEOMETRY_TOL_PX
                if not leaving.any():
                    continue
                distance = float(np.min(-weights[leaving] / dw[leaving]))
                if distance <= GEOMETRY_TOL_PX:
                    continue
                endpoint_weights = weights + distance * dw
                endpoint_weights[abs(endpoint_weights) < GEOMETRY_TOL_PX] = 0
                endpoint_weights /= endpoint_weights.sum()
                # Compute drop from relative nodal heights, not the dot product
                # of nearly cancelling gradient components on an equal edge.
                drop = float((z - z[0]) @ (weights - endpoint_weights))
                if drop <= 0:
                    continue
                slope = drop / distance
                if slope <= best_slope:
                    continue
                endpoint = endpoint_weights @ vertices
                best_slope, best = slope, endpoint
            local_height = float(z @ weights)
            for vertex, height in zip(vertices, z, strict=True):
                distance = float(np.linalg.norm(vertex - point))
                r, c = vertex.astype(int)
                rank = self.prepared.flat_rank[r, c]
                if (
                    distance > GEOMETRY_TOL_PX
                    and abs(height - local_height) <= HEIGHT_TOL_M
                    and rank >= 0
                ):
                    flat_choices.append((int(rank), distance, float(r), float(c)))
        if best is not None:
            return best, False
        node = np.rint(point).astype(int)
        if np.linalg.norm(point - node) <= GEOMETRY_TOL_PX:
            target = self.prepared.d8_receiver[tuple(node)]
            if target >= 0:
                endpoint = np.array(divmod(int(target), self.shape[1]), dtype=float)
                # A missing diagonal may cross two faces; check its midpoint too.
                middle_height = self.height((point + endpoint) / 2)
                if (
                    np.isfinite(middle_height)
                    and middle_height <= self.height(point) + HEIGHT_TOL_M
                ):
                    return endpoint, True
            return None
        if flat_choices:
            _, _, r, c = min(flat_choices)
            return np.array([r, c]), True
        return None


def trace_triangles(
    surface: TriangularSurface,
    seed_rc: tuple[float, float],
    absorbing: np.ndarray,
    *,
    sample_px: float = 0.5,
    max_events: int = 10000,
) -> Flowline:
    """Trace exact facet events; sample spacing changes only output subdivision."""
    if absorbing.shape != surface.shape:
        raise ValueError("absorbing shape differs from surface")
    if not np.isfinite(sample_px) or not (0 < sample_px <= 0.5) or max_events < 1:
        raise ValueError("sample spacing must be positive and <= 0.5; event limit must be positive")
    point = np.asarray(seed_rc, dtype=float)
    if point.shape != (2,) or not np.isfinite(point).all() or not surface.incident(point):
        raise ValueError("seed is outside supported triangles")
    points, heights = [point.copy()], [surface.height(point)]
    status, sink = "event_limit", None
    cell = tuple(np.floor(point + 0.5).astype(int))
    if absorbing[cell]:
        return Flowline(np.array(points), np.array(heights), "absorbed", cell, 0)
    visited = set()
    for _ in range(max_events):
        key = tuple(np.round(point, 9))
        if key in visited:
            status = "cycle"
            break
        visited.add(key)
        event = surface.next_event(point)
        if event is None:
            status = "unresolved"
            break
        candidate, flat = event
        hit = first_absorber(point, candidate, absorbing)
        if hit is not None:
            candidate, sink = hit
        height = surface.height(candidate)
        if not np.isfinite(height):
            status = "missing_support"
            break
        if height > heights[-1] + HEIGHT_TOL_M:
            status = "uphill_rejected"
            break
        if not flat and height >= heights[-1] and np.linalg.norm(candidate - point) > 1e-8:
            status = "nonprogress"
            break
        distance = float(np.linalg.norm(candidate - point))
        if distance > GEOMETRY_TOL_PX:
            count = max(1, int(np.ceil(distance / sample_px)))
            for fraction in np.arange(1, count + 1) / count:
                p = point + fraction * (candidate - point)
                points.append(p)
                heights.append(surface.height(p))
        point = candidate
        if hit is not None:
            status = "absorbed"
            break
    return Flowline(np.asarray(points), np.asarray(heights), status, sink, 0)
