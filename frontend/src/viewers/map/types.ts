/**
 * TypeScript types for the map subsystem.
 * Mirrors the Python models in src/dreamulator/map/models.py.
 */

// ---------------------------------------------------------------------------
// Metadata
// ---------------------------------------------------------------------------

export type MapProjection = 'equirectangular'

export interface MapMetadata {
  planet_id: string
  projection: MapProjection
  width: number
  height: number
  elevation_min_m: number
  elevation_max_m: number
  sea_level: number
  voronoi_seed: number | null
  voronoi_num_cells: number
}

// ---------------------------------------------------------------------------
// Voronoi network
// ---------------------------------------------------------------------------

export interface VoronoiCell {
  id: number
  lon: number
  lat: number
  elevation: number
  moisture: number
  neighbors: number[]
  plate_id: string | null
  biome: string | null
  province_id: string | null
}

export interface VoronoiNetwork {
  seed: number
  num_cells: number
  relaxation_iterations: number
  cells: VoronoiCell[]
}

// ---------------------------------------------------------------------------
// Tectonic plates
// ---------------------------------------------------------------------------

export type PlateType = 'oceanic' | 'continental' | 'mixed'

export interface PlateVelocity {
  dx: number
  dy: number
}

export interface TectonicPlate {
  id: string
  name: string
  type: PlateType
  cell_ids: number[]
  velocity: PlateVelocity
}

// ---------------------------------------------------------------------------
// Features
// ---------------------------------------------------------------------------

export type FeatureType =
  | 'river'
  | 'ridge'
  | 'coastline'
  | 'volcano'
  | 'mountain_peak'
  | 'lake'

export interface MapFeature {
  id: string
  name: string
  type: FeatureType
  coordinates: [number, number][] // [lon, lat] pairs
}

// ---------------------------------------------------------------------------
// Layer types
// ---------------------------------------------------------------------------

export type MapLayerType =
  | 'elevation'
  | 'moisture'
  | 'terrain'
  | 'temperature'
  | 'precipitation'
  | 'biomes'
  | 'plates'
  | 'provinces'
  | 'features'

// ---------------------------------------------------------------------------
// Layer visibility state
// ---------------------------------------------------------------------------

export interface LayerConfig {
  id: MapLayerType | 'landsea' | 'slope' | 'voronoi'
  label: string
  visible: boolean
  opacity: number
}

// ---------------------------------------------------------------------------
// Edit tools
// ---------------------------------------------------------------------------

export type EditTool = 'raise' | 'lower' | 'smooth' | 'flatten' | 'select'

export interface BrushConfig {
  tool: EditTool
  radius: number // pixels
  strength: number // 0..1
  hardness: number // 0..1
}

// ---------------------------------------------------------------------------
// Generate params
// ---------------------------------------------------------------------------

export interface GenerateParams {
  seed?: number
  num_continents?: number
  mountaininess?: number
  num_plates?: number
  width?: number
  height?: number
  voronoi_num_cells?: number
}
