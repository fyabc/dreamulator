import { parseDocument } from 'yaml'
import { validPlanetValues, type PlanetValues, type WorldParameters, type WorldParameterUpdate } from '../api/worldParameters'
import { jsonBlob, readCreationSnapshot, writeCreationSnapshot, type CreationSnapshot } from './creationSnapshot'
import { heightmapCreationPath } from './heightmapWorld'

export type ParameterDefaults = Pick<WorldParameters, 'min_cells' | 'max_cells'> & {
  num_cells: number
  planet: PlanetValues
}

const terrainPath = 'layers/geological/input/terrain_config.yaml'
const planetsPath = 'layers/geological/input/planets.yaml'
const sections = ['export', 'climate', 'noise', 'plates', 'terrain', 'planet']

async function inputDocument(snapshot: CreationSnapshot, source: string) {
  const file = snapshot.files.get(source)
  if (!file) throw new Error('No formal input in this snapshot')
  const document = parseDocument(await file.text(), { version: '1.1' })
  if (document.errors.length) throw document.errors[0]
  return document
}

async function gridInput(snapshot: CreationSnapshot) {
  const source = snapshot.files.has(terrainPath) ? terrainPath : planetsPath
  const document = await inputDocument(snapshot, source)
  const key = source === planetsPath ? ['planets', 0, 'terrain', 'num_nodes'] :
    ['voronoi_num_cells', 'num_cells', 'num_nodes'].flatMap(name => [[name], ...sections.map(section => [section, name])])
      .find(path => document.hasIn(path)) ?? ['num_nodes']
  return { document, source, key }
}

async function planetInput(snapshot: CreationSnapshot, defaults: PlanetValues) {
  const document = await inputDocument(snapshot, planetsPath)
  const id = document.getIn(['planets', 0, 'id'])
  const name = document.getIn(['planets', 0, 'name'])
  const rotation_period_days = document.getIn(['planets', 0, 'rotation_period_days']) ?? defaults.rotation_period_days
  const albedo = document.getIn(['planets', 0, 'albedo']) ?? defaults.albedo
  if (typeof id !== 'string' || typeof name !== 'string' ||
      typeof rotation_period_days !== 'number' || typeof albedo !== 'number' ||
      !validPlanetValues({ rotation_period_days, albedo })) return null
  return { document, values: { id, name, rotation_period_days, albedo } }
}

export async function readBrowserParameters(archive: Blob, defaults: ParameterDefaults, revision: string): Promise<WorldParameters> {
  const snapshot = await readCreationSnapshot(archive)
  const { document, source, key } = await gridInput(snapshot)
  const value = document.getIn(key) ?? defaults.num_cells
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value <= 0) throw new Error('Invalid grid size')
  const input = snapshot.files.has(planetsPath) ? await planetInput(snapshot, defaults.planet) : null
  return { ...defaults, num_cells: value, built_cells: null, reuses_mesh: false, source, read_only: null, revision,
    planet: input ? { ...input.values, source: planetsPath, read_only: null, revision, needs_rebuild: false } : null }
}

export async function writeBrowserParameters(archive: Blob, settings: WorldParameterUpdate, defaults: ParameterDefaults) {
  const snapshot = await readCreationSnapshot(archive)
  if ('planet' in settings) {
    const input = await planetInput(snapshot, defaults.planet)
    if (!input || !validPlanetValues(settings.planet)) throw new Error('Invalid planet parameters')
    for (const field of ['rotation_period_days', 'albedo'] as const) {
      if (input.values[field] !== settings.planet[field]) input.document.setIn(['planets', 0, field], settings.planet[field])
    }
    snapshot.files.set(planetsPath, new Blob([input.document.toString()], { type: 'application/yaml' }))
    return writeCreationSnapshot(snapshot.id, snapshot.files)
  }
  const cells = settings.num_cells
  if (!Number.isSafeInteger(cells) || cells < defaults.min_cells || cells > defaults.max_cells) throw new Error('Invalid grid size')
  const { document, source, key } = await gridInput(snapshot)
  document.setIn(key, cells)
  snapshot.files.set(source, new Blob([document.toString()], { type: 'application/yaml' }))
  if (snapshot.files.has(heightmapCreationPath)) {
    const creation = await snapshot.parse(heightmapCreationPath)
    snapshot.files.set(heightmapCreationPath, jsonBlob({ ...creation, meshCells: cells }))
  }
  return writeCreationSnapshot(snapshot.id, snapshot.files)
}
