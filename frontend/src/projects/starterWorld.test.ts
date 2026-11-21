import { describe, expect, it } from 'vitest'
import { readCreationSnapshot, writeCreationSnapshot } from './creationSnapshot'
import { exportStarterWorld, readStarterSnapshot, type StarterFiles, type StarterSettings } from './starterWorld'
import { readBrowserParameters, writeBrowserParameters } from './worldParameters'

const settings: StarterSettings = { template: 'minimal', id: 'terra-lab', title: '试验世界', seed: 0 }
const created = '2026-11-21T09:00:00.000Z'
const template: StarterFiles = {
  root: { metadata: { tags: ['terrestrial'] }, planet_ids: ['planet_terra'], layers: {} },
  inputs: { 'layers/astronomy/input/stellar.yaml': 'name: Local Star\n',
    'layers/geological/input/planets.yaml': 'planets: []\n' },
}

describe('starter world snapshots', () => {
  it('stores a formal grid override in a starter snapshot and preserves other inputs', async () => {
    const defaults = { num_cells: 100_000, min_cells: 100, max_cells: 200_000, planet: { rotation_period_days: 1, albedo: 0.3 } }
    const planets = 'layers/geological/input/planets.yaml'
    const input = '# Original planets\nplanets:\n  - id: planet_terra\n    name: Terra\n    radius: 1.0\n'
    const archive = await exportStarterWorld(settings, { ...template, inputs: { ...template.inputs, [planets]: input } }, created)
    const before = await readBrowserParameters(archive, defaults, 'first')
    expect(before).toMatchObject({ num_cells: 100_000, source: planets })
    expect(before.planet).toMatchObject(defaults.planet)
    const withGrid = await writeBrowserParameters(archive, { num_cells: 256, revision: 'first' }, defaults)
    const planet = { rotation_period_days: 1.75, albedo: 0.45 }
    const updated = await writeBrowserParameters(withGrid, { planet, revision: 'second' }, defaults)
    const rebuilt = await readCreationSnapshot(updated)
    expect(await readStarterSnapshot(rebuilt)).toEqual({ id: settings.id, title: settings.title })
    expect(await rebuilt.files.get(planets)?.text()).toContain('# Original planets')
    expect(await rebuilt.files.get('layers/astronomy/input/stellar.yaml')?.text()).toBe('name: Local Star\n')
    expect(await readBrowserParameters(updated, defaults, 'third')).toMatchObject({ num_cells: 256, planet })
  })

  it('keeps the template inputs and seed but creates no derived files', async () => {
    const snapshot = await readCreationSnapshot(await exportStarterWorld(settings, template, created))
    expect(await readStarterSnapshot(snapshot)).toEqual({ id: settings.id, title: settings.title })
    expect(await snapshot.parse('world.yaml')).toMatchObject({ metadata: {
      description: settings.title, created, tags: ['terrestrial', 'browser-starter'],
    }, seed: { seed: 0 }, planet_ids: ['planet_terra'] })
    expect([...snapshot.files.keys()]).toEqual(['world.yaml', ...Object.keys(template.inputs)])
    expect(await snapshot.files.get('layers/astronomy/input/stellar.yaml')?.text()).toBe('name: Local Star\n')
  })

  it('does not accept a derived file as part of a starter backup', async () => {
    const snapshot = await readCreationSnapshot(await exportStarterWorld(settings, template, created))
    snapshot.files.set('maps/planet_terra/elevation.png', new Blob(['not an image']))
    const archive = await writeCreationSnapshot(settings.id, snapshot.files)
    await expect(readStarterSnapshot(await readCreationSnapshot(archive))).rejects.toThrow('Unsupported starter snapshot')
  })

  it('rejects the reserved reference ID and invalid seeds', async () => {
    await expect(exportStarterWorld({ ...settings, id: 'earth' }, template, created)).rejects.toThrow('Invalid starter')
    await expect(exportStarterWorld({ ...settings, seed: 1.5 }, template, created)).rejects.toThrow('Invalid starter')
  })
})
