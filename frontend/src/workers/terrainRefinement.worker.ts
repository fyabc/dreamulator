import type { ElevationRaster } from '../viewers/packs/elevationRaster'
import { refineTerrain, type TerrainProgress } from '../viewers/packs/terrainRefinement'
import type { TerrainRecipe } from '../viewers/packs/terrainRecommendation'
import { detectWebGpu } from '../viewers/packs/webGpuDevice'

export type TerrainJob = { base: string; hash: string; raster: ElevationRaster; spanKm: number; sea: number; recipe: TerrainRecipe }
export type TerrainRequest = { kind: 'run'; job: TerrainJob }
export type TerrainReply = { kind: 'progress'; progress: TerrainProgress } | { kind: 'result'; raster: ElevationRaster } |
  { kind: 'unavailable' } | { kind: 'error' | 'deviceLost'; message: string }

const controller = new AbortController()

self.onmessage = async ({ data }: MessageEvent<TerrainRequest>) => {
  try {
    const gpu = await detectWebGpu()
    if (gpu?.kind !== 'hardware') {
      self.postMessage({ kind: 'unavailable' } satisfies TerrainReply)
      return
    }
    const { base, hash, raster, spanKm, sea, recipe } = data.job
    const result = await refineTerrain(new URL(base), hash, gpu, raster, spanKm, sea, recipe, controller.signal,
      (progress) => self.postMessage({ kind: 'progress', progress } satisfies TerrainReply),
      (message) => {
        self.postMessage({ kind: 'deviceLost', message } satisfies TerrainReply)
        controller.abort()
      })
    self.postMessage({ kind: 'result', raster: result } satisfies TerrainReply, { transfer: [result.values.buffer] })
  } catch (error) {
    self.postMessage({ kind: 'error', message: error instanceof Error ? error.message : String(error) } satisfies TerrainReply)
  }
}
