import type { MonthlyClimateData } from '../../api/monthlyClimate'
import { observedPrecipAt, observedSlpAnomAt, observedTempAt } from './spatialReference'
import type { VoronoiCell } from './types'
import {
  AGRICULTURE_SCALE, HABITABILITY_SCALE, NPP_SCALE, PRECIP_SCALE, PRECIP_TOTAL_LIMIT_MM,
  PRECIP_WINDOW_LIMIT_MM, TEMPERATURE_LIMIT_C, TEMPERATURE_SCALE, sequentialColor, type ColorStop,
} from './utils/colorScales'

type ScalarDefinition = {
  annual?: keyof VoronoiCell
  monthly?: 'tMonthly' | 'pMonthly' | 'pressureMonthly' | 'slpMonthly'
  landOnly?: boolean
  maskPressure?: boolean
}

export const scalarFields = {
  temperature: { annual: 'temperature_C', monthly: 'tMonthly' },
  precipitation: { annual: 'precipitation_mm', monthly: 'pMonthly' },
  pressure: { annual: 'pressure_anomaly_annual_hpa', monthly: 'pressureMonthly', maskPressure: true },
  slp: { annual: 'slp_annual_hpa', monthly: 'slpMonthly', maskPressure: true },
  npp: { annual: 'npp_gc_m2_yr', landOnly: true },
  habitable: { annual: 'habitability_score', landOnly: true },
  agriculture: { annual: 'agriculture_score', landOnly: true },
  temperatureError: { annual: 'temperature_C', landOnly: true },
  precipitationError: { annual: 'precipitation_mm', landOnly: true },
  pressureError: { monthly: 'pressureMonthly', maskPressure: true },
} as const satisfies Record<string, ScalarDefinition>

export type ScalarLayer = keyof typeof scalarFields
export type MonthlyScalarLayer = { [Layer in ScalarLayer]: 'monthly' extends keyof typeof scalarFields[Layer] ? Layer : never }[ScalarLayer]
export type ScalarScale = { min: number; max: number; unit: string; stops: ColorStop[]; log?: boolean }

export function isScalarLayer(layer: string | null): layer is ScalarLayer {
  return layer != null && Object.prototype.hasOwnProperty.call(scalarFields, layer)
}

export function isOceanCell(cell: Pick<VoronoiCell, 'water_class' | 'elevation'>, seaLevelM: number) {
  return cell.water_class != null ? cell.water_class === 'ocean' : cell.elevation < seaLevelM
}

export function isLandOnlyScalar(layer: ScalarLayer) {
  return Boolean((scalarFields[layer] as ScalarDefinition).landOnly)
}

export function scalarMonthValues(layer: ScalarLayer, data: MonthlyClimateData | null) {
  const field = (scalarFields[layer] as ScalarDefinition).monthly
  return field && data ? data[field] : undefined
}

export function scalarValue(layer: ScalarLayer, cell: VoronoiCell, seaLevelM: number,
  monthValues?: Float32Array, offset = 0, month = 0) {
  const { annual, landOnly, maskPressure }: ScalarDefinition = scalarFields[layer]
  if ((landOnly && isOceanCell(cell, seaLevelM)) || (maskPressure && cell.slp_reduction_unreliable)) return NaN
  const value = monthValues ? monthValues[offset] : annual ? cell[annual] : undefined
  if (typeof value !== 'number' || !Number.isFinite(value)) return NaN
  if (layer === 'temperatureError') return value - observedTempAt(cell.lat, cell.lon)
  if (layer === 'precipitationError') return value - observedPrecipAt(cell.lat, cell.lon)
  if (layer === 'pressureError') {
    const observed = observedSlpAnomAt(cell.lat, cell.lon, (month + 2) % 12)
    return observed < -50 ? NaN : value - observed
  }
  return value
}

export function scalarScale(layer: ScalarLayer, monthly: boolean, cells: readonly VoronoiCell[] = [], seaLevelM = 0): ScalarScale {
  const diverging = (min: number, max: number, unit: string) => ({ min, max, unit, stops: TEMPERATURE_SCALE })
  switch (layer) {
    case 'temperature': return diverging(-TEMPERATURE_LIMIT_C, TEMPERATURE_LIMIT_C, '°C')
    case 'precipitation': return { min: 0, max: monthly ? PRECIP_WINDOW_LIMIT_MM : PRECIP_TOTAL_LIMIT_MM, unit: 'mm', stops: PRECIP_SCALE, log: true }
    case 'pressure': return monthly ? diverging(-20, 20, 'hPa') : diverging(-5, 5, 'hPa')
    case 'slp': return diverging(973.25, 1053.25, 'hPa')
    case 'temperatureError': return diverging(-20, 20, '°C')
    case 'precipitationError': return diverging(-2000, 2000, 'mm')
    case 'pressureError': return diverging(-20, 20, 'hPa')
    case 'habitable': return { min: 0, max: 100, unit: '', stops: HABITABILITY_SCALE }
    case 'agriculture': return { min: 0, max: 100, unit: '', stops: AGRICULTURE_SCALE }
    case 'npp': {
      const max = cells.reduce((highest, cell) => {
        const value = scalarValue('npp', cell, seaLevelM)
        return value > highest ? value : highest
      }, 0)
      return { min: 0, max: max || 1425, unit: 'gC/m²/yr', stops: NPP_SCALE }
    }
  }
}

export function scalarColor(scale: ScalarScale, value: number) {
  const fraction = scale.log ? Math.log1p(Math.max(0, value)) / Math.log1p(scale.max) : (value - scale.min) / (scale.max - scale.min)
  return sequentialColor(fraction, scale.stops)
}
