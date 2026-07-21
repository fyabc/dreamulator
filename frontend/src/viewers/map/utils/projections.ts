/**
 * Map projection algorithms for rendering spherical CVT mesh data on a flat screen.
 *
 * Each projection converts between geographic coordinates (lon/lat in degrees)
 * and a normalised [0,1]×[0,1] coordinate space where:
 * - x=0 is the left edge, x=1 is the right edge
 * - y=0 is the top (north), y=1 is the bottom (south)
 *
 * All projections handle edge cases (poles, antimeridian, out-of-range inputs)
 * gracefully via clamping.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type ProjectionType = 'equirectangular' | 'mollweide' | 'robinson'

export interface Projection {
  name: string
  type: ProjectionType
  forward(lon: number, lat: number): [number, number]
  inverse(x: number, y: number): [number, number]
  /** Width / height ratio of the projected map. */
  aspectRatio: number
  /** Whether the projection supports horizontal longitude wrapping. */
  wraps: boolean
}

/** All available projection types. */
export const PROJECTION_LIST: ProjectionType[] = [
  'equirectangular',
  'mollweide',
  'robinson',
]

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const DEG2RAD = Math.PI / 180
const RAD2DEG = 180 / Math.PI

/** Clamp a value to [lo, hi]. */
function clamp(v: number, lo: number, hi: number): number {
  return v < lo ? lo : v > hi ? hi : v
}

// ---------------------------------------------------------------------------
// Equirectangular (Plate Carrée)
// ---------------------------------------------------------------------------

const equirectangular: Projection = {
  name: 'Equirectangular',
  type: 'equirectangular',
  aspectRatio: 2, // 360° / 180°
  wraps: true,

  forward(lon: number, lat: number): [number, number] {
    const clon = clamp(lon, -180, 180)
    const clat = clamp(lat, -90, 90)
    const x = (clon + 180) / 360
    const y = (90 - clat) / 180
    return [x, y]
  },

  inverse(x: number, y: number): [number, number] {
    const cx = clamp(x, 0, 1)
    const cy = clamp(y, 0, 1)
    const lon = cx * 360 - 180
    const lat = 90 - cy * 180
    return [lon, lat]
  },
}

// ---------------------------------------------------------------------------
// Mollweide (equal-area)
// ---------------------------------------------------------------------------

/**
 * Solve the auxiliary angle θ for Mollweide via Newton's method.
 *
 * Equation: 2θ + sin(2θ) = π·sin(φ)
 * Rewrite:  f(θ) = 2θ + sin(2θ) - π·sin(φ) = 0
 *           f'(θ) = 2 + 2·cos(2θ)
 */
function mollweideTheta(latRad: number): number {
  const piSinPhi = Math.PI * Math.sin(latRad)
  // Initial guess: θ ≈ φ (works well except near poles)
  let theta = latRad
  for (let i = 0; i < 20; i++) {
    const twoTheta = 2 * theta
    const f = twoTheta + Math.sin(twoTheta) - piSinPhi
    const fPrime = 2 + 2 * Math.cos(twoTheta)
    if (Math.abs(fPrime) < 1e-12) break
    const delta = f / fPrime
    theta -= delta
    if (Math.abs(delta) < 1e-10) break
  }
  return theta
}

const SQRT2 = Math.SQRT2 // ≈ 1.4142135623730951
const TWO_SQRT2_OVER_PI = (2 * Math.SQRT2) / Math.PI // ≈ 0.9003163161571061

const mollweide: Projection = {
  name: 'Mollweide',
  type: 'mollweide',
  aspectRatio: 2, // width 4√2 / height 2√2 = 2
  wraps: false, // elliptical boundary

  forward(lon: number, lat: number): [number, number] {
    const clon = clamp(lon, -180, 180)
    const clat = clamp(lat, -90, 90)
    const lamRad = clon * DEG2RAD
    const phiRad = clat * DEG2RAD

    const theta = mollweideTheta(phiRad)

    // Raw Mollweide: x ∈ [-2√2, 2√2], y ∈ [-√2, √2]
    const xRaw = TWO_SQRT2_OVER_PI * lamRad * Math.cos(theta)
    const yRaw = SQRT2 * Math.sin(theta)

    // Normalise to [0, 1]
    const x = (xRaw / (2 * SQRT2) + 1) / 2 // [-2√2,2√2] → [0,1]
    const y = (1 - yRaw / SQRT2) / 2 // [-√2,√2] → [0,1] (north=0)
    return [clamp(x, 0, 1), clamp(y, 0, 1)]
  },

  inverse(x: number, y: number): [number, number] {
    const cx = clamp(x, 0, 1)
    const cy = clamp(y, 0, 1)

    // Un-normalise
    const xRaw = (2 * cx - 1) * 2 * SQRT2 // [0,1] → [-2√2, 2√2]
    const yRaw = (1 - 2 * cy) * SQRT2 // [0,1] → [-√2, √2]

    const theta = Math.asin(clamp(yRaw / SQRT2, -1, 1))
    const cosTheta = Math.cos(theta)

    // Recover latitude from θ: sin(φ) = (2θ + sin(2θ)) / π
    const sinPhi = (2 * theta + Math.sin(2 * theta)) / Math.PI
    const lat = Math.asin(clamp(sinPhi, -1, 1)) * RAD2DEG

    // Recover longitude: λ = π·x / (2√2·cos(θ))
    let lon: number
    if (Math.abs(cosTheta) < 1e-10) {
      // At the poles, longitude is indeterminate
      lon = 0
    } else {
      lon = ((Math.PI * xRaw) / (2 * SQRT2 * cosTheta)) * RAD2DEG
    }
    lon = clamp(lon, -180, 180)
    return [lon, clamp(lat, -90, 90)]
  },
}

// ---------------------------------------------------------------------------
// Robinson (compromise)
// ---------------------------------------------------------------------------

/**
 * Robinson lookup table at 5° latitude intervals.
 *
 * Each row: [latitude°, parallel-length (PLEN), parallel-displacement (PDFE)]
 * Source: Arthur H. Robinson (1969), "Elements of the Robinson Projection".
 */
const ROBINSON_TABLE: [number, number, number][] = [
  [0, 1.0, 0.0],
  [5, 0.9986, 0.062],
  [10, 0.9954, 0.124],
  [15, 0.99, 0.186],
  [20, 0.9822, 0.248],
  [25, 0.973, 0.31],
  [30, 0.96, 0.372],
  [35, 0.9427, 0.434],
  [40, 0.9216, 0.4958],
  [45, 0.8962, 0.5571],
  [50, 0.8679, 0.6176],
  [55, 0.835, 0.6769],
  [60, 0.7986, 0.7346],
  [65, 0.7597, 0.7903],
  [70, 0.7186, 0.8435],
  [75, 0.6732, 0.8936],
  [80, 0.6213, 0.9394],
  [85, 0.5722, 0.9761],
  [90, 0.5322, 1.0],
]

/** Robinson scaling constant for x. */
const ROBINSON_X_SCALE = 0.8473

/**
 * Maximum raw x extent: ROBINSON_X_SCALE · π · PLEN(0°) = 0.8473·π ≈ 2.6618.
 * Maximum raw y extent: PDFE(90°) = 1.0.
 */
const ROBINSON_X_MAX = ROBINSON_X_SCALE * Math.PI
const ROBINSON_Y_MAX = 1.0

/** Aspect ratio: full width / full height. */
const ROBINSON_ASPECT = (2 * ROBINSON_X_MAX) / (2 * ROBINSON_Y_MAX) // ≈ 2.6618

/**
 * Linearly interpolate the Robinson table for a given absolute latitude (degrees).
 * Returns [PLEN, PDFE].
 */
function robinsonInterp(absLatDeg: number): [number, number] {
  const lat = clamp(absLatDeg, 0, 90)
  const idx = Math.floor(lat / 5)
  if (idx >= ROBINSON_TABLE.length - 1) {
    const last = ROBINSON_TABLE[ROBINSON_TABLE.length - 1]
    return [last[1], last[2]]
  }
  const frac = (lat - idx * 5) / 5
  const lo = ROBINSON_TABLE[idx]
  const hi = ROBINSON_TABLE[idx + 1]
  const plen = lo[1] + frac * (hi[1] - lo[1])
  const pdfe = lo[2] + frac * (hi[2] - lo[2])
  return [plen, pdfe]
}

const robinson: Projection = {
  name: 'Robinson',
  type: 'robinson',
  aspectRatio: ROBINSON_ASPECT,
  wraps: false, // parallels shorten toward poles

  forward(lon: number, lat: number): [number, number] {
    const clon = clamp(lon, -180, 180)
    const clat = clamp(lat, -90, 90)
    const lamRad = clon * DEG2RAD

    const [plen, pdfe] = robinsonInterp(Math.abs(clat))

    // Raw coordinates
    const xRaw = ROBINSON_X_SCALE * lamRad * plen
    const yRaw = pdfe * Math.sign(clat)

    // Normalise to [0,1]
    const x = (xRaw / ROBINSON_X_MAX + 1) / 2
    const y = (1 - yRaw / ROBINSON_Y_MAX) / 2
    return [clamp(x, 0, 1), clamp(y, 0, 1)]
  },

  inverse(x: number, y: number): [number, number] {
    const cx = clamp(x, 0, 1)
    const cy = clamp(y, 0, 1)

    // Un-normalise y to get raw PDFE value
    const yRaw = (1 - 2 * cy) * ROBINSON_Y_MAX // [-1, 1]
    const absPdffe = Math.abs(yRaw)

    // Invert the table: find latitude whose PDFE matches absPdffe.
    // Walk the table to find the bracketing interval, then interpolate.
    let absLatDeg = 90
    for (let i = 0; i < ROBINSON_TABLE.length - 1; i++) {
      const loPdfe = ROBINSON_TABLE[i][2]
      const hiPdfe = ROBINSON_TABLE[i + 1][2]
      if (absPdffe >= loPdfe && absPdffe <= hiPdfe) {
        const frac = (absPdffe - loPdfe) / (hiPdfe - loPdfe)
        absLatDeg = ROBINSON_TABLE[i][0] + frac * 5
        break
      }
    }

    const lat = absLatDeg * Math.sign(yRaw)

    // Recover longitude from x
    const xRaw = (2 * cx - 1) * ROBINSON_X_MAX
    const [plen] = robinsonInterp(absLatDeg)
    let lon: number
    if (Math.abs(plen) < 1e-10) {
      lon = 0
    } else {
      lon = (xRaw / (ROBINSON_X_SCALE * plen)) * RAD2DEG
    }
    lon = clamp(lon, -180, 180)
    return [lon, clamp(lat, -90, 90)]
  },
}

// ---------------------------------------------------------------------------
// Projection registry
// ---------------------------------------------------------------------------

const REGISTRY: Record<ProjectionType, Projection> = {
  equirectangular,
  mollweide,
  robinson,
}

/** Factory: get a projection by type. */
export function getProjection(type: ProjectionType): Projection {
  return REGISTRY[type]
}

// ---------------------------------------------------------------------------
// Convenience pixel helpers
// ---------------------------------------------------------------------------

/**
 * Project geographic coordinates to pixel coordinates within a given viewport.
 *
 * @param lon  Longitude in degrees (−180 to 180).
 * @param lat  Latitude in degrees (−90 to 90).
 * @param proj The projection to use.
 * @param width  Viewport width in pixels.
 * @param height Viewport height in pixels.
 * @returns [px, py] pixel coordinates.
 */
export function projectLonLatToPixel(
  lon: number,
  lat: number,
  proj: Projection,
  width: number,
  height: number,
): [number, number] {
  const [nx, ny] = proj.forward(lon, lat)
  return [nx * width, ny * height]
}

/**
 * Convert pixel coordinates back to geographic coordinates.
 *
 * @param px  Pixel x.
 * @param py  Pixel y.
 * @param proj The projection to use.
 * @param width  Viewport width in pixels.
 * @param height Viewport height in pixels.
 * @returns [lon, lat] in degrees.
 */
export function pixelToLonLat(
  px: number,
  py: number,
  proj: Projection,
  width: number,
  height: number,
): [number, number] {
  const nx = px / width
  const ny = py / height
  return proj.inverse(nx, ny)
}
