"""Continuous terrain sources and spherical footprint integration.

A source owns its projection, geometry and numerical reconstruction. Consumers query it in
latitude/longitude and average over their own footprints. Mesh and canvas sampling therefore
share the same surface. Point-field reconstruction is an approximation when the input values
are cell means; its provenance belongs to the source rather than to the target grid.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

import numpy as np

if TYPE_CHECKING:
    from collections.abc import Callable

    from .td_canvas import CanvasGeometry

SOURCE_SAMPLING = "continuous-source-v1"


class TerrainSource(Protocol):
    """Frozen source queried in degrees, returning metres and a separate land indicator."""

    @property
    def metadata(self) -> dict[str, Any]: ...

    def evaluate(self, lat: np.ndarray, lon: np.ndarray) -> tuple[np.ndarray, np.ndarray]: ...


class FootprintTerrainSource(TerrainSource, Protocol):
    """Terrain difference with a conservative bound on potentially changed footprints."""

    def footprint_support(
        self,
        lat: np.ndarray,
        lon: np.ndarray,
        half_diagonal_km: float,
        radius_km: float,
    ) -> np.ndarray: ...


@dataclass(frozen=True)
class ProjectedTerrainSource:
    """Terrain function in a fixed source plane (x east, y north, kilometres).

    ``height_xy`` and ``land_xy`` read frozen inputs; any stochastic realization and geometric
    reconstruction is prepared before the callbacks are installed. A missing land callback
    means the source's zero-height contour defines its shoreline.
    """

    geometry: CanvasGeometry
    height_xy: Callable[[np.ndarray, np.ndarray], np.ndarray]
    provenance: dict[str, Any]
    land_xy: Callable[[np.ndarray, np.ndarray], np.ndarray] | None = None

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "sampling": SOURCE_SAMPLING,
            "projection": self.geometry.to_dict(),
            **self.provenance,
        }

    def evaluate(self, lat: np.ndarray, lon: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        x, y = self.geometry.latlon_to_xy(lat, lon)
        height = np.asarray(self.height_xy(x, y), dtype=np.float64)
        land = height > 0 if self.land_xy is None else self.land_xy(x, y)
        return height, np.asarray(land, dtype=np.float64)


class PointTerrainField:
    """Frozen, vertex-range-clipped Clough–Tocher reconstruction in a source plane.

    All support points are selected by the caller once. Query batches and target canvas
    extents leave the triangulation unchanged. Values outside the support hull are missing.
    """

    def __init__(self, xy_km: np.ndarray, values: np.ndarray) -> None:
        from scipy.interpolate import CloughTocher2DInterpolator

        self.xy_km = np.array(xy_km, dtype=np.float64, copy=True)
        self.values = np.array(values, dtype=np.float64, copy=True)
        if self.xy_km.ndim != 2 or self.xy_km.shape[1] != 2:
            raise ValueError("support coordinates must have shape (n, 2)")
        if self.values.ndim not in (1, 2) or self.values.shape[0] != len(self.xy_km):
            raise ValueError("values must have shape (n,) or (n, channels)")
        if not np.isfinite(self.xy_km).all() or not np.isfinite(self.values).all():
            raise ValueError("support coordinates and values must be finite")
        self.xy_km.setflags(write=False)
        self.values.setflags(write=False)
        self._interpolator = CloughTocher2DInterpolator(self.xy_km, self.values)
        digest = hashlib.sha256()
        for arr in (self.xy_km, self.values):
            digest.update(str(arr.shape).encode())
            digest.update(arr.astype("<f8").tobytes())
        self.sha256 = digest.hexdigest()

    def __call__(self, x_km: np.ndarray, y_km: np.ndarray) -> np.ndarray:
        x, y = np.broadcast_arrays(x_km, y_km)
        q = np.column_stack([x.ravel(), y.ravel()])
        result = self._interpolator(q)
        simplex = self._interpolator.tri.find_simplex(q)
        valid = simplex >= 0
        vertices = self.values[self._interpolator.tri.simplices[simplex[valid]]]
        result[valid] = np.clip(result[valid], vertices.min(axis=1), vertices.max(axis=1))
        return np.asarray(result.reshape((*x.shape, *self.values.shape[1:])))


class PolylineGeometry:
    """Piecewise straight source geometry, with exact segment distances in its fixed plane.

    The caller supplies coastlines, ridge axes or other feature curves in kilometres. Long
    curves are evaluated in blocks so the working memory stays bounded.
    """

    def __init__(self, lines: list[np.ndarray]) -> None:
        segments = [np.stack([p[:-1], p[1:]], axis=1) for p in lines if len(p) >= 2]
        if not segments:
            raise ValueError("at least one feature segment is required")
        arr = np.concatenate(segments).astype(np.float64)
        if arr.ndim != 3 or arr.shape[1:] != (2, 2) or not np.isfinite(arr).all():
            raise ValueError("feature lines must contain finite (x, y) coordinates")
        lengths2 = np.sum((arr[:, 1] - arr[:, 0]) ** 2, axis=1)
        self.segments = arr[lengths2 > 0].copy()
        if len(self.segments) == 0:
            raise ValueError("feature segments must have positive length")
        self.segments.setflags(write=False)
        self.sha256 = hashlib.sha256(self.segments.astype("<f8").tobytes()).hexdigest()

    def distance_km(self, x_km: np.ndarray, y_km: np.ndarray) -> np.ndarray:
        x, y = np.broadcast_arrays(x_km, y_km)
        points = np.column_stack([x.ravel(), y.ravel()])
        out = np.full(len(points), np.inf)
        for start in range(0, len(points), 2048):
            q = points[start : start + 2048]
            best = np.full(len(q), np.inf)
            for k in range(0, len(self.segments), 128):
                seg = self.segments[k : k + 128]
                v = seg[:, 1] - seg[:, 0]
                offset = q[:, None, :] - seg[None, :, 0, :]
                t = np.clip(np.sum(offset * v, axis=2) / np.sum(v * v, axis=1), 0, 1)
                d2 = np.sum((offset - t[..., None] * v) ** 2, axis=2)
                best = np.minimum(best, d2.min(axis=1))
            out[start : start + len(q)] = np.sqrt(best)
        return out.reshape(x.shape)


@dataclass(frozen=True)
class SphericalProjection:
    """Nearest finite arc, its fractional position, angular distance and oriented side."""

    segment_index: np.ndarray
    fraction: np.ndarray
    distance_rad: np.ndarray
    side: np.ndarray


class SphericalSegmentGeometry:
    """Frozen minor great-circle arcs on a unit sphere, independent of a target projection.

    The source supplies oriented endpoint pairs. Side is the sign of the scalar product
    with ``a cross b`` in that source's coordinate frame. Ties choose the first segment.
    """

    def __init__(self, segments_xyz: np.ndarray) -> None:
        arr = np.array(segments_xyz, dtype=np.float64, copy=True)
        if arr.ndim != 3 or arr.shape[1:] != (2, 3) or len(arr) == 0:
            raise ValueError("sphere segments must have shape (n, 2, 3), n > 0")
        if not np.isfinite(arr).all() or not np.allclose(
            np.linalg.norm(arr, axis=-1), 1, rtol=0, atol=1e-7
        ):
            raise ValueError("sphere endpoints must be finite unit vectors")
        arr /= np.linalg.norm(arr, axis=-1, keepdims=True)
        normal = np.cross(arr[:, 0], arr[:, 1])
        lengths = np.arctan2(np.linalg.norm(normal, axis=-1), (arr[:, 0] * arr[:, 1]).sum(-1))
        if np.any((lengths < 1e-10) | (lengths > np.pi - 1e-10)):
            raise ValueError("sphere arcs must have distinct, non-antipodal endpoints")
        normal /= np.linalg.norm(normal, axis=-1, keepdims=True)
        self.segments = arr
        self._normal = normal
        self._tangent = np.cross(normal, arr[:, 0])
        self._lengths = lengths
        for a in (self.segments, self._normal, self._tangent, self._lengths):
            a.setflags(write=False)
        self.sha256 = hashlib.sha256(arr.astype("<f8").tobytes()).hexdigest()

    def project(self, xyz: np.ndarray) -> SphericalProjection:
        """Project arbitrary-shaped unit-vector queries onto the nearest finite source arc."""
        points = np.asarray(xyz, dtype=np.float64)
        if points.ndim < 1 or points.shape[-1] != 3 or not np.isfinite(points).all():
            raise ValueError("query points must be finite unit vectors")
        shape = points.shape[:-1]
        points = points.reshape(-1, 3)
        if not np.allclose(np.linalg.norm(points, axis=1), 1, rtol=0, atol=1e-7):
            raise ValueError("query points must be unit vectors")
        points = points / np.linalg.norm(points, axis=1, keepdims=True)
        index = np.zeros(len(points), dtype=np.int64)
        fraction, distance, side = (np.zeros(len(points)) for _ in range(3))
        distance[:] = np.inf
        for start in range(0, len(points), 1024):
            sl = slice(start, start + 1024)
            q = points[sl]
            rows = np.arange(len(q))
            for k in range(0, len(self.segments), 128):
                seg = self.segments[k : k + 128]
                qa, qb = q @ seg[:, 0].T, q @ seg[:, 1].T
                normal = q @ self._normal[k : k + 128].T
                along = np.arctan2(q @ self._tangent[k : k + 128].T, qa)
                length = self._lengths[k : k + 128]
                on_arc = (along >= 0) & (along <= length)
                d = np.where(
                    on_arc,
                    np.arcsin(np.clip(abs(normal), 0, 1)),
                    np.arccos(np.clip(np.maximum(qa, qb), -1, 1)),
                )
                t = np.where(on_arc, along / length, (qb > qa).astype(float))
                best = np.argmin(d, axis=1)
                improve = d[rows, best] < distance[sl]
                dst = start + rows[improve]
                j = best[improve]
                index[dst] = k + j
                fraction[dst] = t[rows[improve], j]
                distance[dst] = d[rows[improve], j]
                side[dst] = np.sign(normal[rows[improve], j])
        return SphericalProjection(*(a.reshape(shape) for a in (index, fraction, distance, side)))


class RasterTerrainField:
    """Bilinear query of a frozen source raster; axes increase eastward and northward.

    The source resolution and footprint are independent of the consumer. This adapter also
    supports independently prepared DEMs and geometry fields. Missing coverage returns NaN.
    """

    def __init__(self, x_km: np.ndarray, y_km: np.ndarray, values: np.ndarray) -> None:
        from scipy.interpolate import RegularGridInterpolator

        self.x_km, self.y_km, self.values = (
            np.array(a, dtype=np.float64, copy=True) for a in (x_km, y_km, values)
        )
        if self.x_km.ndim != 1 or self.y_km.ndim != 1:
            raise ValueError("raster axes must be one-dimensional")
        if len(self.x_km) < 2 or len(self.y_km) < 2:
            raise ValueError("raster axes need at least two points")
        if np.any(np.diff(self.x_km) <= 0) or np.any(np.diff(self.y_km) <= 0):
            raise ValueError("raster axes must increase")
        if self.values.shape[:2] != (len(self.y_km), len(self.x_km)):
            raise ValueError("raster values must have shape (ny, nx, ...)")
        digest = hashlib.sha256()
        for a in (self.x_km, self.y_km, self.values):
            if not np.isfinite(a).all():
                raise ValueError("raster data must be finite")
            a.setflags(write=False)
            digest.update(str(a.shape).encode())
            digest.update(a.astype("<f8").tobytes())
        self.sha256 = digest.hexdigest()
        self._interpolator = RegularGridInterpolator(
            (self.y_km, self.x_km), self.values, bounds_error=False, fill_value=np.nan
        )

    def __call__(self, x_km: np.ndarray, y_km: np.ndarray) -> np.ndarray:
        x, y = np.broadcast_arrays(x_km, y_km)
        q = np.column_stack([y.ravel(), x.ravel()])
        return np.asarray(self._interpolator(q).reshape((*x.shape, *self.values.shape[2:])))


@dataclass(frozen=True)
class FrozenStageTerrainField:
    """Carry a frozen stage difference onto a replacement input surface.

    The callbacks query reconstructed reference states before and after a stage, and its
    replacement input, all in the same fixed source plane. Compute ``after + (new - before)``
    after endpoint reconstruction: clipping or limiting the difference independently would
    break reference-state replay. An unchanged input returns the reference final height exactly.

    This transfers the observed reference change as a fixed field. The stage's physical response
    to a changed input still requires its actual operator. Callers record endpoint provenance
    and choose the final source's land indicator separately.
    """

    before_xy: Callable[[np.ndarray, np.ndarray], np.ndarray]
    after_xy: Callable[[np.ndarray, np.ndarray], np.ndarray]
    replacement_xy: Callable[[np.ndarray, np.ndarray], np.ndarray]

    def __call__(self, x_km: np.ndarray, y_km: np.ndarray) -> np.ndarray:
        x, y = np.broadcast_arrays(x_km, y_km)
        before, after, replacement = (
            np.asarray(field(x, y), dtype=np.float64)
            for field in (self.before_xy, self.after_xy, self.replacement_xy)
        )
        if any(a.shape != x.shape for a in (before, after, replacement)):
            raise ValueError("stage fields must return one height per query coordinate")
        return np.asarray(after + (replacement - before))


def transition_profile(
    distance_km: np.ndarray, width_km: float, edge_m: np.ndarray, interior_m: np.ndarray
) -> np.ndarray:
    """Cubic smoothstep between prescribed edge and interior heights over a physical width.

    Width and endpoint elevations are source inputs. Their physical interpretation is supplied
    by the caller's landform model and recorded in its provenance.
    """
    if not np.isfinite(width_km) or width_km <= 0:
        raise ValueError("profile width must be positive and finite")
    t = np.clip(np.asarray(distance_km) / width_km, 0, 1)
    w = t * t * (3 - 2 * t)
    return np.asarray(edge_m + w * (interior_m - edge_m))


@dataclass(frozen=True)
class TerrainAverages:
    height_m: np.ndarray
    land_fraction: np.ndarray
    area_km2: np.ndarray


def average_rectangles(
    source: TerrainSource,
    target: CanvasGeometry,
    x_min_km: np.ndarray,
    y_min_km: np.ndarray,
    x_max_km: np.ndarray,
    y_max_km: np.ndarray,
    *,
    quadrature: int = 8,
) -> TerrainAverages:
    """Area averages over rectangles in a target azimuthal-equidistant plane.

    Tensor Gauss–Legendre quadrature includes the sphere/plane Jacobian sin(c)/c. Heights
    and land indicators are accumulated separately. Raise on missing source coverage so a
    consumer can enlarge its frozen source footprint explicitly. Quadrature convergence is
    checked by comparing orders, especially for coast-crossing cells.
    """
    if quadrature < 2:
        raise ValueError("quadrature must be at least 2")
    x0, y0, x1, y1 = np.broadcast_arrays(x_min_km, y_min_km, x_max_km, y_max_km)
    if not all(np.isfinite(a).all() for a in (x0, y0, x1, y1)):
        raise ValueError("footprints must be finite")
    if np.any(x1 <= x0) or np.any(y1 <= y0):
        raise ValueError("footprints must have positive area")
    far = np.hypot(np.maximum(abs(x0), abs(x1)), np.maximum(abs(y0), abs(y1)))
    if np.any(far >= np.pi * target.radius_km):
        raise ValueError("footprints must lie inside the projection's antipode")
    u, w = np.polynomial.legendre.leggauss(quadrature)
    shape = x0.shape
    xc, yc = ((x0 + x1) / 2).ravel(), ((y0 + y1) / 2).ravel()
    hx, hy = ((x1 - x0) / 2).ravel(), ((y1 - y0) / 2).ravel()
    heights, lands, areas = (np.empty(xc.shape) for _ in range(3))
    weights = w[:, None] * w[None, :]
    for start in range(0, len(xc), 256):
        sl = slice(start, start + 256)
        x = xc[sl, None, None] + hx[sl, None, None] * u[None, :, None]
        y = yc[sl, None, None] + hy[sl, None, None] * u[None, None, :]
        x, y = np.broadcast_arrays(x, y)
        lat, lon = target.xy_to_latlon(x, y)
        h, land = source.evaluate(lat, lon)
        if h.shape != x.shape or land.shape != x.shape:
            raise ValueError("source output shape must match query coordinates")
        if not np.isfinite(h).all() or not np.isfinite(land).all():
            raise ValueError("source coverage is incomplete for the requested footprints")
        if np.any((land < 0) | (land > 1)):
            raise ValueError("source land indicator must lie in [0, 1]")
        jac = np.sinc(np.hypot(x, y) / (np.pi * target.radius_km))
        aw = weights * jac
        total = aw.sum(axis=(1, 2))
        heights[sl] = (h * aw).sum(axis=(1, 2)) / total
        lands[sl] = (land * aw).sum(axis=(1, 2)) / total
        areas[sl] = total * hx[sl] * hy[sl]
    return TerrainAverages(*(a.reshape(shape) for a in (heights, lands, areas)))


def integrate_source_correction(
    source: FootprintTerrainSource, geometry: CanvasGeometry, orders: tuple[int, ...]
) -> tuple[np.ndarray, dict[str, Any]]:
    """Integrate a source difference using the common 2 m/10 m adjacent-order gate."""
    started = time.perf_counter()
    if (
        len(orders) < 2
        or any(order < 2 for order in orders)
        or any(b <= a for a, b in zip(orders, orders[1:], strict=False))
    ):
        raise ValueError("source integration requires increasing quadrature orders")
    if geometry.ncell <= 0 or np.sqrt(2) * geometry.half_km >= np.pi * geometry.radius_km:
        raise ValueError("canvas footprints must lie inside the projection antipode")
    edges = np.linspace(-geometry.half_km, geometry.half_km, geometry.ncell + 1)
    x0, y0 = np.meshgrid(edges[:-1], edges[:-1][::-1])
    x1, y1 = np.meshgrid(edges[1:], edges[1:][::-1])
    lat, lon = geometry.xy_to_latlon((x0 + x1) / 2, (y0 + y1) / 2)
    half_diagonal = float(np.max(np.hypot(x1 - x0, y1 - y0))) / 2
    support = source.footprint_support(lat, lon, half_diagonal, geometry.radius_km)
    if support.shape != x0.shape or support.dtype != np.bool_:
        raise ValueError("source footprint support must be a matching boolean array")
    correction = np.zeros(x0.shape)
    convergence = []
    if not support.any():
        return correction, {
            "quadrature": orders[0],
            "support_footprints": 0,
            "convergence": [],
            "prepare_s": time.perf_counter() - started,
        }
    previous = None
    for order in orders:
        current = average_rectangles(
            source, geometry, x0[support], y0[support], x1[support], y1[support], quadrature=order
        ).height_m
        if previous is not None:
            error = abs(current - previous)
            p95, maximum = float(np.percentile(error, 95)), float(error.max())
            convergence.append({"order": order, "p95_error_m": p95, "maximum_error_m": maximum})
            if p95 <= 2 and maximum <= 10:
                correction[support] = current
                return correction, {
                    "quadrature": order,
                    "support_footprints": int(support.sum()),
                    "convergence": convergence,
                    "prepare_s": time.perf_counter() - started,
                }
        previous = current
    raise ValueError(f"source footprint quadrature did not converge: {convergence}")


def sample_canvas(
    source: TerrainSource, geometry: CanvasGeometry, *, quadrature: int = 8
) -> TerrainAverages:
    """Sample the source on the canvas's 23 km footprints, row zero north."""
    edges = np.linspace(-geometry.half_km, geometry.half_km, geometry.ncell + 1)
    x0, y0 = np.meshgrid(edges[:-1], edges[:-1][::-1])
    x1, y1 = np.meshgrid(edges[1:], edges[1:][::-1])
    return average_rectangles(source, geometry, x0, y0, x1, y1, quadrature=quadrature)
