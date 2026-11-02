/** frameFit — recover the celestial-frame → ENU rotation from the engine
 *  result itself.  Every target row carries both coordinate sets (alt/az and
 *  equatorial RA/Dec, plus ecliptic lon/lat), so two well-separated bodies
 *  fix an exact rotation: build orthonormal bases from the same pair in both
 *  frames and take R = B·Aᵀ.  No engine field additions needed; the fit is
 *  checked against every pair and rejected (null) when the data disagrees,
 *  which keeps a degenerate configuration from drawing a wrong grid.
 */

import type { Vec3 } from './panProjector'

/** Row-major 3×3: maps frame-A vectors to frame-B vectors. */
export type Mat3 = readonly [Vec3, Vec3, Vec3]

function dot(a: Vec3, b: Vec3): number {
  return a.e * b.e + a.n * b.n + a.u * b.u
}

function cross(a: Vec3, b: Vec3): Vec3 {
  return { e: a.n * b.u - a.u * b.n, n: a.u * b.e - a.e * b.u, u: a.e * b.n - a.n * b.e }
}

function scale(a: Vec3, k: number): Vec3 {
  return { e: a.e * k, n: a.n * k, u: a.u * k }
}

function sub(a: Vec3, b: Vec3): Vec3 {
  return { e: a.e - b.e, n: a.n - b.n, u: a.u - b.u }
}

function normalize(a: Vec3): Vec3 {
  const len = Math.hypot(a.e, a.n, a.u)
  return len > 0 ? scale(a, 1 / len) : a
}

export function applyMat3(m: Mat3, v: Vec3): Vec3 {
  return {
    e: dot(m[0], v),
    n: dot(m[1], v),
    u: dot(m[2], v),
  }
}

/** Orthonormal basis whose first axis is along `a`, second in the a–b plane. */
function basisFrom(a: Vec3, b: Vec3): Mat3 {
  const u1 = normalize(a)
  const u2 = normalize(sub(b, scale(u1, dot(b, u1))))
  const u3 = cross(u1, u2)
  return [u1, u2, u3]
}

/** Bases as rows; the rotation mapping a → b is R = Bᵀ·A = Σ_m B_m ⊗ A_m
 *  (outer-product sum over the basis index). */
function rotationBetween(a: Mat3, b: Mat3): Mat3 {
  const row = (k: keyof Vec3): Vec3 => {
    const out: Vec3 = { e: 0, n: 0, u: 0 }
    for (let m = 0; m < 3; m++) {
      const factor = b[m][k]
      out.e += factor * a[m].e
      out.n += factor * a[m].n
      out.u += factor * a[m].u
    }
    return out
  }
  return [row('e'), row('n'), row('u')]
}

export interface FramePair {
  /** direction in frame A (e.g. equatorial) */
  a: Vec3
  /** the same physical direction in frame B (ENU alt/az) */
  b: Vec3
}

/** Max angular residual (radians) tolerated across all pairs. */
const FIT_TOLERANCE = 1e-3

/**
 * Fit the A→B rotation from exact coordinate pairs.  Picks the most
 * widely-separated anchor pair for numerical stability, then verifies every
 * pair; returns null when the data is degenerate or inconsistent.
 */
export function fitRotation(pairs: FramePair[]): Mat3 | null {
  if (pairs.length < 2) return null
  // anchor i: the first pair; anchor j: the pair furthest from it.
  let j = -1
  let best = -1
  for (let k = 1; k < pairs.length; k++) {
    const sep = dot(pairs[0].a, pairs[k].a)
    if (sep < best || j === -1) {
      best = sep
      j = k
    }
  }
  if (Math.abs(best) > 1 - 1e-6) return null // collinear anchors
  const basisA = basisFrom(pairs[0].a, pairs[j].a)
  const basisB = basisFrom(pairs[0].b, pairs[j].b)
  const rotation = rotationBetween(basisA, basisB)
  for (const { a, b } of pairs) {
    const mapped = applyMat3(rotation, a)
    if (dot(mapped, b) < 1 - FIT_TOLERANCE) return null
  }
  return rotation
}

/** Equatorial direction (RA in degrees, dec in degrees) as a unit vector. */
export function equatorialDir(raDeg: number, decDeg: number): Vec3 {
  const ra = raDeg * (Math.PI / 180)
  const dec = decDeg * (Math.PI / 180)
  return {
    e: Math.cos(dec) * Math.cos(ra),
    n: Math.cos(dec) * Math.sin(ra),
    u: Math.sin(dec),
  }
}

/** Ecliptic direction (lon/lat in degrees) as a unit vector. */
export function eclipticDir(lonDeg: number, latDeg: number): Vec3 {
  const lon = lonDeg * (Math.PI / 180)
  const lat = latDeg * (Math.PI / 180)
  return {
    e: Math.cos(lat) * Math.cos(lon),
    n: Math.cos(lat) * Math.sin(lon),
    u: Math.sin(lat),
  }
}
