import { describe, expect, it } from 'vitest'
import { GRID_H, GRID_W } from './temperatureDraft'
import { temperatureColor, temperaturePreviewPixels } from './temperaturePreview'

describe('temperature trial texture', () => {
  it('keeps the same scale as the climate lab and clips extremes', () => {
    expect(temperatureColor(-130)).toEqual([49, 54, 149])
    expect(temperatureColor(0)).toEqual([255, 255, 191])
    expect(temperatureColor(10)).toEqual([254, 215, 144])
    expect(temperatureColor(100)).toEqual([165, 0, 38])
  })

  it('uploads southern rows first and keeps longitude in west-to-east order', () => {
    const field = Array<number>(GRID_W * GRID_H).fill(0)
    field[0] = -40
    field[GRID_W - 1] = -20
    field[(GRID_H - 1) * GRID_W] = 20
    field[field.length - 1] = 40
    const pixels = temperaturePreviewPixels(field)
    const pixel = (index: number) => Array.from(pixels.slice(index * 4, index * 4 + 4))
    expect(pixel(0)).toEqual([...temperatureColor(20), 255])
    expect(pixel(GRID_W - 1)).toEqual([...temperatureColor(40), 255])
    expect(pixel((GRID_H - 1) * GRID_W)).toEqual([...temperatureColor(-40), 255])
    expect(pixel(field.length - 1)).toEqual([...temperatureColor(-20), 255])
  })
})
