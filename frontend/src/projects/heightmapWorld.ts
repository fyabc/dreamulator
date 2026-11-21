import { GRID_H, GRID_W, MODEL_JANUARY_INDEX, EARTH_PARAMS, isTemperatureParams, type PlanetParams } from '../playground/temperatureDraft'
import type { KernelResult } from '../playground/temperature.worker'
import { readElevationPng, type ElevationRaster } from '../viewers/packs/elevationRaster'
import { maxSourceBytes } from './elevationProject'
import { isCreationWorldId, jsonBlob as json, readCreationSnapshot, sha256, writeCreationSnapshot,
  type CreationSnapshot } from './creationSnapshot'

export const heightmapCreationPath = 'browser-creation.json'
const experimentDir = 'layers/climate/derived/browser-temperature'
const geologicalInput = 'layers/geological/input'
export const heightmapPlanet = 'planet_terra'
const star = 'star_primary'

export type HeightmapInput = {
  original: Blob
  filename: string
  sha256: string
  raster: ElevationRaster & { depth: 8 | 16 }
}
export type SavedTemperature = {
  fingerprint: string
  version: string
  annual: number[]
  monthly: number[][]
}
export type HeightmapWorld = {
  id: string
  title: string
  created: string
  seed: number
  meshCells: number
  params: PlanetParams
  heightmap: HeightmapInput
  temperature?: SavedTemperature
}
export const heightmapMapPath = (id: string) => `/worlds/${encodeURIComponent(id)}/map/${heightmapPlanet}?creation=1`

export async function readHeightmapInput(blob: Blob, name: string): Promise<HeightmapInput> {
  if (!blob.size || blob.size > maxSourceBytes) throw new Error('Unsupported heightmap file size')
  const filename = name.trim().slice(0, 200)
  if (!filename) throw new Error('Heightmap name is missing')
  const raster = await readElevationPng(blob, 0, 65535, true)
  if (raster.width !== 2 * raster.height || raster.width > 8192) throw new Error('Expected a 2:1 global heightmap')
  return { original: blob, filename, sha256: await sha256(blob), raster }
}

function mapping(params: PlanetParams) {
  return { mode: 'range', min_m: params.elevMinM, max_m: params.elevMaxM, sea_level_m: params.seaLevelM }
}

export function isHeightmapParams(params: unknown): params is PlanetParams {
  return isTemperatureParams(params) && params.luminosity > 0 && Number.isFinite(params.elevMaxM - params.elevMinM)
}

function canonicalParams(params: PlanetParams) {
  return Object.fromEntries((Object.keys(EARTH_PARAMS) as (keyof PlanetParams)[]).map(key => [key, params[key]])) as PlanetParams
}

export function temperatureInputFingerprint(input: HeightmapInput, params: PlanetParams) {
  return sha256(json({ source: input.sha256, projection: 'equirectangular', registration: 'pixel_center_north_up',
    sampler: 'containing-pixel-v1', grid: [GRID_W, GRID_H], params: canonicalParams(params) }))
}

export function heightmapGrid(input: HeightmapInput, params: Pick<PlanetParams, 'elevMinM' | 'elevMaxM' | 'seaLevelM'>,
  width = GRID_W, height = GRID_H) {
  const source = input.raster
  const elevations = new Float64Array(width * height)
  const land = new Uint8Array(elevations.length)
  const span = params.elevMaxM - params.elevMinM
  for (let row = 0; row < height; row++) {
    const sourceRow = Math.floor((row + 0.5) / height * source.height) * source.width
    for (let column = 0; column < width; column++) {
      const value = params.elevMinM + source.values[sourceRow + Math.floor((column + 0.5) / width * source.width)] / 65535 * span
      const index = row * width + column
      elevations[index] = value
      land[index] = Number(value > params.seaLevelM)
    }
  }
  return { width, height, values: elevations, land }
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

function validateCreation({ id, title, created, seed, meshCells, params }: HeightmapWorld) {
  if (typeof id !== 'string' || !isCreationWorldId(id) || typeof title !== 'string' || !title.trim() || title.length > 120 ||
    typeof created !== 'string' || !Number.isFinite(Date.parse(created)) ||
    !Number.isSafeInteger(seed) || seed < 0 || seed > 0x7fffffff ||
    !Number.isSafeInteger(meshCells) || meshCells < 100 || meshCells > 200_000 || !isHeightmapParams(params)) {
    throw new Error('Invalid heightmap world settings')
  }
}

async function worldFiles(world: HeightmapWorld) {
  validateCreation(world)
  const { id, title, created, seed, meshCells, heightmap, temperature } = world
  const params = canonicalParams(world.params)
  if (temperature && (readTemperature(temperature).fingerprint !== await temperatureInputFingerprint(heightmap, params))) {
    throw new Error('Temperature result does not match the current world inputs')
  }
  const files = new Map<string, Blob>()
  const put = (path: string, value: unknown) => files.set(path, json(value))
  const dimensions = [heightmap.raster.width, heightmap.raster.height]
  put('world.yaml', {
    metadata: { name: id, description: title, created, modified: created, dreamulator_version: __APP_VERSION__, tags: ['browser-heightmap'] },
    seed: { seed }, planet_ids: [heightmapPlanet],
    layers: Object.fromEntries(['physics', 'chemistry', 'astronomy', 'geological', 'climate', 'ecology', 'civilization']
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
    output_resolution: dimensions, mapping: mapping(params), imported_at: created,
  } } })
  files.set(`${geologicalInput}/elevation_sources/${heightmap.sha256}.bin`, heightmap.original)
  put(`maps/${heightmapPlanet}/map.yaml`, { planet_id: heightmapPlanet, projection: 'equirectangular',
    width: dimensions[0], height: dimensions[1], elevation_min_m: params.elevMinM, elevation_max_m: params.elevMaxM,
    sea_level_m: params.seaLevelM })
  put(heightmapCreationPath, { version: 1, id, title, created, seed, meshCells, filename: heightmap.filename,
    sha256: heightmap.sha256, params, temperature: Boolean(temperature) })
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
    }, () => parse(`${experimentDir}/temperature.json`))
}

export async function readHeightmapWorldParts(id: string, value: unknown, readOriginal: () => Promise<Blob>, readResult: () => Promise<unknown>) {
  const data = value as (Omit<HeightmapWorld, 'heightmap' | 'temperature'> & {
    version: number; filename: string; sha256: string; temperature: boolean
  }) | null
  if (data?.id !== id || data.version !== 1 || typeof data.filename !== 'string' || typeof data.temperature !== 'boolean' ||
    typeof data.sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(data.sha256)) throw new Error('Unsupported heightmap world snapshot')
  const [original, temperature] = await Promise.all([readOriginal(), data.temperature ? readResult().then(readTemperature) : undefined])
  const world: HeightmapWorld = { id, title: data.title, created: data.created, seed: data.seed, meshCells: data.meshCells,
    params: data.params, heightmap: await readHeightmapInput(original, data.filename), temperature }
  validateCreation(world)
  if (world.heightmap.sha256 !== data.sha256 || (world.temperature &&
    world.temperature.fingerprint !== await temperatureInputFingerprint(world.heightmap, world.params))) {
    throw new Error('Snapshot inputs do not match the saved experiment')
  }
  return world
}
