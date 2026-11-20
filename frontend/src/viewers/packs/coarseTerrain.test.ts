import type { InferenceSession, Tensor } from 'onnxruntime-web'
import { describe, expect, it, vi } from 'vitest'
import { sampleCoarseTile, type CoarseSchedule } from './coarseTerrain'
import { yieldTerrainTask } from './terrainScheduling'

class TestTensor {
  dispose() {}
}

const tensorType = TestTensor as unknown as typeof Tensor
const step: CoarseSchedule['steps'][number] = { scale: 1, noise: 0, next: [0, 1, 0], history: [0, 0] }
const schedule: CoarseSchedule = { labels: [], sigmaData: 1, steps: [step, step] }

describe('coarse terrain sampling progress', () => {
  it('distinguishes waiting from completed inference and yields without timers', async () => {
    const output = { data: Float32Array.of(5), dispose: vi.fn() }
    let finishFirst!: (value: { output: typeof output }) => void
    const first = new Promise<{ output: typeof output }>((resolve) => { finishFirst = resolve })
    const run = vi.fn().mockReturnValueOnce(first).mockResolvedValue({ output })
    const session = { run } as unknown as InferenceSession
    const report = vi.fn()

    vi.useFakeTimers({ toFake: ['setTimeout'] })
    try {
      const result = sampleCoarseTile(tensorType, session, schedule, Float32Array.of(), Float32Array.of(0),
        new AbortController().signal, report)
      expect(report.mock.calls).toEqual([
        [{ status: 'preparing', done: 0, total: 2 }],
        [{ status: 'waiting', done: 0, total: 2, startedAt: expect.any(Number) }],
      ])
      expect(run).toHaveBeenCalledOnce()
      finishFirst({ output })
      await expect(result).resolves.toEqual(Float32Array.of(5))
      expect(report.mock.calls.slice(2)).toEqual([
        [{ status: 'applying', done: 0, total: 2 }],
        [{ status: 'completed', done: 1, total: 2, runMs: expect.any(Number) }],
        [{ status: 'waiting', done: 1, total: 2, startedAt: expect.any(Number) }],
        [{ status: 'applying', done: 1, total: 2 }],
        [{ status: 'completed', done: 2, total: 2, runMs: expect.any(Number) }],
      ])
      expect(output.dispose).toHaveBeenCalledTimes(2)
    } finally {
      vi.useRealTimers()
    }
  })

  it('does not report an inference step complete when the runtime rejects', async () => {
    const failure = new Error('Device unavailable')
    const session = { run: vi.fn().mockRejectedValue(failure) } as unknown as InferenceSession
    const report = vi.fn()
    const result = sampleCoarseTile(tensorType, session, schedule, Float32Array.of(), Float32Array.of(0),
      new AbortController().signal, report)

    await expect(result).rejects.toBe(failure)
    expect(report).toHaveBeenCalledTimes(2)
    expect(report).toHaveBeenLastCalledWith(expect.objectContaining({ status: 'waiting', done: 0, total: 2 }))
  })

  it('checks for cancellation when resuming after a task yield', async () => {
    const controller = new AbortController()
    const waiting = yieldTerrainTask(controller.signal)
    controller.abort()
    await expect(waiting).rejects.toMatchObject({ name: 'AbortError' })
  })
})
