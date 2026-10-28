"""Continuous collision profiles with an explicit frozen-stage replacement.

The along-axis field preserves the retained-shortening integral. The profile
uses the existing Airy cross-section, flank slopes and force-balance cap.
Its difference replaces one selected contribution inside the existing
active/paleo maximum envelope. Downstream stage responses and crust coverage
are supplied as frozen references, independently of a target canvas.
"""

from __future__ import annotations

import hashlib
from copy import copy
from dataclasses import replace
from typing import TYPE_CHECKING, Any, Literal, Protocol, Self

import numpy as np
from scipy.spatial import cKDTree

from .orogen_profile import (
    _AIRY_THICKENING_PER_ELEVATION,
    _ALONG_STRIKE_KM,
    _PRO_SLOPE_DEG,
    _REFERENCE_CRUST_KM,
    _RETRO_SLOPE_DEG,
    collision_cap_m,
)
from .orogen_transfer import ConservativeArcField
from .paleo_sutures import lonlat_to_xyz
from .terrain_source import SphericalSegmentGeometry

CollisionParameterPolicy = Literal["conservative_arc", "known_contact_vertices"]

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .orogen_contract import OrogenContract
    from .paleo_sutures import AuthorSuture
    from .terrain_source import SphericalProjection


class OrogenProfileField(Protocol):
    """A frozen relief profile queried in the geological unit-vector frame."""

    def __call__(self, xyz: np.ndarray) -> np.ndarray: ...

    @property
    def metadata(self) -> dict[str, Any]: ...


class OrogenEnvelopeProfileField:
    """Evaluate selected profiles using the synthesis's existing maximum rule."""

    def __init__(self, profiles: Mapping[str, OrogenProfileField]) -> None:
        if not profiles or any(not name for name in profiles):
            raise ValueError("an orogen envelope requires named profiles")
        self.profiles = tuple(sorted(profiles.items()))

    def __call__(self, xyz: np.ndarray) -> np.ndarray:
        envelope = np.zeros(np.asarray(xyz).shape[:-1], dtype=np.float64)
        for _, profile in self.profiles:
            value = np.asarray(profile(xyz), dtype=np.float64)
            if value.shape != envelope.shape or not np.isfinite(value).all() or np.any(value < 0):
                raise ValueError("orogen profiles must supply finite nonnegative query relief")
            np.maximum(envelope, value, out=envelope)
        return envelope

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "kind": "selected-orogen-envelope-v1",
            "combination": "maximum of selected active and paleo profiles",
            "profiles": {name: profile.metadata for name, profile in self.profiles},
        }


class PaleoProfileField:
    """An authored old belt using the existing erosion decay and active wedge width."""

    def __init__(self, suture: AuthorSuture, active_crest_m: float, radius_km: float) -> None:
        path = np.array(suture.path, dtype=np.float64, copy=True)
        if path.ndim != 2 or path.shape[1:] != (2,) or len(path) < 2:
            raise ValueError("an old belt requires at least two author path points")
        if not np.isfinite(path).all() or np.any(np.abs(path[:, 1]) > 90):
            raise ValueError("author path coordinates must be finite with valid latitudes")
        age = suture.collision_age_myr
        if age is None or not np.isfinite(age) or age < 0:
            raise ValueError("an old belt requires a finite nonnegative collision age")
        if not np.isfinite(active_crest_m) or active_crest_m < 0:
            raise ValueError("active crest must be finite and nonnegative")
        if not np.isfinite(radius_km) or radius_km <= 0:
            raise ValueError("radius must be positive and finite")
        path.setflags(write=False)
        self.suture = replace(suture, path=path)
        self.active_crest_m = float(active_crest_m)
        self.radius_km = float(radius_km)

    def __call__(self, xyz: np.ndarray) -> np.ndarray:
        from .paleo_orogens import paleo_orogen_field

        return paleo_orogen_field(xyz, [self.suture], self.active_crest_m, self.radius_km)

    @property
    def metadata(self) -> dict[str, Any]:
        from .paleo_orogens import DECAY_MYR, RESIDUAL_CREST_M

        return {
            "kind": "paleo-orogen-profile-v1",
            "suture": self.suture.id,
            "path_lonlat_deg": self.suture.path.tolist(),
            "collision_age_myr": self.suture.collision_age_myr,
            "active_crest_m": self.active_crest_m,
            "radius_km": self.radius_km,
            "decay_myr": DECAY_MYR,
            "residual_crest_m": RESIDUAL_CREST_M,
            "profile_basis": "author path and age, existing decay fit and active wedge width",
        }


class _CollisionWedge:
    """Shared Airy cross-section for the accepted collision reconstructions."""

    geometry: SphericalSegmentGeometry

    def __init__(
        self,
        radius_km: float,
        gravity_m_s2: float,
        base_m: float,
        segment_span_km: float,
        *,
        segment_id: str,
    ) -> None:
        if not np.isfinite(gravity_m_s2) or gravity_m_s2 <= 0:
            raise ValueError("gravity must be finite and positive")
        if not np.isfinite(base_m):
            raise ValueError("base elevation must be finite")
        if not np.isfinite(segment_span_km) or segment_span_km <= 0:
            raise ValueError("segment span must be finite and positive")
        if not segment_id:
            raise ValueError("a stable source segment id is required")
        if not np.isfinite(radius_km) or radius_km <= 0:
            raise ValueError("radius must be finite and positive")
        self.radius_km = float(radius_km)
        self.gravity_m_s2 = float(gravity_m_s2)
        self.base_m = float(base_m)
        self.segment_span_km = float(segment_span_km)
        self.segment_id = segment_id
        self.pro_slope = float(np.tan(np.radians(_PRO_SLOPE_DEG)))
        self.retro_slope = float(np.tan(np.radians(_RETRO_SLOPE_DEG)))
        self.half_inv = 0.5 * (1.0 / self.pro_slope + 1.0 / self.retro_slope)
        self.cap_km = max(collision_cap_m(gravity_m_s2) - base_m, 0.0) / 1000.0
        self._open_endpoints: np.ndarray | None = None
        self._finite_arc_envelope = False

    def with_continuous_arc_envelope(self) -> Self:
        """Combine continuous finite-arc wedges using a common shortening field.

        Every arc has directional-distance endcaps, including shared nodes.
        Its relief is evaluated before taking the maximum over the source.
        The accepted parameter field and its distance-to-source mean blend
        are shared by all arcs, so changing the nearest arc cannot select
        a different height formula.
        """
        source = self.with_continuous_endcaps()
        source._finite_arc_envelope = True
        return source

    def _continuous_arc_profile(self, xyz: np.ndarray, retained_km: np.ndarray) -> np.ndarray:
        shape = xyz.shape[:-1]
        points = xyz.reshape(-1, 3)
        points = points / np.linalg.norm(points, axis=1, keepdims=True)
        retained = retained_km.reshape(-1)
        result = np.zeros(len(points))
        if self.cap_km == 0:
            return result.reshape(shape)
        arcs = self.geometry.segments
        normal = np.cross(arcs[:, 0], arcs[:, 1])
        length = np.arctan2(np.linalg.norm(normal, axis=1), (arcs[:, 0] * arcs[:, 1]).sum(1))
        normal /= np.linalg.norm(normal, axis=1, keepdims=True)
        tangent = np.cross(normal, arcs[:, 0])
        for start in range(0, len(points), 1024):
            part = points[start : start + 1024]
            area = retained[start : start + len(part), None] * (
                _REFERENCE_CRUST_KM / _AIRY_THICKENING_PER_ELEVATION
            )
            peak = np.sqrt(area / self.half_inv)
            plateau = np.maximum((area - self.cap_km**2 * self.half_inv) / self.cap_km, 0)
            best = np.zeros(len(part))
            for edge in range(0, len(arcs), 128):
                seg = arcs[edge : edge + 128]
                qa, qb = part @ seg[:, 0].T, part @ seg[:, 1].T
                transverse = np.arcsin(np.clip(part @ normal[edge : edge + 128].T, -1, 1))
                along = np.arctan2(part @ tangent[edge : edge + 128].T, qa)
                on_arc = (along >= 0) & (along <= length[edge : edge + 128])
                distance = (
                    np.where(
                        on_arc,
                        abs(transverse),
                        np.arccos(np.clip(np.maximum(qa, qb), -1, 1)),
                    )
                    * self.radius_km
                )
                transverse = np.clip(transverse * self.radius_km, -distance, distance)
                pro, retro = (distance + transverse) / 2, (distance - transverse) / 2
                triangle = peak - self.pro_slope * pro - self.retro_slope * retro
                capped = (
                    self.cap_km
                    - self.pro_slope * pro
                    - self.retro_slope * np.maximum(retro - plateau, 0)
                )
                value = np.maximum(np.where(peak <= self.cap_km, triangle, capped), 0)
                np.maximum(best, value.max(axis=1), out=best)
            result[start : start + len(part)] = best * 1000
        return result.reshape(shape)

    def with_continuous_endcaps(self) -> Self:
        """Extend the existing asymmetric cross-section around finite open ends.

        The two directional distances sum to radial distance and reproduce
        each original flank inside an arc. Their continuous mixture at an
        open end uses the same slopes and capped plateau width, without a
        discontinuous side choice beyond the end of the source axis.
        """
        source = copy(self)
        _, inverse = np.unique(self.geometry.segments.reshape(-1, 3), axis=0, return_inverse=True)
        degree = np.bincount(inverse)
        source._open_endpoints = degree[inverse].reshape(-1, 2) == 1
        source._open_endpoints.setflags(write=False)
        return source

    def _profile_for_projection(
        self, xyz: np.ndarray, projection: SphericalProjection, retained_km: np.ndarray
    ) -> np.ndarray:
        distance = projection.distance_rad * self.radius_km
        if self._finite_arc_envelope:
            return self._continuous_arc_profile(xyz, retained_km)
        result = self.profile(distance, retained_km, projection.side < 0)
        if self._open_endpoints is None or self.cap_km == 0:
            return result
        end = self._open_endpoints[projection.segment_index]
        active = ((projection.fraction == 0) & end[..., 0]) | (
            (projection.fraction == 1) & end[..., 1]
        )
        if not active.any():
            return result
        segments = self.geometry.segments[projection.segment_index[active]]
        normal = np.cross(segments[:, 0], segments[:, 1])
        normal /= np.linalg.norm(normal, axis=1, keepdims=True)
        transverse = np.arcsin(np.clip(np.sum(xyz[active] * normal, axis=1), -1, 1))
        transverse = np.clip(transverse * self.radius_km, -distance[active], distance[active])
        pro = (distance[active] + transverse) / 2
        retro = (distance[active] - transverse) / 2
        area = retained_km[active] * _REFERENCE_CRUST_KM / _AIRY_THICKENING_PER_ELEVATION
        peak = np.sqrt(area / self.half_inv)
        plateau = np.maximum((area - self.cap_km**2 * self.half_inv) / self.cap_km, 0)
        triangle = peak - self.pro_slope * pro - self.retro_slope * retro
        capped = (
            self.cap_km - self.pro_slope * pro - self.retro_slope * np.maximum(retro - plateau, 0)
        )
        result[active] = 1000 * np.maximum(np.where(peak <= self.cap_km, triangle, capped), 0)
        return result

    def _endcap_metadata(self) -> dict[str, Any]:
        if self._open_endpoints is None:
            return {}
        if self._finite_arc_envelope:
            return {
                "finite_endpoint_policy": "continuous directional-distance endcaps on every arc",
                "arc_combination": "maximum of continuous finite-arc profiles",
                "open_endpoint_count": int(self._open_endpoints.sum()),
                "endpoint_parameter_basis": "existing pro/retro slopes and capped plateau width",
                "endpoint_kind": "numerical finite-axis extension",
                "shortening_policy": "shared accepted field and distance-to-source mean blend",
            }
        return {
            "finite_endpoint_policy": "continuous directional-distance endcaps",
            "open_endpoint_count": int(self._open_endpoints.sum()),
            "endpoint_parameter_basis": "existing pro/retro slopes and capped plateau width",
            "endpoint_kind": "numerical finite-axis extension",
        }

    def profile(
        self, distance_km: np.ndarray, retained_km: np.ndarray, retro: np.ndarray
    ) -> np.ndarray:
        """Relief in metres; distances and along-axis shortening are in kilometres."""
        d, ret, back = np.broadcast_arrays(distance_km, retained_km, retro)
        if (
            not np.isfinite(d).all()
            or not np.isfinite(ret).all()
            or np.any(d < 0)
            or np.any(ret < 0)
        ):
            raise ValueError("profile distances and shortening must be finite and nonnegative")
        if self.cap_km == 0:
            return np.zeros(d.shape)
        area = ret * _REFERENCE_CRUST_KM / _AIRY_THICKENING_PER_ELEVATION
        peak = np.sqrt(area / self.half_inv)
        plateau = np.maximum((area - self.cap_km**2 * self.half_inv) / self.cap_km, 0)
        triangle = peak - np.where(back, self.retro_slope, self.pro_slope) * d
        capped = self.cap_km - np.where(
            back,
            self.retro_slope * np.maximum(d - plateau, 0),
            self.pro_slope * d,
        )
        return 1000 * np.maximum(np.where(peak <= self.cap_km, triangle, capped), 0)


class CollisionProfileField(_CollisionWedge):
    """An existing collision wedge with conservative along-arc shortening."""

    def __init__(
        self,
        segments_xyz: np.ndarray,
        edge_retained_km: np.ndarray,
        radius_km: float,
        gravity_m_s2: float,
        base_m: float,
        segment_span_km: float,
        *,
        segment_id: str,
    ) -> None:
        super().__init__(radius_km, gravity_m_s2, base_m, segment_span_km, segment_id=segment_id)
        self.axis_field = ConservativeArcField(
            segments_xyz, edge_retained_km, radius_km, _ALONG_STRIKE_KM
        )
        self.geometry = self.axis_field.geometry
        self.mean_retained_km = self.axis_field.integral_after / self.axis_field.lengths_km.sum()

    @property
    def maximum_retained_km(self) -> float:
        return max(float(self.axis_field.node_values.max()), float(self.mean_retained_km))

    def __call__(self, xyz: np.ndarray) -> np.ndarray:
        """Query unmasked relief; the oriented arc normal points to the pro side."""
        points = np.asarray(xyz, dtype=np.float64)
        shape = points.shape[:-1]
        points = points.reshape(-1, 3)
        projection = self.geometry.project(points)
        d = projection.distance_rad * self.radius_km
        ret = self.axis_field(points)
        alpha = np.clip(d / self.segment_span_km, 0, 1)
        ret = ret * (1 - alpha) + self.mean_retained_km * alpha
        return self._profile_for_projection(points, projection, ret).reshape(shape)

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "kind": "conservative-collision-profile-v1",
            "segment": self.segment_id,
            "geometry_sha256": self.geometry.sha256,
            "axis_field_sha256": self.axis_field.sha256,
            "radius_km": self.radius_km,
            "gravity_m_s2": self.gravity_m_s2,
            "base_m": self.base_m,
            "segment_span_km": self.segment_span_km,
            "cap_km": self.cap_km,
            "pro_slope": self.pro_slope,
            "retro_slope": self.retro_slope,
            "axis_integral_before_km2": self.axis_field.integral_before,
            "axis_integral_after_km2": self.axis_field.integral_after,
            "regularisation_radius_km": _ALONG_STRIKE_KM,
            "regularisation_time_km2": _ALONG_STRIKE_KM**2 / 6,
            "regularisation_kind": "numerical",
            "profile_basis": "existing Airy wedge, coarse-scale flank fit and force-balance cap",
            **self._endcap_metadata(),
        }


class ContactCollisionProfileField(_CollisionWedge):
    """Accepted contact-node extension with separately complete distance geometry.

    Known positive contacts supply the existing 300 km contact smoothing and
    shared vertex values. Unknown histories add geometry without adding parameter
    samples. The normalized inverse-square extension retains the supplied range.
    """

    def __init__(
        self,
        segments_xyz: np.ndarray,
        known_segments_xyz: np.ndarray,
        retained_endpoints_km: np.ndarray,
        mean_retained_km: float,
        radius_km: float,
        gravity_m_s2: float,
        base_m: float,
        segment_span_km: float,
        *,
        segment_id: str,
        unavailable_contact_ids: tuple[int, ...] = (),
    ) -> None:
        super().__init__(radius_km, gravity_m_s2, base_m, segment_span_km, segment_id=segment_id)
        self.geometry = SphericalSegmentGeometry(segments_xyz)
        SphericalSegmentGeometry(known_segments_xyz)
        points = np.array(known_segments_xyz, dtype=np.float64, copy=True).reshape(-1, 3)
        values = np.array(retained_endpoints_km, dtype=np.float64, copy=True)
        if values.shape != np.asarray(known_segments_xyz).shape[:2]:
            raise ValueError("one known shortening value is required at each arc endpoint")
        if not np.isfinite(values).all() or np.any(values < 0):
            raise ValueError("known vertex shortening must be finite and nonnegative")
        if not np.isfinite(mean_retained_km) or mean_retained_km < 0:
            raise ValueError("known contact mean must be finite and nonnegative")
        self.nodes, inverse = np.unique(points, axis=0, return_inverse=True)
        self.node_values = np.bincount(inverse, weights=values.ravel()) / np.bincount(inverse)
        self.mean_retained_km = float(mean_retained_km)
        self.unavailable_contact_ids = unavailable_contact_ids
        digest = hashlib.sha256()
        for data in (self.nodes, self.node_values):
            digest.update(data.astype("<f8").tobytes())
            data.setflags(write=False)
        self.parameter_sha256 = digest.hexdigest()

    @property
    def maximum_retained_km(self) -> float:
        return max(float(self.node_values.max()), self.mean_retained_km)

    def shortening(self, xyz: np.ndarray) -> np.ndarray:
        points = np.asarray(xyz, dtype=np.float64).reshape(-1, 3)
        out = np.empty(len(points))
        for start in range(0, len(points), 4096):
            part = points[start : start + 4096]
            distance2 = np.sum((part[:, None, :] - self.nodes[None, :, :]) ** 2, axis=2)
            near = distance2.argmin(axis=1)
            minimum = distance2[np.arange(len(part)), near]
            weights = minimum[:, None] / np.maximum(distance2, 1e-30)
            denominator = weights.sum(axis=1)
            out[start : start + len(part)] = np.divide(
                weights @ self.node_values,
                denominator,
                out=self.node_values[near].copy(),
                where=denominator > 0,
            )
        return out.reshape(np.asarray(xyz).shape[:-1])

    def __call__(self, xyz: np.ndarray) -> np.ndarray:
        points = np.asarray(xyz, dtype=np.float64)
        projection = self.geometry.project(points)
        distance = projection.distance_rad * self.radius_km
        retained = self.shortening(points)
        alpha = np.clip(distance / self.segment_span_km, 0, 1)
        retained = retained * (1 - alpha) + self.mean_retained_km * alpha
        return self._profile_for_projection(points, projection, retained)

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "kind": "known-contact-collision-profile-v1",
            "segment": self.segment_id,
            "geometry_sha256": self.geometry.sha256,
            "parameter_sha256": self.parameter_sha256,
            "radius_km": self.radius_km,
            "gravity_m_s2": self.gravity_m_s2,
            "base_m": self.base_m,
            "segment_span_km": self.segment_span_km,
            "mean_retained_km": self.mean_retained_km,
            "cap_km": self.cap_km,
            "pro_slope": self.pro_slope,
            "retro_slope": self.retro_slope,
            "known_vertices": len(self.nodes),
            "unavailable_contact_ids": list(self.unavailable_contact_ids),
            "history_policy": (
                "unavailable contacts supply geometry; parameters use known positive contacts"
            ),
            "parameter_policy": (
                "existing 300 km contact smoothing; incident-edge vertex means; "
                "inverse-square extension"
            ),
            "parameter_kind": "numerical reconstruction from known contact history",
            "profile_basis": "existing Airy wedge, coarse-scale flank fit and force-balance cap",
            **self._endcap_metadata(),
        }


class FrozenOrogenReplacement:
    """Difference of one continuous profile inside a frozen active/paleo envelope.

    Reference values use the existing nearest-source-cell transfer and retain
    the source mesh's crust coverage. The returned second array is zero: this
    object supplies a height correction, rather than an absolute land fraction.
    A consumer adds the correction after the unchanged S3 structure operation.
    """

    def __init__(
        self,
        profile: OrogenProfileField,
        xyz: np.ndarray,
        land_crust: np.ndarray,
        selected_m: np.ndarray,
        other_active_m: np.ndarray,
        paleo_m: np.ndarray,
        *,
        reference_id: str,
    ) -> None:
        points = np.array(xyz, dtype=np.float64, copy=True)
        n = len(points)
        if points.shape != (n, 3) or not np.isfinite(points).all():
            raise ValueError("reference coordinates must be finite unit vectors")
        if not np.allclose(np.linalg.norm(points, axis=1), 1, rtol=0, atol=1e-7):
            raise ValueError("reference coordinates must be unit vectors")
        if not reference_id:
            raise ValueError("an explicit reference id is required")
        crust = np.array(land_crust, dtype=bool, copy=True)
        fields = [
            np.array(a, dtype=np.float64, copy=True) for a in (selected_m, other_active_m, paleo_m)
        ]
        if crust.shape != (n,) or any(a.shape != (n,) for a in fields):
            raise ValueError("one reference value is required per source cell")
        if any(not np.isfinite(a).all() or np.any(a < 0) for a in fields):
            raise ValueError("reference orogen relief must be finite and nonnegative")
        self.profile_field = profile
        self.reference_id = reference_id
        self.xyz = points
        self.land_crust = crust
        self.selected_m, self.other_active_m, self.paleo_m = fields
        self.tree = cKDTree(points)
        positive = self.selected_m > 0
        self.selected_tree = cKDTree(points[positive]) if positive.any() else None
        digest = hashlib.sha256()
        for arr in (points, crust, *fields):
            digest.update(arr.astype("<f8").tobytes())
            arr.setflags(write=False)
        self.reference_sha256 = digest.hexdigest()

    def evaluate(self, lat: np.ndarray, lon: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        latitude, longitude = np.broadcast_arrays(lat, lon)
        points = lonlat_to_xyz(np.column_stack([longitude.ravel(), latitude.ravel()]))
        _, index = self.tree.query(points)
        selected = np.where(self.land_crust[index], self.profile_field(points), 0)
        background = np.maximum(self.other_active_m[index], self.paleo_m[index])
        previous = np.maximum(background, self.selected_m[index])
        delta = (np.maximum(background, selected) - previous).reshape(latitude.shape)
        return delta, np.zeros(latitude.shape)

    def continuous_reconstruction(self) -> ContinuousOrogenReplacement:
        """Reconstruct all frozen contributions on the same global spherical faces.

        The original nearest-cell transfer remains this object's policy. The
        returned source is explicit, with its own reconstruction fingerprint,
        for combination with continuously reconstructed stage backgrounds.
        """
        return ContinuousOrogenReplacement(
            self.profile_field,
            self.xyz,
            self.land_crust,
            self.selected_m,
            self.other_active_m,
            self.paleo_m,
            reference_id=self.reference_id,
        )

    def footprint_support(
        self, lat: np.ndarray, lon: np.ndarray, half_diagonal_km: float, radius_km: float
    ) -> np.ndarray:
        """Conservative coverage of any changed relief within a spherical footprint.

        The plane's half diagonal bounds geodesic displacement inside the
        azimuthal-equidistant projection. A positive old source cell can be
        nearest only if its centre distance is within twice this displacement
        of the nearest reference centre. New profiles use their physical reach.
        Unknown profile implementations retain all requested footprints.
        """
        if not np.isfinite(half_diagonal_km) or half_diagonal_km < 0:
            raise ValueError("footprint radius must be finite and nonnegative")
        if not np.isfinite(radius_km) or radius_km <= 0:
            raise ValueError("sphere radius must be finite and positive")
        lat, lon = np.broadcast_arrays(lat, lon)
        xyz = lonlat_to_xyz(np.column_stack([lon.ravel(), lat.ravel()]))
        support = np.zeros(len(xyz), dtype=bool)
        margin = 64 * np.finfo(np.float64).eps * radius_km
        if self.selected_tree is not None:
            all_distance = 2 * np.arcsin(np.clip(self.tree.query(xyz)[0] / 2, 0, 1)) * radius_km
            selected_distance = (
                2 * np.arcsin(np.clip(self.selected_tree.query(xyz)[0] / 2, 0, 1)) * radius_km
            )
            support |= selected_distance - all_distance <= 2 * half_diagonal_km + margin
        profiles = (
            [profile for _, profile in self.profile_field.profiles]
            if isinstance(self.profile_field, OrogenEnvelopeProfileField)
            else [self.profile_field]
        )
        for profile in profiles:
            if isinstance(profile, (CollisionProfileField, ContactCollisionProfileField)):
                if profile.radius_km != radius_km:
                    raise ValueError("profile and footprint sphere radii must match")
                if profile.cap_km == 0:
                    continue
                retained = profile.maximum_retained_km
                area = retained * _REFERENCE_CRUST_KM / _AIRY_THICKENING_PER_ELEVATION
                peak = min(np.sqrt(area / profile.half_inv), profile.cap_km)
                plateau = max((area - profile.cap_km**2 * profile.half_inv) / profile.cap_km, 0)
                reach = peak / min(profile.pro_slope, profile.retro_slope) + plateau
                distance = profile.geometry.project(xyz).distance_rad * radius_km
            elif isinstance(profile, PaleoProfileField):
                from .paleo_sutures import polyline_geometry

                if profile.radius_km != radius_km:
                    raise ValueError("profile and footprint sphere radii must match")
                reach = profile.active_crest_m / 1000 / float(np.tan(np.radians(_PRO_SLOPE_DEG)))
                distance = polyline_geometry(xyz, profile.suture.path)[0] * radius_km
            else:
                return np.ones(lat.shape, dtype=bool)
            support |= distance <= reach + half_diagonal_km + margin
        return support.reshape(lat.shape)

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "kind": "frozen-orogen-replacement-v1",
            "profile": self.profile_field.metadata,
            "reference_id": self.reference_id,
            "reference_sha256": self.reference_sha256,
            "reference_transfer": "nearest source cell; frozen active/paleo maximum envelope",
            "coverage": "frozen source-mesh continental crust",
            "downstream_response": "frozen reference-stage difference",
        }


class ContinuousOrogenReplacement(FrozenOrogenReplacement):
    """Replace selected relief using one continuous reference for every contribution.

    Selected and background relief use the same positive spherical barycentric
    reconstruction. Continental coverage is reconstructed as a fraction of the
    frozen point indicator. Both maximum envelopes are evaluated after querying
    these fields; their difference retains the original stage's reconstruction
    residual when added to an independently reconstructed stage background.
    This source supplies a numerical stage response, with physical downstream
    responses and new shoreline geometry recorded separately by its consumer.
    """

    def __init__(
        self,
        profile: OrogenProfileField,
        xyz: np.ndarray,
        land_crust: np.ndarray,
        selected_m: np.ndarray,
        other_active_m: np.ndarray,
        paleo_m: np.ndarray,
        *,
        reference_id: str,
    ) -> None:
        from .spherical_terrain import SphericalPointTerrainField

        super().__init__(
            profile,
            xyz,
            land_crust,
            selected_m,
            other_active_m,
            paleo_m,
            reference_id=reference_id,
        )
        self.reference_field = SphericalPointTerrainField(
            self.xyz,
            np.column_stack([self.selected_m, self.other_active_m, self.paleo_m, self.land_crust]),
        )
        points, faces = self.reference_field.points, self.reference_field.faces
        maximum = 0.0
        for a, b in ((0, 1), (1, 2), (2, 0)):
            cosine = np.sum(points[faces[:, a]] * points[faces[:, b]], axis=1)
            maximum = max(maximum, float(np.arccos(np.clip(cosine, -1, 1)).max()))
        self._reference_maximum_edge_rad = maximum

    def evaluate(self, lat: np.ndarray, lon: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        latitude, longitude = np.broadcast_arrays(lat, lon)
        points = lonlat_to_xyz(np.column_stack([longitude.ravel(), latitude.ravel()]))
        reference = self.reference_field(points)
        coverage = np.clip(reference[:, 3], 0, 1)
        selected = self.profile_field(points) * coverage
        background = np.maximum(reference[:, 1], reference[:, 2])
        previous = np.maximum(background, reference[:, 0])
        delta = (np.maximum(background, selected) - previous).reshape(latitude.shape)
        return delta, np.zeros(latitude.shape)

    def footprint_support(
        self, lat: np.ndarray, lon: np.ndarray, half_diagonal_km: float, radius_km: float
    ) -> np.ndarray:
        if not np.isfinite(half_diagonal_km) or half_diagonal_km < 0:
            raise ValueError("footprint radius must be finite and nonnegative")
        # A contributing reference vertex lies within one source-face edge of
        # a query. Enlarging the nearest-cell bound by that edge also covers
        # its whole continuous interpolation support on irregular meshes.
        return super().footprint_support(
            lat,
            lon,
            half_diagonal_km + self._reference_maximum_edge_rad * radius_km,
            radius_km,
        )

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            **super().metadata,
            "kind": "continuous-orogen-replacement-v1",
            "reference_transfer": "positive spherical barycentric contribution fields",
            "reconstruction_sha256": self.reference_field.sha256,
            "coverage": "interpolated frozen continental-crust fraction",
            "envelope_policy": "difference of maxima after common contribution reconstruction",
            "stage_residual": "frozen original maximum-envelope reconstruction residual",
        }


def collision_source_from_contract(
    fields: Mapping[str, np.ndarray],
    contract: OrogenContract,
    geometry: dict[str, Any],
    *,
    segment_id: str,
    radius_km: float,
    gravity_m_s2: float,
    base_m: float,
    reference_id: str,
    parameter_policy: CollisionParameterPolicy = "conservative_arc",
) -> FrozenOrogenReplacement:
    """Build a declared collision reconstruction from native fields and a full interface.

    Conservative arcs use all available contacts, including valid zeros. The
    explicit known-contact policy keeps the previously accepted vertex extension
    while unavailable histories supply geometry. Positive arcs retain their
    source order, followed by the remaining arcs.
    """
    n = len(fields["xyz"])
    if geometry.get("num_cells") != n or geometry.get("coordinate_frame") != "unit sphere, y north":
        raise ValueError("contract geometry must match the geological source mesh frame")
    for contact in geometry["contacts"]:
        cell = int(contact["cell_id"])
        if (
            not 0 <= cell < n
            or fields["plate_id"][cell] != contact["plate_id"]
            or not np.allclose(fields["xyz"][cell], contact["xyz"], rtol=0, atol=1e-12)
        ):
            raise ValueError("contract contact does not match the geological source mesh")
    selected = next((segment for segment in contract.segments if segment.id == segment_id), None)
    if selected is None or selected.kind != "collision":
        raise ValueError("the selected source must be a collision segment")
    if parameter_policy not in ("conservative_arc", "known_contact_vertices"):
        raise ValueError("unknown collision parameter policy")
    if not selected.cell_ids or any(
        cell not in selected.cell_history for cell in selected.cell_ids
    ):
        raise ValueError("collision source needs available effective contact history")
    if parameter_policy == "conservative_arc" and any(
        selected.cell_history[cell].status == "unavailable" for cell in selected.cell_ids
    ):
        raise ValueError("collision source needs available effective contact history")
    key = f"orogen.segment.{segment_id}"
    if key not in fields:
        raise ValueError("the selected collision contribution is absent from the source archive")
    rows = [row for row in geometry["interfaces"] if row["segment_id"] == segment_id]
    if not rows:
        raise ValueError("the collision source needs complete shared interface arcs")
    rows = [row for row in rows if row["positive_retained_contact_cell_ids"]] + [
        row for row in rows if not row["positive_retained_contact_cell_ids"]
    ]
    members = set(selected.cell_ids)
    if any(
        not row["contact_cell_ids"] or not set(row["contact_cell_ids"]).issubset(members)
        for row in rows
    ):
        raise ValueError("interface budgets must belong to the selected segment contacts")
    vertices = {row["vertex_id"]: row["xyz"] for row in geometry["vertices"]}
    arcs = np.array([[vertices[vertex] for vertex in row["vertex_ids"]] for row in rows])
    profile: OrogenProfileField
    if parameter_policy == "conservative_arc":
        retained = np.array(
            [
                np.mean([contract.retained_km[cell] for cell in row["contact_cell_ids"]])
                for row in rows
            ]
        )
        points = fields["xyz"][selected.cell_ids]
        span = max(
            float(np.arccos(np.clip(points @ points.T, -1, 1)).max()) * radius_km,
            _ALONG_STRIKE_KM,
        )
        profile = CollisionProfileField(
            arcs, retained, radius_km, gravity_m_s2, base_m, span, segment_id=segment_id
        )
    else:
        positive = sorted(cell for cell in selected.cell_ids if contract.retained_km[cell] > 0)
        if not positive or any(
            selected.cell_history[cell].status == "unavailable" for cell in positive
        ):
            raise ValueError("known-contact reconstruction needs available positive history")
        segment_of = {cell: segment for segment in contract.segments for cell in segment.cell_ids}
        pool = np.array(
            sorted(
                cell
                for cell, value in contract.retained_km.items()
                if value > 0 and segment_of[cell].kind == "collision"
            )
        )
        pool_xyz = fields["xyz"][pool]
        neighbours = cKDTree(pool_xyz).query_ball_point(pool_xyz, _ALONG_STRIKE_KM / radius_km)
        smooth = {
            int(cell): float(np.mean([contract.retained_km[int(pool[j])] for j in adjacent]))
            for cell, adjacent in zip(pool, neighbours, strict=True)
        }
        known = [row for row in rows if row["positive_retained_contact_cell_ids"]]
        vertex_values: dict[int, list[float]] = {}
        for row in known:
            contacts = [cell for cell in row["contact_cell_ids"] if cell in positive]
            if not contacts:
                raise ValueError("known arcs need positive contacts in the selected source")
            value = float(np.mean([smooth[cell] for cell in contacts]))
            for vertex in row["vertex_ids"]:
                vertex_values.setdefault(vertex, []).append(value)
        known_arcs = np.array([[vertices[vertex] for vertex in row["vertex_ids"]] for row in known])
        endpoints = np.array(
            [[np.mean(vertex_values[vertex]) for vertex in row["vertex_ids"]] for row in known]
        )
        points = fields["xyz"][positive]
        span = max(
            float(np.arccos(np.clip(points @ points.T, -1, 1)).max()) * radius_km, _ALONG_STRIKE_KM
        )
        profile = ContactCollisionProfileField(
            arcs,
            known_arcs,
            endpoints,
            float(np.mean([smooth[cell] for cell in positive])),
            radius_km,
            gravity_m_s2,
            base_m,
            span,
            segment_id=segment_id,
            unavailable_contact_ids=tuple(
                sorted(
                    cell
                    for cell in selected.cell_ids
                    if selected.cell_history[cell].status == "unavailable"
                )
            ),
        )
    contributions = [
        value
        for name, value in fields.items()
        if name.startswith("orogen.segment.") and name != key
    ]
    other = np.maximum.reduce(contributions) if contributions else np.zeros(n)
    if not np.array_equal(np.maximum(other, fields[key]), fields["active_orogen_m"]):
        raise ValueError("segment contributions do not reproduce the frozen active envelope")
    return FrozenOrogenReplacement(
        profile,
        fields["xyz"],
        fields["land_crust_mask"],
        fields[key],
        other,
        fields["paleo_orogen_m"],
        reference_id=reference_id,
    )


def paleo_source_from_history(
    fields: Mapping[str, np.ndarray],
    sutures: list[AuthorSuture],
    *,
    suture_id: str,
    active_crest_m: float,
    radius_km: float,
    reference_id: str,
) -> FrozenOrogenReplacement:
    """Build an old-belt source after replaying its full authored reference envelope."""
    from .paleo_orogens import paleo_orogen_field

    selected = [suture for suture in sutures if suture.id == suture_id]
    if len(selected) != 1:
        raise ValueError("the old-belt source needs one unique author suture")
    profile = PaleoProfileField(selected[0], active_crest_m, radius_km)
    xyz, crust = fields["xyz"], fields["land_crust_mask"]
    old = np.where(crust, paleo_orogen_field(xyz, sutures, active_crest_m, radius_km), 0)
    if not np.array_equal(old, fields["paleo_orogen_m"]):
        raise ValueError("author history does not reproduce the frozen paleo envelope")
    other_sutures = [suture for suture in sutures if suture.id != suture_id]
    other = np.where(crust, paleo_orogen_field(xyz, other_sutures, active_crest_m, radius_km), 0)
    return FrozenOrogenReplacement(
        profile,
        xyz,
        crust,
        np.where(crust, profile(xyz), 0),
        fields["active_orogen_m"],
        other,
        reference_id=reference_id,
    )


def orogen_source_from_native(
    fields: Mapping[str, np.ndarray],
    contract: OrogenContract,
    geometry: dict[str, Any],
    sutures: list[AuthorSuture],
    *,
    collision_segment_ids: tuple[str, ...] = (),
    paleo_suture_ids: tuple[str, ...] = (),
    radius_km: float,
    gravity_m_s2: float,
    base_m: float,
    reference_id: str,
    collision_parameter_policy: CollisionParameterPolicy = "conservative_arc",
) -> FrozenOrogenReplacement:
    """Prepare explicitly selected native sources inside one joint frozen envelope.

    Unselected active and paleo contributions keep their original cell transfer.
    Selected sources are combined before the reference envelope is subtracted,
    including where two selected belts overlap or exchange dominance. The active
    crest used by old belts is derived by the original synthesis rule.
    """
    from .orogen_profile import collision_crests_m
    from .paleo_orogens import paleo_orogen_field

    if not collision_segment_ids and not paleo_suture_ids:
        raise ValueError("native source preparation needs an explicit belt selection")
    if len(set(collision_segment_ids)) != len(collision_segment_ids) or len(
        set(paleo_suture_ids)
    ) != len(paleo_suture_ids):
        raise ValueError("native belt selections must have unique ids")
    xyz, crust = fields["xyz"], fields["land_crust_mask"]
    n = len(xyz)
    profiles: dict[str, OrogenProfileField] = {}
    selected_m = np.zeros(n)
    for segment_id in sorted(collision_segment_ids):
        source = collision_source_from_contract(
            fields,
            contract,
            geometry,
            segment_id=segment_id,
            radius_km=radius_km,
            gravity_m_s2=gravity_m_s2,
            base_m=base_m,
            reference_id=reference_id,
            parameter_policy=collision_parameter_policy,
        )
        profiles[f"collision:{segment_id}"] = source.profile_field
        np.maximum(selected_m, source.selected_m, out=selected_m)

    contributions = {
        name.removeprefix("orogen.segment."): value
        for name, value in fields.items()
        if name.startswith("orogen.segment.")
    }
    active = np.maximum.reduce(list(contributions.values())) if contributions else np.zeros(n)
    if not np.array_equal(active, fields["active_orogen_m"]):
        raise ValueError("segment contributions do not reproduce the frozen active envelope")
    other_active = np.zeros(n)
    for segment_id, value in contributions.items():
        if segment_id not in collision_segment_ids:
            np.maximum(other_active, value, out=other_active)

    other_paleo = fields["paleo_orogen_m"]
    if paleo_suture_ids:
        if len({suture.id for suture in sutures}) != len(sutures):
            raise ValueError("author history must have unique suture ids")
        crests = collision_crests_m(contract, gravity_m_s2, base_m)
        active_crest = (
            float(np.median(crests)) if crests else max(collision_cap_m(gravity_m_s2) - base_m, 0)
        )
        for suture_id in sorted(paleo_suture_ids):
            source = paleo_source_from_history(
                fields,
                sutures,
                suture_id=suture_id,
                active_crest_m=active_crest,
                radius_km=radius_km,
                reference_id=reference_id,
            )
            profiles[f"paleo:{suture_id}"] = source.profile_field
            np.maximum(selected_m, source.selected_m, out=selected_m)
        remaining = [suture for suture in sutures if suture.id not in paleo_suture_ids]
        other_paleo = np.where(
            crust, paleo_orogen_field(xyz, remaining, active_crest, radius_km), 0
        )

    if not np.array_equal(
        np.maximum(np.maximum(other_active, other_paleo), selected_m),
        np.maximum(fields["active_orogen_m"], fields["paleo_orogen_m"]),
    ):
        raise ValueError("selected and background sources must replay the full frozen envelope")
    return FrozenOrogenReplacement(
        OrogenEnvelopeProfileField(profiles),
        xyz,
        crust,
        selected_m,
        other_active,
        other_paleo,
        reference_id=reference_id,
    )
