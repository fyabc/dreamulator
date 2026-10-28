"""Connected landform curves with independent geometric and vertical evidence.

Geometrical support, height and the two normal slopes have separate provenance
and availability. Query coordinates use the geological unit sphere (y north).
Slopes are signed derivatives along the oriented curve's left normal; left and
right samples describe the two sides of a geological break independently.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any, Literal, cast

import numpy as np

from .spherical_terrain import SphericalCoastGeometry, SphericalPointTerrainField

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class CurveEvidence:
    """Source, information scale and reference age of one declared quantity."""

    category: Literal[
        "author_input", "observation", "geological_derivation", "numerical_reconstruction"
    ]
    source: str
    resolution_km: float
    epoch_myr: float | None = None
    uncertainty: str = "unavailable"

    def __post_init__(self) -> None:
        if (
            self.category
            not in (
                "author_input",
                "observation",
                "geological_derivation",
                "numerical_reconstruction",
            )
            or not self.source.strip()
        ):
            raise ValueError("curve evidence needs a known category and explicit source")
        if not np.isfinite(self.resolution_km) or self.resolution_km < 0:
            raise ValueError("information resolution must be finite and nonnegative")
        if self.epoch_myr is not None and (not np.isfinite(self.epoch_myr) or self.epoch_myr < 0):
            raise ValueError("reference age must be finite and nonnegative")


class SphericalTerrainCurve:
    """Frozen ordered minor arcs and optional point heights and side slopes.

    A closed curve repeats its first node and all available endpoint values.
    Geometry-only curves remain usable without acquiring a height or slope.
    Domain closures, neighbouring curves and connected regions are supplied
    by the landform source; they are not inferred from a query window.
    """

    def __init__(
        self,
        curve_id: str,
        kind: str,
        xyz: np.ndarray,
        *,
        radius_km: float,
        datum: str,
        geometry_evidence: CurveEvidence,
        closed: bool = False,
        height_m: np.ndarray | None = None,
        height_evidence: CurveEvidence | None = None,
        slope_left_m_per_km: np.ndarray | None = None,
        slope_left_evidence: CurveEvidence | None = None,
        slope_right_m_per_km: np.ndarray | None = None,
        slope_right_evidence: CurveEvidence | None = None,
    ) -> None:
        if not curve_id.strip() or not kind.strip() or not datum.strip():
            raise ValueError("curve id, kind and datum must be explicit")
        points = np.array(xyz, dtype=np.float64, copy=True)
        if points.ndim != 2 or points.shape[1] != 3 or len(points) < 2:
            raise ValueError("ordered curve nodes must have shape (n, 3), n >= 2")
        if closed and (len(points) < 4 or not np.array_equal(points[0], points[-1])):
            raise ValueError("closed curves must repeat the first node")
        self.geometry = SphericalCoastGeometry(
            np.stack([points[:-1], points[1:]], axis=1), radius_km
        )
        self.xyz = points
        self.curve_id, self.kind, self.datum, self.closed = curve_id, kind, datum, closed
        self.geometry_evidence = geometry_evidence
        self.height_evidence = height_evidence
        self.slope_left_evidence = slope_left_evidence
        self.slope_right_evidence = slope_right_evidence
        ages = {
            evidence.epoch_myr
            for evidence in (
                geometry_evidence,
                height_evidence,
                slope_left_evidence,
                slope_right_evidence,
            )
            if evidence is not None and evidence.epoch_myr is not None
        }
        if len(ages) > 1:
            raise ValueError("curve quantities must refer to the same reference age")
        arrays: list[np.ndarray | None] = []
        for data, evidence in (
            (height_m, height_evidence),
            (slope_left_m_per_km, slope_left_evidence),
            (slope_right_m_per_km, slope_right_evidence),
        ):
            if (data is None) != (evidence is None):
                raise ValueError("each available vertical quantity needs its own evidence")
            if data is None:
                arrays.append(None)
                continue
            value = np.array(data, dtype=np.float64, copy=True)
            if value.shape != (len(points),) or np.isinf(value).any():
                raise ValueError("curve values must match nodes; NaN marks unavailable samples")
            if closed and not np.array_equal(value[:1], value[-1:], equal_nan=True):
                raise ValueError("closed curve endpoint values must agree")
            value.setflags(write=False)
            arrays.append(value)
        self.height_m, self.slope_left_m_per_km, self.slope_right_m_per_km = arrays
        self.xyz.setflags(write=False)
        digest = hashlib.sha256()
        digest.update(json.dumps(self.metadata, sort_keys=True).encode())
        digest.update(self.xyz.astype("<f8").tobytes())
        for stored in arrays:
            if stored is not None:
                digest.update(stored.astype("<f8").tobytes())
        self.sha256 = digest.hexdigest()

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "format": "terrain-curve-v1",
            "id": self.curve_id,
            "kind": self.kind,
            "closed": self.closed,
            "datum": self.datum,
            "radius_km": self.geometry.radius_km,
            "node_count": len(self.xyz),
            "coordinate_frame": "unit vector; y north",
            "left_normal": "-(a cross b) in the geological y-north frame",
            "height_semantics": "point values on the declared curve",
            "slope_semantics": "m/km derivative toward left normal, evaluated on each side",
            "geometry_evidence": asdict(self.geometry_evidence),
            "height_evidence": None
            if self.height_evidence is None
            else asdict(self.height_evidence),
            "slope_left_evidence": None
            if self.slope_left_evidence is None
            else asdict(self.slope_left_evidence),
            "slope_right_evidence": None
            if self.slope_right_evidence is None
            else asdict(self.slope_right_evidence),
        }

    def query(self, xyz: np.ndarray, maximum_km: float | None = None) -> dict[str, np.ndarray]:
        """Read nearest connected arc samples; unavailable quantities stay NaN."""
        projection = self.geometry.project(xyz, maximum_km)
        valid = projection.segment_index >= 0
        ids = projection.segment_index[valid]
        t = projection.fraction[valid]
        result = {
            "distance_km": projection.distance_rad * self.geometry.radius_km,
            "side": -projection.side,
        }
        for key, value in (
            ("height_m", self.height_m),
            ("slope_left_m_per_km", self.slope_left_m_per_km),
            ("slope_right_m_per_km", self.slope_right_m_per_km),
        ):
            out = np.full(valid.shape, np.nan)
            if value is not None:
                out[valid] = np.where(
                    t == 0,
                    value[ids],
                    np.where(t == 1, value[ids + 1], (1 - t) * value[ids] + t * value[ids + 1]),
                )
            result[key] = out
        return result


class SphericalCurveBoundary:
    """Nearest samples from declared connected components of one source boundary."""

    def __init__(self, curves: list[SphericalTerrainCurve]) -> None:
        if not curves or len({curve.curve_id for curve in curves}) != len(curves):
            raise ValueError("boundary needs curves with unique ids")
        if len({(curve.geometry.radius_km, curve.datum) for curve in curves}) != 1:
            raise ValueError("boundary curves must share radius and vertical datum")
        if (
            len(
                {
                    curve.geometry_evidence.epoch_myr
                    for curve in curves
                    if curve.geometry_evidence.epoch_myr is not None
                }
            )
            > 1
        ):
            raise ValueError("boundary curves must share a reference age")
        self.curves = tuple(curves)
        self.geometry = SphericalCoastGeometry(
            np.concatenate([curve.geometry.geometry.segments for curve in curves]),
            curves[0].geometry.radius_km,
        )
        self._values = {}
        for key in ("height_m", "slope_left_m_per_km", "slope_right_m_per_km"):
            arrays = []
            for curve in curves:
                value = getattr(curve, key)
                arrays.append(
                    np.full((len(curve.xyz) - 1, 2), np.nan)
                    if value is None
                    else np.column_stack([value[:-1], value[1:]])
                )
            self._values[key] = np.concatenate(arrays)
            self._values[key].setflags(write=False)

    def query(self, xyz: np.ndarray) -> dict[str, np.ndarray]:
        projection = self.geometry.project(xyz)
        ids, t = projection.segment_index, projection.fraction
        result = {
            "distance_km": projection.distance_rad * self.geometry.radius_km,
            "side": -projection.side,
        }
        for key, value in self._values.items():
            result[key] = np.where(
                t == 0,
                value[ids, 0],
                np.where(t == 1, value[ids, 1], (1 - t) * value[ids, 0] + t * value[ids, 1]),
            )
        return result


def rational_profile_fraction(
    t: np.ndarray, lower_derivative: np.ndarray, upper_derivative: np.ndarray
) -> np.ndarray:
    """Monotone rational-quadratic interpolation with declared endpoint slopes.

    Derivatives are normalized by the profile secant slope. This interpolation
    has no free shape scale: endpoints and their nonnegative slopes determine
    it. Physical widths, amplitudes and slope evidence belong to the caller.
    """
    t, a, b = np.broadcast_arrays(
        np.asarray(t, dtype=float),
        np.asarray(lower_derivative, dtype=float),
        np.asarray(upper_derivative, dtype=float),
    )
    if not all(np.isfinite(x).all() for x in (t, a, b)):
        raise ValueError("profile coordinate and endpoint derivatives must be finite")
    if ((t < 0) | (t > 1) | (a < 0) | (b < 0)).any():
        raise ValueError("coordinate must be in [0,1], endpoint derivatives nonnegative")
    cross = t * (1 - t)
    result = (t * t + a * cross) / (1 + (a + b - 2) * cross)
    return np.asarray(np.where((a == 1) & (b == 1), t, result))


def contour_source_curves(
    field: SphericalPointTerrainField,
    level_m: float,
    radius_km: float,
    reference_id: str,
    *,
    channel: int = 0,
    epoch_myr: float | None = None,
) -> list[SphericalTerrainCurve]:
    """Expose a frozen source's contour loops with its original information scale."""
    if not reference_id.strip() or not np.isfinite(radius_km) or radius_km <= 0:
        raise ValueError("contour curves need a reference id and finite positive radius")
    evidence = CurveEvidence(
        "numerical_reconstruction",
        f"{reference_id}; point field {field.sha256}",
        float(np.sqrt(4 * np.pi * radius_km**2 / len(field.points))),
        epoch_myr,
        "continuous interpolation of original source samples",
    )
    curves = []
    for i, path in enumerate(field.contour_paths(level_m, channel)):
        closed = np.array_equal(path[0], path[-1])
        # Merge numerically indistinct consecutive nodes at the finite-arc
        # tolerance. This is independent of any physical profile width.
        path = path[np.r_[True, np.linalg.norm(np.diff(path, axis=0), axis=1) > 2e-10]]
        if closed:
            if np.linalg.norm(path[-1] - path[0]) <= 2e-10:
                path[-1] = path[0]
            else:
                path = np.r_[path, path[:1]]
        if len(path) < (4 if closed else 2):
            continue
        curves.append(
            SphericalTerrainCurve(
                f"{reference_id}-shore-{i}",
                "shoreline",
                path,
                radius_km=radius_km,
                datum=f"{reference_id}; sea level {level_m} m in original source datum",
                geometry_evidence=evidence,
                closed=closed,
                height_m=np.full(len(path), level_m),
                height_evidence=evidence,
            )
        )
    return curves


def save_terrain_curves(
    path: Path, curves: list[SphericalTerrainCurve], *, reference_id: str
) -> None:
    """Archive ordered curves and per-quantity evidence for one frozen reference."""
    if path.suffix != ".npz" or not reference_id.strip() or not curves:
        raise ValueError("curve archive needs .npz, curves and a frozen reference id")
    if len({curve.curve_id for curve in curves}) != len(curves):
        raise ValueError("curve ids must be unique in an archive")
    fields = {}
    descriptions = []
    for i, curve in enumerate(curves):
        fields[f"curve_{i}_xyz"] = curve.xyz
        for key in ("height_m", "slope_left_m_per_km", "slope_right_m_per_km"):
            value = getattr(curve, key)
            if value is not None:
                fields[f"curve_{i}_{key}"] = value
        descriptions.append({**curve.metadata, "sha256": curve.sha256})
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, **cast("Any", fields))
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    meta = {
        "format": "terrain-curves-v1",
        "reference_id": reference_id,
        "sha256": digest,
        "fields": list(fields),
        "curves": descriptions,
    }
    path.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n")


def load_terrain_curves(
    path: Path, *, expected_reference_id: str | None = None
) -> tuple[list[SphericalTerrainCurve], dict[str, Any]]:
    """Validate curve geometry, samples, evidence and archive reference together."""
    meta = json.loads(path.with_suffix(".json").read_text())
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if meta.get("format") != "terrain-curves-v1" or meta.get("sha256") != digest:
        raise ValueError("curve archive format or checksum mismatch")
    if expected_reference_id is not None and meta.get("reference_id") != expected_reference_id:
        raise ValueError("curve archive belongs to a different frozen reference")
    curves = []
    with np.load(path, allow_pickle=False) as archive:
        if set(archive.files) != set(meta["fields"]):
            raise ValueError("curve archive field list mismatch")
        for i, description in enumerate(meta["curves"]):
            arguments: dict[str, Any] = {}
            for key in ("height", "slope_left", "slope_right"):
                evidence = description[f"{key}_evidence"]
                unit = "m" if key == "height" else "m_per_km"
                arguments[f"{key}_{unit}"] = archive.get(f"curve_{i}_{key}_{unit}")
                arguments[f"{key}_evidence"] = (
                    None if evidence is None else CurveEvidence(**evidence)
                )
            curve = SphericalTerrainCurve(
                description["id"],
                description["kind"],
                archive[f"curve_{i}_xyz"],
                radius_km=description["radius_km"],
                datum=description["datum"],
                geometry_evidence=CurveEvidence(**description["geometry_evidence"]),
                closed=description["closed"],
                **arguments,
            )
            if curve.sha256 != description["sha256"] or any(
                description.get(key) != value for key, value in curve.metadata.items()
            ):
                raise ValueError("curve source geometry or evidence checksum mismatch")
            curves.append(curve)
    return curves, meta
