import type { ElevationRaster } from './elevationRaster'

export const terrainConditionVersion = 'region-td-grid-v1'
const coarseKm = 23

export type TerrainClimateConditions = {
  temperature_mean_c: Float32Array
  temperature_std_c: Float32Array
  precipitation_total_mm: Float32Array
  precipitation_cv_pct: Float32Array
}

export type TerrainConditionGrid = {
  version: typeof terrainConditionVersion
  elevation: ElevationRaster
  climate?: TerrainClimateConditions
}

export const terrainClimateFields = ['temperature_mean_c', 'temperature_std_c', 'precipitation_total_mm', 'precipitation_cv_pct'] as const

export type TerrainConditionSnapshot = {
  version: typeof terrainConditionVersion
  size: number
  elevation_m: number[]
  climate?: Record<typeof terrainClimateFields[number], number[]>
}

export const terrainLapseRate = (annualPrecipitationMm: number) => Math.max(-9.8, Math.min(-4, -6.5 + 0.0015 * annualPrecipitationMm)) / 1000

export function snapshotTerrainConditions(grid: TerrainConditionGrid): TerrainConditionSnapshot {
  const climate = grid.climate
  return { version: grid.version, size: grid.elevation.width, elevation_m: Array.from(grid.elevation.values),
    ...(climate && { climate: Object.fromEntries(terrainClimateFields.map(field => [field, Array.from(climate[field])])) as TerrainConditionSnapshot['climate'] }) }
}

export function validTerrainConditionSnapshot(value: unknown, spanKm: number): value is TerrainConditionSnapshot {
  if (!value || typeof value !== 'object') return false
  const { version, size, elevation_m, climate } = value as Partial<TerrainConditionSnapshot>
  const side = terrainConditionSide(spanKm)
  const plane = (values: unknown, nonnegative = false) => Array.isArray(values) && values.length === side ** 2 &&
    values.every(sample => typeof sample === 'number' && Number.isFinite(Math.fround(sample)) && (!nonnegative || sample >= 0))
  return version === terrainConditionVersion && size === side && plane(elevation_m) &&
    (climate === undefined || (!!climate && terrainClimateFields.every(field => plane(climate[field], field !== 'temperature_mean_c'))))
}

export function terrainConditionSide(spanKm: number) {
  if (!Number.isFinite(spanKm) || spanKm <= 0) throw new Error('Invalid TD conditioning span')
  const cells = spanKm / coarseKm
  const lower = Math.floor(cells)
  const nearest = cells - lower === 0.5 ? lower + lower % 2 : Math.round(cells)
  return Math.max(2, nearest)
}

function resample(rows: number, columns: number, size: number, read: (index: number) => number) {
  return Float32Array.from({ length: size * size }, (_, index) => {
    const row = Math.floor(index / size) * (rows - 1) / (size - 1)
    const col = (index % size) * (columns - 1) / (size - 1)
    const top = Math.floor(row)
    const left = Math.floor(col)
    const bottom = Math.min(rows - 1, top + 1)
    const right = Math.min(columns - 1, left + 1)
    const east = col - left
    const south = row - top
    return read(top * columns + left) * (1 - east) * (1 - south) +
      read(top * columns + right) * east * (1 - south) +
      read(bottom * columns + left) * (1 - east) * south +
      read(bottom * columns + right) * east * south
  })
}

export function prepareTerrainConditions(elevation: ElevationRaster, spanKm: number, climate?: TerrainClimateConditions): TerrainConditionGrid {
  const { width, height, values } = elevation
  const size = terrainConditionSide(spanKm)
  if (width < 1 || height < 1 || width * height !== values.length || !values.every(Number.isFinite)) {
    throw new Error('Invalid TD source elevation')
  }
  const sample = (source: Float32Array) => resample(height, width, size, index => source[index])
  const grid = { version: terrainConditionVersion, elevation: { width: size, height: size, values: sample(values) } } as const
  if (!climate) return grid
  const { temperature_mean_c, temperature_std_c, precipitation_total_mm, precipitation_cv_pct } = climate
  if (width !== height || width < 2 || [temperature_mean_c, temperature_std_c, precipitation_total_mm, precipitation_cv_pct]
    .some(field => field?.length !== values.length || !field.every(Number.isFinite)) ||
    [temperature_std_c, precipitation_total_mm, precipitation_cv_pct].some(field => field.some(value => value < 0))) {
    throw new Error('Invalid TD source climate')
  }
  return { ...grid, climate: {
    temperature_mean_c: resample(height, width, size, index => {
      const lapse = terrainLapseRate(precipitation_total_mm[index])
      return temperature_mean_c[index] - lapse * Math.max(0, values[index])
    }),
    temperature_std_c: sample(temperature_std_c),
    precipitation_total_mm: sample(precipitation_total_mm),
    precipitation_cv_pct: sample(precipitation_cv_pct),
  } }
}
