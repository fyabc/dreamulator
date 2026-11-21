import { GRID_H, GRID_W } from './temperatureDraft'

export interface TemperaturePreview {
  field: readonly number[]
  label: string
  stale: boolean
  period: 'annual' | number
  periods: readonly { label: string; modelIndex: number }[]
  selectPeriod: (period: 'annual' | number) => void
}

export function sampleTemperature(field: readonly number[], { lon, lat }: { lon: number; lat: number }) {
  const column = Math.floor((((lon + 180) % 360 + 360) % 360) / 360 * GRID_W)
  const row = Math.max(0, Math.min(GRID_H - 1, Math.floor((90 - lat) / 180 * GRID_H)))
  return field[row * GRID_W + column]
}

export function summarizeTemperature(field: readonly number[], width = field.length) {
  if (!field.length) return null
  const height = field.length / width
  let weightedSum = 0
  let totalWeight = 0
  let min = Infinity
  let max = -Infinity
  for (let row = 0; row < height; row++) {
    const weight = Math.sin(Math.PI * (row + 0.5) / height)
    for (let column = 0; column < width; column++) {
      const value = field[row * width + column]
      weightedSum += value * weight
      totalWeight += weight
      min = Math.min(min, value)
      max = Math.max(max, value)
    }
  }
  return { mean: weightedSum / totalWeight, min, max }
}

const STOPS = [
  [-40, [49, 54, 149]],
  [-20, [69, 117, 180]],
  [0, [255, 255, 191]],
  [20, [253, 174, 97]],
  [40, [165, 0, 38]],
] as const

export const TEMPERATURE_GRADIENT = `linear-gradient(90deg, ${STOPS.map(([, color]) => `rgb(${color.join(',')})`).join(', ')})`

export function temperatureColor(value: number): readonly [number, number, number] {
  const clamped = Math.max(-40, Math.min(40, value))
  for (let index = 1; index < STOPS.length; index++) {
    const [upper, end] = STOPS[index]
    const [lower, start] = STOPS[index - 1]
    if (clamped <= upper) {
      const fraction = (clamped - lower) / (upper - lower)
      const channel = (index: 0 | 1 | 2) => Math.round(start[index] + (end[index] - start[index]) * fraction)
      return [channel(0), channel(1), channel(2)]
    }
  }
  return STOPS[STOPS.length - 1][1]
}

export function temperaturePreviewPixels(field: readonly number[]) {
  const pixels = new Uint8Array(GRID_W * GRID_H * 4)
  for (let row = 0; row < GRID_H; row++) {
    for (let column = 0; column < GRID_W; column++) {
      const value = field[(GRID_H - 1 - row) * GRID_W + column]
      const offset = (row * GRID_W + column) * 4
      pixels.set(temperatureColor(value), offset)
      pixels[offset + 3] = 255
    }
  }
  return pixels
}
