import type { ElevationRaster } from '../viewers/packs/elevationRaster'
import { refineTerrain, type TerrainProgress } from '../viewers/packs/terrainRefinement'
import { detectWebGpu } from '../viewers/packs/webGpuDevice'

export type TerrainJob = { base: string; hash: string; raster: ElevationRaster; spanKm: number; sea: number }
export type TerrainRequest = { kind: 'run'; job: TerrainJob } | { kind: 'cancel' }
export type TerrainReply = { kind: 'progress'; progress: TerrainProgress } | { kind: 'result'; raster: ElevationRaster } |
  { kind: 'unavailable' } | { kind: 'error'; message: string }

const controller = new AbortController()

self.onmessage = async ({ data }: MessageEvent<TerrainRequest>) => {
  if (data.kind === 'cancel') {
    controller.abort()
    return
  }
  try {
    const gpu = await detectWebGpu()
    controller.signal.throwIfAborted()
    if (gpu?.kind !== 'hardware') {
      self.postMessage({ kind: 'unavailable' } satisfies TerrainReply)
      return
    }
    const { base, hash, raster, spanKm, sea } = data.job
    const result = await refineTerrain(new URL(base), hash, gpu, raster, spanKm, sea, controller.signal,
      (progress) => self.postMessage({ kind: 'progress', progress } satisfies TerrainReply))
    self.postMessage({ kind: 'result', raster: result } satisfies TerrainReply, { transfer: [result.values.buffer] })
  } catch (error) {
    self.postMessage({ kind: 'error', message: error instanceof Error ? error.message : String(error) } satisfies TerrainReply)
  }
}
