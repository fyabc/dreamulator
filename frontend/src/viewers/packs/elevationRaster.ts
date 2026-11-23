import { pxToLonLat, type PackWindow } from './packCoords'

export interface ElevationRaster {
  width: number
  height: number
  values: Float32Array
}

export type ElevationFormat = 'png' | 'tiff'

const MAX_PIXELS = 8192 * 4096
const PNG_SIGNATURE = [137, 80, 78, 71, 13, 10, 26, 10]
const JPEG_SIGNATURE = [0xff, 0xd8, 0xff]
const PNG_CRC_TABLE = Uint32Array.from({ length: 256 }, (_, index) => {
  let crc = index
  for (let bit = 0; bit < 8; bit++) crc = (crc >>> 1) ^ (crc & 1 ? 0xedb88320 : 0)
  return crc
})

function checkDimensions(width: number, height: number) {
  if (!Number.isInteger(width) || !Number.isInteger(height) || width < 1 || height < 1 || width * height > MAX_PIXELS) {
    throw new Error('Unsupported elevation raster dimensions')
  }
}

function paeth(left: number, above: number, corner: number) {
  const guess = left + above - corner
  const leftDistance = Math.abs(guess - left)
  const aboveDistance = Math.abs(guess - above)
  const cornerDistance = Math.abs(guess - corner)
  return leftDistance <= aboveDistance && leftDistance <= cornerDistance ? left
    : aboveDistance <= cornerDistance ? above : corner
}

/** True when the first bytes are a JPEG start-of-image marker. */
export function isJpegBytes(bytes: Uint8Array): boolean {
  return bytes.length >= JPEG_SIGNATURE.length && JPEG_SIGNATURE.every((value, index) => bytes[index] === value)
}

/**
 * Decode a JPEG through the browser's image decoder and re-encode it as an 8-bit
 * grayscale PNG, so the rest of the heightmap pipeline keeps its PNG contract.
 *
 * Images shared through chat apps arrive as JPEG (the app converts PNG uploads on
 * download).  JPEG is 8-bit and lossy, so this is a convenience path, not the precise
 * one.  Luminance uses Pillow's RGB→L weights, so the same file yields the same
 * samples whether it is imported in the browser or on the server.
 */
export async function jpegToGrayscalePng(blob: Blob): Promise<Blob> {
  if (typeof createImageBitmap !== 'function' || typeof OffscreenCanvas !== 'function') {
    throw new Error('This browser cannot decode JPEG; export the heightmap as a grayscale PNG')
  }
  // imageOrientation 'none' mirrors Pillow, which also ignores EXIF orientation; the
  // stored pixel grid is what a heightmap is.
  const bitmap = await createImageBitmap(blob, { colorSpaceConversion: 'none', premultiplyAlpha: 'none',
    imageOrientation: 'none' })
  try {
    const { width, height } = bitmap
    checkDimensions(width, height)
    const canvas = new OffscreenCanvas(width, height)
    const context = canvas.getContext('2d', { willReadFrequently: true })
    if (!context) throw new Error('This browser cannot decode JPEG; export the heightmap as a grayscale PNG')
    context.drawImage(bitmap, 0, 0)
    const { data } = context.getImageData(0, 0, width, height)
    const samples = new Uint8Array(width * height)
    for (let index = 0; index < samples.length; index++) {
      const pixel = index * 4
      samples[index] = Math.round(0.299 * data[pixel] + 0.587 * data[pixel + 1] + 0.114 * data[pixel + 2])
    }
    return grayscalePng8(width, height, samples)
  } finally {
    bitmap.close()
  }
}

/** Encode 8-bit grayscale samples as a single-channel, non-interlaced PNG. */
async function grayscalePng8(width: number, height: number, samples: Uint8Array): Promise<Blob> {
  checkDimensions(width, height)
  if (samples.length !== width * height) throw new Error('Incomplete elevation raster')
  const stride = width + 1
  const scanlines = new Uint8Array(height * stride)
  for (let row = 0; row < height; row++) {
    scanlines.set(samples.subarray(row * width, (row + 1) * width), row * stride + 1)
  }
  const header = new Uint8Array(13)
  const ihdr = new DataView(header.buffer)
  ihdr.setUint32(0, width)
  ihdr.setUint32(4, height)
  ihdr.setUint8(8, 8) // bit depth 8; color type 0 (grayscale) and the rest stay zero
  const compressed = new Blob([scanlines]).stream().pipeThrough(new CompressionStream('deflate'))
  const image = new Uint8Array(await new Response(compressed).arrayBuffer())
  return new Blob([new Uint8Array(PNG_SIGNATURE), pngChunk(0x49484452, header), pngChunk(0x49444154, image),
    pngChunk(0x49454e44, new Uint8Array(0))], { type: 'image/png' })
}

export async function readElevationPng(blob: Blob, min: number, max: number, strict = false): Promise<ElevationRaster & { depth: 8 | 16 }> {
  const bytes = new Uint8Array(await blob.arrayBuffer())
  const header = new DataView(bytes.buffer)
  if (bytes.length < 33 || !PNG_SIGNATURE.every((value, index) => bytes[index] === value) ||
    header.getUint32(8) !== 13 || header.getUint32(12) !== 0x49484452 ||
    !Number.isFinite(min) || !Number.isFinite(max) || max < min) throw new Error('Invalid elevation PNG')
  const width = header.getUint32(16)
  const height = header.getUint32(20)
  checkDimensions(width, height)
  const depth = bytes[24]
  if ((depth !== 8 && depth !== 16) || bytes[25] || bytes[26] || bytes[27] || bytes[28]) {
    throw new Error('Expected a non-interlaced grayscale heightmap')
  }
  const chunks: Uint8Array<ArrayBuffer>[] = []
  let ended = false
  if (strict && pngCrc(bytes, 12, 29) !== header.getUint32(29)) throw new Error('Invalid PNG checksum')
  for (let offset = 33; offset + 12 <= bytes.length;) {
    const length = header.getUint32(offset)
    const kind = header.getUint32(offset + 4)
    const last = offset + 8 + length
    if (last + 4 > bytes.length) throw new Error('Truncated heightmap')
    if (strict && pngCrc(bytes, offset + 4, last) !== header.getUint32(last)) throw new Error('Invalid PNG checksum')
    if (kind === 0x49444154) chunks.push(bytes.subarray(offset + 8, offset + 8 + length))
    if (kind === 0x49454e44) {
      ended = length === 0 && last + 4 === bytes.length
      break
    }
    offset += 12 + length
  }
  if (strict && (!ended || !chunks.length)) throw new Error('Incomplete heightmap')
  const stride = width * (depth / 8) + 1
  const scanlines = new Uint8Array(height * stride)
  const reader = new Blob(chunks).stream().pipeThrough(new DecompressionStream('deflate')).getReader()
  let received = 0
  try {
    for (;;) {
      const { value, done } = await reader.read()
      if (done) break
      scanlines.set(value, received)
      received += value.length
    }
  } finally {
    await reader.cancel()
  }
  if (received !== scanlines.length) throw new Error('Incomplete heightmap')
  const values = new Float32Array(width * height)
  const channels = depth / 8
  const scale = (max - min) / (depth === 16 ? 65535 : 255)
  for (let row = 0; row < height; row++) {
    const start = row * stride
    const filter = scanlines[start]
    if (filter > 4) throw new Error('Unknown PNG scanline filter')
    for (let col = 1; col < stride; col++) {
      const left = col > channels ? scanlines[start + col - channels] : 0
      const above = row ? scanlines[start + col - stride] : 0
      const corner = row && col > channels ? scanlines[start + col - stride - channels] : 0
      if (filter) scanlines[start + col] += filter === 1 ? left : filter === 2 ? above
        : filter === 3 ? (left + above) >> 1 : paeth(left, above, corner)
    }
    for (let col = 0; col < width; col++) {
      const offset = start + 1 + col * channels
      const sample = depth === 16 ? scanlines[offset] * 256 + scanlines[offset + 1] : scanlines[offset]
      values[row * width + col] = min + sample * scale
    }
  }
  return { width, height, values, depth }
}

export function readElevationNpy(buffer: ArrayBuffer): ElevationRaster {
  const data = new DataView(buffer)
  if (buffer.byteLength < 12 || data.getUint32(0) !== 0x934e554d || data.getUint16(4) !== 0x5059) {
    throw new Error('Invalid elevation array')
  }
  const version = data.getUint8(6)
  if (version < 1 || version > 3) throw new Error('Unsupported NPY version')
  const start = version === 1 ? 10 : 12
  const length = version === 1 ? data.getUint16(8, true) : data.getUint32(8, true)
  const offset = start + length
  const header = new TextDecoder().decode(new Uint8Array(buffer, start, length))
  const dtype = /['"]descr['"]\s*:\s*['"]([<>]f[48])['"]/.exec(header)?.[1]
  const shape = /['"]shape['"]\s*:\s*\(\s*(\d+),\s*(\d+)\s*,?\s*\)/.exec(header)
  if (!dtype || !shape || !/['"]fortran_order['"]\s*:\s*False/.test(header)) throw new Error('Unsupported elevation array')
  const height = Number(shape[1])
  const width = Number(shape[2])
  checkDimensions(width, height)
  const size = Number(dtype[2])
  if (offset + width * height * size !== buffer.byteLength) throw new Error('Incomplete elevation array')
  if (dtype === '<f4' && offset % 4 === 0) return { width, height, values: new Float32Array(buffer, offset) }
  const little = dtype[0] === '<'
  const values = new Float32Array(width * height)
  for (let index = 0; index < values.length; index++) {
    const position = offset + index * size
    values[index] = size === 4 ? data.getFloat32(position, little) : data.getFloat64(position, little)
  }
  return { width, height, values }
}

export function interpolate({ values, width, height }: Omit<ElevationRaster, 'values'> & { values: Float32Array | Float64Array }, col: number, row: number, wrap = false) {
  const boundedRow = Math.max(0, Math.min(height - 1, row))
  const boundedCol = wrap ? ((col % width) + width) % width : Math.max(0, Math.min(width - 1, col))
  const left = Math.floor(boundedCol)
  const right = wrap ? (left + 1) % width : Math.min(width - 1, left + 1)
  const top = Math.floor(boundedRow)
  const bottom = Math.min(height - 1, top + 1)
  const fractionX = boundedCol - left
  const fractionY = boundedRow - top
  const upper = values[top * width + left] * (1 - fractionX) + values[top * width + right] * fractionX
  const lower = values[bottom * width + left] * (1 - fractionX) + values[bottom * width + right] * fractionX
  return upper * (1 - fractionY) + lower * fractionY
}

export function sampleGlobalElevation(source: ElevationRaster, window: PackWindow, size: number, pixelCentres = false): ElevationRaster {
  const width = Math.max(1, Math.round(size * window.extentKmX / Math.max(window.extentKmX, window.extentKmY)))
  const height = Math.max(1, Math.round(size * window.extentKmY / Math.max(window.extentKmX, window.extentKmY)))
  const values = new Float32Array(width * height)
  for (let row = 0; row < height; row++) {
    for (let col = 0; col < width; col++) {
      const { lon, lat } = pxToLonLat(col, row, width, height, window)
      const x = (lon + 180) / 360 * source.width
      const y = (90 - lat) / 180
      values[row * width + col] = interpolate(source, pixelCentres ? x - 0.5 : x,
        pixelCentres ? y * source.height - 0.5 : y * (source.height - 1), true)
    }
  }
  return { width, height, values }
}

export function resizeElevation(source: ElevationRaster, width: number, height: number): ElevationRaster {
  if (source.width === width && source.height === height) return source
  const values = new Float32Array(width * height)
  for (let row = 0; row < height; row++) {
    for (let col = 0; col < width; col++) {
      values[row * width + col] = interpolate(source, (col + 0.5) * source.width / width - 0.5,
        (row + 0.5) * source.height / height - 0.5)
    }
  }
  return { width, height, values }
}

function elevationDescription(raster: ElevationRaster, metadata: Record<string, unknown>) {
  return JSON.stringify({ ...metadata, unit: 'm',
    width: raster.width, height: raster.height, registration: 'pixel_center_north_up' })
    .replace(/[^\x20-\x7e]/g, (char) => `\\u${char.charCodeAt(0).toString(16).padStart(4, '0')}`)
}

function pngCrc(bytes: Uint8Array, start: number, end: number) {
  let crc = 0xffffffff
  for (let index = start; index < end; index++) crc = (crc >>> 8) ^ PNG_CRC_TABLE[(crc ^ bytes[index]) & 255]
  return (crc ^ 0xffffffff) >>> 0
}

function pngChunk(kind: number, body: Uint8Array) {
  const bytes = new Uint8Array(body.length + 12)
  const header = new DataView(bytes.buffer)
  header.setUint32(0, body.length)
  header.setUint32(4, kind)
  bytes.set(body, 8)
  header.setUint32(bytes.length - 4, pngCrc(bytes, 4, bytes.length - 4))
  return bytes
}

/**
 * Encode metres as a 16-bit grayscale PNG.  Without `bounds` the raster's own
 * minimum and maximum define the scale (the decoded fraction is relative to them);
 * with `bounds` the caller fixes the scale, so a constant raster still decodes back
 * to its value and several rasters can share one scale.
 */
export async function elevationPng(raster: ElevationRaster, metadata: Record<string, unknown>,
  bounds?: { min: number; max: number }): Promise<Blob> {
  const { width, height, values } = raster
  checkDimensions(width, height)
  if (values.length !== width * height) throw new Error('Incomplete elevation raster')
  for (const value of values) {
    if (!Number.isFinite(value)) throw new Error('Cannot encode non-finite elevations as grayscale')
  }
  let min = bounds ? bounds.min : Infinity
  let max = bounds ? bounds.max : -Infinity
  if (!bounds) {
    for (const value of values) {
      min = Math.min(min, value)
      max = Math.max(max, value)
    }
  }
  if (!Number.isFinite(min) || !Number.isFinite(max) || max < min) throw new Error('Invalid elevation encoding range')
  const stride = width * 2 + 1
  const scanlines = new ArrayBuffer(height * stride)
  const samples = new DataView(scanlines)
  const range = max - min
  for (let row = 0; row < height; row++) {
    for (let col = 0; col < width; col++) {
      const value = values[row * width + col]
      const fraction = range ? Math.min(1, Math.max(0, (value - min) / range)) : 0.5
      samples.setUint16(row * stride + 1 + col * 2, Math.round(fraction * 65535))
    }
  }
  const header = new Uint8Array(13)
  const ihdr = new DataView(header.buffer)
  ihdr.setUint32(0, width)
  ihdr.setUint32(4, height)
  ihdr.setUint8(8, 16)
  const description = elevationDescription(raster, { ...metadata, encoding: 'linear_uint16', min_m: min, max_m: max })
  const text = new TextEncoder().encode(`Description\0${description}`)
  const compressed = new Blob([scanlines]).stream().pipeThrough(new CompressionStream('deflate'))
  const image = new Uint8Array(await new Response(compressed).arrayBuffer())
  return new Blob([new Uint8Array(PNG_SIGNATURE), pngChunk(0x49484452, header), pngChunk(0x74455874, text),
    pngChunk(0x49444154, image), pngChunk(0x49454e44, new Uint8Array(0))], { type: 'image/png' })
}

export function elevationTiff(raster: ElevationRaster, metadata: Record<string, unknown>): Blob {
  const description = new TextEncoder().encode(elevationDescription(raster, metadata))
  const tags = [
    [256, 4, 1, raster.width], [257, 4, 1, raster.height], [258, 3, 1, 32],
    [259, 3, 1, 1], [262, 3, 1, 1], [270, 2, description.length + 1, 0],
    [273, 4, 1, 0], [277, 3, 1, 1], [278, 4, 1, raster.height],
    [279, 4, 1, raster.values.byteLength], [339, 3, 1, 3],
  ]
  const descriptionOffset = 8 + 2 + tags.length * 12 + 4
  const pixelOffset = Math.ceil((descriptionOffset + description.length + 1) / 4) * 4
  const buffer = new ArrayBuffer(pixelOffset + raster.values.byteLength)
  const writer = new DataView(buffer)
  writer.setUint16(0, 0x4949, true)
  writer.setUint16(2, 42, true)
  writer.setUint32(4, 8, true)
  writer.setUint16(8, tags.length, true)
  tags.forEach(([tag, type, count, value], index) => {
    const offset = 10 + index * 12
    writer.setUint16(offset, tag, true)
    writer.setUint16(offset + 2, type, true)
    writer.setUint32(offset + 4, count, true)
    writer.setUint32(offset + 8, tag === 270 ? descriptionOffset : tag === 273 ? pixelOffset : value, true)
  })
  new Uint8Array(buffer, descriptionOffset, description.length).set(description)
  raster.values.forEach((value, index) => writer.setFloat32(pixelOffset + index * 4, value, true))
  return new Blob([buffer], { type: 'image/tiff' })
}
