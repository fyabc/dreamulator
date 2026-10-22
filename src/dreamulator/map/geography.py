"""Authored geography — continent anchoring via a land-bias field.

Worldbuilding settings (e.g. nacrea's ``geography.yaml``) name landmasses and
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
from typing import TYPE_CHECKING

import numpy as np
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

if TYPE_CHECKING:
    from pathlib import Path

    from .models import CVTMesh
    from .pipeline_types import TerrainPipelineConfig

logger = logging.getLogger(__name__)

# Deterministic noise seed offset (convention: mesh=seed, plates=seed+1,
# tectonics=seed, synthesis=seed+100/+200).
_GEOGRAPHY_NOISE_SEED_OFFSET = 500
# Feature-kernel roughening noise (separate from the score-blending fBm at +500,
# so the two noises are uncorrelated).
_FEATURE_NOISE_SEED_OFFSET = 501


def feature_noise_seed(config_seed: int) -> int:
    """Deterministic seed for the feature-kernel roughening noise."""
    return int(config_seed) + _FEATURE_NOISE_SEED_OFFSET


class GeographyFeature(BaseModel):
    """One authored landmass / ocean feature anchored on the sphere."""

    # unknown keys are authoring errors (a misspelt or unsupported parameter would
    # otherwise be dropped silently)
    model_config = ConfigDict(extra="forbid")

    name: str
    lon: float = Field(default=0.0, ge=-180.0, le=180.0)
    #: Centre latitude of an ellipse feature (not used with ``polygon``).
    lat: float | None = Field(default=None, ge=-90.0, le=90.0)
    #: Circular radius in degrees; for elongated features this is the
    #: semi-minor axis (half-width).  Not used with ``polygon``.
    radius_deg: float | None = Field(default=None, gt=0.0, le=90.0)
    #: Outline as [lon, lat] vertices in degrees (GeoJSON order, closed implicitly,
    #: joined by great circles) — an alternative to the ellipse (lat, radius_deg,
    #: elongation, bearing_deg), for shapes an ellipse cannot draw.
    polygon: list[tuple[float, float]] | None = None
    #: Width (degrees) of a polygon's soft edge: the kernel is 0 on the outline and
    #: reaches 1 this far inside.
    edge_deg: float = Field(default=1.0, gt=0.0, le=30.0)
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
    #: Target elevation relative to the calibrated sea surface at 0 m
    #: (metres): positive = land height, negative = water depth (e.g.
    #: shallow_sea −120, isthmus +120).  Absolute against the datum — a
    #: sea_level_offset_m of −120 exposes a −80 m pin (glacial strait
    #: closure).  None = crust-only anchoring (legacy behaviour).
    elevation_target_m: float | None = None
    #: How strongly the pin pulls elevation toward the target (0–1); the
    #: spatial soft edge is provided by the feature kernel itself.
    pin_strength: float = Field(default=1.0, ge=0.0, le=1.0)
    #: Deviation exponent: >1 exaggerates the pull for cells far from target
    #: (山峰被强力下压, 平原温和调整).  1.0 = linear, 1.5 = moderate, 2.0 = aggressive.
    pin_exponent: float = Field(default=1.0, gt=0.0)
    #: Whether the pin may move cells across the sea surface.  False (default):
    #: the pin only adjusts heights on its own side — a positive target acts on
    #: land cells, a negative one on ocean cells — so mean-elevation pins (a
    #: continent's ~400 m) never turn coastal sea into land.  True: the pin is
    #: meant to change the land–sea pattern (a land bridge, a cut strait).
    pin_crosses_sea_level: bool = False
    #: fBm noise amplitude injected into the bias field kernel (0 = off).
    #: For rift features this roughens the otherwise smooth cosine-tapered
    #: boundary, creating fractal coastlines.  Typical: 0.1–0.5.
    noise_amplitude: float = Field(default=0.0, ge=0.0, le=5.0)

    @model_validator(mode="after")
    def _one_shape(self) -> GeographyFeature:
        if self.polygon is not None:
            if len(self.polygon) < 3:
                raise ValueError(f"{self.name}: a polygon needs at least 3 vertices")
            for lon, lat in self.polygon:
                if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
                    raise ValueError(f"{self.name}: polygon vertex out of range ({lon}, {lat})")
            if self.lat is not None or self.radius_deg is not None:
                raise ValueError(f"{self.name}: give either polygon or lat/radius_deg, not both")
        elif self.lat is None or self.radius_deg is None:
            raise ValueError(f"{self.name}: an ellipse feature needs lat and radius_deg")
        return self

    @property
    def size_deg(self) -> float:
        """Characteristic radius (degrees): the ellipse's semi-minor axis, or a polygon's
        mean centre-to-vertex distance."""
        if self.polygon is None:
            assert self.radius_deg is not None
            return self.radius_deg
        v = np.array([_lonlat_to_xyz(lon, lat) for lon, lat in self.polygon])
        c = v.sum(axis=0)
        c /= np.linalg.norm(c)
        return float(np.degrees(np.arccos(np.clip(v @ c, -1.0, 1.0))).mean())


class GeographySpec(BaseModel):
    """Machine-readable authored geography (``geography.yaml``)."""

    model_config = ConfigDict(extra="forbid")

    version: int = 1
    #: Target land fraction; defaults to config.target_land_fraction when None.
    land_fraction_target: float | None = Field(default=None, gt=0.0, lt=1.0)
    #: >0 biases land toward the northern hemisphere (smooth sin-lat weighting).
    hemisphere_land_bias: float = Field(default=0.0, ge=-1.0, le=1.0)
    #: Re-stamp crust from the anchor field after tectonic evolution so
    #: authored continents do not drift with their plates.
    reapply_after_tectonics: bool = True
    #: Weight of the optional dense raster bias (geography_raster.png,
    #: Gleba-style probability map) when superposed onto the feature field.
    #: 0 disables the raster even if present.
    raster_weight: float = Field(default=1.0, ge=0.0, le=3.0)
    #: Plate-affecting features: continents, rift seas, straits — they steer
    #: the plate seeds / crust partition and re-anchoring, so editing them
    #: regenerates the global plate realization (new ridges, moved coasts
    #: everywhere).  Editing them is a *world-shaping* act.
    features: list[GeographyFeature] = Field(default_factory=list)
    #: Terrain-only overlays (2026-09-30): coast roughening, archipelago
    #: noise, local seaway carves / land additions.  Invisible to the plate
    #: stage (seeds, crust, coast cost, re-anchor) and to the
    #: plates/tectonics cache fingerprints — editing them keeps the plate
    #: realization bit-identical and the change stays local to the patch.
    #: The water-budget calibration solves the global sea level blind to the
    #: overlay discs, so overlays create local deviations instead of moving
    #: every coastline; the global land fraction drifts by their net
    #: contribution (the intended "local edit" semantics).  See the yaml
    #: header for the authoring rules in plain language.
    overlays: list[GeographyFeature] = Field(default_factory=list)

    @property
    def all_features(self) -> list[GeographyFeature]:
        """Every feature the terrain stage consumes (plate + overlay)."""
        return list(self.features) + list(self.overlays)

    def plate_view(self) -> GeographySpec:
        """Spec with terrain-only features stripped — what the plate stage sees.

        Plates, tectonics and the crust re-anchor consume this view, so
        overlays (coast roughening, archipelago noise, local carves) cannot
        reshape the plate partition or reshuffle the world.
        """
        if not self.overlays:
            return self
        return self.model_copy(update={"overlays": []})

    def plates_fingerprint(self) -> str:
        """Stable hash of the plate-affecting geography (excludes overlays).

        Used for the plates/tectonics cache fingerprints, replacing the raw
        geography.yaml file hash there — overlay-only edits keep those caches
        valid.  The terrain stage keeps using the full-file hash.
        """
        import hashlib

        payload = self.plate_view().model_dump_json()
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def overlay_cell_mask(
        self, px: np.ndarray, py: np.ndarray, pz: np.ndarray, *, threshold: float = 0.05
    ) -> np.ndarray | None:
        """Boolean mask of cells inside any overlay (None when there are none).

        The water-budget calibration solves the global sea level on the
        *non-overlay* cells only, so an overlay's added/carved land creates a
        local deviation instead of dragging every coastline on the planet
        (2026-09-30: a single seaway overlay shifted the calibration by tens
        of metres and moved every coast).  Noise-free kernel discs — the mask
        is a conservative boundary (≈86% of each overlay's nominal radius),
        not a coastline.
        """
        if not self.overlays:
            return None
        mask = np.zeros(px.shape[0], dtype=bool)
        for f in self.overlays:
            mask |= _feature_kernel(px, py, pz, f, noise=None) > threshold
        return mask


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
        len(spec.all_features),
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


def _feature_kernel(
    px: np.ndarray,
    py: np.ndarray,
    pz: np.ndarray,
    feature: GeographyFeature,
    noise: np.ndarray | None = None,
) -> np.ndarray:
    """Per-cell kernel of one feature: 1 at the centre → 0 at the edge (N,).

    ``noise`` (optional, per-cell fBm in [-1, 1]) roughens the otherwise smooth
    cosine-tapered boundary: the effective radius is scaled by
    ``1 + noise_amplitude·noise``, so the ellipse / rift edge becomes a fractal
    coastline instead of a regular shape.
    """
    if feature.polygon is not None:
        return _polygon_kernel(px, py, pz, feature, noise)
    assert feature.lat is not None and feature.radius_deg is not None
    c = _lonlat_to_xyz(feature.lon, feature.lat)
    p = np.stack([px, py, pz], axis=1)
    dot = np.clip(p @ c, -1.0, 1.0)
    d = np.arccos(dot)  # great-circle distance (radians)

    radius_rad = np.radians(feature.radius_deg)
    # Polar anchors (or circular features): pure angular-distance kernel.
    polar = abs(abs(feature.lat) - 90.0) < 1e-6
    if feature.elongation <= 1.0 + 1e-9 or polar:
        q = d / radius_rad
        if feature.noise_amplitude > 0 and noise is not None:
            q = q / (1.0 + feature.noise_amplitude * noise)
        return _cosine_kernel(q)

    # Elongated feature: elliptic metric in the tangent plane at the centre.
    semi_major = radius_rad * feature.elongation
    semi_minor = radius_rad
    # The tangent-plane projection degenerates at the antipode (offset → 0 →
    # q → 0, a spurious full-strength hit on the far side of the planet).
    # Pre-filter by the noise-expanded semi-major axis so the roughening can
    # still push the edge outward (the antipode stays far outside).
    result = np.zeros(p.shape[0])
    margin = 1.0 + max(feature.noise_amplitude, 0.0)
    within = d <= semi_major * margin
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
    if feature.noise_amplitude > 0 and noise is not None:
        q = q / (1.0 + feature.noise_amplitude * noise)
    result[within] = _cosine_kernel(q[within])
    return result


def _polygon_kernel(
    px: np.ndarray,
    py: np.ndarray,
    pz: np.ndarray,
    feature: GeographyFeature,
    noise: np.ndarray | None = None,
) -> np.ndarray:
    """Kernel of a polygon feature: 0 outside and on the outline, rising with a cosine
    taper to 1 at ``edge_deg`` inside.

    Inside/outside is a ray-casting test in the gnomonic projection about the vertex
    centroid (great-circle edges are straight lines there); the distance is the angular
    distance to the closed outline.  ``noise`` shifts the signed distance by
    ``noise_amplitude · edge_deg · noise``, roughening the outline by at most that much.
    """
    from .paleo_sutures import polyline_geometry

    assert feature.polygon is not None
    verts = np.array(feature.polygon, dtype=np.float64)
    vx = np.array([_lonlat_to_xyz(lon, lat) for lon, lat in verts])
    c = vx.sum(axis=0)
    c /= np.linalg.norm(c)
    edge = np.radians(feature.edge_deg)
    amp = feature.noise_amplitude if noise is not None else 0.0
    reach = float(np.arccos(np.clip(vx @ c, -1.0, 1.0)).max()) + edge * (1.0 + amp)
    p = np.stack([px, py, pz], axis=1)
    dot = p @ c
    out = np.zeros(p.shape[0])
    near = (dot > np.cos(min(reach, np.pi / 2 - 1e-3))) & (dot > 0.0)
    if not near.any():
        return out
    q = p[near]
    north, east = _tangent_frame(c)
    qd = q @ c
    x, y = (q @ east) / qd, (q @ north) / qd
    vd = vx @ c
    ux, uy = (vx @ east) / vd, (vx @ north) / vd
    inside = np.zeros(q.shape[0], dtype=bool)
    for k in range(len(ux)):  # even–odd ray casting along +x
        x0, y0, x1, y1 = ux[k - 1], uy[k - 1], ux[k], uy[k]
        cross = (y0 > y) != (y1 > y)
        xi = x0 + (y - y0) * (x1 - x0) / np.where(y1 != y0, y1 - y0, 1e-300)
        inside ^= cross & (x < xi)
    closed = np.vstack([verts, verts[:1]])
    dist = polyline_geometry(q, closed)[0]
    signed = np.where(inside, dist, -dist)
    if amp > 0.0 and noise is not None:
        signed = signed + amp * edge * noise[near]
    t = np.clip(signed / edge, 0.0, 1.0)
    out[near] = 0.5 * (1.0 - np.cos(np.pi * t))
    return out


def _feature_contribution(
    px: np.ndarray,
    py: np.ndarray,
    pz: np.ndarray,
    feature: GeographyFeature,
    noise: np.ndarray | None = None,
) -> np.ndarray:
    """Per-cell bias contribution of one feature (array of shape (N,))."""
    return feature.strength * _feature_kernel(px, py, pz, feature, noise)


def build_land_bias_field(
    mesh: CVTMesh,
    spec: GeographySpec,
    *,
    raster_bias: np.ndarray | None = None,
    noise_seed: int | None = None,
) -> np.ndarray:
    """Build the per-cell land-bias field in [-1, 1].

    Positive values favour continental crust, negative oceanic.  Pure function
    of (mesh, spec[, raster_bias, noise_seed]) — no randomness.  When a dense
    raster bias (Gleba-style probability map, [-1, 1] per cell) is given, it is
    superposed with weight ``spec.raster_weight`` — same treatment as the
    feature field.  ``noise_seed`` enables the per-feature ``noise_amplitude``
    roughening (deterministic fBm); omit it to keep features smooth.
    """
    n = len(mesh.cells)
    px = np.fromiter((c.x for c in mesh.cells), dtype=np.float64, count=n)
    py = np.fromiter((c.y for c in mesh.cells), dtype=np.float64, count=n)
    pz = np.fromiter((c.z for c in mesh.cells), dtype=np.float64, count=n)

    # Feature-roughening noise (computed once, shared across features) — only
    # when a seed is given and at least one feature declares noise_amplitude.
    noise: np.ndarray | None = None
    if noise_seed is not None and any(f.noise_amplitude > 0 for f in spec.all_features):
        from .noise_kernels import fbm_on_points

        noise = fbm_on_points(
            px,
            py,
            pz,
            noise_seed,
            octaves=5,
            lacunarity=2.5,
            persistence=0.5,
            base_freq=15.0,
        )

    field = np.zeros(n, dtype=np.float64)
    for feature in spec.all_features:
        field += _feature_contribution(px, py, pz, feature, noise)

    if spec.hemisphere_land_bias != 0.0:
        lat_rad = np.fromiter((np.radians(c.lat) for c in mesh.cells), dtype=np.float64, count=n)
        field += spec.hemisphere_land_bias * np.sin(lat_rad)

    if raster_bias is not None and spec.raster_weight != 0.0:
        field += spec.raster_weight * raster_bias

    return np.clip(field, -1.0, 1.0)


def load_geography_raster(path: Path | None) -> np.ndarray | None:
    """Load the optional dense bias raster (grayscale heightmap convention).

    The raster is stored as ``geography_raster.png`` next to geography.yaml
    (any importer-supported format works).  Grayscale [0, 1] is mapped to a
    bias in [-1, 1] (mid-grey = neutral).  Returns None when absent.
    """
    if path is None:
        return None
    try:
        data = path.read_bytes()
    except OSError as exc:
        logger.warning("geography raster unreadable (%s): %s", path, exc)
        return None
    from .importer import import_heightmap

    result = import_heightmap(data, filename=path.name)
    return np.asarray(2.0 * result.elevation - 1.0)


def sample_raster_at_cells(mesh: CVTMesh, raster: np.ndarray) -> np.ndarray:
    """Nearest-pixel sampling of a (H, W) equirectangular raster at cells."""
    from .elevation_codec import lon_lat_to_pixel

    h, w = raster.shape
    out = np.empty(len(mesh.cells), dtype=np.float64)
    for i, cell in enumerate(mesh.cells):
        x, y = lon_lat_to_pixel(cell.lon, cell.lat, w, h)
        out[i] = raster[y, x]
    return out


def build_elevation_pins(
    mesh: CVTMesh, spec: GeographySpec, *, crosses_sea_level: bool | None = None
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray] | None:
    """Kernel-weighted elevation pins for features with ``elevation_target_m``.

    Returns ``(weight, target_m, strength, exponent)`` arrays of shape (N,),
    or None when no feature declares a target.  Overlapping pins blend by
    kernel weight.  ``crosses_sea_level`` selects only the features with that
    ``pin_crosses_sea_level`` value (None = all).  Pure function of (mesh,
    spec) — no randomness.
    """
    pinned = [
        f
        for f in spec.all_features
        if f.elevation_target_m is not None
        and (crosses_sea_level is None or f.pin_crosses_sea_level == crosses_sea_level)
    ]
    if not pinned:
        return None

    n = len(mesh.cells)
    px = np.fromiter((c.x for c in mesh.cells), dtype=np.float64, count=n)
    py = np.fromiter((c.y for c in mesh.cells), dtype=np.float64, count=n)
    pz = np.fromiter((c.z for c in mesh.cells), dtype=np.float64, count=n)

    w_sum = np.zeros(n, dtype=np.float64)
    wt = np.zeros(n, dtype=np.float64)
    ws = np.zeros(n, dtype=np.float64)
    we = np.zeros(n, dtype=np.float64)
    for feature in pinned:
        target_m = feature.elevation_target_m
        if target_m is None:  # narrowed by the filter above; mypy guard
            continue
        k = _feature_kernel(px, py, pz, feature)
        w_sum += k
        wt += k * target_m
        ws += k * feature.pin_strength
        we += k * feature.pin_exponent

    weight = np.clip(w_sum, 0.0, 1.0)
    target = np.divide(wt, w_sum, out=np.zeros(n), where=w_sum > 0.0)
    strength = np.divide(ws, w_sum, out=np.zeros(n), where=w_sum > 0.0)
    exponent = np.divide(we, w_sum, out=np.ones(n), where=w_sum > 0.0)
    return weight, target, strength, exponent


# ---------------------------------------------------------------------------
# Crust assignment from the bias field
# ---------------------------------------------------------------------------


def compute_geography_land_mask(
    mesh: CVTMesh,
    config: TerrainPipelineConfig,
    *,
    anchor_weight: float | None = None,
    raster_bias: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Compute ``(field, score, continental_mask)`` from the authored geography.

    Pure function of ``(mesh, config[, raster_bias])`` — no side effects.  The
    continental mask is the top ``target_land_fraction`` cells by
    ``score = anchor_weight·field + (1−anchor_weight)·fBm``.  ``apply_geography_crust``
    writes this mask to ``crust_type``; ``build_geography_coast_cost`` reuses the
    mask to locate the coastline.  Returns all three (n,) arrays so callers that
    need the field (seed interiority) or score (crust floor) don't recompute the
    fBm.

    The caller must guarantee a geography spec is present (``config.geography``
    is not None and has features or a raster).
    """
    from .noise_kernels import fbm_on_points

    spec = config.geography
    assert spec is not None, "compute_geography_land_mask requires config.geography"

    n = len(mesh.cells)

    weight = config.anchor_weight if anchor_weight is None else anchor_weight
    weight = float(min(max(weight, 0.0), 1.0))
    target_fraction = spec.land_fraction_target or config.target_land_fraction

    field = build_land_bias_field(
        mesh, spec, raster_bias=raster_bias, noise_seed=feature_noise_seed(int(config.seed))
    )

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
    mask = np.zeros(n, dtype=np.bool_)
    mask[order[:n_land]] = True
    _fill_oceanic_specks(
        mesh, mask, build_land_bias_field(mesh, spec, raster_bias=raster_bias, noise_seed=None)
    )

    return field, score, mask


#: An oceanic-crust patch enclosed by continental crust of up to this many cells is a speck
#: of the noisy threshold (54 km cells: ~20 cells ≈ 60 000 km², the scale of the smallest
#: trapped ocean basins); larger enclosed patches are basins and stay.  Numerical convention.
_SPECK_MAX_CELLS = 20


def _fill_oceanic_specks(mesh: CVTMesh, mask: np.ndarray, authored: np.ndarray) -> int:
    """Turn oceanic specks inside continents into continental crust (``mask`` in place).

    The partition takes the top cells of a noisy score, so the noise leaves specks of
    oceanic crust inside the continents; with the ocean base they become round pits and
    ponds a few cells wide in continental interiors.  An oceanic component of the mask
    that is not the world ocean, has at most ``_SPECK_MAX_CELLS`` cells and lies where the
    author did not ask for sea (noise-free bias ``authored`` nowhere below −0.3) is filled.
    Returns the number of cells filled.
    """
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import connected_components

    cells = mesh.cells
    n = len(cells)
    ocean = ~mask
    if not ocean.any():
        return 0
    rows = np.repeat(np.arange(n), [len(c.neighbors) for c in cells])
    cols = np.array([j for c in cells for j in c.neighbors], dtype=np.int64)
    both = ocean[rows] & ocean[cols]
    graph = csr_matrix((np.ones(int(both.sum())), (rows[both], cols[both])), shape=(n, n))
    _, lab = connected_components(graph, directed=False)
    labels, sizes = np.unique(lab[ocean], return_counts=True)
    world_ocean = labels[np.argmax(sizes)]
    filled = 0
    for lbl, size in zip(labels, sizes, strict=True):
        if lbl == world_ocean or size > _SPECK_MAX_CELLS:
            continue
        idx = np.flatnonzero(lab == lbl)
        if np.any(authored[idx] < -0.3):
            continue  # an authored sea
        mask[idx] = True
        filled += int(size)
    if filled:
        logger.info("  Crust partition: %d oceanic speck cells filled", filled)
    return filled


def build_geography_coast_cost(
    mesh: CVTMesh,
    config: TerrainPipelineConfig,
    *,
    raster_bias: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    """Coast-attraction cost field for the weighted plate partition (§5).

    Returns ``(coast_cost, field, mask)`` or None when no authored geography is
    present.  ``coast_cost[i] = 1 + w·max(0, 1 − d_i/band)`` where ``d_i`` is the
    geodesic distance (km) from cell ``i`` to the nearest coastline cell (a cell
    whose continental mask differs from a neighbour's), ``band`` ≈ 2 mean cell
    spacings, and ``w = geography_boundary_weight``.

    A coastline is a plate boundary on Earth (continent ↔ ocean).  Weighting the
    Dijkstra partition's cell-entry cost to be HIGHER near the coast pins the
    meeting front of a continental-plate wavefront and an oceanic-plate wavefront
    onto the coast, aligning plate boundaries with continental margins (§5 方案 2).
    """
    spec = config.geography
    if spec is None or (not spec.features and not spec.overlays and raster_bias is None):
        return None

    from .distance import geodesic_bfs

    n = len(mesh.cells)
    field, _score, mask = compute_geography_land_mask(mesh, config, raster_bias=raster_bias)

    # Coast cells = boundary of the continental mask (a neighbour has the
    # opposite crust).
    coast = np.zeros(n, dtype=np.bool_)
    for i in range(n):
        for nb in mesh.cells[i].neighbors:
            if mask[nb] != mask[i]:
                coast[i] = True
                break
    coast_ids = [int(i) for i in np.where(coast)[0]]
    if not coast_ids:
        return np.ones(n, dtype=np.float64), field, mask

    dist = geodesic_bfs(mesh, coast_ids, config.radius_km)
    band_km = 2.0 * float(np.sqrt(4.0 * np.pi * config.radius_km**2 / n))
    w = float(config.geography_boundary_weight)
    cost = np.ones(n, dtype=np.float64)
    for i, d in dist.items():
        cost[i] += w * max(0.0, 1.0 - d / band_km)
    return cost, field, mask


def apply_geography_crust(
    mesh: CVTMesh,
    config: TerrainPipelineConfig,
    *,
    anchor_weight: float | None = None,
    raster_bias: np.ndarray | None = None,
) -> None:
    """Set per-cell crust_type from the authored geography.

    ``score = anchor_weight * bias_field + (1 - anchor_weight) * fBm``; the top
    ``target_land_fraction`` cells by score become continental.  Used both for
    the initial assignment (plate stage) and the post-tectonics re-anchor, so
    the two use identical seeds and produce identical land patterns.

    Modifies ``mesh.cells[*].crust_type`` in place.
    """
    spec: GeographySpec | None = config.geography
    if spec is None or (not spec.features and not spec.overlays and raster_bias is None):
        return

    n = len(mesh.cells)
    if n == 0:
        return

    target_fraction = spec.land_fraction_target or config.target_land_fraction

    field, score, mask = compute_geography_land_mask(
        mesh, config, anchor_weight=anchor_weight, raster_bias=raster_bias
    )
    n_land = int(mask.sum())
    for i in range(n):
        mesh.cells[i].crust_type = "continental" if mask[i] else "oceanic"

    # Per-plate continental floor: the global top-N threshold can leave whole
    # plates near-zero continental crust (Earth has ~40% mostly-oceanic
    # plates, not ~64%).  Promote each non-exempt plate's highest-scoring
    # oceanic cells up to the floor.  Plates whose authored bias is decisively
    # oceanic (mean field < -0.3, e.g. the southern-ocean ring) are exempt.
    # The global land fraction is re-absorbed by sea-level calibration.
    floor = config.crust_plate_floor
    if floor > 0.0:
        by_plate: dict[str, list[int]] = {}
        for i, c in enumerate(mesh.cells):
            if c.plate_id:
                by_plate.setdefault(c.plate_id, []).append(i)
        floored = 0
        for idxs in by_plate.values():
            if len(idxs) < 8:
                continue
            mean_bias = float(np.mean(field[np.asarray(idxs, dtype=np.int64)]))
            if mean_bias < -0.3:
                continue  # decisively authored ocean
            n_cont = sum(1 for i in idxs if mesh.cells[i].crust_type == "continental")
            need = int(floor * len(idxs)) - n_cont
            if need <= 0:
                continue
            oceanic = [i for i in idxs if mesh.cells[i].crust_type == "oceanic"]
            oceanic.sort(key=lambda i: -score[i])
            for i in oceanic[:need]:
                mesh.cells[i].crust_type = "continental"
                floored += 1
        if floored:
            logger.info("  Crust floor: %d cells promoted across plates", floored)

    logger.info(
        "Geography anchoring: %d/%d cells continental (target %.1f%%)",
        n_land,
        n,
        target_fraction * 100.0,
    )
