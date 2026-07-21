/**
 * Coordinate conversion utilities for map projections.
 *
 * Converts between three coordinate systems:
 * - Geographic: (lon, lat) in degrees
 * - Normalised: (nx, ny) in [0, 1] range
 * - Pixel: (x, y) in raster pixels
 * - World: (x, y, z) in Three.js scene coordinates
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
        nx: (lon + 180) / 360,
        ny: (90 - lat) / 180,
      }
    case 'mollweide': {
      // Mollweide projection: x ∈ [-2√2, 2√2], y ∈ [-√2, √2]
      const latRad = (lat * Math.PI) / 180
      const lonRad = (lon * Math.PI) / 180
      // Solve auxiliary angle θ via Newton-Raphson
      let theta = latRad
      for (let i = 0; i < 10; i++) {
        const dTheta =
          (2 * theta + Math.sin(2 * theta) - Math.PI * Math.sin(latRad)) /
          (2 + 2 * Math.cos(2 * theta))
        theta -= dTheta
        if (Math.abs(dTheta) < 1e-7) break
      }
      const mx = (2 * Math.SQRT2 * lonRad * Math.cos(theta)) / Math.PI
      const my = Math.SQRT2 * Math.sin(theta)
      // Normalise: x ∈ [-2√2, 2√2] → [0,1], y ∈ [-√2, √2] → [0,1]
      return {
        nx: (mx / (2 * Math.SQRT2) + 1) / 2,
        ny: (1 - my / Math.SQRT2) / 2,
      }
    }
    case 'robinson': {
      // Robinson projection (tabular interpolation)
      const latRad = (lat * Math.PI) / 180
      const absLat = Math.abs(latRad)
      // Robinson table at 5° intervals
      const table = [
        [1.0000, 0.0000], [0.9986, 0.0620], [0.9954, 0.1240], [0.9900, 0.1860],
        [0.9822, 0.2480], [0.9730, 0.3100], [0.9600, 0.3720], [0.9420, 0.4340],
        [0.9162, 0.4958], [0.8800, 0.5571], [0.8310, 0.6176], [0.7700, 0.6769],
        [0.6950, 0.7346], [0.6032, 0.7903], [0.4920, 0.8435], [0.3550, 0.8936],
        [0.1800, 0.9394], [0.0000, 0.9761], [0.0000, 1.0000],
      ]
      const idx = Math.min(17, Math.floor(absLat / (5 * Math.PI / 180)))
      const frac = (absLat / (5 * Math.PI / 180)) - idx
      const plen = table[idx][0] * (1 - frac) + table[idx + 1][0] * frac
      const pdfe = table[idx][1] * (1 - frac) + table[idx + 1][1] * frac
      const sign = lat >= 0 ? 1 : -1
      const rx = 0.8487 * plen * (lon * Math.PI) / 180
      const ry = 1.3523 * pdfe * sign
      // Normalise to [0,1]: Robinson x range ≈ [-2.67, 2.67], y ≈ [-1.35, 1.35]
      return {
        nx: (rx / 5.34 + 0.5),
        ny: (1 - ry / 2.7046) / 2,
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
        lon: nx * 360 - 180,
        lat: 90 - ny * 180,
      }
    case 'mollweide': {
      const mx = (nx * 2 - 1) * 2 * Math.SQRT2
      const my = (1 - ny * 2) * Math.SQRT2
      const theta = Math.asin(Math.max(-1, Math.min(1, my / Math.SQRT2)))
      const lat = Math.asin(
        Math.max(-1, Math.min(1, (2 * theta + Math.sin(2 * theta)) / Math.PI)),
      )
      const cosTheta = Math.cos(theta)
      const lon =
        cosTheta !== 0
          ? (Math.PI * mx) / (2 * Math.SQRT2 * cosTheta)
          : 0
      return {
        lon: Math.max(-180, Math.min(180, (lon * 180) / Math.PI)),
        lat: (lat * 180) / Math.PI,
      }
    }
    case 'robinson': {
      // Approximate inverse via iterative refinement
      const targetX = (nx - 0.5) * 5.34
      const targetY = (0.5 - ny) * 2.7046
      // Invert y first (Robinson y is monotonic in latitude)
      const table = [
        [1.0000, 0.0000], [0.9986, 0.0620], [0.9954, 0.1240], [0.9900, 0.1860],
        [0.9822, 0.2480], [0.9730, 0.3100], [0.9600, 0.3720], [0.9420, 0.4340],
        [0.9162, 0.4958], [0.8800, 0.5571], [0.8310, 0.6176], [0.7700, 0.6769],
        [0.6950, 0.7346], [0.6032, 0.7903], [0.4920, 0.8435], [0.3550, 0.8936],
        [0.1800, 0.9394], [0.0000, 0.9761], [0.0000, 1.0000],
      ]
      const absNormY = Math.abs(targetY) / 1.3523
      let latIdx = 0
      for (let i = 0; i < 18; i++) {
        if (table[i + 1][1] >= absNormY) { latIdx = i; break }
      }
      const yFrac = (absNormY - table[latIdx][1]) / (table[latIdx + 1][1] - table[latIdx][1] || 1)
      const absLat = (latIdx + yFrac) * 5
      const lat = targetY >= 0 ? absLat : -absLat
      const plen = table[latIdx][0] * (1 - yFrac) + table[latIdx + 1][0] * yFrac
      const lon = plen > 0.001 ? (targetX / (0.8487 * plen)) * (180 / Math.PI) : 0
      return {
        lon: Math.max(-180, Math.min(180, lon)),
        lat: Math.max(-90, Math.min(90, lat)),
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Pixel / world coordinate helpers
// ---------------------------------------------------------------------------

/** Convert (lon, lat) → pixel (x, y) using the given projection. */
export function lonLatToPixel(
  lon: number,
  lat: number,
  width: number,
  height: number,
  projection: ProjectionType = 'equirectangular',
): { x: number; y: number } {
  const { nx, ny } = projectForward(projection, lon, lat)
  return { x: nx * width, y: ny * height }
}

/** Convert pixel (x, y) → (lon, lat) using the given projection. */
export function pixelToLonLat(
  x: number,
  y: number,
  width: number,
  height: number,
  projection: ProjectionType = 'equirectangular',
): { lon: number; lat: number } {
  return projectInverse(projection, x / width, y / height)
}

/** Convert (lon, lat) → Three.js world coordinates on the terrain plane.
 *
 * The terrain plane is centred at the origin, with:
 * - x-axis = longitude (east positive)
 * - y-axis = up (not used for 2D view)
 * - z-axis = latitude (north positive, inverted for screen coords)
 */
export function lonLatToWorld(
  lon: number,
  lat: number,
  planeWidth: number,
  planeHeight: number,
): { x: number; y: number; z: number } {
  const x = (lon / 180) * (planeWidth / 2)
  const z = -(lat / 90) * (planeHeight / 2)
  return { x, y: 0, z }
}

/** Convert Three.js world coordinates → (lon, lat). */
export function worldToLonLat(
  wx: number,
  wz: number,
  planeWidth: number,
  planeHeight: number,
): { lon: number; lat: number } {
  const lon = (wx / (planeWidth / 2)) * 180
  const lat = -(wz / (planeHeight / 2)) * 90
  return { lon, lat }
}

/** Convert pixel → Three.js world coordinates. */
export function pixelToWorld(
  px: number,
  py: number,
  rasterWidth: number,
  rasterHeight: number,
  planeWidth: number,
  planeHeight: number,
): { x: number; y: number; z: number } {
  const { lon, lat } = pixelToLonLat(px, py, rasterWidth, rasterHeight)
  return lonLatToWorld(lon, lat, planeWidth, planeHeight)
}

/** Convert elevation in metres to a normalised [0, 1] value. */
export function metersToNormalised(
  meters: number,
  minM: number,
  maxM: number,
): number {
  if (maxM <= minM) return 0.5
  return Math.max(0, Math.min(1, (meters - minM) / (maxM - minM)))
}

/** Convert normalised [0, 1] elevation to metres. */
export function normalisedToMeters(
  normalised: number,
  minM: number,
  maxM: number,
): number {
  return minM + normalised * (maxM - minM)
}
