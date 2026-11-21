import type { MonthlyClimateData } from '../../api/monthlyClimate'
import type { VoronoiCell } from './types'
import { PRECIP_SCALE, PRECIP_TOTAL_LIMIT_MM, PRECIP_WINDOW_LIMIT_MM, TEMPERATURE_SCALE, sequentialColor, temperatureColor } from './utils/colorScales'

export const downscaledFields = {
  temperature: ['temperature_C', 'tMonthly'],
  precipitation: ['precipitation_mm', 'pMonthly'],
  pressure: ['pressure_anomaly_annual_hpa', 'pressureMonthly'],
  slp: ['slp_annual_hpa', 'slpMonthly'],
} as const satisfies Record<string, readonly [keyof VoronoiCell, keyof MonthlyClimateData]>

export type DownscaledField = keyof typeof downscaledFields

export function canDownscale(layer: string | null): layer is DownscaledField {
  return layer != null && Object.prototype.hasOwnProperty.call(downscaledFields, layer)
}

export function climateSourceDimensions(cellCount: number, meshWidth: number, meshHeight: number) {
  const gridHeight = Math.min(meshHeight, Math.max(16, Math.ceil(Math.sqrt(cellCount * 2))))
  return { gridWidth: Math.min(meshWidth, gridHeight * 2), gridHeight }
}

export interface ClimateRasterTerrain {
  elevation: Float32Array
  width: number
  height: number
  minM: number
  maxM: number
  seaLevelM: number
}

interface ClimateGrid {
  width: number
  height: number
  values: Float32Array
  modelHeight?: Float32Array
  lapse?: Float32Array
}

export function temperatureLapseCPerM(annualPrecipitationMm: number) {
  return Math.max(-9.8, Math.min(-4, -6.5 + 0.0015 * annualPrecipitationMm)) / 1000
}

function blend(topLeft: number, topRight: number, bottomLeft: number, bottomRight: number, east: number, south: number) {
  if (Number.isFinite(topLeft) && Number.isFinite(topRight) && Number.isFinite(bottomLeft) && Number.isFinite(bottomRight)) {
    return (topLeft * (1 - east) + topRight * east) * (1 - south) + (bottomLeft * (1 - east) + bottomRight * east) * south
  }
  const nw = Number.isFinite(topLeft) ? (1 - east) * (1 - south) : 0
  const ne = Number.isFinite(topRight) ? east * (1 - south) : 0
  const sw = Number.isFinite(bottomLeft) ? (1 - east) * south : 0
  const se = Number.isFinite(bottomRight) ? east * south : 0
  const weight = nw + ne + sw + se
  return weight > 0 ? ((nw ? nw * topLeft : 0) + (ne ? ne * topRight : 0) +
    (sw ? sw * bottomLeft : 0) + (se ? se * bottomRight : 0)) / weight : NaN
}

function sample(grid: Float32Array, nw: number, ne: number, sw: number, se: number, east: number, south: number) {
  return blend(grid[nw], grid[ne], grid[sw], grid[se], east, south)
}

export function climateRasterPixels(grid: ClimateGrid, width: number, height: number,
  color: (value: number) => readonly number[], surface?: (column: number, row: number) => number) {
  const pixels = new Uint8Array(width * height * 4)
  const columns = Array.from({ length: width }, (_, column) => {
    const position = (column + 0.5) * grid.width / width - 0.5
    const west = Math.floor(position)
    return { west: (west + grid.width) % grid.width, east: (west + 1) % grid.width, fraction: position - west }
  })
  for (let row = 0; row < height; row++) {
    const position = Math.max(0, Math.min(grid.height - 1, (row + 0.5) * grid.height / height - 0.5))
    const north = Math.floor(position)
    const south = Math.min(north + 1, grid.height - 1)
    for (let column = 0; column < width; column++) {
      const fineHeight = surface ? surface(column, row) : 0
      if (!Number.isFinite(fineHeight)) continue
      const { west, east, fraction } = columns[column]
      const nw = north * grid.width + west, ne = north * grid.width + east
      const sw = south * grid.width + west, se = south * grid.width + east
      let value = sample(grid.values, nw, ne, sw, se, fraction, position - north)
      if (!Number.isFinite(value)) continue
      if (grid.modelHeight && grid.lapse) {
        const modelHeight = sample(grid.modelHeight, nw, ne, sw, se, fraction, position - north)
        const lapse = sample(grid.lapse, nw, ne, sw, se, fraction, position - north)
        if (Number.isFinite(lapse) && Number.isFinite(modelHeight)) value += lapse * (fineHeight - modelHeight)
      }
      const offset = ((height - 1 - row) * width + column) * 4
      pixels.set(color(value), offset)
      pixels[offset + 3] = 255
    }
  }
  return pixels
}

export function climateRasterSurface(terrain: ClimateRasterTerrain, width: number, height: number) {
  const span = terrain.maxM - terrain.minM
  return (column: number, row: number) => {
    const sourceX = Math.floor((column + 0.5) * terrain.width / width)
    const sourceY = Math.floor((row + 0.5) * terrain.height / height)
    const aboveSea = terrain.minM + terrain.elevation[sourceY * terrain.width + sourceX] * span - terrain.seaLevelM
    return aboveSea > 0 ? aboveSea : NaN
  }
}

export function downscaledClimatePixels(
  field: DownscaledField, cells: readonly VoronoiCell[], cellIds: Uint32Array, meshWidth: number, meshHeight: number,
  width: number, height: number, seaLevelM: number, native: ClimateRasterTerrain | null,
  data: MonthlyClimateData | null, month: number | null,
) {
  const [annualKey, monthlyKey] = downscaledFields[field]
  const monthly = month != null ? data?.[monthlyKey] : undefined
  const landOnly = field === 'temperature' || field === 'precipitation'
  const correctHeight = field === 'temperature' && native != null
  const byId = new Map(cells.map((cell, index) => [cell.id, index]))
  const valid = cells.map(cell => landOnly ? cell.water_class != null ? cell.water_class !== 'ocean' : cell.elevation >= seaLevelM
    : !cell.slp_reduction_unreliable)
  const values = cells.map((cell, index) => valid[index] ? monthly && data && month != null
    ? monthly[index * data.months + month] : cell[annualKey] ?? NaN : NaN)
  if (!values.some(Number.isFinite)) return null

  const { gridWidth, gridHeight } = climateSourceDimensions(cells.length, meshWidth, meshHeight)
  const count = gridWidth * gridHeight
  const grid: ClimateGrid = { width: gridWidth, height: gridHeight, values: new Float32Array(count).fill(NaN) }
  if (correctHeight) {
    grid.modelHeight = new Float32Array(count).fill(NaN)
    grid.lapse = new Float32Array(count).fill(NaN)
  }
  const lapse = correctHeight ? cells.map((cell, index) => {
    let precipitation = cell.precipitation_mm ?? NaN
    if (data && data.pMonthly.length === cells.length * data.months) {
      let sum = 0
      for (let period = 0; period < data.months; period++) sum += data.pMonthly[index * data.months + period]
      if (Number.isFinite(sum)) precipitation = sum
    }
    return Number.isFinite(precipitation) ? temperatureLapseCPerM(precipitation) : NaN
  }) : null
  for (let row = 0; row < gridHeight; row++) {
    for (let column = 0; column < gridWidth; column++) {
      const x = Math.round((column + 0.5) * (meshWidth - 1) / gridWidth)
      const y = Math.round((row + 0.5) * (meshHeight - 1) / gridHeight)
      const cell = byId.get(cellIds[y * meshWidth + x])
      if (cell == null) continue
      const point = row * gridWidth + column
      grid.values[point] = values[cell]
      if (Number.isFinite(values[cell]) && grid.modelHeight && grid.lapse && lapse) {
        grid.modelHeight[point] = Math.max(0, cells[cell].elevation - seaLevelM)
        grid.lapse[point] = lapse[cell]
      }
    }
  }
  const surface = native && landOnly ? climateRasterSurface(native, width, height) : (column: number, row: number) => {
    const columnAt = Math.floor((column + 0.5) * meshWidth / width)
    const rowAt = Math.floor((row + 0.5) * meshHeight / height)
    const index = byId.get(cellIds[rowAt * meshWidth + columnAt])
    return index != null && valid[index] ? 0 : NaN
  }
  const precipLimit = monthly ? PRECIP_WINDOW_LIMIT_MM : PRECIP_TOTAL_LIMIT_MM
  const color = field === 'temperature' ? temperatureColor : (value: number) => {
    if (field === 'precipitation') return sequentialColor(Math.log10(Math.max(value, 0) + 1) / Math.log10(precipLimit + 1), PRECIP_SCALE)
    if (field === 'slp') return sequentialColor((value - 1013.25) / 80 + 0.5, TEMPERATURE_SCALE)
    return sequentialColor(value / (monthly ? 40 : 10) + 0.5, TEMPERATURE_SCALE)
  }
  return climateRasterPixels(grid, width, height, color, surface)
}
