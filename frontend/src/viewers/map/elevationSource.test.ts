import { describe, expect, it } from 'vitest'
import { importedRasterSpacingKm, meshTextureDimensions, terrainSourceFor } from './elevationSource'
import { getLayerTextures } from './layerBakes'
import type { CVTMesh, MapMetadata } from './types'

const meta: MapMetadata = {
  planet_id: 'earth', projection: 'equirectangular', width: 4096, height: 2048,
  elevation_min_m: -100, elevation_max_m: 100, sea_level_m: 0,
  voronoi_seed: 42, voronoi_num_cells: 256,
  elevation_import: { source_resolution: [4096, 2048], output_resolution: [4096, 2048], was_resampled: false },
}

describe('global elevation sources', () => {
  it('defaults to the imported heightmap without changing native grid layers', () => {
    expect(terrainSourceFor(meta, true, true, null)).toBe('raster')
    expect(terrainSourceFor(meta, true, true, 'gray')).toBe('gray')
    expect(terrainSourceFor(meta, true, true, 'mesh')).toBe('mesh')
    expect(terrainSourceFor(meta, false, true, 'mesh')).toBe('raster')
    expect(terrainSourceFor(meta, true, false, null)).toBe('mesh')
    expect(meshTextureDimensions(meta)).toEqual({ width: 2048, height: 1024 })
  })

  it('prefers inherited ETOPO1 terrain without applying that default to replaced branch terrain', () => {
    const reference = { ...meta, planet_id: 'planet_earth', elevation_import: null, pipeline_version: 'etopo1-import' }
    expect(terrainSourceFor(reference, true, true, null)).toBe('raster')
    expect(terrainSourceFor(reference, true, true, 'gray')).toBe('gray')
    expect(terrainSourceFor(reference, true, true, 'mesh')).toBe('mesh')
    expect(terrainSourceFor(reference, true, false, 'gray')).toBe('mesh')
    expect(terrainSourceFor({ ...reference, pipeline_version: undefined }, true, true, null)).toBe('mesh')
    expect(terrainSourceFor({ ...reference, pipeline_version: 'generated' }, true, true, 'gray')).toBe('mesh')
  })

  it('estimates original row spacing only for a native-size imported raster', () => {
    expect(importedRasterSpacingKm(meta, 4096, 2048, 6371)).toBeCloseTo(9.773, 2)
    expect(importedRasterSpacingKm(meta, 2048, 1024, 6371)).toBeNull()
    expect(importedRasterSpacingKm({ ...meta, elevation_import: { ...meta.elevation_import!, was_resampled: true } },
      4096, 2048, 6371)).toBeNull()
    expect(importedRasterSpacingKm({ ...meta, elevation_import: null }, 4096, 2048, 6371)).toBeNull()
  })

  it('shows raster detail even when every display pixel maps to the same cell', () => {
    const cvtMesh = { cells: [{ id: 0, lon: 0, lat: 0, elevation: 100, neighbors: [] }] } as unknown as CVTMesh
    const input = { cvtMesh, cellIdMap: new Uint32Array(8), width: 8, height: 4, meshWidth: 4, meshHeight: 2,
      elevation: Float32Array.from({ length: 32 }, (_, index) => index % 2), seaLevel: 0,
      elevMinM: -100, elevMaxM: 100, waterDepthFactor: 1, flipHorizontal: false }
    const raster = getLayerTextures({ ...input, terrainSource: 'raster' }).terrainThematic.image
    expect([raster.width, raster.height]).toEqual([8, 4])
    expect(raster.data.slice(0, 4)).not.toEqual(raster.data.slice(4, 8))
    const gray = getLayerTextures({ ...input, terrainSource: 'gray' }).terrainThematic.image
    expect([...gray.data.slice(0, 8)]).toEqual([0, 0, 0, 255, 255, 255, 255, 255])
    const mesh = getLayerTextures({ ...input, terrainSource: 'mesh' }).terrainThematic.image
    expect([mesh.width, mesh.height]).toEqual([4, 2])
    expect(mesh.data.slice(0, 4)).toEqual(mesh.data.slice(4, 8))
  })
})
