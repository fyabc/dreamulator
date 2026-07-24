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
  generateAdaptiveTerrainScale,
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
  layers: Record<ColorMode, number>
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
  /** Per-layer opacity: { terrain: 0-1, landsea: 0-1, plates: 0-1, boundaries: 0-1 } */
  layers?: Record<ColorMode, number>
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
  layers = { terrain: 1, landsea: 0, plates: 0, boundaries: 0 },
  hillshadeStrength = 0,
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
      lastCache.layers.terrain === layers.terrain &&
      lastCache.layers.landsea === layers.landsea &&
      lastCache.layers.plates === layers.plates &&
      lastCache.layers.boundaries === layers.boundaries &&
      lastCache.cellIdMap === cellIdMap &&
      lastCache.cvtMesh === cvtMesh
    ) {
      return lastCache.material
    }

    const totalPixels = width * height
    const buf = new Uint8Array(totalPixels * 4)

    // Compute normalised sea level from absolute metres
    const range = elevMaxM - elevMinM || 1
    const normSeaLevel = (seaLevel - elevMinM) / range

    // --- Step 1: Precompute LUTs for all active layers ---
    const activeModes = (Object.keys(layers) as ColorMode[]).filter((k) => layers[k] > 0)
    const terrainLut = activeModes.includes('terrain')
      ? generateAdaptiveTerrainScale(elevMinM, elevMaxM, seaLevel) : null
    const landseaLut = activeModes.includes('landsea')
      ? (() => {
          const l = new Uint8Array(1024 * 3)
          const cutoff = Math.round(normSeaLevel * 1023)
          for (let i = 0; i < 1024; i++) {
            const c = i <= cutoff ? [30, 60, 120] : [80, 140, 60]
            l[i*3]=c[0]; l[i*3+1]=c[1]; l[i*3+2]=c[2]
          }
          return l
        })() : null

    // --- Step 2: Build cell colour palettes ---
    const platesColor = new Map<number, [number, number, number]>()
    const boundariesColor = new Map<number, [number, number, number]>()
    if (cvtMesh && (activeModes.includes('plates') || activeModes.includes('boundaries'))) {
      if (activeModes.includes('plates')) {
        const plateIds = [...new Set(cvtMesh.cells.map((c) => c.plate_id).filter(Boolean))]
        const palette = new Map<string, [number, number, number]>()
        plateIds.forEach((pid, idx) => {
          palette.set(pid!, hexRgb(PLATE_COLORS[idx % PLATE_COLORS.length]))
        })
        for (const cell of cvtMesh.cells) {
          if (cell.plate_id) {
            const c = palette.get(cell.plate_id)
            if (c) platesColor.set(cell.id, c)
          }
        }
      }
      if (activeModes.includes('boundaries')) {
        for (const cell of cvtMesh.cells) {
          const bType = cell.boundary_type as BoundaryType | null
          if (bType) boundariesColor.set(cell.id, BOUNDARY_COLORS[bType])
        }
      }
    }

    // --- Step 3: Composite all active layers per pixel ---
    // Alpha-blend helper
    const blend = (dst: number[], src: [number, number, number], alpha: number) => {
      dst[0] = Math.round(dst[0] * (1 - alpha) + src[0] * alpha)
      dst[1] = Math.round(dst[1] * (1 - alpha) + src[1] * alpha)
      dst[2] = Math.round(dst[2] * (1 - alpha) + src[2] * alpha)
    }

    for (let i = 0; i < totalPixels; i++) {
      const elev = elevation[i]
      const cellId = cellIdMap?.[i]
      const accum = [0, 0, 0] // RGB accumulator

      // Layer 1: Terrain
      if (terrainLut) {
        const idx = Math.min(1023, Math.max(0, Math.round(elev * 1023)))
        const c: [number, number, number] = [terrainLut[idx*4], terrainLut[idx*4+1], terrainLut[idx*4+2]]
        // Water depth darkening
        if (elev < normSeaLevel) {
          const depth = (normSeaLevel - elev) / Math.max(normSeaLevel, 0.001)
          const f = 1 - waterDepthFactor * depth
          c[0] = Math.round(c[0] * f); c[1] = Math.round(c[1] * f); c[2] = Math.round(c[2] * f)
        }
        blend(accum, c, layers.terrain)
      }

      // Layer 2: Land/sea
      if (landseaLut) {
        const idx = Math.min(1023, Math.max(0, Math.round(elev * 1023)))
        const c: [number, number, number] = [landseaLut[idx*3], landseaLut[idx*3+1], landseaLut[idx*3+2]]
        blend(accum, c, layers.landsea)
      }

      // Layer 3: Plates
      if (layers.plates > 0 && cellId != null) {
        const pc = platesColor.get(cellId)
        if (pc) blend(accum, pc, layers.plates)
      }

      // Layer 4: Boundaries
      if (layers.boundaries > 0 && cellId != null) {
        const bc = boundariesColor.get(cellId)
        if (bc) blend(accum, bc, layers.boundaries)
      }

      const pi = i * 4
      buf[pi] = accum[0]; buf[pi + 1] = accum[1]; buf[pi + 2] = accum[2]; buf[pi + 3] = 255
    }

    // --- Coastline detection (land/sea boundary edge) ---
    if (layers.terrain > 0) {
      const COAST_COLOR = [20, 20, 20] as const // near-black coastline
      for (let y = 0; y < height; y++) {
        for (let x = 0; x < width; x++) {
          const i = y * width + x
          const isLand = elevation[i] >= normSeaLevel
          // Check right neighbor
          const rx = x + 1
          if (rx < width && isLand !== (elevation[y * width + rx] >= normSeaLevel)) {
            const pi = i * 4
            buf[pi] = COAST_COLOR[0]; buf[pi + 1] = COAST_COLOR[1]; buf[pi + 2] = COAST_COLOR[2]
            // Also mark the neighbor for symmetry
            const npi = (y * width + rx) * 4
            buf[npi] = COAST_COLOR[0]; buf[npi + 1] = COAST_COLOR[1]; buf[npi + 2] = COAST_COLOR[2]
          }
          // Check bottom neighbor
          const by = y + 1
          if (by < height && isLand !== (elevation[by * width + x] >= normSeaLevel)) {
            const pi = i * 4
            buf[pi] = COAST_COLOR[0]; buf[pi + 1] = COAST_COLOR[1]; buf[pi + 2] = COAST_COLOR[2]
            const npi = (by * width + x) * 4
            buf[npi] = COAST_COLOR[0]; buf[npi + 1] = COAST_COLOR[1]; buf[npi + 2] = COAST_COLOR[2]
          }
        }
      }
    }

    // --- Reverse rows + columns to match SphereGeometry UV convention ---
    // SphereGeometry default: u=0→lon=180°, u=0.5→lon=0°.
    // Our buffer:        col 0→lon=-180°(=180°), col w/2→lon=0°.
    // The UV mapping is mirrored: sphere_lon(u)=90° at u=0.25 but texture_lon(u)=-90°.
    // Fix: horizontally mirror (reverse columns) + vertically flip (reverse rows).
    let outBuf = new Uint8Array(totalPixels * 4)
    for (let y = 0; y < height; y++) {
      const srcRow = (height - 1 - y) * width * 4
      const dstRow = y * width * 4
      for (let x = 0; x < width; x++) {
        const srcX = (width - 1 - x) * 4
        const dstX = x * 4
        outBuf[dstRow + dstX] = buf[srcRow + srcX]
        outBuf[dstRow + dstX + 1] = buf[srcRow + srcX + 1]
        outBuf[dstRow + dstX + 2] = buf[srcRow + srcX + 2]
        outBuf[dstRow + dstX + 3] = buf[srcRow + srcX + 3]
      }
    }

    // --- Step 3.5: Draw graticule on flipped buffer ---
    // Row → lat:  lat = y / height * 180 - 90   (row 0 = lat -90°)
    const GRID_STEP = 30
    const GRID_ALPHA = 0.08
    for (let lat = -90 + GRID_STEP; lat < 90; lat += GRID_STEP) {
      const y = Math.round(((90 + lat) / 180) * height)
      if (y < 0 || y >= height) continue
      for (let x = 0; x < width; x++) {
        const pi = (y * width + x) * 4
        outBuf[pi] = Math.round(outBuf[pi] * (1 - GRID_ALPHA) + 255 * GRID_ALPHA)
        outBuf[pi + 1] = Math.round(outBuf[pi + 1] * (1 - GRID_ALPHA) + 255 * GRID_ALPHA)
        outBuf[pi + 2] = Math.round(outBuf[pi + 2] * (1 - GRID_ALPHA) + 255 * GRID_ALPHA)
      }
    }
    for (let lon = -180 + GRID_STEP; lon < 180; lon += GRID_STEP) {
      const x = Math.round(((lon + 180) / 360) * width)
      if (x < 0 || x >= width) continue
      for (let y = 0; y < height; y++) {
        const pi = (y * width + x) * 4
        outBuf[pi] = Math.round(outBuf[pi] * (1 - GRID_ALPHA) + 255 * GRID_ALPHA)
        outBuf[pi + 1] = Math.round(outBuf[pi + 1] * (1 - GRID_ALPHA) + 255 * GRID_ALPHA)
        outBuf[pi + 2] = Math.round(outBuf[pi + 2] * (1 - GRID_ALPHA) + 255 * GRID_ALPHA)
      }
    }

    // --- Step 4: Upload as DataTexture ---
    const hasCellLayers = layers.plates > 0 || layers.boundaries > 0
    const filterType = hasCellLayers ? THREE.NearestFilter : THREE.LinearFilter
    const colorTex = new THREE.DataTexture(
      outBuf as unknown as BufferSource, width, height, THREE.RGBAFormat,
    )
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
    lastCache = { elevation, width, height, layers, cellIdMap, cvtMesh, material }

    return material
  }, [
    elevation, width, height, seaLevel,
    elevMinM, elevMaxM, layers,
    hillshadeStrength, waterDepthFactor, cvtMesh, cellIdMap,
  ])
}
