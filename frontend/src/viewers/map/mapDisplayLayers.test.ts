import { describe, expect, it } from 'vitest'
import { availableTrialLayers, availableWorldLayers } from './useMapDisplayLayers'
import { trialTerrainCell } from './trialInspection'
import type { CVTMesh, VoronoiCell } from './types'

const cell: VoronoiCell = {
  id: 18, lon: 120, lat: 24, elevation: 640, neighbors: [], area_km2: 780,
  moisture: 0, plate_id: 'plate_1', biome: null, province_id: null,
  temperature_C: 0, precipitation_mm: 1000, domesticable_tags: [],
}
const mesh: CVTMesh = { seed: 1, num_cells: 1, cells: [cell], vertices: [], regions: [] }

describe('map data availability', () => {
  it('exposes available climate layers even when a later layer is absent', () => {
    const layers = availableWorldLayers(mesh, null, false)
    expect(layers).toContain('temperature')
    expect(layers).toContain('precipitation')
    expect(layers).not.toContain('biomes')
    expect(layers).not.toContain('domesticable')
    expect(layers).not.toContain('pressureError')
  })

  it('only enables trial temperature after a result exists', () => {
    expect(availableTrialLayers(false)).not.toContain('temperature')
    expect(availableTrialLayers(true)).toContain('temperature')
    expect(availableTrialLayers(true)).not.toContain('precipitation')
    expect(availableTrialLayers(true)).not.toContain('biomes')
  })

  it('keeps the inspection geometry without copying any official result', () => {
    const terrain = trialTerrainCell(cell)
    expect(terrain).toMatchObject({ id: cell.id, lon: cell.lon, lat: cell.lat, elevation: cell.elevation, area_km2: cell.area_km2 })
    expect(terrain.plate_id).toBeUndefined()
    expect(terrain.moisture).toBeUndefined()
    expect(terrain.temperature_C).toBeUndefined()
    expect(terrain.precipitation_mm).toBeUndefined()
    expect(terrain.domesticable_tags).toBeUndefined()
  })
})
