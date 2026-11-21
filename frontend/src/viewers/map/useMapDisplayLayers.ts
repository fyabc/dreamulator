import { useMemo } from 'react'
import type { LayerState } from '../../components/map/MapLayerPanel'
import { inspectionLayerId } from '../../components/map/layerStateInit'
import type { MonthlyClimateData } from '../../api/monthlyClimate'
import type { ColorMode, CVTMesh, VoronoiCell } from './types'
import type { MapTemperatureTrialSession } from './useTemperatureTrialPreview'

const annualFields = {
  plates: 'plate_id', boundaries: 'crust_type',
  temperature: 'temperature_C', temperatureError: 'temperature_C',
  precipitation: 'precipitation_mm', precipitationError: 'precipitation_mm',
  pressure: 'pressure_anomaly_annual_hpa', slp: 'slp_annual_hpa', koppen: 'koppen_class',
  winds: 'wind_east_m_s', windError: 'wind_east_m_s',
  currents: 'ocean_current_east_m_s', currentError: 'ocean_current_east_m_s',
  biomes: 'biome', npp: 'npp_gc_m2_yr',
  soil: 'soil_type', provinces: 'biogeographic_province',
  habitable: 'habitability_score', agriculture: 'agriculture_score',
} satisfies Partial<Record<ColorMode, keyof VoronoiCell>>

export function availableTrialLayers(hasTemperature: boolean): ReadonlySet<ColorMode> {
  return new Set<ColorMode>(hasTemperature ? ['terrain', 'landsea', 'coastlines', 'temperature'] : ['terrain', 'landsea', 'coastlines'])
}

export function availableWorldLayers(mesh: CVTMesh | null, monthly: MonthlyClimateData | null, hasUcc: boolean) {
  const available = new Set<ColorMode>(['terrain', 'landsea', 'coastlines'])
  for (const [id, field] of Object.entries(annualFields)) {
    if (mesh?.cells.some(cell => cell[field] != null)) available.add(id as ColorMode)
  }
  if (mesh?.cells.some(cell => cell.boundary_type != null)) available.add('boundaries')
  if (mesh?.cells.some(cell => cell.domesticable_tags?.length)) available.add('domesticable')
  if (hasUcc) available.add('ucc')
  if (monthly?.tMonthly.length) available.add('temperature')
  if (monthly?.pMonthly.length) available.add('precipitation')
  if (monthly?.pressureMonthly?.length) available.add('pressure')
  if (monthly?.slpMonthly?.length) available.add('slp')
  if (monthly?.windEastMonthly?.length) available.add('winds')
  if (monthly?.pressureMonthly?.length || (!monthly && (available.has('pressure') || available.has('slp')))) available.add('pressureError')
  return available
}

export function useMapDisplayLayers(trial: MapTemperatureTrialSession, official: LayerState,
  setOfficial: (state: LayerState) => void, mesh: CVTMesh | null, monthly: MonthlyClimateData | null, hasUcc: boolean) {
  const trialMode = trial.mode === 'trial' && !trial.ebm
  const hasTrialTemperature = Boolean(trial.preview)
  const available = useMemo(() => trialMode ? availableTrialLayers(hasTrialTemperature) : availableWorldLayers(mesh, monthly, hasUcc),
    [trialMode, hasTrialTemperature, mesh, monthly, hasUcc])
  return {
    state: trialMode ? trial.layerState : official,
    onChange: trialMode ? trial.setLayerState : setOfficial,
    available,
    trialInspectionLayer: inspectionLayerId(trial.layerState),
    texture: trial.layerState.layers.temperature > 0 ? trial.texture : null,
  }
}
