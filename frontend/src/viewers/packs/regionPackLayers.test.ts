import { describe, expect, it } from 'vitest'
import { pxToLonLat, type PackWindow } from './packCoords'
import { regionFieldAt, regionFieldLabel, regionRasterSource, regionRasterSources } from './regionPackLayers'
import type { PackMeta } from './types'

describe('regional conditioning', () => {
  const pack = { height_source: 'refined-out', condition_layers: { source: ['temperature_mean_c', 'runoff'], grid: [] } } as unknown as PackMeta
  const window: PackWindow = { centerLat: 24.1, centerLon: 121.45, extentKmX: 150, extentKmY: 150, radiusKm: 6371, projection: 'azimuthal_equidistant' }

  it('only offers recorded fields and does not mistake source temperature for sea-level temperature', () => {
    expect(regionRasterSources(null, 'terrain')).toEqual([])
    expect(regionRasterSources(pack, 'terrain')).toEqual(['map'])
    expect(regionRasterSources(pack, 'temperature')).toEqual(['source'])
    expect(regionRasterSources(pack, 'precipitation')).toEqual([])
    expect(regionRasterSources(pack, 'runoff')).toEqual(['source'])
    expect(regionFieldLabel('temperature', 'source')).toBe('packs.conditions.surfaceTemperature')
    expect(regionFieldLabel('temperature', 'grid')).toBe('packs.conditions.temperature')
  })

  it('defaults to adopted elevation or the real TD grid, and respects valid user choices', () => {
    expect(regionRasterSource(['map', 'source', 'grid'])).toBe('map')
    expect(regionRasterSource(['source', 'grid'])).toBe('grid')
    expect(regionRasterSource(['source', 'grid'], 'source')).toBe('source')
    expect(regionRasterSource(['source'], 'grid')).toBe('source')
  })

  it('reads the displayed pixel without interpolating or borrowing outside values', () => {
    const raster = { width: 2, height: 2, values: Float32Array.of(12, 21, NaN, 30) }
    expect(regionFieldAt(pxToLonLat(1, 0, 2, 2, window), window, raster)).toEqual({ row: 0, col: 1, value: 21 })
    expect(regionFieldAt(pxToLonLat(0, 1, 2, 2, window), window, raster)).toBeUndefined()
    expect(regionFieldAt(pxToLonLat(2, 1, 2, 2, window), window, raster)).toBeUndefined()
  })
})
