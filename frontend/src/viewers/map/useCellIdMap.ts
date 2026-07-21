/**
 * useCellIdMap — pre-computes a cell-ID texture for fast palette-based rendering.
 *
 * For each pixel in the equirectangular grid, stores the ID of the nearest CVT cell.
 * This is an O(W × H × log N) computation done ONCE (via KD-tree).
 *
 * Cell-based color modes (plates, boundaries) then use this map for O(1) per-pixel
 * palette lookup, making mode switches ~20× faster than re-querying the KD-tree.
 *
 * ## Design pattern
 *
 * This follows the **palette-indexed texture** pattern common in game engines:
 *
 * - **id Software** (Doom/Quake): pre-computed lightmaps indexed by surface ID
 * - **Unreal Engine**: virtual texturing with indirection tables
 * - **Mapbox GL**: tile-based feature-ID textures for picking/highlighting
 * - **QGIS**: raster cell-value maps + categorized renderers (palette lookup)
 *
 * The cell-ID map is analogous to a **G-buffer ID channel** in deferred rendering:
 * geometry is rendered once to an ID buffer, then shading passes read the buffer
 * and apply material/color via lookup tables — avoiding re-traversal of geometry.
 *
 * ## Cache invalidation
 *
 * The cell-ID map depends only on (cvtMesh, width, height).
 * It does NOT depend on colorMode, projection, or elevation data.
 * This means switching color modes reuses the cached map.
 */

import { useMemo } from 'react'
import { buildCellKDTree } from '../../components/map/utils/kdtree'
import type { CVTMesh } from './types'

/**
 * Pre-computed cell-ID map: for each equirectangular pixel, the ID of the
 * nearest CVT cell.  Stored as a Uint32Array of size width × height.
 * Value 0xFFFFFFFF means "no cell" (shouldn't happen with valid mesh).
 */
export type CellIdMap = Uint32Array

interface UseCellIdMapOptions {
  cvtMesh: CVTMesh | null | undefined
  width: number
  height: number
}

/**
 * Build and cache the cell-ID map.
 *
 * Recomputes only when cvtMesh, width, or height changes.
 * Returns null if no CVT mesh is available.
 */
export default function useCellIdMap({
  cvtMesh,
  width,
  height,
}: UseCellIdMapOptions): CellIdMap | null {
  return useMemo(() => {
    if (!cvtMesh || !cvtMesh.cells.length || width <= 0 || height <= 0) return null

    const kdTree = buildCellKDTree(cvtMesh.cells)
    const map = new Uint32Array(width * height)

    const DEG2RAD = Math.PI / 180

    for (let py = 0; py < height; py++) {
      const latDeg = 90 - (py / (height - 1)) * 180
      const latRad = latDeg * DEG2RAD
      const cosLat = Math.cos(latRad)
      const sinLat = Math.sin(latRad)

      for (let px = 0; px < width; px++) {
        const lonDeg = (px / (width - 1)) * 360 - 180
        const lonRad = lonDeg * DEG2RAD

        const qx = cosLat * Math.cos(lonRad)
        const qy = sinLat
        const qz = cosLat * Math.sin(lonRad)

        map[py * width + px] = kdTree.nearest(qx, qy, qz)
      }
    }

    return map
  }, [cvtMesh, width, height])
}
