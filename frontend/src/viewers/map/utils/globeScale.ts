import { Quaternion, Vector3 } from 'three'

export const GLOBE_OVERVIEW_DISTANCE = 2.8
export const GLOBE_PREVIEW_MIN_DISTANCE = 1.03
export const GLOBE_MAX_DISTANCE = 8

export type GlobeScale = 'region' | 'globe'

function viewportTangent(fovDeg: number, aspect: number) {
  return Math.tan(fovDeg * Math.PI / 360) * Math.min(1, aspect)
}

export function overviewCameraDistance(fovDeg: number, aspect: number): number {
  const tangent = viewportTangent(fovDeg, aspect) * 0.9
  return Math.min(GLOBE_MAX_DISTANCE, Math.max(GLOBE_OVERVIEW_DISTANCE, Math.hypot(1, tangent) / tangent))
}

export function regionCameraDistance(spanKm: number, radiusKm: number, fovDeg: number, aspect: number): number {
  const diagonalAngle = spanKm / (Math.SQRT2 * radiusKm)
  const overviewDistance = overviewCameraDistance(fovDeg, aspect)
  if (diagonalAngle >= Math.acos(1 / overviewDistance)) return overviewDistance

  const viewportTan = viewportTangent(fovDeg, aspect) * 0.82
  const fitDistance = Math.cos(diagonalAngle) + Math.sin(diagonalAngle) / viewportTan
  return Math.min(overviewDistance, Math.max(GLOBE_PREVIEW_MIN_DISTANCE, fitDistance))
}

export function globeCameraPath(start: Vector3, end: Vector3): (position: Vector3, fraction: number) => void {
  const direction = start.clone().normalize()
  const rotation = new Quaternion().setFromUnitVectors(direction, end.clone().normalize())
  const logStart = Math.log(start.length() - 1)
  const logEnd = Math.log(end.length() - 1)
  const stepRotation = new Quaternion()

  return (position, fraction) => {
    const easing = fraction * fraction * (3 - 2 * fraction)
    stepRotation.identity().slerp(rotation, easing)
    const altitude = Math.exp(logStart + (logEnd - logStart) * easing)
    position.copy(direction).applyQuaternion(stepRotation).multiplyScalar(1 + altitude)
  }
}
