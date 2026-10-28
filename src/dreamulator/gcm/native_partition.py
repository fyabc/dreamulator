"""Complete native Gaussian parents for area-conserving precipitation refinement.

Parent areas use the model's Gaussian quadrature. Latitude/longitude subcells
cover every parent, including both poles and the periodic seam. Their positive
solid-angle areas are normalized to the parent quadrature at rounding precision.
These are integration cells; their spacing adds no geological observations.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from pathlib import Path

PRECIPITATION_FORMAT = "native-precipitation-v1"


@dataclass(frozen=True)
class GaussianParentPartition:
    radius_km: float
    spacing_km: float
    shape: tuple[int, int]
    mu_edges: np.ndarray
    offsets: np.ndarray
    nrows: np.ndarray
    ncols: np.ndarray
    parent_index: np.ndarray
    parent_area_km2: np.ndarray
    area_km2: np.ndarray
    latitude: np.ndarray
    longitude: np.ndarray
    area_roundoff_relative_max: float

    def parent_integrals(self, values: np.ndarray) -> np.ndarray:
        """Integrate a complete child field over each native parent."""
        v = np.asarray(values, dtype=np.float64)
        if v.ndim < 1 or v.shape[-1] != len(self.area_km2) or not np.isfinite(v).all():
            raise ValueError("child values must be finite and cover the complete partition")
        result: np.ndarray = np.add.reduceat(v * self.area_km2, self.offsets[:-1], axis=-1)
        return result

    def conservative_depths(
        self, native_mm: np.ndarray, *, prior_mm: np.ndarray | None = None
    ) -> np.ndarray:
        """Allocate native depths within parents with a nonnegative optional prior.

        Without a prior, retain the parent constant. Otherwise preserve the
        prior's relative shape and normalize its complete area integral to the
        native quota. A zero prior uses the parent constant; a dry parent remains
        dry. This numerical baseline precedes weather-dependent share closure.
        """
        native = np.asarray(native_mm, dtype=np.float64)
        if (
            native.ndim < 1
            or native.shape[-1] != len(self.parent_area_km2)
            or not np.isfinite(native).all()
            or (native < 0).any()
        ):
            raise ValueError("native precipitation must be nonnegative and cover all parents")
        constant = native[..., self.parent_index]
        if prior_mm is None:
            return constant
        prior = np.asarray(prior_mm, dtype=np.float64)
        if prior.shape != constant.shape or not np.isfinite(prior).all() or (prior < 0).any():
            raise ValueError("prior must be nonnegative and cover the complete child field")
        mean = self.parent_integrals(prior) / self.parent_area_km2
        scale = np.divide(native, mean, out=np.zeros_like(mean), where=mean > 0)
        result = np.where(
            mean[..., self.parent_index] > 0, prior * scale[..., self.parent_index], constant
        )
        # A second scaling removes rounding in the complete parent sum.
        actual = self.parent_integrals(result) / self.parent_area_km2
        correction = np.divide(
            native, actual, out=np.ones_like(actual), where=(actual > 0) & (mean > 0)
        )
        result *= correction[..., self.parent_index]
        return np.asarray(result)

    def locate(self, latitude: np.ndarray, longitude: np.ndarray) -> np.ndarray:
        """Find the integration child containing each finite geographic point."""
        lat, lon = np.broadcast_arrays(latitude, longitude)
        if not np.isfinite(lat).all() or not np.isfinite(lon).all() or (abs(lat) > 90).any():
            raise ValueError("query coordinates must be finite geographic points")
        nlat, nlon = self.shape
        row = np.clip(
            np.searchsorted(self.mu_edges, np.sin(np.radians(lat)), side="right") - 1, 0, nlat - 1
        )
        x = ((lon + 180.0 / nlon) % 360.0) / (360.0 / nlon)
        col = np.minimum(np.floor(x).astype(np.int64), nlon - 1)
        parent = row * nlon + col
        low, high = (
            np.degrees(np.arcsin(self.mu_edges[row])),
            np.degrees(np.arcsin(self.mu_edges[row + 1])),
        )
        child_row = np.clip(
            np.floor((lat - low) / (high - low) * self.nrows[parent]).astype(np.int64),
            0,
            self.nrows[parent] - 1,
        )
        child_col = np.clip(
            np.floor((x - col) * self.ncols[parent]).astype(np.int64), 0, self.ncols[parent] - 1
        )
        return np.asarray(self.offsets[parent] + child_row * self.ncols[parent] + child_col)


def gaussian_parent_partition(
    latitude: np.ndarray,
    longitude: np.ndarray,
    *,
    radius_km: float,
    spacing_km: float,
) -> GaussianParentPartition:
    """Build positive subcells of a complete ascending Gaussian/periodic grid."""
    lat, lon = np.asarray(latitude, dtype=np.float64), np.asarray(longitude, dtype=np.float64)
    if lat.ndim != 1 or lon.ndim != 1 or len(lat) < 2 or len(lon) < 2:
        raise ValueError("native coordinates must describe a complete two-dimensional grid")
    if (
        not np.isfinite(radius_km)
        or radius_km <= 0
        or not np.isfinite(spacing_km)
        or spacing_km <= 0
    ):
        raise ValueError("radius and integration spacing must be positive and finite")
    mu, weights = np.polynomial.legendre.leggauss(len(lat))
    if not np.allclose(lat, np.degrees(np.arcsin(mu)), rtol=0, atol=2e-5):
        raise ValueError("native latitude must be the complete ascending Gaussian grid")
    if not np.allclose(lon, np.arange(len(lon)) * 360 / len(lon), rtol=0, atol=1e-8):
        raise ValueError("native longitude must be complete, uniform and start at zero")
    edges = np.concatenate([[-1.0], -1.0 + np.cumsum(weights)])
    edges[-1] = 1.0
    phi = np.arcsin(edges)
    dlon = 2 * np.pi / len(lon)
    parent_area = np.repeat(weights * radius_km**2 * dlon, len(lon))
    rows, cols, areas, latitudes, longitudes, parents = [], [], [], [], [], []
    roundoff = 0.0
    for i in range(len(lat)):
        nr = max(1, int(np.ceil(radius_km * (phi[i + 1] - phi[i]) / spacing_km)))
        nearest_equator = 0.0 if phi[i] <= 0 <= phi[i + 1] else min(abs(phi[i]), abs(phi[i + 1]))
        nc = max(1, int(np.ceil(radius_km * np.cos(nearest_equator) * dlon / spacing_km)))
        sub_phi = np.linspace(phi[i], phi[i + 1], nr + 1)
        sub_mu = np.sin(sub_phi)
        sub_mu[[0, -1]] = edges[[i, i + 1]]
        solid = np.diff(sub_mu)[:, None] * np.full((1, nc), dlon / nc)
        geometric_area = solid * radius_km**2
        target = weights[i] * radius_km**2 * dlon
        factor = target / float(geometric_area.sum())
        roundoff = max(roundoff, abs(factor - 1))
        if abs(factor - 1) > 1e-9:
            raise ValueError("child geometry differs from native Gaussian area beyond rounding")
        areas.append(np.tile((geometric_area * factor).ravel(), len(lon)))
        centres_lat = np.degrees(np.arcsin((sub_mu[:-1] + sub_mu[1:]) / 2))
        latitudes.append(np.tile(np.repeat(centres_lat, nc), len(lon)))
        centres_lon = (
            lon[:, None] - 180 / len(lon) + (np.arange(nc) + 0.5)[None, :] * 360 / len(lon) / nc
        )
        longitudes.append(np.repeat(centres_lon[:, None, :], nr, axis=1).ravel() % 360)
        parents.append(np.repeat(i * len(lon) + np.arange(len(lon)), nr * nc))
        rows.extend([nr] * len(lon))
        cols.extend([nc] * len(lon))
    nrows, ncols = np.asarray(rows, dtype=np.int64), np.asarray(cols, dtype=np.int64)
    arrays = [
        edges,
        np.concatenate([[0], np.cumsum(nrows * ncols)]),
        nrows,
        ncols,
        np.concatenate(parents),
        parent_area,
        np.concatenate(areas),
        np.concatenate(latitudes),
        np.concatenate(longitudes),
    ]
    for array in arrays:
        array.setflags(write=False)
    return GaussianParentPartition(
        float(radius_km),
        float(spacing_km),
        (len(lat), len(lon)),
        edges,
        arrays[1],
        nrows,
        ncols,
        arrays[4],
        parent_area,
        arrays[6],
        arrays[7],
        arrays[8],
        roundoff,
    )


@dataclass(frozen=True)
class NativePrecipitationField:
    """Full-sphere monthly prl/prc depths, with native component budgets.

    The area ledger is the complete Gaussian partition. Geographic queries
    return its piecewise-constant field; a sampled raster is a point view, and
    its pixel sum is not a substitute for integrating the native partition.
    """

    partition: GaussianParentPartition
    native_component_mm: np.ndarray  # (2, 12, parents), prl then prc
    component_monthly_mm: np.ndarray  # (2, 12, children)
    provenance: dict[str, Any]

    def __post_init__(self) -> None:
        p = self.partition
        native = np.array(self.native_component_mm, dtype=np.float64, copy=True)
        depths = np.array(self.component_monthly_mm, dtype=np.float64, copy=True)
        if native.shape != (2, 12, len(p.parent_area_km2)) or depths.shape != (
            2,
            12,
            len(p.area_km2),
        ):
            raise ValueError(
                "precipitation must cover both components, twelve months and all areas"
            )
        if not np.isfinite(native).all() or not np.isfinite(depths).all():
            raise ValueError("precipitation must be finite")
        if (native < 0).any() or (depths < 0).any():
            raise ValueError("precipitation must be nonnegative")
        expected = native * p.parent_area_km2
        actual = p.parent_integrals(depths)
        if (abs(actual - expected) > 32 * np.finfo(float).eps * expected).any():
            raise ValueError("precipitation does not conserve every native component/month budget")
        native.setflags(write=False)
        depths.setflags(write=False)
        object.__setattr__(self, "native_component_mm", native)
        object.__setattr__(self, "component_monthly_mm", depths)

    def sample_monthly(self, latitude: np.ndarray, longitude: np.ndarray) -> np.ndarray:
        """Total precipitation in mm/reference-month, shape (12, *query_shape)."""
        index = self.partition.locate(latitude, longitude)
        return np.asarray(self.component_monthly_mm[:, :, index].sum(axis=0))

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            **self.provenance,
            "format": PRECIPITATION_FORMAT,
            "components": ["prl", "prc"],
            "basis": "mm per reference month (365.25/12 days)",
            "spacing_km": self.partition.spacing_km,
            "radius_km": self.partition.radius_km,
            "area_ledger": "complete Gaussian parent partition, including land and sea",
            "sampling": "piecewise constant native integration child at geographic point",
        }

    def save(self, path: Path) -> None:
        """Save one self-contained float64 field; no NetCDF dependency on read."""
        p = self.partition
        mu, _ = np.polynomial.legendre.leggauss(p.shape[0])
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as stream:
            np.savez_compressed(
                stream,
                metadata=np.asarray(json.dumps(self.metadata)),
                latitude=np.degrees(np.arcsin(mu)),
                longitude=np.arange(p.shape[1]) * 360.0 / p.shape[1],
                native_component_mm=self.native_component_mm,
                component_monthly_mm=self.component_monthly_mm,
            )

    @classmethod
    def load(cls, path: Path) -> NativePrecipitationField:
        """Rebuild the complete geometry and check budgets before consumption."""
        with np.load(path, allow_pickle=False) as archive:
            metadata = json.loads(str(archive["metadata"].item()))
            if metadata.get("format") != PRECIPITATION_FORMAT:
                raise ValueError("unsupported native precipitation format")
            partition = gaussian_parent_partition(
                archive["latitude"],
                archive["longitude"],
                radius_km=metadata["radius_km"],
                spacing_km=metadata["spacing_km"],
            )
            return cls(
                partition, archive["native_component_mm"], archive["component_monthly_mm"], metadata
            )
