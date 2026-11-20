import type { InferenceSession, Tensor } from 'onnxruntime-web'
import { yieldTerrainTask } from './terrainScheduling'

const size = 64
const samplePlanes = 6
const round = Math.fround

export interface CoarseSchedule {
  labels: number[]
  sigmaData: number
  steps: { scale: number; noise: number; next: [number, number, number]; history: [number, number] }[]
}

export type CoarseInferenceProgress = { done: number; total: number } & (
  { status: 'preparing' | 'applying' } | { status: 'waiting'; startedAt: number } | { status: 'completed'; runMs: number }
)

export async function sampleCoarseTile(
  TensorType: typeof Tensor, session: InferenceSession, settings: CoarseSchedule, condition: Float32Array,
  initial: Float32Array, signal: AbortSignal, report: (progress: CoarseInferenceProgress) => void,
) {
  signal.throwIfAborted()
  let done = 0
  const total = settings.steps.length
  report({ status: 'preparing', done, total })
  const scalar = (value: number) => new TensorType('float32', Float32Array.of(value), [1])
  const conditions = Object.fromEntries(settings.labels.map((value, index) => [`cond_${index}`, scalar(value)]))
  const image = new Float32Array(initial.length + condition.length)
  image.set(condition, initial.length)
  const input = new TensorType('float32', image, [1, samplePlanes + 5, size, size])
  const sample = initial.slice()
  const history = new Float32Array(sample.length)
  try {
    for (const step of settings.steps) {
      signal.throwIfAborted()
      sample.forEach((value, index) => { image[index] = value * step.scale })
      const noise = scalar(step.noise)
      const startedAt = performance.now()
      report({ status: 'waiting', done, total, startedAt: performance.timeOrigin + startedAt })
      const { output } = await session.run({ x: input, noise_labels: noise, ...conditions }).finally(() => noise.dispose())
      const runMs = performance.now() - startedAt
      try {
        signal.throwIfAborted()
        report({ status: 'applying', done, total })
        const [fromSample, fromModel, fromHistory] = step.next
        const [historySample, historyModel] = step.history
        const prediction = output.data as Float32Array
        for (let index = 0; index < sample.length; index += 1) {
          const previous = sample[index]
          const current = prediction[index]
          sample[index] = round(round(round(fromSample * previous) + round(fromModel * current)) + round(fromHistory * history[index]))
          history[index] = round(round(historySample * previous) + round(historyModel * current))
        }
      } finally {
        output.dispose()
      }
      signal.throwIfAborted()
      report({ status: 'completed', done: ++done, total, runMs })
      await yieldTerrainTask(signal)
    }
    signal.throwIfAborted()
    return Float32Array.from(sample, (value) => value / settings.sigmaData)
  } finally {
    input.dispose()
    Object.values(conditions).forEach((value) => value.dispose())
  }
}
