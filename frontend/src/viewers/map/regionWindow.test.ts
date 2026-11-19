import { describe, expect, it } from 'vitest'
import type { PackSummary } from '../packs/types'
import {
  availableRegionPacks, encodeRegionWindow, matchingRegionPacks,
  projectRegionOutline, readRegionBoundary, readRegionWindow,
} from './regionWindow'
import { lonLatToScreen } from './utils/mapCoords'

const radiusKm = 6371
const scope = { world: 'sample', planet: 'planet_sample', branch: null }
const pack: PackSummary = {
  ...scope,
  name: 'test-window',
  center_lat: 85.125,
  center_lon: 180,
  span_km: 550,
  mtime: '2026-11-20T00:00:00+00:00',
  legs: { carto: false, color: false, gaea: false, prog: false, refined: false, renders: false },
}

describe('regional window selection', () => {
  it('round-trips a polar window and treats both antimeridian spellings alike', () => {
    const window = { lat: 85.125, lon: -180, spanKm: 550 }
    expect(readRegionWindow('85.125,180,550', radiusKm)).toEqual(window)
    expect(readRegionWindow(encodeRegionWindow(window), radiusKm)).toEqual(window)
  })

  it.each([null, '0,1', '0,,500', '0,0,500,1', '91,0,500', '0,181,500', '0,0,0', '0,0,Infinity',
    `0,0,${Math.PI * radiusKm}`])('does not restore invalid window %s', (raw) => {
    expect(readRegionWindow(raw, radiusKm)).toBeNull()
  })

  it('offers only addressable packs for this world, body and branch', () => {
    const packs = [pack,
      { ...pack, name: 'other-branch', branch: 'variant' },
      { ...pack, name: 'other-body', planet: 'other' },
      { ...pack, name: 'ambiguous' },
      { ...pack, name: 'ambiguous', world: 'other' },
      { ...pack, name: 'invalid', span_km: 0 },
    ]
    expect(availableRegionPacks(packs, scope, radiusKm)).toEqual([pack])
    expect(availableRegionPacks(packs, { ...scope, branch: 'variant' }, radiusKm).map(({ name }) => name))
      .toEqual(['other-branch'])
  })

  it('links the same centre and span without substituting a nearby window', () => {
    const window = { lat: 85.125, lon: -180, spanKm: 550 }
    expect(matchingRegionPacks([pack, { ...pack, span_km: 551 }, { ...pack, center_lat: 85 }], window, radiusKm))
      .toEqual([pack])
  })
})

describe('regional window outline', () => {
  it('traces a closed square in the region export projection using the given radius', () => {
    const boundary = readRegionBoundary('0,0,550', radiusKm)!
    const quarter = (boundary.length - 1) / 4
    const midpoint = boundary[quarter / 2]
    expect(boundary[boundary.length - 1]).toEqual(boundary[0])
    expect(midpoint.lon).toBeCloseTo(0)
    expect(midpoint.lat).toBeCloseTo(275 / radiusKm * 180 / Math.PI)
    expect(boundary[0].lat).toBeLessThan(midpoint.lat)
    expect(readRegionBoundary('0,0,550', radiusKm * 2)![quarter / 2].lat).toBeCloseTo(midpoint.lat / 2)
    expect(readRegionBoundary('0,0,-1', radiusKm)).toBeNull()
  })

  it('keeps a pole-centred boundary finite and surrounds the pole at all longitudes', () => {
    const boundary = readRegionBoundary('90,0,550', radiusKm)!
    expect(boundary.every(({ lat, lon }) => lat < 90 && lat > 86 && Number.isFinite(lon))).toBe(true)
    expect(Math.max(...boundary.map(({ lon }) => lon))).toBeGreaterThan(175)
    expect(Math.min(...boundary.map(({ lon }) => lon))).toBe(-180)
  })

  it('draws both sides of the 2D seam without a line across the map', () => {
    const boundary = [{ lon: 178, lat: 10 }, { lon: -178, lat: 10 }]
    const viewport = { width: 360, height: 180 }
    const outline = (centre: number, zoom: number) => projectRegionOutline(boundary, (lon, lat) =>
      lonLatToScreen({ lon, lat }, { mapCenter: { lon: centre, lat: 0 }, zoom }, viewport), viewport.width, zoom)

    expect(outline(0, 1)).toEqual({ path: 'M358,80 L362,80', offsets: [-360, 0] })
    expect(outline(180, 2)).toEqual({ path: 'M176,70 L184,70', offsets: [0] })
    expect(outline(0, 2).offsets).toEqual([])
  })
})
