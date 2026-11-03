/** graticule — sample a celestial frame's coordinate grid into SVG path
 *  strings for whichever projector is active (pan or all-sky disc).  The
 *  frame enters as a pure direction function (frame coordinate pair → ENU
 *  vector); parallels are the constant-"latitude" circles, meridians the
 *  constant-"longitude" arcs.  Segments break wherever the projector returns
 *  null (behind the view plane / below the disc's horizon).
 */

import type { ScreenPoint, Vec3 } from './panProjector'
import { applyMat3, type Mat3 } from './frameFit'

export type ProjectDir = (v: Vec3) => ScreenPoint | null
export type FrameDir = (along: number, across: number) => Vec3

export interface GraticuleOptions {
  /** degrees between parallels (constant across) */
  parallelStep?: number
  /** degrees between meridians (constant along) */
  meridianStep?: number
  /** inclusive across-range for the parallels, e.g. [-60, 60] */
  parallelRange?: [number, number]
  /** inclusive across-range endpoints for the meridian arcs */
  meridianRange?: [number, number]
}

function polyline(project: ProjectDir, points: Vec3[]): string[] {
  const segments: string[] = []
  let current: string[] = []
  for (const v of points) {
    const p = project(v)
    if (p) current.push(`${p.x.toFixed(1)} ${p.y.toFixed(1)}`)
    else if (current.length > 1) {
      segments.push(current.join(' L '))
      current = []
    } else current = []
  }
  if (current.length > 1) segments.push(current.join(' L '))
  return segments.map((seg) => `M ${seg}`)
}

export function graticulePaths(
  project: ProjectDir,
  dir: FrameDir,
  options: GraticuleOptions = {},
): string[] {
  const {
    parallelStep = 30,
    meridianStep = 30,
    parallelRange = [-60, 60],
    meridianRange = [-75, 75],
  } = options
  const paths: string[] = []
  // Parallels: full circles of constant across.
  for (let across = parallelRange[0]; across <= parallelRange[1] + 1e-9; across += parallelStep) {
    const points: Vec3[] = []
    for (let along = 0; along <= 360 + 1e-9; along += 3) points.push(dir(along % 360, across))
    paths.push(...polyline(project, points))
  }
  // Meridians: arcs of constant along.
  for (let along = 0; along < 360 - 1e-9; along += meridianStep) {
    const points: Vec3[] = []
    for (let across = meridianRange[0]; across <= meridianRange[1] + 1e-9; across += 3) {
      points.push(dir(along, across))
    }
    paths.push(...polyline(project, points))
  }
  return paths
}

/** One highlighted circle of constant across (the ecliptic, the celestial
 *  equator): sampled finer than a grid. */
export function greatCirclePaths(project: ProjectDir, dir: FrameDir, across = 0): string[] {
  const points: Vec3[] = []
  for (let along = 0; along <= 360 + 1e-9; along += 2) points.push(dir(along % 360, across))
  return polyline(project, points)
}

/** Convert a fitted frame rotation into the direction function the grid
 *  drawers want (frame along/across degrees → rotated ENU vector). */
export function frameDirFrom(
  rotation: Mat3,
  coord: (along: number, across: number) => Vec3,
): FrameDir {
  return (along: number, across: number) => applyMat3(rotation, coord(along, across))
}
