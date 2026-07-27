/**
 * Solar geometry helpers for the 3D globe lighting.
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
 */

/**
 * Solar declination (subsolar latitude) in degrees for a given season.
 *
 * @param seasonDeg - Orbital position: 0 = vernal equinox, 90 = N. summer solstice.
 * @param axialTiltDeg - Planet axial tilt in degrees (amplitude of the variation).
 */
export function solarDeclinationDeg(seasonDeg: number, axialTiltDeg: number): number {
  return axialTiltDeg * Math.sin((seasonDeg * Math.PI) / 180)
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
  const lon = (sunLongitudeDeg * Math.PI) / 180
  const dec = (declinationDeg * Math.PI) / 180
  const cosDec = Math.cos(dec)
  return [-cosDec * Math.cos(lon), Math.sin(dec), -cosDec * Math.sin(lon)]
}
