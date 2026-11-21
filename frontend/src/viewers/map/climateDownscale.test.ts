import { describe, expect, it } from 'vitest'
import { canDownscale, climateRasterPixels, downscaledClimatePixels, temperatureLapseCPerM } from './climateDownscale'
import type { VoronoiCell } from './types'
import { scalarColor, scalarScale } from './scalarLayers'
import { temperatureColor } from './utils/colorScales'

describe('climate display downscaling', () => {
  it('interpolates values before coloring and wraps longitude across the antimeridian', () => {
    const pixels = climateRasterPixels({ width: 2, height: 1, values: new Float32Array([0, 40]) }, 4, 1, value => [value, 0, 0])
    expect([pixels[0], pixels[4], pixels[8], pixels[12]]).toEqual([10, 10, 30, 30])
  })

  it('does not invent data at a wholly missing or explicitly masked point', () => {
    const grid = { width: 2, height: 1, values: new Float32Array([NaN, 1]) }
    const pixels = climateRasterPixels(grid, 2, 1, value => [value, 0, 0], column => column === 0 ? 10 : NaN)
    expect([pixels[3], pixels[7]]).toEqual([0, 0])
    expect(canDownscale('koppen')).toBe(false)
  })

  it('corrects temperature over imported land without treating ocean depth as altitude', () => {
    const cells = [{ id: 7, temperature_C: 20, elevation: 500, precipitation_mm: 1000, water_class: 'land' }] as VoronoiCell[]
    const pixels = downscaledClimatePixels('temperature', cells, new Uint32Array(2).fill(7), 2, 1, 2, 1, 0,
      { elevation: new Float32Array([0.75, 0]), width: 2, height: 1, minM: -2000, maxM: 2000, seaLevelM: 0 }, null, null)
    expect(temperatureLapseCPerM(1000)).toBe(-0.005)
    expect(Array.from(pixels ?? [])).toEqual([...temperatureColor(17.5), 255, ...temperatureColor(20), 255])
  })

  it('paints valid annual and monthly ocean precipitation, not missing values', () => {
    const cells = [{ id: 7, precipitation_mm: 1200, elevation: -500, water_class: 'ocean' }] as VoronoiCell[]
    const data = { numCells: 1, months: 2, tMonthly: new Float32Array([12, 13]), pMonthly: new Float32Array([100, NaN]),
      temperatureRangeC: [12, 13] as [number, number], precipitationRangeMm: [0, 100] as [number, number] }
    const render = (month: number | null) => downscaledClimatePixels('precipitation', cells, new Uint32Array([7]), 1, 1, 1, 1, 0, null, data, month)
    expect(render(null)?.[3]).toBe(255)
    expect(render(0)?.[3]).toBe(255)
    expect(render(1)).toBeNull()
  })

  it('downscales NPP and scores without spilling land values into the ocean or missing cells', () => {
    const cells = [
      { id: 1, npp_gc_m2_yr: 400, agriculture_score: 0, habitability_score: 20, elevation: 500, water_class: 'land' },
      { id: 2, npp_gc_m2_yr: 800, agriculture_score: 80, habitability_score: 90, elevation: 330, water_class: 'land' },
      { id: 3, npp_gc_m2_yr: 9000, elevation: -500, water_class: 'ocean' },
      { id: 4, elevation: 100, water_class: 'land' },
    ] as VoronoiCell[]
    const cellIds = new Uint32Array([1, 2, 3, 4])
    for (const layer of ['npp', 'agriculture', 'habitable'] as const) {
      expect(canDownscale(layer)).toBe(true)
      const result = downscaledClimatePixels(layer, cells, cellIds, 4, 1, 8, 1, 0, null, null, null)
      expect([result?.[3], result?.[7], result?.[11], result?.[15]]).toEqual([255, 255, 255, 255])
      expect(result?.slice(16)).toEqual(new Uint8Array(16))
      const native = { elevation: new Float32Array([0, 1, 1, 1]), width: 4, height: 1, minM: -1000, maxM: 1000, seaLevelM: 0 }
      expect(downscaledClimatePixels(layer, cells, cellIds, 4, 1, 4, 1, 0, native, null, null)?.[3]).toBe(0)
    }
    const npp = scalarScale('npp', false, cells)
    expect(npp.max).toBe(800)
    expect(npp.unit).toBe('gC/m²/yr')
    expect(scalarColor(scalarScale('temperature', true), 30)).toEqual(temperatureColor(30))
  })

  it('preserves the unreliable-pressure mask and does not invent an annual pressure deviation', () => {
    const cells = [
      { id: 1, slp_annual_hpa: 1040, slp_reduction_unreliable: true },
      { id: 2, slp_annual_hpa: 1003, pressure_anomaly_annual_hpa: 2 },
    ] as VoronoiCell[]
    const cellIds = new Uint32Array([1, 2])
    const slp = downscaledClimatePixels('slp', cells, cellIds, 2, 1, 2, 1, 0, null, null, null)
    expect([slp?.[3], slp?.[7]]).toEqual([0, 255])
    expect(downscaledClimatePixels('pressureError', cells, cellIds, 2, 1, 2, 1, 0, null, null, null)).toBeNull()
  })
})
