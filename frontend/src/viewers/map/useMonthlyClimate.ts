/**
 * useMonthlyClimate — load climate months and bake the active scalar texture.
 *
 * Fetches `climate_monthly.msgpack` for charts or monthly mode. Thematic
 * overrides cover monthly model-grid textures and both annual and monthly
 * downscaled textures.
 */

import { useEffect, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../../api/client'
import type { CVTMesh } from './types'
import type { CellIdMap } from './useCellIdMap'
import { bakeMonthlyLayer, makeTexture } from './layerBakes'
import { downscaledClimatePixels, type ClimateRasterTerrain } from './climateDownscale'
import type { MonthlyClimateData } from '../../api/monthlyClimate'
import { scalarMonthValues, type MonthlyScalarLayer, type ScalarLayer } from './scalarLayers'

export type MonthlyField = MonthlyScalarLayer
export type ScalarTexture = { layer: ScalarLayer; texture: import('three').DataTexture }

interface UseMonthlyClimateArgs {
  worldName?: string
  planetId?: string
  branch?: string | null
  trialData?: MonthlyClimateData
  month: number
  /** Thematic field to bake into a texture, or null (e.g. only wind arrows wanted). */
  field: ScalarLayer | null
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
  texture: ScalarTexture | null
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
  const monthValues = field && monthlyMode ? scalarMonthValues(field, monthly) : undefined
  const displayingMonthly = Boolean(monthValues?.length && monthly && monthValues.length === monthly.numCells * monthly.months && month < monthly.months)
  const texture = useMemo<ScalarTexture | null>(() => {
    if (!cvtMesh || !cellIdMap || field === null) return null
    if (downscale) {
      const outputWidth = Math.min(width, 2048)
      const outputHeight = Math.min(height, 1024)
      const pixels = downscaledClimatePixels(field, cvtMesh.cells, cellIdMap, width, height, outputWidth, outputHeight,
        seaLevelM, native, monthly, displayingMonthly ? month : null)
      return pixels ? { layer: field, texture: makeTexture(pixels, outputWidth, outputHeight) } : null
    }
    return displayingMonthly && monthly ? {
      layer: field, texture: bakeMonthlyLayer(monthly, month, field, cvtMesh, cellIdMap, width, height, flipHorizontal),
    } : null
  }, [monthly, month, field, displayingMonthly, downscale, native, seaLevelM, cvtMesh, cellIdMap, width, height, flipHorizontal])
  useEffect(() => () => texture?.texture.dispose(), [texture])

  return { texture, data: monthly, loading: !trialData && isFetching, displayingMonthly }
}
