import wasmUrl from 'onnxruntime-web/ort-wasm-simd-threaded.jsep.wasm?url'
import type { InferenceSession, Tensor } from 'onnxruntime-web'
import type { ElevationRaster } from './elevationRaster'
import type { WebGpuDevice } from './webGpuDevice'

const size = 64
const stride = 48
const pixels = size * size
const samplePlanes = 6
const conditionPlanes = 5
const manifestDigest = '4d8613b846872d2526f3838192d9531f9debf1157cdd02afc5271329ef0206e9'
const round = Math.fround

interface Manifest {
  model: string
  modelSha256: string
  labels: number[]
  sigmaData: number
  steps: { scale: number; noise: number; next: [number, number, number]; history: [number, number] }[]
  weights: string
  tiles: { initial: string; condition: string }[]
  elevationMean: number
  elevationStd: number
}

async function bytes(base: URL, name: string, signal: AbortSignal) {
  const response = await fetch(new URL(name, base), { signal })
  if (!response.ok) throw new Error(`TD asset ${name}: HTTP ${response.status}`)
  return response.arrayBuffer()
}

async function verify(buffer: ArrayBuffer, expected: string) {
  const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', buffer))
  const hash = Array.from(digest, (byte) => byte.toString(16).padStart(2, '0')).join('')
  if (hash !== expected) throw new Error('TD asset failed SHA-256 verification')
}

async function floats(base: URL, name: string, length: number, signal: AbortSignal) {
  const buffer = await bytes(base, name, signal)
  if (buffer.byteLength !== length * 4) throw new Error(`Unexpected size of ${name}`)
  const view = new DataView(buffer)
  const values = Float32Array.from({ length }, (_, index) => view.getFloat32(index * 4, true))
  if (!values.every(Number.isFinite)) throw new Error(`Invalid values in ${name}`)
  return values
}

async function sampleTile(
  TensorType: typeof Tensor, session: InferenceSession, settings: Manifest, condition: Float32Array,
  initial: Float32Array, signal: AbortSignal, onStep: () => void,
) {
  const scalar = (value: number) => new TensorType('float32', Float32Array.of(value), [1])
  const conditions = Object.fromEntries(settings.labels.map((value, index) => [`cond_${index}`, scalar(value)]))
  const image = new Float32Array(initial.length + condition.length)
  image.set(condition, initial.length)
  const input = new TensorType('float32', image, [1, samplePlanes + conditionPlanes, size, size])
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
      onStep()
      await new Promise((resolve) => setTimeout(resolve, 0))
    }
    signal.throwIfAborted()
    return Float32Array.from(sample.subarray(0, pixels), (value) => (value / settings.sigmaData) * settings.elevationStd + settings.elevationMean)
  } finally {
    input.dispose()
    Object.values(conditions).forEach((value) => value.dispose())
  }
}

export function stitchCoarseElevation(tiles: Float32Array[], weights: Float32Array): ElevationRaster {
  const width = size + stride * (tiles.length - 1)
  const sums = new Float64Array(width * size)
  const total = new Float64Array(sums.length)
  tiles.forEach((tile, tileIndex) => tile.forEach((value, index) => {
    const destination = Math.floor(index / size) * width + index % size + tileIndex * stride
    sums[destination] += value * weights[index]
    total[destination] += weights[index]
  }))
  const values = Float32Array.from(sums, (sum, index) => {
    const value = round(sum / total[index])
    return Math.sign(value) * value * value
  })
  if (!values.every(Number.isFinite)) throw new Error('TD produced invalid elevations')
  return { width, height: size, values }
}

export async function runCoarseTerrain(
  base: URL, device: WebGpuDevice, signal: AbortSignal, onStep: (done: number, total: number) => void,
) {
  const manifest = await bytes(base, 'manifest.json', signal)
  await verify(manifest, manifestDigest)
  const settings = JSON.parse(new TextDecoder().decode(manifest)) as Manifest
  const [model, weights, tiles] = await Promise.all([
    bytes(base, settings.model, signal),
    floats(base, settings.weights, pixels, signal),
    Promise.all(settings.tiles.map(async (tile) => ({
      initial: await floats(base, tile.initial, pixels * samplePlanes, signal),
      condition: await floats(base, tile.condition, pixels * conditionPlanes, signal),
    }))),
  ])
  await verify(model, settings.modelSha256)
  signal.throwIfAborted()
  const ort = await import('onnxruntime-web/all')
  if (!ort.env.webgpu.adapter) {
    ort.env.wasm.numThreads = 1
    ort.env.wasm.wasmPaths = { wasm: new URL(wasmUrl, window.location.href).href }
    ort.env.webgpu.adapter = device.adapter
  }
  signal.throwIfAborted()
  const session = await ort.InferenceSession.create(model, { executionProviders: ['webgpu'] })
  try {
    const output: Float32Array[] = []
    const total = tiles.length * settings.steps.length
    let done = 0
    const advance = () => onStep(++done, total)
    for (const tile of tiles) {
      output.push(await sampleTile(ort.Tensor, session, settings, tile.condition, tile.initial, signal, advance))
    }
    return stitchCoarseElevation(output, weights)
  } finally {
    await session.release()
  }
}
