import { GRID_H, GRID_W, type PlanetParams } from './temperatureDraft'
import { scaleGradient, temperatureColor, TEMPERATURE_SCALE } from '../viewers/map/utils/colorScales'

export interface TrialTerrain {
  elevation: Float32Array
  params: PlanetParams
}

export interface TemperaturePreview {
  field: readonly number[]
  terrain: TrialTerrain
  monthly: readonly (readonly number[])[]
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

export const TEMPERATURE_GRADIENT = scaleGradient(TEMPERATURE_SCALE)

export function temperaturePreviewPixels(field: readonly number[], terrain: TrialTerrain) {
  const pixels = new Uint8Array(GRID_W * GRID_H * 4)
  const { elevMinM, elevMaxM, seaLevelM } = terrain.params
  const span = elevMaxM - elevMinM
  for (let row = 0; row < GRID_H; row++) {
    for (let column = 0; column < GRID_W; column++) {
      const index = (GRID_H - 1 - row) * GRID_W + column
      const value = field[index]
      if (!Number.isFinite(value) || elevMinM + terrain.elevation[index] * span <= seaLevelM) continue
      const offset = (row * GRID_W + column) * 4
      pixels.set(temperatureColor(value), offset)
      pixels[offset + 3] = 255
    }
  }
  return pixels
}
