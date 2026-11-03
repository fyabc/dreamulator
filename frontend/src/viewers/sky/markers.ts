/** markers — the shared body-marker pipeline for both sky views: project each
 *  target, size and colour the disc, aim the phase crescent's bright limb at
 *  the star's screen position, and split off the below-horizon rows.  The two
 *  charts differ only in projection and radius policy; this module is the
 *  common part (pure).
 */

import { brightAngleRad } from './phaseGeometry'
import { BODY_FILL, starColorCss } from './bodyColor'
import type { ScreenPoint } from './panProjector'
import type { SkyCatalog, SkyEphemerisResult, TargetPosition } from './types'

export interface Marker {
  row: TargetPosition
  x: number
  y: number
  radius: number
  fill: string
  brightAngle: number
  isStar: boolean
}

export type ProjectFn = (altDeg: number, azDeg: number) => ScreenPoint | null

export interface MarkerBuild {
  /** Above-horizon markers, dimmest first so bright ones draw on top. */
  markers: Marker[]
  belowHorizon: TargetPosition[]
}

export function buildMarkers(
  result: SkyEphemerisResult,
  catalog: SkyCatalog | undefined,
  project: ProjectFn,
  radiusOf: (angularDiameterDeg: number) => number,
): MarkerBuild {
  const starTemps = new Map<string, number | null | undefined>()
  for (const star of catalog?.stars ?? []) starTemps.set(star.id, star.temperature_k)
  const starRow = result.targets.find((r) => starTemps.has(r.body_id))
  const starPoint = starRow ? project(starRow.altitude_deg, starRow.azimuth_deg) : null

  const placed: Marker[] = []
  const below: TargetPosition[] = []
  for (const row of result.targets) {
    const point = project(row.altitude_deg, row.azimuth_deg)
    if (!point) {
      below.push(row)
      continue
    }
    const isStar = starTemps.has(row.body_id)
    placed.push({
      row,
      x: point.x,
      y: point.y,
      radius: radiusOf(row.angular_diameter_deg),
      fill: isStar ? starColorCss(starTemps.get(row.body_id)) : BODY_FILL,
      brightAngle: starPoint ? brightAngleRad(point.x, point.y, starPoint.x, starPoint.y) : 0,
      isStar,
    })
  }
  // Painter's algorithm by distance (far first): a nearer body paints over a
  // farther one, so occultation renders like every planetarium does it — the
  // near disc simply covers what is physically behind it.  (Magnitude order
  // would put a bright distant body on top of its occluder.)
  placed.sort((a, b) => b.row.distance_km - a.row.distance_km)
  return { markers: placed, belowHorizon: below }
}

/** True when the marker's centre sits behind a NEARER body's disc on screen
 *  (occulted): its label should not float over the occluder.  Painting order
 *  already hides the disc; hit-testing naturally picks the topmost body. */
export function isOccultedMarker(markers: Marker[], m: Marker): boolean {
  return markers.some(
    (o) =>
      o.row.body_id !== m.row.body_id &&
      o.row.distance_km < m.row.distance_km &&
      Math.hypot(o.x - m.x, o.y - m.y) < o.radius,
  )
}

/** Irradiation glare radius (px) added around bright bodies: the eye/optics
 *  point-spread that planetariums render for luminous sources.  Only bodies
 *  brighter than mag 1 glare — no background star qualifies, so the flux
 *  hierarchy (bright moon ≫ brightest star) reads on screen. */
export function glareRadiusPx(apparentMagnitude: number): number {
  return apparentMagnitude < 1 ? Math.min(6, (1 - apparentMagnitude) * 0.5) : 0
}

/** Labeled set policy shared by both charts: selected + hovered + the five
 *  brightest above the horizon. */
export function labeledIds(markers: Marker[], selectedId: string | null, hoveredId: string | null): Set<string> {
  const brightest = [...markers].sort((a, b) => a.row.apparent_magnitude - b.row.apparent_magnitude)
  const ids = new Set<string>([selectedId ?? '', hoveredId ?? ''])
  for (const m of brightest.slice(0, 5)) ids.add(m.row.body_id)
  return ids
}
