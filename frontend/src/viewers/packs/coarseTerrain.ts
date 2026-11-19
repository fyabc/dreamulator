import type { InferenceSession, Tensor } from 'onnxruntime-web'

const size = 64
const samplePlanes = 6
const round = Math.fround

export interface CoarseSchedule {
  labels: number[]
  sigmaData: number
  steps: { scale: number; noise: number; next: [number, number, number]; history: [number, number] }[]
}

export async function sampleCoarseTile(
  TensorType: typeof Tensor, session: InferenceSession, settings: CoarseSchedule, condition: Float32Array,
  initial: Float32Array, signal: AbortSignal,
) {
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
      const { output } = await session.run({ x: input, noise_labels: noise, ...conditions }).finally(() => noise.dispose())
      try {
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
      await new Promise((resolve) => setTimeout(resolve, 0))
    }
    signal.throwIfAborted()
    return Float32Array.from(sample, (value) => value / settings.sigmaData)
  } finally {
    input.dispose()
    Object.values(conditions).forEach((value) => value.dispose())
  }
}
