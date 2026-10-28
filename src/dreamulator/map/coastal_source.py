"""Continuous coastal-stage differences with a prescribed physical profile width.

The first experiment keeps the existing near-coast target and mountain fraction.
They remain empirical source inputs. Spherical distance and footprint integration
remove dependence on a coastal cell centre or a minimum number of grid cells.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import TYPE_CHECKING, Any

import numpy as np

from dreamulator.map.paleo_sutures import lonlat_to_xyz
from dreamulator.map.spherical_terrain import SphericalCoastGeometry, SphericalPointTerrainField
from dreamulator.map.terrain_curve import SphericalTerrainCurve, contour_source_curves
from dreamulator.map.terrain_source import transition_profile

if TYPE_CHECKING:
    from dreamulator.map.shelf_source import ShelfEnvelopeDifferenceSource


class CoastalPlainDifferenceSource:
    """Replace a frozen coastal stage, leaving the other terrain contributions intact.

    Source xyz uses the geological frame (y north). The supplied stage arrays and
    targets share one vertical datum. The new width and endpoint rules are explicit
    source inputs; their production interpretation belongs to the landform model.
    """

    def __init__(
        self,
        xyz: np.ndarray,
        before_m: np.ndarray,
        after_m: np.ndarray,
        lowland_target_m: np.ndarray,
        *,
        width_km: float,
        radius_km: float,
        max_plain_elevation_m: float,
        mountain_fraction: float,
        sea_level_m: float = 0.0,
        provenance: Mapping[str, Any] | None = None,
    ) -> None:
        if not np.isfinite(width_km) or width_km < 0:
            raise ValueError("coastal width must be finite and nonnegative")
        if not np.isfinite(max_plain_elevation_m) or max_plain_elevation_m <= 0:
            raise ValueError("plain elevation scale must be finite and positive")
        if not np.isfinite(mountain_fraction) or not 0 <= mountain_fraction <= 1:
            raise ValueError("mountain fraction must be between zero and one")
        if not np.isfinite(sea_level_m):
            raise ValueError("sea level must be finite")
        arrays = [np.asarray(v, dtype=np.float64) for v in (before_m, after_m, lowland_target_m)]
        if any(v.shape != (len(xyz),) for v in arrays):
            raise ValueError("one height per source point is required")
        self.field = SphericalPointTerrainField(xyz, np.column_stack(arrays))
        if not np.isfinite(radius_km) or radius_km <= 0:
            raise ValueError("radius_km must be finite and positive")
        self.radius_km = float(radius_km)
        self.coast_segments = self.field.contour_segments(sea_level_m, channel=0)
        self.coast_segments.setflags(write=False)
        self.width_km = float(width_km)
        self.max_plain_elevation_m = float(max_plain_elevation_m)
        self.mountain_fraction = float(mountain_fraction)
        self.sea_level_m = float(sea_level_m)
        self._provenance = deepcopy(dict(provenance)) if provenance is not None else None
        self._support_reach_km: float | None = None
        self.coast = (
            SphericalCoastGeometry(self.coast_segments, radius_km)
            if len(self.coast_segments)
            else None
        )

    def query(self, lat: np.ndarray, lon: np.ndarray) -> dict[str, np.ndarray]:
        """Return the reference stage, replacement and distance in their source datum."""
        lat, lon = np.broadcast_arrays(lat, lon)
        q = lonlat_to_xyz(np.column_stack([lon.ravel(), lat.ravel()]))
        values = self.field(q)
        before, after, target = values.T
        distance = np.full(len(q), np.inf)
        land = before > self.sea_level_m
        if self.width_km > 0 and self.coast is not None and land.any():
            distance[land] = self.coast.distance_km(q[land], maximum_km=self.width_km)
        replacement = self.apply_profile(before, target, distance)
        return {
            "before_m": before.reshape(lat.shape),
            "after_m": after.reshape(lat.shape),
            "replacement_m": replacement.reshape(lat.shape),
            "distance_km": distance.reshape(lat.shape),
            "delta_m": (replacement - after).reshape(lat.shape),
        }

    def apply_profile(
        self, before: np.ndarray, target: np.ndarray, distance: np.ndarray
    ) -> np.ndarray:
        """Apply the declared shore profile to an incoming surface and its own coast distance."""
        before, target, distance = np.broadcast_arrays(
            np.asarray(before, dtype=np.float64),
            np.asarray(target, dtype=np.float64),
            np.asarray(distance, dtype=np.float64),
        )
        if not np.isfinite(before).all() or not np.isfinite(target).all():
            raise ValueError("coastal input and targets must be finite")
        if np.isnan(distance).any() or (distance < 0).any():
            raise ValueError("coastal distances must be nonnegative or unbounded")
        replacement = before.copy()
        changed = (before > self.sea_level_m) & (distance < self.width_km)
        if changed.any():
            factor = np.clip(
                1 - (before[changed] - self.sea_level_m) / self.max_plain_elevation_m, 0, 1
            )
            mountain_edge = self.sea_level_m + self.mountain_fraction * (
                before[changed] - self.sea_level_m
            )
            edge = target[changed] * factor + mountain_edge * (1 - factor)
            replacement[changed] = np.maximum(
                target[changed],
                transition_profile(distance[changed], self.width_km, edge, before[changed]),
            )
        return replacement

    def evaluate(self, lat: np.ndarray, lon: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        delta = self.query(lat, lon)["delta_m"]
        return delta, np.zeros(delta.shape)

    def footprint_support(
        self,
        lat: np.ndarray,
        lon: np.ndarray,
        half_diagonal_km: float,
        radius_km: float,
    ) -> np.ndarray:
        """Bound both the new shore profile and the old interpolated stage change."""
        if not np.isfinite(half_diagonal_km) or half_diagonal_km < 0:
            raise ValueError("footprint half diagonal must be finite and nonnegative")
        if radius_km != self.radius_km:
            raise ValueError("footprint and coastal source radii must match")
        lat, lon = np.broadcast_arrays(lat, lon)
        if self.coast is None:
            # Without a shoreline, the old stage may still contain a frozen change.
            return np.full(lat.shape, np.any(self.field.values[:, 0] != self.field.values[:, 1]))
        if self._support_reach_km is None:
            points, faces = self.field.points, self.field.faces
            edge_km = 0.0
            for a, b in ((0, 1), (1, 2), (2, 0)):
                cosine = np.sum(points[faces[:, a]] * points[faces[:, b]], axis=1)
                edge_km = max(
                    edge_km, float(np.arccos(np.clip(cosine, -1, 1)).max()) * self.radius_km
                )
            changed = self.field.values[:, 0] != self.field.values[:, 1]
            old_reach = (
                float(self.coast.distance_km(points[changed]).max()) if changed.any() else 0.0
            )
            self._support_reach_km = max(self.width_km, old_reach) + edge_km
        q = lonlat_to_xyz(np.column_stack([lon.ravel(), lat.ravel()]))
        distance = self.coast.distance_km(q, maximum_km=self._support_reach_km + half_diagonal_km)
        return np.asarray(np.isfinite(distance).reshape(lat.shape), dtype=bool)

    def terrain_curves(
        self, reference_id: str, *, epoch_myr: float | None = None
    ) -> list[SphericalTerrainCurve]:
        """Export connected reference-stage shores with explicit coarse-source evidence."""
        return contour_source_curves(
            self.field,
            self.sea_level_m,
            self.radius_km,
            reference_id,
            channel=0,
            epoch_myr=epoch_myr,
        )

    @property
    def metadata(self) -> dict[str, Any]:
        result = {
            "kind": "coastal-stage-difference-v1",
            "point_reconstruction_sha256": self.field.sha256,
            "geometry_sha256": None if self.coast is None else self.coast.geometry.sha256,
            "radius_km": getattr(self, "radius_km", None),
            "width_km": self.width_km,
            "max_plain_elevation_m": self.max_plain_elevation_m,
            "mountain_fraction": self.mountain_fraction,
            "sea_level_m": self.sea_level_m,
            "profile_policy": "fixed legacy target inputs; continuous spherical shore distance",
            "transfer_policy": (
                "replacement stage minus independently reconstructed reference stage"
            ),
            "input_precision": "coarse geological samples and derived shoreline",
        }
        if self._provenance is not None:
            result["native_provenance"] = deepcopy(self._provenance)
        return result


def coastal_source_from_native(
    fields: Mapping[str, np.ndarray],
    metadata: Mapping[str, Any],
    *,
    width_km: float,
    max_plain_elevation_m: float,
    mountain_fraction: float,
    profile_reference: str,
) -> CoastalPlainDifferenceSource:
    """Reconstruct the frozen coastal trial from a verified geological archive.

    Width and endpoint parameters remain explicit caller inputs. The reference
    identifies their source; local landform interpretation is a separate contract.
    The native target array retains the original numerical realization.
    """
    if not profile_reference.strip():
        raise ValueError("coastal profile inputs require a source reference")
    if metadata.get("format") != "terrain-source-fields-v1":
        raise ValueError("coastal source requires a verified native terrain archive")
    required = (
        "xyz",
        "after_shelf_m",
        "before_coastal_plain_m",
        "after_coastal_plain_m",
        "coastal_lowland_target_m",
    )
    if any(name not in fields for name in required):
        raise ValueError("native coastal source is missing its stage endpoints or targets")
    if len(fields["xyz"]) != metadata.get("cell_count"):
        raise ValueError("native coastal source size differs from the archive declaration")
    if not np.array_equal(fields["after_shelf_m"], fields["before_coastal_plain_m"]):
        raise ValueError("native shelf endpoint and coastal input must share the same stage")
    origin = metadata.get("source")
    if not isinstance(origin, Mapping) or not origin.get("terrain_fingerprint"):
        raise ValueError("native coastal source requires its geological reference fingerprint")
    return CoastalPlainDifferenceSource(
        fields["xyz"],
        fields["before_coastal_plain_m"],
        fields["after_coastal_plain_m"],
        fields["coastal_lowland_target_m"],
        width_km=width_km,
        radius_km=float(metadata["radius_km"]),
        max_plain_elevation_m=max_plain_elevation_m,
        mountain_fraction=mountain_fraction,
        sea_level_m=float(origin["sea_level_m"]),
        provenance={
            "archive_sha256": metadata["sha256"],
            "terrain_fingerprint": origin["terrain_fingerprint"],
            "profile_reference": profile_reference,
            "stage_before": "before_coastal_plain_m",
            "stage_after": "after_coastal_plain_m",
            "target_source": "frozen coastal_lowland_target_m numerical realization",
            "scope": "native numerical-stage reconstruction; local landform basis separate",
        },
    )


class ShelfCoastalDifferenceSource:
    """Consume the shelf surface and its verified shoreline before applying the coastal profile."""

    def __init__(
        self,
        shelf: ShelfEnvelopeDifferenceSource,
        coastal: CoastalPlainDifferenceSource,
        shoreline: SphericalCoastGeometry,
        *,
        shoreline_reference: str,
    ) -> None:
        if not shoreline_reference.strip():
            raise ValueError("joint coastal source requires its shoreline reference")
        if shelf.radius_km != coastal.radius_km or shoreline.radius_km != coastal.radius_km:
            raise ValueError("joint stage sources must share their spherical radius")
        if shelf.sea_level_m != coastal.sea_level_m:
            raise ValueError("joint stage sources must share their vertical datum")
        if (
            shelf.field.points.shape != coastal.field.points.shape
            or not np.allclose(shelf.field.points, coastal.field.points, rtol=0, atol=1e-12)
            or not np.array_equal(shelf.field.values[:, 1], coastal.field.values[:, 0])
        ):
            raise ValueError("shelf reference endpoint and coastal reference input must agree")
        self.shelf, self.coastal, self.shoreline = shelf, coastal, shoreline
        self.shoreline_reference = shoreline_reference

    def query(self, lat: np.ndarray, lon: np.ndarray) -> dict[str, np.ndarray]:
        lat, lon = np.broadcast_arrays(lat, lon)
        xyz = lonlat_to_xyz(np.column_stack([lon.ravel(), lat.ravel()]))
        incoming = self.shelf.query(lat, lon)["replacement_m"].ravel()
        values = self.coastal.field(xyz)
        distance = np.full(len(xyz), np.inf)
        land = incoming > self.coastal.sea_level_m
        if self.coastal.width_km > 0 and land.any():
            distance[land] = self.shoreline.distance_km(xyz[land], maximum_km=self.coastal.width_km)
        output = self.coastal.apply_profile(incoming, values[:, 2], distance)
        return {
            "incoming_m": incoming.reshape(lat.shape),
            "replacement_m": output.reshape(lat.shape),
            "reference_after_m": values[:, 1].reshape(lat.shape),
            "distance_km": distance.reshape(lat.shape),
            "delta_m": (output - values[:, 1]).reshape(lat.shape),
        }

    def evaluate(self, lat: np.ndarray, lon: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        delta = self.query(lat, lon)["delta_m"]
        return delta, np.zeros(delta.shape)

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "kind": "sequential-shelf-coastal-stage-difference-v1",
            "shelf": self.shelf.metadata,
            "coastal": self.coastal.metadata,
            "shoreline_sha256": self.shoreline.geometry.sha256,
            "shoreline_reference": self.shoreline_reference,
            "stage_order": "shelf surface, shared shoreline, coastal profile",
            "transfer_policy": "combined coastal surface minus native coastal endpoint",
        }
