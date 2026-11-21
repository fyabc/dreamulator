import { describe, expect, it } from 'vitest'
import { regionContextWindow, type PackWindow } from './packCoords'
import { projectedRegionGraticule } from './regionGraticule'

const inner: PackWindow = { centerLat: 0, centerLon: 0, extentKmX: 150, extentKmY: 150,
  radiusKm: 6371, projection: 'azimuthal_equidistant' }

describe('regional contextual layers', () => {
  it('draws continuous geographic lines across both sides of the refinement frame at the dateline', () => {
    const context = regionContextWindow({ ...inner, centerLon: 179.8 })!
    const lines = projectedRegionGraticule(context)
    const equator = lines.find(line => line.latitude && line.coordinate === 0)
    expect(equator?.paths).toHaveLength(1)
    expect(Math.min(...equator!.paths[0].map(([x]) => x))).toBeCloseTo(-context.extentKmX / 2)
    expect(Math.max(...equator!.paths[0].map(([x]) => x))).toBeCloseTo(context.extentKmX / 2)
    expect(lines.some(line => !line.latitude && line.coordinate < -179)).toBe(true)
    for (const [x, y] of lines.flatMap(line => line.paths.flat())) {
      expect(Math.abs(x)).toBeLessThanOrEqual(context.extentKmX / 2 + 1e-6)
      expect(Math.abs(y)).toBeLessThanOrEqual(context.extentKmY / 2 + 1e-6)
    }
  })
})
