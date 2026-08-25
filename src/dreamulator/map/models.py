"""Map data models — metadata, Voronoi cells, tectonic plates, map layers."""

from __future__ import annotations

import math
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    import numpy as np

# ---------------------------------------------------------------------------
# JSON safety
# ---------------------------------------------------------------------------


def sanitize_nonfinite(value: Any) -> Any:
    """Recursively replace non-finite floats (NaN / ±Inf) with None.

    JSON has no representation for NaN/Infinity; Python's :mod:`json` emits them
    as the non-standard literals ``NaN``/``Infinity``, which a browser's
    ``JSON.parse`` rejects — silently breaking every client that reads the file.
    The concrete trigger: a mesh with no plate boundaries (e.g. an imported
    real-Earth elevation) gets ``distance_to_boundary_km = inf`` for *every*
    cell, which made ``cvt_mesh.json`` unparseable in the browser and took down
    the whole map view (Köppen / coastlines / highlights all depend on it).
    Sanitising at the serialization boundary guarantees strict-JSON output.
    """
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: sanitize_nonfinite(v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_nonfinite(v) for v in value]
    return value


# ---------------------------------------------------------------------------
# Projection & metadata
# ---------------------------------------------------------------------------


class MapProjection(StrEnum):
    """Supported map projections."""

    EQUIRECTANGULAR = "equirectangular"


class ElevationImportProvenance(BaseModel):
    """Provenance of an externally imported elevation heightmap.

    Recorded in map.yaml by the import-elevation endpoint so an imported
    (authored / real-world) raster is distinguishable from pipeline-generated
    terrain — imported maps carry no plate/tectonic data.
    """

    source_format: str = Field(description="png-16bit / tiff-uint16 / tiff-float32")
    source_filename: str = ""
    source_resolution: list[int] = Field(default_factory=list)
    output_resolution: list[int] = Field(default_factory=list)
    was_resampled: bool = False
    range_normalized: list[float] = Field(default_factory=list)
    notes: str | None = None
    imported_at: datetime = Field(default_factory=datetime.now)


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
    #: Set when the elevation raster was imported from an external tool
    #: (absent for pipeline-generated terrain).
    elevation_import: ElevationImportProvenance | None = None


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

    # Distance to nearest plate boundary. Optional because meshes without any
    # plate boundary (e.g. imported real-Earth elevations) have no finite value;
    # such cells serialise as null (JSON has no Infinity — see sanitize_nonfinite).
    distance_to_boundary_km: float | None = Field(
        default=float("inf"),
        description="Distance to nearest plate boundary in km (None if no boundary)",
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
    temperature_hottest_month_C: float | None = Field(
        default=None,
        description="Hottest-month mean temperature (°C)",
    )
    temperature_coldest_month_C: float | None = Field(
        default=None,
        description="Coldest-month mean temperature (°C)",
    )
    distance_to_coast_km: float | None = Field(
        default=None,
        description="Shortest graph-path distance to nearest ocean cell (km; 0 for ocean)",
    )

    # Ocean current properties (filled by climate simulator — stage 2.5)
    ocean_current_east_m_s: float | None = Field(
        default=None,
        description="Surface ocean current east component (m/s)",
    )
    ocean_current_north_m_s: float | None = Field(
        default=None,
        description="Surface ocean current north component (m/s)",
    )
    sst_anomaly_c: float | None = Field(
        default=None,
        description="SST anomaly from ocean heat transport (°C, rel. latitude profile)",
    )

    # Wind properties (filled by climate simulator — Stage 2)
    wind_east_m_s: float | None = Field(
        default=None,
        description="Surface wind east component (m/s, positive=eastward)",
    )
    wind_north_m_s: float | None = Field(
        default=None,
        description="Surface wind north component (m/s, positive=northward)",
    )

    # Ecology properties (filled by ecology engine — P0)
    biome: str | None = Field(
        default=None,
        description="Whittaker biome classification (e.g. 'tropical_rainforest')",
    )
    npp_gc_m2_yr: float | None = Field(
        default=None,
        description="Net Primary Productivity in gC / m² / yr (Miami model)",
    )
    domesticable_tags: list[str] = Field(
        default_factory=list,
        description="Domestication potential tags (e.g. ['large_herbivores_high', ...])",
    )

    # Ecology properties (filled by ecology engine — P1a)
    soil_type: str | None = Field(
        default=None,
        description="USDA soil order (e.g. 'mollisol')",
    )
    soil_fertility: str | None = Field(
        default=None,
        description="Soil fertility grade: 'high' | 'medium' | 'low'",
    )
    biogeographic_province: str | None = Field(
        default=None,
        description="Biogeographic province id (e.g. '3.7' = realm.province)",
    )

    # Hydrology properties (filled by river generator — map/hydrology.py)
    flow_direction: int | None = Field(
        default=None,
        description="Downstream neighbour cell id; -1 = sink (endorheic); None = ocean",
    )
    flow_accumulation: float = Field(
        default=0.0,
        description="Upstream catchment area in km² (0 for ocean cells)",
    )
    river_id: str | None = Field(
        default=None,
        description="ID of the river this cell belongs to",
    )
    river_order: int = Field(
        default=0,
        description="Accumulation-threshold stream order (0 = no channel)",
    )
    is_lake: bool = Field(
        default=False,
        description=(
            "True for a closed below-sea-level depression (endorheic lake), "
            "distinct from the global ocean"
        ),
    )

    # Erosion properties (filled by erosion loop — map/erosion.py)
    net_erosion_m: float = Field(
        default=0.0,
        description="Net elevation change from fluvial erosion + deposition "
        "(m; negative = eroded, positive = deposition)",
    )
    hotspot_id: str | None = Field(
        default=None,
        description=(
            "Hotspot chain ID (e.g. 'hs_0') if this cell is part of a volcanic hotspot chain"
        ),
    )
    landform: str | None = Field(
        default=None,
        description="Interior landform type: 'orogeny', 'rift', or None",
    )

    # Moisture (legacy, may be replaced by precipitation_mm)
    moisture: float = Field(
        default=0.0,
        ge=0,
        le=1,
        description="Normalised moisture value [0, 1]",
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

    # Habitability / agriculture (filled by civilization engine)
    # Two independent derived layers, distinguished by the settle-vs-farm line:
    #   - habitable_coast: annual T>0°C AND P>500mm AND coastal → settleable
    #     (includes cool-wet oceanic ET — Faroese/Inuit-type: liveable, not farmable).
    #   - agricultural_core: hottest-month T>10°C (Köppen C/D tree-line) → trees/crops.
    habitable_coast: bool | None = Field(
        default=None,
        description="宜居海岸: annual mean T>0°C, P>500mm, and within coast threshold",
    )
    agricultural_core: bool | None = Field(
        default=None,
        description="农业核心区: hottest-month mean T>10°C (Köppen C/D tree-line)",
    )
    # Graded counterparts (0–100) of the two booleans — drive the frontend's
    # progressive colour ramps (better discrimination on warm-wet worlds where
    # the hard thresholds are nearly everywhere satisfied).
    habitability_score: float | None = Field(
        default=None,
        description="宜居等级 (0–100): graded settleability from T/P/coast factors",
    )
    agriculture_score: float | None = Field(
        default=None,
        description="农业等级 (0–100): graded farm suitability, hard zero below tree-line",
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


class PlateType(StrEnum):
    """Classification of tectonic plates."""

    OCEANIC = "oceanic"
    CONTINENTAL = "continental"
    MIXED = "mixed"


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

    model_config = {"arbitrary_types_allowed": True}

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

    # ---- lazily cached coordinate arrays (set via property) ----
    _xyz: np.ndarray | None = None
    _lon: np.ndarray | None = None
    _lat: np.ndarray | None = None

    @property
    def cell_xyz(self) -> np.ndarray:
        """(n, 3) array of cell positions on the unit sphere, computed once."""
        if self._xyz is None:
            import numpy as np

            self._xyz = np.array([[c.x, c.y, c.z] for c in self.cells], dtype=np.float64)
        return self._xyz

    @property
    def cell_lon(self) -> np.ndarray:
        """(n,) array of cell longitudes (radians), computed once."""
        if self._lon is None:
            import numpy as np

            self._lon = np.array([c.lon for c in self.cells], dtype=np.float64)
        return self._lon

    @property
    def cell_lat(self) -> np.ndarray:
        """(n,) array of cell latitudes (radians), computed once."""
        if self._lat is None:
            import numpy as np

            self._lat = np.array([c.lat for c in self.cells], dtype=np.float64)
        return self._lat


# ---------------------------------------------------------------------------
# Linear / point features (rivers, ridges, volcanoes, …)
# ---------------------------------------------------------------------------


class FeatureType(StrEnum):
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
    order: int = Field(
        default=0,
        description="Stream order / width class (rivers, see hydrology "
        "RIVER_ORDER_THRESHOLDS); 0 = not applicable",
    )


# ---------------------------------------------------------------------------
# Map layer types
# ---------------------------------------------------------------------------


class MapLayerType(StrEnum):
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
    resolution: tuple[int, int] = Field(description="(width, height) in pixels")
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
    file_path: str = Field(description="Relative path from maps/<planet_id>/")
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
            │   │       ├── temperature (engine: climate simulator)
            │   │       │   └── biomes (engine: ecology engine)
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
        for name, raster_meta in self.raster_layers.items():
            all_layers[name] = raster_meta.depends_on
        for name, vector_meta in self.vector_layers.items():
            all_layers[name] = vector_meta.depends_on

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
