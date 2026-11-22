import { describe, expect, it } from 'vitest'
import type { ElevationResult, ElevationSource, LocalProject } from '../../projects/elevationProject'
import { matchingBrowserRegionResults } from './browserRegionResults'
import type { PackWindow } from './packCoords'

const window: PackWindow = { centerLat: 24.1, centerLon: -180, radiusKm: 6371, extentKmX: 150, extentKmY: 150,
  projection: 'azimuthal_equidistant' }
const location = { planet: 'planet_terra', branch: 'tilt-6344' }

function resultPair(id: string, locationOverride: Partial<typeof location> = {}, frame: Partial<PackWindow> = {}) {
  const data = { width: 1, height: 1, data: new Blob([new Float32Array([5])]) }
  const source: ElevationSource = { ...data, id: `${id}-source`, name: 'Original', kind: 'elevation-source',
    frame: { window: { ...window, ...frame }, min: 0, max: 10, sea: 0, sourceStepKm: 10 }, location: { ...location, ...locationOverride } }
  const result: ElevationResult = { ...data, id, name: 'Redrawn', kind: 'elevation-result', sourceId: source.id,
    settings: { recipe: { method: 'redraw', seed: 314, residualGain: 1 }, recommendation: 'redraw',
      manifestSha256: 'a'.repeat(64), nativeSpacingKm: 10 } }
  return [source, result]
}

describe('browser regional result choices', () => {
  it('only lists results from the same location and frame, including an equivalent antimeridian longitude', () => {
    const [source, layer] = resultPair('matching', {}, { centerLon: 180 })
    const project: LocalProject = { id: 'earth', name: 'Earth', published: true, updatedAt: 1, layers: [source, layer,
      ...resultPair('other-branch', { branch: 'main' }), ...resultPair('other-planet', { planet: 'moon' }),
      ...resultPair('other-center', {}, { centerLat: 23 }), ...resultPair('other-size', {}, { extentKmY: 140 }),
      ...resultPair('other-radius', {}, { radiusKm: 6000 }), ...resultPair('other-projection', {}, { projection: undefined })] }

    expect(matchingBrowserRegionResults(project, location, window)).toEqual([{ layer, source }])
    expect(matchingBrowserRegionResults({ ...project, published: undefined }, location, window)).toEqual([])
  })
})
