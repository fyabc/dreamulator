import { api } from '../../api/client'
import type { WorldTerrainRequest } from '../../workers/worldTerrainSource.worker'
import type { PackWindow } from './packCoords'
import type { TerrainConditionGrid } from './terrainConditions'
import { decodeWorldTerrainSource } from './worldTerrainSource'

export async function loadWorldTerrainConditions(world: string, planet: string, branch: string | null, window: PackWindow, signal: AbortSignal) {
  const packet = await api.getTerrainSource(world, planet, branch, signal)
  const bytes = await packet.arrayBuffer()
  const source = decodeWorldTerrainSource(bytes)
  if (!source) return null
  const native = source.native ? await api.getTerrainNativeElevation(world, planet, branch, source.native, signal) : null
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
      worker.postMessage({ bytes, native, window } satisfies WorldTerrainRequest, [bytes])
    })
  } finally {
    workerScope.abort()
    worker.terminate()
  }
}
