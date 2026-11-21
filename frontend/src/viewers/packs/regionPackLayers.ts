import type { LonLat } from '../map/utils/mapCoords'
import type { ElevationRaster } from './elevationRaster'
import { lonLatToKm, type PackWindow } from './packCoords'
import type { PackMeta, RiverData } from './types'

export const regionFields = {
  terrain: { field: 'elevation_m', unit: 'm', range: [-8000, 5000], colors: ['#0f2b51', '#427d98', '#79976a', '#a78b61', '#f5f0df'] },
  temperature: { field: 'temperature_mean_c', unit: '°C', range: [-40, 50], colors: ['#3b50a1', '#8dc9e5', '#fcf2bb', '#e99048', '#a73236'] },
  temperatureStd: { field: 'temperature_std_c', unit: '°C', range: [0, 30], colors: ['#eff7e2', '#7bc9b0', '#3b8fa2', '#354687', '#35154d'] },
  precipitation: { field: 'precipitation_total_mm', unit: 'mm/yr', range: [0, 3500], colors: ['#faf2db', '#addbb3', '#63b7ac', '#317d9d', '#214370'] },
  precipitationCv: { field: 'precipitation_cv_pct', unit: '%', range: [0, 250], colors: ['#eff7e2', '#7bc9b0', '#3b8fa2', '#354687', '#35154d'] },
  runoff: { field: 'runoff', unit: 'mm/yr', range: [0, 2000], colors: ['#faf2db', '#addbb3', '#63b7ac', '#317d9d', '#214370'] },
} as const

export const regionConditionLayers = ['terrain', 'temperature', 'temperatureStd', 'precipitation', 'precipitationCv'] as const
export const regionFieldLayers = [...regionConditionLayers, 'runoff'] as const
export const regionPackBaseLayers = ['mapElevation', ...regionFieldLayers] as const
export type RegionFieldLayer = typeof regionFieldLayers[number]
export type RegionPackBaseLayer = typeof regionPackBaseLayers[number]
export type RegionRasterSource = 'source' | 'grid'

export function regionConditionSources(meta: PackMeta | null) {
  return (['source', 'grid'] as const).filter(source =>
    regionConditionLayers.some(layer => meta?.condition_layers?.[source].includes(regionFields[layer].field)))
}

export function regionFieldSource(meta: PackMeta | null, layer: RegionFieldLayer, selected: RegionRasterSource) {
  const source = layer === 'runoff' ? 'source' : selected
  return meta?.condition_layers?.[source].includes(regionFields[layer].field) ? source : undefined
}

export function regionFieldLabel(layer: RegionPackBaseLayer, source?: RegionRasterSource) {
  if (layer === 'mapElevation') return 'packs.conditions.map'
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

const riverSnapKm = 2

export function indexRegionRivers(rivers: RiverData) {
  const buckets = new Map<string, { x: number; y: number; index: number }[]>()
  rivers.segs.forEach((segment, index) => {
    if (!Number.isFinite(rivers.flows[index])) return
    for (const [y, x] of segment) {
      const key = `${Math.floor(x / riverSnapKm)}:${Math.floor(y / riverSnapKm)}`
      const bucket = buckets.get(key) ?? []
      bucket.push({ x, y, index })
      buckets.set(key, bucket)
    }
  })
  return ({ x, y }: { x: number; y: number }) => {
    const column = Math.floor(x / riverSnapKm)
    const row = Math.floor(y / riverSnapKm)
    let closest = Infinity
    let distance = riverSnapKm ** 2
    for (let dy = -1; dy <= 1; dy++) {
      for (let dx = -1; dx <= 1; dx++) {
        for (const endpoint of buckets.get(`${column + dx}:${row + dy}`) ?? []) {
          const squared = (x - endpoint.x) ** 2 + (y - endpoint.y) ** 2
          if (squared < distance || (squared === distance && endpoint.index < closest)) {
            closest = endpoint.index
            distance = squared
          }
        }
      }
    }
    return Number.isFinite(closest) ? { flow: rivers.flows[closest], regime: rivers.regimes[closest] } : undefined
  }
}
