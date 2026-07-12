/**
 * CivMap types — TypeScript interfaces for the civilization map system.
 *
 * Mirrors Pydantic models in src/dreamulator/civmap/models.py.
 */

export interface CivCountry {
  id: string
  name: string
  color: string
  description: string
}

export interface CivSnapshot {
  id: string
  year: number | null
  description: string
}

export interface TerritoryAssignment {
  province_id: string
  country_id: string
}

export interface CivTerritory {
  countries: CivCountry[]
  snapshots: CivSnapshot[]
  active_snapshot: string | null
  assignments: Record<string, TerritoryAssignment[]>
}

/** GeoJSON Feature from Natural Earth / geoBoundaries */
export interface GeoBoundaryFeature {
  type: 'Feature'
  id?: string
  properties: Record<string, unknown>
  geometry: {
    type: string
    coordinates: number[][][] | number[][][][]
  }
}

export interface GeoBoundaryCollection {
  type: 'FeatureCollection'
  features: GeoBoundaryFeature[]
}

/** Admin boundary level */
export type BoundaryLevel = 'adm0' | 'adm1' | 'adm2'

/** Paint tool mode */
export type PaintToolMode = 'select' | 'paint' | 'erase'

/** Country ISO_A2 → list of ADM1 province IDs */
export type CountryProvinceMapping = Record<string, string[]>

/** Province/country info for the inspector panel */
export interface ProvinceInfo {
  id: string
  name: string
  admin: string
  type: string
  country_id: string | null
  country_name: string | null
  country_color: string | null
  /** For ADM0: total provinces in this country */
  province_count?: number
  /** For ADM0: number of painted provinces */
  painted_count?: number
}
