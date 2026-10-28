"""Finite-area native precipitation on complete spherical Voronoi cells.

Cell boundaries are reconstructed from the same geographic centres in full
precision. Great-circle edges are refined in the equal-area clipping plane.
Independent spherical areas check the geometry before small column corrections
restore each source integration cell's full area at floating-point precision.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from scipy.sparse import csr_matrix
from scipy.spatial import SphericalVoronoi

from dreamulator.map.canvas_precipitation import _native_rows, _weights

from .area_remap import SphericalCellCoverage

if TYPE_CHECKING:
    from pathlib import Path

    from .native_partition import GaussianParentPartition


def coordinate_fingerprint(latitude: np.ndarray, longitude: np.ndarray) -> str:
    """Bind a finite-area operator to ordered geographic sites, modulo full turns."""
    lat, lon = np.asarray(latitude, dtype=np.float64), np.asarray(longitude, dtype=np.float64)
    if (
        lat.ndim != 1
        or lon.shape != lat.shape
        or len(lat) < 4
        or not np.isfinite(lat).all()
        or not np.isfinite(lon).all()
        or (abs(lat) > 90).any()
    ):
        raise ValueError("Voronoi sites must be finite ordered geographic coordinates")
    data = np.column_stack([lat, (lon + 180) % 360 - 180]).astype("<f8")
    return hashlib.sha256(data.tobytes()).hexdigest()


def _polygons(
    vertices: np.ndarray,
    regions: list[list[int]],
    which: np.ndarray,
    subdivisions: int,
) -> tuple[np.ndarray, np.ndarray]:
    lengths = np.fromiter((len(regions[i]) for i in which), dtype=np.int64, count=len(which))
    points = np.zeros((len(which), int(lengths.max()) * subdivisions + 4, 2))
    counts = np.zeros(len(which), dtype=np.int64)
    t = np.arange(subdivisions) / subdivisions
    for length in np.unique(lengths):
        group = np.flatnonzero(lengths == length)
        ids = np.asarray([regions[i] for i in which[group]], dtype=np.int64)
        a = vertices[ids]
        b = np.roll(a, -1, axis=1)
        angle = np.arctan2(np.linalg.norm(np.cross(a, b), axis=2), np.sum(a * b, axis=2))
        sine = np.sin(angle)
        p = (np.sin(angle[..., None] * (1 - t)) / sine[..., None])[..., None] * a[:, :, None] + (
            np.sin(angle[..., None] * t) / sine[..., None]
        )[..., None] * b[:, :, None]
        p = p.reshape(len(group), -1, 3)
        p = np.concatenate([p, p[:, :1]], axis=1)
        lam = np.unwrap(np.arctan2(p[..., 1], p[..., 0]), axis=1)
        mu = np.clip(p[..., 2], -1, 1)
        n = p.shape[1]
        points[group, :n, 0] = lam
        points[group, :n, 1] = mu
        counts[group] = n
        for j in np.flatnonzero(abs(lam[:, -1] - lam[:, 0]) > np.pi):
            cell = group[j]
            pole = 1.0 if np.mean(mu[j]) > 0 else -1.0
            points[cell, n] = (lam[j, -1], pole)
            points[cell, n + 1] = (lam[j, 0], pole)
            counts[cell] += 2
        for j in np.flatnonzero(np.any(abs(mu[:, :-1]) > 1 - 2e-15, axis=1)):
            ring = []
            for k in range(n - 1):
                if abs(mu[j, k]) > 1 - 2e-15:
                    ring.extend(
                        [
                            (lam[j, (k - 1) % (n - 1)], np.sign(mu[j, k])),
                            (lam[j, (k + 1) % (n - 1)], np.sign(mu[j, k])),
                        ]
                    )
                else:
                    ring.append((lam[j, k], mu[j, k]))
            ring.append(ring[0])
            polygon = np.asarray(ring)
            polygon[:, 0] = np.unwrap(polygon[:, 0])
            points[group[j], : len(polygon)] = polygon
            counts[group[j]] = len(polygon)
    return points, counts


@dataclass(frozen=True)
class CvtPrecipitationCoverage:
    cells: SphericalCellCoverage
    geometric_area_km2: np.ndarray
    coordinate_sha256: str
    native_geometry: tuple[int, int, float, float]
    max_raw_target_area_relative_error: float
    max_overlap_change_relative: float
    max_raw_source_parent_area_relative_error: float
    max_source_column_relative_correction: float
    max_final_target_area_relative_error: float
    max_edge_subdivisions: int

    @property
    def metadata(self) -> dict[str, object]:
        return {
            "format": "cvt-precipitation-area-v1",
            "coordinate_sha256": self.coordinate_sha256,
            "native_geometry": list(self.native_geometry),
            "max_raw_target_area_relative_error": self.max_raw_target_area_relative_error,
            "max_overlap_change_relative": self.max_overlap_change_relative,
            "max_raw_source_parent_area_relative_error": (
                self.max_raw_source_parent_area_relative_error
            ),
            "max_source_column_relative_correction": self.max_source_column_relative_correction,
            "max_final_target_area_relative_error": self.max_final_target_area_relative_error,
            "max_edge_subdivisions": self.max_edge_subdivisions,
            "sampling": "spherical area mean over reconstructed CVT cells",
            "target_area_array": "reference_geometry.precipitation_area_km2",
            "area_correction": "native integration-cell columns normalized after geometry checks",
        }

    def check_sites(
        self,
        partition: GaussianParentPartition,
        latitude: np.ndarray,
        longitude: np.ndarray,
    ) -> None:
        if self.coordinate_sha256 != coordinate_fingerprint(
            latitude, longitude
        ) or self.native_geometry != (*partition.shape, partition.radius_km, partition.spacing_km):
            raise ValueError("CVT precipitation coverage differs from source or target geometry")

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        matrix = self.cells.overlap_km2
        with path.open("wb") as stream:
            np.savez_compressed(
                stream,
                metadata=json.dumps(self.metadata),
                data=matrix.data,
                indices=matrix.indices,
                indptr=matrix.indptr,
                area_km2=self.cells.area_km2,
                geometric_area_km2=self.geometric_area_km2,
            )

    @classmethod
    def load(
        cls,
        path: Path,
        partition: GaussianParentPartition,
        latitude: np.ndarray,
        longitude: np.ndarray,
    ) -> CvtPrecipitationCoverage:
        with np.load(path, allow_pickle=False) as archive:
            meta = json.loads(str(archive["metadata"].item()))
            if meta.get("format") != "cvt-precipitation-area-v1":
                raise ValueError("unsupported CVT precipitation coverage format")
            area = np.array(archive["area_km2"], dtype=float)
            exact = np.array(archive["geometric_area_km2"], dtype=float)
            matrix = csr_matrix(
                (archive["data"], archive["indices"], archive["indptr"]),
                shape=(len(latitude), len(partition.area_km2)),
            )
        if (
            area.shape != (len(latitude),)
            or exact.shape != area.shape
            or not np.isfinite(area).all()
            or not np.isfinite(exact).all()
            or (area <= 0).any()
            or (exact <= 0).any()
            or not np.isfinite(matrix.data).all()
            or (matrix.data <= 0).any()
            or not np.allclose(
                np.asarray(matrix.sum(axis=1)).ravel(), area, rtol=16 * np.finfo(float).eps, atol=0
            )
            or not np.allclose(
                np.asarray(matrix.sum(axis=0)).ravel(),
                partition.area_km2,
                rtol=16 * np.finfo(float).eps,
                atol=0,
            )
        ):
            raise ValueError("cached CVT coverage violates its area ledger")
        area.setflags(write=False)
        exact.setflags(write=False)
        coverage = cls(
            SphericalCellCoverage(matrix, area, (len(latitude),)),
            exact,
            meta["coordinate_sha256"],
            tuple(meta["native_geometry"]),
            meta["max_raw_target_area_relative_error"],
            meta["max_overlap_change_relative"],
            meta["max_raw_source_parent_area_relative_error"],
            meta["max_source_column_relative_correction"],
            meta["max_final_target_area_relative_error"],
            meta["max_edge_subdivisions"],
        )
        coverage.check_sites(partition, latitude, longitude)
        return coverage


def cvt_precipitation_coverage(
    partition: GaussianParentPartition,
    latitude: np.ndarray,
    longitude: np.ndarray,
    *,
    relative_tolerance: float = 2e-6,
    max_subdivisions: int = 4096,
) -> CvtPrecipitationCoverage:
    """Build a complete conservative global CVT transfer, with explicit geometry checks.

    Source-column normalization is a numerical area correction applied after
    raw target areas and native-parent coverage pass their geometry checks.
    Target integration areas are the corrected row sums; their differences
    from independent exact Voronoi areas are checked and recorded separately.
    """
    fingerprint = coordinate_fingerprint(latitude, longitude)
    if not 0 < relative_tolerance < 0.01 or max_subdivisions < 2:
        raise ValueError("invalid Voronoi boundary convergence limits")
    lat, lon = np.radians(latitude), np.radians(longitude)
    xyz = np.column_stack([np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)])
    voronoi = SphericalVoronoi(xyz)
    voronoi.sort_vertices_of_regions()
    exact = np.asarray(voronoi.calculate_areas()) * partition.radius_km**2
    if not np.allclose(exact.sum(), partition.area_km2.sum(), rtol=2e-12):
        raise ValueError("Voronoi sites must define a complete spherical partition")
    mu, starts, columns, strides = _native_rows(partition)
    pending = np.arange(len(latitude))
    accepted = []
    max_area_error, max_change = 0.0, 0.0
    subdivisions = 1

    def operator(which: np.ndarray, n: int) -> csr_matrix:
        poly, count = _polygons(voronoi.vertices, voronoi.regions, which, n)
        ptr, idx, areas = _weights(
            poly, count, mu, starts, columns, strides, partition.shape[1], partition.radius_km**2
        )
        return csr_matrix((areas, idx, ptr), shape=(len(which), len(partition.area_km2)))

    previous = operator(pending, subdivisions)
    # Large open-ocean ownership cells span many native parents. Their absolute
    # edge error must also fit within the smallest parent they intersect.
    parent_areas = partition.parent_area_km2[partition.parent_index[previous.indices]]
    minimum_parent_area = np.minimum.reduceat(parent_areas, previous.indptr[:-1])
    local_tolerance = relative_tolerance * np.minimum(1.0, minimum_parent_area / exact)
    pending_area_error = np.full(len(pending), np.inf)
    pending_overlap_change = np.full(len(pending), np.inf)
    while len(pending):
        subdivisions *= 2
        if subdivisions > max_subdivisions:
            raise ValueError(
                "Voronoi overlap geometry failed to converge: "
                f"cells={pending[:8].tolist()}, "
                f"area_error={pending_area_error[:8].tolist()}, "
                f"overlap_change={pending_overlap_change[:8].tolist()}, "
                f"tolerance={local_tolerance[pending][:8].tolist()}, "
                f"area_km2={exact[pending][:8].tolist()}"
            )
        current = operator(pending, subdivisions)
        area_error = abs(np.asarray(current.sum(axis=1)).ravel() / exact[pending] - 1)
        change = np.asarray(abs(current - previous).sum(axis=1)).ravel() / exact[pending]
        good = (area_error <= local_tolerance[pending]) & (change <= local_tolerance[pending])
        if good.any():
            block = current[good].tocoo()
            accepted.append((pending[good][block.row], block.col, block.data))
            max_area_error = max(max_area_error, float(area_error[good].max()))
            max_change = max(max_change, float(change[good].max()))
        pending_area_error, pending_overlap_change = area_error[~good], change[~good]
        pending, previous = pending[~good], current[~good]
    rows, cols, values = (np.concatenate(parts) for parts in zip(*accepted, strict=True))
    overlap = csr_matrix((values, (rows, cols)), shape=(len(latitude), len(partition.area_km2)))
    source_area = np.asarray(overlap.sum(axis=0)).ravel()
    if (source_area <= 0).any():
        raise ValueError("Voronoi transfer must cover every native integration cell")
    raw_parent = np.add.reduceat(source_area - partition.area_km2, partition.offsets[:-1])
    parent_error = float(np.max(abs(raw_parent / partition.parent_area_km2)))
    if parent_error > relative_tolerance:
        raise ValueError("raw Voronoi source coverage exceeds the geometry tolerance")
    correction = float(np.max(abs(partition.area_km2 / source_area - 1)))
    for _ in range(2):
        source_area = np.asarray(overlap.sum(axis=0)).ravel()
        overlap.data *= (partition.area_km2 / source_area)[overlap.indices]
    source_area = np.asarray(overlap.sum(axis=0)).ravel()
    if not np.allclose(source_area, partition.area_km2, rtol=16 * np.finfo(float).eps, atol=0):
        raise ValueError("CVT transfer does not conserve each native integration-cell area")
    target_area = np.asarray(overlap.sum(axis=1)).ravel()
    target_error = float(np.max(abs(target_area / exact - 1)))
    if target_error > relative_tolerance:
        raise ValueError("source area correction exceeds the target geometry tolerance")
    target_area.setflags(write=False)
    exact.setflags(write=False)
    return CvtPrecipitationCoverage(
        SphericalCellCoverage(overlap, target_area, (len(latitude),)),
        exact,
        fingerprint,
        (*partition.shape, partition.radius_km, partition.spacing_km),
        max_area_error,
        max_change,
        parent_error,
        correction,
        target_error,
        subdivisions,
    )
