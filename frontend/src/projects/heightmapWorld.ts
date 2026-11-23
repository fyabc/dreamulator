import { GRID_H, GRID_W, MODEL_JANUARY_INDEX, EARTH_PARAMS, isTemperatureParams, type PlanetParams } from '../playground/temperatureDraft'
import type { KernelResult } from '../playground/temperature.worker'
import { elevationPng, isJpegBytes, jpegToGrayscalePng, readElevationPng, type ElevationRaster } from '../viewers/packs/elevationRaster'
import { hasProjectHeightmap, maxSourceBytes, type LocalProject } from './elevationProject'
import type { SavedClimateTrial } from '../api/climateTrials'
import type { MappingDiagnostic } from '../api/elevationImport'
import type { MapResultMetadata } from '../api/resultContract'
import type { BrowserEbmSource } from '../playground/browserEbm'
import { isCreationWorldId, jsonBlob as json, readCreationSnapshot, sha256, writeCreationSnapshot,
  type CreationSnapshot } from './creationSnapshot'
import { worldLayers } from './worldLayers'

export const heightmapCreationPath = 'browser-creation.json'
export const defaultHeightmapCells = 18_432
const experimentDir = 'layers/climate/derived/browser-temperature'
const geologicalInput = 'layers/geological/input'
export const heightmapPlanet = 'planet_terra'
const star = 'star_primary'

export type HeightmapInput = {
  original: Blob
  filename: string
  sha256: string
  raster: ElevationRaster & { depth: 8 | 16 }
  /** Set when the picked file was a JPEG and the retained original is its PNG conversion. */
  converted?: 'jpeg'
}
export type SavedTemperature = {
  fingerprint: string
  version: string
  annual: number[]
  monthly: number[][]
}
/**
 * How the creation flow turns grey levels into metres (the same contract as the
 * server's `ElevationMapping`, limited to the two modes the browser can read).
 */
export type HeightmapMapping =
  | { mode: 'range'; min_m: number; max_m: number; sea_level_m: number }
  | { mode: 'threshold'; sea_level: number; max_m: number; seafloor_m: number
      curve: 'linear' | 'gamma'; gamma: number }
export type HeightmapWorld = {
  id: string
  title: string
  created: string
  seed: number
  meshCells: number
  params: PlanetParams
  mapping: HeightmapMapping
  heightmap: HeightmapInput
  /** Derived metres raster for threshold worlds; absent for range worlds. */
  elevation?: Blob
  temperature?: SavedTemperature
}
export const heightmapMapPath = (id: string) => `/worlds/${encodeURIComponent(id)}/map/${heightmapPlanet}`

export function latestHeightmapClimate(project: LocalProject): SavedClimateTrial | undefined {
  let latest: SavedClimateTrial | undefined
  for (const { metadata } of project.climateTrials ?? []) {
    if (metadata.planet !== heightmapPlanet || metadata.branch !== null || !metadata.surface.browser_heightmap) continue
    if (!latest || Date.parse(metadata.saved_at) > Date.parse(latest.saved_at)) latest = metadata
  }
  return latest
}

export function canDefaultToHeightmapClimate(planet: string | undefined, search: URLSearchParams) {
  return (!planet || planet === heightmapPlanet) && !search.get('branch') && !search.has('draft')
    && !search.has('climateResult') && search.get('trial') !== 'climate' && search.get('creation') !== '1'
}

export function defaultHeightmapClimateSearch(project: LocalProject, search: URLSearchParams) {
  if (project.published || !hasProjectHeightmap(project)) return null
  const latest = latestHeightmapClimate(project)
  if (!latest) return null
  const next = new URLSearchParams(search)
  next.set('climateResult', latest.id)
  return next
}

export function heightmapMapMetadata(world: HeightmapWorld): MapResultMetadata {
  const { heightmap: { raster } } = world
  const resolution = [raster.width, raster.height]
  const scale = heightmapDisplayScale(world.heightmap, world.mapping)
  return { planet_id: heightmapPlanet, projection: 'equirectangular', width: raster.width, height: raster.height,
    elevation_min_m: scale.minM, elevation_max_m: scale.maxM, sea_level_m: scale.seaLevelM,
    voronoi_seed: null, voronoi_num_cells: 0, elevation_import: { source_resolution: resolution,
      output_resolution: resolution, was_resampled: false }, format_version: '3',
    time: { reference_year_days: 365.25, reference_month_days: 365.25 / 12 }, browser_heightmap: true }
}

export function heightmapEbmSource({ params, heightmap, mapping, seed, meshCells }: HeightmapWorld): BrowserEbmSource {
  const forcing = { axial_tilt_deg: params.tiltDeg, rotation_period_days: params.rotationDays,
    albedo: params.albedo, greenhouse_warming_k: params.greenhouseK }
  return { cells: meshCells, forcing, mesh: { image: heightmap.original, name: heightmap.filename, sha256: heightmap.sha256, mapping },
    config: { seed, num_nodes: meshCells, elevation_source: 'imported', stellar_luminosity_sol: params.luminosity,
      orbital_distance_au: params.distanceAu, orbital_period_days: params.yearDays, variable_lapse_rate: params.variableLapse,
      axial_tilt_deg: params.tiltDeg, rotation_period_days: params.rotationDays, albedo: params.albedo,
      greenhouse_warming_K: params.greenhouseK } }
}

export async function readHeightmapInput(blob: Blob, name: string): Promise<HeightmapInput> {
  if (!blob.size || blob.size > maxSourceBytes) throw new Error('Unsupported heightmap file size')
  const filename = name.trim().slice(0, 200)
  if (!filename) throw new Error('Heightmap name is missing')
  const source = await normalizeHeightmapSource(blob, filename)
  const raster = await readElevationPng(source.blob, 0, 65535, true)
  if (raster.width !== 2 * raster.height || raster.width > 8192) throw new Error('Expected a 2:1 global heightmap')
  return { original: source.blob, filename: source.filename, sha256: await sha256(source.blob), raster,
    ...(source.convertedFromJpeg ? { converted: 'jpeg' as const } : {}) }
}

/**
 * The browser heightmap pipeline consumes grayscale PNG bytes everywhere (archive,
 * rebuild, climate worker), so a JPEG from a chat app is decoded and re-encoded as an
 * 8-bit grayscale PNG.  The retained original is that PNG: it keeps every sample the
 * JPEG carried, and the provenance records that the source was a JPEG.
 */
async function normalizeHeightmapSource(blob: Blob, filename: string) {
  if (!isJpegBytes(new Uint8Array(await blob.slice(0, 3).arrayBuffer()))) {
    return { blob, filename, convertedFromJpeg: false }
  }
  const png = await jpegToGrayscalePng(blob)
  return { blob: png, filename: filename.replace(/\.jpe?g$/i, '.png'), convertedFromJpeg: true }
}

/** The range mapping described by the elevation fields of the planet parameters. */
export function rangeMapping(params: Pick<PlanetParams, 'elevMinM' | 'elevMaxM' | 'seaLevelM'>): HeightmapMapping {
  return { mode: 'range', min_m: params.elevMinM, max_m: params.elevMaxM, sea_level_m: params.seaLevelM }
}

const finiteNumber = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value)

export function isHeightmapMapping(value: unknown): value is HeightmapMapping {
  const m = value as Record<string, unknown> | null
  if (!m || typeof m !== 'object') return false
  if (m.mode === 'range') {
    return finiteNumber(m.min_m) && finiteNumber(m.max_m) && finiteNumber(m.sea_level_m) && m.min_m < m.max_m
  }
  if (m.mode === 'threshold') {
    return finiteNumber(m.sea_level) && m.sea_level >= 0 && m.sea_level < 1 && finiteNumber(m.max_m) &&
      m.max_m > 0 && finiteNumber(m.seafloor_m) && m.seafloor_m < 0 &&
      (m.curve === 'linear' || m.curve === 'gamma') && finiteNumber(m.gamma) && m.gamma > 0
  }
  return false
}

/** Read a stored mapping; snapshots written before the field existed are range mappings. */
export function readHeightmapMapping(value: unknown, params: Pick<PlanetParams, 'elevMinM' | 'elevMaxM' | 'seaLevelM'>): HeightmapMapping {
  if (value === undefined || value === null) return rangeMapping(params)
  if (!isHeightmapMapping(value)) throw new Error('Invalid heightmap mapping')
  return value
}

/** The threshold curve's fraction: 0 at the sea threshold, 1 at full scale. */
function thresholdFraction(value: number, mapping: Extract<HeightmapMapping, { mode: 'threshold' }>) {
  const u = Math.min(1, Math.max(0, (value - mapping.sea_level) / (1 - mapping.sea_level)))
  return mapping.curve === 'gamma' ? u ** mapping.gamma : u
}

/** Exact metres range and land share over the full source raster (not a preview sample). */
export function heightmapStats(input: HeightmapInput, mapping: HeightmapMapping) {
  const { values } = input.raster
  if (!values.length) return null
  const span = mapping.mode === 'range' ? mapping.max_m - mapping.min_m : 0
  let min = Infinity
  let max = -Infinity
  let land = 0
  for (const raw of values) {
    const value = raw / 65535
    let metres: number
    let isLand: boolean
    if (mapping.mode === 'range') {
      metres = mapping.min_m + value * span
      isLand = metres > mapping.sea_level_m
    } else {
      isLand = value > mapping.sea_level
      metres = isLand ? mapping.max_m * thresholdFraction(value, mapping) : mapping.seafloor_m
    }
    if (metres < min) min = metres
    if (metres > max) max = metres
    if (isLand) land++
  }
  return { minM: min, maxM: max, landShare: land / values.length }
}

/** Smallest and largest source grey values as fractions of full scale. */
function rasterExtremes(input: HeightmapInput) {
  let low = Infinity
  let high = -Infinity
  for (const value of input.raster.values) {
    if (value < low) low = value
    if (value > high) high = value
  }
  return { low: low / 65535, high: high / 65535 }
}

/**
 * Display scale for the map raster: the metres range `map.yaml` records and the
 * shader's linear decoding uses.  Range worlds use the declared scale.  Threshold
 * worlds use the actual extent of their metres raster (sea floor to the highest
 * land pixel the image reaches); a flat tone expands by 1 m on each side so the
 * range stays valid.
 */
export function heightmapDisplayScale(input: HeightmapInput, mapping: HeightmapMapping) {
  if (mapping.mode === 'range') {
    return { minM: mapping.min_m, maxM: mapping.max_m, seaLevelM: mapping.sea_level_m }
  }
  const { low, high } = rasterExtremes(input)
  let minM = low <= mapping.sea_level ? mapping.seafloor_m : mapping.max_m * thresholdFraction(low, mapping)
  let maxM = high > mapping.sea_level ? mapping.max_m * thresholdFraction(high, mapping) : mapping.max_m
  if (!(minM < maxM)) {
    minM -= 1
    maxM += 1
  }
  return { minM, maxM, seaLevelM: 0 }
}

export function isHeightmapParams(params: unknown): params is PlanetParams {
  return isTemperatureParams(params) && params.luminosity > 0 && Number.isFinite(params.elevMaxM - params.elevMinM)
}

function canonicalParams(params: PlanetParams) {
  return Object.fromEntries((Object.keys(EARTH_PARAMS) as (keyof PlanetParams)[]).map(key => [key, params[key]])) as PlanetParams
}

/**
 * Fingerprint of everything a temperature result depends on.  Range mappings are
 * already covered by the planet parameters; a threshold mapping is folded in only
 * in that mode, so temperatures saved before threshold worlds existed still match.
 */
export function temperatureInputFingerprint(input: HeightmapInput, params: PlanetParams, mapping?: HeightmapMapping) {
  const threshold = mapping && mapping.mode !== 'range' ? { mapping } : {}
  return sha256(json({ source: input.sha256, projection: 'equirectangular', registration: 'pixel_center_north_up',
    sampler: 'containing-pixel-v1', grid: [GRID_W, GRID_H], params: canonicalParams(params), ...threshold }))
}

export function heightmapGrid(input: HeightmapInput, mapping: HeightmapMapping, width = GRID_W, height = GRID_H) {
  const source = input.raster
  const elevations = new Float64Array(width * height)
  const land = new Uint8Array(elevations.length)
  const span = mapping.mode === 'range' ? mapping.max_m - mapping.min_m : 0
  for (let row = 0; row < height; row++) {
    const sourceRow = Math.floor((row + 0.5) / height * source.height) * source.width
    for (let column = 0; column < width; column++) {
      const raw = source.values[sourceRow + Math.floor((column + 0.5) / width * source.width)] / 65535
      const index = row * width + column
      if (mapping.mode === 'range') {
        const value = mapping.min_m + raw * span
        elevations[index] = value
        land[index] = Number(value > mapping.sea_level_m)
      } else {
        const isLand = raw > mapping.sea_level
        elevations[index] = isLand ? mapping.max_m * thresholdFraction(raw, mapping) : mapping.seafloor_m
        land[index] = Number(isLand)
      }
    }
  }
  return { width, height, values: elevations, land }
}

/**
 * Mapping advice for the browser creation flow, mirroring the backend's
 * `_mapping_diagnostics`: the codes and numbers are the same, so both import
 * journeys render one wording.  Every entry is computed from the raster and the
 * parameters; suggestions only name values the author can type into the form.
 */
export function heightmapDiagnostics(input: HeightmapInput, mapping: HeightmapMapping): MappingDiagnostic[] {
  const { values, depth } = input.raster
  if (!values.length) return []
  let low = Infinity
  let high = -Infinity
  for (const value of values) {
    if (value < low) low = value
    if (value > high) high = value
  }
  const levels = depth === 8 ? 255 : 65535
  const tolerance = 65535 / levels
  let darkest = 0
  for (const value of values) if (value <= low + tolerance) darkest++
  const share = darkest / values.length
  const lowFraction = low / 65535
  const highFraction = high / 65535

  if (mapping.mode === 'threshold') {
    if (highFraction <= mapping.sea_level) {
      return [{ code: 'threshold_all_sea', brightest: highFraction, thresh: mapping.sea_level, levels }]
    }
    if (lowFraction > mapping.sea_level) {
      return [{ code: 'threshold_all_land', darkest: lowFraction, thresh: mapping.sea_level, levels }]
    }
    const reach = thresholdFraction(highFraction, mapping)
    if (!(reach > 0 && reach < 0.9)) return []
    return [{ code: 'threshold_reach', reach_m: mapping.max_m * reach, reach_share: reach,
      max_m: mapping.max_m, suggested_white_m: mapping.max_m / reach }]
  }

  const span = mapping.max_m - mapping.min_m
  if (!(span > 0)) return []
  const bottom = mapping.min_m + lowFraction * span
  const top = mapping.min_m + highFraction * span
  const suggested = high > 0 ? mapping.min_m + span / highFraction : undefined
  const darkestLevel: MappingDiagnostic = { code: 'range_darkest_share', share,
    level: Math.round(low / 65535 * levels), levels }
  const addSuggestion = (entry: MappingDiagnostic) => {
    if (suggested !== undefined) entry.suggested_white_m = suggested
    return entry
  }
  if (top <= mapping.sea_level_m) {
    return [addSuggestion({ code: 'range_all_sea', brightest: highFraction, top_m: top,
      sea_m: mapping.sea_level_m, min_m: mapping.min_m, max_m: mapping.max_m }),
    ...(high > low && share >= 0.5 ? [darkestLevel] : [])]
  }
  if (bottom > mapping.sea_level_m) {
    return [{ code: 'range_all_land', darkest: lowFraction, bottom_m: bottom, sea_m: mapping.sea_level_m,
      min_m: mapping.min_m, max_m: mapping.max_m }]
  }
  return [
    ...(highFraction - lowFraction < 0.9
      ? [addSuggestion({ code: 'range_grey_use', low: lowFraction, high: highFraction, top_m: top,
        max_m: mapping.max_m })]
      : []),
    ...(high > low && share >= 0.5 ? [darkestLevel] : []),
  ]
}

/**
 * The threshold to prefill when switching to threshold mode: the darkest grey level,
 * so by default only that tone (for most images, pure black) is sea.
 */
export function thresholdSeaLevel(input: HeightmapInput): number {
  const { depth, values } = input.raster
  let low = Infinity
  for (const value of values) if (value < low) low = value
  const levels = depth === 8 ? 255 : 65535
  return Math.round(low / 65535 * levels) / levels
}

function validGrid(values: unknown): values is number[] {
  return Array.isArray(values) && values.length === GRID_W * GRID_H && values.every(Number.isFinite)
}

export function savedTemperature(result: KernelResult, fingerprint: string, version: string): SavedTemperature {
  return { fingerprint, version, annual: result.annual,
    monthly: [...result.monthly.slice(MODEL_JANUARY_INDEX), ...result.monthly.slice(0, MODEL_JANUARY_INDEX)] }
}

function readTemperature(value: unknown): SavedTemperature {
  const data = value as Partial<SavedTemperature> | null
  if (!data || typeof data.fingerprint !== 'string' || !/^[a-f0-9]{64}$/.test(data.fingerprint) ||
    typeof data.version !== 'string' || !/^[\w.+-]{1,100}$/.test(data.version) || !validGrid(data.annual) ||
    !Array.isArray(data.monthly) || data.monthly.length !== 12 || !data.monthly.every(validGrid)) {
    throw new Error('Invalid saved temperature experiment')
  }
  return { fingerprint: data.fingerprint, version: data.version, annual: data.annual, monthly: data.monthly }
}

function validateCreation({ id, title, created, seed, meshCells, params, mapping }: HeightmapWorld) {
  if (typeof id !== 'string' || !isCreationWorldId(id) || typeof title !== 'string' || !title.trim() || title.length > 120 ||
    typeof created !== 'string' || !Number.isFinite(Date.parse(created)) ||
    !Number.isSafeInteger(seed) || seed < 0 || seed > 0x7fffffff ||
    !Number.isSafeInteger(meshCells) || meshCells < 100 || meshCells > 200_000 || !isHeightmapParams(params) ||
    !isHeightmapMapping(mapping)) {
    throw new Error('Invalid heightmap world settings')
  }
}

/**
 * The metres raster a threshold world carries for the map: the original grey values
 * mapped through the threshold contract, encoded against the world's display scale.
 * Range worlds keep their original image, which the linear scale already decodes.
 */
async function thresholdElevationPng(input: HeightmapInput, mapping: Extract<HeightmapMapping, { mode: 'threshold' }>) {
  const { width, height } = input.raster
  const source = input.raster.values
  const metres = new Float32Array(width * height)
  for (let index = 0; index < metres.length; index++) {
    const value = source[index] / 65535
    metres[index] = value > mapping.sea_level ? mapping.max_m * thresholdFraction(value, mapping) : mapping.seafloor_m
  }
  const { minM, maxM } = heightmapDisplayScale(input, mapping)
  return elevationPng({ width, height, values: metres }, {
    source: input.filename, projection: 'equirectangular', registration: 'pixel_center_north_up',
    encoding: 'linear_uint16', min_m: minM, max_m: maxM,
  }, { min: minM, max: maxM })
}

async function worldFiles(world: HeightmapWorld) {
  validateCreation(world)
  const { id, title, created, seed, meshCells, heightmap, mapping, temperature } = world
  const params = canonicalParams(world.params)
  if (temperature && (readTemperature(temperature).fingerprint !== await temperatureInputFingerprint(heightmap, params, mapping))) {
    throw new Error('Temperature result does not match the current world inputs')
  }
  const scale = heightmapDisplayScale(heightmap, mapping)
  const files = new Map<string, Blob>()
  const put = (path: string, value: unknown) => files.set(path, json(value))
  const dimensions = [heightmap.raster.width, heightmap.raster.height]
  put('world.yaml', {
    metadata: { name: id, description: title, created, modified: created, dreamulator_version: __APP_VERSION__, tags: ['browser-heightmap'] },
    seed: { seed }, planet_ids: [heightmapPlanet],
    layers: Object.fromEntries(worldLayers
      .map(layer => [layer, { engine: layer, configured: ['astronomy', 'geological'].includes(layer) }])),
  })
  put('layers/astronomy/input/stellar.yaml', {
    name: title,
    stars: [{ id: star, name: 'Primary', spectral_class: 'G2', luminosity_class: 'V', luminosity: params.luminosity }],
    orbits: [{ body_id: heightmapPlanet, parent_id: star, semi_major_axis_au: params.distanceAu, eccentricity: 0 }],
  })
  put(`${geologicalInput}/planets.yaml`, { planets: [{
    id: heightmapPlanet, name: title, orbits: star, planet_type: 'terrestrial', mass: 1, radius: 1,
    rotation_period_days: params.rotationDays, axial_tilt_deg: params.tiltDeg, albedo: params.albedo,
    atmosphere: { surface_pressure_atm: 1, composition: { N2: 0.78, O2: 0.21, Ar: 0.01 }, greenhouse_factor: params.greenhouseK },
  }] })
  put(`${geologicalInput}/terrain_config.yaml`, { num_nodes: meshCells })
  put(`${geologicalInput}/elevation_imports.yaml`, { [heightmapPlanet]: { sha256: heightmap.sha256, provenance: {
    source_format: `png-${heightmap.raster.depth}bit`, source_filename: heightmap.filename, source_resolution: dimensions,
    output_resolution: dimensions, mapping, imported_at: created,
    ...(heightmap.converted ? { notes: 'source JPEG converted to an 8-bit grayscale PNG on import' } : {}),
  } } })
  files.set(`${geologicalInput}/elevation_sources/${heightmap.sha256}.bin`, heightmap.original)
  put(`maps/${heightmapPlanet}/map.yaml`, { planet_id: heightmapPlanet, projection: 'equirectangular',
    width: dimensions[0], height: dimensions[1], elevation_min_m: scale.minM, elevation_max_m: scale.maxM,
    sea_level_m: scale.seaLevelM })
  if (mapping.mode === 'threshold') {
    files.set(`maps/${heightmapPlanet}/elevation.png`, await thresholdElevationPng(heightmap, mapping))
  }
  put(heightmapCreationPath, { version: 1, id, title, created, seed, meshCells, filename: heightmap.filename,
    sha256: heightmap.sha256, params, mapping, temperature: Boolean(temperature) })
  if (temperature) {
    put(`${experimentDir}/metadata.json`, { model: 'browser-temperature', version: temperature.version,
      planet: heightmapPlanet, fingerprint: temperature.fingerprint, unit: 'degC', calendar: 'model-month-january-first',
      projection: 'equirectangular', registration: 'pixel_center_north_up', grid: [GRID_W, GRID_H] })
    put(`${experimentDir}/temperature.json`, temperature)
  }
  return files
}

export async function exportHeightmapWorld(world: HeightmapWorld): Promise<Blob> {
  return writeCreationSnapshot(world.id, await worldFiles(world))
}

export async function importHeightmapWorld(blob: Blob): Promise<HeightmapWorld> {
  return readHeightmapSnapshot(await readCreationSnapshot(blob))
}

export async function readHeightmapSnapshot({ id, files, parse }: CreationSnapshot): Promise<HeightmapWorld> {
  const data = await parse(heightmapCreationPath)
  return readHeightmapWorldParts(id, data,
    async () => {
      const original = files.get(`${geologicalInput}/elevation_sources/${data?.sha256}.bin`)
      if (!original) throw new Error('Original heightmap is missing')
      return original
    }, () => parse(`${experimentDir}/temperature.json`),
    async () => files.get(`maps/${heightmapPlanet}/elevation.png`))
}

export async function readHeightmapWorldParts(id: string, value: unknown,
  readOriginal: () => Promise<Blob>, readResult: () => Promise<unknown>,
  readElevation?: () => Promise<Blob | undefined>) {
  const data = value as (Omit<HeightmapWorld, 'heightmap' | 'temperature' | 'mapping' | 'elevation'> & {
    version: number; filename: string; sha256: string; temperature: boolean; mapping?: unknown
  }) | null
  if (data?.id !== id || data.version !== 1 || typeof data.filename !== 'string' || typeof data.temperature !== 'boolean' ||
    typeof data.sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(data.sha256)) throw new Error('Unsupported heightmap world snapshot')
  const mapping = readHeightmapMapping(data.mapping, data.params)
  const [original, temperature, elevation] = await Promise.all([
    readOriginal(),
    data.temperature ? readResult().then(readTemperature) : undefined,
    readElevation && mapping.mode === 'threshold' ? readElevation() : undefined,
  ])
  if (mapping.mode === 'threshold' && readElevation && !elevation) throw new Error('Derived elevation raster is missing')
  const world: HeightmapWorld = { id, title: data.title, created: data.created, seed: data.seed, meshCells: data.meshCells,
    params: data.params, mapping, heightmap: await readHeightmapInput(original, data.filename), elevation, temperature }
  validateCreation(world)
  if (world.heightmap.sha256 !== data.sha256 || (world.temperature &&
    world.temperature.fingerprint !== await temperatureInputFingerprint(world.heightmap, world.params, world.mapping))) {
    throw new Error('Snapshot inputs do not match the saved experiment')
  }
  return world
}
