import { afterEach, describe, expect, it, vi } from 'vitest'
import type { TerrainJob, TerrainReply } from '../../workers/terrainRefinement.worker'
import { runTerrainRefinement } from './runTerrainRefinement'
import type { WebGpuDevice } from './webGpuDevice'

const job: TerrainJob = {
  base: 'https://example.test/models/', hash: 'test',
  raster: { width: 1, height: 1, values: new Float32Array(1) }, spanKm: 150, sea: 0,
  recipe: { method: 'redraw', seed: 42, residualGain: 1 },
}
const gpu: WebGpuDevice = { adapter: {}, kind: 'hardware', name: 'test GPU' }

function stubWorker() {
  const worker = {
    onmessage: null as ((event: { data: TerrainReply }) => void) | null,
    postMessage: vi.fn(),
    terminate: vi.fn(),
  }
  vi.stubGlobal('Worker', class { constructor() { return worker } })
  return worker
}

describe('browser terrain worker lifetime', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('terminates the worker on cancellation even if inference never replies', async () => {
    const worker = stubWorker()
    const controller = new AbortController()
    const task = runTerrainRefinement(job, gpu, controller.signal, vi.fn())
    expect(worker.postMessage).toHaveBeenCalledOnce()
    controller.abort()
    await expect(task).rejects.toBe(controller.signal.reason)
    expect(worker.terminate).toHaveBeenCalledOnce()
  })

  it('surfaces a lost device and terminates the worker', async () => {
    const worker = stubWorker()
    const task = runTerrainRefinement(job, gpu, new AbortController().signal, vi.fn())
    worker.onmessage?.({ data: { kind: 'deviceLost', message: 'GPU process disconnected' } })
    await expect(task).rejects.toMatchObject({ name: 'WebGpuDeviceLostError', message: 'GPU process disconnected' })
    expect(worker.terminate).toHaveBeenCalledOnce()
  })
})
