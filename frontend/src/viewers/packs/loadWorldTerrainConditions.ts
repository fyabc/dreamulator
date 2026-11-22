import { api } from '../../api/client'
import type { WorldTerrainRequest } from '../../workers/worldTerrainSource.worker'
import type { PackWindow } from './packCoords'
import type { TerrainConditionGrid } from './terrainConditions'
import { decodeWorldTerrainSource } from './worldTerrainSource'

export type WorldTerrainSelection = { world: string; planet: string; branch: string | null; window: PackWindow;
  browserWorld?: true; climateResult?: string }

export async function loadWorldTerrainConditions(selection: WorldTerrainSelection, signal: AbortSignal) {
  const { world, planet, branch, window, browserWorld, climateResult } = selection
  let packet: Blob | null
  let png: WorldTerrainRequest['png']
  if (browserWorld) {
    if (!climateResult) return null
    const { getProject } = await import('../../projects/projectStore')
    const result = (await getProject(world))?.climateTrials?.find(({ metadata }) =>
      metadata.id === climateResult && metadata.planet === planet && metadata.branch === branch && metadata.surface.browser_heightmap)
    if (!result?.assets.terrain) throw new Error('Missing conditioning data for the selected climate result')
    packet = result.assets.terrain
    const { elevation_min_m: min, elevation_max_m: max } = result.metadata.surface
    png = { blob: result.assets.elevation, min, max }
  } else {
    packet = await api.getTerrainSource(world, planet, branch, signal)
  }
  if (!packet) return null
  const bytes = await packet.arrayBuffer()
  const source = decodeWorldTerrainSource(bytes)
  if (!source) return null
  const native = !png && source.native ? await api.getTerrainNativeElevation(world, planet, branch, source.native, signal) : null
  signal.throwIfAborted()
  const worker = new Worker(new URL('../../workers/worldTerrainSource.worker.ts', import.meta.url), { type: 'module' })
  const workerScope = new AbortController()
  try {
    return await new Promise<TerrainConditionGrid>((resolve, reject) => {
      signal.addEventListener('abort', () => reject(signal.reason), { once: true, signal: workerScope.signal })
      worker.onmessage = ({ data }: MessageEvent<{ grid: TerrainConditionGrid } | { error: string }>) => {
        if ('error' in data) reject(new Error(data.error))
        else resolve(data.grid)
      }
      worker.onerror = (event) => reject(new Error(event.message || 'Unable to prepare world TD inputs'))
      worker.onmessageerror = () => reject(new Error('Unable to read world TD inputs'))
      worker.postMessage({ bytes, native, png, window } satisfies WorldTerrainRequest, [bytes])
    })
  } finally {
    workerScope.abort()
    worker.terminate()
  }
}
