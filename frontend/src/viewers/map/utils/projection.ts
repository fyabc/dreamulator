/**
 * Coordinate conversion utilities for map projections.
 *
 * Converts between three coordinate systems:
 * - Geographic: (lon, lat) in degrees
 * - Normalised: (nx, ny) in [0, 1] range
 * - Pixel: (x, y) in raster pixels
 */

// ---------------------------------------------------------------------------
// Projection type
// ---------------------------------------------------------------------------

/** Supported map projections. */
export type ProjectionType = 'equirectangular' | 'mollweide' | 'robinson'

/** All available projections (for UI dropdowns). */
export const PROJECTIONS: { id: ProjectionType; label: string }[] = [
  { id: 'equirectangular', label: '等距圆柱 (Plate Carrée)' },
  { id: 'mollweide', label: '摩尔威德' },
  { id: 'robinson', label: '罗宾逊' },
]

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const DEG2RAD = Math.PI / 180
const RAD2DEG = 180 / Math.PI

function clamp(v: number, lo: number, hi: number): number {
  return v < lo ? lo : v > hi ? hi : v
}

// ---------------------------------------------------------------------------
// Mollweide helpers
// ---------------------------------------------------------------------------

const SQRT2 = Math.SQRT2

function mollweideTheta(latRad: number): number {
  const piSinPhi = Math.PI * Math.sin(latRad)
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

// ---------------------------------------------------------------------------
// Robinson table (5° intervals, 0° to 90°)
// [plen, pdfe]
// ---------------------------------------------------------------------------

const ROBINSON_TABLE: [number, number][] = [
  [1.0000, 0.0000], [0.9986, 0.0620], [0.9954, 0.1240], [0.9900, 0.1860],
  [0.9822, 0.2480], [0.9730, 0.3100], [0.9600, 0.3720], [0.9427, 0.4340],
  [0.9216, 0.4958], [0.8962, 0.5571], [0.8679, 0.6176], [0.8350, 0.6769],
  [0.7986, 0.7346], [0.7597, 0.7903], [0.7186, 0.8435], [0.6732, 0.8936],
  [0.6213, 0.9394], [0.5722, 0.9761], [0.5322, 1.0000],
]

const ROBINSON_X_SCALE = 0.8473
const ROBINSON_X_MAX = ROBINSON_X_SCALE * Math.PI // ≈ 2.6618
const ROBINSON_Y_MAX = 1.0

function robinsonInterp(absLatDeg: number): [number, number] {
  const lat = clamp(absLatDeg, 0, 90)
  const idx = Math.floor(lat / 5)
  if (idx >= ROBINSON_TABLE.length - 1) {
    const last = ROBINSON_TABLE[ROBINSON_TABLE.length - 1]
    return [last[0], last[1]]
  }
  const frac = (lat - idx * 5) / 5
  const lo = ROBINSON_TABLE[idx]
  const hi = ROBINSON_TABLE[idx + 1]
  return [lo[0] + frac * (hi[0] - lo[0]), lo[1] + frac * (hi[1] - lo[1])]
}

// ---------------------------------------------------------------------------
// Projection forward/inverse (lon,lat ↔ normalised)
// ---------------------------------------------------------------------------

/**
 * Forward projection: (lon, lat) → normalised (nx, ny) in [0, 1].
 */
export function projectForward(
  projection: ProjectionType,
  lon: number,
  lat: number,
): { nx: number; ny: number } {
  switch (projection) {
    case 'equirectangular':
      return {
        nx: (clamp(lon, -180, 180) + 180) / 360,
        ny: (90 - clamp(lat, -90, 90)) / 180,
      }
    case 'mollweide': {
      const phiRad = clamp(lat, -90, 90) * DEG2RAD
      const lamRad = clamp(lon, -180, 180) * DEG2RAD
      const theta = mollweideTheta(phiRad)
      const xRaw = (2 * SQRT2 / Math.PI) * lamRad * Math.cos(theta)
      const yRaw = SQRT2 * Math.sin(theta)
      return {
        nx: clamp((xRaw / (2 * SQRT2) + 1) / 2, 0, 1),
        ny: clamp((1 - yRaw / SQRT2) / 2, 0, 1),
      }
    }
    case 'robinson': {
      const clon = clamp(lon, -180, 180)
      const clat = clamp(lat, -90, 90)
      const [plen, pdfe] = robinsonInterp(Math.abs(clat))
      const xRaw = ROBINSON_X_SCALE * clon * DEG2RAD * plen
      const yRaw = pdfe * Math.sign(clat)
      return {
        nx: clamp((xRaw / ROBINSON_X_MAX + 1) / 2, 0, 1),
        ny: clamp((1 - yRaw / ROBINSON_Y_MAX) / 2, 0, 1),
      }
    }
  }
}

/**
 * Inverse projection: normalised (nx, ny) → (lon, lat).
 */
export function projectInverse(
  projection: ProjectionType,
  nx: number,
  ny: number,
): { lon: number; lat: number } {
  switch (projection) {
    case 'equirectangular':
      return {
        lon: clamp(nx, 0, 1) * 360 - 180,
        lat: 90 - clamp(ny, 0, 1) * 180,
      }
    case 'mollweide': {
      const cx = clamp(nx, 0, 1)
      const cy = clamp(ny, 0, 1)
      const xRaw = (2 * cx - 1) * 2 * SQRT2
      const yRaw = (1 - 2 * cy) * SQRT2
      const theta = Math.asin(clamp(yRaw / SQRT2, -1, 1))
      const cosTheta = Math.cos(theta)
      const sinPhi = (2 * theta + Math.sin(2 * theta)) / Math.PI
      const lat = Math.asin(clamp(sinPhi, -1, 1)) * RAD2DEG
      const lon = Math.abs(cosTheta) < 1e-10
        ? 0
        : (Math.PI * xRaw) / (2 * SQRT2 * cosTheta) * RAD2DEG
      return { lon: clamp(lon, -180, 180), lat: clamp(lat, -90, 90) }
    }
    case 'robinson': {
      const cx = clamp(nx, 0, 1)
      const cy = clamp(ny, 0, 1)
      const xRaw = (2 * cx - 1) * ROBINSON_X_MAX
      const yRaw = (1 - 2 * cy) * ROBINSON_Y_MAX
      const absPdfe = Math.abs(yRaw)

      // Invert table to find latitude
      let absLatDeg = 90
      for (let i = 0; i < ROBINSON_TABLE.length - 1; i++) {
        const loPdfe = ROBINSON_TABLE[i][1]
        const hiPdfe = ROBINSON_TABLE[i + 1][1]
        if (absPdfe >= loPdfe && absPdfe <= hiPdfe) {
          const frac = (absPdfe - loPdfe) / (hiPdfe - loPdfe || 1)
          absLatDeg = i * 5 + frac * 5
          break
        }
      }
      const lat = absLatDeg * Math.sign(yRaw)

      const [plen] = robinsonInterp(absLatDeg)
      const lon = Math.abs(plen) < 1e-10
        ? 0
        : (xRaw / (ROBINSON_X_SCALE * plen)) * RAD2DEG
      return { lon: clamp(lon, -180, 180), lat: clamp(lat, -90, 90) }
    }
  }
}

// ---------------------------------------------------------------------------
// Pixel / world coordinate helpers
// ---------------------------------------------------------------------------

/** Convert (lon, lat) → pixel (x, y) using the given projection. */
export function lonLatToPixel(
  lon: number, lat: number,
  width: number, height: number,
  projection: ProjectionType = 'equirectangular',
): { x: number; y: number } {
  const { nx, ny } = projectForward(projection, lon, lat)
  return { x: nx * width, y: ny * height }
}

/** Convert pixel (x, y) → (lon, lat) using the given projection. */
export function pixelToLonLat(
  x: number, y: number,
  width: number, height: number,
  projection: ProjectionType = 'equirectangular',
): { lon: number; lat: number } {
  return projectInverse(projection, x / width, y / height)
}

/** Convert elevation in metres to a normalised [0, 1] value. */
export function metersToNormalised(meters: number, minM: number, maxM: number): number {
  if (maxM <= minM) return 0.5
  return Math.max(0, Math.min(1, (meters - minM) / (maxM - minM)))
}

/** Convert normalised [0, 1] elevation to metres. */
export function normalisedToMeters(normalised: number, minM: number, maxM: number): number {
  return minM + normalised * (maxM - minM)
}
