import { describe, expect, it } from 'vitest'
import type { MonthlyClimateData } from '../../api/monthlyClimate'
import { EARTH_PARAMS, GRID_H, GRID_W } from '../../playground/temperatureDraft'
import type { VoronoiCell } from '../../viewers/map/types'
import { countSubzeroMonths, isMonthlyLayer, monthFromSearch, officialMonthlyMeans, trialLandTemperatureMeans } from './climateTime'

describe('monthly temperature chart', () => {
  it('counts only strictly subzero months in a complete finite year', () => {
    expect(countSubzeroMonths(12, month => month - 5)).toBe(5)
    expect(countSubzeroMonths(12, () => -2)).toBe(12)
    expect(countSubzeroMonths(12, () => 0)).toBe(0)
    expect(countSubzeroMonths(11, () => -2)).toBeNull()
    expect(countSubzeroMonths(12, month => month === 5 ? NaN : -2)).toBeNull()
  })

  it('uses official cell areas and ignores ocean cells and non-finite values', () => {
    const tMonthly = new Float32Array([...Array(12).fill(10), ...Array(12).fill(30), ...Array(12).fill(-50)])
    tMonthly[1] = NaN
    const data = { months: 12, numCells: 3, tMonthly } as MonthlyClimateData
    const cells = [
      { water_class: 'land', area_km2: 1 },
      { water_class: 'land', area_km2: 3 },
      { water_class: 'ocean', area_km2: 10 },
    ] as VoronoiCell[]
    expect(officialMonthlyMeans('temperature', data, cells)?.slice(0, 3)).toEqual([25, 30, 25])
    expect(officialMonthlyMeans('temperature', data, cells.slice(0, 1))).toBeUndefined()
  })

  it('reads the selected field and does not fall back to temperature for missing fields', () => {
    const data = { months: 12, numCells: 1, tMonthly: new Float32Array(12).fill(26),
      pMonthly: new Float32Array(12).fill(143), windEastMonthly: new Float32Array(12).fill(3),
      windNorthMonthly: new Float32Array(12).fill(4) } as MonthlyClimateData
    const cells = [{ water_class: 'land' }] as VoronoiCell[]
    expect(officialMonthlyMeans('precipitation', data, cells)?.[0]).toBe(143)
    expect(officialMonthlyMeans('winds', data, cells)?.[0]).toBe(5)
    expect(officialMonthlyMeans('slp', data, cells)).toBeUndefined()
    expect(isMonthlyLayer('terrain')).toBe(false)
  })

  it('keeps data month independent of the lighting season and opens older monthly URLs', () => {
    expect(monthFromSearch(new URLSearchParams('monthly=1&month=10&season=180'))).toBe(10)
    expect(monthFromSearch(new URLSearchParams('monthly=1&season=180'))).toBe(6)
    expect(monthFromSearch(new URLSearchParams('season=180'))).toBe(0)
  })

  it('uses the trial sea level and latitude-area weighting', () => {
    const elevation = new Float32Array(GRID_H * GRID_W)
    const field = Array<number>(elevation.length).fill(200)
    const equator = Math.floor(GRID_H / 2) * GRID_W
    elevation[0] = 1
    elevation[equator] = 1
    field[0] = 0
    field[equator] = 20
    const [mean] = trialLandTemperatureMeans([field], { elevation, params: EARTH_PARAMS })
    expect(mean).toBeGreaterThan(19)
    expect(mean).toBeLessThan(20)
    expect(trialLandTemperatureMeans([field], { elevation, params: { ...EARTH_PARAMS, seaLevelM: EARTH_PARAMS.elevMaxM } })[0])
      .toBeNaN()
  })
})
