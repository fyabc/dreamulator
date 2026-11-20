import { useFrame, useThree } from '@react-three/fiber'
import { useEffect, useMemo, useState } from 'react'
import * as THREE from 'three'
import type { ElevationFrame } from '../projects/elevationProject'
import { generateAdaptiveTerrainScale } from './map/utils/colorScales'
import { globeRegionBasis, globeRegionBlend } from './map/utils/globeRegionDetail'
import type { ElevationRaster } from './packs/elevationRaster'

export type GlobeRegionDetail = { raster: ElevationRaster; frame: ElevationFrame }

export default function GlobeRegionMaterial({ map, detail }: { map: THREE.Texture; detail: GlobeRegionDetail }) {
  const { raster, frame } = detail
  const maxTextureSize = useThree(({ gl }) => gl.capabilities.maxTextureSize)
  const [ready, setReady] = useState<{ detail: GlobeRegionDetail; texture: THREE.DataTexture } | null>(null)
  useEffect(() => {
    const { width, height, values } = raster
    if (Math.max(width, height) > maxTextureSize) return
    const { min, max, sea } = frame
    const lut = generateAdaptiveTerrainScale(min, max, sea)
    const bins = lut.length / 4 - 1
    const inverseRange = 1 / (max - min || 1)
    const pixels = new Uint8Array(values.length * 4)
    values.forEach((value, index) => {
      const offset = 4 * Math.round(bins * THREE.MathUtils.clamp((value - min) * inverseRange, 0, 1))
      pixels[index * 4] = lut[offset]
      pixels[index * 4 + 1] = lut[offset + 1]
      pixels[index * 4 + 2] = lut[offset + 2]
      pixels[index * 4 + 3] = 255
    })
    const texture = new THREE.DataTexture(pixels, width, height)
    texture.colorSpace = THREE.SRGBColorSpace
    texture.magFilter = THREE.LinearFilter
    texture.minFilter = THREE.LinearMipmapLinearFilter
    texture.generateMipmaps = true
    texture.needsUpdate = true
    setReady({ detail, texture })
    return () => texture.dispose()
  }, [detail, frame, maxTextureSize, raster])

  const basis = useMemo(() => globeRegionBasis(frame.window), [frame.window])
  const uniforms = useMemo(() => ({
    regionMap: { value: null as THREE.Texture | null },
    regionCentre: { value: new THREE.Vector3() }, regionEast: { value: new THREE.Vector3() }, regionNorth: { value: new THREE.Vector3() },
    regionScale: { value: 0 }, regionBlend: { value: 0 },
  }), [])
  useFrame(({ camera }) => {
    uniforms.regionCentre.value = basis.centre
    uniforms.regionEast.value = basis.east
    uniforms.regionNorth.value = basis.north
    uniforms.regionScale.value = frame.window.radiusKm / frame.window.extentKmX
    uniforms.regionMap.value = ready?.detail === detail ? ready.texture : null
    uniforms.regionBlend.value = uniforms.regionMap.value && camera instanceof THREE.PerspectiveCamera
      ? globeRegionBlend(frame.window, camera.position.length(), camera.fov, camera.aspect) : 0
  })

  return <meshStandardMaterial map={map} roughness={0.9} metalness={0.05} onBeforeCompile={(shader) => {
    Object.assign(shader.uniforms, uniforms)
    shader.vertexShader = `varying vec3 regionSurface;\n${shader.vertexShader}`.replace('#include <begin_vertex>',
      '#include <begin_vertex>\nregionSurface = position;')
    shader.fragmentShader = `
      varying vec3 regionSurface;
      uniform sampler2D regionMap;
      uniform vec3 regionCentre, regionEast, regionNorth;
      uniform float regionScale, regionBlend;
      ${shader.fragmentShader}`.replace('#include <map_fragment>', `
      #include <map_fragment>
      if (regionBlend > 0.0) {
        vec3 surface = normalize(regionSurface);
        float towardCentre = dot(regionCentre, surface);
        if (towardCentre > 0.0) {
          vec2 plane = vec2(dot(regionEast, surface), -dot(regionNorth, surface));
          float sine = length(plane);
          float projection = sine > 0.000001 ? atan(sine, towardCentre) / sine : 1.0;
          vec2 offset = plane * (projection * regionScale);
          float edge = max(abs(offset.x), abs(offset.y));
          float weight = regionBlend * (1.0 - smoothstep(0.45, 0.5, edge));
          diffuseColor.rgb = mix(diffuseColor.rgb, texture2D(regionMap, vec2(0.5) + offset).rgb, weight);
        }
      }
    `)
  }} />
}
