/**
 * Known-answer tests for packCoords against the real nacrea-21.5_95.5_550km
 * pack numbers (center 21.5/95.5, extent 554.67 × 567.11 km, R = 6371).
 * The backend probe uses the same formulas, so these identities are what
 * keeps the hover readout and the /api/packs probe on the same grid.
 */

import { describe, expect, it } from 'vitest'
import {
  degPerKm,
  graticule,
  kmToLonLat,
  lonLatToKm,
  pxToLonLat,
  wrapLon,
  type PackWindow,
} from './packCoords'

const NACREA: PackWindow = {
  centerLat: 21.5,
  centerLon: 95.5,
  radiusKm: 6371,
  extentKmX: 554.67,
  extentKmY: 567.11,
}

describe('degPerKm', () => {
  it('matches 180/(π·R) for the Earth radius', () => {
    expect(degPerKm(NACREA)).toBeCloseTo(0.0089932, 6)
  })
})

describe('km ↔ lon/lat round trip', () => {
  it('maps the window centre onto the pack centre', () => {
    expect(kmToLonLat(0, 0, NACREA)).toEqual({ lon: 95.5, lat: 21.5 })
  })

  it('maps the north-west corner of the raster', () => {
    // px (0, 0) of a 2048² input raster: pixel centre a half-cell in.
    const ll = pxToLonLat(0, 0, 2048, 2048, NACREA)
    const km = lonLatToKm(ll, NACREA)
    // NW corner in centre-origin km: x = -extent/2 + half cell, y = +extent/2 - half cell
    expect(km.x).toBeCloseTo(-NACREA.extentKmX / 2 + NACREA.extentKmX / 4096, 9)
    expect(km.y).toBeCloseTo(NACREA.extentKmY / 2 - NACREA.extentKmY / 4096, 9)
    expect(ll.lat).toBeGreaterThan(21.5)
    expect(wrapLon(ll.lon)).toBeLessThan(95.5)
  })

  it('round-trips arbitrary in-window points', () => {
    for (const [x, y] of [
      [-200.4, 120.7],
      [137.9, -211.2],
      [0.5, -0.25],
    ]) {
      const ll = kmToLonLat(x, y, NACREA)
      const back = lonLatToKm(ll, NACREA)
      expect(back.x).toBeCloseTo(x, 9)
      expect(back.y).toBeCloseTo(y, 9)
    }
  })

  it('scales degrees per km by cos(center_lat) in longitude only', () => {
    // 100 km east of centre vs 100 km north: both cover the same km, so the
    // lon delta is the lat delta stretched by 1/cos(center_lat).
    const east = kmToLonLat(100, 0, NACREA)
    const north = kmToLonLat(0, 100, NACREA)
    const cosLat = Math.cos((21.5 * Math.PI) / 180)
    expect(east.lon - 95.5).toBeCloseTo((north.lat - 21.5) / cosLat, 9)
  })
})

describe('graticule', () => {
  it('picks a 1° step for the 550 km window (5–6 lines per axis)', () => {
    const g = graticule(NACREA)
    expect(g.step).toBe(1)
    expect(g.lats.length).toBeGreaterThanOrEqual(4)
    expect(g.lats.length).toBeLessThanOrEqual(8)
    // Lines land on whole degrees.
    for (const lat of g.lats) expect(Number.isInteger(lat)).toBe(true)
    for (const lon of g.lons) expect(Number.isInteger(lon)).toBe(true)
    // 21.5N / 95E-family lines must cross the window (the printed-sheet labels).
    expect(g.lats).toContain(21)
    expect(g.lons).toContain(95)
  })
})
