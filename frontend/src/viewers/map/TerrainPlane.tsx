/**
 * TerrainPlane — R3F component that renders a heightmap as a textured plane.
 *
 * Uses a custom ShaderMaterial with:
 * - Elevation texture (single-channel, from PNG)
 * - 1-D color ramp LUT for hypsometric tinting
 * - Hillshading (simulated directional light)
 * - Water depth darkening
 */

import { useMemo, useRef } from 'react'
import * as THREE from 'three'
import { generateLut, TERRAIN_SCALE, ELEVATION_SCALE, LANDSEA_SCALE, SLOPE_SCALE } from './utils/colorScales'

// Inline shaders (avoids Vite GLSL import issues)
const vertexShader = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
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
  // Wrap horizontally for seamless longitude
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
    color *= mix(1.0, 1.0 - 0.5, depth);
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

  // Create elevation DataTexture from Float32Array
  const elevationTexture = useMemo(() => {
    if (!elevation) return null
    const data = new Float32Array(elevation.buffer.slice(0))
    const tex = new THREE.DataTexture(
      data as any,
      width,
      height,
      THREE.RedFormat,
      THREE.FloatType,
    )
    tex.minFilter = THREE.LinearFilter
    tex.magFilter = THREE.LinearFilter
    tex.wrapS = THREE.RepeatWrapping // horizontal wrap for seamless longitude
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
    // Convert RGB to RGBA for Three.js DataTexture
    const rgba = new Uint8Array(256 * 4)
    for (let i = 0; i < 256; i++) {
      rgba[i * 4 + 0] = lut[i * 3 + 0]
      rgba[i * 4 + 1] = lut[i * 3 + 1]
      rgba[i * 4 + 2] = lut[i * 3 + 2]
      rgba[i * 4 + 3] = 255
    }
    const tex = new THREE.DataTexture(
      rgba as any,
      256,
      1,
      THREE.RGBAFormat,
      THREE.UnsignedByteType,
    )
    tex.minFilter = THREE.LinearFilter
    tex.magFilter = THREE.LinearFilter
    tex.needsUpdate = true
    return tex
  }, [colorMode])

  // Shader uniforms
  const uniforms = useMemo(
    () => ({
      uElevation: { value: elevationTexture },
      uColorRamp: { value: colorRampTexture },
      uSeaLevel: { value: seaLevel },
      uHillshadeStrength: { value: hillshadeStrength },
      uWaterDepthFactor: { value: waterDepthFactor },
      uResolution: { value: new THREE.Vector2(width, height) },
    }),
    [elevationTexture, colorRampTexture, seaLevel, hillshadeStrength, waterDepthFactor, width, height],
  )

  if (!elevation || !elevationTexture) {
    return null
  }

  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]}>
      <planeGeometry args={[planeWidth, planeHeight, 1, 1]} />
      <shaderMaterial
        ref={materialRef}
        vertexShader={vertexShader}
        fragmentShader={fragmentShader}
        uniforms={uniforms}
      />
    </mesh>
  )
}
