/**
 * Region-pack data shapes — the `/api/packs` contract (see
 * `src/dreamulator/api_routes/packs.py`).  Only the fields the viewer
 * consumes are typed; both meta documents keep an index signature because
 * the export pipeline keeps adding diagnostic keys.
 */

export interface PackLegs {
  color: boolean
  refined: boolean
  carto: boolean
  renders: boolean
  prog: boolean
  gaea: boolean
}

export interface PackSummary {
  name: string
  world: string | null
  planet: string | null
  branch: string | null
  center_lat: number
  center_lon: number
  span_km: number
  mtime: string
  legs: PackLegs
}

export interface PackInputMeta {
  center_lat: number
  center_lon: number
  span_km: number
  radius_km?: number
  grid: { w: number; h: number }
  extent_km: { x: number; y: number }
  km_per_px?: { x: number; y: number }
  climate?: {
    biome?: { legend?: Record<string, string> }
    koppen?: { legend?: Record<string, string> }
  }
  [key: string]: unknown
}

export interface PackRefinedMeta {
  regime?: { encoding?: string }
  [key: string]: unknown
}

export interface PackMeta {
  input: PackInputMeta
  refined: PackRefinedMeta | null
}

export interface ProbeResult {
  row: number
  col: number
  res: { w: number; h: number }
  height_source: 'refined' | 'input' | null
  height_m: number | null
  biome_code: number | null
  koppen_code: number | null
  river: boolean | null
  lake: boolean | null
  sea_water: boolean | null
  river_flow_accum: number | null
  river_regime: number | null
  offset_km: { x: number; y: number }
}

/** A displayable raster layer over the pack window. */
export interface LayerOption {
  id: string
  /** Pack-relative image path, e.g. "refined-out/rivers.png". */
  path: string
  kind: 'base' | 'overlay'
}

/**
 * Vector river segments from /rivers.json: each segment is
 * ``[[y, x], [y, x]]`` in centre-origin km (the map frame), with the
 * relative upstream accumulation driving the √-law stroke width and the
 * 0/1 perennial/non-perennial regime driving the dash.
 */
export interface RiverData {
  segs: number[][][]
  flows: number[]
  regimes: number[]
  flowMax: number
}
