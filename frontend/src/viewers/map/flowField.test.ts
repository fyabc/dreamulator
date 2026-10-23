import { describe, expect, it } from 'vitest'

import {
  EARTH_RADIUS_M,
  advectParticle,
  buildFlowField,
  sampleCellId,
  sampleFlow,
  wrapLongitude,
  type AdvectResult,
  type FlowField,
  type FlowSample,
} from './flowField'
import type { VoronoiCell } from './types'

function cell(
  lon: number,
  lat: number,
  fields: Partial<VoronoiCell> = {},
): VoronoiCell {
  return {
    id: 0,
    lon,
    lat,
    elevation: 0,
    moisture: 0,
    neighbors: [],
    plate_id: null,
    biome: null,
    province_id: null,
    area_km2: 1,
    ...fields,
  }
}

/** A uniformly valid field — avoids depending on the binning for advection tests. */
function uniformField(u: number, v: number, n = 180 * 90): FlowField {
  const uArr = new Float32Array(n)
  const vArr = new Float32Array(n)
  const valid = new Uint8Array(n)
  uArr.fill(u)
  vArr.fill(v)
  valid.fill(1)
  return {
    kind: 'wind',
    stepDeg: 2,
    nLon: 180,
    nLat: 90,
    u: uArr,
    v: vArr,
    aux: new Float32Array(n),
    valid,
    maxSpeed: Math.hypot(u, v),
  }
}

describe('buildFlowField', () => {
  it('bins annual and monthly wind into the same grid', () => {
    const cells = [cell(0, 0, { wind_east_m_s: 10, wind_north_m_s: 0 })]
    const annual = buildFlowField({ kind: 'wind', cells })
    // lon 0, lat 0 → bin (90, 45) at a 2° step.
    const k = 45 * annual.nLon + 90
    expect(annual.u[k]).toBeCloseTo(10)
    expect(annual.v[k]).toBeCloseTo(0)
    expect(annual.maxSpeed).toBeCloseTo(10)

    const monthlyEast = new Float32Array(12)
    const monthlyNorth = new Float32Array(12)
    monthlyEast[3] = 20
    const monthly = buildFlowField({
      kind: 'wind',
      cells,
      monthlyWindEast: monthlyEast,
      monthlyWindNorth: monthlyNorth,
      month: 3,
    })
    expect(monthly.u[k]).toBeCloseTo(20)
  })

  it('keeps the ocean-current field masked on land', () => {
    const ocean = cell(0, 0, {
      ocean_current_east_m_s: 0.1,
      ocean_current_north_m_s: 0,
      sst_anomaly_c: 2,
    })
    const land = cell(40, 40)
    const field = buildFlowField({ kind: 'current', cells: [ocean, land] })

    const seaSample: FlowSample = { u: 0, v: 0, aux: 0, valid: false }
    expect(sampleFlow(field, 0, 0, seaSample)).toBe(true)
    expect(seaSample.u).toBeCloseTo(0.1)
    expect(seaSample.aux).toBeCloseTo(2)

    const landSample: FlowSample = { u: 0, v: 0, aux: 0, valid: false }
    expect(sampleFlow(field, 40, 40, landSample)).toBe(false)
  })
})

describe('advectParticle', () => {
  it('moves eastward at the physical m/s → degrees rate', () => {
    const field = uniformField(10, 0)
    const out: AdvectResult = { lon: 0, lat: 0, speed: 0, aux: 0 }
    expect(advectParticle(field, 0, 0, EARTH_RADIUS_M, 86400, out)).toBe(true)
    // 10 m/s for one day at the equator = 864 km ≈ 7.77° of longitude.
    expect(out.lon).toBeCloseTo(7.77, 1)
    expect(out.lat).toBeCloseTo(0, 3)
  })

  it('wraps across the date line', () => {
    const field = uniformField(10, 0)
    const out: AdvectResult = { lon: 0, lat: 0, speed: 0, aux: 0 }
    expect(advectParticle(field, 179.5, 0, EARTH_RADIUS_M, 86400, out)).toBe(true)
    expect(out.lon).toBeGreaterThanOrEqual(-180)
    expect(out.lon).toBeLessThan(-170)
  })

  it('reflects a particle that crosses the pole', () => {
    const field = uniformField(0, 100)
    const out: AdvectResult = { lon: 0, lat: 0, speed: 0, aux: 0 }
    // 100 m/s for 0.9 day moves ~81° north from 20°N, crossing the pole.
    expect(advectParticle(field, 0, 20, EARTH_RADIUS_M, 90_000, out)).toBe(true)
    expect(out.lat).toBeLessThan(85)
    expect(out.lat).toBeGreaterThan(70)
    expect(Math.abs(wrapLongitude(out.lon))).toBeGreaterThan(170)
  })
})

describe('sampleCellId', () => {
  it('maps lon/lat to the nearest raster pixel and wraps the date line', () => {
    // 4 × 2 raster: x = round((lon+180)/360 × 3), y = round((90-lat)/180 × 1).
    const map = new Uint32Array([
      10, 11, 12, 13,
      20, 21, 22, 23,
    ])
    expect(sampleCellId(map, 4, 2, -180, 90)).toBe(10)
    expect(sampleCellId(map, 4, 2, 180, 90)).toBe(10) // wraps to -180
    expect(sampleCellId(map, 4, 2, 0, 90)).toBe(12)
    expect(sampleCellId(map, 4, 2, 0, -90)).toBe(22)
    expect(sampleCellId(null, 4, 2, 0, 0)).toBe(-1)
  })

  it('treats the 0xFFFFFFFF sentinel as no cell', () => {
    const map = new Uint32Array([0xffffffff, 0xffffffff, 0xffffffff, 0xffffffff])
    expect(sampleCellId(map, 2, 2, 0, 0)).toBe(-1)
  })
})

describe('wrapLongitude', () => {
  it('normalises into [-180, 180)', () => {
    expect(wrapLongitude(181)).toBeCloseTo(-179)
    expect(wrapLongitude(-181)).toBeCloseTo(179)
    expect(wrapLongitude(540)).toBeCloseTo(-180)
  })
})
