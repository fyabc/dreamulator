"""Finite spherical footprints of projected canvas precipitation cells.

Curved boundaries are refined in the equal-area (longitude, sin(latitude))
plane. Axis clipping against native integration cells yields positive overlap
weights. The projection Jacobian provides an independent area check; subdivision
convergence controls how water is split across native boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from numba import njit
from scipy.sparse import csr_matrix

from dreamulator.gcm.area_remap import SphericalCellCoverage

from .td_canvas import TD_COARSE_KM

if TYPE_CHECKING:
    from dreamulator.gcm.native_partition import GaussianParentPartition

    from .td_canvas import CanvasGeometry


@njit(cache=True)
def _clip(points: np.ndarray, axis: int, bound: float, above: bool) -> np.ndarray:
    result = np.empty((len(points) + 4, 2))
    count = 0
    for i in range(len(points)):
        a, b = points[i - 1], points[i]
        ina, inb = a[axis] >= bound, b[axis] >= bound
        if not above:
            ina, inb = a[axis] <= bound, b[axis] <= bound
        if ina != inb:
            t = (bound - a[axis]) / (b[axis] - a[axis])
            result[count] = a + t * (b - a)
            result[count, axis] = bound
            count += 1
        if inb:
            result[count] = b
            count += 1
    return result[:count]


@njit(cache=True)
def _area(points: np.ndarray) -> float:
    if len(points) < 3:
        return 0.0
    value = 0.0
    # Subtract a local origin to retain precision in small far-from-origin cells.
    for i in range(len(points)):
        a, b = points[i - 1] - points[0], points[i] - points[0]
        value += a[0] * b[1] - a[1] * b[0]
    return abs(value) / 2


@njit(cache=True)
def _weights(
    polygons: np.ndarray,
    counts: np.ndarray,
    mu_edges: np.ndarray,
    starts: np.ndarray,
    ncols: np.ndarray,
    strides: np.ndarray,
    native_nlon: int,
    radius2: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    indices, values = [], []
    offsets = np.zeros(len(polygons) + 1, dtype=np.int64)
    base = -np.pi / native_nlon
    for k in range(len(polygons)):
        poly = polygons[k, : counts[k]]
        low = np.min(poly[:, 1])
        high = np.max(poly[:, 1])
        first = max(0, np.searchsorted(mu_edges, low, side="right") - 1)
        stop = min(len(starts), np.searchsorted(mu_edges, high, side="left"))
        for row in range(first, stop):
            strip = _clip(_clip(poly, 1, mu_edges[row], True), 1, mu_edges[row + 1], False)
            if len(strip) < 3:
                continue
            nc = ncols[row]
            dl = 2 * np.pi / (native_nlon * nc)
            left = int(np.floor((np.min(strip[:, 0]) - base) / dl))
            right = int(np.ceil((np.max(strip[:, 0]) - base) / dl))
            for col in range(left, right):
                clipped = _clip(
                    _clip(strip, 0, base + col * dl, True), 0, base + (col + 1) * dl, False
                )
                area = _area(clipped) * radius2
                if area > 0:
                    wrap = col % (native_nlon * nc)
                    indices.append(starts[row] + wrap // nc * strides[row] + wrap % nc)
                    values.append(area)
        offsets[k + 1] = len(indices)
    return offsets, np.asarray(indices, dtype=np.int64), np.asarray(values)


def _native_rows(p: GaussianParentPartition) -> tuple[np.ndarray, ...]:
    edges: list[float] = []
    starts: list[int] = []
    columns: list[int] = []
    strides: list[int] = []
    for row in range(p.shape[0]):
        parent = row * p.shape[1]
        nr, nc = int(p.nrows[parent]), int(p.ncols[parent])
        a, b = np.arcsin(p.mu_edges[row : row + 2])
        mu = np.sin(np.linspace(a, b, nr + 1))
        mu[[0, -1]] = p.mu_edges[row : row + 2]
        edges.extend(mu[:-1])
        starts.extend(p.offsets[parent] + np.arange(nr) * nc)
        columns.extend([nc] * nr)
        strides.extend([nr * nc] * nr)
    edges.append(1.0)
    return (
        np.asarray(edges),
        np.asarray(starts, dtype=np.int64),
        np.asarray(columns, dtype=np.int64),
        np.asarray(strides, dtype=np.int64),
    )


def _polygons(
    geom: CanvasGeometry,
    x: np.ndarray,
    y: np.ndarray,
    subdivisions: int,
) -> tuple[np.ndarray, np.ndarray]:
    t = np.arange(subdivisions) / subdivisions
    dx = TD_COARSE_KM * np.concatenate([t, np.ones_like(t), 1 - t, np.zeros_like(t), [0]])
    dy = TD_COARSE_KM * np.concatenate([np.zeros_like(t), t, np.ones_like(t), 1 - t, [0]])
    lat, lon = geom.xy_to_latlon(x[:, None] + dx, y[:, None] + dy)
    lam = np.unwrap(np.radians(lon), axis=1)
    mu = np.sin(np.radians(lat))
    polygons = np.zeros((len(x), len(dx) + 4, 2))
    polygons[:, : len(dx), 0] = lam
    polygons[:, : len(dx), 1] = mu
    counts = np.full(len(x), len(dx), dtype=np.int64)
    # A ring around a pole spans a full longitude turn. Close along mu = +/-1.
    for i in np.flatnonzero(abs(lam[:, -1] - lam[:, 0]) > np.pi):
        pole = 1.0 if np.mean(mu[i]) > 0 else -1.0
        polygons[i, len(dx)] = (lam[i, -1], pole)
        polygons[i, len(dx) + 1] = (lam[i, 0], pole)
        counts[i] += 2
    # A pole lying exactly on a boundary has two approach longitudes.
    for i in np.flatnonzero(np.any(abs(mu[:, :-1]) > 1 - 2e-15, axis=1)):
        points = []
        for j in range(len(dx) - 1):
            if abs(mu[i, j]) > 1 - 2e-15:
                points.extend(
                    [
                        (lon[i, (j - 1) % (len(dx) - 1)], np.sign(mu[i, j])),
                        (lon[i, (j + 1) % (len(dx) - 1)], np.sign(mu[i, j])),
                    ]
                )
            else:
                points.append((lon[i, j], mu[i, j]))
        points.append(points[0])
        a = np.asarray(points)
        a[:, 0] = np.unwrap(np.radians(a[:, 0]))
        polygons[i, : len(a)] = a
        counts[i] = len(a)
    return polygons, counts


def _jacobian_areas(geom: CanvasGeometry, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    nodes, weights = np.polynomial.legendre.leggauss(8)
    nodes = (nodes + 1) * TD_COARSE_KM / 2
    area = np.zeros(len(x))
    for i, a in enumerate(nodes):
        for j, b in enumerate(nodes):
            radius = np.hypot(x + a, y + b) / geom.radius_km
            area += weights[i] * weights[j] * np.sinc(radius / np.pi)
    return area * (TD_COARSE_KM / 2) ** 2


@dataclass(frozen=True)
class CanvasPrecipitationCoverage:
    cells: SphericalCellCoverage
    max_area_relative_error: float
    max_overlap_change_relative: float
    max_edge_subdivisions: int
    geometry: CanvasGeometry
    native_geometry: tuple[int, int, float, float]


def canvas_precipitation_coverage(
    partition: GaussianParentPartition,
    geom: CanvasGeometry,
    *,
    relative_tolerance: float = 2e-6,
    max_subdivisions: int = 4096,
) -> CanvasPrecipitationCoverage:
    """Integrate full coarse-cell footprints, refining curved boundaries to tolerance.

    The tolerance bounds the independent spherical-area discrepancy and the L1
    change in source overlaps relative to target area between successive edge
    subdivisions. It is a numerical geometry tolerance, shared by all worlds.
    """
    if not np.isclose(partition.radius_km, geom.radius_km, rtol=1e-10, atol=0):
        raise ValueError("precipitation and canvas must use the same planetary radius")
    if (
        geom.ncell < 1
        or not np.isfinite([geom.center_lat, geom.center_lon]).all()
        or abs(geom.center_lat) > 90
        or np.hypot(geom.half_km, geom.half_km) >= np.pi * geom.radius_km
        or not 0 < relative_tolerance < 0.01
        or max_subdivisions < 4
    ):
        raise ValueError("invalid canvas footprint or numerical geometry tolerance")
    axis = np.arange(geom.ncell) * TD_COARSE_KM - geom.half_km
    xx, yy = np.meshgrid(axis, axis[::-1])
    x, y = xx.ravel(), yy.ravel()
    reference_area = _jacobian_areas(geom, x, y)
    mu_edges, starts, columns, strides = _native_rows(partition)
    pending = np.arange(len(x))
    accepted = []
    max_area_error, max_change = 0.0, 0.0
    subdivisions = 2

    def operator(which: np.ndarray, n: int) -> csr_matrix:
        polygons, counts = _polygons(geom, x[which], y[which], n)
        ptr, indices, values = _weights(
            polygons,
            counts,
            mu_edges,
            starts,
            columns,
            strides,
            partition.shape[1],
            geom.radius_km**2,
        )
        return csr_matrix((values, indices, ptr), shape=(len(which), len(partition.area_km2)))

    previous = operator(pending, subdivisions)
    while len(pending):
        subdivisions *= 2
        if subdivisions > max_subdivisions:
            raise ValueError("projected precipitation overlap failed to converge")
        current = operator(pending, subdivisions)
        area = np.asarray(current.sum(axis=1)).ravel()
        area_error = abs(area / reference_area[pending] - 1)
        change = np.asarray(abs(current - previous).sum(axis=1)).ravel() / reference_area[pending]
        good = (area_error <= relative_tolerance) & (change <= relative_tolerance)
        if good.any():
            block = current[good].tocoo()
            accepted.append((pending[good][block.row], block.col, block.data))
            max_area_error = max(max_area_error, float(area_error[good].max()))
            max_change = max(max_change, float(change[good].max()))
        pending = pending[~good]
        previous = current[~good]
    rows, cols, values = (np.concatenate(parts) for parts in zip(*accepted, strict=True))
    overlap = csr_matrix((values, (rows, cols)), shape=(len(x), len(partition.area_km2)))
    # The approximated closed boundaries define this finite integration geometry.
    # The independently computed smooth footprint remains the convergence check.
    target_area = np.asarray(overlap.sum(axis=1)).reshape(geom.ncell, geom.ncell)
    if (target_area <= 0).any():
        raise ValueError("projected cells must have positive covered areas")
    target_area.setflags(write=False)
    return CanvasPrecipitationCoverage(
        SphericalCellCoverage(overlap, target_area, (geom.ncell, geom.ncell)),
        max_area_error,
        max_change,
        subdivisions,
        geom,
        (*partition.shape, partition.radius_km, partition.spacing_km),
    )
