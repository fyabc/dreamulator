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
 * computed UV.  Mollweide inverse is closed-form; Robinson uses a small LUT.
 *
 * Convention (matches utils/projection.ts):
 *   nx = vUv.x        (0 = left = lon −180°, 1 = right = lon +180°)
 *   ny = 1 − vUv.y    (0 = top = north, 1 = bottom = south — canvas convention)
 *   equirect UV = ((lon+180)/360, (lat+90)/180); the source DataTexture has
 *   flipY=false so v=0 ↔ lat −90° (row 0), matching that mapping.
 */

import * as THREE from 'three'
import { ROBINSON_TABLE, robinsonInterp } from './utils/projection'

const vertexShader = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`

/**
 * Mollweide inverse warp (closed-form).
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

/**
 * Robinson inverse warp via a 1-D lookup texture.
 *   xRaw = (2·nx − 1)·X_MAX,  yRaw = (1 − 2·ny)·Y_MAX   (Y_MAX = 1)
 * The table maps |lat| → (plen, pdfe); its inverse (pdfe → |lat|, plen) is
 * pre-baked into u_robinsonLUT (r = |lat|/90, g = plen).  The map boundary is
 * the curved edge where |lon| = 180°, i.e. |xRaw| = X_SCALE·plen·π; a fragment
 * is outside iff the recovered |lon| > 180°.
 */
const robinsonFragmentShader = /* glsl */ `
precision highp float;
uniform sampler2D u_colorMap;
uniform sampler2D u_robinsonLUT;
varying vec2 vUv;

const float PI = 3.14159265359;
const float X_SCALE = 0.8473;
const float X_MAX = 0.8473 * 3.14159265359;  // X_SCALE · π

void main() {
  float nx = vUv.x;
  float ny = 1.0 - vUv.y;

  float xRaw = (2.0 * nx - 1.0) * X_MAX;
  float yRaw = 1.0 - 2.0 * ny;              // ROBINSON_Y_MAX = 1.0

  float absPdfe = clamp(abs(yRaw), 0.0, 1.0);
  vec2 lut = texture2D(u_robinsonLUT, vec2(absPdfe, 0.5)).rg;  // r=|lat|/90, g=plen
  float absLat = lut.r * 90.0;
  float plen = lut.g;                        // ∈ [0.5322, 1.0], never ~0

  float lon = xRaw / (X_SCALE * plen);       // radians
  if (abs(lon) > PI) discard;                // outside the curved robinson edge

  float lat = absLat * sign(yRaw) * PI / 180.0;

  vec2 eqUV = vec2((lon + PI) / (2.0 * PI), (lat + 0.5 * PI) / PI);
  gl_FragColor = texture2D(u_colorMap, eqUV);
}
`

export type ReprojectableProjection = 'mollweide' | 'robinson'

// ---------------------------------------------------------------------------
// Robinson lookup texture (built once, module-level cache)
// ---------------------------------------------------------------------------

const ROBINSON_LUT_SIZE = 512
let robinsonLUT: THREE.DataTexture | null = null

/**
 * Pre-bake the inverse Robinson table into a 1-D RGBA float texture:
 * for each pdfe index, store (|lat|/90, plen).  One shader texture fetch then
 * recovers both the latitude and the plen scale factor — no per-fragment table
 * search or iteration.
 */
function getRobinsonLUT(): THREE.DataTexture {
  if (robinsonLUT) return robinsonLUT
  const size = ROBINSON_LUT_SIZE
  const data = new Float32Array(size * 4)
  for (let i = 0; i < size; i++) {
    const absPdfe = i / (size - 1)
    // Invert the pdfe column of the Robinson table → |lat| in degrees.
    let absLat = 90
    for (let j = 0; j < ROBINSON_TABLE.length - 1; j++) {
      const lo = ROBINSON_TABLE[j][1]
      const hi = ROBINSON_TABLE[j + 1][1]
      if (absPdfe >= lo && absPdfe <= hi) {
        const frac = (absPdfe - lo) / (hi - lo || 1)
        absLat = j * 5 + frac * 5
        break
      }
    }
    const plen = robinsonInterp(absLat)[0]
    data[i * 4] = absLat / 90
    data[i * 4 + 1] = plen
    data[i * 4 + 2] = 0
    data[i * 4 + 3] = 1
  }
  const tex = new THREE.DataTexture(
    data as unknown as BufferSource, size, 1, THREE.RGBAFormat, THREE.FloatType,
  )
  // NearestFilter: WebGL2 float textures don't guarantee linear filtering;
  // 512 entries → ~0.18° latitude quantisation, imperceptible.
  tex.minFilter = THREE.NearestFilter
  tex.magFilter = THREE.NearestFilter
  tex.wrapS = THREE.ClampToEdgeWrapping
  tex.wrapT = THREE.ClampToEdgeWrapping
  tex.needsUpdate = true
  robinsonLUT = tex
  return tex
}

/**
 * Build a ShaderMaterial that renders `colorMap` (an equirectangular texture)
 * reprojected to the target projection via inverse warping.
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
  if (projection === 'robinson') {
    return new THREE.ShaderMaterial({
      vertexShader,
      fragmentShader: robinsonFragmentShader,
      uniforms: {
        u_colorMap: { value: colorMap },
        u_robinsonLUT: { value: getRobinsonLUT() },
      },
      side: THREE.DoubleSide,
    })
  }
  return null
}
