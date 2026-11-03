/** Alt/az → screen projection for the sky hemisphere chart.
 *
 * Projection: azimuthal equidistant — the radius is linear in zenith
 * distance (altitude rings sit at fixed radii, azimuth is an equal-angle
 * everywhere), so the chart's two quantitative readings are both linear.
 *
 * Convention: the inside-the-dome "looking up" view — N top, E LEFT, S
 * bottom, W right (the planisphere convention; a looking-down map
 * convention would mirror the sky).  SVG y grows downward.
 */

export interface SkyPoint {
  x: number
  y: number
}

export interface SkyProjector {
  /** Project (altitude°, azimuth°) to chart coordinates; null below horizon. */
  project: (altDeg: number, azDeg: number) => SkyPoint | null
  /**
   * Same projection without the below-horizon rejection — a body centred
   * below the horizon still gets a (clipped-away) position so a horizon-
   * straddling disc can render its above-horizon part.
   */
  projectUnclipped: (altDeg: number, azDeg: number) => SkyPoint
  /** Chart-space radius for a zenith distance in degrees. */
  radiusOf: (zenithDistanceDeg: number) => number
  readonly cx: number
  readonly cy: number
  readonly radius: number
}

export function skyProjector(cx: number, cy: number, radius: number): SkyProjector {
  const radiusOf = (zenithDistanceDeg: number): number =>
    (radius * zenithDistanceDeg) / 90.0
  return {
    cx,
    cy,
    radius,
    radiusOf,
    project(altDeg: number, azDeg: number): SkyPoint | null {
      if (altDeg < 0.0) return null
      return this.projectUnclipped(altDeg, azDeg)
    },
    projectUnclipped(altDeg: number, azDeg: number): SkyPoint {
      const r = radiusOf(90.0 - altDeg)
      const az = (azDeg * Math.PI) / 180.0
      // E left: x decreases as azimuth grows from N toward E.
      return { x: cx - r * Math.sin(az), y: cy - r * Math.cos(az) }
    },
  }
}

/** Altitude-ring radii as fractions of the chart radius (30°/60°/horizon). */
export const ALTITUDE_RING_DEGREES: readonly number[] = [30, 60]
