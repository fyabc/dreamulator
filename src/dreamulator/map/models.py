"""Map data models — metadata, Voronoi cells, tectonic plates, map layers."""

from __future__ import annotations

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
    width: int = Field(default=2048, gt=0, description="Raster width in pixels")
    height: int = Field(default=1024, gt=0, description="Raster height in pixels")
    elevation_min_m: float = Field(
        default=-11_000.0,
        description="Minimum elevation in metres (e.g. Mariana Trench)",
    )
    elevation_max_m: float = Field(
        default=9_000.0,
        description="Maximum elevation in metres (e.g. Everest)",
    )
    sea_level: float = Field(
        default=0.0,
        description="Sea level as a normalised value in [0, 1] "
        "(fraction of the elevation range)",
    )
    voronoi_seed: int | None = Field(
        default=None,
        description="RNG seed for Voronoi network generation (None = use world seed)",
    )
    voronoi_num_cells: int = Field(
        default=5000,
        gt=0,
        description="Target number of Voronoi cells",
    )


# ---------------------------------------------------------------------------
# Voronoi network
# ---------------------------------------------------------------------------


class VoronoiCell(BaseModel):
    """A single cell in the Voronoi network."""

    id: int = Field(description="Unique cell identifier (0-based)")
    lon: float = Field(ge=-180, le=180, description="Centre longitude in degrees")
    lat: float = Field(ge=-90, le=90, description="Centre latitude in degrees")
    elevation: float = Field(
        default=0.0,
        ge=0,
        le=1,
        description="Normalised elevation sampled from the raster heightmap [0, 1]",
    )
    moisture: float = Field(
        default=0.0,
        ge=0,
        le=1,
        description="Normalised moisture value [0, 1]",
    )
    neighbors: list[int] = Field(
        default_factory=list,
        description="IDs of adjacent cells",
    )
    plate_id: str | None = Field(
        default=None,
        description="ID of the tectonic plate this cell belongs to",
    )
    biome: str | None = Field(
        default=None,
        description="Biome classification (filled by ecology engine)",
    )
    province_id: str | None = Field(
        default=None,
        description="ID of the province this cell belongs to (civilisation layer)",
    )


class VoronoiNetwork(BaseModel):
    """Complete Voronoi network for a planet map."""

    seed: int = Field(description="RNG seed used for generation")
    num_cells: int = Field(gt=0, description="Number of cells in the network")
    relaxation_iterations: int = Field(
        default=3,
        ge=0,
        description="Number of Lloyd relaxation iterations applied",
    )
    cells: list[VoronoiCell] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Tectonic plates
# ---------------------------------------------------------------------------


class PlateType(str, Enum):
    """Classification of tectonic plates."""

    OCEANIC = "oceanic"
    CONTINENTAL = "continental"
    MIXED = "mixed"


class PlateVelocity(BaseModel):
    """Plate motion vector (degrees per Myr, arbitrary scale for now)."""

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
    velocity: PlateVelocity = Field(
        default_factory=PlateVelocity,
        description="Plate motion vector",
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

    # Vector layers
    PLATES = "plates"  # editable
    PROVINCES = "provinces"  # editable (civilisation layer)
    FEATURES = "features"  # editable / derived


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
    format: Literal["geojson", "voronoi-json", "plates-json"] = Field(
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

        elevation (editable/imported)
            ├── plates (engine: assign_cells_to_plates)
            │   └── provinces (engine: voronoi → GeoJSON)
            │       └── civ_territory (manual: civmap painting)
            ├── features (engine: feature_extractor)
            ├── temperature (engine: climate engine)
            │   └── biomes (engine: ecology engine)
            └── moisture (engine: climate engine)
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
