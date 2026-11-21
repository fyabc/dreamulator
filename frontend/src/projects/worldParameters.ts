import { parseDocument } from 'yaml'
import type { WorldParameters, WorldParameterUpdate } from '../api/worldParameters'
import { jsonBlob, readCreationSnapshot, writeCreationSnapshot, type CreationSnapshot } from './creationSnapshot'
import { heightmapCreationPath } from './heightmapWorld'

export type GridDefaults = Pick<WorldParameters, 'min_cells' | 'max_cells'> & { num_cells: number }

const terrainPath = 'layers/geological/input/terrain_config.yaml'
const planetsPath = 'layers/geological/input/planets.yaml'
const sections = ['export', 'climate', 'noise', 'plates', 'terrain', 'planet']

async function gridInput(snapshot: CreationSnapshot) {
  const source = snapshot.files.has(terrainPath) ? terrainPath : planetsPath
  const file = snapshot.files.get(source)
  if (!file) throw new Error('No formal grid input in this snapshot')
  const document = parseDocument(await file.text(), { version: '1.1' })
  if (document.errors.length) throw document.errors[0]
  const key = source === planetsPath ? ['planets', 0, 'terrain', 'num_nodes'] :
    ['voronoi_num_cells', 'num_cells', 'num_nodes'].flatMap(name => [[name], ...sections.map(section => [section, name])])
      .find(path => document.hasIn(path)) ?? ['num_nodes']
  return { document, source, key }
}

export async function readBrowserGrid(archive: Blob, defaults: GridDefaults, revision: string): Promise<WorldParameters> {
  const snapshot = await readCreationSnapshot(archive)
  const { document, source, key } = await gridInput(snapshot)
  const value = document.getIn(key) ?? defaults.num_cells
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value <= 0) throw new Error('Invalid grid size')
  return { ...defaults, num_cells: value, built_cells: null, reuses_mesh: false, source, read_only: null, revision }
}

export async function writeBrowserGrid(archive: Blob, settings: WorldParameterUpdate, defaults: GridDefaults) {
  const cells = settings.num_cells
  if (!Number.isSafeInteger(cells) || cells < defaults.min_cells || cells > defaults.max_cells) throw new Error('Invalid grid size')
  const snapshot = await readCreationSnapshot(archive)
  const { document, source, key } = await gridInput(snapshot)
  document.setIn(key, cells)
  snapshot.files.set(source, new Blob([document.toString()], { type: 'application/yaml' }))
  if (snapshot.files.has(heightmapCreationPath)) {
    const creation = await snapshot.parse(heightmapCreationPath)
    snapshot.files.set(heightmapCreationPath, jsonBlob({ ...creation, meshCells: cells }))
  }
  return writeCreationSnapshot(snapshot.id, snapshot.files)
}
