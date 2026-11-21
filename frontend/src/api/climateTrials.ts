import type { CVTMesh } from '../viewers/map/types'
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

export type ClimateTrialResult = ClimateTrialProducts & { forcing: ClimateTrialForcing }
