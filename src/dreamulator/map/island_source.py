"""Continuous volcanic geometry with an explicit present-day reference.

The fixed-flank cone is a geometric closure of the catalogue's current summit
and built slope. Its exposed volume differs from the legacy cell-mean load.
The original load remains an independent source ledger. Replacement consumes
its actual final-stage removal response and a declared present-day geometry.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
from scipy.spatial import cKDTree

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .island_catalog import IslandCatalog, Volcano


@dataclass(frozen=True)
class VolcanicCone:
    source_id: str
    kind: str
    latitude_deg: float
    longitude_deg: float
    floor_elevation_m: float
    summit_elevation_m: float
    built_relief_m: float
    built_radius_km: float
    built_volume_km3: float
    origin_id: str = ""
    age_myr: float | None = None

    def __post_init__(self) -> None:
        values = (
            self.latitude_deg,
            self.longitude_deg,
            self.floor_elevation_m,
            self.summit_elevation_m,
            self.built_relief_m,
            self.built_radius_km,
            self.built_volume_km3,
        )
        if not self.source_id or not np.isfinite(values).all():
            raise ValueError("volcanic geometry needs an id and finite reference values")
        if self.age_myr is not None and (not np.isfinite(self.age_myr) or self.age_myr < 0):
            raise ValueError("volcanic source age must be nonnegative or unavailable")
        if not -90 <= self.latitude_deg <= 90 or not -180 <= self.longitude_deg <= 180:
            raise ValueError("volcanic location must use latitude and longitude in degrees")
        if min(self.built_relief_m, self.built_radius_km, self.built_volume_km3) <= 0:
            raise ValueError("built volcanic height, radius and volume must be positive")
        expected = np.pi * self.built_radius_km**2 * self.built_relief_m / 3000.0
        if not np.isclose(self.built_volume_km3, expected, rtol=1e-8, atol=1e-10):
            raise ValueError("built volcanic radius and relief disagree with its cone volume")
        if self.relief_m > self.built_relief_m + 1e-7:
            raise ValueError("current volcanic relief exceeds the declared built cone")

    @classmethod
    def from_volcano(cls, volcano: Volcano) -> VolcanicCone:
        """Read full-precision catalogue values after final-surface summarisation."""
        return cls(
            volcano.id,
            volcano.kind,
            volcano.lat,
            volcano.lon,
            volcano.floor_elevation_m,
            volcano.summit_m,
            volcano.relief_m,
            volcano.base_radius_km,
            volcano.volume_km3,
            volcano.source,
            None if np.isnan(volcano.age_myr) else volcano.age_myr,
        )

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> VolcanicCone:
        """Reconstruct a saved full-precision source and validate its derived geometry."""
        result = cls(
            record["id"],
            record["kind"],
            record["latitude_deg"],
            record["longitude_deg"],
            record["floor_elevation_m"],
            record["summit_elevation_m"],
            record["built_relief_m"],
            record["built_radius_km"],
            record["built_volume_km3"],
            record["origin_id"],
            record["age_myr"],
        )
        for key, value in result.to_record().items():
            if record[key] != value:
                raise ValueError("saved volcanic geometry disagrees with its source constraints")
        return result

    @property
    def relief_m(self) -> float:
        return max(self.summit_elevation_m - self.floor_elevation_m, 0.0)

    @property
    def radius_km(self) -> float:
        return self.built_radius_km * self.relief_m / self.built_relief_m

    @property
    def volume_km3(self) -> float:
        """Present cone above its background, using the catalogue's planar convention."""
        return self.built_volume_km3 * (self.relief_m / self.built_relief_m) ** 3

    @property
    def emergent_radius_km(self) -> float:
        return min(
            self.radius_km,
            self.built_radius_km * max(self.summit_elevation_m, 0.0) / self.built_relief_m,
        )

    def relief_at_distance_m(self, distance_km: np.ndarray) -> np.ndarray:
        distance = np.asarray(distance_km, dtype=np.float64)
        if not np.isfinite(distance).all() or np.any(distance < 0):
            raise ValueError("volcanic profile distance must be finite and nonnegative")
        if self.radius_km == 0:
            return np.zeros_like(distance)
        return np.asarray(self.relief_m * np.maximum(1 - distance / self.radius_km, 0))

    def spherical_volume_km3(self, planet_radius_km: float) -> float:
        """Integrate relief over spherical surface area, using arc-length flank distance."""
        if not np.isfinite(planet_radius_km) or planet_radius_km <= 0:
            raise ValueError("planet radius must be finite and positive")
        beta = self.radius_km / planet_radius_km
        if beta >= np.pi:
            raise ValueError("cone support must be smaller than a hemisphere-to-antipode arc")
        term = (
            beta**2 / 6 - beta**4 / 120 + beta**6 / 5040 if beta < 0.01 else 1 - np.sin(beta) / beta
        )
        return float(2 * np.pi * planet_radius_km**2 * self.relief_m / 1000 * term)

    def to_record(self) -> dict[str, Any]:
        return {
            "id": self.source_id,
            "kind": self.kind,
            "origin_id": self.origin_id,
            "age_myr": self.age_myr,
            "latitude_deg": self.latitude_deg,
            "longitude_deg": self.longitude_deg,
            "floor_elevation_m": self.floor_elevation_m,
            "summit_elevation_m": self.summit_elevation_m,
            "built_relief_m": self.built_relief_m,
            "built_radius_km": self.built_radius_km,
            "built_volume_km3": self.built_volume_km3,
            "present_relief_m": self.relief_m,
            "present_radius_km": self.radius_km,
            "present_volume_km3": self.volume_km3,
            "emergent_radius_km": self.emergent_radius_km,
        }


def catalogue_geometry(catalogue: IslandCatalog) -> dict[str, Any]:
    """Export full-precision geometric sources while retaining the original load fields."""
    profiles = [VolcanicCone.from_volcano(v) for v in catalogue.volcanoes if v.status != "dropped"]
    return {
        "format": "volcanic-cone-sources-v1",
        "profile": "fixed built flank; present summit and final-background sea datum",
        "volume": "geometric cone above the present floor; planar catalogue convention",
        "load_reference": "volcano_cell_mean_m in the terrain source archive",
        "composition": "maximum surface envelope; source overlap is accounted separately",
        "scope": "explicit continuous-source trial; default coarse terrain remains unchanged",
        "profiles": [p.to_record() for p in profiles],
    }


class VolcanicConeField:
    """Evaluate an absolute cone-surface envelope above a supplied background."""

    def __init__(self, profiles: Sequence[VolcanicCone], planet_radius_km: float) -> None:
        if not np.isfinite(planet_radius_km) or planet_radius_km <= 0:
            raise ValueError("planet radius must be finite and positive")
        self.profiles = tuple(p for p in profiles if p.radius_km > 0)
        if len({p.source_id for p in profiles}) != len(profiles):
            raise ValueError("volcanic source ids must be unique")
        self.planet_radius_km = float(planet_radius_km)
        if any(p.radius_km >= np.pi * planet_radius_km for p in self.profiles):
            raise ValueError("cone support must fit within the spherical distance domain")
        lat = np.radians([p.latitude_deg for p in self.profiles])
        lon = np.radians([p.longitude_deg for p in self.profiles])
        self.centres = np.column_stack(
            [np.cos(lat) * np.cos(lon), np.sin(lat), np.cos(lat) * np.sin(lon)]
        )
        self.centres.setflags(write=False)
        self._tree = cKDTree(self.centres)
        self._maximum_radius_km = max((p.radius_km for p in self.profiles), default=0.0)
        self._radii = np.array([p.radius_km for p in self.profiles])
        self._summits = np.array([p.summit_elevation_m for p in self.profiles])
        self._relief = np.array([p.relief_m for p in self.profiles])
        self.sha256 = hashlib.sha256(repr((self.profiles, planet_radius_km)).encode()).hexdigest()

    def surface_m(self, xyz: np.ndarray, background_m: np.ndarray) -> np.ndarray:
        return self._envelope_m(xyz, background_m, thickness=False)

    def thickness_m(self, xyz: np.ndarray) -> np.ndarray:
        """Present cone thickness, continuous at its support edge.

        This geometry is measured normal to the spherical reference datum and
        is added to a separately supplied substrate. The maximum of overlapping
        bodies is an envelope; its overlap volume is recorded by the caller.
        """
        points = np.asarray(xyz, dtype=np.float64)
        return self._envelope_m(points, np.zeros(points.shape[:-1]), thickness=True)

    def _envelope_m(
        self, xyz: np.ndarray, background_m: np.ndarray, *, thickness: bool
    ) -> np.ndarray:
        points = np.asarray(xyz, dtype=np.float64)
        background = np.asarray(background_m, dtype=np.float64)
        if points.ndim < 1 or points.shape[-1] != 3 or points.shape[:-1] != background.shape:
            raise ValueError("volcanic queries need matching spherical coordinates and background")
        if not np.isfinite(points).all() or not np.isfinite(background).all():
            raise ValueError("volcanic query values must be finite")
        if not np.allclose(np.linalg.norm(points, axis=-1), 1, rtol=0, atol=1e-7):
            raise ValueError("volcanic query coordinates must be unit vectors")
        result = background.copy().reshape(-1)
        if not self.profiles:
            return result.reshape(background.shape)
        flat = points.reshape(-1, 3)
        chord = 2 * np.sin(self._maximum_radius_km / self.planet_radius_km / 2) + 1e-12
        for start in range(0, len(flat), 4096):
            q = flat[start : start + 4096]
            near = self._tree.query_ball_point(q, chord)
            lengths = np.array([len(ids) for ids in near])
            if not lengths.sum():
                continue
            rows = np.repeat(np.arange(len(q)), lengths)
            ids = np.concatenate(near).astype(np.int64)
            centres = self.centres[ids]
            angle = np.arctan2(
                np.linalg.norm(np.cross(q[rows], centres), axis=1),
                np.sum(q[rows] * centres, axis=1),
            )
            distance = angle * self.planet_radius_km
            active = distance <= self._radii[ids]
            peak = self._relief[ids] if thickness else self._summits[ids]
            top = peak - self._relief[ids] * distance / self._radii[ids]
            np.maximum.at(result, start + rows[active], top[active])
        return result.reshape(background.shape)


class FrozenVolcanicReplacement:
    """Source correction on two frozen geological endpoints and a present cone.

    The reference is the accepted final coarse surface. The background is
    the actual recomputed final surface after withdrawing selected old loads.
    Current cones are combined at the present surface, using their catalogue
    age/summit closure. All regional and global background responses remain
    in the correction. The second result is zero for a delta-only source.
    """

    def __init__(
        self,
        profiles: Sequence[VolcanicCone],
        xyz: np.ndarray,
        reference_m: np.ndarray,
        background_m: np.ndarray,
        *,
        planet_radius_km: float,
        reference_id: str,
        background_reference_id: str,
    ) -> None:
        from .spherical_terrain import SphericalPointTerrainField

        if not reference_id or not background_reference_id:
            raise ValueError("volcanic replacement needs both geological reference ids")
        reference = np.asarray(reference_m, dtype=np.float64)
        background = np.asarray(background_m, dtype=np.float64)
        if reference.shape != (len(xyz),) or background.shape != reference.shape:
            raise ValueError("volcanic reference and background need one value per source point")
        self.reference_field = SphericalPointTerrainField(
            xyz, np.column_stack([reference, background])
        )
        self.cone_field = VolcanicConeField(profiles, planet_radius_km)
        self.reference_id = reference_id
        self.background_reference_id = background_reference_id

    def evaluate(self, lat: np.ndarray, lon: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        xyz, values = self._query(lat, lon)
        surface = self.cone_field.surface_m(xyz, values[..., 1])
        delta = surface - values[..., 0]
        return delta, np.zeros_like(delta)

    def _query(self, lat: np.ndarray, lon: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        from .paleo_sutures import lonlat_to_xyz

        latitude, longitude = np.broadcast_arrays(lat, lon)
        xyz = lonlat_to_xyz(np.column_stack([longitude.ravel(), latitude.ravel()])).reshape(
            (*latitude.shape, 3)
        )
        values = self.reference_field(xyz)
        return xyz, values

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "kind": "actual-background-volcanic-replacement-v1",
            "reference_id": self.reference_id,
            "background_reference_id": self.background_reference_id,
            "reference_sha256": self.reference_field.sha256,
            "geometry_sha256": self.cone_field.sha256,
            "profiles": [p.to_record() for p in self.cone_field.profiles],
            "composition": "present absolute cone envelope over actual final background",
            "correction": "new present surface minus accepted final point reconstruction",
            "coordinate_system": "sphere, y north; short-arc profile distances",
            "author_pin_policy": (
                "coarse-mean pins remain in the background replay; "
                "crossing constraints must be checked for the chosen source"
            ),
        }


class FrozenVolcanicDeposit(FrozenVolcanicReplacement):
    """Present thickness on the actual substrate, with a declared central floor.

    The current cone volume and thickness slope are inherited from the source.
    The absolute flank also includes the local substrate gradient. This is a
    geometric deposition approximation; basal contact and overlap budgets are
    explicit, while volcanic flow and later erosion retain their source closure.
    """

    def __init__(
        self,
        profiles: Sequence[VolcanicCone],
        xyz: np.ndarray,
        reference_m: np.ndarray,
        background_m: np.ndarray,
        *,
        planet_radius_km: float,
        reference_id: str,
        background_reference_id: str,
    ) -> None:
        super().__init__(
            profiles,
            xyz,
            reference_m,
            background_m,
            planet_radius_km=planet_radius_km,
            reference_id=reference_id,
            background_reference_id=background_reference_id,
        )
        active = self.cone_field.profiles
        if active:
            central_background = self.reference_field(self.cone_field.centres)[..., 1]
            floors = [p.floor_elevation_m for p in active]
            if not np.allclose(central_background, floors, rtol=0, atol=1e-6):
                raise ValueError("deposit floors must match the actual central background")

    def evaluate(self, lat: np.ndarray, lon: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        xyz, values = self._query(lat, lon)
        delta = values[..., 1] + self.cone_field.thickness_m(xyz) - values[..., 0]
        return delta, np.zeros_like(delta)

    @property
    def metadata(self) -> dict[str, Any]:
        result = super().metadata
        result.update(
            kind="actual-background-volcanic-deposit-v1",
            composition="actual final background plus maximum present cone thickness",
            flank_policy="fixed thickness slope; absolute flank includes substrate gradient",
            budget="single-body spherical volume; overlapping envelopes measured separately",
            closure="geometric deposition approximation on the declared present background",
            profile_reference="listed emergent radius uses the horizontal central-floor datum",
            surface_emergence="zero contour of actual substrate plus current thickness",
        )
        return result
