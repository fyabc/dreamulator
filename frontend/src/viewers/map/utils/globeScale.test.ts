import { Vector3 } from 'three'
import { describe, expect, it } from 'vitest'
import {
  globeCameraPath, GLOBE_OVERVIEW_DISTANCE, GLOBE_PREVIEW_MIN_DISTANCE, overviewCameraDistance,
  overviewProjectionZoom, regionCameraDistance,
} from './globeScale'

describe('globe region scale preview', () => {
  it('uses the shorter viewport dimension to fit the selection corners', () => {
    const spanKm = 150
    const radiusKm = 6371
    const aspect = 0.65
    const wide = regionCameraDistance(spanKm, radiusKm, 40, 1.5)
    const tall = regionCameraDistance(spanKm, radiusKm, 40, aspect)
    const corner = spanKm / (Math.SQRT2 * radiusKm)

    expect(tall).toBeGreaterThan(wide)
    expect(Math.sin(corner) / (tall - Math.cos(corner))).toBeCloseTo(Math.tan(Math.PI / 9) * aspect * 0.82)
  })

  it('stays above the preview floor and uses the overview for planet-scale windows', () => {
    expect(regionCameraDistance(1, 6371, 40, 1)).toBe(GLOBE_PREVIEW_MIN_DISTANCE)
    expect(regionCameraDistance(19000, 6371, 40, 1)).toBe(overviewCameraDistance(40, 1))
  })

  it('fits the globe silhouette in a portrait viewport without changing direction', () => {
    const distance = overviewCameraDistance(40, 0.6)
    expect(Math.asin(1 / distance)).toBeLessThan(Math.atan(Math.tan(Math.PI / 9) * 0.6))
  })

  it('fits the ordinary overview horizontally without moving the camera into the stellar transition', () => {
    expect(overviewProjectionZoom(40, 1.5)).toBe(1)
    const aspect = 390 / 595
    const zoom = overviewProjectionZoom(40, aspect)
    const horizontal = Math.tan(Math.PI / 9) * aspect / zoom
    const angularRadius = Math.asin(1 / GLOBE_OVERVIEW_DISTANCE)
    expect(horizontal).toBeGreaterThan(Math.tan(angularRadius))
  })

  it('approaches the other side of the globe without crossing the surface', () => {
    const start = new Vector3(0, 0, GLOBE_OVERVIEW_DISTANCE)
    const end = new Vector3(0, 0, -GLOBE_PREVIEW_MIN_DISTANCE)
    const path = globeCameraPath(start, end)
    const position = new Vector3()

    path(position, 0)
    expect(position.distanceTo(start)).toBeCloseTo(0)
    let previousDistance = position.length()
    for (let frame = 1; frame <= 20; frame++) {
      path(position, frame / 20)
      const distance = position.length()
      expect(distance).toBeGreaterThan(1)
      expect(distance).toBeLessThan(previousDistance)
      previousDistance = distance
    }
    expect(position.distanceTo(end)).toBeCloseTo(0)
  })

  it('keeps the viewing direction fixed when zooming on the same location', () => {
    const direction = new Vector3(1, 2, -3).normalize()
    const path = globeCameraPath(direction.clone().multiplyScalar(1.05), direction.clone().multiplyScalar(2.8))
    const position = new Vector3()
    path(position, 0.5)
    expect(position.length()).toBeCloseTo(1.3)
    expect(position.normalize().distanceTo(direction)).toBeCloseTo(0)
  })
})
