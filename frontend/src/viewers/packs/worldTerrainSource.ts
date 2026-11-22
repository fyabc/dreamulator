import { decode } from '@msgpack/msgpack'
import { KDTree3D } from '../../components/map/utils/kdtree'
import { interpolate, type ElevationRaster } from './elevationRaster'
import { pxToLonLat, type PackWindow } from './packCoords'
import { prepareTerrainConditions, terrainClimateFields, terrainLapseRate, type TerrainClimateConditions } from './terrainConditions'

const fields = ['elevation_m', ...terrainClimateFields] as const
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object'
const littleEndian = new Uint8Array(Uint16Array.of(1).buffer)[0] === 1

function doubles(bytes: Uint8Array) {
  if (littleEndian && bytes.byteOffset % 8 === 0) return new Float64Array(bytes.buffer, bytes.byteOffset, bytes.byteLength / 8)
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
  return Float64Array.from({ length: bytes.byteLength / 8 }, (_, index) => view.getFloat64(index * 8, true))
}

export function decodeWorldTerrainSource(bytes: ArrayBuffer) {
  const data = decode(bytes)
  if (data === null) return null
  if (!record(data) || data.version !== 1 || typeof data.cells !== 'number' || !Number.isSafeInteger(data.cells) || data.cells <= 0 ||
      !record(data.fields) || (data.native !== null && (typeof data.native !== 'string' || !/^[a-f0-9]{64}$/.test(data.native)))) {
    throw new Error('Invalid world TD source')
  }
  const read = (value: unknown, length: number, nonnegative = false) => {
    if (!(value instanceof Uint8Array) || value.byteLength !== length * 8) throw new Error('Invalid world TD field length')
    const values = doubles(value)
    if (!values.every(sample => Number.isFinite(sample) && (!nonnegative || sample >= 0))) throw new Error('Invalid world TD value')
    return values
  }
  const sources = data.fields
  const cells = data.cells
  return {
    cells, native: data.native, positions: read(data.positions, cells * 3),
    fields: Object.fromEntries(fields.map(name => [name, read(sources[name], cells, name !== 'elevation_m' && name !== 'temperature_mean_c')])) as
      Record<typeof fields[number], Float64Array>,
  }
}

export async function readNativeTerrain(blob: Blob) {
  const raw = await new Response(blob.stream().pipeThrough(new DecompressionStream('gzip'))).arrayBuffer()
  const header = new DataView(raw)
  const width = header.getUint32(0, true)
  const height = header.getUint32(4, true)
  if (!width || !height || width * height > 4096 * 2048 || raw.byteLength !== 8 + width * height * 8) {
    throw new Error('Invalid native TD elevation')
  }
  return { width, height, values: doubles(new Uint8Array(raw, 8)) }
}

export function prepareWorldTerrainSource(source: NonNullable<ReturnType<typeof decodeWorldTerrainSource>>, window: PackWindow,
  native: Awaited<ReturnType<typeof readNativeTerrain>> | ElevationRaster | null) {
  if (Boolean(source.native) !== Boolean(native) || window.projection !== 'azimuthal_equidistant' || window.extentKmX !== window.extentKmY) {
    throw new Error('Invalid TD source window or missing native elevation')
  }
  const cells = window.extentKmX / (Math.PI * window.radiusKm / 2047)
  const floor = Math.floor(cells)
  const side = Math.max(2, cells - floor === 0.5 ? floor + floor % 2 : Math.round(cells))
  if (!Number.isFinite(side) || side > 2048) throw new Error('Invalid TD source grid dimensions')
  const { positions } = source
  const tree = new KDTree3D(Array.from({ length: source.cells }, (_, index) =>
    [positions[index * 3], positions[index * 3 + 1], positions[index * 3 + 2], index]), true)
  const climate = Object.fromEntries(terrainClimateFields.map(name => [name, new Float32Array(side ** 2)])) as TerrainClimateConditions
  const values = new Float32Array(side ** 2)
  for (let pixel = 0; pixel < values.length; pixel++) {
    const { lat, lon } = pxToLonLat(pixel % side, Math.floor(pixel / side), side, side, window)
    const latitude = lat * Math.PI / 180
    const longitude = lon * Math.PI / 180
    const cosLat = Math.cos(latitude)
    const cell = tree.nearest(cosLat * Math.cos(longitude), Math.sin(latitude), cosLat * Math.sin(longitude))
    const meshHeight = source.fields.elevation_m[cell]
    const height = native ? interpolate(native, (lon + 180) * native.width / 360 - 0.5, (90 - lat) * native.height / 180 - 0.5, true) : meshHeight
    values[pixel] = height
    for (const name of terrainClimateFields) climate[name][pixel] = source.fields[name][cell]
    climate.temperature_mean_c[pixel] = source.fields.temperature_mean_c[cell] +
      terrainLapseRate(source.fields.precipitation_total_mm[cell]) * (Math.max(0, height) - Math.max(0, meshHeight))
  }
  return prepareTerrainConditions({ width: side, height: side, values }, window.extentKmX, climate)
}
