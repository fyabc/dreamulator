import { GRID_H, GRID_W } from './temperatureDraft'

export interface TemperaturePreview {
  field: readonly number[]
  label: string
  stale: boolean
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
