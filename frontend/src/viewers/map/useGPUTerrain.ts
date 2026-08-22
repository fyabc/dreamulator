/**
 * useGPUTerrain — GPU-composited layer rendering (Step 3 of the layer
 * refactor, see docs/design/map-system.md).
 *
 * Bake/display separation:
 *  - `layerBakes.getLayerTextures()` bakes one DataTexture PER LAYER, keyed
 *    only by DATA dependencies (elevation / mesh / cell-id map / sizing) —
 *    cached at module level so route navigation never re-bakes.
 *  - A tiny full-screen-quad pass composites the layers
 *    (base → thematic → fill → feature) into a WebGLRenderTarget, applying
 *    per-layer opacity on the GPU.
 *  - The returned display material shows the composited texture.  The public
 *    interface is unchanged from the old single-texture design:
 *    `material.uniforms.u_colorMap.value` IS the composited texture, so
 *    reprojection (Mollweide/Robinson) and the 3D globe consume it as-is.
 *
 * Opacity slider drag = uniform update + one cheap GPU composite pass — no
 * CPU re-bake (the old pipeline re-baked ~8.4M pixels per drag event).
 *
 * Usage: call `renderComposite(renderer)` once per frame BEFORE the main
 * `renderer.render(...)`.  The pass always renders (one fullscreen quad,
 * ~0.1–0.5 ms) — no shared dirty-flag gating, so pages with several canvases
 * (mobile + desktop globe layouts, two GL contexts) each refresh their own
 * framebuffer without racing over one flag.
 */

import { useMemo, useEffect, useCallback } from 'react'
import * as THREE from 'three'
import type { ColorMode } from './TerrainPlane'
import type { CVTMesh } from './types'
import type { CellIdMap } from './useCellIdMap'
import { getLayerTextures, type LayerTextures } from './layerBakes'

// ---------------------------------------------------------------------------
// Shaders
// ---------------------------------------------------------------------------

const vertexShader = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`

/** Composite pass: blend layer textures in kind z-order. */
const compositeFragmentShader = /* glsl */ `
precision highp float;
uniform sampler2D u_thematic;   // map mode (terrain / Köppen / Whittaker / NPP / cradle)
uniform sampler2D u_fill;       // plates
uniform sampler2D u_feature;    // boundaries (crust/plate)
uniform sampler2D u_coastlines; // coastline outline
uniform sampler2D u_flow;       // drainage / flow accumulation (stackable)
uniform float u_thematicOp;
uniform float u_fillOp;
uniform float u_featureOp;
uniform float u_coastlinesOp;
uniform float u_flowOp;
varying vec2 vUv;

vec3 blendLayer(vec3 dst, vec4 src, float op) {
  float a = src.a * op;
  return mix(dst, src.rgb, a);
}

void main() {
  // Neutral dark background — visible when no thematic is active.
  vec3 color = vec3(0.12, 0.16, 0.22);
  color = blendLayer(color, texture2D(u_thematic, vUv), u_thematicOp);
  color = blendLayer(color, texture2D(u_fill, vUv), u_fillOp);
  color = blendLayer(color, texture2D(u_feature, vUv), u_featureOp);
  color = blendLayer(color, texture2D(u_flow, vUv), u_flowOp);
  color = blendLayer(color, texture2D(u_coastlines, vUv), u_coastlinesOp);
  gl_FragColor = vec4(color, 1.0);
}
`

/**
 * Display pass: show the active colour source (+ optional day/night).
 * u_useComposite = 0 → sample the baked base texture DIRECTLY.  This is the
 * pre-refactor code path, used whenever no overlay layer is active (the common
 * "plain elevation map" view): zero per-frame composite cost, byte-identical
 * colours.  u_useComposite = 1 → sample the FBO-composited texture (overlays).
 */
const displayFragmentShader = /* glsl */ `
precision highp float;
uniform sampler2D u_colorMap;    // FBO-composited texture (overlays active)
uniform sampler2D u_directBase;  // baked base texture (no overlays)
uniform float u_useComposite;
uniform float u_sunLonRad;  // subsolar longitude (radians)
uniform float u_sunDecRad;  // solar declination (radians)
uniform float u_dayNight;   // 0 = off, 1 = on
varying vec2 vUv;
void main() {
  vec4 color = u_useComposite > 0.5
    ? texture2D(u_colorMap, vUv)
    : texture2D(u_directBase, vUv);
  if (u_dayNight > 0.5) {
    // vUv -> geographic (PlaneGeometry + compositing target flipY=false):
    //   lon = vUv.x*360 - 180, lat = vUv.y*180 - 90
    float lonRad = vUv.x * 6.28318530718 - 3.14159265359;
    float latRad = vUv.y * 3.14159265359 - 1.57079632679;
    float h = lonRad - u_sunLonRad;
    float cz = sin(latRad) * sin(u_sunDecRad)
             + cos(latRad) * cos(u_sunDecRad) * cos(h);
    // Twilight smoothstep + cool night tint — mirrors solar.ts constants.
    float t = smoothstep(-0.1, 0.1, cz);
    vec3 night = color.rgb * vec3(0.16, 0.20, 0.34);
    color.rgb = mix(night, color.rgb, t);
  }
  gl_FragColor = color;
}
`

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

interface UseGPUTerrainOptions {
  elevation: Float32Array | null
  width: number
  height: number
  seaLevel: number
  elevMinM?: number
  elevMaxM?: number
  /** Per-layer opacity: { terrain: 0-1, landsea: 0-1, plates: 0-1, boundaries: 0-1 } */
  layers?: Record<ColorMode, number>
  hillshadeStrength?: number
  waterDepthFactor?: number
  cvtMesh?: CVTMesh | null
  cellIdMap?: CellIdMap | null
  /** Flip texture horizontally. Set true for SphereGeometry (Three.js sphere
   *  UV u=0 maps to lon=+180°, mirroring the equirectangular convention).
   *  Set false for PlaneGeometry (2D map, u=0 = left = lon=-180°). */
  flipHorizontal?: boolean
  /** Subsolar longitude in radians — drives the day/night overlay. */
  sunLonRad?: number
  /** Solar declination in radians — drives the day/night overlay. */
  sunDecRad?: number
  /** 1 = enable day/night overlay, 0 = off. */
  dayNight?: number
}

/** Internal composite state (one per bake/size). */
interface CompositeState {
  target: THREE.WebGLRenderTarget
  compMat: THREE.ShaderMaterial
  displayMat: THREE.ShaderMaterial
  scene: THREE.Scene
  camera: THREE.OrthographicCamera
  quad: THREE.Mesh
}

export interface GPUTerrainResult {
  /** Display material for the equirectangular path. Null when no elevation
   *  data is available. */
  material: THREE.ShaderMaterial | null
  /** Texture to sample for reprojection / 3D globe: the FBO composite while
   *  overlays are active, otherwise the plain baked base texture. */
  texture: THREE.Texture | null
  /** Composite pass — call once per frame before the main render. No-op while
   *  no overlay layer is active; safe to call from multiple canvases. */
  renderComposite: (renderer: THREE.WebGLRenderer) => void
}

export default function useGPUTerrain({
  elevation,
  width,
  height,
  seaLevel,
  elevMinM = -11000,
  elevMaxM = 9000,
  layers = { terrain: 1, landsea: 0, plates: 0, boundaries: 0, coastlines: 1, koppen: 0, currents: 0, winds: 0, biomes: 0, npp: 0, domesticable: 0, soil: 0, provinces: 0, temperature: 0, precipitation: 0, habitable: 0, agriculture: 0, flow: 0 },
  waterDepthFactor = 0.5,
  cvtMesh,
  cellIdMap,
  flipHorizontal = false,
  sunLonRad = 0,
  sunDecRad = 0,
  dayNight = 0,
}: UseGPUTerrainOptions): GPUTerrainResult {
  // --- Bake per-layer textures (DATA-driven only; opacity-independent) ---
  const baked: LayerTextures | null = useMemo(() => {
    if (!elevation || width <= 0 || height <= 0) return null
    return getLayerTextures({
      elevation, width, height, seaLevel, elevMinM, elevMaxM,
      waterDepthFactor, flipHorizontal, cvtMesh, cellIdMap,
    })
  }, [elevation, width, height, seaLevel, elevMinM, elevMaxM,
      waterDepthFactor, flipHorizontal, cvtMesh, cellIdMap])

  // --- Composite target + materials (one per bake/size) ---
  const composite = useMemo<CompositeState | null>(() => {
    if (!baked) return null

    const target = new THREE.WebGLRenderTarget(width, height, {
      depthBuffer: false,
      stencilBuffer: false,
    })
    target.texture.wrapS = THREE.RepeatWrapping
    target.texture.wrapT = THREE.ClampToEdgeWrapping
    target.texture.flipY = false

    const compMat = new THREE.ShaderMaterial({
      vertexShader,
      fragmentShader: compositeFragmentShader,
      uniforms: {
        u_thematic: { value: baked.terrainThematic },
        u_fill: { value: baked.plates },
        u_feature: { value: baked.boundaries },
        u_coastlines: { value: baked.coastlines },
        u_flow: { value: baked.flow },
        u_thematicOp: { value: layers.terrain ?? 1 },
        u_fillOp: { value: layers.plates ?? 0 },
        u_featureOp: { value: layers.boundaries ?? 0 },
        u_coastlinesOp: { value: layers.coastlines ?? 1 },
        u_flowOp: { value: layers.flow ?? 0 },
        _terrainThematic: { value: baked.terrainThematic },
        _landseaThematic: { value: baked.landseaThematic },
        _koppen: { value: baked.koppen },
        _biomes: { value: baked.biomes },
        _npp: { value: baked.npp },
        _domesticable: { value: baked.domesticable },
      },
      depthTest: false,
      depthWrite: false,
    })

    const scene = new THREE.Scene()
    const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1)
    const quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), compMat)
    scene.add(quad)

    const displayMat = new THREE.ShaderMaterial({
      vertexShader,
      fragmentShader: displayFragmentShader,
      uniforms: {
        u_colorMap: { value: target.texture },
        u_directBase: { value: baked.terrainThematic },
        u_useComposite: { value: 0 },
        u_sunLonRad: { value: sunLonRad },
        u_sunDecRad: { value: sunDecRad },
        u_dayNight: { value: dayNight },
      },
      side: THREE.DoubleSide,
    })

    return { target, compMat, displayMat, scene, camera, quad }
    // Sun intentionally excluded from deps: updated via the effect below.
  }, [baked, width, height])

  // --- Layer-derived state (recomputed on every opacity/base change) ---
  // overlayActive: triggers the composite pass and u_useComposite for 2D display.
  const overlayActive =
    (layers.koppen ?? 0) > 0 || (layers.landsea ?? 0) > 0 ||
    (layers.plates ?? 0) > 0 || (layers.boundaries ?? 0) > 0 ||
    (layers.coastlines ?? 1) > 0 ||
    (layers.biomes ?? 0) > 0 || (layers.npp ?? 0) > 0 ||
    (layers.domesticable ?? 0) > 0 ||
    (layers.habitable ?? 0) > 0 || (layers.agriculture ?? 0) > 0 ||
    (layers.soil ?? 0) > 0 || (layers.provinces ?? 0) > 0 ||
    (layers.temperature ?? 0) > 0 || (layers.precipitation ?? 0) > 0 ||
    (layers.flow ?? 0) > 0

  // needsFboForGlobe: substantive overlays that require the FBO composite.
  // The coastline feature layer is pre-baked into a dedicated globe texture at
  // bake time, avoiding the FBO colour-space round-trip issue with
  // MeshStandardMaterial's PBR pipeline on the 3D globe.
  const needsFboForGlobe =
    (layers.koppen ?? 0) > 0 || (layers.landsea ?? 0) > 0 ||
    (layers.plates ?? 0) > 0 || (layers.boundaries ?? 0) > 0 ||
    (layers.biomes ?? 0) > 0 || (layers.npp ?? 0) > 0 ||
    (layers.domesticable ?? 0) > 0 ||
    (layers.habitable ?? 0) > 0 || (layers.agriculture ?? 0) > 0 ||
    (layers.soil ?? 0) > 0 || (layers.provinces ?? 0) > 0 ||
    (layers.temperature ?? 0) > 0 || (layers.precipitation ?? 0) > 0 ||
    (layers.flow ?? 0) > 0

  // Dispose composite resources when they are replaced / on unmount.
  useEffect(() => {
    return () => {
      if (!composite) return
      composite.target.dispose()
      composite.compMat.dispose()
      composite.displayMat.dispose()
      composite.quad.geometry.dispose()
    }
  }, [composite])

  // --- Layer opacities → uniforms (no re-bake) ---
  useEffect(() => {
    if (!composite || !baked) return
    const u = composite.compMat.uniforms

    // Determine active thematic texture: terrain (default), landsea, Köppen, biomes, NPP, domesticable
    const thematicLayers: [number | undefined, THREE.DataTexture][] = [
      [layers.terrain, baked.terrainThematic],
      [layers.landsea, baked.landseaThematic],
      [layers.koppen, baked.koppen],
      [layers.biomes, baked.biomes],
      [layers.npp, baked.npp],
      [layers.domesticable, baked.domesticable],
      [layers.habitable, baked.habitable],
      [layers.agriculture, baked.agriculture],
      [layers.soil, baked.soil],
      [layers.provinces, baked.provinces],
      [layers.temperature, baked.temperature],
      [layers.precipitation, baked.precipitation],
    ]
    let activeThematic = baked.terrainThematic
    let thematicOp = 1.0  // default: terrain on
    for (const [op, tex] of thematicLayers) {
      if ((op ?? 0) > 0) {
        activeThematic = tex
        thematicOp = op ?? 0
        break
      }
    }
    u.u_thematic.value = activeThematic
    u.u_thematicOp.value = thematicOp
    u.u_fillOp.value = layers.plates ?? 0
    u.u_featureOp.value = layers.boundaries ?? 0
    u.u_flowOp.value = layers.flow ?? 0
    u.u_coastlinesOp.value = layers.coastlines ?? 1
    const d = composite.displayMat.uniforms
    d.u_useComposite.value = overlayActive ? 1 : 0
    // Minification: NearestFilter when cell layers are visible (crisp cell edges
    // when zoomed out), LinearFilter for smooth terrain-only view.
    // Magnification: always LinearFilter — smooth interpolation when zoomed in,
    // eliminating the "pixel block" look at high zoom levels.
    composite.target.texture.minFilter = overlayActive ? THREE.NearestFilter : THREE.LinearFilter
    composite.target.texture.magFilter = THREE.LinearFilter
  }, [composite, baked, layers, overlayActive])

  // --- Sun uniforms on the display material (smooth slider, no re-composite) ---
  useEffect(() => {
    if (!composite) return
    composite.displayMat.uniforms.u_sunLonRad.value = sunLonRad
    composite.displayMat.uniforms.u_sunDecRad.value = sunDecRad
    composite.displayMat.uniforms.u_dayNight.value = dayNight
  }, [composite, sunLonRad, sunDecRad, dayNight])

  // --- Composite pass — consumers call it once per frame, before the main render. ---
  // Re-composites only while overlay layers are active (one fullscreen quad,
  // ~0.1–0.5 ms). With no overlays the display samples the baked base texture
  // directly and this is a no-op. No shared dirty flag: GlobeViewerPage keeps
  // mobile+desktop canvases mounted (two GL contexts), and a single flag cleared
  // by one would leave the other's framebuffer stale.
  const renderComposite = useCallback(
    (renderer: THREE.WebGLRenderer) => {
      if (!composite || !overlayActive) return
      // The composite pass is just layer blending, not a final render.
      // Disable all colour transforms (tone mapping + sRGB encoding) so the
      // FBO stores the same values as the source DataTextures.  Without this,
      // an SRGBColorSpace renderer (3D globe) double-encodes the sRGB data,
      // and the downstream sampler decodes it only once — shifting colours.
      const prevTM = renderer.toneMapping
      const prevExp = renderer.toneMappingExposure
      const prevOCS = renderer.outputColorSpace
      renderer.toneMapping = THREE.NoToneMapping
      renderer.toneMappingExposure = 1.0
      renderer.outputColorSpace = THREE.NoColorSpace
      renderer.setRenderTarget(composite.target)
      renderer.render(composite.scene, composite.camera)
      renderer.setRenderTarget(null)
      renderer.toneMapping = prevTM
      renderer.toneMappingExposure = prevExp
      renderer.outputColorSpace = prevOCS
      composite.target.texture.colorSpace = THREE.NoColorSpace
    },
    [composite, overlayActive],
  )

  /** The texture consumers (reprojection, 3D globe) should sample: the FBO
   *  composite while substantive overlays (Köppen, plates, biomes, etc.) are
   *  active, otherwise a pre-baked texture incorporating the coastline feature
   *  layer at its current binary on/off state.  Feature layers avoid the FBO
   *  for the globe because its MeshStandardMaterial PBR pipeline has a known
   *  colour-space round-trip issue. */

  // Feature-layer flag (binary on/off for the globe pre-bake path).
  const coastActive = (layers.coastlines ?? 1) > 0

  const texture: THREE.Texture | null = !baked
    ? null
    : needsFboForGlobe
      ? (composite?.target.texture ?? null)
      : coastActive
        ? baked.terrainWithCoastlines
        : baked.terrainThematic

  return { material: composite?.displayMat ?? null, texture, renderComposite }
}
