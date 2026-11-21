import { describe, expect, it } from 'vitest'
import { readCreationSnapshot, writeCreationSnapshot } from './creationSnapshot'
import { exportStarterWorld, readStarterSnapshot, type StarterFiles, type StarterSettings } from './starterWorld'

const settings: StarterSettings = { template: 'minimal', id: 'terra-lab', title: '试验世界', seed: 0 }
const created = '2026-11-21T09:00:00.000Z'
const template: StarterFiles = {
  root: { metadata: { tags: ['terrestrial'] }, planet_ids: ['planet_terra'], layers: {} },
  inputs: { 'layers/astronomy/input/stellar.yaml': 'name: Local Star\n',
    'layers/geological/input/planets.yaml': 'planets: []\n' },
}

describe('starter world snapshots', () => {
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
