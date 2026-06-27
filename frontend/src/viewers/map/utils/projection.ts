/**
 * Coordinate conversion utilities for equirectangular projection.
 *
 * Converts between three coordinate systems:
 * - Geographic: (lon, lat) in degrees
 * - Pixel: (x, y) in raster pixels
 * - World: (x, y, z) in Three.js scene coordinates
 */

/** Convert (lon, lat) → pixel (x, y). */
export function lonLatToPixel(
  lon: number,
  lat: number,
  width: number,
  height: number,
): { x: number; y: number } {
  const x = ((lon + 180) / 360) * width
  const y = ((90 - lat) / 180) * height
  return { x, y }
}

/** Convert pixel (x, y) → (lon, lat). */
export function pixelToLonLat(
  x: number,
  y: number,
  width: number,
  height: number,
): { lon: number; lat: number } {
  const lon = (x / width) * 360 - 180
  const lat = 90 - (y / height) * 180
  return { lon, lat }
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
