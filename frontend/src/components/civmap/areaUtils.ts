/**
 * Area calculation utilities for GeoJSON features.
 * Uses the spherical shoelace formula for lon/lat coordinates.
 */

const R_EARTH = 6371 // Earth radius in km
const DEG2RAD = Math.PI / 180

/** Spherical shoelace formula for a single ring (degrees → km²) */
function ringAreaKm2(ring: number[][]): number {
  let area = 0
  for (let i = 0; i < ring.length - 1; i++) {
    const lon1 = ring[i][0] * DEG2RAD
    const lat1 = ring[i][1] * DEG2RAD
    const lon2 = ring[i + 1][0] * DEG2RAD
    const lat2 = ring[i + 1][1] * DEG2RAD
    area += (lon2 - lon1) * (2 + Math.sin(lat1) + Math.sin(lat2))
  }
  return Math.abs(area * R_EARTH * R_EARTH / 2)
}

/** Calculate area of a GeoJSON polygon/multipolygon in km² */
export function geoJsonAreaKm2(geometry: any): number {
  if (!geometry) return 0
  const { type, coordinates } = geometry
  if (type === 'Polygon') return ringAreaKm2(coordinates[0])
  if (type === 'MultiPolygon') {
    let total = 0
    for (const polygon of coordinates) total += ringAreaKm2(polygon[0])
    return total
  }
  return 0
}

/** Format area in km² to readable string */
export function formatArea(km2: number): string {
  if (km2 >= 1_000_000) return `${(km2 / 1_000_000).toFixed(1)}M`
  if (km2 >= 1_000) return `${Math.round(km2 / 1_000)}K`
  return `${Math.round(km2)}`
}
