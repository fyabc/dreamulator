"""Map data models — metadata, Voronoi cells, tectonic plates, map layers."""

from __future__ import annotations

import math
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Projection & metadata
# ---------------------------------------------------------------------------


class MapProjection(str, Enum):
    """Supported map projections."""

    EQUIRECTANGULAR = "equirectangular"


class MapMetadata(BaseModel):
    """Map metadata — stored in maps/<planet_id>/map.yaml."""

    planet_id: str = Field(description="Planet identifier (matches Planet.id)")
    projection: MapProjection = Field(
        default=MapProjection.EQUIRECTANGULAR,
        description="Map projection type",
    )
    width: int = Field(default=4096, gt=0, description="Raster width in pixels")
    height: int = Field(default=2048, gt=0, description="Raster height in pixels")
    elevation_min_m: float = Field(
        default=-11_000.0,
        description="Minimum elevation in metres (e.g. Mariana Trench)",
    )
    elevation_max_m: float = Field(
        default=9_000.0,
        description="Maximum elevation in metres (e.g. Everest)",
    )
    sea_level_m: float = Field(
        default=0.0,
        description="Sea level in metres (absolute)",
    )
    voronoi_seed: int | None = Field(
        default=None,
        description="RNG seed for Voronoi network generation (None = use world seed)",
    )
    voronoi_num_cells: int = Field(
        default=100_000,
        gt=0,
        description="Target number of Voronoi cells",
    )
    cvt_jitter_sigma: float = Field(
        default=0.3,
        ge=0,
        description="Random jitter applied to initial Fibonacci lattice (σ in cell radii)",
    )
    cvt_lloyd_iterations: int = Field(
        default=8,
        ge=0,
        description="Number of Lloyd relaxation iterations for CVT mesh",
    )


# ---------------------------------------------------------------------------
# Voronoi network (spherical CVT)
# ---------------------------------------------------------------------------


class VoronoiCell(BaseModel):
    """A single cell in the spherical CVT Voronoi network."""

    id: int = Field(description="Unique cell identifier (0-based)")

    # Geographic coordinates (backward compatible)
    lon: float = Field(ge=-180, le=180, description="Centre longitude in degrees")
    lat: float = Field(ge=-90, le=90, description="Centre latitude in degrees")

    # 3D spherical coordinates (unit sphere)
    x: float = Field(default=0.0, description="Unit sphere x-coordinate")
    y: float = Field(default=0.0, description="Unit sphere y-coordinate (north)")
    z: float = Field(default=0.0, description="Unit sphere z-coordinate")

    # Geometric properties
    area_km2: float = Field(default=0.0, ge=0, description="Cell area in km²")

    # Elevation (absolute metres, no longer normalised)
    elevation: float = Field(
        default=0.0,
        description="Elevation in metres above planetary datum",
    )

    # Crust classification
    crust_type: str = Field(
        default="oceanic",
        description="Crust type: 'continental', 'oceanic', or 'transitional'",
    )

    # Distance to nearest plate boundary
    distance_to_boundary_km: float = Field(
        default=float("inf"),
        description="Distance to nearest plate boundary in km",
    )

    # Tectonic plate membership
    plate_id: str | None = Field(
        default=None,
        description="ID of the tectonic plate this cell belongs to",
    )

    # Tectonic boundary properties
    boundary_type: str | None = Field(
        default=None,
        description="Boundary type: 'convergent', 'divergent', 'transform', or None",
    )
    convergence_rate_cm_yr: float = Field(
        default=0.0,
        description="Convergence rate at boundary (cm/year, positive=convergent)",
    )

    # Climate properties (filled by climate simulator — TODO)
    temperature_C: float | None = Field(
        default=None,
        description="Mean annual temperature in °C",
    )
    precipitation_mm: float | None = Field(
        default=None,
        description="Annual precipitation in mm",
    )
    koppen_class: str | None = Field(
        default=None,
        description="Köppen climate classification code",
    )

    # Hydrology properties (filled by river generator — TODO)
    flow_accumulation: float = Field(
        default=0.0,
        description="Upstream drainage area (number of cells)",
    )
    river_id: str | None = Field(
        default=None,
        description="ID of the river this cell belongs to",
    )

    # Moisture (legacy, may be replaced by precipitation_mm)
    moisture: float = Field(
        default=0.0,
        ge=0,
        le=1,
        description="Normalised moisture value [0, 1]",
    )

    # Ecology
    biome: str | None = Field(
        default=None,
        description="Biome classification (filled by ecology engine)",
    )

    # Neighbours
    neighbors: list[int] = Field(
        default_factory=list,
        description="IDs of adjacent cells",
    )

    # Civilisation layer
    province_id: str | None = Field(
        default=None,
        description="ID of the province this cell belongs to",
    )


class VoronoiNetwork(BaseModel):
    """Complete Voronoi network for a planet map.

    Legacy model — prefer CVTMesh for the new spherical CVT pipeline.
    Retained for backward compatibility with existing data files.
    """

    seed: int = Field(description="RNG seed used for generation")
    num_cells: int = Field(gt=0, description="Number of cells in the network")
    relaxation_iterations: int = Field(
        default=3,
        ge=0,
        description="Number of Lloyd relaxation iterations applied",
    )
    cells: list[VoronoiCell] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Euler pole (rigid body rotation on sphere)
# ---------------------------------------------------------------------------


class EulerPole(BaseModel):
    """Euler pole describing rigid-body rotation of a tectonic plate.

    The rotation axis is a unit vector (x, y, z) and the angular velocity
    is ``omega_rad_yr`` radians per year.  The velocity of any point P on
    the plate is: v(P) = ω × P, where ω = (x, y, z) * omega_rad_yr.
    """

    x: float = Field(description="Rotation axis unit vector x-component")
    y: float = Field(description="Rotation axis unit vector y-component")
    z: float = Field(description="Rotation axis unit vector z-component")
    omega_rad_yr: float = Field(
        description="Angular velocity in radians per year",
    )


# ---------------------------------------------------------------------------
# Tectonic plates
# ---------------------------------------------------------------------------


class PlateType(str, Enum):
    """Classification of tectonic plates."""

    OCEANIC = "oceanic"
    CONTINENTAL = "continental"
    MIXED = "mixed"


class PlateVelocity(BaseModel):
    """Plate motion vector (legacy — prefer EulerPole).

    Retained for backward compatibility with existing data files.
    """

    dx: float = Field(default=0.0, description="Eastward component")
    dy: float = Field(default=0.0, description="Northward component")


class TectonicPlate(BaseModel):
    """A tectonic plate — a group of Voronoi cells."""

    id: str = Field(description="Unique plate identifier")
    name: str = Field(description="Display name")
    type: PlateType = Field(default=PlateType.MIXED)
    cell_ids: list[int] = Field(
        default_factory=list,
        description="IDs of Voronoi cells belonging to this plate",
    )
    euler_pole: EulerPole = Field(
        description="Euler pole describing plate rotation",
    )
    velocity: PlateVelocity | None = Field(
        default=None,
        description="Legacy plate motion vector (optional, for backward compat)",
    )
    growth_speed_multiplier: float = Field(
        default=1.0,
        gt=0,
        description="Speed multiplier for flood-fill plate growth",
    )


# ---------------------------------------------------------------------------
# CVT Mesh — top-level container for the spherical CVT pipeline output
# ---------------------------------------------------------------------------


class CVTMesh(BaseModel):
    """Spherical CVT mesh — primary data structure for the terrain pipeline.

    Contains all cell data, adjacency information, SphericalVoronoi vertices,
    and region-to-vertex mappings for polygon rendering.
    """

    seed: int = Field(description="RNG seed used for generation")
    num_cells: int = Field(gt=0, description="Number of cells in the mesh")
    jitter_sigma: float = Field(default=0.3, description="Jitter applied to initial lattice")
    lloyd_iterations: int = Field(default=8, description="Number of Lloyd relaxation iterations")

    cells: list[VoronoiCell] = Field(
        default_factory=list,
        description="All Voronoi cells",
    )
    adjacency: dict[str, list[int]] = Field(
        default_factory=dict,
        description="Cell adjacency graph (cell_id as string → neighbor IDs)",
    )

    # SphericalVoronoi vertex data for polygon rendering
    vertices: list[list[float]] = Field(
        default_factory=list,
        description="Voronoi vertices as [x, y, z] on unit sphere",
    )
    regions: list[list[int]] = Field(
        default_factory=list,
        description="Per-cell vertex indices (cell i → vertices[regions[i][j]])",
    )


# ---------------------------------------------------------------------------
# Linear / point features (rivers, ridges, volcanoes, …)
# ---------------------------------------------------------------------------


class FeatureType(str, Enum):
    """Classification of map features."""

    RIVER = "river"
    RIDGE = "ridge"
    COASTLINE = "coastline"
    VOLCANO = "volcano"
    MOUNTAIN_PEAK = "mountain_peak"
    LAKE = "lake"


class MapFeature(BaseModel):
    """A named linear or point feature on the map."""

    id: str = Field(description="Unique feature identifier")
    name: str = Field(default="", description="Display name")
    type: FeatureType
    coordinates: list[tuple[float, float]] = Field(
        default_factory=list,
        description="(lon, lat) pairs forming a polyline or a single point",
    )


# ---------------------------------------------------------------------------
# Map layer types
# ---------------------------------------------------------------------------


class MapLayerType(str, Enum):
    """Raster and vector map layer identifiers."""

    # Raster layers
    ELEVATION = "elevation"  # editable
    MOISTURE = "moisture"  # editable
    TERRAIN = "terrain"  # engine-derived
    TEMPERATURE = "temperature"  # engine-derived
    PRECIPITATION = "precipitation"  # engine-derived
    BIOMES = "biomes"  # engine-derived
    PLATES_RASTER = "plates_raster"  # engine-derived (plate IDs as raster)
    BOUNDARIES = "boundaries"  # engine-derived

    # Vector layers
    PLATES = "plates"  # editable
    PROVINCES = "provinces"  # editable (civilisation layer)
    FEATURES = "features"  # editable / derived
    CVT_MESH = "cvt_mesh"  # engine-derived (full CVT mesh JSON)


# ---------------------------------------------------------------------------
# Layer registry — unified tracking of all map layers per planet
# ---------------------------------------------------------------------------


class RasterLayerMeta(BaseModel):
    """Metadata for a raster map layer (PNG/TIFF heightmap-like)."""

    layer_type: MapLayerType = Field(description="Which layer this represents")
    source: Literal["editable", "engine-derived", "imported"] = Field(
        description="How this layer was created"
    )
    file_path: str = Field(
        description="Relative path from maps/<planet_id>/ (e.g. 'input/elevation.png')"
    )
    resolution: tuple[int, int] = Field(
        description="(width, height) in pixels"
    )
    depends_on: list[str] = Field(
        default_factory=list,
        description="Layer type names this layer depends on",
    )
    stale: bool = Field(
        default=False,
        description="True if an upstream layer changed and this needs recomputation",
    )


class VectorLayerMeta(BaseModel):
    """Metadata for a vector map layer (JSON/GeoJSON)."""

    layer_id: str = Field(description="Identifier for this vector layer")
    format: Literal["geojson", "voronoi-json", "plates-json", "cvt-json"] = Field(
        description="File format"
    )
    file_path: str = Field(
        description="Relative path from maps/<planet_id>/"
    )
    depends_on: list[str] = Field(
        default_factory=list,
        description="Layer type names this layer depends on",
    )
    stale: bool = Field(
        default=False,
        description="True if an upstream layer changed and this needs recomputation",
    )


class MapLayerRegistry(BaseModel):
    """Registry of all map layers for a planet.

    Stored as ``registry.yaml`` alongside the map data.  Tracks layer sources,
    dependencies, and staleness so that re-importing an elevation heightmap can
    cascade updates to all downstream layers.

    Dependency DAG::

        cvt_mesh (engine: CVT generation)
            ├── plates (engine: plate generator)
            │   ├── boundaries (engine: boundary detector)
            │   │   └── elevation (engine: terrain synthesiser)
            │   │       ├── temperature (engine: climate simulator — TODO)
            │   │       │   └── biomes (engine: ecology engine — TODO)
            │   │       └── flow_accumulation (engine: river generator — TODO)
            │   └── provinces (engine: voronoi → GeoJSON)
            │       └── civ_territory (manual: civmap painting)
            └── features (engine: feature_extractor)
    """

    planet_id: str = Field(description="Planet this registry belongs to")
    raster_layers: dict[str, RasterLayerMeta] = Field(
        default_factory=dict,
        description="Raster layers keyed by MapLayerType value",
    )
    vector_layers: dict[str, VectorLayerMeta] = Field(
        default_factory=dict,
        description="Vector layers keyed by layer_id",
    )

    def mark_downstream_stale(self, changed_layer: str) -> list[str]:
        """Mark all layers that depend on *changed_layer* as stale.

        Performs a transitive closure: if A depends on B and B depends on
        the changed layer, both A and B are marked stale.

        Returns:
            List of layer names that were marked stale.
        """
        # Build reverse dependency map
        all_layers: dict[str, list[str]] = {}
        for name, meta in self.raster_layers.items():
            all_layers[name] = meta.depends_on
        for name, meta in self.vector_layers.items():
            all_layers[name] = meta.depends_on

        # BFS to find all transitively affected layers
        affected: list[str] = []
        queue = [changed_layer]
        visited: set[str] = set()

        while queue:
            current = queue.pop(0)
            for name, deps in all_layers.items():
                if current in deps and name not in visited:
                    visited.add(name)
                    affected.append(name)
                    queue.append(name)

        # Apply stale flags
        for name in affected:
            if name in self.raster_layers:
                self.raster_layers[name].stale = True
            if name in self.vector_layers:
                self.vector_layers[name].stale = True

        return affected
