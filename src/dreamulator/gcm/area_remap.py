"""Spherical overlap integrals from native Gaussian children to geographic cells.

The overlap measure is R² d(sin(latitude)) d(longitude). This remaps finite
cell areas, including the periodic seam and poles, rather than their centres.
Projected boundaries are provided by map.canvas_precipitation. Spherical CVT
footprints use their own geometry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from scipy.sparse import csr_matrix

if TYPE_CHECKING:
    from .native_partition import GaussianParentPartition


@dataclass(frozen=True)
class SphericalCellCoverage:
    """Positive overlap areas in km²; target ordering is supplied by its geometry."""

    overlap_km2: csr_matrix
    area_km2: np.ndarray
    shape: tuple[int, ...]

    def integrals(self, child_values: np.ndarray) -> np.ndarray:
        """Integrate any finite (..., children) field over each target cell."""
        values = np.asarray(child_values, dtype=np.float64)
        if (
            values.ndim < 1
            or values.shape[-1] != self.overlap_km2.shape[1]
            or not np.isfinite(values).all()
        ):
            raise ValueError("values must be finite and cover all native children")
        result = self.overlap_km2 @ values.reshape(-1, values.shape[-1]).T
        return np.asarray(result.T).reshape(*values.shape[:-1], *self.shape)

    def means(self, child_values: np.ndarray) -> np.ndarray:
        """Area-average a field without smoothing across its source boundaries."""
        return np.asarray(self.integrals(child_values) / self.area_km2)

    @property
    def source_covered_area_km2(self) -> np.ndarray:
        """Area of each native child inside this target footprint."""
        return np.asarray(self.overlap_km2.sum(axis=0)).ravel()


def _overlaps(source: np.ndarray, target: np.ndarray) -> tuple[np.ndarray, ...]:
    """Indices and lengths of positive intersections of two ascending partitions."""
    si, ti, widths = [], [], []
    for i in range(len(source) - 1):
        first = max(0, int(np.searchsorted(target, source[i], side="right")) - 1)
        stop = min(len(target) - 1, int(np.searchsorted(target, source[i + 1], side="left")))
        for j in range(first, stop):
            width = min(source[i + 1], target[j + 1]) - max(source[i], target[j])
            if width > 0:
                si.append(i)
                ti.append(j)
                widths.append(width)
    return np.asarray(si, dtype=np.int64), np.asarray(ti, dtype=np.int64), np.asarray(widths)


def gaussian_rectilinear_coverage(
    partition: GaussianParentPartition,
    latitude_edges: np.ndarray,
    longitude_edges: np.ndarray,
) -> SphericalCellCoverage:
    """Intersect Gaussian children with latitude/longitude rectangles analytically.

    Edges must ascend. Longitude edges may start anywhere and span at most one
    full turn; an interval such as [170, 190] crosses the conventional seam.
    A regional footprint retains precisely its covered source water volume.
    Each precipitation component and month can use the same sparse operator.
    """
    lat = np.asarray(latitude_edges, dtype=np.float64)
    lon = np.asarray(longitude_edges, dtype=np.float64)
    if (
        lat.ndim != 1
        or lon.ndim != 1
        or len(lat) < 2
        or len(lon) < 2
        or not np.isfinite(lat).all()
        or not np.isfinite(lon).all()
        or (np.diff(lat) <= 0).any()
        or (np.diff(lon) <= 0).any()
        or lat[0] < -90
        or lat[-1] > 90
        or lon[-1] - lon[0] > 360
    ):
        raise ValueError("target edges must ascend within geographic bounds and one longitude turn")
    mu = np.sin(np.radians(lat))
    # Remove arbitrary full turns before computing intersections.
    lam = np.radians(lon - 360 * np.floor(lon[0] / 360))
    if (np.diff(mu) <= 0).any() or (np.diff(lam) <= 0).any():
        raise ValueError("target edges have zero spherical area at floating-point precision")
    nlat, nlon = partition.shape
    target_nlon = len(lon) - 1
    dlon = 2 * np.pi / nlon
    radius2 = partition.radius_km**2
    rows, cols, areas = [], [], []
    for row in range(nlat):
        parent = row * nlon
        nr, nc = int(partition.nrows[parent]), int(partition.ncols[parent])
        phi = np.arcsin(partition.mu_edges[row : row + 2])
        source_mu = np.sin(np.linspace(phi[0], phi[1], nr + 1))
        source_mu[[0, -1]] = partition.mu_edges[row : row + 2]
        sy, ty, dy = _overlaps(source_mu, mu)
        if not len(sy):
            continue
        source_lon = np.linspace(-dlon / 2, 2 * np.pi - dlon / 2, nc * nlon + 1)
        longitude_parts = []
        first_turn = int(np.floor((lam[0] - source_lon[-1]) / (2 * np.pi)))
        last_turn = int(np.ceil((lam[-1] - source_lon[0]) / (2 * np.pi)))
        for turn in range(first_turn, last_turn + 1):
            longitude_parts.append(_overlaps(source_lon + turn * 2 * np.pi, lam))
        sx, tx, dx = (np.concatenate(items) for items in zip(*longitude_parts, strict=True))
        rows.append((ty[:, None] * target_nlon + tx).ravel())
        cols.append(
            (
                partition.offsets[parent]
                + (sx[None, :] // nc * nr + sy[:, None]) * nc
                + sx[None, :] % nc
            ).ravel()
        )
        areas.append((dy[:, None] * dx * radius2).ravel())
    shape = (len(lat) - 1, target_nlon)
    overlaps = csr_matrix(
        (np.concatenate(areas), (np.concatenate(rows), np.concatenate(cols))),
        shape=(shape[0] * shape[1], len(partition.area_km2)),
    )
    area = radius2 * np.diff(mu)[:, None] * np.diff(lam)
    actual_area = np.asarray(overlaps.sum(axis=1)).reshape(shape)
    if not np.allclose(actual_area, area, rtol=2e-12, atol=0):
        raise ValueError("source overlap areas do not cover every target cell")
    area.setflags(write=False)
    return SphericalCellCoverage(overlaps, area, shape)
