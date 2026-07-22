/**
 * useGPUTerrain — GPU-accelerated terrain rendering.
 *
 * All color modes (terrain, landsea, plates, boundaries) pre-compute the
 * FULL RGBA colour buffer on the CPU, then upload as a single DataTexture.
 * The fragment shader simply displays the texture — guaranteed no black screen.
 *
 * Performance:
 * - terrain/landsea: ~200ms (LUT + hillshading per pixel)
 * - plates/boundaries: ~100ms (cellIdMap palette lookup per pixel)
 * - Pan/zoom: <1ms (just re-display the texture)
 */

import { useMemo } from 'react'
import * as THREE from 'three'
import type { ColorMode } from './TerrainPlane'
import type { CVTMesh, BoundaryType } from './types'
import type { CellIdMap } from './useCellIdMap'
import {
  generateLut,
  generateAdaptiveTerrainScale,
  TERRAIN_SCALE,
  LANDSEA_SCALE,
  PLATE_COLORS,
} from './utils/colorScales'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function hexRgb(hex: string): [number, number, number] {
  const h = hex.replace('#', '')
  return [
    parseInt(h.substring(0, 2), 16),
    parseInt(h.substring(2, 4), 16),
    parseInt(h.substring(4, 6), 16),
  ]
}

const BOUNDARY_COLORS: Record<BoundaryType, [number, number, number]> = {
  convergent: hexRgb('#e53935'),
  divergent: hexRgb('#43a047'),
  transform: hexRgb('#fdd835'),
}

function sampleElev(elev: Float32Array, w: number, h: number, x: number, y: number): number {
  const wx = ((x % w) + w) % w
  const wy = Math.max(0, Math.min(h - 1, y))
  return elev[wy * w + wx]
}

// ---------------------------------------------------------------------------
// Minimal shaders — just display the pre-computed texture
// ---------------------------------------------------------------------------

const vertexShader = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`

const fragmentShader = /* glsl */ `
precision highp float;
uniform sampler2D u_colorMap;
varying vec2 vUv;
void main() {
  gl_FragColor = texture2D(u_colorMap, vUv);
}
`

// ---------------------------------------------------------------------------
// Module-level cache — survives component unmount/remount (React Router nav)
// ---------------------------------------------------------------------------

interface CacheEntry {
  // Cache key fields
  elevation: Float32Array
  width: number
  height: number
  colorMode: ColorMode
  cellIdMap: CellIdMap | null | undefined
  cvtMesh: CVTMesh | null | undefined
  // Cached result
  material: THREE.ShaderMaterial
}

let lastCache: CacheEntry | null = null

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
  colorMode?: ColorMode
  hillshadeStrength?: number
  waterDepthFactor?: number
  cvtMesh?: CVTMesh | null
  cellIdMap?: CellIdMap | null
}

export default function useGPUTerrain({
  elevation,
  width,
  height,
  seaLevel,
  elevMinM = -11000,
  elevMaxM = 9000,
  colorMode = 'terrain',
  hillshadeStrength = 0.7,
  waterDepthFactor = 0.5,
  cvtMesh,
  cellIdMap,
}: UseGPUTerrainOptions): THREE.ShaderMaterial | null {
  return useMemo(() => {
    if (!elevation || width <= 0 || height <= 0) return null

    // Check module-level cache: if inputs match, reuse material instantly
    if (
      lastCache &&
      lastCache.elevation === elevation &&
      lastCache.width === width &&
      lastCache.height === height &&
      lastCache.colorMode === colorMode &&
      lastCache.cellIdMap === cellIdMap &&
      lastCache.cvtMesh === cvtMesh
    ) {
      return lastCache.material
    }

    const totalPixels = width * height
    const buf = new Uint8Array(totalPixels * 4)

    // --- Step 1: Build LUT ---
    let lut: Uint8Array
    let isRgbaLut = false
    if (colorMode === 'terrain') {
      lut = generateAdaptiveTerrainScale(elevMinM, elevMaxM, seaLevel)
      isRgbaLut = true
    } else if (colorMode === 'landsea') {
      lut = generateLut(LANDSEA_SCALE, 256)
    } else {
      lut = generateLut(TERRAIN_SCALE, 256)
    }

    // --- Step 2: Build cell colour palette (for plates/boundaries) ---
    const isCellMode = colorMode === 'plates' || colorMode === 'boundaries'
    const cellColor = new Map<number, [number, number, number]>()

    if (isCellMode && cvtMesh) {
      if (colorMode === 'plates') {
        const plateIds = [...new Set(cvtMesh.cells.map((c) => c.plate_id).filter(Boolean))]
        const plateColorMap = new Map<string, [number, number, number]>()
        plateIds.forEach((pid, idx) => {
          plateColorMap.set(pid!, hexRgb(PLATE_COLORS[idx % PLATE_COLORS.length]))
        })
        for (const cell of cvtMesh.cells) {
          if (cell.plate_id) {
            const c = plateColorMap.get(cell.plate_id)
            if (c) cellColor.set(cell.id, c)
          }
        }
      } else if (colorMode === 'boundaries') {
        for (const cell of cvtMesh.cells) {
          const bType = cell.boundary_type as BoundaryType | null
          if (bType) cellColor.set(cell.id, BOUNDARY_COLORS[bType])
        }
      }
    }

    // --- Step 3: Render every pixel ---
    const lx = -1 / Math.sqrt(3)
    const ly = 1 / Math.sqrt(3)
    const lz = 1 / Math.sqrt(3)

    for (let y = 0; y < height; y++) {
      for (let x = 0; x < width; x++) {
        const i = y * width + x

        // Cell-based modes: use plate/boundary colour directly (flat, no gradients)
        if (isCellMode && cellIdMap && cellIdMap.length === totalPixels) {
          const cc = cellColor.get(cellIdMap[i])
          const pi = i * 4
          if (cc) {
            buf[pi] = cc[0]
            buf[pi + 1] = cc[1]
            buf[pi + 2] = cc[2]
          } else {
            // No colour for this cell — use terrain base
            const elev = elevation[i]
            const lutIdx = Math.min(255, Math.max(0, Math.round(elev * 255)))
            buf[pi] = lut[lutIdx * 3 + 0]
            buf[pi + 1] = lut[lutIdx * 3 + 1]
            buf[pi + 2] = lut[lutIdx * 3 + 2]
          }
          buf[pi + 3] = 255
          continue
        }

        // Elevation-based modes: LUT + hillshading + water depth
        const elev = elevation[i]
        const lutIdx = Math.min(255, Math.max(0, Math.round(elev * 255)))

        let r: number, g: number, b: number
        if (isRgbaLut) {
          r = lut[lutIdx * 4 + 0]
          g = lut[lutIdx * 4 + 1]
          b = lut[lutIdx * 4 + 2]
        } else {
          r = lut[lutIdx * 3 + 0]
          g = lut[lutIdx * 3 + 1]
          b = lut[lutIdx * 3 + 2]
        }

        // Hillshading
        if (hillshadeStrength > 0) {
          const dx = sampleElev(elevation, width, height, x + 1, y) -
                     sampleElev(elevation, width, height, x - 1, y)
          const dy = sampleElev(elevation, width, height, x, y + 1) -
                     sampleElev(elevation, width, height, x, y - 1)
          const nx = -dx * hillshadeStrength * 8
          const ny = -dy * hillshadeStrength * 8
          const nLen = Math.sqrt(nx * nx + ny * ny + 1)
          const shade = 0.4 + 0.6 * Math.max(0, (nx * lx + ny * ly + lz) / nLen)
          r = Math.min(255, Math.round(r * shade))
          g = Math.min(255, Math.round(g * shade))
          b = Math.min(255, Math.round(b * shade))
        }

        // Water depth darkening
        if (elev < seaLevel) {
          const depth = (seaLevel - elev) / Math.max(seaLevel, 0.001)
          const factor = 1 - waterDepthFactor * depth
          r = Math.round(r * factor)
          g = Math.round(g * factor)
          b = Math.round(b * factor)
        }

        const pi = i * 4
        buf[pi] = r
        buf[pi + 1] = g
        buf[pi + 2] = b
        buf[pi + 3] = 255
      }
    }

    // --- Step 4: Upload as DataTexture, display with trivial shader ---
    // Use NearestFilter for cell-based modes (sharp plate boundaries)
    // Use LinearFilter for elevation modes (smooth terrain gradients)
    const filterType = isCellMode ? THREE.NearestFilter : THREE.LinearFilter
    const colorTex = new THREE.DataTexture(
      buf as unknown as BufferSource, width, height, THREE.RGBAFormat,
    )
    // Three.js r162+ changed DataTexture default flipY to false.
    // Our buffer is row-major with row 0 = lat 90° (north) at the top.
    // flipY = true ensures row 0 maps to v=1 (screen top), matching
    // the SVG overlay's project() convention (ny=0 → lat=90°).
    colorTex.flipY = true
    colorTex.wrapS = THREE.RepeatWrapping
    colorTex.wrapT = THREE.ClampToEdgeWrapping
    colorTex.minFilter = filterType
    colorTex.magFilter = filterType
    colorTex.needsUpdate = true

    const material = new THREE.ShaderMaterial({
      vertexShader,
      fragmentShader,
      uniforms: { u_colorMap: { value: colorTex } },
      side: THREE.DoubleSide,
    })

    // Save to module-level cache (survives component unmount/remount)
    lastCache = { elevation, width, height, colorMode, cellIdMap, cvtMesh, material }

    return material
  }, [
    elevation, width, height, seaLevel,
    elevMinM, elevMaxM, colorMode, hillshadeStrength, waterDepthFactor,
    cvtMesh, cellIdMap,
  ])
}
