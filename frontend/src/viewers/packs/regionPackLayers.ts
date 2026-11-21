import type { LonLat } from '../map/utils/mapCoords'
import type { ElevationRaster } from './elevationRaster'
import { lonLatToKm, type PackWindow } from './packCoords'
import type { PackMeta } from './types'

export const regionFields = {
  terrain: { field: 'elevation_m', unit: 'm', range: [-8000, 5000], colors: ['#0f2b51', '#427d98', '#79976a', '#a78b61', '#f5f0df'] },
  temperature: { field: 'temperature_mean_c', unit: '°C', range: [-40, 50], colors: ['#3b50a1', '#8dc9e5', '#fcf2bb', '#e99048', '#a73236'] },
  temperatureStd: { field: 'temperature_std_c', unit: '°C', range: [0, 30], colors: ['#eff7e2', '#7bc9b0', '#3b8fa2', '#354687', '#35154d'] },
  precipitation: { field: 'precipitation_total_mm', unit: 'mm/yr', range: [0, 3500], colors: ['#faf2db', '#addbb3', '#63b7ac', '#317d9d', '#214370'] },
  precipitationCv: { field: 'precipitation_cv_pct', unit: '%', range: [0, 250], colors: ['#eff7e2', '#7bc9b0', '#3b8fa2', '#354687', '#35154d'] },
  runoff: { field: 'runoff', unit: 'mm/yr', range: [0, 2000], colors: ['#faf2db', '#addbb3', '#63b7ac', '#317d9d', '#214370'] },
} as const

export const regionPackBaseLayers = ['terrain', 'temperature', 'temperatureStd', 'precipitation', 'precipitationCv', 'runoff'] as const
export type RegionPackBaseLayer = typeof regionPackBaseLayers[number]
export type RegionRasterSource = 'map' | 'source' | 'grid'

export function regionRasterSources(meta: PackMeta | null, layer: RegionPackBaseLayer): RegionRasterSource[] {
  const field = regionFields[layer].field
  const choices: RegionRasterSource[] = []
  if (layer === 'terrain' && meta?.height_source) choices.push('map')
  if (meta?.condition_layers?.source.includes(field)) choices.push('source')
  if (meta?.condition_layers?.grid.includes(field)) choices.push('grid')
  return choices
}

export function regionRasterSource(choices: RegionRasterSource[], requested?: RegionRasterSource): RegionRasterSource | undefined {
  if (requested && choices.includes(requested)) return requested
  return choices.includes('map') ? 'map' : choices[choices.length - 1]
}

export function regionFieldLabel(layer: RegionPackBaseLayer, source?: RegionRasterSource) {
  return `packs.conditions.${layer === 'temperature' && source === 'source' ? 'surfaceTemperature' : layer}`
}

export function regionFieldAt(point: LonLat, window: PackWindow, raster: ElevationRaster) {
  const { x, y } = lonLatToKm(point, window)
  if (Math.abs(x) > window.extentKmX / 2 + 1e-8 || Math.abs(y) > window.extentKmY / 2 + 1e-8) return undefined
  const col = Math.min(raster.width - 1, Math.max(0, Math.floor((0.5 + x / window.extentKmX) * raster.width)))
  const row = Math.min(raster.height - 1, Math.max(0, Math.floor((0.5 - y / window.extentKmY) * raster.height)))
  const value = raster.values[row * raster.width + col]
  return Number.isFinite(value) ? { row, col, value } : undefined
}
