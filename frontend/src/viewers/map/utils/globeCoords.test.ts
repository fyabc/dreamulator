import { Mesh, PerspectiveCamera, Raycaster, SphereGeometry, Vector2 } from 'three'
import { describe, expect, it } from 'vitest'
import { lonLatToGlobePosition } from './globeCoords'

describe('globe position for map coordinates', () => {
  it.each([
    [{ lon: 0, lat: 0 }, [2, 0, 0]],
    [{ lon: 90, lat: 0 }, [0, 0, -2]],
    [{ lon: -90, lat: 0 }, [0, 0, 2]],
    [{ lon: 180, lat: 0 }, [-2, 0, 0]],
    [{ lon: -180, lat: 0 }, [-2, 0, 0]],
    [{ lon: 140, lat: 90 }, [0, 2, 0]],
    [{ lon: -70, lat: -90 }, [0, -2, 0]],
  ])('uses the globe axes at %j', (point, expected) => {
    lonLatToGlobePosition(point, 2).forEach((value, index) => expect(value).toBeCloseTo(expected[index]))
  })

  it.each([
    { lon: 121.45, lat: 24.1 },
    { lon: 179.8, lat: 69 },
    { lon: -179.7, lat: -68 },
  ])('aims the canvas center at the matching map coordinates for %j', (point) => {
    const camera = new PerspectiveCamera(40, 1, 0.1, 100)
    camera.position.set(...lonLatToGlobePosition(point, 2.8))
    camera.lookAt(0, 0, 0)
    camera.updateMatrixWorld()

    const raycaster = new Raycaster()
    raycaster.setFromCamera(new Vector2(0, 0), camera)
    const globe = new Mesh(new SphereGeometry(1, 64, 32))
    const uv = raycaster.intersectObject(globe)[0]?.uv
    expect(uv).toBeDefined()
    expect(Math.abs(uv!.x * 360 - 180 - point.lon)).toBeLessThan(0.2)
    expect(Math.abs(uv!.y * 180 - 90 - point.lat)).toBeLessThan(0.2)
  })
})
