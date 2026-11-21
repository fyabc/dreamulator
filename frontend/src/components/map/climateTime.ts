import type { TFunction } from 'i18next'
import type { MonthlyClimateData } from '../../api/monthlyClimate'
import type { VoronoiCell } from '../../viewers/map/types'
import type { TrialTerrain } from '../../playground/temperaturePreview'
import { GRID_H, GRID_W } from '../../playground/temperatureDraft'
import type { MonthlyField } from '../../viewers/map/useMonthlyClimate'
import { observedSlpAnomAt } from '../../viewers/map/spatialReference'
import {
  PRECIP_SCALE, PRECIP_WINDOW_LIMIT_MM, TEMPERATURE_SCALE, sequentialColor, temperatureColor,
} from '../../viewers/map/utils/colorScales'

export const monthlyLayers = {
  temperature: { field: 'tMonthly', unit: '°C', landOnly: true, color: temperatureColor },
  precipitation: { field: 'pMonthly', unit: 'mm', landOnly: true, color: (value: number) =>
    sequentialColor(Math.log10(Math.max(value, 0) + 1) / Math.log10(PRECIP_WINDOW_LIMIT_MM + 1), PRECIP_SCALE) },
  pressure: { field: 'pressureMonthly', unit: 'hPa', landOnly: false, color: pressureColor },
  pressureError: { field: 'pressureMonthly', unit: 'hPa', landOnly: false, color: pressureColor },
  slp: { field: 'slpMonthly', unit: 'hPa', landOnly: false, color: (value: number) =>
    sequentialColor((value - 1013.25) / 80 + 0.5, TEMPERATURE_SCALE) },
  winds: { field: 'windEastMonthly', unit: 'm/s', landOnly: false, color: () => [118, 201, 218] },
} as const satisfies Record<MonthlyField | 'winds', { field: keyof MonthlyClimateData; unit: string; landOnly: boolean; color: (value: number) => readonly number[] }>

function pressureColor(value: number) {
  return sequentialColor((value + 20) / 40, TEMPERATURE_SCALE)
}

export type MonthlyLayer = keyof typeof monthlyLayers

export function isMonthlyLayer(layer: string | null): layer is MonthlyLayer {
  return layer != null && Object.prototype.hasOwnProperty.call(monthlyLayers, layer)
}

export function monthFromSearch(params: URLSearchParams): number {
  const month = params.get('month')
  const legacySeason = Number(params.get('season'))
  const legacyMonthly = params.get('monthly') === '1' || params.get('play') === '1'
  const index = month == null ? legacyMonthly ? Math.round(legacySeason / 30) : 0 : Number(month)
  return Number.isInteger(index) ? ((index % 12) + 12) % 12 : 0
}

export function climateWindowLabel(t: TFunction<'map'>, data: MonthlyClimateData | null, index: number) {
  if (data?.month0 === 'vernal_equinox') {
    const months = t('months', { returnObjects: true }) as unknown as string[]
    if (months[index]) return months[index]
  }
  return t('time.windowNumber', { number: index + 1 })
}

export function countSubzeroMonths(months: number, temperatureAt: (month: number) => number) {
  if (months !== 12) return null
  let count = 0
  for (let month = 0; month < months; month++) {
    const temperature = temperatureAt(month)
    if (!Number.isFinite(temperature)) return null
    if (temperature < 0) count++
  }
  return count
}

export function officialMonthlyMeans(layer: MonthlyLayer, data: MonthlyClimateData, cells: readonly VoronoiCell[]) {
  const spec = monthlyLayers[layer]
  const values = data[spec.field]
  const size = cells.length * data.months
  const north = data.windNorthMonthly
  if (!data.months || data.numCells !== cells.length || values?.length !== size) return undefined
  if (layer === 'winds' && north?.length !== size) return undefined
  const pressure = layer === 'pressure' || layer === 'pressureError' || layer === 'slp'
  const validCells = cells.map((cell, index) => ({ cell, index })).filter(({ cell }) => {
    if (pressure && cell.slp_reduction_unreliable) return false
    return !spec.landOnly || (cell.water_class != null ? cell.water_class !== 'ocean' : cell.elevation >= 0)
  })
  const hasArea = validCells.every(({ cell }) => cell.area_km2 != null && Number.isFinite(cell.area_km2) && cell.area_km2 > 0)
  return Array.from({ length: data.months }, (_, month) => {
    let weight = 0
    let sum = 0
    for (const { cell, index } of validCells) {
      const offset = index * data.months + month
      let value = values[offset]
      if (layer === 'winds' && north) value = Math.hypot(value, north[offset])
      if (layer === 'pressureError') {
        const observed = observedSlpAnomAt(cell.lat, cell.lon, (month + 2) % 12)
        if (observed < -50) continue
        value -= observed
      }
      if (!Number.isFinite(value)) continue
      const area = hasArea ? cell.area_km2! : 1
      sum += value * area
      weight += area
    }
    return weight > 0 ? sum / weight : NaN
  })
}

export function trialLandTemperatureMeans(fields: readonly (readonly number[])[], { elevation, params }: TrialTerrain) {
  const isLand = (height: number) => params.elevMinM + height * (params.elevMaxM - params.elevMinM) > params.seaLevelM
  const weights = elevation.map((height, index) => isLand(height)
    ? Math.sin(Math.PI * (Math.floor(index / GRID_W) + 0.5) / GRID_H) : 0)
  return fields.map(field => {
    let weight = 0
    let sum = 0
    for (let index = 0; index < field.length; index++) {
      if (!weights[index] || !Number.isFinite(field[index])) continue
      sum += field[index] * weights[index]
      weight += weights[index]
    }
    return weight > 0 ? sum / weight : NaN
  })
}
