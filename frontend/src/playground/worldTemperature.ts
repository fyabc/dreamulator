import type { CatalogBody, CatalogStar, SystemCatalog } from '../api/catalogAdapter'
import type { MapMetadata } from '../viewers/map/types'
import { EARTH_PARAMS, GRID_W, GRID_H } from './temperatureDraft'

type PlanetInput = NonNullable<CatalogBody['physical']> & {
  id: string
  name?: string
  orbits?: string
  atmosphere?: CatalogBody['atmosphere']
}

type StellarInput = {
  stars?: Array<CatalogStar & { luminosity?: number }>
  orbits?: Array<{ body_id: string; parent_id: string; semi_major_axis_au: number }>
  bodies?: PlanetInput[]
}

export function temperatureInputCatalog(stellar: StellarInput | null, planets: PlanetInput[]): SystemCatalog {
  const targets = new Map([...(stellar?.bodies ?? []), ...planets].map(body => [body.id, body]))
  const orbits = new Map(stellar?.orbits?.map(orbit => [orbit.body_id, orbit]))
  return {
    stars: stellar?.stars?.map(star => ({ id: star.id, luminosity_sol: star.luminosity_sol ?? star.luminosity })),
    bodies: [...targets.values()].map(body => ({
      id: body.id, name: body.name, parent_id: orbits.get(body.id)?.parent_id ?? body.orbits,
      orbit: orbits.get(body.id), physical: body, atmosphere: body.atmosphere,
    })),
  }
}

export function worldTemperatureParams(catalog: SystemCatalog | null, planet: string) {
  const bodies = new Map(catalog?.bodies?.map(body => [body.id, body]))
  const target = bodies.get(planet)
  let stellarOrbiter = target
  const visited = new Set<string>()
  while (stellarOrbiter?.parent_id && !visited.has(stellarOrbiter.id) && bodies.has(stellarOrbiter.parent_id)) {
    visited.add(stellarOrbiter.id)
    stellarOrbiter = bodies.get(stellarOrbiter.parent_id)
  }
  const star = catalog?.stars?.find(entry => entry.id === stellarOrbiter?.parent_id)
  const tilt = target?.physical?.axial_tilt_deg
  const rotation = target?.physical?.rotation_period_days
  const supplied = {
    luminosity: star?.luminosity_sol,
    distanceAu: star && stellarOrbiter?.orbit?.semi_major_axis_au,
    yearDays: star && stellarOrbiter?.orbit?.period_days,
    albedo: target?.physical?.albedo,
    greenhouseK: target?.atmosphere?.greenhouse_factor,
    tiltDeg: tilt !== undefined && tilt >= 0 && tilt <= 180 ? Math.min(tilt, 180 - tilt) : undefined,
    rotationDays: rotation === undefined ? undefined : Math.abs(rotation),
  }
  const params = { ...EARTH_PARAMS }
  let defaults = false
  for (const key of Object.keys(supplied) as Array<keyof typeof supplied>) {
    const value = supplied[key]
    if (value !== undefined && Number.isFinite(value)) params[key] = value
    else defaults = true
  }
  return { params, defaults, name: target?.name ?? planet }
}

export async function loadTemperatureElevation(blob: Blob, meta: MapMetadata) {
  const min = meta.elevation_min_m
  const max = meta.elevation_max_m
  if (meta.projection !== 'equirectangular' || ![min, max, meta.sea_level_m].every(Number.isFinite) || max < min) {
    throw new Error('Incompatible global elevation metadata')
  }
  const raster = meta.elevation_import
    ? await import('../viewers/packs/elevationRaster').then(async ({ readElevationPng }) => {
        const { values, width, height } = await readElevationPng(blob, 0, 1)
        return { data: values, width, height }
      })
    : await import('../viewers/map/utils/imageCodec').then(({ decodePngToFloat32 }) => decodePngToFloat32(blob))
  if (raster.width !== meta.width || raster.height !== meta.height) throw new Error('Elevation dimensions do not match the map')

  const gray = new Float32Array(GRID_W * GRID_H)
  for (let row = 0; row < GRID_H; row++) {
    const top = Math.floor(row * raster.height / GRID_H)
    const bottom = Math.max(top + 1, Math.floor((row + 1) * raster.height / GRID_H))
    for (let col = 0; col < GRID_W; col++) {
      const left = Math.floor(col * raster.width / GRID_W)
      const right = Math.max(left + 1, Math.floor((col + 1) * raster.width / GRID_W))
      let total = 0
      for (let y = top; y < bottom; y++) {
        for (let x = left; x < right; x++) total += raster.data[y * raster.width + x]
      }
      gray[row * GRID_W + col] = max === min ? 0 : total / ((bottom - top) * (right - left))
    }
  }
  return { gray, elevMinM: min, elevMaxM: max === min ? min + 1 : max, seaLevelM: meta.sea_level_m }
}
