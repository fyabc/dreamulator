/**
 * useMonthlyClimate — load + bake the monthly temperature/precipitation texture
 * (Phase 4 monthly display).
 *
 * Fetches the backend's `climate_monthly.msgpack` once (when the monthly mode is
 * enabled) and re-bakes a colour texture for the current month/field via
 * `bakeMonthlyLayer`.  The returned texture is passed to `useGPUTerrain` as the
 * monthly thematic override.
 */

import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../../api/client'
import type { CVTMesh } from './types'
import type { CellIdMap } from './useCellIdMap'
import { bakeMonthlyLayer } from './layerBakes'

export type MonthlyField = 'temperature' | 'precipitation'

interface UseMonthlyClimateArgs {
  worldName?: string
  planetId?: string
  branch?: string | null
  seasonDeg: number
  field: MonthlyField | null
  cvtMesh: CVTMesh | null
  cellIdMap: CellIdMap | null
  width: number
  height: number
  flipHorizontal: boolean
}

export function useMonthlyClimate({
  worldName,
  planetId,
  branch,
  seasonDeg,
  field,
  cvtMesh,
  cellIdMap,
  width,
  height,
  flipHorizontal,
}: UseMonthlyClimateArgs) {
  const { data: monthly } = useQuery({
    queryKey: ['monthlyClimate', worldName, planetId, branch],
    queryFn: () => api.getMonthlyClimate(worldName!, planetId!, branch),
    enabled: !!worldName && !!planetId && field !== null,
    retry: false,
  })

  const month = Math.round(seasonDeg / 30) % 12

  return useMemo(() => {
    if (!monthly || !cvtMesh || !cellIdMap || field === null) return null
    return bakeMonthlyLayer(monthly, month, field, cvtMesh, cellIdMap, width, height, flipHorizontal)
  }, [monthly, month, field, cvtMesh, cellIdMap, width, height, flipHorizontal])
}
