import { PerspectiveCamera, Vector3 } from 'three'
import { describe, expect, it } from 'vitest'
import { computeOrbitPath, earthRadiiToAU } from './scale'
import {
  orbitFrameDirection, orbitFrameNormal, orbitFrameRadius, stellarCloseUpDistance, stellarFrameDistance, stellarNearPlane,
  STELLAR_DEFAULT_NEAR_AU,
} from './stellarCamera'

const glint = {
  semi_major_axis_au: 0.00111165,
  eccentricity: 0.008,
  inclination_deg: 47.2,
  longitude_ascending_node_deg: 137.4,
  argument_of_periapsis_deg: 200,
  mean_anomaly_epoch_deg: 310,
}
const glintRadiusAU = earthRadiiToAU(4.1e-4)

describe('stellar camera framing', () => {
  it('keeps Glint’s near side in front of the clipping plane, even at minimum zoom distance', () => {
    const distance = glintRadiusAU * 1.5
    expect(stellarNearPlane(distance)).toBeGreaterThan(0)
    expect(stellarNearPlane(distance)).toBeLessThan(distance - glintRadiusAU)
    expect(stellarNearPlane(1)).toBe(STELLAR_DEFAULT_NEAR_AU)
  })

  it('backs away from the four-radius close-up on a narrow viewport', () => {
    expect(stellarCloseUpDistance(glintRadiusAU, 50, 1.8)).toBe(glintRadiusAU * 4)
    expect(stellarCloseUpDistance(glintRadiusAU, 50, 0.55)).toBeGreaterThan(glintRadiusAU * 4)
  })

  it.each([1.8, 0.55])('frames the real orbit and primary at aspect %s', (aspect) => {
    const camera = new PerspectiveCamera(50, aspect, STELLAR_DEFAULT_NEAR_AU, 5000)
    const parentRadiusAU = earthRadiiToAU(11)
    const radius = orbitFrameRadius(glint, glintRadiusAU, parentRadiusAU)
    const normal = orbitFrameNormal(glint)
    const from = new Vector3(-normal.z, 0, normal.x).normalize()
    const direction = orbitFrameDirection(from, normal)
    expect(Math.abs(direction.dot(normal))).toBeGreaterThan(0.9)
    camera.position.copy(direction).multiplyScalar(stellarFrameDistance(radius, camera.fov, aspect))
    camera.lookAt(0, 0, 0)
    camera.updateMatrixWorld()

    const path = computeOrbitPath(glint).map((point) => new Vector3(...point))
    for (const point of path) expect(Math.abs(point.dot(normal))).toBeLessThan(1e-12)
    const primarySamples = [-parentRadiusAU, parentRadiusAU].flatMap((edge) => [
      new Vector3(edge, 0, 0), new Vector3(0, edge, 0), new Vector3(0, 0, edge),
    ])
    for (const point of [...path, ...primarySamples]) {
      const projected = point.project(camera)
      expect(Math.max(Math.abs(projected.x), Math.abs(projected.y), Math.abs(projected.z))).toBeLessThan(1)
    }
  })
})
