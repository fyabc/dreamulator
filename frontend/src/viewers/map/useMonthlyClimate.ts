/**
 * useMonthlyClimate — load + bake the monthly temperature/precipitation texture
 * (Phase 4 monthly display).
 *
 * Fetches `climate_monthly.msgpack` for charts or monthly mode, then bakes a
 * colour texture for the current month and map field via
 * `bakeMonthlyLayer`.  The returned texture is passed to `useGPUTerrain` as the
 * monthly thematic override.
 */

import { useEffect, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../../api/client'
import type { CVTMesh } from './types'
import type { CellIdMap } from './useCellIdMap'
import { bakeMonthlyLayer, makeTexture } from './layerBakes'
import { canDownscale, downscaledClimatePixels, type ClimateRasterTerrain } from './climateDownscale'
import type { MonthlyClimateData } from '../../api/monthlyClimate'

export type MonthlyField = 'temperature' | 'precipitation' | 'pressure' | 'pressureError' | 'slp'

interface UseMonthlyClimateArgs {
  worldName?: string
  planetId?: string
  branch?: string | null
  trialData?: MonthlyClimateData
  month: number
  /** Thematic field to bake into a texture, or null (e.g. only wind arrows wanted). */
  field: MonthlyField | null
  monthlyMode: boolean
  downscale: boolean
  native: ClimateRasterTerrain | null
  seaLevelM: number
  /** Fetch monthly data for a chart or monthly map. */
  active: boolean
  cvtMesh: CVTMesh | null
  cellIdMap: CellIdMap | null
  width: number
  height: number
  flipHorizontal: boolean
}

export interface MonthlyClimateResult {
  /** Baked colour texture for `field`, or null. */
  texture: import('three').DataTexture | null
  /** Raw decoded monthly arrays (for wind arrows etc.), or null. */
  data: MonthlyClimateData | null
  loading: boolean
  displayingMonthly: boolean
}

export function useMonthlyClimate({
  worldName,
  planetId,
  branch,
  trialData,
  month,
  field,
  monthlyMode,
  downscale,
  native,
  seaLevelM,
  active,
  cvtMesh,
  cellIdMap,
  width,
  height,
  flipHorizontal,
}: UseMonthlyClimateArgs): MonthlyClimateResult {
  const { data, isFetching } = useQuery({
    queryKey: ['monthlyClimate', worldName, planetId, branch],
    queryFn: () => api.getMonthlyClimate(worldName!, planetId!, branch),
    enabled: !trialData && !!worldName && !!planetId && active,
    retry: false,
  })

  const source = trialData ?? data
  const monthly = active && source && (!cvtMesh || source.numCells === cvtMesh.cells.length) ? source : null
  const displayingMonthly = Boolean(monthlyMode && monthly && field && (
    field === 'pressure' || field === 'pressureError' ? monthly.pressureMonthly :
      field === 'slp' ? monthly.slpMonthly : field === 'temperature' ? monthly.tMonthly.length : monthly.pMonthly.length
  ))
  const texture = useMemo(() => {
    if (!cvtMesh || !cellIdMap || field === null) return null
    if (downscale && canDownscale(field)) {
      const outputWidth = Math.min(width, 2048)
      const outputHeight = Math.min(height, 1024)
      const pixels = downscaledClimatePixels(field, cvtMesh.cells, cellIdMap, width, height, outputWidth, outputHeight,
        seaLevelM, native, monthly, displayingMonthly ? month : null)
      return pixels ? makeTexture(pixels, outputWidth, outputHeight) : null
    }
    return displayingMonthly && monthly ? bakeMonthlyLayer(monthly, month, field, cvtMesh, cellIdMap, width, height, flipHorizontal) : null
  }, [monthly, month, field, displayingMonthly, downscale, native, seaLevelM, cvtMesh, cellIdMap, width, height, flipHorizontal])
  useEffect(() => () => texture?.dispose(), [texture])

  return { texture, data: monthly, loading: !trialData && isFetching, displayingMonthly }
}
