"""Map manager — CRUD operations for planet map data with branch inheritance.

Integrates with the LayerResolver to support branch inheritance: a branch
that forks at the geological layer inherits (or overrides) map data from
the root world.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import yaml  # type: ignore[import-untyped]

from dreamulator.resolver import LayerResolver

from .elevation_codec import decode_elevation, encode_elevation
from .models import (
    MapFeature,
    MapLayerRegistry,
    MapLayerType,
    MapMetadata,
    RasterLayerMeta,
    TectonicPlate,
    VectorLayerMeta,
    VoronoiNetwork,
)


class MapManager:
    """Manages map data for all planets in a world.

    Args:
        world_dir: Path to the world root directory.
        branch: Branch name (None for root world).
    """

    def __init__(self, world_dir: Path, branch: str | None = None) -> None:
        self.world_dir = world_dir
        self.branch = branch
        self._resolver = LayerResolver(world_dir, branch)

    # -------------------------------------------------------------------
    # Path resolution
    # -------------------------------------------------------------------

    def _map_input_dir(self, planet_id: str) -> Path | None:
        """Resolve the effective input directory for a planet's map data.

        Checks derived directory first (CVT pipeline output), then input.
        """
        # Check derived directory first (new CVT pipeline output)
        derived_dir = self._resolver.get_derived_dir("geological")
        if derived_dir is not None:
            maps_dir = derived_dir / "maps" / planet_id
            if maps_dir.exists() and any(maps_dir.iterdir()):
                return maps_dir
        # Fall back to input directory
        input_dir = self._resolver.get_input_dir("geological")
        if input_dir is None:
            return None
        maps_dir = input_dir / "maps" / planet_id
        if maps_dir.exists() and any(maps_dir.iterdir()):
            return maps_dir
        return None

    def _map_derived_dir(self, planet_id: str, layer: str = "geological") -> Path | None:
        """Resolve the effective derived directory for a planet's map data."""
        derived_dir = self._resolver.get_derived_dir(layer)
        if derived_dir is None:
            return None
        maps_dir = derived_dir / "maps" / planet_id
        if maps_dir.exists():
            return maps_dir
        return None

    def _ensure_input_dir(self, planet_id: str) -> Path:
        """Create and return the input directory for a planet's map data."""
        # Always write to the branch's own input directory (not inherited)
        if self.branch is not None:
            base = self.world_dir / "branches" / self.branch / "layers"
        else:
            base = self.world_dir / "layers"
        maps_dir = base / "geological" / "input" / "maps" / planet_id
        maps_dir.mkdir(parents=True, exist_ok=True)
        return maps_dir

    def _ensure_derived_dir(self, planet_id: str, layer: str = "geological") -> Path:
        """Create and return the derived directory for a planet's map data."""
        if self.branch is not None:
            base = self.world_dir / "branches" / self.branch / "layers"
        else:
            base = self.world_dir / "layers"
        maps_dir = base / layer / "derived" / "maps" / planet_id
        maps_dir.mkdir(parents=True, exist_ok=True)
        return maps_dir

    # -------------------------------------------------------------------
    # Metadata
    # -------------------------------------------------------------------

    def get_map_metadata(self, planet_id: str) -> MapMetadata | None:
        """Load map metadata for a planet."""
        map_dir = self._map_input_dir(planet_id)
        if map_dir is None:
            return None
        yaml_path = map_dir / "map.yaml"
        if not yaml_path.exists():
            return None
        with yaml_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if data is None:
            return None
        return MapMetadata.model_validate(data)

    def save_map_metadata(self, planet_id: str, metadata: MapMetadata) -> None:
        """Save map metadata for a planet."""
        map_dir = self._ensure_input_dir(planet_id)
        yaml_path = map_dir / "map.yaml"
        with yaml_path.open("w", encoding="utf-8") as f:
            yaml.dump(
                metadata.model_dump(mode="json"),
                f,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
            )

    # -------------------------------------------------------------------
    # Elevation (raster)
    # -------------------------------------------------------------------

    def get_elevation(self, planet_id: str) -> np.ndarray | None:
        """Load the elevation heightmap for a planet.

        Returns:
            Normalised 2-D numpy array [0, 1], or None if not found.
        """
        map_dir = self._map_input_dir(planet_id)
        if map_dir is None:
            return None
        png_path = map_dir / "elevation.png"
        if not png_path.exists():
            return None
        with png_path.open("rb") as f:
            return decode_elevation(f.read())

    def save_elevation(self, planet_id: str, elevation: np.ndarray) -> None:
        """Save the elevation heightmap for a planet.

        Uses the current map metadata for min/max elevation.
        If no metadata exists, defaults are used.
        """
        metadata = self.get_map_metadata(planet_id)
        min_m = metadata.elevation_min_m if metadata else -11_000.0
        max_m = metadata.elevation_max_m if metadata else 9_000.0

        map_dir = self._ensure_input_dir(planet_id)
        png_path = map_dir / "elevation.png"
        with png_path.open("wb") as f:
            f.write(encode_elevation(elevation, min_m, max_m))

    # -------------------------------------------------------------------
    # Voronoi network
    # -------------------------------------------------------------------

    def get_voronoi(self, planet_id: str) -> VoronoiNetwork | None:
        """Load the Voronoi network for a planet.

        Supports both legacy voronoi.json and new CVT mesh format.
        """
        map_dir = self._map_input_dir(planet_id)
        if map_dir is None:
            return None

        # Try legacy voronoi.json first
        json_path = map_dir / "voronoi.json"
        if json_path.exists():
            with json_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if data is not None:
                return VoronoiNetwork.model_validate(data)

        # Fall back to CVT mesh format — convert to VoronoiNetwork
        cvt_path = map_dir / "cvt_mesh.json"
        if cvt_path.exists():
            with cvt_path.open("r", encoding="utf-8") as f:
                cvt_data = json.load(f)
            if cvt_data is not None:
                return self._cvt_mesh_to_voronoi_network(cvt_data)

        return None

    @staticmethod
    def _cvt_mesh_to_voronoi_network(cvt_data: dict) -> VoronoiNetwork:
        """Convert CVT mesh JSON to legacy VoronoiNetwork format."""
        from .models import VoronoiCell

        cells = []
        for c in cvt_data.get("cells", []):
            cell = VoronoiCell(
                id=c["id"],
                lon=c.get("lon", 0.0),
                lat=c.get("lat", 0.0),
                x=c.get("x", 0.0),
                y=c.get("y", 0.0),
                z=c.get("z", 0.0),
                elevation=c.get("elevation", 0.0),
                crust_type=c.get("crust_type", "oceanic"),
                plate_id=c.get("plate_id"),
                boundary_type=c.get("boundary_type"),
                convergence_rate_cm_yr=c.get("convergence_rate_cm_yr", 0.0),
                distance_to_boundary_km=c.get("distance_to_boundary_km", float("inf")),
                biome=c.get("biome"),
                neighbors=c.get("neighbors", []),
            )
            cells.append(cell)

        return VoronoiNetwork(
            seed=cvt_data.get("seed", 0),
            num_cells=cvt_data.get("num_cells", len(cells)),
            relaxation_iterations=cvt_data.get("lloyd_iterations", 0),
            cells=cells,
        )

    def save_voronoi(self, planet_id: str, network: VoronoiNetwork) -> None:
        """Save the Voronoi network for a planet."""
        map_dir = self._ensure_input_dir(planet_id)
        json_path = map_dir / "voronoi.json"
        with json_path.open("w", encoding="utf-8") as f:
            json.dump(
                network.model_dump(mode="json"),
                f,
                ensure_ascii=False,
            )

    # -------------------------------------------------------------------
    # Tectonic plates
    # -------------------------------------------------------------------

    def get_plates(self, planet_id: str) -> list[TectonicPlate]:
        """Load tectonic plate definitions for a planet."""
        map_dir = self._map_input_dir(planet_id)
        if map_dir is None:
            return []
        json_path = map_dir / "plates.json"
        if not json_path.exists():
            return []
        with json_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if data is None:
            return []
        # Support both formats: plain list and {"plates": [...]}
        if isinstance(data, list):
            plates_data = data
        elif isinstance(data, dict):
            plates_data = data.get("plates", [])
        else:
            return []
        return [TectonicPlate.model_validate(p) for p in plates_data]

    def save_plates(self, planet_id: str, plates: list[TectonicPlate]) -> None:
        """Save tectonic plate definitions for a planet."""
        map_dir = self._ensure_input_dir(planet_id)
        json_path = map_dir / "plates.json"
        data = {"plates": [p.model_dump(mode="json") for p in plates]}
        with json_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

    # -------------------------------------------------------------------
    # Features (rivers, ridges, coastlines, …)
    # -------------------------------------------------------------------

    def get_features(self, planet_id: str) -> list[MapFeature]:
        """Load map features for a planet."""
        map_dir = self._map_input_dir(planet_id)
        if map_dir is None:
            return []
        json_path = map_dir / "features.json"
        if not json_path.exists():
            return []
        with json_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if data is None or not isinstance(data, dict):
            return []
        features_data = data.get("features", [])
        return [MapFeature.model_validate(feat) for feat in features_data]

    def save_features(self, planet_id: str, features: list[MapFeature]) -> None:
        """Save map features for a planet."""
        map_dir = self._ensure_input_dir(planet_id)
        json_path = map_dir / "features.json"
        data = {"features": [f.model_dump(mode="json") for f in features]}
        with json_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

    # -------------------------------------------------------------------
    # Derived layer images
    # -------------------------------------------------------------------

    def get_layer_image(
        self, planet_id: str, layer_type: MapLayerType, layer: str = "geological"
    ) -> bytes | None:
        """Load a derived raster layer as PNG bytes.

        Args:
            planet_id: Planet identifier.
            layer_type: Which layer to load (e.g. TERRAIN, BIOMES).
            layer: Which engine layer to look in (geological, climate, ecology).

        Returns:
            PNG bytes, or None if not found.
        """
        derived_dir = self._map_derived_dir(planet_id, layer)
        if derived_dir is None:
            return None
        png_path = derived_dir / f"{layer_type.value}.png"
        if not png_path.exists():
            return None
        with png_path.open("rb") as f:
            return f.read()

    # -------------------------------------------------------------------
    # Listing & queries
    # -------------------------------------------------------------------

    def list_planets_with_maps(self) -> list[str]:
        """List planet IDs that have map data.

        Searches both derived (CVT pipeline output) and input directories.
        """
        planets: set[str] = set()

        # Check derived directory first (CVT pipeline output)
        derived_dir = self._resolver.get_derived_dir("geological")
        if derived_dir is not None:
            maps_dir = derived_dir / "maps"
            if maps_dir.exists():
                for d in maps_dir.iterdir():
                    if d.is_dir() and (d / "elevation.png").exists():
                        planets.add(d.name)

        # Also check input directory
        input_dir = self._resolver.get_input_dir("geological")
        if input_dir is not None:
            maps_dir = input_dir / "maps"
            if maps_dir.exists():
                for d in maps_dir.iterdir():
                    if d.is_dir() and (d / "elevation.png").exists():
                        planets.add(d.name)

        return sorted(planets)

    def has_map(self, planet_id: str) -> bool:
        """Check if a planet has map data."""
        return self._map_input_dir(planet_id) is not None

    # -------------------------------------------------------------------
    # Sync operations
    # -------------------------------------------------------------------

    def sync_voronoi_from_elevation(self, planet_id: str) -> None:
        """Re-sample Voronoi cell elevations from the current heightmap.

        Call this after the heightmap is edited to keep the Voronoi network
        in sync.
        """
        from .voronoi_generator import sample_heightmap

        elevation = self.get_elevation(planet_id)
        network = self.get_voronoi(planet_id)
        if elevation is None or network is None:
            return

        metadata = self.get_map_metadata(planet_id)
        min_m = metadata.elevation_min_m if metadata else -11_000.0
        max_m = metadata.elevation_max_m if metadata else 9_000.0

        updated = sample_heightmap(network, elevation, min_m, max_m)
        self.save_voronoi(planet_id, updated)

    # -------------------------------------------------------------------
    # Layer registry
    # -------------------------------------------------------------------

    def get_registry(self, planet_id: str) -> MapLayerRegistry | None:
        """Load the layer registry for a planet.

        If no registry file exists, returns ``None`` (callers may create one
        via :meth:`build_registry`).
        """
        map_dir = self._map_input_dir(planet_id)
        if map_dir is None:
            return None
        yaml_path = map_dir / "registry.yaml"
        if not yaml_path.exists():
            return None
        with yaml_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if data is None:
            return None
        return MapLayerRegistry.model_validate(data)

    def save_registry(self, planet_id: str, registry: MapLayerRegistry) -> None:
        """Save the layer registry for a planet."""
        map_dir = self._ensure_input_dir(planet_id)
        yaml_path = map_dir / "registry.yaml"
        with yaml_path.open("w", encoding="utf-8") as f:
            yaml.dump(
                registry.model_dump(mode="json"),
                f,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
            )

    def build_registry(self, planet_id: str) -> MapLayerRegistry:
        """Build a fresh layer registry by scanning existing map data.

        This creates or rebuilds the registry from the actual files on disk.
        """
        meta = self.get_map_metadata(planet_id)
        resolution = (meta.width, meta.height) if meta else (2048, 1024)

        registry = MapLayerRegistry(planet_id=planet_id)

        # Elevation raster
        map_dir = self._map_input_dir(planet_id)
        if map_dir and (map_dir / "elevation.png").exists():
            registry.raster_layers[MapLayerType.ELEVATION.value] = RasterLayerMeta(
                layer_type=MapLayerType.ELEVATION,
                source="imported",
                file_path="input/elevation.png",
                resolution=resolution,
            )

        # Voronoi network
        if map_dir and (map_dir / "voronoi.json").exists():
            registry.vector_layers["voronoi"] = VectorLayerMeta(
                layer_id="voronoi",
                format="voronoi-json",
                file_path="input/voronoi.json",
                depends_on=[MapLayerType.ELEVATION.value],
            )

        # Tectonic plates
        if map_dir and (map_dir / "plates.json").exists():
            registry.vector_layers["plates"] = VectorLayerMeta(
                layer_id="plates",
                format="plates-json",
                file_path="input/plates.json",
                depends_on=["voronoi"],
            )

        # Features
        if map_dir and (map_dir / "features.json").exists():
            registry.vector_layers["features"] = VectorLayerMeta(
                layer_id="features",
                format="voronoi-json",
                file_path="input/features.json",
                depends_on=[MapLayerType.ELEVATION.value],
            )

        self.save_registry(planet_id, registry)
        return registry

    def update_registry_on_elevation_change(self, planet_id: str) -> MapLayerRegistry:
        """Update the registry after the elevation heightmap changes.

        Marks all downstream layers as stale and updates the elevation entry.
        """
        registry = self.get_registry(planet_id)
        if registry is None:
            registry = self.build_registry(planet_id)

        meta = self.get_map_metadata(planet_id)
        resolution = (meta.width, meta.height) if meta else (2048, 1024)

        # Update elevation entry
        registry.raster_layers[MapLayerType.ELEVATION.value] = RasterLayerMeta(
            layer_type=MapLayerType.ELEVATION,
            source="imported",
            file_path="input/elevation.png",
            resolution=resolution,
        )

        # Mark downstream layers as stale
        registry.mark_downstream_stale(MapLayerType.ELEVATION.value)

        self.save_registry(planet_id, registry)
        return registry

    # -------------------------------------------------------------------
    # Full generation
    # -------------------------------------------------------------------

    def generate_map(
        self,
        planet_id: str,
        *,
        seed: int | None = None,
        num_continents: int = 3,
        mountaininess: float = 0.5,
        num_plates: int = 10,
        width: int = 2048,
        height: int = 1024,
        voronoi_num_cells: int = 5000,
    ) -> MapMetadata:
        """Generate a complete map (raster + Voronoi + plates) for a planet.

        Args:
            planet_id: Planet identifier.
            seed: RNG seed (uses world seed if None).
            num_continents: Approximate number of continents.
            mountaininess: Terrain roughness parameter.
            num_plates: Number of tectonic plates.
            width: Raster width.
            height: Raster height.
            voronoi_num_cells: Number of Voronoi cells.

        Returns:
            The generated MapMetadata.
        """
        from .terrain_generator import TerrainParams, generate_terrain
        from .voronoi_generator import assign_cells_to_plates, generate_voronoi, sample_heightmap

        # Resolve seed
        if seed is None:
            from dreamulator.io.loader import load_world

            config = load_world(self.world_dir)
            seed = config.seed.seed

        # 1. Generate terrain raster
        params = TerrainParams(
            num_continents=num_continents,
            mountaininess=mountaininess,
        )
        terrain = generate_terrain(width, height, seed, params)

        # 2. Generate Voronoi network
        network = generate_voronoi(width, height, seed, voronoi_num_cells)
        network = sample_heightmap(network, terrain)

        # 3. Assign plates
        rng = np.random.default_rng(seed)
        plates = assign_cells_to_plates(network, num_plates, sea_level=0.4, rng=rng)

        # 4. Create metadata
        metadata = MapMetadata(
            planet_id=planet_id,
            width=width,
            height=height,
            voronoi_seed=seed,
            voronoi_num_cells=voronoi_num_cells,
            sea_level=0.4,
        )

        # 5. Save everything
        self.save_map_metadata(planet_id, metadata)
        self.save_elevation(planet_id, terrain)
        self.save_voronoi(planet_id, network)
        self.save_plates(planet_id, plates)

        return metadata
