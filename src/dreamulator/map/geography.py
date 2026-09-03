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
# Feature-kernel roughening noise (separate from the score-blending fBm at +500,
# so the two noises are uncorrelated).
_FEATURE_NOISE_SEED_OFFSET = 501


def feature_noise_seed(config_seed: int) -> int:
    """Deterministic seed for the feature-kernel roughening noise."""
    return int(config_seed) + _FEATURE_NOISE_SEED_OFFSET


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
    #: fBm noise amplitude injected into the bias field kernel (0 = off).
    #: For rift features this roughens the otherwise smooth cosine-tapered
    #: boundary, creating fractal coastlines.  Typical: 0.1–0.5.
    noise_amplitude: float = Field(default=0.0, ge=0.0, le=3.0)


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
    #: Weight of the optional dense raster bias (geography_raster.png,
    #: Gleba-style probability map) when superposed onto the feature field.
    #: 0 disables the raster even if present.
    raster_weight: float = Field(default=1.0, ge=0.0, le=3.0)
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
    if noise_seed is not None and any(f.noise_amplitude > 0 for f in spec.features):
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
    for feature in spec.features:
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
    mesh: CVTMesh, spec: GeographySpec
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray] | None:
    """Kernel-weighted elevation pins for features with ``elevation_target_m``.

    Returns ``(weight, target_m, strength, exponent)`` arrays of shape (N,),
    or None when no feature declares a target.  Overlapping pins blend by
    kernel weight.  Pure function of (mesh, spec) — no randomness.
    """
    pinned = [f for f in spec.features if f.elevation_target_m is not None]
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

    return field, score, mask


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
    if spec is None or (not spec.features and raster_bias is None):
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
    if spec is None or (not spec.features and raster_bias is None):
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
