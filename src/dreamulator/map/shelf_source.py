"""Continuous shelf profiles combined with their actual pre-shelf background.

The profile is a geometric envelope using existing shelf-width and lowstand
inputs. Its elevation integral describes a geometric replacement, while a
sediment supply and erosion history belong to a separate process budget.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any, Literal

import numpy as np
from scipy.spatial import cKDTree

from .paleo_sutures import lonlat_to_xyz
from .spherical_terrain import SphericalCoastGeometry, SphericalPointTerrainField
from .terrain_curve import SphericalTerrainCurve, contour_source_curves


class ShelfEnvelopeDifferenceSource:
    """Replace frozen shelf endpoints with a coast-anchored continuous envelope.

    Coast width and the existing small profile modulation are reconstructed
    from their actual source fields. Heights and all stage endpoints share
    one datum. The true shoreline has zero water depth. The retained original
    background bounds the envelope from below and supplies its outer contact.
    """

    def __init__(
        self,
        xyz: np.ndarray,
        before_m: np.ndarray,
        after_m: np.ndarray,
        coast_width_m: np.ndarray,
        profile_noise_fraction: np.ndarray,
        *,
        radius_km: float,
        shelf_break_depth_m: float,
        slope_m_per_km: float,
        active_flexure_mask: np.ndarray | None = None,
        sea_level_m: float = 0.0,
        protection_policy: Literal["nearest-cell", "source-weight"] = "nearest-cell",
        provenance: Mapping[str, Any] | None = None,
    ) -> None:
        if not np.isfinite(radius_km) or radius_km <= 0:
            raise ValueError("radius must be finite and positive")
        if not np.isfinite(shelf_break_depth_m) or shelf_break_depth_m <= 0:
            raise ValueError("shelf break depth must be finite and positive")
        if not np.isfinite(slope_m_per_km) or slope_m_per_km <= 0:
            raise ValueError("slope must be finite and positive")
        if not np.isfinite(sea_level_m):
            raise ValueError("sea level must be finite")
        if protection_policy not in ("nearest-cell", "source-weight"):
            raise ValueError("unknown shelf protection policy")
        arrays = [
            np.asarray(v, dtype=np.float64)
            for v in (
                before_m,
                after_m,
                coast_width_m,
                profile_noise_fraction,
            )
        ]
        if any(v.shape != (len(xyz),) for v in arrays):
            raise ValueError("shelf source needs one value per point")
        if not all(np.isfinite(v).all() for v in arrays):
            raise ValueError("shelf source values must be finite")
        if (arrays[2] < 0).any() or (abs(arrays[3]) >= 1).any():
            raise ValueError("width must be nonnegative and noise magnitude below one")
        protected = (
            np.zeros(len(xyz), dtype=bool)
            if active_flexure_mask is None
            else np.array(active_flexure_mask, dtype=bool, copy=True)
        )
        if protected.shape != (len(xyz),):
            raise ValueError("active flexure mask must match the source points")
        channels = arrays
        if protection_policy == "source-weight":
            channels = [*arrays, (~protected).astype(np.float64)]
        self.field = SphericalPointTerrainField(xyz, np.column_stack(channels))
        self.radius_km = float(radius_km)
        self.shelf_break_depth_m = float(shelf_break_depth_m)
        self.slope_m_per_km = float(slope_m_per_km)
        self.sea_level_m = float(sea_level_m)
        self.coast_segments = self.field.contour_segments(sea_level_m, channel=0)
        self.coast_segments.setflags(write=False)
        self.coast = (
            SphericalCoastGeometry(self.coast_segments, radius_km)
            if len(self.coast_segments)
            else None
        )
        protected.setflags(write=False)
        self.protected = protected
        self.protection_policy = protection_policy
        self._provenance = deepcopy(dict(provenance)) if provenance is not None else None
        self._tree = (
            cKDTree(self.field.points)
            if protected.any() and protection_policy == "nearest-cell"
            else None
        )
        self.maximum_width_km = float(arrays[2].max() / 1000)
        self.reach_km = self.maximum_width_km + max(
            0.0, self.sea_level_m - float(arrays[0].min())
        ) / (self.slope_m_per_km * (1 - float(abs(arrays[3]).max())))

    def query(self, lat: np.ndarray, lon: np.ndarray) -> dict[str, np.ndarray]:
        """Query one frozen geometric replacement independently of canvas sampling."""
        lat, lon = np.broadcast_arrays(lat, lon)
        xyz = lonlat_to_xyz(np.column_stack([lon.ravel(), lat.ravel()]))
        values = self.field(xyz)
        before, after, width_m, noise = values[:, :4].T
        distance = np.full(len(xyz), np.inf)
        eligible = np.ones(len(xyz), dtype=bool)
        if self._tree is not None:
            eligible &= ~self.protected[self._tree.query(xyz)[1]]
        shelf_fraction = (
            np.clip(values[:, 4], 0, 1)
            if self.protection_policy == "source-weight"
            else eligible.astype(np.float64)
        )
        marine = (before <= self.sea_level_m) & eligible
        replacement = before.copy()
        if self.coast is not None and marine.any():
            distance[marine] = self.coast.distance_km(xyz[marine], maximum_km=self.reach_km)
            ids = np.flatnonzero(marine & np.isfinite(distance))
            d, width = distance[ids], width_m[ids] / 1000
            on_shelf = (width > 0) & (d <= width)
            depth = self.shelf_break_depth_m + np.maximum(d - width, 0) * self.slope_m_per_km
            depth[on_shelf] = self.shelf_break_depth_m * d[on_shelf] / width[on_shelf]
            # A zero-width profile has its slope starting at the true shore.
            depth[width == 0] = d[width == 0] * self.slope_m_per_km
            profile = self.sea_level_m - depth * (1 + noise[ids])
            replacement[ids] = np.maximum(before[ids], profile)
        if self.protection_policy == "source-weight":
            # Mixed source triangles carry a numerical eligibility fraction;
            # their physical subcell material boundary remains unresolved.
            replacement = after + shelf_fraction * (replacement - after)
            eligible = shelf_fraction > 0
        else:
            # The incoming-plate footprint retains the actual original shelf stage.
            replacement[~eligible] = after[~eligible]
        delta = replacement - after
        result = {
            key: value.reshape(lat.shape)
            for key, value in (
                ("before_m", before),
                ("after_m", after),
                ("replacement_m", replacement),
                ("delta_m", delta),
                ("distance_km", distance),
                ("width_km", width_m / 1000),
                ("protected_mask", ~eligible),
            )
        }
        if self.protection_policy == "source-weight":
            result["shelf_fraction"] = shelf_fraction.reshape(lat.shape)
        return result

    def evaluate(self, lat: np.ndarray, lon: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        delta = self.query(lat, lon)["delta_m"]
        return delta, np.zeros(delta.shape)

    def terrain_curves(
        self, reference_id: str, *, epoch_myr: float | None = None
    ) -> list[SphericalTerrainCurve]:
        """Export the actual pre-shelf reference shoreline as connected source curves."""
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
        result: dict[str, Any] = {
            "kind": "continuous-shelf-envelope-difference-v1",
            "point_reconstruction_sha256": self.field.sha256,
            "geometry_sha256": None if self.coast is None else self.coast.geometry.sha256,
            "radius_km": self.radius_km,
            "sea_level_m": self.sea_level_m,
            "shelf_break_depth_m": self.shelf_break_depth_m,
            "slope_m_per_km": self.slope_m_per_km,
            "maximum_width_km": self.maximum_width_km,
            "profile_policy": "zero depth at geometric shore; existing width/modulation fields",
            "background_policy": "maximum with actual pre-shelf surface; geometric envelope",
            "transfer_policy": "replacement shelf stage minus reconstructed actual shelf endpoint",
            "active_policy": "original incoming-plate CVT footprint retained",
            "parameter_reconstruction": "continuous original width and noise fields at query point",
            "budget_scope": "geometric elevation integral; sediment and erosion budgets separate",
            "input_precision": "200k point reconstruction plus existing shelf profile inputs",
        }
        if self.protection_policy == "source-weight":
            result.update(
                {
                    "kind": "continuous-shelf-stage-composition-v1",
                    "active_policy": "continuous source weights of original protection indicator",
                    "protection_weight_basis": (
                        "positive source-triangle reconstruction of frozen native eligibility; "
                        "numerical fraction, subcell material boundary unresolved"
                    ),
                    "stage_composition": "reference + eligibility * (new envelope - reference)",
                }
            )
        if self._provenance is not None:
            result["native_provenance"] = deepcopy(self._provenance)
        return result


def shelf_source_from_native(
    fields: Mapping[str, np.ndarray],
    metadata: Mapping[str, Any],
    *,
    shelf_break_depth_m: float,
    slope_m_per_km: float,
    profile_reference: str,
    protection_policy: Literal["nearest-cell", "source-weight"] = "source-weight",
) -> ShelfEnvelopeDifferenceSource:
    """Prepare the shelf trial from its actual stage archive and explicit profile basis."""
    if metadata.get("format") != "terrain-source-fields-v1" or not profile_reference.strip():
        raise ValueError("shelf source requires a verified archive and profile reference")
    required = (
        "xyz",
        "before_shelf_m",
        "after_shelf_m",
        "before_coastal_plain_m",
        "shelf_coast_width_m",
        "shelf_noise_fraction",
        "subducting_mask",
        "shelf_continental_crust_mask",
    )
    if any(name not in fields for name in required):
        raise ValueError("native shelf source is missing actual stage fields")
    if len(fields["xyz"]) != metadata.get("cell_count"):
        raise ValueError("native shelf source size differs from its archive")
    if not np.array_equal(fields["after_shelf_m"], fields["before_coastal_plain_m"]):
        raise ValueError("native shelf output and coastal input must share the same stage")
    for name in ("subducting_mask", "shelf_continental_crust_mask"):
        if fields[name].dtype.kind != "b" or fields[name].shape != (len(fields["xyz"]),):
            raise ValueError("native shelf stage masks must be boolean source arrays")
    origin = metadata.get("source")
    if not isinstance(origin, Mapping) or not origin.get("terrain_fingerprint"):
        raise ValueError("native shelf source requires its geological reference fingerprint")
    return ShelfEnvelopeDifferenceSource(
        fields["xyz"],
        fields["before_shelf_m"],
        fields["after_shelf_m"],
        fields["shelf_coast_width_m"],
        fields["shelf_noise_fraction"],
        radius_km=float(metadata["radius_km"]),
        shelf_break_depth_m=shelf_break_depth_m,
        slope_m_per_km=slope_m_per_km,
        sea_level_m=float(origin["sea_level_m"]),
        active_flexure_mask=fields["subducting_mask"],
        protection_policy=protection_policy,
        provenance={
            "archive_sha256": metadata["sha256"],
            "terrain_fingerprint": origin["terrain_fingerprint"],
            "profile_reference": profile_reference,
            "stage_before": "before_shelf_m",
            "stage_after": "after_shelf_m",
            "crust_field": "shelf_continental_crust_mask",
            "protection_field": "subducting_mask",
            "scope": "native numerical-stage reconstruction; subcell material basis separate",
        },
    )
