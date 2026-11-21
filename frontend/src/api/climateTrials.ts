import type { CVTMesh, MapMetadata } from '../viewers/map/types'
import type { MonthlyClimateData } from './monthlyClimate'
import type { YearlyClimateData } from './yearlyClimate'

export type ClimateTrialForcing = {
  axial_tilt_deg: number
  rotation_period_days: number
  albedo: number
  greenhouse_warming_k: number
}

export interface ClimateTrialJob {
  id: string
  state: 'queued' | 'running' | 'succeeded' | 'failed'
  stage: string
  elapsed_seconds: number
  stage_seconds: number
  cells: number | null
  months_done: number | null
  months_total: number | null
  moisture_pass: number | null
  error: string | null
  error_detail?: string
}

export interface ClimateTrialProducts {
  mesh: CVTMesh
  monthly: MonthlyClimateData
  yearly: YearlyClimateData | null
}

export interface SavedClimateTrial {
  id: string
  format: 1
  solver: 'ebm'
  planet: string
  branch: string | null
  saved_at: string
  cells: number
  elapsed_seconds: number
  inputs: {
    solver_version: string
    mesh_sha256: string
    config_sha256: string
    forcing: ClimateTrialForcing
    radius_km: number
  }
  surface: MapMetadata
}

export const browserClimateAssets = ['geometry', 'fields', 'monthly', 'yearly', 'elevation'] as const
export const maxBrowserClimateTrials = 8
export type SavedBrowserEbm = {
  metadata: SavedClimateTrial
  assets: Record<typeof browserClimateAssets[number], Blob>
}

export type ClimateTrialResult = ClimateTrialProducts & {
  forcing: ClimateTrialForcing
  saved?: { metadata: SavedClimateTrial; elevation: Blob }
}

export const savedClimateKey = (world: string) => ['saved-climate-trials', world] as const

export function savedClimateMapPath(world: string, result: SavedClimateTrial) {
  const search = new URLSearchParams({ climateResult: result.id })
  if (result.branch) search.set('branch', result.branch)
  return `/worlds/${encodeURIComponent(world)}/map/${encodeURIComponent(result.planet)}?${search}`
}
