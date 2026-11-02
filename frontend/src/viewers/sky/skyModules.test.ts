import { describe, expect, it } from 'vitest'

import { applyMat3, fitRotation, type FramePair } from './frameFit'
import { graticulePaths, greatCirclePaths } from './graticule'
import { estimateTextWidth, layoutLabels, type LabelItem } from './labelLayout'
import { buildMarkers, isOccultedMarker } from './markers'
import {
  clampLook,
  enuFromAltAz,
  fovFromPinch,
  groundPath,
  lookBasis,
  lookFromDrag,
  panProjector,
  wrapAzimuth,
} from './panProjector'
import { phasePathD, brightAngleRad, markerRadius } from './phaseGeometry'
import { ALTITUDE_RING_DEGREES, skyProjector } from './projector'
import { dayClock, dayReadout, sliderStep, sliderYearDays } from './timeFormat'

describe('skyProjector', () => {
  const p = skyProjector(320, 320, 300)

  it('places the cardinals for the looking-up view (E left)', () => {
    const north = p.project(0, 0)!
    const east = p.project(0, 90)!
    const south = p.project(0, 180)!
    const west = p.project(0, 270)!
    expect(north.y).toBeLessThan(320) // top
    expect(east.x).toBeLessThan(320) // left
    expect(south.y).toBeGreaterThan(320) // bottom
    expect(west.x).toBeGreaterThan(320) // right
  })

  it('puts the zenith at the centre and 30° at 2/3 radius', () => {
    const zenith = p.project(90, 123)!
    expect(zenith.x).toBeCloseTo(320, 9)
    expect(zenith.y).toBeCloseTo(320, 9)
    expect(p.project(30, 0)!.y).toBeCloseTo(320 - 300 * (60 / 90), 9)
    expect(ALTITUDE_RING_DEGREES).toEqual([30, 60])
  })

  it('wraps azimuth and rejects below-horizon points', () => {
    const a = p.project(10, 5)!
    const b = p.project(10, 365)!
    expect(a.x).toBeCloseTo(b.x, 9)
    expect(a.y).toBeCloseTo(b.y, 9)
    expect(p.project(-0.01, 0)).toBeNull()
  })

  it('projectUnclipped keeps below-horizon centres outside the disc', () => {
    // A setting giant needs its clipped-away position so the horizon
    // clipPath can render the above-horizon sliver.
    const below = p.projectUnclipped(-10, 0)
    // az 0 = north of centre; alt −10 → radius 300·100/90 beyond the rim.
    expect(below.y).toBeLessThan(320 - 300)
    const at = p.projectUnclipped(30, 0)
    expect(at.y).toBeCloseTo(p.project(30, 0)!.y, 9)
  })
})

describe('timeFormat', () => {
  it('splits days into whole solar days + fraction', () => {
    const r = dayReadout(61.979, 3.2352)
    expect(r.day).toBe(19)
    expect(r.fraction).toBeCloseTo(0.1577, 3)
    expect(dayReadout(61.979, null)).toEqual({ day: 61.979, fraction: 0 })
  })

  it('renders the epoch-relative dial HH:MM and wraps negative times', () => {
    expect(dayClock(0.5, 1.0)).toBe('12:00')
    expect(dayClock(1.25, 1.0)).toBe('06:00')
    expect(dayClock(-0.25, 1.0)).toBe('18:00')
    expect(dayClock(5, null)).toBeNull()
  })

  it('derives slider range from the parent period and step from the solar day', () => {
    const catalog = {
      bodies: [
        { id: 'sat', parent_id: 'planet', orbit: { period_days: 3.14 } },
        { id: 'planet', orbit: { period_days: 99.7 } },
      ],
    }
    expect(sliderYearDays(catalog, 'sat')).toBeCloseTo(99.7, 9)
    expect(sliderYearDays(catalog, 'unknown')).toBe(100)
    expect(sliderStep(3.0)).toBeCloseTo(0.125, 9)
    expect(sliderStep(null)).toBeCloseTo(0.01, 9)
  })
})

describe('phaseGeometry', () => {
  it('marker radius grows with angular diameter and clamps', () => {
    expect(markerRadius(0.5, 0.5)).toBeCloseTo(14, 6)
    expect(markerRadius(0.001, 0.5)).toBeCloseTo(2.5 + 11.5 * Math.sqrt(0.002), 6)
    expect(markerRadius(10, 0.5)).toBe(14)
  })

  it('builds the canonical construction with the star to the right', () => {
    // Star right (angle 0): p1 = bottom (100,120), p2 = top (100,80); the
    // limb semicircle runs bottom→top through the bright pole (120,100)
    // (screen-CCW ⇒ sweep 0); the terminator (rx = r·|2k−1|, ry = r) closes
    // top→bottom bulging toward the star for a crescent (sweep 1), away for
    // a gibbous (sweep 0), degenerating to a line at half phase.
    expect(phasePathD(100, 100, 20, 0.25, 0)).toBe(
      'M 100 120 A 20 20 0 0 0 100 80 A 10 20 0 0 1 100 120 Z',
    )
    expect(phasePathD(100, 100, 20, 0.75, 0)).toBe(
      'M 100 120 A 20 20 0 0 0 100 80 A 10 20 0 0 0 100 120 Z',
    )
    expect(phasePathD(100, 100, 20, 0.5, 0)).toBe(
      'M 100 120 A 20 20 0 0 0 100 80 A 0 20 0 0 0 100 120 Z',
    )
    expect(phasePathD(100, 100, 20, 0, 0)).toBe('')
    expect(phasePathD(100, 100, 20, 1, 0)).toMatch(/^M 80 100 A 20 20 0 1 1 120 100 A 20 20 0 1 1 80 100 Z$/)
  })

  it('rotates the construction with the bright angle', () => {
    // Star down (angle π/2): p1 = left (80,100), p2 = right (120,100); the
    // ellipse rotation tracks the bright angle (90°).
    expect(phasePathD(100, 100, 20, 0.25, Math.PI / 2)).toBe(
      'M 80 100 A 20 20 0 0 0 120 100 A 10 20 90 0 1 80 100 Z',
    )
  })

  it('brightAngle points from the marker to the star', () => {
    expect(brightAngleRad(0, 0, 10, 0)).toBeCloseTo(0, 9)
    expect(brightAngleRad(0, 0, 0, 10)).toBeCloseTo(Math.PI / 2, 9)
  })
})

describe('labelLayout', () => {
  const item = (id: string, x: number, y: number, text = 'Aegis', radius = 8): LabelItem => ({
    id,
    x,
    y,
    radius,
    text,
    fontSize: 11,
  })

  it('estimates CJK text wider than Latin of the same length', () => {
    expect(estimateTextWidth('巨械星', 11)).toBeCloseTo(33, 6)
    expect(estimateTextWidth('Aegis', 11)).toBeCloseTo(5 * 11 * 0.58, 6)
    expect(estimateTextWidth('巨械星-Aegis', 11)).toBeCloseTo(33 + 6 * 11 * 0.58, 6)
  })

  it('gives an isolated marker the default above-middle label', () => {
    const placements = layoutLabels([item('a', 100, 100)], [])
    const p = placements.get('a')!
    expect(p.anchor).toBe('middle')
    expect(p.dx).toBe(0)
    expect(p.dy).toBe(-13) // -(radius + 5)
  })

  it('moves the lower-priority label when two labels collide', () => {
    // Discs clear each other, but b's default above label would sit on a's disc.
    const placements = layoutLabels([item('a', 100, 100), item('b', 104, 120)], [])
    const a = placements.get('a')!
    const b = placements.get('b')!
    expect(a.anchor).toBe('middle')
    // b must not keep the default above slot that collides with a's disc.
    expect([b.dx, b.dy]).not.toEqual([0, -13])
  })

  it('dodges a static obstacle covering the above slot', () => {
    // A cardinal-sized box right above the marker.
    const obstacle = { left: 80, top: 60, right: 120, bottom: 90 }
    const placements = layoutLabels([item('a', 100, 100)], [obstacle])
    const p = placements.get('a')!
    expect(p.anchor).not.toBe('middle')
    expect(p.dx).toBeGreaterThan(0) // pushed to the right side
  })
})

describe('panProjector', () => {
  it('builds an orthonormal camera frame; facing north puts east right and zenith up', () => {
    const basis = lookBasis(0, 0)
    // forward = north, right = east, up = zenith (ENU).
    expect(basis.forward.e).toBe(0)
    expect(basis.forward.n).toBe(1)
    expect(basis.right.e).toBe(1)
    expect(basis.right.n).toBeCloseTo(0, 9) // −0 from −sin(0)
    expect(basis.up.u).toBe(1)
    for (const [az, alt] of [[37, 12], [214, -45], [90, 89.5]] as const) {
      const b = lookBasis(az, alt)
      const dot = (a: { e: number; n: number; u: number }, c: { e: number; n: number; u: number }) =>
        a.e * c.e + a.n * c.n + a.u * c.u
      expect(dot(b.forward, b.right)).toBeCloseTo(0, 9)
      expect(dot(b.forward, b.up)).toBeCloseTo(0, 9)
      expect(dot(b.right, b.up)).toBeCloseTo(0, 9)
      expect(Math.hypot(b.right.e, b.right.n, b.right.u)).toBeCloseTo(1, 9)
      expect(Math.hypot(b.up.e, b.up.n, b.up.u)).toBeCloseTo(1, 9)
    }
    // Pole limit stays finite (roll defined by azimuth).
    const pole = lookBasis(123, 90)
    expect(Math.hypot(pole.right.e, pole.right.n, pole.right.u)).toBeCloseTo(1, 9)
  })

  it('projects the view centre to the screen centre, east right, zenith up', () => {
    const p = panProjector(720, 480, { azDeg: 0, altDeg: 20, fovDeg: 90 })
    const centre = p.projectAltAz(20, 0)!
    expect(centre.x).toBeCloseTo(360, 6)
    expect(centre.y).toBeCloseTo(240, 6)
    // A body to the east (az +) appears right of centre; higher altitude appears above.
    const east = p.projectAltAz(20, 10)!
    expect(east.x).toBeGreaterThan(360)
    const higher = p.projectAltAz(30, 0)!
    expect(higher.y).toBeLessThan(240)
  })

  it('returns null behind the view plane and wraps/clamps look values', () => {
    const p = panProjector(720, 480, { azDeg: 0, altDeg: 0, fovDeg: 60 })
    expect(p.projectAltAz(0, 180)).toBeNull() // due south is behind
    expect(p.projectAltAz(10, 30)!.x).toBeGreaterThan(360) // east of the view
    const clamped = clampLook({ azDeg: -30, altDeg: 120, fovDeg: 400 })
    expect(clamped.azDeg).toBeCloseTo(330, 6)
    expect(clamped.altDeg).toBe(89.5)
    expect(clamped.fovDeg).toBe(120)
    expect(wrapAzimuth(720)).toBe(0)
  })

  it('fills the ground from the front horizon arc, empty when looking steeply up', () => {
    const horizonLook = panProjector(720, 480, { azDeg: 0, altDeg: 5, fovDeg: 90 })
    const ground = groundPath(horizonLook)
    expect(ground).toMatch(/^M /)
    expect(ground).toContain('Z')
    // At the altitude clamp the whole horizon grazes/behind the view plane.
    const up = panProjector(720, 480, { azDeg: 0, altDeg: 89.5, fovDeg: 90 })
    expect(groundPath(up)).toBe('')
  })

  it('maps grab-the-sky drags and pinch zooms', () => {
    const start = { azDeg: 10, altDeg: 5, fovDeg: 90 }
    // 100 px right, 50 px down at 0.2°/px: az drops (wraps to 350), alt climbs.
    const dragged = lookFromDrag(start, { x: 0, y: 0 }, { x: 100, y: 50 }, 0.2)
    expect(dragged.azDeg).toBeCloseTo(350, 6)
    expect(dragged.altDeg).toBeCloseTo(15, 6)
    // Spreading doubles the distance → field halves, clamped at the minimum.
    expect(fovFromPinch(90, 100, 200)).toBeCloseTo(45, 6)
    expect(fovFromPinch(20, 100, 400)).toBe(15)
  })
})

describe('frameFit', () => {
  // A known rotation: 90° about the u axis (e→n, n→−e) then tilt about e.
  const rotate = (v: { e: number; n: number; u: number }) => ({ e: -v.n, n: v.e, u: v.u })

  it('recovers an exact rotation from coordinate pairs', () => {
    const samples = [enuFromAltAz(23, 17), enuFromAltAz(-41, 158), enuFromAltAz(67, 291)]
    const pairs: FramePair[] = samples.map((b) => ({ a: rotate(b), b }))
    const rotation = fitRotation(pairs)!
    for (const { a, b } of pairs) {
      const mapped = applyMat3(rotation, a)
      expect(mapped.e).toBeCloseTo(b.e, 9)
      expect(mapped.n).toBeCloseTo(b.n, 9)
      expect(mapped.u).toBeCloseTo(b.u, 9)
    }
  })

  it('rejects collinear or inconsistent data', () => {
    const a = enuFromAltAz(0, 0)
    expect(fitRotation([{ a, b: a }, { a, b: a }])).toBeNull()
    const pairs: FramePair[] = [
      { a: enuFromAltAz(0, 0), b: enuFromAltAz(0, 0) },
      { a: enuFromAltAz(0, 90), b: enuFromAltAz(0, 90) },
      // The third pair contradicts the identity implied by the first two.
      { a: enuFromAltAz(0, 180), b: enuFromAltAz(0, 0) },
    ]
    expect(fitRotation(pairs)).toBeNull()
  })
})

describe('graticule', () => {
  const projector = panProjector(720, 480, { azDeg: 0, altDeg: 20, fovDeg: 120 })

  it('breaks grid segments at the view plane and yields path strings', () => {
    const paths = graticulePaths(projector.projectDir.bind(projector), (along, across) =>
      enuFromAltAz(across, along),
    )
    expect(paths.length).toBeGreaterThan(4)
    for (const d of paths) expect(d).toMatch(/^M [\d.-]+ [\d.-]+( L [\d.-]+ [\d.-]+)+$/)
  })

  it('draws a full great circle when it is in view and nothing when it is behind', () => {
    const inView = greatCirclePaths(projector.projectDir.bind(projector), (along) => enuFromAltAz(20, along))
    expect(inView.length).toBeGreaterThan(0)
    const up = panProjector(720, 480, { azDeg: 0, altDeg: 89.5, fovDeg: 60 })
    const horizonBehind = greatCirclePaths(up.projectDir.bind(up), (along) => enuFromAltAz(0, along))
    expect(horizonBehind.length).toBe(0)
  })
})

describe('markers', () => {
  const row = (id: string, alt: number, az: number, distanceKm: number, mag = 1) =>
    ({
      body_id: id,
      name: id,
      altitude_deg: alt,
      azimuth_deg: az,
      ecliptic_lon_deg: 0,
      ecliptic_lat_deg: 0,
      equatorial_ra_deg: 0,
      equatorial_dec_deg: 0,
      distance_km: distanceKm,
      angular_diameter_deg: 1,
      phase_angle_deg: null,
      illuminated_fraction: null,
      phase_function: null,
      apparent_magnitude: mag,
      illuminance_w_m2: 1,
      elongation_star_deg: null,
      elongation_parent_deg: null,
      altitude_rate_deg_per_hr: 0,
      rise_state: null,
      next_rise_days: null,
      next_set_days: null,
    }) as never
  const result = {
    observer_id: 'o',
    lat_deg: 0,
    lon_deg: 0,
    at_days: 0,
    solar_day_days: null,
    spin_source: null,
    targets: [row('near', 30, 0, 1e6), row('far', 31, 0, 1e9), row('below', -5, 90, 1e7)],
  } as never
  const build = buildMarkers(
    result,
    undefined,
    (alt, az) => (alt <= 0 ? null : { x: 100 + az, y: 200 - alt }),
    () => 40,
  )

  it('paintes far-to-near (occultation z-order) and splits the below-horizon row', () => {
    expect(build.markers.map((m) => m.row.body_id)).toEqual(['far', 'near'])
    expect(build.belowHorizon.map((r) => r.body_id)).toEqual(['below'])
  })

  it('flags a body whose centre hides behind a nearer disc', () => {
    const far = build.markers.find((m) => m.row.body_id === 'far')!
    const near = build.markers.find((m) => m.row.body_id === 'near')!
    // far sits 1 px from near's centre, inside its 40 px disc, and is farther.
    expect(isOccultedMarker(build.markers, far)).toBe(true)
    expect(isOccultedMarker(build.markers, near)).toBe(false)
  })
})
