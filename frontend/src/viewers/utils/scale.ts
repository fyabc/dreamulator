/**
 * Scale functions and orbital math for 3D stellar system visualization.
 *
 * Real astronomical distances and sizes span enormous ranges
 * (star radius ~0.005 AU, planet orbit ~0.3–30 AU). These functions
 * compress the range logarithmically so everything remains visible
 * in the same scene.
 */

// ---------------------------------------------------------------------------
// Distance scaling — maps AU distances to scene units
// ---------------------------------------------------------------------------

const DISTANCE_SCALE_FACTOR = 8

/**
 * Convert an AU distance to scene units using logarithmic scaling.
 *
 * Linear AU ratios make inner planets invisible (e.g. 0.28 AU vs 1.0 AU).
 * Log scaling preserves ordering while compressing the visual range.
 *
 * Examples (factor=8):
 *   0.1 AU → ~3.4 units
 *   0.28 AU → ~5.0 units  (gaia-m Aegis)
 *   1.0 AU → ~8.3 units   (Earth)
 *   5.0 AU → ~13.9 units  (Jupiter)
 */
export function distanceScale(au: number): number {
  return Math.log10(1 + au * 10) * DISTANCE_SCALE_FACTOR
}

// ---------------------------------------------------------------------------
// Body radius scaling
// ---------------------------------------------------------------------------

/**
 * Scale a stellar radius (in solar radii) to scene units.
 * Stars are rendered small relative to orbits — sqrt compresses the range.
 */
export function starRadiusScale(rSun: number): number {
  return Math.sqrt(Math.max(0.05, rSun)) * 0.8
}

/**
 * Scale a planet radius (in Earth radii) to scene units.
 * Log scaling handles the huge range from dwarf planets (~0.2 R⊕)
 * to gas giants (~11 R⊕).
 */
export function planetRadiusScale(rEarth: number): number {
  return Math.log2(1 + Math.max(0.1, rEarth)) * 0.12
}

// ---------------------------------------------------------------------------
// Orbital position computation
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
 * Solve Kepler's equation M = E - e·sin(E) via Newton-Raphson iteration.
 *
 * @param M - Mean anomaly in radians
 * @param e - Eccentricity (0 ≤ e < 1)
 * @returns Eccentric anomaly E in radians
 */
function solveKepler(M: number, e: number): number {
  // Initial guess
  let E = M
  for (let i = 0; i < 20; i++) {
    const dE = (E - e * Math.sin(E) - M) / (1 - e * Math.cos(E))
    E -= dE
    if (Math.abs(dE) < 1e-8) break
  }
  return E
}

/**
 * Compute the 3D position of an orbiting body from its orbital elements.
 *
 * Returns [x, y, z] in scene units (after distance scaling).
 * The orbit lies in the XZ plane (Y=0) with inclination tilting around X axis.
 *
 * @param elements - Keplerian orbital elements
 * @param timeAnomalyDeg - Additional mean anomaly offset in degrees (0 = epoch position)
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

  // Solve Kepler's equation for eccentric anomaly
  const E = solveKepler(M, e)

  // True anomaly
  const cosV =
    (Math.cos(E) - e) / (1 - e * Math.cos(E))
  const sinV =
    (Math.sqrt(1 - e * e) * Math.sin(E)) / (1 - e * Math.cos(E))
  const v = Math.atan2(sinV, cosV)

  // Distance from focus
  const r = a * (1 - e * Math.cos(E))

  // Position in orbital plane
  const xOrb = r * Math.cos(v + omega)
  const yOrb = r * Math.sin(v + omega)

  // Rotate by longitude of ascending node and inclination
  const x = xOrb * Math.cos(Omega) - yOrb * Math.sin(Omega) * Math.cos(i)
  const z = xOrb * Math.sin(Omega) + yOrb * Math.cos(Omega) * Math.cos(i)
  const y = yOrb * Math.sin(i)

  // Apply distance scaling
  const dist = Math.sqrt(x * x + y * y + z * z)
  const scaledDist = distanceScale(dist)
  const scale = dist > 0 ? scaledDist / dist : 1

  return [x * scale, y * scale, z * scale]
}

/**
 * Generate points along an orbital ellipse for rendering orbit lines.
 *
 * @param elements - Keplerian orbital elements
 * @param segments - Number of line segments (default 128)
 * @returns Array of [x, y, z] points in scene units
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
