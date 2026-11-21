import { isCreationWorldId, jsonBlob, writeCreationSnapshot, type CreationSnapshot } from './creationSnapshot'

export const starterTemplates = ['minimal', 'earthlike'] as const
export type StarterTemplate = typeof starterTemplates[number]
export type StarterSettings = { id: string; title: string; template: StarterTemplate; seed: number }
export type StarterFiles = {
  root: { metadata: { tags: string[] }; planet_ids: string[]; layers: Record<string, unknown> }
  inputs: Record<string, string>
}
const starterTag = 'browser-starter'
const inputPath = /^layers\/[a-z]+\/input\/[a-z0-9_-]+\.yaml$/

export function isStarterSeed(seed: number) {
  return Number.isInteger(seed) && seed >= 0 && seed <= 0x7fffffff
}

export async function exportStarterWorld(settings: StarterSettings, template: StarterFiles, created: string) {
  const { id, title, seed } = settings
  if (!isCreationWorldId(id) || !title.trim() || title.length > 120 || !isStarterSeed(seed)) throw new Error('Invalid starter settings')
  const files = new Map<string, Blob>()
  files.set('world.yaml', jsonBlob({ ...template.root, metadata: { ...template.root.metadata,
    name: id, description: title, created, modified: created, dreamulator_version: __APP_VERSION__,
    tags: [...template.root.metadata.tags, starterTag],
  }, seed: { seed } }))
  for (const [path, yaml] of Object.entries(template.inputs)) {
    if (!inputPath.test(path) || typeof yaml !== 'string') throw new Error('Invalid template input')
    files.set(path, new Blob([yaml], { type: 'application/yaml' }))
  }
  return writeCreationSnapshot(id, files)
}

export async function readStarterSnapshot({ id, files, parse }: CreationSnapshot) {
  if (files.size > 20 || [...files.keys()].some(path => path !== 'world.yaml' && !inputPath.test(path)) ||
    !files.has('layers/astronomy/input/stellar.yaml') || !files.has('layers/geological/input/planets.yaml')) {
    throw new Error('Unsupported starter snapshot')
  }
  const { metadata, seed, planet_ids: planets } = await parse('world.yaml') ?? {}
  if (metadata?.name !== id || typeof metadata.description !== 'string' || !metadata.description.trim() ||
    metadata.description.length > 120 || !Array.isArray(metadata.tags) || !metadata.tags.includes(starterTag) ||
    !isStarterSeed(seed?.seed) || !Array.isArray(planets) || !planets.length) throw new Error('Invalid starter snapshot')
  return { id, title: metadata.description as string }
}
