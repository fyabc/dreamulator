/**
 * Elevation import contract on the client side.
 *
 * The backend owns decoding and the grey-to-metre mapping (`ElevationMapping`
 * in `src/dreamulator/map/models.py`).  The browser only collects the
 * declaration, sends it, and shows what the backend reports: the preview and
 * the import use the same functions, so the mapping shown after an import is
 * the `mapping` the server returned, never a value recomputed here.
 */

export type ElevationMappingMode = 'range' | 'threshold' | 'metres'

/** Mirror of the backend `ElevationMapping` model (all fields present in responses). */
export interface ElevationMapping {
  mode: ElevationMappingMode
  /** range: metres at grey value 0 (black). */
  min_m: number
  /** range/threshold: metres at full scale (white). */
  max_m: number
  /** threshold: grey fraction (0–1) at or below which a pixel is sea. */
  sea_level: number
  /** range/metres: land lies above this height in metres. */
  sea_level_m: number
  curve: 'linear' | 'gamma'
  gamma: number
  /** threshold: depth in metres given to every sea pixel (an assumption). */
  seafloor_m: number
}

/** Fields of the mapping that each mode actually reads. */
export const MODE_FIELDS: Record<ElevationMappingMode, (keyof ElevationMapping)[]> = {
  range: ['min_m', 'max_m', 'sea_level_m'],
  threshold: ['sea_level', 'max_m', 'curve', 'gamma', 'seafloor_m'],
  metres: ['sea_level_m'],
}

/** The summary shared by the preview and the import responses. */
export interface ElevationImportSummary {
  source_format: string
  source_resolution: [number, number]
  output_resolution: [number, number]
  was_resampled: boolean
  mapping: ElevationMapping
  range_m: [number, number]
  /** Share of equirectangular pixels that are land (not a share of the planet). */
  land_fraction: number
  /** Share of the sphere's surface that is land, rows weighted by their area. */
  land_area_fraction: number
  seafloor_assumed: boolean
  level_step_m: { coast: number; max: number } | null
  warnings: string[]
}

export interface ElevationPreviewResponse extends ElevationImportSummary {
  ok: true
  resolution_from: 'map' | 'source'
  mapping_source: 'request' | 'map' | 'contract'
  preview: { width: number; height: number; metres_f32: string; land_u8: string }
}

export interface ElevationImportResponse extends ElevationImportSummary {
  ok: true
  stored_scale_m: [number, number]
  stale_layers: string[]
}

/** Router state handed to the map page after a successful import journey. */
export interface ImportedState {
  imported: { world: string; created: boolean; result: ElevationImportResponse }
}

export interface ElevationPreviewGrid {
  width: number
  height: number
  metres: Float32Array
  land: Uint8Array
}

export interface ElevationImportTarget {
  world: string
  planetId: string
  branch?: string | null
}

function base64Bytes(b64: string): Uint8Array {
  const bin = atob(b64)
  const out = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i)
  return out
}

/** Decode the preview grid: little-endian float32 metres and a uint8 land mask, row-major. */
export function decodePreviewGrid(preview: ElevationPreviewResponse['preview']): ElevationPreviewGrid {
  const { width, height } = preview
  const n = width * height
  const raw = base64Bytes(preview.metres_f32)
  const view = new DataView(raw.buffer, raw.byteOffset, raw.byteLength)
  const metres = new Float32Array(n)
  for (let i = 0; i < n; i++) metres[i] = view.getFloat32(i * 4, true)
  const land = base64Bytes(preview.land_u8)
  if (raw.byteLength !== n * 4 || land.length !== n) {
    throw new Error(`preview grid size mismatch: ${width}x${height}`)
  }
  return { width, height, metres, land }
}

/**
 * Form fields for a mapping: the mode plus only the fields that mode reads.
 * A null mapping sends nothing, so the backend picks its default (the map's
 * own scale, or the contract defaults) and reports it back.
 */
export function mappingFormFields(mapping: ElevationMapping | null): Record<string, string> {
  if (!mapping) return {}
  const out: Record<string, string> = { mode: mapping.mode }
  for (const key of MODE_FIELDS[mapping.mode]) out[key] = String(mapping[key])
  return out
}

/** Colour scale endpoints used by the legend: the deepest sea and the highest land. */
export function previewScale(grid: ElevationPreviewGrid): {
  seaMin: number
  seaMax: number
  landMin: number
  landMax: number
} {
  let seaMin = Infinity
  let seaMax = -Infinity
  let landMin = Infinity
  let landMax = -Infinity
  for (let i = 0; i < grid.metres.length; i++) {
    const m = grid.metres[i]
    if (grid.land[i]) {
      if (m < landMin) landMin = m
      if (m > landMax) landMax = m
    } else {
      if (m < seaMin) seaMin = m
      if (m > seaMax) seaMax = m
    }
  }
  return { seaMin, seaMax, landMin, landMax }
}

/** Latitude and longitude of a pixel centre on a global equirectangular grid. */
export function pixelLatLon(x: number, y: number, width: number, height: number): [number, number] {
  return [90 - ((y + 0.5) * 180) / height, ((x + 0.5) * 360) / width - 180]
}

/** A world directory name the backend can create safely. */
export const WORLD_NAME_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/

/** Suggest a world name from an uploaded file name, avoiding names already taken. */
export function suggestWorldName(fileName: string, taken: readonly string[] = []): string {
  const stem = fileName.replace(/\.[^.]*$/, '')
  const slug = stem
    .replace(/[^A-Za-z0-9_-]+/g, '-')
    .replace(/^[-_]+|[-_]+$/g, '')
    .slice(0, 48)
  const base = slug && WORLD_NAME_PATTERN.test(slug) ? slug : 'my-world'
  let name = base
  for (let i = 2; taken.includes(name); i++) name = `${base}-${i}`
  return name
}
