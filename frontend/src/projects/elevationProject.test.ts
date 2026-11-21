import { describe, expect, it } from 'vitest'
import { exportProject, importProject, makeElevationResult, makeElevationSource, openProjectRaster, projectBytes } from './elevationProject'
import { removeProjectLayer } from './projectStore'
import { exportWorldData, importWorldData } from './worldDataArchive'
import { EARTH_PARAMS, GRID_H, GRID_W, readTemperatureGrid } from '../playground/temperatureDraft'
import type { SavedBrowserEbm } from '../api/climateTrials'

function exampleProject() {
  const raster = { width: 2, height: 2, values: Float32Array.of(-4.25, 1.125, 5, 7.75) }
  const file = Object.assign(new Blob(['original test data']), { name: 'source.png' }) as File
  const source = makeElevationSource('Coast', raster, { min: -10, max: 10, sea: 0, sourceStepKm: 23,
    window: { centerLat: 10, centerLon: 20, radiusKm: 6371, extentKmX: 46, extentKmY: 46, projection: 'azimuthal_equidistant' } }, file)
  const result = makeElevationResult('Redrawn', source.id, { raster, manifestSha256: 'a'.repeat(64), nativeSpacingKm: 25,
    recommendation: 'redraw', recipe: { method: 'redraw', seed: 314, residualGain: 1 } })
  return { id: crypto.randomUUID(), name: 'My world', updatedAt: 1, layers: [source, result] }
}

describe('portable elevation projects', () => {
  it('retains input bytes, samples, settings and relations while assigning a new project identity', async () => {
    const project = exampleProject()
    const restored = await importProject(exportProject(project))
    const [source, result] = restored.layers
    expect(restored.id).not.toBe(project.id)
    expect(restored.name).toBe(project.name)
    expect(projectBytes(restored)).toBe(projectBytes(project))
    expect(source.kind).toBe('elevation-source')
    if (source.kind === 'elevation-source') {
      expect(source.frame.sea).toBe(0)
      expect(source.original?.name).toBe('source.png')
      expect(await source.original?.data.text()).toBe('original test data')
    }
    expect(result).toMatchObject({ sourceId: source.id, settings: { recipe: { seed: 314 } } })
    expect((await openProjectRaster(result)).values).toEqual(Float32Array.of(-4.25, 1.125, 5, 7.75))
  })

  it('rejects truncated files, added data and orphaned results', async () => {
    const project = exampleProject()
    const archive = exportProject(project)
    await expect(importProject(archive.slice(0, -1))).rejects.toThrow('Incomplete')
    await expect(importProject(new Blob([archive, 'x']))).rejects.toThrow('Unexpected')
    await expect(importProject(exportProject({ ...project, layers: project.layers.slice(1) }))).rejects.toThrow('Invalid result settings')
  })

  it('rejects non-finite elevations and preserves linked inputs when deleting a result', async () => {
    const project = exampleProject()
    const [source, result] = project.layers
    const corrupt = { ...result, data: new Blob([Float32Array.of(0, NaN, 0, 0)]) }
    await expect(importProject(exportProject({ ...project, layers: [source, corrupt] }))).rejects.toThrow('Invalid elevation values')
    expect(() => removeProjectLayer(project, source.id)).toThrow('Source is still in use')
    expect(removeProjectLayer(project, result.id).layers).toEqual([source])
  })
})

describe('world data archives', () => {
  it('includes all saved EBM assets and preserves the source branch and experiment inputs', async () => {
    const trial: SavedBrowserEbm = {
      metadata: { id: crypto.randomUUID(), format: 1, solver: 'ebm', planet: 'planet_earth',
        branch: 'tilt-test', saved_at: '2026-01-01T00:00:00Z', cells: 320, elapsed_seconds: 5,
        inputs: { solver_version: '1.2.0', mesh_sha256: 'a'.repeat(64), config_sha256: 'b'.repeat(64), radius_km: 6371,
          forcing: { axial_tilt_deg: 63.44, albedo: 0.3, rotation_period_days: 1, greenhouse_warming_k: 33 } },
        surface: { planet_id: 'planet_earth', projection: 'equirectangular', width: 4096, height: 2048,
          elevation_min_m: -10000, elevation_max_m: 8000, sea_level_m: 0, voronoi_num_cells: 320, voronoi_seed: 5 } },
      assets: { elevation: new Blob(['surface']), geometry: new Blob(['geometry']), fields: new Blob(['fields']),
        monthly: new Blob(['monthly']), yearly: new Blob(['yearly']) },
    }
    const world = { ...exampleProject(), id: 'earth', published: true as const, layers: [], climateTrials: [trial] }
    const restored = await importWorldData(exportWorldData(world))
    expect(restored).toMatchObject({ id: world.id, published: true })
    const [saved] = restored.climateTrials ?? []
    expect(saved.metadata).toEqual(trial.metadata)
    expect(await Promise.all(Object.values(saved.assets).map(asset => asset.text()))).toEqual([
      'geometry', 'fields', 'monthly', 'yearly', 'surface',
    ])
    await expect(importWorldData(exportWorldData({ ...world, climateTrials: [trial, trial] }))).rejects.toThrow('Invalid climate trial manifest')
  })

  it('restores a temperature-only archive with its source branch, parameters, and exact normalized samples', async () => {
    const values = new Float32Array(GRID_W * GRID_H).fill(0.75)
    const draft = { id: crypto.randomUUID(), planet: 'planet_earth', branch: 'ERE-if',
      source: 'Earth terrain', defaults: false, updatedAt: 100, params: { ...EARTH_PARAMS, albedo: 0.4 },
      grid: new Blob([values.buffer]) }
    const world = { ...exampleProject(), id: 'earth', published: true as const, layers: [], temperatureDrafts: [draft] }
    const restored = await importWorldData(exportWorldData(world))
    expect(restored).toMatchObject({ id: 'earth', published: true, layers: [], temperatureDrafts: [draft] })
    const saved = restored.temperatureDrafts![0]
    expect(await readTemperatureGrid(saved.grid)).toEqual(values)
    expect(projectBytes(world)).toBe(values.byteLength)
    values[0] = NaN
    await expect(readTemperatureGrid(new Blob([values.buffer]))).rejects.toThrow('Invalid temperature draft grid')
    await expect(readTemperatureGrid(new Blob())).rejects.toThrow('Invalid temperature draft grid size')
  })

  it('round-trips a browser world with its original, parameters and exact samples', async () => {
    const world = exampleProject()
    const archive = exportWorldData(world)
    expect(archive.type).toBe('application/x-tar')
    const restored = await importWorldData(archive)
    expect(restored).toMatchObject({ id: world.id, name: world.name })
    const [source, result] = restored.layers
    expect(source.kind === 'elevation-source' && await source.original?.data.text()).toBe('original test data')
    expect(result).toMatchObject({ sourceId: source.id, settings: { recipe: { seed: 314 } } })
    expect((await openProjectRaster(result)).values).toEqual((await openProjectRaster(world.layers[1])).values)
  })

  it('keeps the identity of a published world and its source planet and branch', async () => {
    const sample = exampleProject()
    const [source, result] = sample.layers
    if (source.kind !== 'elevation-source') throw new Error('Missing test source')
    const location = { planet: 'planet_gaia', branch: 'test-climate' }
    const world = { ...sample, id: 'global-earth-1024x512', published: true as const,
      layers: [{ ...source, location }, result] }
    const archive = exportWorldData(world)
    const headers = await archive.text()
    expect(headers).not.toContain('world.yaml')
    expect(headers).toContain(`/input/height.meters.npy`)
    const restored = await importWorldData(archive)
    expect(restored).toMatchObject({ id: world.id, published: true })
    expect(restored.layers[0]).toMatchObject({ location })
  })

  it('rejects malformed containers and invalid numeric arrays', async () => {
    const world = exampleProject()
    const archive = exportWorldData(world)
    await expect(importWorldData(archive.slice(0, -512))).rejects.toThrow()
    await expect(importWorldData(new Blob(['bad', archive.slice(3)]))).rejects.toThrow('Invalid world archive entry')
    const result = { ...world.layers[1], data: new Blob([Float32Array.of(0, NaN, 0, 0)]) }
    await expect(importWorldData(exportWorldData({ ...world, layers: [world.layers[0], result] }))).rejects.toThrow('Invalid elevation values')
  })
})
