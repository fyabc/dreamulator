import type { PackSummary } from '../packs/types'
import type { LonLat } from './utils/mapCoords'
import { kmToLonLat, type PackWindow } from '../packs/packCoords'

export const REGION_WINDOW_PARAM = 'window'

export interface RegionWindow {
  lat: number
  lon: number
  spanKm: number
}

interface RegionScope {
  world: string
  planet: string
  branch: string | null
}

export function readRegionWindow(raw: string | null, radiusKm: number): RegionWindow | null {
  const parts = raw?.split(',')
  if (parts?.length !== 3 || parts.some((part) => !part.trim())) return null
  const [lat, lon, spanKm] = parts.map(Number)
  if (![lat, lon, spanKm, radiusKm].every(Number.isFinite)) return null
  if (Math.abs(lat) > 90 || Math.abs(lon) > 180 || spanKm <= 0 || spanKm >= Math.PI * radiusKm) {
    return null
  }
  return { lat, lon: lon === 180 ? -180 : lon, spanKm }
}

export function encodeRegionWindow({ lat, lon, spanKm }: RegionWindow): string {
  return `${lat},${lon},${spanKm}`
}

const EDGE_STEPS = 64

export function regionPackWindow(window: RegionWindow, radiusKm: number): PackWindow {
  return { centerLat: window.lat, centerLon: window.lon, radiusKm, projection: 'azimuthal_equidistant',
    extentKmX: window.spanKm, extentKmY: window.spanKm }
}

export function readRegionBoundary(raw: string | null, radiusKm: number): LonLat[] | null {
  const window = readRegionWindow(raw, radiusKm)
  if (!window) return null
  const projection = regionPackWindow(window, radiusKm)
  const half = window.spanKm / 2
  const corners = [[-half, half], [half, half], [half, -half], [-half, -half], [-half, half]]

  const boundary: LonLat[] = []
  for (let edge = 0; edge < corners.length - 1; edge++) {
    const [startEast, startNorth] = corners[edge]
    const [endEast, endNorth] = corners[edge + 1]
    for (let step = 0; step < EDGE_STEPS; step++) {
      const fraction = step / EDGE_STEPS
      const east = startEast + (endEast - startEast) * fraction
      const north = startNorth + (endNorth - startNorth) * fraction
      boundary.push(kmToLonLat(east, north, projection))
    }
  }
  boundary.push(boundary[0])
  return boundary
}

export function projectRegionOutline(
  boundary: readonly LonLat[],
  project: (lon: number, lat: number) => { x: number; y: number },
  viewWidth: number,
  zoom: number,
): { path: string; offsets: number[] } {
  const worldWidth = viewWidth * zoom
  if (worldWidth <= 0 || !boundary.length) return { path: '', offsets: [] }

  let previousX: number | undefined
  let minX = Infinity
  let maxX = -Infinity
  const path = boundary.map(({ lon, lat }, index) => {
    const point = project(lon, lat)
    const screenX = previousX === undefined ? point.x
      : point.x + Math.round((previousX - point.x) / worldWidth) * worldWidth
    previousX = screenX
    minX = Math.min(minX, screenX)
    maxX = Math.max(maxX, screenX)
    return `${index === 0 ? 'M' : 'L'}${screenX},${point.y}`
  }).join(' ')

  const offsets: number[] = []
  for (let copy = Math.ceil(-maxX / worldWidth); copy <= Math.floor((viewWidth - minX) / worldWidth); copy++) {
    offsets.push(copy === 0 ? 0 : copy * worldWidth)
  }
  return { path, offsets }
}

export function packRegionWindow(pack: PackSummary, radiusKm: number): RegionWindow | null {
  return readRegionWindow(`${pack.center_lat},${pack.center_lon},${pack.span_km}`, radiusKm)
}

export function availableRegionPacks(packs: PackSummary[], scope: RegionScope, radiusKm: number) {
  const nameCounts = new Map<string, number>()
  for (const pack of packs) nameCounts.set(pack.name, (nameCounts.get(pack.name) ?? 0) + 1)
  return packs.filter((pack) =>
    nameCounts.get(pack.name) === 1 &&
    pack.world === scope.world && pack.planet === scope.planet && pack.branch === scope.branch &&
    packRegionWindow(pack, radiusKm) !== null,
  )
}

export function matchingRegionPacks(packs: PackSummary[], window: RegionWindow, radiusKm: number) {
  const key = encodeRegionWindow(window)
  return packs.filter((pack) => {
    const candidate = packRegionWindow(pack, radiusKm)
    return candidate && encodeRegionWindow(candidate) === key
  })
}
