import { describe, expect, it } from 'vitest'
import { Vector3 } from 'three'
import type { ElevationResult, ElevationSource } from '../../../projects/elevationProject'
import { kmToLonLat } from '../../packs/packCoords'
import { regionPackWindow } from '../regionWindow'
import { lonLatToGlobePosition } from './globeCoords'
import { globeRegionBasis, globeRegionBlend, savedGlobeRegion } from './globeRegionDetail'
import { overviewCameraDistance, regionCameraDistance } from './globeScale'

const radiusKm = 6371
const selection = { lat: 24.1, lon: 121.45, spanKm: 150 }
const window = regionPackWindow(selection, radiusKm)
const scope = { world: 'earth-fixture', planet: 'earth', branch: null, radiusKm, selection }
const source: ElevationSource = {
  id: 'input', kind: 'elevation-source', name: 'Input', width: 16, height: 16, data: new Blob(),
  location: { planet: scope.planet, branch: scope.branch }, frame: { window, min: -200, max: 2000, sea: 0, sourceStepKm: 5 },
}
const result: ElevationResult = {
  id: 'detail', kind: 'elevation-result', name: 'Detail', width: 256, height: 256, data: new Blob(), sourceId: source.id,
  settings: { recipe: { method: 'redraw', residualGain: 1, seed: 42 }, nativeSpacingKm: 5, recommendation: 'redraw', manifestSha256: 'a'.repeat(64) },
}
const latest = { ...result, id: 'new' }
const project = { published: true as const, id: scope.world, name: scope.world, updatedAt: 1,
  layers: [source, result, latest, { ...result, id: 'orphan', sourceId: 'missing' }] }

describe('saved globe detail', () => {
  it('uses the most recently appended matching result, skipping orphan results', () => {
    expect(savedGlobeRegion(project, scope)).toEqual({ result: latest, frame: source.frame })
  })

  it('rejects unrelated worlds, branches, planets, radii and selections', () => {
    expect(savedGlobeRegion({ ...project, published: undefined }, scope)).toBeNull()
    expect(savedGlobeRegion(project, { ...scope, world: 'other' })).toBeNull()
    expect(savedGlobeRegion(project, { ...scope, planet: 'other' })).toBeNull()
    expect(savedGlobeRegion(project, { ...scope, branch: 'other' })).toBeNull()
    expect(savedGlobeRegion(project, { ...scope, radiusKm: 6000 })).toBeNull()
    expect(savedGlobeRegion(project, { ...scope, selection: { ...selection, spanKm: 151 } })).toBeNull()
  })

  it('keeps the azimuthal raster oriented east and north across the date line', () => {
    const polarWindow = regionPackWindow({ lat: 82, lon: 179.9, spanKm: 400 }, radiusKm)
    const basis = globeRegionBasis(polarWindow)
    const known = kmToLonLat(125, 90, polarWindow)
    expect(known.lon).toBeLessThan(0)
    const direction = new Vector3(...lonLatToGlobePosition(known, 1))
    const projected = [direction.dot(basis.east), direction.dot(basis.north)]
    const sine = Math.hypot(...projected)
    const scale = radiusKm * Math.atan2(sine, direction.dot(basis.centre)) / sine
    expect(projected[0] * scale).toBeCloseTo(125, 6)
    expect(projected[1] * scale).toBeCloseTo(90, 6)
  })

  it.each([0.5, 1.6])('blends by camera distance (viewport aspect %s)', (aspect) => {
    const close = regionCameraDistance(selection.spanKm, radiusKm, 40, aspect)
    const overview = overviewCameraDistance(40, aspect)
    expect(globeRegionBlend(window, close, 40, aspect)).toBe(1)
    expect(globeRegionBlend(window, close + (close - 1) / 2, 40, aspect)).toBeCloseTo(0.5)
    expect(globeRegionBlend(window, overview, 40, aspect)).toBe(0)
  })
})
