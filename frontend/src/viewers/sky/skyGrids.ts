/** skyGrids — build the overlay grid layers (horizon / equatorial / ecliptic)
 *  from the engine result, generic over the projector so the pan view and the
 *  all-sky disc share one implementation.  The equatorial and ecliptic frames
 *  enter through a rotation fitted to the result's own coordinate pairs
 *  (frameFit), so no engine fields are added; a degenerate fit silently skips
 *  that grid instead of drawing a wrong one.
 */

import {
  applyMat3Transpose,
  eclipticDir,
  equatorialDir,
  fitRotation,
  type FramePair,
  type Mat3,
} from './frameFit'
import { enuFromAltAz, type LookDirection, type Vec3 } from './panProjector'
import { frameDirFrom, greatCirclePaths, graticulePaths, type ProjectDir } from './graticule'
import type { SkyEphemerisResult, TargetPosition } from './types'

export interface GridToggles {
  altAz: boolean
  equatorial: boolean
  ecliptic: boolean
}

export const GRID_STYLES = {
  grid: 'rgba(255,255,255,0.12)',
  /** Equatorial graticule — the equator's blue, dimmed so the highlighted
   *  equator line still reads as the anchor of the family. */
  equatorialGrid: 'rgba(77,166,255,0.25)',
  equator: 'rgba(77,166,255,0.45)',
  ecliptic: 'rgba(240,192,64,0.42)',
} as const

export interface GridLayer {
  d: string
  stroke: string
  dash?: string
  width?: number
}

type FrameCoord = (row: TargetPosition) => { along: number; across: number } | null
type FrameDirBuilder = (along: number, across: number) => Vec3

function framePairs(result: SkyEphemerisResult, coord: FrameCoord, dirOf: FrameDirBuilder): FramePair[] {
  const out: FramePair[] = []
  for (const row of result.targets) {
    const c = coord(row)
    if (c === null) continue
    out.push({ a: dirOf(c.along, c.across), b: enuFromAltAz(row.altitude_deg, row.azimuth_deg) })
  }
  return out
}

export function buildGridLayers(
  result: SkyEphemerisResult,
  project: ProjectDir,
  toggles: GridToggles,
): GridLayer[] {
  const layers: GridLayer[] = []
  if (toggles.altAz) {
    // along = azimuth, across = altitude.
    const dir: FrameDirBuilder = (along, across) => enuFromAltAz(across, along)
    for (const d of graticulePaths(project, dir)) {
      layers.push({ d, stroke: GRID_STYLES.grid, dash: '3 7' })
    }
  }
  if (toggles.equatorial) {
    const rotation = fitRotation(
      framePairs(
        result,
        (row) =>
          row.equatorial_ra_deg === null || row.equatorial_dec_deg === null
            ? null
            : { along: row.equatorial_ra_deg, across: row.equatorial_dec_deg },
        equatorialDir,
      ),
    )
    if (rotation) {
      const dir = frameDirFrom(rotation, equatorialDir)
      for (const d of graticulePaths(project, dir)) {
        layers.push({ d, stroke: GRID_STYLES.equatorialGrid, dash: '3 7' })
      }
      for (const d of greatCirclePaths(project, dir, 0)) {
        layers.push({ d, stroke: GRID_STYLES.equator, width: 1.2 })
      }
    }
  }
  if (toggles.ecliptic) {
    const rotation = eclipticRotation(result)
    if (rotation) {
      for (const d of greatCirclePaths(project, frameDirFrom(rotation, eclipticDir), 0)) {
        layers.push({ d, stroke: GRID_STYLES.ecliptic, width: 1.2 })
      }
    }
  }
  return layers
}

/** The ecliptic → ENU rotation fitted from the result's own dual coordinates.
 *  Shared by the ecliptic grid and the background-sky layer (both rotate
 *  ecliptic-frame directions into the observer frame). */
export function eclipticRotation(result: SkyEphemerisResult): import('./frameFit').Mat3 | null {
  return fitRotation(
    framePairs(
      result,
      (row) =>
        row.ecliptic_lon_deg === null || row.ecliptic_lat_deg === null
          ? null
          : { along: row.ecliptic_lon_deg, across: row.ecliptic_lat_deg },
      eclipticDir,
    ),
  )
}

/** Degree tick labels for the grids, placed where planetariums put them:
 *  parallel values ride the view's central meridian (pan) or the N–S axis
 *  (disc); meridian values ride the horizon (alt/az) or the equator (RA/dec).
 *  Positions that would sit on a cardinal label are skipped. */
export interface GridLabel {
  x: number
  y: number
  text: string
}

const PARALLEL_LABELS = [-60, -30, 30, 60]
const MERIDIAN_LABELS = [30, 60, 120, 150, 210, 240, 300, 330] // 0/90/180/270 = cardinals, 45s = intercardinals

function raDecOf(v: Vec3): { ra: number; dec: number } {
  const dec = (Math.asin(Math.max(-1, Math.min(1, v.u))) * 180) / Math.PI
  const ra = (((Math.atan2(v.n, v.e) * 180) / Math.PI) % 360 + 360) % 360
  return { ra, dec }
}

export function gridLabels(
  kind: 'altAz' | 'equatorial',
  project: ProjectDir,
  opts: {
    mode: 'pan' | 'disc'
    rotation?: Mat3 | null
    look?: LookDirection
    /** Disc centre in chart pixels (rim labels pull toward it). */
    center?: { x: number; y: number }
  },
): GridLabel[] {
  const labels: GridLabel[] = []
  const push = (v: Vec3, text: string, dx: number, dy: number) => {
    const p = project(v)
    if (p) labels.push({ x: p.x + dx, y: p.y + dy, text })
  }
  if (kind === 'altAz') {
    const dir: FrameDirBuilder = (along, across) => enuFromAltAz(across, along)
    const parallelAz = opts.mode === 'pan' ? (opts.look?.azDeg ?? 0) : 180
    for (const alt of PARALLEL_LABELS) {
      push(dir(parallelAz, alt), `${alt > 0 ? '+' : ''}${alt}°`, 4, opts.mode === 'pan' ? -4 : 3)
    }
    for (const az of MERIDIAN_LABELS) {
      if (opts.mode === 'disc' && opts.center) {
        // Just inside the horizon rim (the rim carries the horizon stroke).
        const p = project(dir(az, 0))
        if (p) {
          labels.push({
            x: p.x + (opts.center.x - p.x) * 0.07,
            y: p.y + (opts.center.y - p.y) * 0.07 + 3,
            text: `${az}°`,
          })
        }
      } else {
        push(dir(az, 0), `${az}°`, 0, -8)
      }
    }
    return labels
  }
  // equatorial
  const rotation = opts.rotation
  if (!rotation) return labels
  const dir = frameDirFrom(rotation, equatorialDir)
  // The view centre (pan: look direction; disc: zenith) in equatorial coords.
  const centreEnu: Vec3 =
    opts.mode === 'pan' && opts.look
      ? enuFromAltAz(opts.look.altDeg, opts.look.azDeg)
      : { e: 0, n: 0, u: 1 }
  const { ra: raCentre } = raDecOf(applyMat3Transpose(rotation, centreEnu))
  for (const dec of PARALLEL_LABELS) {
    push(dir(raCentre, dec), `${dec > 0 ? '+' : ''}${dec}°`, 4, -4)
  }
  for (const ra of MERIDIAN_LABELS) {
    push(dir(ra, 0), `${ra}°`, 4, -4)
  }
  return labels
}
