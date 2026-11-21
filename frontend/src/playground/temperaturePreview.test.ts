import { describe, expect, it } from 'vitest'
import { GRID_H, GRID_W } from './temperatureDraft'
import { sampleTemperature, summarizeTemperature, temperaturePreviewPixels } from './temperaturePreview'
import { temperatureColor } from '../viewers/map/utils/colorScales'

describe('temperature trial texture', () => {
  it('uses the official temperature scale and clips extremes', () => {
    expect(temperatureColor(-130)).toEqual([33, 102, 172])
    expect(temperatureColor(0)).toEqual([255, 255, 255])
    expect(temperatureColor(100)).toEqual([103, 0, 31])
  })

  it('uploads southern rows first and keeps longitude in west-to-east order', () => {
    const field = Array<number>(GRID_W * GRID_H).fill(0)
    field[0] = -40
    field[GRID_W - 1] = -20
    field[(GRID_H - 1) * GRID_W] = 20
    field[field.length - 1] = 40
    field[1] = NaN
    const pixels = temperaturePreviewPixels(field)
    const pixel = (index: number) => Array.from(pixels.slice(index * 4, index * 4 + 4))
    expect(pixel(0)).toEqual([...temperatureColor(20), 255])
    expect(pixel(GRID_W - 1)).toEqual([...temperatureColor(40), 255])
    expect(pixel((GRID_H - 1) * GRID_W)).toEqual([...temperatureColor(-40), 255])
    expect(pixel((GRID_H - 1) * GRID_W + 1)).toEqual([0, 0, 0, 0])
    expect(pixel(field.length - 1)).toEqual([...temperatureColor(-20), 255])
  })
})

describe('temperature trial inspection', () => {
  it('samples the north-first grid, wraps the date line and clamps the poles', () => {
    const field = Array.from({ length: GRID_W * GRID_H }, (_, index) => index)
    expect(sampleTemperature(field, { lon: -179, lat: 89 })).toBe(0)
    expect(sampleTemperature(field, { lon: 179, lat: -90 })).toBe(field.length - 1)
    expect(sampleTemperature(field, { lon: 180, lat: 90 })).toBe(0)
    expect(sampleTemperature(field, { lon: -181, lat: 89 })).toBe(GRID_W - 1)
    expect(sampleTemperature(field, { lon: 1, lat: -1 })).toBe(45 * GRID_W + 90)
  })

  it('weights the global grid by latitude band area but uses an unweighted mean for selected samples', () => {
    const field = [0, 0, 40, 40, 0, 0]
    expect(summarizeTemperature(field, 2)).toMatchObject({ min: 0, max: 40 })
    expect(summarizeTemperature(field, 2)?.mean).toBeCloseTo(20)
    expect(summarizeTemperature(field)?.mean).toBeCloseTo(40 / 3)
    expect(summarizeTemperature([])).toBeNull()
  })
})
