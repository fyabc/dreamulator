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
  source?: { canvas?: string }
  climate?: {
    biome?: { legend?: Record<string, string>; missing?: number }
    koppen?: { legend?: Record<string, string>; missing?: number }
  }
  [key: string]: unknown
}

export interface PackRefinedMeta {
  regime?: { encoding?: string }
  td_revision?: string | null
  [key: string]: unknown
}

export interface PackMeta {
  input: PackInputMeta
  refined: PackRefinedMeta | null
  height_source?: PackHeightSource | null
  condition_layers?: { source: string[]; grid: string[] }
}

export type PackHeightSource = 'input' | 'refined-out' | 'gaea-out'

export interface ProbeResult {
  row: number
  col: number
  res: { w: number; h: number }
  height_source: 'refined' | 'input' | null
  height_m: number | null
  input_height_m?: number
  biome_code: number | null
  koppen_code: number | null
  river: boolean | null
  lake: boolean | null
  sea_water: boolean | null
  river_flow_accum: number | null
  river_regime: number | null
  offset_km: { x: number; y: number }
}

export type RegionRefinementMode = 'redraw' | 'blend' | 'hydrology'

export type RegionRefinementSource = ({ kind: 'pack'; pack: string } | {
  kind: 'world'; world: string; planet: string; branch: string | null; lat: number; lon: number; span_km: number
  input_px?: number
}) & { mode?: RegionRefinementMode; native_resolution_km?: number; preserve_wavelength_km?: number; river_threshold?: number }

export interface RegionRefinementPlan {
  span_km: number
  input_px: number
  output_px: number
  native_scale_km: number | null
  mode: RegionRefinementMode
  native_resolution_km: number | null
  preserve_wavelength_km: number | null
  river_threshold: number | null
}

export interface RegionDevice {
  kind: 'gpu' | 'cpu' | 'unavailable'
  name: string | null
  reason?: string | null
}

export interface RegionRefinementJob {
  id: string
  plan: RegionRefinementPlan
  state: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'
  stage: 'preparing' | 'terrain' | 'hydrology' | 'publishing'
  elapsed_seconds: number
  result_pack: string | null
  error: string | null
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
