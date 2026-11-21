import { spawnSync } from 'node:child_process'
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { EARTH_PARAMS, GRID_H, GRID_W } from '../playground/temperatureDraft'
import { elevationPng } from '../viewers/packs/elevationRaster'
import { readBrowserGrid, writeBrowserGrid } from './worldParameters'
import { exportHeightmapWorld, heightmapGrid, importHeightmapWorld, readHeightmapInput, savedTemperature,
  temperatureInputFingerprint, type HeightmapWorld } from './heightmapWorld'

async function fixture(real?: string): Promise<HeightmapWorld> {
  const blob = real ? new Blob([Uint8Array.from(await readFile(real))]) : await elevationPng({ width: 4, height: 2,
    values: Float32Array.from([4000, 4000, -2000, -2000, 4000, 4000, -2000, -2000]) }, {})
  const heightmap = await readHeightmapInput(blob, 'elevation.png')
  const params = { ...EARTH_PARAMS, elevMinM: -2000, elevMaxM: 4000, luminosity: 1.05, tiltDeg: 24, yearDays: 410 }
  const fingerprint = await temperatureInputFingerprint(heightmap, params)
  const grid = (value: number) => new Array<number>(GRID_W * GRID_H).fill(value)
  const temperature = savedTemperature({ annual: grid(13), monthly: Array.from({ length: 12 }, (_, month) => grid(month)),
    globalMeanC: 13, annualMeanC: 13, minC: 0, maxC: 13, elapsedS: 1 }, fingerprint, 'fixture-v1')
  return { id: 'fixture-imported-world', title: '测试世界', created: '2026-11-21T00:00:00Z', seed: 42,
    meshCells: 256, heightmap, params, temperature }
}

describe('heightmap world snapshots', () => {
  it('changes the formal mesh without changing the saved browser experiment or original image', async () => {
    const world = await fixture()
    const archive = await exportHeightmapWorld(world)
    const defaults = { num_cells: 100_000, min_cells: 100, max_cells: 200_000 }
    expect((await readBrowserGrid(archive, defaults, 'first')).num_cells).toBe(256)
    const updated = await writeBrowserGrid(archive, { num_cells: 320, revision: 'first' }, defaults)
    const restored = await importHeightmapWorld(updated)
    expect((await readBrowserGrid(updated, defaults, 'second')).num_cells).toBe(320)
    expect(restored.meshCells).toBe(320)
    expect(restored.temperature).toEqual(world.temperature)
    expect(restored.heightmap.sha256).toBe(world.heightmap.sha256)
  })

  it('restores original bytes and month order without running the experiment', async () => {
    const world = await fixture()
    const restored = await importHeightmapWorld(await exportHeightmapWorld(world))
    expect(restored.title).toBe(world.title)
    expect(restored.params).toEqual(world.params)
    expect(restored.heightmap.sha256).toBe(world.heightmap.sha256)
    expect(await restored.heightmap.original.arrayBuffer()).toEqual(await world.heightmap.original.arrayBuffer())
    expect(restored.temperature?.monthly.map(month => month[0])).toEqual([10, 11, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9])
    const preview = heightmapGrid(restored.heightmap, restored.params, 4, 2)
    expect([...preview.land]).toEqual([1, 1, 0, 0, 1, 1, 0, 0])
    expect([...preview.values]).toEqual([4000, 4000, -2000, -2000, 4000, 4000, -2000, -2000])
  })

  it('rejects stale experimental data and still allows an inputs-only save', async () => {
    const world = await fixture()
    const params = { ...world.params, seaLevelM: 50 }
    await expect(exportHeightmapWorld({ ...world, params })).rejects.toThrow('does not match')
    const restored = await importHeightmapWorld(await exportHeightmapWorld({ ...world, params, temperature: undefined }))
    expect(restored.params.seaLevelM).toBe(50)
    expect(restored.temperature).toBeUndefined()
  })

  it('rejects invalid source bytes and truncated snapshots', async () => {
    const world = await fixture()
    const broken = world.heightmap.original.slice(0, -2)
    await expect(readHeightmapInput(broken, 'elevation.png')).rejects.toThrow('Incomplete heightmap')
    const snapshot = await exportHeightmapWorld(world)
    await expect(importHeightmapWorld(snapshot.slice(0, -20))).rejects.toThrow()
  })

  it.skipIf(!process.env.DREAMULATOR_TEST_CREATION_CLI)('restores the browser export and builds it with the CLI', async () => {
    const root = await mkdtemp(join(tmpdir(), 'dreamulator-creation-'))
    try {
      const world = await fixture(process.env.DREAMULATOR_TEST_CREATION_PNG)
      const snapshot = await exportHeightmapWorld(world)
      const file = join(root, 'world.tar.gz')
      const dataDir = join(root, 'worlds')
      await writeFile(file, new Uint8Array(await snapshot.arrayBuffer()))
      const cli = (...args: string[]) => spawnSync('uv', ['run', 'dreamulator', ...args, '--data-dir', dataDir],
        { cwd: new URL('../../..', import.meta.url), encoding: 'utf8', timeout: 90_000, env: { ...process.env, OPENBLAS_NUM_THREADS: '2' } })
      const restored = cli('snapshot', 'restore', file)
      expect(restored.status, restored.stderr).toBe(0)
      const duplicate = cli('snapshot', 'restore', file)
      expect(duplicate.stderr).toContain('already exists')
      const worldDir = join(dataDir, world.id)
      const original = join(worldDir, 'layers/geological/input/elevation_sources', `${world.heightmap.sha256}.bin`)
      expect(Uint8Array.from(await readFile(original))).toEqual(new Uint8Array(await world.heightmap.original.arrayBuffer()))
      const resultPath = join(worldDir, 'layers/climate/derived/browser-temperature/temperature.json')
      const result = await readFile(resultPath, 'utf8')
      expect(JSON.parse(result).fingerprint).toBe(world.temperature?.fingerprint)
      const built = cli('build', world.id)
      expect(built.status, built.stderr + built.stdout).toBe(0)
      expect((await readFile(join(worldDir, 'maps/planet_terra/cvt_mesh.msgpack.gz'))).length).toBeGreaterThan(0)
      expect(await readFile(resultPath, 'utf8')).toBe(result)
    } finally { await rm(root, { recursive: true, force: true }) }
  }, 120_000)
})
