import type { ElevationRaster } from '../viewers/packs/elevationRaster'
import type { BrowserTerrainResult } from '../viewers/packs/TerrainCompute'
import type { PackWindow } from '../viewers/packs/packCoords'
import { supportsTerrainSpan } from '../viewers/packs/terrainTiles'
import { terrainRecipe } from '../viewers/packs/terrainRecommendation'

export const maxProjectBytes = 256 * 2 ** 20
export const maxSourceBytes = 32 * 2 ** 20
export const maxSourceSide = 4096
const maxLayers = 128

export type ElevationFrame = { window: PackWindow; min: number; max: number; sea: number; sourceStepKm: number }
type LayerBase = { id: string; name: string; width: number; height: number; data: Blob }
export type ElevationSource = LayerBase & {
  kind: 'elevation-source'
  frame: ElevationFrame
  location?: { planet: string; branch: string | null }
  original?: { name: string; data: Blob }
}
export type ElevationResult = LayerBase & {
  kind: 'elevation-result'
  sourceId: string
  settings: Omit<BrowserTerrainResult, 'raster'>
}
export type ProjectLayer = ElevationSource | ElevationResult
export type LocalProject = { id: string; name: string; updatedAt: number; layers: ProjectLayer[]; published?: true }

export function elevationSource(layers: ProjectLayer[], layer: ProjectLayer): ElevationSource | undefined {
  return layer.kind === 'elevation-source' ? layer :
    layers.find((input): input is ElevationSource => input.kind === 'elevation-source' && input.id === layer.sourceId)
}

export function projectBytes(project: LocalProject) {
  return project.layers.reduce((size, layer) => size + layer.data.size + (layer.kind === 'elevation-source' ? layer.original?.data.size ?? 0 : 0), 0)
}

function encodeRaster(raster: ElevationRaster) {
  return new Blob([new Uint8Array(raster.values.buffer as ArrayBuffer, raster.values.byteOffset, raster.values.byteLength)])
}

export async function openProjectRaster(layer: ProjectLayer): Promise<ElevationRaster> {
  const { width, height, data } = layer
  const values = new Float32Array(await data.arrayBuffer())
  if (values.length !== width * height || !values.every(Number.isFinite)) throw new Error('Invalid elevation values')
  return { width, height, values }
}

export function makeElevationSource(name: string, raster: ElevationRaster, frame: ElevationFrame, original?: File): ElevationSource {
  return { kind: 'elevation-source', id: crypto.randomUUID(), name: name.slice(0, 200),
    frame, width: raster.width, height: raster.height, data: encodeRaster(raster),
    ...(original && { original: { name: original.name.slice(0, 200), data: original } }) }
}

export function makeElevationResult(name: string, sourceId: string, { raster, ...settings }: BrowserTerrainResult): ElevationResult {
  return { kind: 'elevation-result', id: crypto.randomUUID(), name: name.slice(0, 200),
    sourceId, settings, width: raster.width, height: raster.height, data: encodeRaster(raster) }
}

export function assertProjectCapacity(project: LocalProject) {
  if (project.layers.length > maxLayers || projectBytes(project) > maxProjectBytes) throw new Error('Project capacity exceeded')
}

export const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value)
const number = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value)
const name = (value: unknown): value is string => typeof value === 'string' && !!value.trim() && value.length <= 200
const id = (value: unknown): value is string => typeof value === 'string' && /^[a-f0-9-]{36}$/.test(value)
const dimension = (value: unknown): value is number => number(value) && Number.isInteger(value) && value >= 1 && value <= maxSourceSide

function validFrame(value: unknown): value is ElevationFrame {
  if (!record(value) || !record(value.window)) return false
  const { window, min, max, sea, sourceStepKm } = value
  return number(min) && number(max) && Math.abs(min) <= 1e9 && Math.abs(max) <= 1e9 && max >= min &&
    number(sea) && Math.abs(sea) <= 1e9 && number(sourceStepKm) && sourceStepKm > 0 &&
    number(window.centerLat) && Math.abs(window.centerLat) <= 90 && number(window.centerLon) && Math.abs(window.centerLon) <= 180 &&
    number(window.radiusKm) && window.radiusKm > 0 && number(window.extentKmX) && window.extentKmX > 0 &&
    window.extentKmX < Math.PI * window.radiusKm && window.extentKmX === window.extentKmY && window.projection === 'azimuthal_equidistant'
}

function validSettings(value: unknown, source: ElevationSource, width: number): value is ElevationResult['settings'] {
  if (!record(value) || !record(value.recipe)) return false
  const { recipe, nativeSpacingKm, recommendation, manifestSha256 } = value
  const { seed, residualGain, method, preserveKm } = recipe
  if ((method !== 'redraw' && method !== 'enhanced' && method !== 'blend') || !number(seed) || !number(residualGain) ||
    (nativeSpacingKm !== null && (!number(nativeSpacingKm) || nativeSpacingKm <= 0)) || (recommendation !== null && recommendation !== 'redraw') ||
    typeof manifestSha256 !== 'string' || !/^[a-f0-9]{64}$/.test(manifestSha256) || !supportsTerrainSpan(source.frame.window.extentKmX) ||
    (method === 'blend' && !number(preserveKm))) return false
  const actual = terrainRecipe(method, nativeSpacingKm, source.frame.window.extentKmX / width,
    { seed: String(seed), gain: String(residualGain), wavelength: method === 'blend' ? String(preserveKm) : '' })
  return actual !== null && actual.residualGain === residualGain
}

const projectType = 'dreamulator-project'
const maxHeaderBytes = 256 * 1024

export function exportProject(project: LocalProject) {
  assertProjectCapacity(project)
  const blobs: Blob[] = []
  const layers = project.layers.map(({ data, ...layer }: ProjectLayer) => {
    blobs.push(data)
    if (layer.kind === 'elevation-source' && layer.original) {
      blobs.push(layer.original.data)
      return { ...layer, original: { name: layer.original.name, bytes: layer.original.data.size } }
    }
    return layer
  })
  const header = new TextEncoder().encode(JSON.stringify({ type: projectType, version: 1, name: project.name, layers }))
  if (header.length > maxHeaderBytes) throw new Error('Project header too large')
  const prefix = new DataView(new ArrayBuffer(4))
  prefix.setUint32(0, header.length, true)
  return new Blob([prefix, header, ...blobs], { type: 'application/octet-stream' })
}

export async function importProject(file: Blob): Promise<LocalProject> {
  if (file.size < 4 || file.size > maxProjectBytes + maxHeaderBytes + 4) throw new Error('Invalid project file size')
  const headerSize = new DataView(await file.slice(0, 4).arrayBuffer()).getUint32(0, true)
  let offset = 4 + headerSize
  if (headerSize > maxHeaderBytes || offset > file.size) throw new Error('Invalid project header size')
  const header: unknown = JSON.parse(await file.slice(4, offset).text())
  if (!record(header) || header.type !== projectType || header.version !== 1 || !name(header.name) ||
    !Array.isArray(header.layers) || header.layers.length > maxLayers) throw new Error('Unsupported project file')
  const read = (bytes: number) => {
    if (offset + bytes > file.size) throw new Error('Incomplete project file')
    const blob = file.slice(offset, offset + bytes)
    offset += bytes
    return blob
  }
  const layers = await readElevationLayers(header.layers, (entry, original) => read(original ?? Number(entry.width) ** 2 * 4))
  if (offset !== file.size) throw new Error('Unexpected data in project file')
  const project = { id: crypto.randomUUID(), name: header.name, updatedAt: Date.now(), layers }
  assertProjectCapacity(project)
  return project
}

export async function readElevationLayers(entries: unknown[], data: (entry: Record<string, unknown>, original?: number) => Blob | Promise<Blob>) {
  if (entries.length > maxLayers) throw new Error('Too many elevation layers')
  const layers: ProjectLayer[] = []
  const sources = new Map<string, ElevationSource>()
  const ids = new Set<string>()
  for (const entry of entries) {
    if (!record(entry) || !id(entry.id) || ids.has(entry.id) || !name(entry.name) || !dimension(entry.width) || entry.width !== entry.height) {
      throw new Error('Invalid project layer')
    }
    const base = { id: entry.id, name: entry.name, width: entry.width, height: entry.width, data: await data(entry) }
    ids.add(base.id)
    if (entry.kind === 'elevation-source' && validFrame(entry.frame)) {
      const layer: ElevationSource = { ...base, kind: entry.kind, frame: entry.frame }
      if (entry.location !== undefined) {
        const location = entry.location
        if (!record(location) || !name(location.planet) || (location.branch !== null && !name(location.branch))) throw new Error('Invalid layer location')
        layer.location = { planet: location.planet, branch: location.branch }
      }
      if (entry.original !== undefined) {
        const original = entry.original
        if (!record(original) || !name(original.name) || !dimensionBytes(original.bytes)) throw new Error('Invalid source file')
        const blob = await data(entry, original.bytes)
        if (blob.size !== original.bytes) throw new Error('Invalid source file size')
        layer.original = { name: original.name, data: blob }
      }
      sources.set(layer.id, layer)
      layers.push(layer)
    } else if (entry.kind === 'elevation-result' && id(entry.sourceId)) {
      const source = sources.get(entry.sourceId)
      if (!source || !validSettings(entry.settings, source, base.width)) throw new Error('Invalid result settings')
      layers.push({ ...base, kind: entry.kind, sourceId: entry.sourceId, settings: entry.settings })
    } else throw new Error('Invalid layer type')
    await openProjectRaster(layers[layers.length - 1])
  }
  return layers
}

function dimensionBytes(value: unknown): value is number {
  return number(value) && Number.isInteger(value) && value > 0 && value <= maxSourceBytes
}
