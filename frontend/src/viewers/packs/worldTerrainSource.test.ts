import { encode } from '@msgpack/msgpack'
import { describe, expect, it } from 'vitest'
import { decodeWorldTerrainSource, prepareWorldTerrainSource } from './worldTerrainSource'

const bytes = (value: unknown) => Uint8Array.from(encode(value)).buffer
const field = (...values: number[]) => new Uint8Array(Float64Array.from(values).buffer)
const packet = { version: 1, cells: 2, positions: field(1, 0, 0, -1, 0, 0), native: null, fields: {
  elevation_m: field(100, 500), temperature_mean_c: field(10, 30), temperature_std_c: field(1, 2),
  precipitation_total_mm: field(1000, 500), precipitation_cv_pct: field(20, 40),
} }
const window = { centerLat: 0, centerLon: 0, radiusKm: 6371, extentKmX: 46, extentKmY: 46,
  projection: 'azimuthal_equidistant' as const }

describe('scientific TD assets', () => {
  it('distinguishes missing climate from truncated or invalid fields', () => {
    expect(decodeWorldTerrainSource(bytes(null))).toBeNull()
    expect(() => decodeWorldTerrainSource(bytes({ ...packet, positions: field(1, 2) }))).toThrow('length')
    expect(() => decodeWorldTerrainSource(bytes({ ...packet, fields: { ...packet.fields, precipitation_cv_pct: field(-1, 0) } }))).toThrow('value')
  })

  it('samples the selected CVT cell and corrects native elevation before conditioning', () => {
    const meshOnly = prepareWorldTerrainSource(decodeWorldTerrainSource(bytes(packet))!, window, null)
    const native = prepareWorldTerrainSource(decodeWorldTerrainSource(bytes({ ...packet, native: 'a'.repeat(64) }))!,
      window, { width: 2, height: 1, values: Float64Array.of(350, 350) })
    expect(meshOnly.elevation.values).toEqual(Float32Array.of(100, 100, 100, 100))
    expect(native.elevation.values).toEqual(Float32Array.of(350, 350, 350, 350))
    expect(native.climate).toEqual(meshOnly.climate)
    expect(native.climate?.temperature_mean_c[0]).toBe(10.5)
    expect(native.climate?.precipitation_total_mm[0]).toBe(1000)
  })
})
