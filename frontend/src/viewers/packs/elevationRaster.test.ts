import { describe, expect, it } from 'vitest'
import { elevationPng, elevationTiff, readElevationNpy, readElevationPng, resizeElevation, sampleGlobalElevation } from './elevationRaster'
import { kmToLonLat, lonLatToKm, type PackWindow } from './packCoords'

const window: PackWindow = { centerLat: 30, centerLon: -180, extentKmX: 550, extentKmY: 550,
  radiusKm: 6371, projection: 'azimuthal_equidistant' }

function chunk(kind: string, body: Uint8Array) {
  const output = new Uint8Array(12 + body.length)
  new DataView(output.buffer).setUint32(0, body.length)
  output.set(new TextEncoder().encode(kind), 4)
  output.set(body, 8)
  return output
}

describe('region elevation', () => {
  it('decodes grayscale16 without losing the low byte and reverses PNG filters', async () => {
    const header = new Uint8Array([0, 0, 0, 2, 0, 0, 0, 5, 16, 0, 0, 0, 0])
    const filtered = new Uint8Array([
      0, 0, 1, 0, 2,
      1, 0, 3, 0, 1,
      2, 0, 2, 0, 2,
      3, 0, 5, 0, 3,
      4, 0, 3, 0, 2,
    ])
    const compressed = new Uint8Array(await new Response(new Blob([filtered]).stream()
      .pipeThrough(new CompressionStream('deflate'))).arrayBuffer())
    const raster = await readElevationPng(new Blob([new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10]),
      chunk('IHDR', header), chunk('IDAT', compressed), chunk('IEND', new Uint8Array())]), -5, 65530)
    expect([raster.width, raster.height]).toEqual([2, 5])
    expect(Array.from(raster.values)).toEqual([-4, -3, -2, -1, 0, 1, 2, 4, 5, 7])
  })

  it('wraps longitude at the seam and keeps north at the top', () => {
    const source = { width: 4, height: 3, values: new Float32Array([0, 5, 10, 15, -30, -25, -20, -15, -60, -55, -50, -45]) }
    expect(sampleGlobalElevation(source, window, 1).values[0]).toBe(-20)
    const grid = sampleGlobalElevation(source, window, 3).values
    expect(grid[3]).toBeGreaterThan(grid[4])
    expect(grid[0]).toBeGreaterThan(grid[6])
  })

  it('writes 16-bit grayscale spanning the elevation range and records its decoding metadata', async () => {
    const values = new Float32Array([-2000, -1923.5, -1923.25, 0, 1234.5, 3000])
    const file = await elevationPng({ width: 3, height: 2, values }, { source: '海岸', sea_level_m: 0 })
    expect(file.type).toBe('image/png')
    const raw = new Uint8Array(await file.arrayBuffer())
    expect(raw.slice(24, 26)).toEqual(new Uint8Array([16, 0]))
    const head = new DataView(raw.buffer)
    const textOffset = 33
    expect(head.getUint32(textOffset + 4)).toBe(0x74455874)
    const text = new TextDecoder().decode(raw.subarray(textOffset + 8, textOffset + 8 + head.getUint32(textOffset)))
    const [keyword, description] = text.split('\0')
    expect(keyword).toBe('Description')
    const metadata = JSON.parse(description)
    expect(metadata).toMatchObject({ source: '海岸', sea_level_m: 0, encoding: 'linear_uint16', unit: 'm',
      min_m: -2000, max_m: 3000, width: 3, height: 2, registration: 'pixel_center_north_up' })
    const { values: grayscale } = await readElevationPng(file, 0, 65535)
    expect(grayscale[0]).toBe(0)
    expect(grayscale[5]).toBe(65535)
    expect(new Set(grayscale).size).toBe(values.length)
    const restored = await readElevationPng(file, metadata.min_m, metadata.max_m)
    restored.values.forEach((value, index) => expect(Math.abs(value - values[index])).toBeLessThan(5000 / 65535))
  })

  it('uses mid-gray for constant elevations and rejects non-finite PNG samples', async () => {
    const flat = { width: 2, height: 1, values: new Float32Array([-30, -30]) }
    const file = await elevationPng(flat, {})
    expect(Array.from((await readElevationPng(file, 0, 65535)).values)).toEqual([32768, 32768])
    expect(Array.from((await readElevationPng(file, -30, -30)).values)).toEqual([-30, -30])
    flat.values[1] = NaN
    await expect(elevationPng(flat, {})).rejects.toThrow('non-finite')
  })

  it('uses the same local projection at the pole and for reverse lookup', () => {
    const polar = { ...window, centerLat: 90 }
    const location = kmToLonLat(100, -200, polar)
    const back = lonLatToKm(location, polar)
    expect(location.lat).toBeLessThan(90)
    expect(back.x).toBeCloseTo(100, 8)
    expect(back.y).toBeCloseTo(-200, 8)
  })

  it('reads a native signed floating raster and writes metre values and metadata to TIFF', async () => {
    const header = new TextEncoder().encode("{'descr': '<f4', 'fortran_order': False, 'shape': (1, 2), }\n")
    const buffer = new ArrayBuffer(10 + header.length + 8)
    new Uint8Array(buffer).set([147, 78, 85, 77, 80, 89, 1, 0])
    const data = new DataView(buffer)
    data.setUint16(8, header.length, true)
    new Uint8Array(buffer, 10, header.length).set(header)
    data.setFloat32(10 + header.length, -512.25, true)
    data.setFloat32(14 + header.length, 47.125, true)
    const input = readElevationNpy(buffer)
    expect(Array.from(input.values)).toEqual([-512.25, 47.125])
    expect(resizeElevation(input, 1, 1).values[0]).toBe(-232.5625)
    const tiff = new DataView(await elevationTiff(input, { source: '海岸' }).arrayBuffer())
    const tags = new Map(Array.from({ length: tiff.getUint16(8, true) }, (_, index) => {
      const offset = 10 + index * 12
      return [tiff.getUint16(offset, true), tiff.getUint32(offset + 8, true)]
    }))
    expect(tags.get(339)).toBe(3)
    const samples = tags.get(273)!
    expect(tiff.getFloat32(samples, true)).toBe(-512.25)
    expect(tiff.getFloat32(samples + 4, true)).toBe(47.125)
    const metadata = new TextDecoder().decode(new Uint8Array(tiff.buffer, tags.get(270)!, samples - tags.get(270)!))
    expect(JSON.parse(metadata.split('\0')[0])).toMatchObject({ source: '海岸', unit: 'm', width: 2, height: 1 })
  })
})
