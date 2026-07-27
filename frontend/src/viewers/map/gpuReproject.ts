/**
 * gpuReproject — GPU map-projection reprojection via inverse warping.
 *
 * Instead of warping the equirectangular image on the CPU (useTerrainTexture),
 * this renders the baked equirectangular colour texture through a fragment
 * shader that, for every output fragment, runs the INVERSE projection to recover
 * (lon, lat) and samples the equirectangular source there.  This is the classic
 * "inverse warp" and is embarrassingly parallel on the GPU.
 *
 * Why this is safe on the AMD ANGLE/D3D11 hardware: the equirectangular GPU path
 * (useGPUTerrain) already fills the viewport sampling a DataTexture via vUv and
 * works — this uses the exact same primitives (vUv → texture2D), only with a
 * computed UV.  The Mollweide inverse is closed-form (no iteration).
 *
 * Convention (matches utils/projection.ts):
 *   nx = vUv.x        (0 = left = lon −180°, 1 = right = lon +180°)
 *   ny = 1 − vUv.y    (0 = top = north, 1 = bottom = south — canvas convention)
 *   equirect UV = ((lon+180)/360, (lat+90)/180); the source DataTexture has
 *   flipY=false so v=0 ↔ lat −90° (row 0), matching that mapping.
 */

import * as THREE from 'three'

const vertexShader = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`

/**
 * Mollweide inverse warp.
 *   xRaw = (2·nx − 1)·2√2,  yRaw = (1 − 2·ny)·√2
 *   θ = asin(yRaw/√2),  sinφ = (2θ + sin 2θ)/π
 *   lat = asin(sinφ),  lon = π·xRaw / (2√2·cosθ)
 * Boundary is the ellipse xRaw²/8 + yRaw²/2 ≤ 1; outside → discard.
 */
const mollweideFragmentShader = /* glsl */ `
precision highp float;
uniform sampler2D u_colorMap;
varying vec2 vUv;

const float SQRT2 = 1.41421356237;
const float PI = 3.14159265359;

void main() {
  float nx = vUv.x;
  float ny = 1.0 - vUv.y;

  float xRaw = (2.0 * nx - 1.0) * 2.0 * SQRT2;
  float yRaw = (1.0 - 2.0 * ny) * SQRT2;

  // Outside the projection ellipse → transparent (scene background shows).
  if (xRaw * xRaw / 8.0 + yRaw * yRaw / 2.0 > 1.0) discard;

  float theta = asin(clamp(yRaw / SQRT2, -1.0, 1.0));
  float cosTheta = cos(theta);
  float sinPhi = (2.0 * theta + sin(2.0 * theta)) / PI;
  float lat = asin(clamp(sinPhi, -1.0, 1.0));
  float lon = abs(cosTheta) < 1e-6 ? 0.0 : (PI * xRaw) / (2.0 * SQRT2 * cosTheta);
  lon = clamp(lon, -PI, PI);

  vec2 eqUV = vec2((lon + PI) / (2.0 * PI), (lat + 0.5 * PI) / PI);
  gl_FragColor = texture2D(u_colorMap, eqUV);
}
`

export type ReprojectableProjection = 'mollweide' | 'robinson'

/**
 * Build a ShaderMaterial that renders `colorMap` (an equirectangular texture)
 * reprojected to the target projection.  Returns null for projections not yet
 * implemented (Robinson — needs a GLSL lookup table; step 2).
 */
export function createReprojectMaterial(
  projection: ReprojectableProjection,
  colorMap: THREE.Texture,
): THREE.ShaderMaterial | null {
  if (projection === 'mollweide') {
    return new THREE.ShaderMaterial({
      vertexShader,
      fragmentShader: mollweideFragmentShader,
      uniforms: { u_colorMap: { value: colorMap } },
      side: THREE.DoubleSide,
    })
  }
  return null
}
