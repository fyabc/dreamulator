/**
 * Region-pack window geometry — the frontend twin of the backend's
 * `region_export.region_window` inverse (see `api_routes/packs.py`).
 *
 * A pack's full-bleed rasters (input/ 2048², refined-out/ & color/ 4096²) all
 * cover the same physical window described by `input/meta.json`: centred on
 * (center_lat, center_lon) with east–west extent `extent_km.x` and
 * north–south extent `extent_km.y` (they differ — the export grid snaps to
 * whole source pixels).  Degrees per kilometre use the planet radius from the
 * meta, and the east–west span is divided by cos(center_lat), exactly as the
 * export crop defined it.
 *
 * Map coordinates here are kilometre offsets from the window centre:
 * x grows east, y grows north.  That is also the Leaflet CRS.Simple frame
 * used by PackMap (Leaflet "lat" = y, "lng" = x), so image bounds are
 * [[-extY/2, -extX/2], [extY/2, extX/2]] and mouse positions convert with
 * these functions directly.
 */

import type { LonLat } from '../map/utils/mapCoords'

/** The part of a pack's input/meta.json that fixes the window geometry. */
export interface PackWindow {
  centerLat: number
  centerLon: number
  radiusKm: number
  extentKmX: number
  extentKmY: number
}

/** Graticule step candidates in degrees — same ladder as the carto sheets. */
const GRATICULE_STEPS_DEG = [1, 2, 5, 10, 15, 30]

export function degPerKm(w: PackWindow): number {
  return 180 / (Math.PI * w.radiusKm)
}

/** Wrap a longitude into [-180, 180]. */
export function wrapLon(lon: number): number {
  return (((lon + 180) % 360) + 360) % 360 - 180
}

/** Centre-origin km offsets → geographic degrees. */
export function kmToLonLat(x: number, y: number, w: PackWindow): LonLat {
  const cosLat = Math.cos((w.centerLat * Math.PI) / 180)
  const lon = w.centerLon + (x * degPerKm(w)) / cosLat
  const lat = w.centerLat + y * degPerKm(w)
  return { lon: wrapLon(lon), lat }
}

/** Geographic degrees → centre-origin km offsets (x east, y north). */
export function lonLatToKm(ll: LonLat, w: PackWindow): { x: number; y: number } {
  const cosLat = Math.cos((w.centerLat * Math.PI) / 180)
  const dx = (((ll.lon - w.centerLon) % 360) + 540) % 360 - 180
  return {
    x: (dx * cosLat) / degPerKm(w),
    y: (ll.lat - w.centerLat) / degPerKm(w),
  }
}

/**
 * Raster pixel (row 0 = north, col 0 = west, any resolution covering the
 * window) → the lon/lat of that pixel's centre.  Used for known-answer tests
 * against the backend formulas.
 */
export function pxToLonLat(
  col: number,
  row: number,
  width: number,
  height: number,
  w: PackWindow,
): LonLat {
  const x = ((col + 0.5) / width - 0.5) * w.extentKmX
  const y = (0.5 - (row + 0.5) / height) * w.extentKmY
  return kmToLonLat(x, y, w)
}

export interface GraticuleLines {
  lats: number[]
  lons: number[]
  step: number
}

/**
 * Graticule meridians/parallels crossing the window.  The step ladder and
 * the "≤ 8 lines across the longer span" rule mirror the carto sheets'
 * `_graticule` (carto_render.py), except that degrees are derived from the
 * planet radius rather than Earth's 111.19 km/deg — identical for R=6371.
 */
export function graticule(w: PackWindow): GraticuleLines {
  const cosLat = Math.cos((w.centerLat * Math.PI) / 180)
  const latSpan = w.extentKmY * degPerKm(w)
  const lonSpan = (w.extentKmX * degPerKm(w)) / cosLat
  let step = GRATICULE_STEPS_DEG[GRATICULE_STEPS_DEG.length - 1]
  for (const s of GRATICULE_STEPS_DEG) {
    if (Math.max(latSpan, lonSpan) / s <= 8) {
      step = s
      break
    }
  }
  const axis = (center: number, span: number, min: number, max: number): number[] => {
    const half = span / 2
    const start = Math.ceil((center - half) / step) * step
    const values: number[] = []
    for (let v = start; v < center + half - 1e-9; v += step) {
      if (v >= min && v <= max) values.push(Number(v.toFixed(6)))
    }
    return values
  }
  return {
    lats: axis(w.centerLat, latSpan, -90, 90),
    lons: axis(w.centerLon, lonSpan, -180, 180),
    step,
  }
}
