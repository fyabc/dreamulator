export interface Rect {
  top: number
  left: number
  bottom: number
  right: number
}

export const minTerrainSpanKm = 45
export const maxTerrainSpanKm = 184
const conditionKm = 23
const pixelsPerCell = 256
export const conditioningPadding = 64
export const latentScale = 8
export const synthesisPadding = 6 * latentScale
export const tileSize = 64
export const coarseStride = 48
export const latentStride = 32
export const decoderSize = 512
export const decoderStride = 384

export interface Tile {
  row: number
  col: number
}

export function square(top: number, left: number, size: number): Rect {
  return { top, left, bottom: top + size, right: left + size }
}

export function coveringTiles(rect: Rect, size: number, stride: number): Tile[] {
  const result = []
  for (let row = Math.floor((rect.top - size) / stride) + 1; row * stride < rect.bottom; row++) {
    for (let col = Math.floor((rect.left - size) / stride) + 1; col * stride < rect.right; col++) {
      result.push({ row, col })
    }
  }
  return result
}

export const unionTiles = (tiles: Tile[]) => [...new Map(tiles.map((tile) => [tileKey(tile), tile])).values()]
export const tileKey = ({ row, col }: Tile) => `${row},${col}`

export function latentArea({ row, col }: Tile) {
  return square(row * latentStride, col * latentStride, tileSize)
}

export function coarseArea({ row, col }: Tile) {
  return square(row - 1, col - 1, 4)
}

export function decoderInputArea({ row, col }: Tile) {
  return square(row * decoderStride / latentScale, col * decoderStride / latentScale, decoderSize / latentScale)
}

export function supportsTerrainSpan(spanKm: number) {
  return spanKm >= minTerrainSpanKm && spanKm <= maxTerrainSpanKm
}

export function makeTerrainPlan(spanKm: number) {
  if (!supportsTerrainSpan(spanKm)) throw new Error('TD window out of range')
  const inputSize = Math.round(spanKm / conditionKm)
  const size = inputSize * pixelsPerCell
  const origin = conditioningPadding * pixelsPerCell
  const padded = square(origin - synthesisPadding, origin - synthesisPadding, size + 2 * synthesisPadding)
  const low = square(padded.top / latentScale, padded.left / latentScale, (size + 2 * synthesisPadding) / latentScale)
  const decoder = coveringTiles(padded, decoderSize, decoderStride)
  const final = unionTiles([...decoder.map(decoderInputArea), low].flatMap((rect) => coveringTiles(rect, tileSize, latentStride)))
  const initial = unionTiles(final.flatMap((tile) => coveringTiles(latentArea(tile), tileSize, latentStride)))
  const coarse = unionTiles(initial.flatMap((tile) => coveringTiles(coarseArea(tile), tileSize, coarseStride)))
  const totals = { coarse: coarse.length, base: initial.length + final.length, decoder: decoder.length }
  return { size, inputSize, totals, padded, low, decoder, final, initial, coarse }
}

export function tileWeights(size: number) {
  const middle = (size - 1) / 2
  return Float32Array.from({ length: size }, (_, position) => 1 - 0.999 * Math.abs(position - middle) / middle)
}

export function stitchTiles(tiles: Map<string, Float32Array>, rect: Rect, size: number, stride: number, planes: number) {
  const width = rect.right - rect.left
  const area = width * (rect.bottom - rect.top)
  const output = new Float32Array(planes * area)
  const total = new Float32Array(area)
  const weights = tileWeights(size)
  for (const tile of coveringTiles(rect, size, stride)) {
    const values = tiles.get(tileKey(tile))
    if (!values) throw new Error('Missing terrain tile')
    const top = tile.row * stride
    const left = tile.col * stride
    for (let row = Math.max(rect.top, top); row < Math.min(rect.bottom, top + size); row++) {
      for (let col = Math.max(rect.left, left); col < Math.min(rect.right, left + size); col++) {
        const index = (row - rect.top) * width + col - rect.left
        const tileIndex = (row - top) * size + col - left
        const weight = Math.fround(weights[row - top] * weights[col - left])
        total[index] += weight
        for (let plane = 0; plane < planes; plane++) {
          output[plane * area + index] += Math.fround(weight * values[plane * size * size + tileIndex])
        }
      }
    }
  }
  return output.map((value, index) => value / total[index % area])
}

export function terrainNoise(seed: number, top: number, left: number, size: number, planes: number) {
  const result = new Float32Array(planes * size * size)
  for (const tile of coveringTiles(square(top, left, size), size, size)) {
    const tileTop = tile.row * size
    const tileLeft = tile.col * size
    const golden = 0x9e3779b9n
    let state = (BigInt(seed) * golden + BigInt(tile.row >>> 0)) * golden + BigInt(tile.col >>> 0)
    const uniform = () => {
      state = BigInt.asUintN(64, state * 6364136223846793005n + 1442695040888963407n)
      const bits = Number(BigInt.asUintN(32, ((state >> 18n) ^ state) >> 27n))
      const rotation = Number(state >> 59n)
      const value = ((bits >>> rotation) | (bits << ((32 - rotation) & 31))) >>> 0
      return 2 * (value + 1) / 4294967296 - 1
    }
    let index = 0
    const put = (value: number) => {
      const plane = Math.floor(index / (size * size))
      const row = tileTop + Math.floor(index / size) % size - top
      const col = tileLeft + index % size - left
      if (row >= 0 && row < size && col >= 0 && col < size) result[(plane * size + row) * size + col] = value
      index++
    }
    while (index < result.length) {
      const first = uniform()
      const second = uniform()
      const radius = first * first + second * second
      if (radius <= 0 || radius >= 1) continue
      const scale = Math.sqrt(-2 * Math.log(radius) / radius)
      put(first * scale)
      if (index < result.length) put(second * scale)
    }
  }
  return result
}
