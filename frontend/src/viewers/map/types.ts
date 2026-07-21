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
  sea_level: number
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
// Color modes (for terrain rendering + overlay coloring)
// ---------------------------------------------------------------------------

/**
 * Color modes available in the map viewer.
 * - 'terrain': hypsometric tint (natural appearance)
 * - 'elevation': grayscale gradient
 * - 'landsea': binary land/sea
 * - 'slope': slope gradient
 * - 'plates': color cells by plate_id (random categorical colors)
 * - 'boundaries': show boundary_type (convergent=red, divergent=green, transform=yellow)
 */
export type ViewerColorMode = 'terrain' | 'elevation' | 'landsea' | 'slope' | 'plates' | 'boundaries'

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
// CVT mesh (centroidal Voronoi tessellation, from Python backend)
// ---------------------------------------------------------------------------

/** Boundary type between two adjacent plates. */
export type BoundaryType = 'convergent' | 'divergent' | 'transform'

/** A vertex in the CVT mesh (Voronoi polygon corner). */
export interface CVTVertex {
  /** Vertex index. */
  id: number
  /** Longitude in degrees. */
  lon: number
  /** Latitude in degrees. */
  lat: number
}

/** A Voronoi region (polygon) in the CVT mesh. */
export interface CVTRegion {
  /** Cell ID (matches VoronoiCell.id). */
  id: number
  /** Ordered vertex indices defining the polygon boundary. */
  vertex_ids: number[]
  /** Plate ID this cell belongs to. */
  plate_id: string | null
  /** Boundary types for edges shared with neighboring cells.
   *  Keyed by neighbor cell ID. */
  boundaries: Record<string, BoundaryType> | null
}

/** Complete CVT mesh output from the backend. */
export interface CVTMesh {
  vertices: CVTVertex[]
  regions: CVTRegion[]
}
