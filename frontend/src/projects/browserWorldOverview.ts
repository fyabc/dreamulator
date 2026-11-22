import { parse } from 'yaml'
import { readCreationSnapshot } from './creationSnapshot'
import { worldLayers } from './worldLayers'

type SnapshotEntry = Record<string, unknown> & { id: string }
type Orbit = { body_id: string; parent_id: string; semi_major_axis_au?: number; eccentricity?: number }

function entries(value: unknown): SnapshotEntry[] {
  return Array.isArray(value) ? value.filter((item): item is SnapshotEntry => typeof item?.id === 'string') : []
}
export async function readBrowserWorldOverview(archive: Blob) {
  const snapshot = await readCreationSnapshot(archive)
  const readInput = async (path: string) => {
    const file = snapshot.files.get(path)
    return file ? parse(await file.text(), { version: '1.1' }) : null
  }
  const [world, system, geology] = await Promise.all([
    snapshot.parse('world.yaml'), readInput('layers/astronomy/input/stellar.yaml'),
    readInput('layers/geological/input/planets.yaml'),
  ])
  const stars = entries(system?.stars).map(star => ({ ...star, luminosity_sol: star.luminosity,
    mass_sol: star.mass, radius_sol: star.radius, temperature_k: star.temperature }))
  const orbits = Array.isArray(system?.orbits) ? system.orbits.filter((orbit: Partial<Orbit>): orbit is Orbit =>
    typeof orbit?.body_id === 'string' && typeof orbit.parent_id === 'string') as Orbit[] : []
  const stellarSystem = typeof system?.name === 'string' ? { name: system.name, stars, orbits,
    description: typeof system.description === 'string' ? system.description : undefined } : null
  const paths = Array.from(snapshot.files.keys())
  const inputs = worldLayers.filter(layer => paths.some(path => path.startsWith(`layers/${layer}/input/`) && path.endsWith('.yaml')))
  return { world, stellarSystem, planets: entries(geology?.planets), inputs }
}
