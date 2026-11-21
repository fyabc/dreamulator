import { assertProjectCapacity, importProject, maxProjectBytes, readElevationLayers, record,
  type ElevationSource, type LocalProject, type ProjectLayer } from './elevationProject'
import { maxTemperatureDrafts, restoreTemperatureDraft } from '../playground/temperatureDraft'

const encoder = new TextEncoder()
const decoder = new TextDecoder()
const blockSize = 512
const maxMetadata = 8 * 1024
const worldId = /^[a-zA-Z0-9_-]{1,100}$/
const layerId = /^[a-f0-9-]{36}$/
const archivePath = /^[a-zA-Z0-9_./-]{1,100}$/
const maxFiles = 2 + 128 * 3 + maxTemperatureDrafts * 2
const maxArchive = maxProjectBytes + maxFiles * (maxMetadata + 2 * blockSize) + 2 * blockSize

function tarHeader(path: string, bytes: number) {
  const header = new Uint8Array(blockSize)
  const split = path.length > 100 ? path.lastIndexOf('/') : -1
  const name = encoder.encode(path.slice(split + 1))
  const prefix = encoder.encode(split < 0 ? '' : path.slice(0, split))
  if (name.length > 100 || prefix.length > 155) throw new Error('World archive path is too long')
  header.set(name)
  header.set(prefix, 345)
  header.set(encoder.encode('0000644\0'), 100)
  header.set(encoder.encode('0000000\0' + '0000000\0'), 108)
  header.set(encoder.encode(bytes.toString(8).padStart(11, '0') + '\0'), 124)
  header.set(encoder.encode('00000000000\0'), 136)
  header.fill(32, 148, 156)
  header[156] = 48
  header.set(encoder.encode('ustar\x0000'), 257)
  const checksum = header.reduce((sum, byte) => sum + byte, 0)
  header.set(encoder.encode(checksum.toString(8).padStart(6, '0') + '\0 '), 148)
  return header
}

export function writeTar(files: Map<string, Blob>) {
  const parts: BlobPart[] = []
  for (const [path, blob] of files) {
    parts.push(tarHeader(path, blob.size), blob, new Uint8Array((blockSize - blob.size % blockSize) % blockSize))
  }
  return new Blob([...parts, new Uint8Array(2 * blockSize)], { type: 'application/x-tar' })
}

export async function readTar(file: Blob, allowPrefix = false) {
  if (file.size < 3 * blockSize || file.size > maxArchive || file.size % blockSize) throw new Error('Invalid world archive size')
  const files = new Map<string, Blob>()
  for (let offset = 0; offset + 2 * blockSize <= file.size;) {
    const header = new Uint8Array(await file.slice(offset, offset + blockSize).arrayBuffer())
    if (header.every((byte) => byte === 0)) {
      const tail = new Uint8Array(await file.slice(offset + blockSize, offset + 2 * blockSize).arrayBuffer())
      if (offset + 2 * blockSize !== file.size || tail.some((byte) => byte !== 0)) throw new Error('Invalid archive end')
      return files
    }
    const field = (start: number, length: number) => decoder.decode(header.subarray(start, start + length)).split('\0')[0].trim()
    const prefix = field(345, 155)
    const path = prefix ? `${prefix}/${field(0, 100)}` : field(0, 100)
    const size = field(124, 12)
    const checksum = field(148, 8)
    if (files.size >= maxFiles || !(allowPrefix ? /^[a-zA-Z0-9_./-]{1,256}$/ : archivePath).test(path) ||
      path.split('/').some((part) => !part || part === '.' || part === '..') ||
      files.has(path) || header[156] !== 48 || field(257, 6) !== 'ustar' || (!allowPrefix && header.subarray(345, 500).some(Boolean)) ||
      !/^[0-7]{1,11}$/.test(size) || !/^[0-7]{1,7}$/.test(checksum) ||
      parseInt(checksum, 8) !== header.reduce((sum, byte, index) => sum + (index >= 148 && index < 156 ? 32 : byte), 0)) {
      throw new Error('Invalid world archive entry')
    }
    const start = offset + blockSize
    const bytes = parseInt(size, 8)
    offset = start + Math.ceil(bytes / blockSize) * blockSize
    if (offset > file.size - 2 * blockSize) throw new Error('Incomplete world archive')
    files.set(path, file.slice(start, start + bytes))
  }
  throw new Error('Incomplete world archive')
}

const packPath = (id: string) => `packs/browser-${id}/input`

function npyHeader(width: number, height: number) {
  const header = `{'descr': '<f4', 'fortran_order': False, 'shape': (${height}, ${width}), }`.padEnd(117) + '\n'
  const bytes = new Uint8Array(128)
  bytes.set([0x93, 78, 85, 77, 80, 89, 1, 0, 118, 0])
  bytes.set(encoder.encode(header), 10)
  return bytes
}

function layerMetadata(world: LocalProject, layer: ProjectLayer, source: ElevationSource) {
  const { window, min, max, sea, sourceStepKm } = source.frame
  const { extentKmX, extentKmY } = window
  return {
    pack_version: 4, center_lat: window.centerLat, center_lon: window.centerLon,
    projection: window.projection, span_km: extentKmX, radius_km: window.radiusKm,
    extent_km: { x: extentKmX, y: extentKmY }, grid: { w: layer.width, h: layer.height },
    km_per_px: { x: extentKmX / layer.width, y: extentKmY / layer.height },
    sea_level_m: sea, elevation_m_global: [min, max], height_gaea_png_range_m: [min, max], climate: {},
    source: { kind: 'external-heightmap', world: world.id,
      planet: source.location?.planet ?? null, branch: source.location?.branch ?? null },
    browser: {
      name: layer.name, kind: layer.kind,
      ...(layer.kind === 'elevation-source' ? { source_step_km: sourceStepKm,
        ...(layer.original && { original: { name: layer.original.name, bytes: layer.original.data.size } }) }
        : { source_id: layer.sourceId, settings: layer.settings }),
    },
  }
}

export function exportWorldData(world: LocalProject) {
  assertProjectCapacity(world)
  if (!worldId.test(world.id)) throw new Error('Invalid world ID')
  const files = new Map<string, Blob>()
  const json = (path: string, value: unknown) => {
    const blob = new Blob([JSON.stringify(value, null, 2) + '\n'])
    if (blob.size > maxMetadata) throw new Error('World metadata is too large')
    files.set(path, blob)
  }
  json('world-data.json', { type: 'dreamulator-world-data', version: 1, id: world.id, name: world.name,
    published: world.published === true, layers: world.layers.map((layer) => layer.id),
    ...(world.temperatureDrafts?.length && { temperature_drafts: world.temperatureDrafts.map(draft => draft.id) }) })
  for (const draft of world.temperatureDrafts ?? []) {
    const { id, grid, ...metadata } = draft
    if (!layerId.test(id)) throw new Error('Invalid temperature draft ID')
    json(`experiments/temperature/${id}.json`, metadata)
    files.set(`experiments/temperature/${id}.f32`, grid)
  }
  if (!world.published) {
    const timestamp = new Date(world.updatedAt).toISOString()
    json('world.yaml', { metadata: { name: world.id, description: world.name, created: timestamp, modified: timestamp }, seed: { seed: 0 } })
  }
  const sources = new Map(world.layers.flatMap((layer) => layer.kind === 'elevation-source' ? [[layer.id, layer] as const] : []))
  for (const layer of world.layers) {
    if (!layerId.test(layer.id)) throw new Error('Invalid layer ID')
    const source = layer.kind === 'elevation-source' ? layer : sources.get(layer.sourceId)
    if (!source) throw new Error('Missing elevation source')
    const path = packPath(layer.id)
    json(`${path}/meta.json`, layerMetadata(world, layer, source))
    files.set(`${path}/height.meters.npy`, new Blob([npyHeader(layer.width, layer.height), layer.data]))
    if (layer.kind === 'elevation-source' && layer.original) files.set(`${path}/original.png`, layer.original.data)
  }
  return writeTar(files)
}

export async function importWorldData(file: Blob): Promise<LocalProject> {
  const files = await readTar(file)
  const take = (path: string) => {
    const blob = files.get(path)
    if (!blob) throw new Error(`Missing world data entry: ${path}`)
    files.delete(path)
    return blob
  }
  const json = async (path: string): Promise<unknown> => {
    const blob = take(path)
    if (blob.size > maxMetadata) throw new Error('World metadata is too large')
    return JSON.parse(await blob.text())
  }
  const manifest = await json('world-data.json')
  if (!record(manifest) || manifest.type !== 'dreamulator-world-data' || manifest.version !== 1 ||
    typeof manifest.id !== 'string' || !worldId.test(manifest.id) || typeof manifest.name !== 'string' ||
    !manifest.name.trim() || manifest.name.length > 200 || typeof manifest.published !== 'boolean' ||
    !Array.isArray(manifest.layers) || manifest.layers.length > 128) throw new Error('Invalid world data manifest')
  if (!manifest.published) {
    const config = await json('world.yaml')
    if (!record(config) || !record(config.metadata) || config.metadata.name !== manifest.id) throw new Error('Mismatched world config')
  }
  const layers = await readElevationLayers(await Promise.all(manifest.layers.map(async (id: unknown) => {
    if (typeof id !== 'string' || !layerId.test(id)) throw new Error('Invalid layer ID')
    const meta = await json(`${packPath(id)}/meta.json`)
    if (!record(meta) || !record(meta.browser) || !record(meta.grid) || !record(meta.extent_km) || !record(meta.source) ||
      meta.source.world !== manifest.id || !Array.isArray(meta.elevation_m_global)) throw new Error('Invalid region metadata')
    const [min, max] = meta.elevation_m_global
    return { ...meta.browser, id, width: meta.grid.w, height: meta.grid.h, sourceId: meta.browser.source_id,
      ...(meta.source.planet !== null && { location: { planet: meta.source.planet, branch: meta.source.branch } }),
      frame: { min, max, sea: meta.sea_level_m, sourceStepKm: meta.browser.source_step_km,
        window: { centerLat: meta.center_lat, centerLon: meta.center_lon, radiusKm: meta.radius_km,
          extentKmX: meta.extent_km.x, extentKmY: meta.extent_km.y, projection: meta.projection } } }
  })), async (entry, original) => {
    const path = packPath(String(entry.id))
    if (original !== undefined) return take(`${path}/original.png`)
    const blob = take(`${path}/height.meters.npy`)
    const header = npyHeader(Number(entry.width), Number(entry.height))
    const actual = new Uint8Array(await blob.slice(0, header.length).arrayBuffer())
    if (blob.size !== header.length + Number(entry.width) ** 2 * 4 || !header.every((byte, index) => byte === actual[index])) {
      throw new Error('Invalid world elevation array')
    }
    return blob.slice(header.length)
  })
  const draftIds = manifest.temperature_drafts ?? []
  if (!Array.isArray(draftIds) || draftIds.length > maxTemperatureDrafts || new Set(draftIds).size !== draftIds.length) {
    throw new Error('Invalid temperature draft manifest')
  }
  const temperatureDrafts = await Promise.all(draftIds.map(async (id: unknown) => {
    if (typeof id !== 'string' || !layerId.test(id)) throw new Error('Invalid temperature draft ID')
    const path = `experiments/temperature/${id}`
    return restoreTemperatureDraft(await json(`${path}.json`), id, take(`${path}.f32`))
  }))
  if (files.size) throw new Error('Unexpected world archive entries')
  const world: LocalProject = { id: manifest.id, name: manifest.name, updatedAt: Date.now(), layers,
    ...(manifest.published && { published: true }), ...(temperatureDrafts.length && { temperatureDrafts }) }
  assertProjectCapacity(world)
  return world
}

export function readWorldBackup(file: File) {
  return file.name.toLowerCase().endsWith('.dreamulator') ? importProject(file) : importWorldData(file)
}
