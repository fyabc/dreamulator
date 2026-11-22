import wasmUrl from 'onnxruntime-web/ort-wasm-simd-threaded.jsep.wasm?url'
import type { InferenceSession, Tensor } from 'onnxruntime-web'
import { sampleCoarseTile, type CoarseInferenceProgress, type CoarseSchedule } from './coarseTerrain'
import { type ElevationRaster, resizeElevation } from './elevationRaster'
import { openTerrainModelCache, saveTerrainModel } from './terrainModelCache'
import { blendTerrain } from './terrainBlend'
import { prepareTerrainConditions, type TerrainConditionGrid } from './terrainConditions'
import { defaultTerrainSeed, type TerrainRecipe } from './terrainRecommendation'
import { yieldTerrainTask } from './terrainScheduling'
import { coarseArea, coarseStride, conditioningPadding, decoderInputArea, decoderSize, decoderStride,
  latentArea, latentScale, latentStride, makeTerrainPlan, stitchTiles, synthesisPadding, terrainNoise, tileKey, tileSize,
  type Rect, type Tile } from './terrainTiles'
import type { WebGpuDevice } from './webGpuDevice'

const initialAngle = Math.fround(Math.atan(80 / 0.5))
const secondAngle = Math.fround(Math.atan(0.35 / 0.5))
const round = Math.fround

export type TerrainStage = 'coarse' | 'base' | 'decoder'
type ModelSource = 'network' | 'cache'
export type TerrainProgress =
  | { phase: 'prepare' | 'manifest' | 'runtime' | 'finalize' | 'blend'; stage?: never }
  | { phase: 'download' | 'cacheRead'; stage: TerrainStage; received: number; total: number }
  | { phase: 'verify' | 'cacheWrite' | 'merge'; stage: TerrainStage }
  | { phase: 'initialize'; stage: TerrainStage; reusable: boolean }
  | { phase: 'tiles'; stage: TerrainStage; done: number; total: number; inference?: CoarseInferenceProgress }

type AssetProgress = {
  bytes: number
  reading: (received: number, source: ModelSource) => void
  verifying: () => Promise<void>
  saving?: () => void
}

type Manifest = CoarseSchedule & {
  version: 1
  sigmaMax: number
  snr: number[]
  means: number[]
  stds: number[]
  residualMean: number
  residualStd: number
  models: Record<TerrainStage, { sha256: string; bytes: number }>
}

async function readModel(body: ReadableStream<Uint8Array>, progress: AssetProgress, source: ModelSource, signal: AbortSignal, name: string) {
  const data = new Uint8Array(progress.bytes)
  const reader = body.getReader()
  let received = 0
  let lastUpdate = Number.NEGATIVE_INFINITY
  let finished = false
  try {
    while (!finished) {
      const chunk = await reader.read()
      finished = chunk.done
      signal.throwIfAborted()
      if (chunk.done) break
      if (received + chunk.value.byteLength > data.byteLength) throw new Error(`${name}: unexpected size`)
      data.set(chunk.value, received)
      received += chunk.value.byteLength
      const now = performance.now()
      if (now - lastUpdate >= 200 || received === data.byteLength) {
        progress.reading(received, source)
        lastUpdate = now
      }
    }
  } finally {
    if (!finished) await reader.cancel().catch(() => undefined)
    reader.releaseLock()
  }
  if (received !== data.byteLength) throw new Error(`${name}: unexpected size`)
  return data.buffer
}

export async function checkedAsset(base: URL, name: string, hash: string, signal: AbortSignal,
  progress?: AssetProgress, cache?: FileSystemDirectoryHandle) {
  const key = `${name}.${hash}`
  const verify = async (data: ArrayBuffer) => {
    await progress?.verifying()
    const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', data))
    const actual = Array.from(digest, (byte) => byte.toString(16).padStart(2, '0')).join('')
    signal.throwIfAborted()
    if (actual !== hash) throw new Error(`${name}: SHA-256 mismatch`)
  }
  if (cache) {
    const file = await cache.getFileHandle(key).then((entry) => entry.getFile()).catch(() => undefined)
    signal.throwIfAborted()
    if (file) {
      try {
        if (progress && file.size !== progress.bytes) throw new Error(`${name}: unexpected cached size`)
        progress?.reading(0, 'cache')
        const data = progress ? await readModel(file.stream(), progress, 'cache', signal, name) : await file.arrayBuffer()
        await verify(data)
        return { data, reusable: true }
      } catch {
        signal.throwIfAborted()
        await cache.removeEntry(key).catch(() => undefined)
      }
    }
  }
  progress?.reading(0, 'network')
  const response = await fetch(new URL(name, base), { signal })
  if (!response.ok) throw new Error(`${name}: HTTP ${response.status}`)
  if (progress && !response.body) throw new Error(`${name}: missing response body`)
  const data = progress && response.body ? await readModel(response.body, progress, 'network', signal, name) : await response.arrayBuffer()
  await verify(data)
  if (cache) progress?.saving?.()
  const reusable = cache ? await saveTerrainModel(cache, key, data, signal) : false
  return { data, reusable }
}

export function coarseCondition({ elevation, climate }: TerrainConditionGrid, tile: Tile, sea: number, manifest: Pick<Manifest, 'means' | 'stds' | 'snr'>,
  seed = defaultTerrainSeed) {
  const top = tile.row * coarseStride
  const left = tile.col * coarseStride
  const area = tileSize * tileSize
  const noise = terrainNoise(seed, top, left, tileSize, 5)
  const channels = [0, 2, 3, 4, 5]
  const climatePlanes = climate && [climate.temperature_mean_c, climate.temperature_std_c,
    climate.precipitation_total_mm, climate.precipitation_cv_pct]
  const means = Float32Array.from(manifest.means)
  const stds = Float32Array.from(manifest.stds)
  const factors = manifest.snr.map((snr) => {
    const angle = round(Math.atan(round(snr)))
    return [round(Math.cos(angle)), round(Math.sin(angle))]
  })
  return noise.map((value, index) => {
    const channel = Math.floor(index / area)
    const reference = channels[channel]
    const [signalFactor, noiseFactor] = factors[channel]
    const climatePlane = climatePlanes?.[channel - 1]
    if (channel !== 0 && !climatePlane) return noiseFactor * value
    const row = Math.max(0, Math.min(elevation.height - 1, top + Math.floor(index % area / tileSize) - conditioningPadding))
    const col = Math.max(0, Math.min(elevation.width - 1, left + index % tileSize - conditioningPadding))
    const cell = row * elevation.width + col
    const metres = round(elevation.values[cell] - (climate ? 0 : sea))
    const scaled = climatePlane ? round(climatePlane[cell] * (channel === 2 ? 100 : 1)) :
      round(Math.sign(metres) * Math.sqrt(Math.abs(metres)))
    return round(round(round(scaled - means[reference]) / stds[reference]) * signalFactor) + round(noiseFactor * value)
  })
}

function latentCondition(coarse: Float32Array) {
  const means = [14.99, 11.65, 15.87, 619.26, 833.12, 69.40, 0.66]
  const stds = [21.72, 21.78, 10.40, 452.29, 738.09, 34.59, 0.47]
  const normalized = (plane: number, index: number) => round(round(coarse[plane * 16 + index] - round(means[plane])) / round(stds[plane]))
  const span = (plane: number) => Array.from({ length: 16 }, (_, index) => normalized(plane, index))
  const climate = [2, 3, 4, 5].map((plane) => [5, 6, 9, 10].reduce((sum, index) => sum + normalized(plane, index), 0) / 4)
  const mask = Array<number>(16).fill((1 - means[6]) / stds[6])
  const groups = [span(0), span(1), climate, mask, Array<number>(5).fill(0), [-Math.sqrt(3)]]
  return Float32Array.from(groups.flatMap((group) => group.map((value) => value * Math.sqrt(58 / (6 * group.length)))))
}

async function predict(
  TensorType: typeof Tensor, session: InferenceSession, image: Float32Array, size: number, angle: number,
  condition?: Float32Array,
) {
  const feeds: Record<string, Tensor> = {
    x: new TensorType('float32', image, [1, 5, size, size]),
    noise_labels: new TensorType('float32', Float32Array.of(angle), [1]),
  }
  if (condition) feeds.cond_0 = new TensorType('float32', condition, [1, condition.length])
  try {
    const { output } = await session.run(feeds)
    try { return (output.data as Float32Array).slice() } finally { output.dispose() }
  } finally { Object.values(feeds).forEach((tensor) => tensor.dispose()) }
}

function restoreElevation(residual: Float32Array, low: Float32Array, area: Rect, size: number, sea: number) {
  const width = area.right - area.left
  const lowWidth = width / latentScale
  const lowRaster: ElevationRaster = { values: low, width: lowWidth, height: lowWidth }
  const expanded = resizeElevation(lowRaster, width, width).values
  const down = new Float32Array(low.length)
  for (let row = 0; row < lowWidth; row++) {
    for (let col = 0; col < lowWidth; col++) {
      let sum = 0
      let weight = 0
      for (let y = Math.max(0, row * latentScale - 4); y < Math.min(width, row * latentScale + 12); y++) {
        for (let x = Math.max(0, col * latentScale - 4); x < Math.min(width, col * latentScale + 12); x++) {
          const index = y * width + x
          const factor = (1 - Math.abs(y / latentScale - row - 7 / 16)) * (1 - Math.abs(x / latentScale - col - 7 / 16))
          sum += factor * (residual[index] + expanded[index])
          weight += factor
        }
      }
      down[row * lowWidth + col] = sum / weight
    }
  }
  const blur = down.map((_, index) => {
    const row = Math.floor(index / lowWidth)
    const col = index % lowWidth
    let sum = 0
    let weight = 0
    const reflect = (value: number) => value < 0 ? -value : value >= lowWidth ? 2 * lowWidth - 2 - value : value
    for (let y = -5; y <= 5; y++) {
      for (let x = -5; x <= 5; x++) {
        const factor = Math.exp(-(y * y + x * x) / 50)
        sum += factor * down[reflect(row + y) * lowWidth + reflect(col + x)]
        weight += factor
      }
    }
    return sum / weight
  })
  const base = resizeElevation({ ...lowRaster, values: blur }, width, width).values
  const values = Float32Array.from({ length: size * size }, (_, index) => {
    const position = (Math.floor(index / size) + synthesisPadding) * width + index % size + synthesisPadding
    const transformed = round(residual[position] + base[position])
    return Math.sign(transformed) * transformed * transformed + sea
  })
  if (!values.every(Number.isFinite)) throw new Error('TD produced invalid elevations')
  return { width: size, height: size, values }
}

let running = false

export async function refineTerrain(
  base: URL, hash: string, device: WebGpuDevice, input: ElevationRaster, spanKm: number, sea: number,
  recipe: TerrainRecipe, signal: AbortSignal, progress: (progress: TerrainProgress) => void,
  onDeviceLost?: (message: string) => void,
  conditioning?: TerrainConditionGrid,
): Promise<ElevationRaster> {
  if (running) throw new Error('TD is already running')
  running = true
  try {
    const { seed, residualGain } = recipe
    const plan = makeTerrainPlan(spanKm)
    const conditions = conditioning ?? prepareTerrainConditions(input, spanKm)
    progress({ phase: 'manifest' })
    const cache = await openTerrainModelCache()
    const { data: manifestData } = await checkedAsset(base, 'manifest.json', hash, signal, undefined, cache)
    const manifest = JSON.parse(new TextDecoder().decode(manifestData)) as Manifest
    if (manifest.version !== 1) throw new Error('Unsupported TD manifest')
    progress({ phase: 'runtime' })
    const ort = await import('onnxruntime-web/all')
    signal.throwIfAborted()
    if (!ort.env.webgpu.adapter) {
      ort.env.wasm.numThreads = 1
      ort.env.wasm.wasmPaths = { wasm: new URL(wasmUrl, globalThis.location.href).href }
      ort.env.webgpu.adapter = device.adapter
    }
    const watched = new WeakSet<object>()
    const watchDevice = async () => {
      const gpu = await ort.env.webgpu.device as { lost: Promise<{ reason: string; message: string }> } | undefined
      if (!gpu?.lost || watched.has(gpu)) return
      watched.add(gpu)
      const { reason, message } = await gpu.lost
      if (reason !== 'destroyed' && !signal.aborted) onDeviceLost?.(message || reason)
    }
    const stage = async <Result>(name: TerrainStage, compute: (
      session: InferenceSession, step: () => Promise<void>, reportInference: (inference: CoarseInferenceProgress) => void,
    ) => Promise<Result>) => {
      let done = 0
      const total = plan.totals[name]
      const reportTiles = (inference?: CoarseInferenceProgress) => progress({ phase: 'tiles', stage: name, done, total, inference })
      const asset = manifest.models[name]
      const initialise = async () => {
        const { data, reusable } = await checkedAsset(base, `${name}.onnx`, asset.sha256, signal, {
          bytes: asset.bytes,
          reading: (received, source) => progress({ phase: source === 'cache' ? 'cacheRead' : 'download', stage: name, received, total: asset.bytes }),
          verifying: async () => {
            progress({ phase: 'verify', stage: name })
            await yieldTerrainTask(signal)
          },
          saving: () => progress({ phase: 'cacheWrite', stage: name }),
        }, cache)
        progress({ phase: 'initialize', stage: name, reusable })
        await yieldTerrainTask(signal)
        return ort.InferenceSession.create(data, { executionProviders: ['webgpu'], enableMemPattern: false })
      }
      const session = await initialise()
      try {
        if (onDeviceLost) void watchDevice().catch((error) => console.warn('Unable to monitor the terrain WebGPU device', error))
        reportTiles()
        await yieldTerrainTask(signal)
        return await compute(session, async () => {
          done += 1
          reportTiles()
          await yieldTerrainTask(signal)
        }, reportTiles)
      } finally { await session.release() }
    }
    const coarse = await stage('coarse', async (session, step, reportInference) => {
      const tiles = new Map<string, Float32Array>()
      for (const tile of plan.coarse) {
        const initial = terrainNoise(seed + 1, tile.row * coarseStride, tile.col * coarseStride, tileSize, 6)
          .map((value) => value * manifest.sigmaMax)
        const condition = coarseCondition(conditions, tile, sea, manifest, seed)
        const values = await sampleCoarseTile(ort.Tensor, session, manifest, condition, initial, signal, reportInference)
        const area = tileSize * tileSize
        for (let index = 0; index < values.length; index++) {
          const plane = Math.floor(index / area)
          const transformed = round(round(values[index] * manifest.stds[plane]) + manifest.means[plane])
          values[index] = plane === 1 ? values[index - area] - transformed : transformed
        }
        tiles.set(tileKey(tile), values)
        await step()
      }
      return tiles
    })
    const latent = await stage('base', async (session, step) => {
      const make = async (tiles: Tile[], angle: number, noiseSeed: number, previous?: Map<string, Float32Array>) => {
        const result = new Map<string, Float32Array>()
        const cosine = round(Math.cos(angle))
        const sine = round(Math.sin(angle))
        for (const tile of tiles) {
          const rect = latentArea(tile)
          const condition = latentCondition(stitchTiles(coarse, coarseArea(tile), tileSize, coarseStride, 6))
          const noise = terrainNoise(noiseSeed, rect.top, rect.left, tileSize, 5)
          const input = previous && stitchTiles(previous, rect, tileSize, latentStride, 5)
          const image = noise.map((value, index) => round(sine * value) + round(cosine * (input?.[index] ?? 0)))
          const output = await predict(ort.Tensor, session, image, tileSize, angle, condition)
          result.set(tileKey(tile), output.map((value, index) => round(sine * value) + round(cosine * image[index])))
          await step()
        }
        return result
      }
      return make(plan.final, secondAngle, seed + 5820, await make(plan.initial, initialAngle, seed + 5819))
    })
    const residual = await stage('decoder', async (session, step) => {
      const result = new Map<string, Float32Array>()
      const area = decoderSize * decoderSize
      const sine = round(Math.sin(initialAngle))
      const cosine = round(Math.cos(initialAngle))
      for (const tile of plan.decoder) {
        const condition = stitchTiles(latent, decoderInputArea(tile), tileSize, latentStride, 4)
        const noise = terrainNoise(seed + 5819, tile.row * decoderStride, tile.col * decoderStride, decoderSize, 1)
        const image = new Float32Array(5 * area)
        for (let index = 0; index < area; index++) {
          image[index] = noise[index] * sine
          const src = Math.floor(Math.floor(index / decoderSize) / latentScale) * tileSize + Math.floor(index % decoderSize / latentScale)
          for (let plane = 0; plane < 4; plane++) image[(plane + 1) * area + index] = condition[plane * tileSize * tileSize + src]
        }
        const output = await predict(ort.Tensor, session, image, decoderSize, initialAngle)
        result.set(tileKey(tile), output.map((value, index) => round(sine * value) + round(cosine * image[index])))
        await step()
      }
      progress({ phase: 'merge', stage: 'decoder' })
      await yieldTerrainTask(signal)
      const amplitude = manifest.residualStd * residualGain
      return stitchTiles(result, plan.padded, decoderSize, decoderStride, 1)
        .map((value) => round(value * amplitude) + manifest.residualMean)
    })
    progress({ phase: 'finalize' })
    await yieldTerrainTask(signal)
    const low = stitchTiles(latent, plan.low, tileSize, latentStride, 5)
    const donor = restoreElevation(residual, low.subarray(low.length * 4 / 5).map((value) => round(value * 38.6) - 31.4), plan.padded, plan.size, conditions.climate ? 0 : sea)
    if (recipe.method !== 'blend') return donor
    progress({ phase: 'blend' })
    return await blendTerrain(input, donor, spanKm / plan.size, recipe.preserveKm, sea, () => yieldTerrainTask(signal))
  } finally { running = false }
}
