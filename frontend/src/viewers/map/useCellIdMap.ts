/**
 * useCellIdMap — pre-computes a cell-ID texture for fast palette-based rendering.
 *
 * For each pixel of the equirectangular grid, stores the ID of the nearest CVT
 * cell. This is an O(W × H × log N) computation done ONCE (via KD-tree) and is
 * offloaded to a worker: at 4096 × 2048 it used to block the main thread for
 * seconds during the first map load.
 *
 * Cell-based color modes (plates, boundaries, climate overlays) then use this
 * map for O(1) per-pixel palette lookup.  It is built only when a consumer
 * asks for it (climate/ecological overlays), so a plain terrain view no longer
 * pays for it before first paint.
 */

import { useEffect, useState } from 'react'
import { mark } from '../../utils/perf'
import { KDTree3D } from '../../components/map/utils/kdtree'
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
 * Module-level single-entry cache.  The build is an O(W × H × log N) pass
 * (~seconds at 4096×2048); mobile+desktop map viewers are mounted
 * simultaneously and would otherwise each rebuild the identical map.  The
 * result is deterministic for a given (mesh, width, height), so sharing one
 * array across consumers is safe.
 */
let cellIdCache: { mesh: CVTMesh; width: number; height: number; map: CellIdMap } | null = null
let cellIdPending: { mesh: CVTMesh; width: number; height: number; promise: Promise<CellIdMap> } | null =
  null

interface CellArrays {
  ids: Uint32Array
  x: Float64Array
  y: Float64Array
  z: Float64Array
}

function cellArrays(cvtMesh: CVTMesh): CellArrays {
  const cells = cvtMesh.cells
  const ids = new Uint32Array(cells.length)
  const x = new Float64Array(cells.length)
  const y = new Float64Array(cells.length)
  const z = new Float64Array(cells.length)
  for (let i = 0; i < cells.length; i++) {
    const cell = cells[i]
    ids[i] = cell.id
    if (cell.x !== undefined && cell.y !== undefined && cell.z !== undefined) {
      x[i] = cell.x
      y[i] = cell.y
      z[i] = cell.z
    } else {
      const lonRad = (cell.lon * Math.PI) / 180
      const latRad = (cell.lat * Math.PI) / 180
      const cosLat = Math.cos(latRad)
      x[i] = cosLat * Math.cos(lonRad)
      y[i] = Math.sin(latRad)
      z[i] = cosLat * Math.sin(lonRad)
    }
  }
  return { ids, x, y, z }
}

const DEG2RAD = Math.PI / 180

function fillCellIdMap({ ids, x, y, z }: CellArrays, width: number, height: number): CellIdMap {
  const points: Array<[number, number, number, number]> = new Array(ids.length)
  for (let i = 0; i < ids.length; i++) points[i] = [x[i], y[i], z[i], ids[i]]
  const tree = new KDTree3D(points, true)
  const map = new Uint32Array(width * height)
  const cosLon = new Float64Array(width)
  const sinLon = new Float64Array(width)
  for (let px = 0; px < width; px++) {
    const lonRad = ((px / (width - 1)) * 360 - 180) * DEG2RAD
    cosLon[px] = Math.cos(lonRad)
    sinLon[px] = Math.sin(lonRad)
  }
  for (let py = 0; py < height; py++) {
    const latRad = (90 - (py / (height - 1)) * 180) * DEG2RAD
    const cosLat = Math.cos(latRad)
    const sinLat = Math.sin(latRad)
    const rowOff = py * width
    for (let px = 0; px < width; px++) {
      map[rowOff + px] = tree.nearest(cosLat * cosLon[px], sinLat, cosLat * sinLon[px])
    }
  }
  return map
}

function loadCellIdMap(cvtMesh: CVTMesh, width: number, height: number): Promise<CellIdMap> {
  if (cellIdCache && cellIdCache.mesh === cvtMesh && cellIdCache.width === width &&
    cellIdCache.height === height) {
    return Promise.resolve(cellIdCache.map)
  }
  if (cellIdPending && cellIdPending.mesh === cvtMesh && cellIdPending.width === width &&
    cellIdPending.height === height) {
    return cellIdPending.promise
  }
  const arrays = cellArrays(cvtMesh)
  let promise: Promise<CellIdMap>
  if (typeof Worker === 'undefined') {
    promise = Promise.resolve().then(() => fillCellIdMap(arrays, width, height))
  } else {
    promise = new Promise<CellIdMap>((resolve, reject) => {
      let worker: Worker
      try {
        worker = new Worker(new URL('./cellIdMap.worker.ts', import.meta.url), { type: 'module' })
      } catch (error) {
        try {
          resolve(fillCellIdMap(arrays, width, height))
        } catch {
          reject(error)
        }
        return
      }
      worker.onmessage = ({ data }: MessageEvent<{ map: CellIdMap }>) => {
        worker.terminate()
        resolve(data.map)
      }
      worker.onerror = (event) => {
        worker.terminate()
        try {
          resolve(fillCellIdMap(cellArrays(cvtMesh), width, height))
        } catch {
          reject(event)
        }
      }
      worker.postMessage({ ...arrays, width, height },
        [arrays.ids.buffer, arrays.x.buffer, arrays.y.buffer, arrays.z.buffer])
    })
  }
  cellIdPending = { mesh: cvtMesh, width, height, promise }
  void promise.then((map) => {
    cellIdCache = { mesh: cvtMesh, width, height, map }
    if (cellIdPending?.promise === promise) cellIdPending = null
  }, () => {
    if (cellIdPending?.promise === promise) cellIdPending = null
  })
  return promise
}

/**
 * Return the cached cell-ID map, building it in a worker when needed.
 * Returns null until the worker finishes; consumers fall back to the raster
 * base in the meantime.
 */
export default function useCellIdMap({
  cvtMesh,
  width,
  height,
}: UseCellIdMapOptions): CellIdMap | null {
  const [map, setMap] = useState<CellIdMap | null>(() =>
    cvtMesh && cellIdCache && cellIdCache.mesh === cvtMesh && cellIdCache.width === width &&
      cellIdCache.height === height ? cellIdCache.map : null)

  useEffect(() => {
    if (!cvtMesh || !cvtMesh.cells.length || width <= 0 || height <= 0) {
      setMap(null)
      return
    }
    if (cellIdCache && cellIdCache.mesh === cvtMesh && cellIdCache.width === width &&
      cellIdCache.height === height) {
      setMap(cellIdCache.map)
      return
    }
    let cancelled = false
    mark('kd-tree-start')
    void loadCellIdMap(cvtMesh, width, height).then((result) => {
      if (cancelled) return
      mark('kd-tree-end')
      setMap(result)
    }, () => {
      if (!cancelled) setMap(null)
    })
    return () => { cancelled = true }
  }, [cvtMesh, width, height])

  return map
}
