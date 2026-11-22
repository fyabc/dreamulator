import { describe, expect, it } from 'vitest'
import { prepareTerrainConditions } from './terrainConditions'

describe('portable TD grid', () => {
  const elevation = { width: 2, height: 2, values: Float32Array.of(-100, 1000, 2000, 3000) }
  const climate = {
    temperature_mean_c: Float32Array.of(10, 20, 30, 40),
    temperature_std_c: Float32Array.of(1, 2, 3, 4),
    precipitation_total_mm: Float32Array.of(0, 1000, 2000, 3000),
    precipitation_cv_pct: Float32Array.of(10, 20, 30, 40),
  }

  it('matches the local TD driver: convert temperature before resampling and preserve source endpoints', () => {
    const grid = prepareTerrainConditions(elevation, 69, climate)
    expect(grid.version).toBe('region-td-grid-v1')
    expect(grid.elevation.values).toEqual(Float32Array.of(-100, 450, 1000, 950, 1475, 2000, 2000, 2500, 3000))
    expect(grid.climate).toEqual({
      temperature_mean_c: Float32Array.of(10, 17.5, 25, 24, 31.25, 38.5, 38, 45, 52),
      temperature_std_c: Float32Array.of(1, 1.5, 2, 2, 2.5, 3, 3, 3.5, 4),
      precipitation_total_mm: Float32Array.of(0, 500, 1000, 1000, 1500, 2000, 2000, 2500, 3000),
      precipitation_cv_pct: Float32Array.of(10, 15, 20, 20, 25, 30, 30, 35, 40),
    })
    expect(climate.temperature_mean_c).toEqual(Float32Array.of(10, 20, 30, 40))
  })

  it('omits entirely missing climate but rejects incomplete, invalid or misregistered channels', () => {
    expect(prepareTerrainConditions(elevation, 69)).not.toHaveProperty('climate')
    for (const badField of [Float32Array.of(0), Float32Array.of(1, 2, 3, NaN), Float32Array.of(1, 2, 3, -1)]) {
      expect(() => prepareTerrainConditions(elevation, 69, { ...climate, temperature_std_c: badField })).toThrow('Invalid TD source climate')
    }
  })
})
