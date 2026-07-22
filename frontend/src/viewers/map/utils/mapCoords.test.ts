import { describe, it, expect } from 'vitest'
import {
  lonLatToScreen,
  screenToLonLat,
  applyDrag,
  applyZoom,
  lonLatToPixel,
  clampViewState,
  type MapViewState,
  type Viewport,
} from './mapCoords'

const VP: Viewport = { width: 1000, height: 500 }

// Centre of screen always maps to the mapCenter
function expectRoundTrip(ll: { lon: number; lat: number }, state: MapViewState, vp: Viewport = VP) {
  const s = lonLatToScreen(ll, state, vp)
  const back = screenToLonLat(s.x, s.y, state, vp)
  // lon may wrap to [-180,180]; lat should be within ~0.001°
  expect(Math.abs(back.lon - ll.lon) % 360).toBeLessThan(0.01)
  expect(Math.abs(back.lat - ll.lat)).toBeLessThan(0.01)
}

describe('lonLatToScreen', () => {
  const state: MapViewState = { mapCenter: { lon: 0, lat: 0 }, zoom: 1 }

  it('maps the centre to the middle of the viewport', () => {
    const s = lonLatToScreen({ lon: 0, lat: 0 }, state, VP)
    expect(s.x).toBeCloseTo(500, 1)
    expect(s.y).toBeCloseTo(250, 1)
  })

  it('maps lon=-180 to left edge at zoom=1', () => {
    const s = lonLatToScreen({ lon: -180, lat: 0 }, state, VP)
    expect(s.x).toBeCloseTo(0, 1)
  })

  it('maps lon=+180 to edge (same meridian as -180)', () => {
    // +180 and -180 are the same meridian on a cylindrical map
    const s = lonLatToScreen({ lon: 180, lat: 0 }, state, VP)
    expect(Math.abs(s.x - 500)).toBeCloseTo(500, 0) // 500 px from centre in either direction
  })

  it('maps lat=+90 to top edge', () => {
    const s = lonLatToScreen({ lon: 0, lat: 90 }, state, VP)
    expect(s.y).toBeCloseTo(0, 1)
  })

  it('maps lat=-90 to bottom edge', () => {
    const s = lonLatToScreen({ lon: 0, lat: -90 }, state, VP)
    expect(s.y).toBeCloseTo(500, 1)
  })

  it('wraps lon+360 to same screen position', () => {
    const s1 = lonLatToScreen({ lon: 30, lat: 0 }, state, VP)
    const s2 = lonLatToScreen({ lon: 390, lat: 0 }, state, VP)
    expect(s1.x).toBeCloseTo(s2.x, 1)
    expect(s1.y).toBeCloseTo(s2.y, 1)
  })

  it('scales with zoom', () => {
    const z2: MapViewState = { mapCenter: { lon: 0, lat: 0 }, zoom: 2 }
    const s = lonLatToScreen({ lon: 0, lat: 0 }, z2, VP)
    expect(s.x).toBeCloseTo(500, 1)
    expect(s.y).toBeCloseTo(250, 1)
    // At zoom=2, lon=180 is one full screen width from centre
    const s180 = lonLatToScreen({ lon: 180, lat: 0 }, z2, VP)
    expect(Math.abs(s180.x - 500)).toBeCloseTo(1000, 0)
  })

  it('works with offset centre', () => {
    const off: MapViewState = { mapCenter: { lon: 90, lat: 0 }, zoom: 1 }
    const s = lonLatToScreen({ lon: 90, lat: 0 }, off, VP)
    expect(s.x).toBeCloseTo(500, 1)
  })
})

describe('screenToLonLat', () => {
  const state: MapViewState = { mapCenter: { lon: 0, lat: 0 }, zoom: 1 }

  it('returns centre lon/lat for screen centre', () => {
    const ll = screenToLonLat(500, 250, state, VP)
    expect(ll.lon).toBeCloseTo(0, 1)
    expect(ll.lat).toBeCloseTo(0, 1)
  })

  it('wraps lon to [-180, 180]', () => {
    const ll = screenToLonLat(1500, 250, state, VP) // way off to the right
    expect(ll.lon).toBeGreaterThanOrEqual(-180)
    expect(ll.lon).toBeLessThanOrEqual(180)
  })

  it('clamps lat to [-90, 90]', () => {
    const ll = screenToLonLat(500, -1000, state, VP)
    expect(ll.lat).toBeGreaterThanOrEqual(-90)
    expect(ll.lat).toBeLessThanOrEqual(90)
  })

  it('round-trips for various coordinates', () => {
    const tests = [
      { lon: 0, lat: 0 },
      { lon: 45, lat: 30 },
      { lon: -120, lat: -45 },
      { lon: 179, lat: 89 },
      { lon: 720, lat: 0 }, // wrapped
    ]
    for (const t of tests) {
      expectRoundTrip(t, state)
    }
  })

  it('round-trips with offset centre', () => {
    const off: MapViewState = { mapCenter: { lon: 120, lat: -30 }, zoom: 2 }
    const tests = [
      { lon: 0, lat: 0 },
      { lon: 120, lat: -30 },
      { lon: -180, lat: 1 },
    ]
    for (const t of tests) {
      expectRoundTrip(t, off, VP)
    }
  })
})

describe('applyDrag', () => {
  it('moves centre right when dragging left', () => {
    const state: MapViewState = { mapCenter: { lon: 0, lat: 0 }, zoom: 1 }
    const next = applyDrag(state, { dx: -250, dy: 0 }, VP)
    // dx=-250 at zoom=1, width=1000 → dLon = +250/1000*360 = +90
    expect(next.mapCenter.lon).toBeCloseTo(90, 1)
    expect(next.mapCenter.lat).toBeCloseTo(0, 1)
    expect(next.zoom).toBe(1)
  })

  it('wraps lon past 180', () => {
    const state: MapViewState = { mapCenter: { lon: 170, lat: 0 }, zoom: 1 }
    const next = applyDrag(state, { dx: -250, dy: 0 }, VP)
    // dLon = +90, 170+90=260 → wraps to -100
    expect(next.mapCenter.lon).toBeCloseTo(-100, 1)
  })

  it('scales with zoom', () => {
    const state: MapViewState = { mapCenter: { lon: 0, lat: 0 }, zoom: 2 }
    const next = applyDrag(state, { dx: -250, dy: 0 }, VP)
    // At zoom=2, each pixel is half a degree, so 250px = 45°
    expect(next.mapCenter.lon).toBeCloseTo(45, 1)
  })

  it('moves centre south when dragging up (dy<0)', () => {
    // Drag up → content follows finger up → centre shows more southern land → lat decreases
    const state: MapViewState = { mapCenter: { lon: 0, lat: 0 }, zoom: 1 }
    const next = applyDrag(state, { dx: 0, dy: -250 }, VP)
    // dy=-250, height=500 → dLat = (-250/500)*180 = -90
    expect(next.mapCenter.lat).toBeCloseTo(-90, 1)
  })

  it('clamps lat to [-90, 90] on extreme drag up', () => {
    const state: MapViewState = { mapCenter: { lon: 0, lat: 85 }, zoom: 1 }
    const next = applyDrag(state, { dx: 0, dy: -500 }, VP)
    // dLat = -180, 85-180 = -95 → clamped to -90
    expect(next.mapCenter.lat).toBe(-90)
  })
})

describe('applyZoom', () => {
  it('zooms in/out from screen centre', () => {
    const state: MapViewState = { mapCenter: { lon: 0, lat: 0 }, zoom: 1 }
    const next = applyZoom(state, 2, { x: 500, y: 250 }, VP)
    expect(next.zoom).toBe(2)
    // Centre stays the same since anchor = centre
    expect(next.mapCenter.lon).toBeCloseTo(0, 1)
    expect(next.mapCenter.lat).toBeCloseTo(0, 1)
  })
})

describe('lonLatToPixel', () => {
  it('converts correctly', () => {
    const p = lonLatToPixel({ lon: 0, lat: 0 }, 2048, 1024)
    expect(p?.px).toBe(1024)
    expect(p?.py).toBe(512)
  })

  it('handles lon wrapping', () => {
    const p1 = lonLatToPixel({ lon: 0, lat: 0 }, 2048, 1024)
    const p2 = lonLatToPixel({ lon: 360, lat: 0 }, 2048, 1024)
    expect(p1?.px).toBe(p2?.px)
    expect(p1?.py).toBe(p2?.py)
  })

  it('returns null for out-of-bounds lat', () => {
    expect(lonLatToPixel({ lon: 0, lat: 100 }, 2048, 1024)).toBeNull()
  })
})

describe('clampViewState', () => {
  it('clamps zoom to range', () => {
    const state: MapViewState = { mapCenter: { lon: 0, lat: 0 }, zoom: 50 }
    const clamped = clampViewState(state, 1, 20)
    expect(clamped.zoom).toBe(20)
  })

  it('wraps lon', () => {
    const state: MapViewState = { mapCenter: { lon: 720, lat: 0 }, zoom: 1 }
    const clamped = clampViewState(state, 1, 20)
    expect(clamped.mapCenter.lon).toBe(0)
  })
})
