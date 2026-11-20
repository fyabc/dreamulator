import { describe, expect, it } from 'vitest'
import { blendTerrain } from './terrainBlend'
import type { ElevationRaster } from './elevationRaster'

const checkpoint = async () => {}

function raster(width: number, height: number, heightAt: (row: number, col: number) => number): ElevationRaster {
  return { width, height, values: Float32Array.from({ length: width * height }, (_, index) => heightAt(Math.floor(index / width), index % width)) }
}

describe('source-preserving terrain blend', () => {
  it.each([
    { width: 8, height: 8, expected: [27.02933, 28.92035, 30.96444] },
    { width: 7, height: 5, expected: [26.99667, 27.96165, 28.97021] },
  ])('matches the CLI cosine blend on a $width by $height grid', async ({ width, height, expected }) => {
    const source = raster(width, height, (row, col) => col < 2 ? -16 - row : 20 + 2 * row + col)
    const donor = raster(width, height, (row, col) => source.values[row * width + col] + 2 * row - col +
      8 * Math.cos(2 * Math.PI * (col + 0.5) / width) * Math.cos(3 * Math.PI * (row + 0.5) / height))
    const result = await blendTerrain(source, donor, 1, 4.5, 0, checkpoint)
    for (let row = 1; row <= expected.length; row++) expect(result.values[row * width + 4 + (width === 8 ? 1 : 0)]).toBeCloseTo(expected[row - 1], 4)
    expect(result.values.slice(0, width)).toEqual(source.values.slice(0, width))
    expect(result.values[width + 1]).toBe(source.values[width + 1])
    expect(result.values[2 * width + 2]).toBe(source.values[2 * width + 2])
  })

  it('rejects coarse donor variation while retaining short waves around the interior', async () => {
    const size = 32
    const source = raster(size, size, () => 50)
    const donor = raster(size, size, (_, col) => 80 + 80 * Math.cos(Math.PI * (col + 0.5) / size) +
      8 * Math.cos(20 * Math.PI * (col + 0.5) / size))
    const result = await blendTerrain(source, donor, 1, 8, 0, checkpoint)
    expect(result.values[16 * size + 16]).toBeCloseTo(50 + 8 * Math.cos(20 * Math.PI * 16.5 / size), 4)
    expect(source.values.every((value) => value === 50)).toBe(true)
  })

  it('does not turn land into water or overwrite the source seabed', async () => {
    const source = raster(16, 16, (_, col) => col < 4 ? -10 : 1)
    const donor = raster(16, 16, (_, col) => col % 2 ? 1000 : -1000)
    const result = await blendTerrain(source, donor, 1, 4, 0, checkpoint)
    expect(result.values.every((value, index) => source.values[index] <= 0 ? value === -10 : value > 0)).toBe(true)
    expect(result.values[8 * 16 + 9]).toBeGreaterThan(1)
  })
})
