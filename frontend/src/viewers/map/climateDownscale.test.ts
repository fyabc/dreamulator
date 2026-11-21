import { describe, expect, it } from 'vitest'
import { canDownscale, climateRasterPixels, downscaledClimatePixels, temperatureLapseCPerM } from './climateDownscale'
import type { VoronoiCell } from './types'
import { temperatureColor } from './utils/colorScales'

describe('climate display downscaling', () => {
  it('interpolates values before coloring and wraps longitude across the antimeridian', () => {
    const pixels = climateRasterPixels({ width: 2, height: 1, values: new Float32Array([0, 40]) }, 4, 1, value => [value, 0, 0])
    expect([pixels[0], pixels[4], pixels[8], pixels[12]]).toEqual([10, 10, 30, 30])
  })

  it('does not invent data at a wholly missing grid point or paint masked ocean', () => {
    const grid = { width: 2, height: 1, values: new Float32Array([NaN, 1]) }
    const pixels = climateRasterPixels(grid, 2, 1, value => [value, 0, 0], column => column === 0 ? 10 : NaN)
    expect([pixels[3], pixels[7]]).toEqual([0, 0])
    expect(canDownscale('koppen')).toBe(false)
  })

  it('corrects temperature for the imported land elevation with the canvas lapse convention', () => {
    const cells = [{ id: 7, temperature_C: 20, elevation: 500, precipitation_mm: 1000, water_class: 'land' }] as VoronoiCell[]
    const pixels = downscaledClimatePixels('temperature', cells, new Uint32Array(2).fill(7), 2, 1, 2, 1, 0,
      { elevation: new Float32Array([0.75, 0]), width: 2, height: 1, minM: 0, maxM: 2000, seaLevelM: 0 }, null, null)
    expect(temperatureLapseCPerM(1000)).toBe(-0.005)
    expect(Array.from(pixels ?? [])).toEqual([...temperatureColor(15), 255, 0, 0, 0, 0])
  })
})
