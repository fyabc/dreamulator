"""Authored geography — continent anchoring via a land-bias field.

Worldbuilding settings (e.g. gaia-m's ``geography.yaml``) name landmasses and
oceans anchored to lon/lat.  This module turns that spec into a per-cell
**land-bias field** on the CVT mesh ([-1, 1]: positive = land, negative =
ocean) which ``plate_generator.assign_crust_types`` consumes through a global
threshold instead of its usual per-plate random fractions.

Design precedent (see roadmap / plan): Gleba's custom landmass-probability-map
import; Azgaar's heightmap templates.  Without a spec, the pipeline behaves
exactly as before (per-plate fractions).

Determinism: all randomness derives from ``config.seed`` offsets (mesh=seed,
plates=seed+1, geography noise=seed+500), so the initial crust assignment and
the post-tectonics re-anchor produce identical land patterns.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

import numpy as np
import yaml
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from pathlib import Path

    from .models import CVTMesh
    from .pipeline_types import TerrainPipelineConfig

logger = logging.getLogger(__name__)

# Deterministic noise seed offset (convention: mesh=seed, plates=seed+1,
# tectonics=seed, synthesis=seed+100/+200).
_GEOGRAPHY_NOISE_SEED_OFFSET = 500

FeatureKind = Literal[
    "continent",
    "archipelago",
    "plateau",
    "ocean_basin",
    "rift_sea",
    "shallow_sea",
    "isthmus",
]


class GeographyFeature(BaseModel):
    """One authored landmass / ocean feature anchored on the sphere."""

    name: str
    kind: FeatureKind = "continent"
    lon: float = Field(default=0.0, ge=-180.0, le=180.0)
    lat: float = Field(ge=-90.0, le=90.0)
    #: Circular radius in degrees; for elongated features this is the
    #: semi-minor axis (half-width).
    radius_deg: float = Field(gt=0.0, le=90.0)
    #: Bias amplitude. + = land, − = ocean. Magnitudes above 1 let a "cutting"
    #: feature (rift_sea, isthmus gap) overwhelm an underlying continent so the
    #: net field goes negative there (e.g. rift −1.8 over continent +0.85).
    #: Values down to −3 express anomalously deep collapse basins.
    strength: float = Field(default=1.0, ge=-3.0, le=3.0)
    #: Semi-major / semi-minor axis ratio (≥1; 1 = circular).
    elongation: float = Field(default=1.0, ge=1.0)
    #: Semi-major axis bearing in degrees (0 = north, 90 = east). Negative
    #: values tilt the opposite way (−12 ≡ 348); cos/sin handle either sign.
    bearing_deg: float = Field(default=0.0, ge=-360.0, le=360.0)


class GeographySpec(BaseModel):
    """Machine-readable authored geography (``geography.yaml``)."""

    version: int = 1
    #: Target land fraction; defaults to config.target_land_fraction when None.
    land_fraction_target: float | None = Field(default=None, gt=0.0, lt=1.0)
    #: >0 biases land toward the northern hemisphere (smooth sin-lat weighting).
    hemisphere_land_bias: float = Field(default=0.0, ge=-1.0, le=1.0)
    #: Re-stamp crust from the anchor field after tectonic evolution so
    #: authored continents do not drift with their plates.
    reapply_after_tectonics: bool = True
    features: list[GeographyFeature] = Field(default_factory=list)


def load_geography_spec(path: Path | None) -> GeographySpec | None:
    """Load and validate a geography spec; None when absent/unreadable."""
    if path is None:
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except OSError as exc:
        logger.warning("geography spec unreadable (%s): %s", path, exc)
        return None
    if not data:
        return None
    spec = GeographySpec.model_validate(data)
    logger.info(
        "Loaded geography spec '%s': %d features",
        path.name,
        len(spec.features),
    )
    return spec


# ---------------------------------------------------------------------------
# Sphere helpers (mesh convention: x=cosφcosλ, y=sinφ, z=cosφsinλ; y=north)
# ---------------------------------------------------------------------------


def _lonlat_to_xyz(lon_deg: float, lat_deg: float) -> np.ndarray:
    lon = np.radians(lon_deg)
    lat = np.radians(lat_deg)
    cos_lat = np.cos(lat)
    return np.array([cos_lat * np.cos(lon), np.sin(lat), cos_lat * np.sin(lon)])


def _tangent_frame(c: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Orthonormal tangent basis (north, east) at unit vector *c*.

    Degenerate at the poles — callers must treat polar anchors as circular.
    """
    up = np.array([0.0, 1.0, 0.0])
    north = up - np.dot(up, c) * c
    norm = np.linalg.norm(north)
    if norm < 1e-12:  # at a pole: pick any tangent basis
        return np.array([0.0, 0.0, 1.0]), np.array([1.0, 0.0, 0.0])
    north /= norm
    east = np.array([-c[2], 0.0, c[0]])
    east_norm = np.linalg.norm(east)
    if east_norm < 1e-12:
        east = np.cross(north, c)
    else:
        east /= east_norm
    return north, east


def _cosine_kernel(q: np.ndarray) -> np.ndarray:
    """Smooth bell: 1 at q=0 → 0 at q≥1 (C¹ at the edge)."""
    out = np.zeros_like(q)
    m = q < 1.0
    out[m] = 0.5 * (1.0 + np.cos(np.pi * q[m]))
    return out


def _feature_contribution(
    px: np.ndarray,
    py: np.ndarray,
    pz: np.ndarray,
    feature: GeographyFeature,
) -> np.ndarray:
    """Per-cell bias contribution of one feature (array of shape (N,))."""
    c = _lonlat_to_xyz(feature.lon, feature.lat)
    p = np.stack([px, py, pz], axis=1)
    dot = np.clip(p @ c, -1.0, 1.0)
    d = np.arccos(dot)  # great-circle distance (radians)

    radius_rad = np.radians(feature.radius_deg)
    # Polar anchors (or circular features): pure angular-distance kernel.
    polar = abs(abs(feature.lat) - 90.0) < 1e-6
    if feature.elongation <= 1.0 + 1e-9 or polar:
        q = d / radius_rad
        return feature.strength * _cosine_kernel(q)

    # Elongated feature: elliptic metric in the tangent plane at the centre.
    semi_major = radius_rad * feature.elongation
    semi_minor = radius_rad
    # The tangent-plane projection degenerates at the antipode (offset → 0 →
    # q → 0, a spurious full-strength hit on the far side of the planet).
    # Any point farther than the semi-major axis is outside the ellipse
    # regardless, so zero those first — this also removes the antipode.
    result = np.zeros(p.shape[0])
    within = d <= semi_major
    if not np.any(within):
        return result
    north, east = _tangent_frame(c)
    bearing = np.radians(feature.bearing_deg)
    axis = np.cos(bearing) * north + np.sin(bearing) * east
    perp = np.cross(c, axis)
    # Tangent offset (chord component); ≈ angular for the small distances
    # involved — the kernel only needs monotonic, smooth behaviour.
    v = p - np.outer(dot, c)
    along = v @ axis
    across = v @ perp
    q = np.sqrt((along / semi_major) ** 2 + (across / semi_minor) ** 2)
    result[within] = _cosine_kernel(q[within])
    return feature.strength * result


def build_land_bias_field(mesh: CVTMesh, spec: GeographySpec) -> np.ndarray:
    """Build the per-cell land-bias field in [-1, 1].

    Positive values favour continental crust, negative oceanic.  Pure function
    of (mesh, spec) — no randomness.
    """
    n = len(mesh.cells)
    px = np.fromiter((c.x for c in mesh.cells), dtype=np.float64, count=n)
    py = np.fromiter((c.y for c in mesh.cells), dtype=np.float64, count=n)
    pz = np.fromiter((c.z for c in mesh.cells), dtype=np.float64, count=n)

    field = np.zeros(n, dtype=np.float64)
    for feature in spec.features:
        field += _feature_contribution(px, py, pz, feature)

    if spec.hemisphere_land_bias != 0.0:
        lat_rad = np.fromiter((np.radians(c.lat) for c in mesh.cells), dtype=np.float64, count=n)
        field += spec.hemisphere_land_bias * np.sin(lat_rad)

    return np.clip(field, -1.0, 1.0)


# ---------------------------------------------------------------------------
# Crust assignment from the bias field
# ---------------------------------------------------------------------------


def apply_geography_crust(
    mesh: CVTMesh,
    config: TerrainPipelineConfig,
    *,
    anchor_weight: float | None = None,
) -> None:
    """Set per-cell crust_type from the authored geography.

    ``score = anchor_weight * bias_field + (1 - anchor_weight) * fBm``; the top
    ``target_land_fraction`` cells by score become continental.  Used both for
    the initial assignment (plate stage) and the post-tectonics re-anchor, so
    the two use identical seeds and produce identical land patterns.

    Modifies ``mesh.cells[*].crust_type`` in place.
    """
    from .noise_kernels import fbm_on_points

    spec: GeographySpec | None = config.geography
    if spec is None or not spec.features:
        return

    n = len(mesh.cells)
    if n == 0:
        return

    weight = config.anchor_weight if anchor_weight is None else anchor_weight
    weight = float(min(max(weight, 0.0), 1.0))

    target_fraction = spec.land_fraction_target or config.target_land_fraction

    field = build_land_bias_field(mesh, spec)

    px = np.fromiter((c.x for c in mesh.cells), dtype=np.float64, count=n)
    py = np.fromiter((c.y for c in mesh.cells), dtype=np.float64, count=n)
    pz = np.fromiter((c.z for c in mesh.cells), dtype=np.float64, count=n)
    noise_seed = int(config.seed) + _GEOGRAPHY_NOISE_SEED_OFFSET
    fbm = fbm_on_points(
        px,
        py,
        pz,
        noise_seed,
        octaves=5,
        lacunarity=2.5,
        persistence=0.5,
        base_freq=2.0,
    )

    score = weight * field + (1.0 - weight) * fbm

    n_land = int(round(target_fraction * n))
    n_land = min(max(n_land, 0), n)
    # score[i] corresponds to mesh.cells[i]; argsort positions index the list.
    order = np.argsort(score)[::-1]
    for pos in order[:n_land]:
        mesh.cells[int(pos)].crust_type = "continental"
    for pos in order[n_land:]:
        mesh.cells[int(pos)].crust_type = "oceanic"

    logger.info(
        "Geography anchoring: %d/%d cells continental (target %.1f%%)",
        n_land,
        n,
        target_fraction * 100.0,
    )
