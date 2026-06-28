/**
 * TerrainPlane — R3F component that renders a heightmap as a textured plane.
 *
 * ⚠️ EXPERIMENTAL BRANCH — GPU shader approach.
 *
 * On AMD iGPU (Radeon 0x1638) + Windows ANGLE/D3D11, BOTH the `uv` and
 * `position` vertex attributes fail to interpolate correctly when the mesh
 * covers a large portion of the viewport.  They work correctly only when the
 * mesh is small (< ~50px).  This makes the GPU shader approach impractical
 * for a full-screen terrain plane.
 *
 * The working solution (on main branch) is Canvas 2D pre-rendering + CSS
 * positioning, which bypasses Three.js entirely.
 *
 * This file is kept as a reference for when the ANGLE driver issue is fixed.
 */

import { useEffect, useMemo, useRef } from 'react'
import * as THREE from 'three'
import { generateLut, TERRAIN_SCALE, ELEVATION_SCALE, LANDSEA_SCALE, SLOPE_SCALE } from './utils/colorScales'

// GLSL 1.0 shaders — Three.js auto-converts to GLSL 300 es under WebGL 2.
// UV is computed from position (not the `uv` attribute, which is broken on
// AMD ANGLE/D3D11).  Geometry is a unit plane (1×1).  Visual size is
// controlled by uScale uniform applied in the vertex shader.
const vertexShader = /* glsl */ `
uniform vec2 uScale;
varying vec2 vUv;

void main() {
  vUv = position.xy + 0.5;  // unit plane: position.xy ∈ [-0.5, 0.5]
  vec4 scaled = vec4(position * vec3(uScale, 1.0), 1.0);
  gl_Position = projectionMatrix * modelViewMatrix * scaled;
}
`

const fragmentShader = /* glsl */ `
uniform sampler2D uElevation;
uniform sampler2D uColorRamp;
uniform float uSeaLevel;
uniform float uHillshadeStrength;
uniform float uWaterDepthFactor;
uniform vec2 uResolution;

varying vec2 vUv;

float sampleElev(vec2 uv, vec2 offset, vec2 texelSize) {
  vec2 suv = uv + offset * texelSize;
  suv.x = fract(suv.x);
  suv.y = clamp(suv.y, 0.0, 1.0);
  return texture2D(uElevation, suv).r;
}

void main() {
  float elev = texture2D(uElevation, vUv).r;

  // Base color from ramp
  vec3 baseColor = texture2D(uColorRamp, vec2(elev, 0.5)).rgb;

  // Hillshading
  vec2 texelSize = 1.0 / uResolution;
  float dx = sampleElev(vUv, vec2(1.0, 0.0), texelSize)
           - sampleElev(vUv, vec2(-1.0, 0.0), texelSize);
  float dy = sampleElev(vUv, vec2(0.0, 1.0), texelSize)
           - sampleElev(vUv, vec2(0.0, -1.0), texelSize);

  vec3 lightDir = normalize(vec3(-1.0, 1.0, 1.0));
  vec3 normal = normalize(vec3(-dx * uHillshadeStrength * 8.0,
                                -dy * uHillshadeStrength * 8.0,
                                1.0));
  float shade = max(dot(normal, lightDir), 0.0);
  shade = 0.4 + 0.6 * shade;

  vec3 color = baseColor * shade;

  // Water depth darkening
  if (elev < uSeaLevel) {
    float depth = (uSeaLevel - elev) / max(uSeaLevel, 0.001);
    color *= mix(1.0, 1.0 - uWaterDepthFactor, depth);
    float spec = pow(max(dot(normal, lightDir), 0.0), 32.0);
    color += vec3(0.05, 0.08, 0.12) * spec;
  }

  gl_FragColor = vec4(color, 1.0);
}
`

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type ColorMode = 'terrain' | 'elevation' | 'landsea' | 'slope'

export interface TerrainPlaneProps {
  /** Elevation data as Float32Array [0, 1]. */
  elevation: Float32Array | null
  /** Raster width. */
  width: number
  /** Raster height. */
  height: number
  /** Normalised sea level [0, 1]. */
  seaLevel: number
  /** Color mode for the ramp. */
  colorMode?: ColorMode
  /** Hillshade strength [0, 1]. */
  hillshadeStrength?: number
  /** Water depth darkening factor [0, 1]. */
  waterDepthFactor?: number
  /** Three.js plane dimensions in world units. */
  planeWidth?: number
  planeHeight?: number
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function TerrainPlane({
  elevation,
  width,
  height,
  seaLevel,
  colorMode = 'terrain',
  hillshadeStrength = 0.7,
  waterDepthFactor = 0.5,
  planeWidth = 4,
  planeHeight = 2,
}: TerrainPlaneProps) {
  const materialRef = useRef<THREE.ShaderMaterial>(null)

  // Create elevation CanvasTexture from Float32Array.
  // Paints data onto an OffscreenCanvas for reliable GPU upload.
  const elevationTexture = useMemo(() => {
    if (!elevation) return null
    const canvas = new OffscreenCanvas(width, height)
    const ctx = canvas.getContext('2d')!
    const imageData = ctx.createImageData(width, height)
    const px = imageData.data
    for (let i = 0; i < elevation.length; i++) {
      const v = Math.max(0, Math.min(255, Math.round(elevation[i] * 255)))
      px[i * 4] = v
      px[i * 4 + 1] = v
      px[i * 4 + 2] = v
      px[i * 4 + 3] = 255
    }
    ctx.putImageData(imageData, 0, 0)
    const tex = new THREE.CanvasTexture(canvas as any)
    tex.minFilter = THREE.LinearFilter
    tex.magFilter = THREE.LinearFilter
    tex.wrapS = THREE.RepeatWrapping
    tex.wrapT = THREE.ClampToEdgeWrapping
    tex.needsUpdate = true
    return tex
  }, [elevation, width, height])

  // Create 1-D color ramp texture
  const colorRampTexture = useMemo(() => {
    const scaleMap: Record<ColorMode, typeof TERRAIN_SCALE> = {
      terrain: TERRAIN_SCALE,
      elevation: ELEVATION_SCALE,
      landsea: LANDSEA_SCALE,
      slope: SLOPE_SCALE,
    }
    const scale = scaleMap[colorMode] || TERRAIN_SCALE
    const lut = generateLut(scale, 256)
    const canvas = new OffscreenCanvas(256, 1)
    const ctx = canvas.getContext('2d')!
    const imageData = ctx.createImageData(256, 1)
    const px = imageData.data
    for (let i = 0; i < 256; i++) {
      px[i * 4 + 0] = lut[i * 3 + 0]
      px[i * 4 + 1] = lut[i * 3 + 1]
      px[i * 4 + 2] = lut[i * 3 + 2]
      px[i * 4 + 3] = 255
    }
    ctx.putImageData(imageData, 0, 0)
    const tex = new THREE.CanvasTexture(canvas as any)
    tex.minFilter = THREE.LinearFilter
    tex.magFilter = THREE.LinearFilter
    tex.needsUpdate = true
    return tex
  }, [colorMode])

  // Stable uniforms object — created with correct initial values so the
  // shader compiles correctly on the FIRST render (before useEffect runs).
  // Subsequent updates modify .value in place to keep object identity stable.
  const uniforms = useMemo(
    () => ({
      uElevation: { value: elevationTexture },
      uColorRamp: { value: colorRampTexture },
      uSeaLevel: { value: seaLevel },
      uHillshadeStrength: { value: hillshadeStrength },
      uWaterDepthFactor: { value: waterDepthFactor },
      uResolution: { value: new THREE.Vector2(width, height) },
      uScale: { value: new THREE.Vector2(planeWidth, planeHeight) },
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [], // created once — values kept in sync via useEffect below
  )

  // Update uniform values in place (never replace the object itself)
  useEffect(() => {
    uniforms.uElevation.value = elevationTexture
    uniforms.uColorRamp.value = colorRampTexture
    uniforms.uSeaLevel.value = seaLevel
    uniforms.uHillshadeStrength.value = hillshadeStrength
    uniforms.uWaterDepthFactor.value = waterDepthFactor
    uniforms.uResolution.value.set(width, height)
    uniforms.uScale.value.set(planeWidth, planeHeight)
  }, [uniforms, elevationTexture, colorRampTexture, seaLevel, hillshadeStrength, waterDepthFactor, width, height, planeWidth, planeHeight])

  if (!elevation || !elevationTexture) {
    return null
  }

  // FIXED unit plane — no scale, no dynamic geometry args.
  // Testing if position.xy varies correctly without any transform interference.
  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]}>
      <planeGeometry args={[1, 1, 1, 1]} />
      <shaderMaterial
        ref={materialRef}
        vertexShader={vertexShader}
        fragmentShader={fragmentShader}
        uniforms={uniforms}
      />
    </mesh>
  )
}
