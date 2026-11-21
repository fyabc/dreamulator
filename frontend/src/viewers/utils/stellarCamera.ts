import { MathUtils, Spherical, Vector3 } from 'three'
import type { OrbitalElements } from './scale'

export const STELLAR_DEFAULT_NEAR_AU = 0.00001
export const STELLAR_MAX_POLAR_ANGLE = Math.PI * 0.9

export type StellarFocusMode = 'close-up' | 'orbit'

export function stellarNearPlane(distanceAU: number): number {
  return MathUtils.clamp(distanceAU * 0.05, Number.EPSILON, STELLAR_DEFAULT_NEAR_AU)
}

export function stellarFrameDistance(radiusAU: number, verticalFovDeg: number, aspect: number): number {
  const verticalHalfAngle = MathUtils.degToRad(verticalFovDeg) / 2
  const horizontalHalfAngle = Math.atan(Math.tan(verticalHalfAngle) * aspect)
  const limitingHalfAngle = Math.min(verticalHalfAngle, horizontalHalfAngle)
  return radiusAU / Math.sin(limitingHalfAngle * 0.82)
}

export function stellarCloseUpDistance(radiusAU: number, verticalFovDeg: number, aspect: number): number {
  return Math.max(radiusAU * 4, stellarFrameDistance(radiusAU, verticalFovDeg, aspect))
}

export function orbitFrameRadius(orbit: OrbitalElements, bodyRadiusAU: number, parentRadiusAU: number): number {
  const apoapsisAU = orbit.semi_major_axis_au * (1 + orbit.eccentricity)
  return Math.max(apoapsisAU + bodyRadiusAU, parentRadiusAU)
}

export function orbitFrameNormal(orbit: OrbitalElements): Vector3 {
  const inclination = MathUtils.degToRad(orbit.inclination_deg)
  const ascendingNode = MathUtils.degToRad(orbit.longitude_ascending_node_deg ?? 0)
  return new Vector3(
    -Math.sin(ascendingNode) * Math.sin(inclination),
    -Math.cos(inclination),
    Math.cos(ascendingNode) * Math.sin(inclination),
  )
}

export function orbitFrameDirection(from: Vector3, orbitNormal: Vector3): Vector3 {
  const normal = orbitNormal.clone()
  if (normal.dot(from) < 0) normal.negate()
  const direction = from.clone().lerp(normal, 0.8).normalize()
  const spherical = new Spherical().setFromVector3(direction).makeSafe()
  spherical.phi = Math.min(spherical.phi, STELLAR_MAX_POLAR_ANGLE)
  return direction.setFromSpherical(spherical)
}
