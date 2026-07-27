/**
 * Solar geometry helpers for globe & map lighting.
 *
 * The sun direction is driven by two independent angles:
 *
 *   - sunLongitude (hour angle) — the diurnal (daily) rotation: where the sun
 *     is overhead in longitude. 0° = subsolar point on the prime meridian
 *     (local noon there).
 *
 *   - season (orbital position) — the annual variation of the subsolar
 *     latitude (solar declination) caused by the planet's axial tilt.
 *     0° = vernal equinox.
 *
 * Solar declination follows δ = axialTilt · sin(season):
 *   season   0° (春分) → δ = 0            (sun over the equator)
 *   season  90° (夏至) → δ = +axialTilt   (sun overhead in the north)
 *   season 180° (秋分) → δ = 0
 *   season 270° (冬至) → δ = −axialTilt   (sun overhead in the south)
 *
 * Illumination at any geographic point is the solar zenith angle:
 *   cos θz = sin φ·sin δ + cos φ·cos δ·cos(λ − λ☉)
 * This is a pure function of (lat, lon) — independent of map projection — so
 * the same season/time controls drive the 3D globe and every 2D projection.
 */

export const DEG2RAD = Math.PI / 180

// ---------------------------------------------------------------------------
// Day/night visual model
//
// These constants are mirrored in the GLSL day/night shader in useGPUTerrain.ts
// — keep the two in sync.
// ---------------------------------------------------------------------------

/** cos θz below this → full night. */
export const TWILIGHT_LO = -0.1
/** cos θz above this → full day. */
export const TWILIGHT_HI = 0.1
/** Multiplicative tint applied to terrain in full darkness (cool blue). */
export const NIGHT_TINT: [number, number, number] = [0.16, 0.2, 0.34]

/**
 * Solar declination (subsolar latitude) in degrees for a given season.
 *
 * @param seasonDeg - Orbital position: 0 = vernal equinox, 90 = N. summer solstice.
 * @param axialTiltDeg - Planet axial tilt in degrees (amplitude of the variation).
 */
export function solarDeclinationDeg(seasonDeg: number, axialTiltDeg: number): number {
  return axialTiltDeg * Math.sin(seasonDeg * DEG2RAD)
}

/**
 * Unit direction FROM which sunlight arrives — i.e. pointing toward the
 * subsolar point — in globe coordinates where +Y is the north pole and the
 * equator lies in the XZ plane.
 *
 * Matches the existing longitude convention: at declination 0 the light comes
 * from (−cos λ, 0, −sin λ).
 *
 * @param sunLongitudeDeg - Subsolar longitude (hour angle), degrees.
 * @param declinationDeg - Subsolar latitude (solar declination), degrees.
 */
export function sunDirection(
  sunLongitudeDeg: number,
  declinationDeg: number,
): [number, number, number] {
  const lon = sunLongitudeDeg * DEG2RAD
  const dec = declinationDeg * DEG2RAD
  const cosDec = Math.cos(dec)
  return [-cosDec * Math.cos(lon), Math.sin(dec), -cosDec * Math.sin(lon)]
}

/**
 * Cosine of the solar zenith angle for a geographic point. > 0 = daytime,
 * < 0 = night. φ/λ/δ/λ☉ all in degrees.
 */
export function solarZenithCos(
  latDeg: number,
  lonDeg: number,
  declinationDeg: number,
  sunLongitudeDeg: number,
): number {
  const lat = latDeg * DEG2RAD
  const dec = declinationDeg * DEG2RAD
  const h = (lonDeg - sunLongitudeDeg) * DEG2RAD
  return Math.sin(lat) * Math.sin(dec) + Math.cos(lat) * Math.cos(dec) * Math.cos(h)
}

/** GLSL-style smoothstep. */
function smoothstep(edge0: number, edge1: number, x: number): number {
  const t = Math.min(1, Math.max(0, (x - edge0) / (edge1 - edge0)))
  return t * t * (3 - 2 * t)
}

/** Day/night blend factor from cos θz: 0 = full night, 1 = full day. */
export function dayNightFactor(cosZenith: number): number {
  return smoothstep(TWILIGHT_LO, TWILIGHT_HI, cosZenith)
}

/**
 * Apply the day/night overlay IN PLACE to an equirectangular RGBA buffer whose
 * row 0 = +90°N (north) and column 0 = −180° — the Canvas/imageData convention
 * used by the CPU map renderer. Each pixel is darkened + cool-tinted according
 * to its solar zenith angle, with a smooth twilight terminator.
 *
 * @param data - RGBA bytes (length = width·height·4).
 * @param sunLonRad - Subsolar longitude, radians.
 * @param decRad - Solar declination, radians.
 */
export function applyDayNightEquirect(
  data: Uint8Array | Uint8ClampedArray,
  width: number,
  height: number,
  sunLonRad: number,
  decRad: number,
): void {
  const sinDec = Math.sin(decRad)
  const cosDec = Math.cos(decRad)
  const [nr, ng, nb] = NIGHT_TINT

  // Pre-compute cos(hour angle) per column — turns the inner loop into mul/add.
  const cosH = new Float32Array(width)
  for (let x = 0; x < width; x++) {
    const lonRad = (x / (width - 1)) * 2 * Math.PI - Math.PI
    cosH[x] = Math.cos(lonRad - sunLonRad)
  }

  const invH = 1 / (height - 1)
  for (let y = 0; y < height; y++) {
    const lat = (90 - y * invH * 180) * DEG2RAD
    const sinLat = Math.sin(lat)
    const cosLatCosDec = Math.cos(lat) * cosDec
    const rowBase = y * width * 4
    for (let x = 0; x < width; x++) {
      const cz = sinLat * sinDec + cosLatCosDec * cosH[x]
      const t = dayNightFactor(cz)
      if (t >= 1) continue // fully lit — nothing to do
      const pi = rowBase + x * 4
      const nightR = data[pi] * nr
      const nightG = data[pi + 1] * ng
      const nightB = data[pi + 2] * nb
      data[pi] = nightR + (data[pi] - nightR) * t
      data[pi + 1] = nightG + (data[pi + 1] - nightG) * t
      data[pi + 2] = nightB + (data[pi + 2] - nightB) * t
    }
  }
}
