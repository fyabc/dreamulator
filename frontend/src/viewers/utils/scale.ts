/**
 * Scale functions and orbital math for 3D stellar system visualization.
 *
 * All distances and sizes use real astronomical proportions in AU.
 * Visibility of small bodies at system scale is handled by the Label
 * component (leader lines + dots) and minimum apparent-size glow,
 * NOT by distorting proportions.
 *
 * Reference scales (real):
 *   Sun radius:    0.00465 AU   (696,340 km)
 *   Earth radius:  0.0000426 AU (6,371 km)
 *   Earth orbit:   1.0 AU
 *   Jupiter orbit: 5.2 AU
 *
 * At 1 AU viewing distance, the Sun subtends ~0.5° — barely a pixel.
 * This is correct; Space Engine and Universe Sandbox behave the same way.
 * Labels and leader lines make small bodies findable.
 */

// ---------------------------------------------------------------------------
// Unit conversions → AU (the single scene unit)
// ---------------------------------------------------------------------------

const KM_PER_AU = 149_597_870.7
const SOLAR_RADIUS_KM = 696_340
const EARTH_RADIUS_KM = 6_371

/** Convert solar radii (R☉) to AU. */
export function solarRadiiToAU(rSun: number): number {
  return (rSun * SOLAR_RADIUS_KM) / KM_PER_AU
}

/** Convert Earth radii (R⊕) to AU. */
export function earthRadiiToAU(rEarth: number): number {
  return (rEarth * EARTH_RADIUS_KM) / KM_PER_AU
}

// ---------------------------------------------------------------------------
// Minimum apparent size — ensures bodies are never truly invisible
// ---------------------------------------------------------------------------

/**
 * Minimum visual radius in AU so that bodies always have a clickable
 * region even when their real radius is sub-pixel at the current zoom.
 *
 * 0.008 AU ≈ 1.7× the Sun's real radius — large enough to click on,
 * small enough to not obscure inner planet orbits.
 */
export const MIN_VISUAL_RADIUS_AU = 0.008

/**
 * Get an effective visual radius that is at least MIN_VISUAL_RADIUS_AU.
 * The real geometry is at `realRadiusAU`; the returned value is what
 * glow shells and click targets should use.
 */
export function effectiveVisualRadius(realRadiusAU: number): number {
  return Math.max(realRadiusAU, MIN_VISUAL_RADIUS_AU)
}

// ---------------------------------------------------------------------------
// Orbital position computation (real AU, no scaling)
// ---------------------------------------------------------------------------

interface OrbitalElements {
  semi_major_axis_au: number
  eccentricity: number
  inclination_deg: number
  longitude_ascending_node_deg?: number
  argument_of_periapsis_deg?: number
  mean_anomaly_epoch_deg?: number
}

/**
 * Solve Kepler's equation M = E - e·sin(E) via Newton-Raphson.
 *
 * @param M - Mean anomaly in radians
 * @param e - Eccentricity (0 ≤ e < 1)
 * @returns Eccentric anomaly E in radians
 */
function solveKepler(M: number, e: number): number {
  let E = M
  for (let i = 0; i < 20; i++) {
    const dE = (E - e * Math.sin(E) - M) / (1 - e * Math.cos(E))
    E -= dE
    if (Math.abs(dE) < 1e-10) break
  }
  return E
}

/**
 * Compute the 3D position of an orbiting body in AU.
 *
 * Coordinate system: XZ is the reference plane, Y is "up".
 *
 * @param elements - Keplerian orbital elements
 * @param timeAnomalyDeg - Additional mean anomaly offset in degrees (0 = epoch)
 * @returns [x, y, z] in AU
 */
export function computeOrbitalPosition(
  elements: OrbitalElements,
  timeAnomalyDeg: number = 0,
): [number, number, number] {
  const a = elements.semi_major_axis_au
  const e = elements.eccentricity
  const i = (elements.inclination_deg * Math.PI) / 180
  const omega = ((elements.argument_of_periapsis_deg ?? 0) * Math.PI) / 180
  const Omega = ((elements.longitude_ascending_node_deg ?? 0) * Math.PI) / 180
  const M0 = ((elements.mean_anomaly_epoch_deg ?? 0) * Math.PI) / 180
  const M = M0 + (timeAnomalyDeg * Math.PI) / 180

  const E = solveKepler(M, e)

  const cosV = (Math.cos(E) - e) / (1 - e * Math.cos(E))
  const sinV = (Math.sqrt(1 - e * e) * Math.sin(E)) / (1 - e * Math.cos(E))
  const v = Math.atan2(sinV, cosV)

  const r = a * (1 - e * Math.cos(E))

  // Position in orbital plane
  const xOrb = r * Math.cos(v + omega)
  const yOrb = r * Math.sin(v + omega)

  // Rotate by ascending node longitude and inclination
  const x = xOrb * Math.cos(Omega) - yOrb * Math.sin(Omega) * Math.cos(i)
  const z = xOrb * Math.sin(Omega) + yOrb * Math.cos(Omega) * Math.cos(i)
  const y = yOrb * Math.sin(i)

  return [x, y, z]
}

/**
 * Generate points along an orbital ellipse for rendering orbit lines.
 *
 * @param elements - Keplerian orbital elements
 * @param segments - Number of line segments (default 128)
 * @returns Array of [x, y, z] points in AU
 */
export function computeOrbitPath(
  elements: OrbitalElements,
  segments: number = 128,
): [number, number, number][] {
  const points: [number, number, number][] = []
  for (let j = 0; j <= segments; j++) {
    const anomaly = (j / segments) * 360
    points.push(computeOrbitalPosition(elements, anomaly))
  }
  return points
}
