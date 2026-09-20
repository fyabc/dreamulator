/**
 * useUccLayer — bake the UCC classification thematic texture from the yearly
 * climate data (UCC-01 step 4a).
 *
 * The yearly data comes from the already-fetched `useYearlyClimate` hook (the
 * cell panel uses it too — react-query shares the cache).  The class codes are
 * computed by the backend export (`classify_v0`), so the bake is a pure
 * palette lookup — thresholds never live in the frontend.  Null while the
 * yearly file is missing or predates the classification fields; the layer
 * then degrades to transparent (the composite shader treats alpha=0 as
 * no-data, like the Köppen layer's ocean).
 */

import { useMemo } from 'react'
import type * as THREE from 'three'
import type { YearlyClimateData } from '../../api/yearlyClimate'
import type { CVTMesh } from './types'
import type { CellIdMap } from './useCellIdMap'
import { bakeUccLayer } from './layerBakes'

export function useUccLayer(
  yearlyData: YearlyClimateData | null,
  cvtMesh: CVTMesh | null,
  cellIdMap: CellIdMap | null,
  width: number,
  height: number,
  flipHorizontal: boolean,
): THREE.DataTexture | null {
  return useMemo(() => {
    if (!yearlyData || !yearlyData.uccThermal || !cvtMesh || !cellIdMap) return null
    if (width <= 0 || height <= 0) return null
    return bakeUccLayer(yearlyData, cvtMesh, cellIdMap, width, height, flipHorizontal)
  }, [yearlyData, cvtMesh, cellIdMap, width, height, flipHorizontal])
}
