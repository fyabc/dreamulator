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
import type { MonthlyClimateData } from '../../api/monthlyClimate'

export type MonthlyField = 'temperature' | 'precipitation' | 'pressure'

interface UseMonthlyClimateArgs {
  worldName?: string
  planetId?: string
  branch?: string | null
  seasonDeg: number
  /** Thematic field to bake into a texture, or null (e.g. only wind arrows wanted). */
  field: MonthlyField | null
  /** Fetch the monthly data at all (monthly mode + a monthly layer active). */
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
  /** Current month index 0–11 (0 = March / vernal equinox). */
  month: number
}

export function useMonthlyClimate({
  worldName,
  planetId,
  branch,
  seasonDeg,
  field,
  active,
  cvtMesh,
  cellIdMap,
  width,
  height,
  flipHorizontal,
}: UseMonthlyClimateArgs): MonthlyClimateResult {
  const { data: monthly } = useQuery({
    queryKey: ['monthlyClimate', worldName, planetId, branch],
    queryFn: () => api.getMonthlyClimate(worldName!, planetId!, branch),
    enabled: !!worldName && !!planetId && active,
    retry: false,
  })

  const month = Math.round(seasonDeg / 30) % 12

  const texture = useMemo(() => {
    if (!monthly || !cvtMesh || !cellIdMap || field === null) return null
    return bakeMonthlyLayer(monthly, month, field, cvtMesh, cellIdMap, width, height, flipHorizontal)
  }, [monthly, month, field, cvtMesh, cellIdMap, width, height, flipHorizontal])

  return { texture, data: monthly ?? null, month }
}
