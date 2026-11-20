import type { TerrainJob, TerrainReply, TerrainRequest } from '../../workers/terrainRefinement.worker'
import type { ElevationRaster } from './elevationRaster'
import type { TerrainProgress } from './terrainRefinement'
import type { WebGpuDevice } from './webGpuDevice'

type Report = (progress: TerrainProgress) => void

function runInWorker(job: TerrainJob, signal: AbortSignal, report: Report) {
  let worker: Worker
  try {
    worker = new Worker(new URL('../../workers/terrainRefinement.worker.ts', import.meta.url), { type: 'module' })
  } catch {
    return Promise.resolve(null)
  }
  let cancel: () => void
  return new Promise<ElevationRaster | null>((resolve, reject) => {
    cancel = () => reject(signal.reason)
    worker.onmessage = ({ data }: MessageEvent<TerrainReply>) => {
      if (data.kind === 'progress') report(data.progress)
      else if (data.kind === 'result') resolve(data.raster)
      else if (data.kind === 'unavailable') resolve(null)
      else if (data.kind === 'deviceLost') reject(new DOMException(data.message, 'WebGpuDeviceLostError'))
      else reject(new Error(data.message))
    }
    worker.onerror = (event) => reject(new Error(event.message || 'Unable to start the terrain worker'))
    worker.onmessageerror = () => reject(new Error('Unable to read the terrain worker result'))
    signal.addEventListener('abort', cancel, { once: true })
    worker.postMessage({ kind: 'run', job } satisfies TerrainRequest)
  }).finally(() => {
    signal.removeEventListener('abort', cancel)
    worker.terminate()
  })
}

export async function runTerrainRefinement(job: TerrainJob, gpu: WebGpuDevice, signal: AbortSignal, report: Report) {
  signal.throwIfAborted()
  const result = await runInWorker(job, signal, report)
  signal.throwIfAborted()
  if (result) return result
  const { refineTerrain } = await import('./terrainRefinement')
  signal.throwIfAborted()
  return refineTerrain(new URL(job.base), job.hash, gpu, job.raster, job.spanKm, job.sea, job.recipe, signal, report)
}
