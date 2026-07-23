/**
 * TypeScript types for the map subsystem.
 * Mirrors the Python models in src/dreamulator/map/models.py.
 */

import type { ProjectionType } from './utils/projection'

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
  sea_level_m: number
  voronoi_seed: number | null
  voronoi_num_cells: number
}

// Re-export ProjectionType for convenience
export type { ProjectionType }

// ---------------------------------------------------------------------------
// Voronoi network
// ---------------------------------------------------------------------------

export interface VoronoiCell {
  id: number
  lon: number
  lat: number
  /** Elevation in metres above planetary datum. */
  elevation: number
  moisture: number
  neighbors: number[]
  plate_id: string | null
  biome: string | null
  province_id: string | null

  // Extended fields from CVT mesh (backend VoronoiCell model)
  x?: number
  y?: number
  z?: number
  area_km2?: number
  crust_type?: string
  distance_to_boundary_km?: number
  boundary_type?: string | null
  convergence_rate_cm_yr?: number
  temperature_C?: number | null
  precipitation_mm?: number | null
  koppen_class?: string | null
  flow_accumulation?: number
  river_id?: string | null
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
  | 'moisture'
  | 'terrain'
  | 'temperature'
  | 'precipitation'
  | 'biomes'
  | 'plates'
  | 'provinces'

// ---------------------------------------------------------------------------
// Color modes (for terrain rendering + overlay coloring)
// ---------------------------------------------------------------------------

/**
 * Color modes available in the map viewer.
 * - 'terrain': adaptive hypsometric tint (natural appearance)
 * - 'landsea': binary land/sea
 * - 'plates': color cells by plate_id (categorical colors)
 * - 'boundaries': show boundary_type (convergent=red, divergent=green, transform=yellow)
 */
export type ViewerColorMode = 'terrain' | 'landsea' | 'plates' | 'boundaries'

// ---------------------------------------------------------------------------
// Layer visibility state
// ---------------------------------------------------------------------------

export interface LayerConfig {
  id: MapLayerType | 'landsea' | 'voronoi'
  label: string
  visible: boolean
  opacity: number
}

// ---------------------------------------------------------------------------
// CVT mesh (centroidal Voronoi tessellation, from Python backend)
// ---------------------------------------------------------------------------

/** Boundary type between two adjacent plates. */
export type BoundaryType = 'convergent' | 'divergent' | 'transform'

/** A vertex in the CVT mesh (Voronoi polygon corner).
 *  Transformed by adaptCvtMesh() from raw [x,y,z] arrays. */
export interface CVTVertex {
  id: number
  lon: number
  lat: number
}

/** A Voronoi region (polygon) in the CVT mesh.
 *  Transformed by adaptCvtMesh() from raw vertex-index arrays. */
export interface CVTRegion {
  id: number
  vertex_ids: number[]
  plate_id: string | null
  boundaries: Record<string, BoundaryType> | null
}

/** Complete CVT mesh output from the backend. */
export interface CVTMesh {
  seed: number
  num_cells: number
  jitter_sigma?: number
  lloyd_iterations?: number
  cells: VoronoiCell[]
  adjacency: Record<string, number[]>
  vertices: CVTVertex[]
  regions: CVTRegion[]
}
