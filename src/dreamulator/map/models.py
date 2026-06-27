"""Map data models — metadata, Voronoi cells, tectonic plates, map layers."""

from __future__ import annotations

from enum import Enum

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
