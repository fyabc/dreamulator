/**
 * flowField — the sampled vector field behind the nullschool-style particle
 * overlay (wind and ocean-current layers).
 *
 * The CVT mesh stores one vector per cell (~200k cells).  Advecting thousands
 * of particles against a per-cell nearest-neighbour lookup would make the
 * trajectory jump whenever a particle crosses a cell boundary, so the mesh is
 * first binned into a regular lon/lat grid (area-weighted vector average) and
 * the particle integrator samples that grid bilinearly.
 *
 * A grid bin also carries the layer's auxiliary value (SST anomaly for ocean
 * currents), a validity mask, and the field's maximum speed for colour scaling.
 * The grid is cheap to rebuild (one pass over the cells, a few milliseconds),
 * so it is rebuilt per displayed month rather than cached across months.
 */

import type { VoronoiCell } from './types'

export type FlowKind = 'wind' | 'current'

/** Earth radius used when no planet-specific radius is supplied (metres). */
export const EARTH_RADIUS_M = 6_371_000

const DEG = Math.PI / 180

export interface FlowField {
  kind: FlowKind
  /** Grid spacing in degrees (both axes). */
  stepDeg: number
  nLon: number
  nLat: number
  /** Area-weighted east/north components, row-major (lat-major). */
  u: Float32Array
  v: Float32Array
  /** Auxiliary value (SST anomaly for currents; zero for wind). */
  aux: Float32Array
  /** 1 = at least one contributing cell landed in this bin. */
  valid: Uint8Array
  /** Largest bin-averaged speed, for colour scaling. */
  maxSpeed: number
}

export interface BuildFlowFieldOptions {
  kind: FlowKind
  cells: VoronoiCell[]
  /** Monthly wind arrays in mesh-cell order (N × 12), when available. */
  monthlyWindEast?: Float32Array | null
  monthlyWindNorth?: Float32Array | null
  /** Month index 0–11; ignored when the monthly arrays are absent. */
  month?: number
  /** Grid spacing in degrees (default 2°). */
  stepDeg?: number
}

function isFiniteNumber(v: unknown): v is number {
  return typeof v === 'number' && Number.isFinite(v)
}

/** Wrap a longitude into [-180, 180). */
export function wrapLongitude(lon: number): number {
  let out = ((lon + 180) % 360 + 360) % 360 - 180
  if (out === 180) out = -180
  return out
}

/**
 * Build a regular lon/lat vector grid from the mesh's per-cell fields.
 *
 * Wind uses the monthly arrays when both are supplied (monthly mode), else the
 * annual per-cell `wind_east_m_s` / `wind_north_m_s`.  Ocean currents are
 * annual-mean in the current data contract; the same builder will pick up
 * monthly current arrays if a future export provides them.
 */
export function buildFlowField({
  kind,
  cells,
  monthlyWindEast = null,
  monthlyWindNorth = null,
  month = 0,
  stepDeg = 2.0,
}: BuildFlowFieldOptions): FlowField {
  const step = stepDeg > 0 ? stepDeg : 2.0
  const nLon = Math.max(1, Math.round(360 / step))
  const nLat = Math.max(1, Math.round(180 / step))
  const n = nLon * nLat

  const sumU = new Float64Array(n)
  const sumV = new Float64Array(n)
  const sumAux = new Float64Array(n)
  const sumW = new Float64Array(n)

  const useMonthlyWind =
    kind === 'wind' &&
    !!monthlyWindEast && !!monthlyWindNorth

  for (let i = 0; i < cells.length; i++) {
    const c = cells[i]
    let u: number | null | undefined
    let v: number | null | undefined
    let aux = 0

    if (kind === 'wind') {
      if (useMonthlyWind) {
        const idx = i * 12 + month
        u = (monthlyWindEast as Float32Array)[idx]
        v = (monthlyWindNorth as Float32Array)[idx]
      } else {
        u = c.wind_east_m_s
        v = c.wind_north_m_s
      }
    } else {
      u = c.ocean_current_east_m_s
      v = c.ocean_current_north_m_s
      if (isFiniteNumber(c.sst_anomaly_c)) aux = c.sst_anomaly_c
    }

    if (!isFiniteNumber(u) || !isFiniteNumber(v) || !isFiniteNumber(c.lon) || !isFiniteNumber(c.lat)) {
      continue
    }

    const ix = Math.min(nLon - 1, Math.max(0, Math.floor((c.lon + 180) / step)))
    const iy = Math.min(nLat - 1, Math.max(0, Math.floor((c.lat + 90) / step)))
    const k = iy * nLon + ix
    // Each CVT cell carries roughly equal area on the sphere; the area weight
    // is still used when present so a future non-uniform mesh bins correctly.
    const w = isFiniteNumber(c.area_km2) && c.area_km2 > 0 ? c.area_km2 : 1
    sumU[k] += u * w
    sumV[k] += v * w
    sumAux[k] += aux * w
    sumW[k] += w
  }

  const uOut = new Float32Array(n)
  const vOut = new Float32Array(n)
  const auxOut = new Float32Array(n)
  const valid = new Uint8Array(n)
  let maxSpeed = 0

  for (let k = 0; k < n; k++) {
    const w = sumW[k]
    if (w <= 0) continue
    const uu = sumU[k] / w
    const vv = sumV[k] / w
    uOut[k] = uu
    vOut[k] = vv
    auxOut[k] = sumAux[k] / w
    valid[k] = 1
    const s = Math.hypot(uu, vv)
    if (s > maxSpeed) maxSpeed = s
  }

  return { kind, stepDeg: step, nLon, nLat, u: uOut, v: vOut, aux: auxOut, valid, maxSpeed }
}

export interface FlowSample {
  u: number
  v: number
  aux: number
  valid: boolean
}

/**
 * Bilinear sample of the flow grid.  Invalid corners (land in the current
 * field, missing data) are dropped and the remaining weights renormalised; a
 * sample with less than a quarter of its weight available is treated as
 * outside the field so particles die at the coastline rather than drifting
 * inland on interpolated ocean flow.
 */
export function sampleFlow(
  field: FlowField,
  lon: number,
  lat: number,
  out: FlowSample,
): boolean {
  const { stepDeg, nLon, nLat, u, v, aux, valid } = field
  const lonWrapped = wrapLongitude(lon)
  const gx = (lonWrapped + 180) / stepDeg - 0.5
  const gy = (lat + 90) / stepDeg - 0.5

  const ix0Raw = Math.floor(gx)
  const fx = gx - ix0Raw
  let ix0 = ix0Raw % nLon
  if (ix0 < 0) ix0 += nLon
  const ix1 = (ix0 + 1) % nLon

  let iy0 = Math.floor(gy)
  let fy = gy - iy0
  if (iy0 < 0) { iy0 = 0; fy = 0 }
  else if (iy0 >= nLat - 1) { iy0 = nLat - 1; fy = 0 }
  const iy1 = Math.min(nLat - 1, iy0 + 1)

  const k00 = iy0 * nLon + ix0
  const k10 = iy0 * nLon + ix1
  const k01 = iy1 * nLon + ix0
  const k11 = iy1 * nLon + ix1

  const w00 = (1 - fx) * (1 - fy)
  const w10 = fx * (1 - fy)
  const w01 = (1 - fx) * fy
  const w11 = fx * fy

  let wSum = 0
  let uSum = 0
  let vSum = 0
  let auxSum = 0
  if (valid[k00]) { wSum += w00; uSum += u[k00] * w00; vSum += v[k00] * w00; auxSum += aux[k00] * w00 }
  if (valid[k10]) { wSum += w10; uSum += u[k10] * w10; vSum += v[k10] * w10; auxSum += aux[k10] * w10 }
  if (valid[k01]) { wSum += w01; uSum += u[k01] * w01; vSum += v[k01] * w01; auxSum += aux[k01] * w01 }
  if (valid[k11]) { wSum += w11; uSum += u[k11] * w11; vSum += v[k11] * w11; auxSum += aux[k11] * w11 }

  out.valid = false
  if (wSum < 0.25) return false
  out.u = uSum / wSum
  out.v = vSum / wSum
  out.aux = auxSum / wSum
  out.valid = true
  return true
}

/**
 * Look up the nearest CVT cell ID at a geographic point from the precomputed
 * equirectangular cell-ID raster (`useCellIdMap`).  The raster uses the
 * `px / (width - 1)` convention, so the inverse is a rounded multiply.
 * Returns -1 when the map is unavailable or the index is out of range.
 */
export function sampleCellId(
  cellIdMap: Uint32Array | null | undefined,
  width: number,
  height: number,
  lon: number,
  lat: number,
): number {
  if (!cellIdMap || width <= 1 || height <= 1) return -1
  const x = Math.round(((wrapLongitude(lon) + 180) / 360) * (width - 1))
  const y = Math.round(((90 - lat) / 180) * (height - 1))
  if (x < 0 || x >= width || y < 0 || y >= height) return -1
  const id = cellIdMap[y * width + x]
  return id === 0xffffffff ? -1 : id
}

export interface AdvectResult {
  lon: number
  lat: number
  /** Local speed at the destination (m/s), for colour classification. */
  speed: number
  /** Auxiliary value at the destination (SST anomaly for currents). */
  aux: number
}

const _sampleA: FlowSample = { u: 0, v: 0, aux: 0, valid: false }
const _sampleB: FlowSample = { u: 0, v: 0, aux: 0, valid: false }

/**
 * Advance one particle with a midpoint (RK2) step on the sphere.
 *
 * The grid components are east/north in m/s; dividing by the planet radius
 * converts them to radians on the sphere.  Longitude advances by
 * u / (R cos lat), which diverges at the poles — the cosine is floored and a
 * particle that crosses a pole reflects to the other side instead of pinning
 * to ±90°.
 *
 * Returns false when the starting point or the midpoint leaves the field
 * (e.g. a current particle reaching land); the caller then respawns it.
 */
export function advectParticle(
  field: FlowField,
  lon: number,
  lat: number,
  planetRadiusM: number,
  simSeconds: number,
  out: AdvectResult,
): boolean {
  if (!sampleFlow(field, lon, lat, _sampleA)) return false

  const cosLat = Math.max(0.05, Math.cos(lat * DEG))
  const radius = planetRadiusM > 0 ? planetRadiusM : EARTH_RADIUS_M
  const halfLat = lat + (_sampleA.v * simSeconds / radius) / DEG * 0.5
  const halfLon = wrapLongitude(lon + (_sampleA.u * simSeconds / (radius * cosLat)) / DEG * 0.5)

  // Midpoint sample; falling back to the start sample keeps the step stable
  // at a coastline instead of freezing the particle.
  const midOk = sampleFlow(field, halfLon, halfLat, _sampleB)
  const u = midOk ? _sampleB.u : _sampleA.u
  const v = midOk ? _sampleB.v : _sampleA.v
  const aux = midOk ? _sampleB.aux : _sampleA.aux

  const midCosLat = Math.max(0.05, Math.cos(halfLat * DEG))
  let nextLat = lat + (v * simSeconds / radius) / DEG
  let nextLon = lon + (u * simSeconds / (radius * midCosLat)) / DEG

  if (nextLat > 90) {
    nextLat = 180 - nextLat
    nextLon += 180
  } else if (nextLat < -90) {
    nextLat = -180 - nextLat
    nextLon += 180
  }
  nextLon = wrapLongitude(nextLon)

  out.lon = nextLon
  out.lat = Math.max(-89.5, Math.min(89.5, nextLat))
  out.speed = Math.hypot(u, v)
  out.aux = aux
  return true
}

/** Uniform-area random point on the sphere, avoiding the polar singularity. */
export function randomLonLat(rand: () => number = Math.random): { lon: number; lat: number } {
  const lon = rand() * 360 - 180
  // asin gives an equal-area latitude distribution; the clamp keeps particles
  // out of the last half-degree where the longitude step is ill-conditioned.
  const lat = Math.asin(2 * rand() - 1) / DEG
  return { lon, lat: Math.max(-89.5, Math.min(89.5, lat)) }
}
