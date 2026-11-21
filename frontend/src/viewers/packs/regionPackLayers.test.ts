import { describe, expect, it } from 'vitest'
import { pxToLonLat, type PackWindow } from './packCoords'
import { indexRegionRivers, regionConditionSources, regionFieldAt, regionFieldLabel, regionFieldSource } from './regionPackLayers'
import type { PackMeta } from './types'

describe('regional conditioning', () => {
  const pack = { height_source: 'refined-out', condition_layers: {
    source: ['temperature_mean_c', 'runoff'], grid: ['temperature_mean_c', 'elevation_m'],
  } } as unknown as PackMeta
  const window: PackWindow = { centerLat: 24.1, centerLon: 121.45, extentKmX: 150, extentKmY: 150, radiusKm: 6371, projection: 'azimuthal_equidistant' }

  it('only offers recorded fields and does not mistake source temperature for sea-level temperature', () => {
    expect(regionConditionSources(null)).toEqual([])
    expect(regionConditionSources(pack)).toEqual(['source', 'grid'])
    expect(regionFieldSource(pack, 'terrain', 'source')).toBeUndefined()
    expect(regionFieldSource(pack, 'terrain', 'grid')).toBe('grid')
    expect(regionFieldSource(pack, 'temperature', 'source')).toBe('source')
    expect(regionFieldSource(pack, 'temperature', 'grid')).toBe('grid')
    expect(regionFieldSource(pack, 'precipitation', 'grid')).toBeUndefined()
    expect(regionFieldLabel('temperature', 'source')).toBe('packs.conditions.surfaceTemperature')
    expect(regionFieldLabel('temperature', 'grid')).toBe('packs.conditions.temperature')
  })

  it('keeps runoff independent of the TD source selector', () => {
    expect(regionFieldSource(pack, 'runoff', 'grid')).toBe('source')
    expect(regionFieldSource(pack, 'runoff', 'source')).toBe('source')
    expect(regionConditionSources({ ...pack, condition_layers: { source: ['runoff'], grid: [] } })).toEqual([])
  })

  it('samples only nearby river endpoints, including across index bucket boundaries', () => {
    const lookup = indexRegionRivers({ segs: [[[0, 2.1], [0, 3]], [[-2, -1], [-2.2, -1]]],
      flows: [42, 14], regimes: [0, 1], flowMax: 42 })
    expect(lookup({ x: 1.9, y: 0 })).toEqual({ flow: 42, regime: 0 })
    expect(lookup({ x: -1, y: -2 })).toEqual({ flow: 14, regime: 1 })
    expect(lookup({ x: 6, y: 2 })).toBeUndefined()
  })

  it('reads the displayed pixel without interpolating or borrowing outside values', () => {
    const raster = { width: 2, height: 2, values: Float32Array.of(12, 21, NaN, 30) }
    expect(regionFieldAt(pxToLonLat(1, 0, 2, 2, window), window, raster)).toEqual({ row: 0, col: 1, value: 21 })
    expect(regionFieldAt(pxToLonLat(0, 1, 2, 2, window), window, raster)).toBeUndefined()
    expect(regionFieldAt(pxToLonLat(2, 1, 2, 2, window), window, raster)).toBeUndefined()
  })
})
