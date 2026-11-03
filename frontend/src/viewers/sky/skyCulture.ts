/** Sky-culture geometry — pure helpers (the backgroundStars precedent).
 *
 *  Culture files carry ids only; positions are joined here against the
 *  background catalogue.  Edges are sampled along the great circle between
 *  their endpoints in the catalog frame, so a figure stays straight on the
 *  sphere in both projections (the bandPath sampling posture) and the
 *  sampling is viewer-independent — only the rotate+project step runs per
 *  frame.
 */

import type { Vec3 } from './panProjector'
import type { SkyBackground, SkyCultureAsterism, SkyCultureEntry } from './types'

/** Degrees between great-circle samples along an asterism edge. */
const EDGE_STEP_DEG = 2
/** Safety cap on samples per edge (huge figures stay cheap). */
const MAX_SAMPLES = 64

export type Unit = [number, number, number]

export function toVec3(unit: Unit): Vec3 {
  return { e: unit[0], n: unit[1], u: unit[2] }
}

/** Id -> catalog-frame unit vector for every referenceable object.
 *  Mirrors the backend rule: authored stars and deep-sky objects only —
 *  procedural starfield ids are never referenceable. */
export function buildCultureLookup(background: SkyBackground): Map<string, Unit> {
  const lookup = new Map<string, Unit>()
  for (const star of background.stars) {
    if (star.source === 'authored') lookup.set(star.id, star.unit)
  }
  for (const dso of background.deep_sky) lookup.set(dso.id, dso.unit)
  return lookup
}

/** Great-circle (slerp) samples between two unit vectors, endpoints included. */
export function greatCircleSamples(a: Vec3, b: Vec3, stepDeg = EDGE_STEP_DEG): Vec3[] {
  const dot = Math.min(1, Math.max(-1, a.e * b.e + a.n * b.n + a.u * b.u))
  const omega = Math.acos(dot)
  if (omega < 1e-9) return [a, b]
  const steps = Math.max(1, Math.min(MAX_SAMPLES, Math.ceil((omega * 180) / Math.PI / stepDeg)))
  const sinOmega = Math.sin(omega)
  const points: Vec3[] = []
  for (let i = 0; i <= steps; i++) {
    const t = i / steps
    const sa = Math.sin((1 - t) * omega) / sinOmega
    const sb = Math.sin(t * omega) / sinOmega
    points.push({ e: sa * a.e + sb * b.e, n: sa * a.n + sb * b.n, u: sa * a.u + sb * b.u })
  }
  return points
}

export interface AsterismGeometry {
  asterism: SkyCultureAsterism
  culture: SkyCultureEntry
  /** Sampled edges in catalog-frame unit vectors (unresolvable ids skipped). */
  edges: Vec3[][]
  /** Normalized mean of the resolved vertices — the name-label anchor. */
  centroid: Vec3 | null
  /** Resolved vertex ids in edge order of first appearance. */
  memberIds: string[]
}

/** Join one asterism's edges against the catalogue. Null when nothing resolves
 *  (a stale culture against a changed catalogue degrades to "no figure" —
 *  the build-time validator is the authority, this is defence in depth). */
export function buildAsterismGeometry(
  culture: SkyCultureEntry,
  asterism: SkyCultureAsterism,
  lookup: Map<string, Unit>,
): AsterismGeometry | null {
  const edges: Vec3[][] = []
  const memberIds: string[] = []
  const vertexSum = { e: 0, n: 0, u: 0 }
  for (const [idA, idB] of asterism.lines) {
    const ua = lookup.get(idA)
    const ub = lookup.get(idB)
    if (!ua || !ub) continue
    edges.push(greatCircleSamples(toVec3(ua), toVec3(ub)))
    for (const id of [idA, idB]) {
      if (!memberIds.includes(id)) memberIds.push(id)
      const unit = lookup.get(id)!
      vertexSum.e += unit[0]
      vertexSum.n += unit[1]
      vertexSum.u += unit[2]
    }
  }
  if (edges.length === 0) return null
  const len = Math.hypot(vertexSum.e, vertexSum.n, vertexSum.u)
  const centroid =
    len > 1e-9
      ? { e: vertexSum.e / len, n: vertexSum.n / len, u: vertexSum.u / len }
      : null
  return { asterism, culture, edges, centroid, memberIds }
}
