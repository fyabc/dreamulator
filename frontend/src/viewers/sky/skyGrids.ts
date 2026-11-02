/** skyGrids — build the overlay grid layers (horizon / equatorial / ecliptic)
 *  from the engine result, generic over the projector so the pan view and the
 *  all-sky disc share one implementation.  The equatorial and ecliptic frames
 *  enter through a rotation fitted to the result's own coordinate pairs
 *  (frameFit), so no engine fields are added; a degenerate fit silently skips
 *  that grid instead of drawing a wrong one.
 */

import { eclipticDir, equatorialDir, fitRotation, type FramePair } from './frameFit'
import { enuFromAltAz, type Vec3 } from './panProjector'
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
    const rotation = fitRotation(
      framePairs(
        result,
        (row) =>
          row.ecliptic_lon_deg === null || row.ecliptic_lat_deg === null
            ? null
            : { along: row.ecliptic_lon_deg, across: row.ecliptic_lat_deg },
        eclipticDir,
      ),
    )
    if (rotation) {
      for (const d of greatCirclePaths(project, frameDirFrom(rotation, eclipticDir), 0)) {
        layers.push({ d, stroke: GRID_STYLES.ecliptic, width: 1.2 })
      }
    }
  }
  return layers
}
