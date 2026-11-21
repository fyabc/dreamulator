/** Build execution snapshots; timestamps are ISO 8601 UTC strings. */
export interface BuildOptions {
  engine?: string | null
  branch?: string | null
  force?: boolean
}

export interface BuildGrid {
  num_cells: number | null
  reuses_mesh: boolean
}

export interface BuildSummary {
  status: string
  engines_run: number
  success: number
  failed: number
  errors: string[]
}

export interface BuildStep {
  name: string
  started_at: string
  finished_at: string | null
  completed: number | null
  total: number | null
  pass_number: number | null
}

export interface BuildStage {
  engine: string
  layer: string
  bootstrap: boolean
  state: 'pending' | 'validating' | 'running' | 'succeeded' | 'failed' | 'skipped' | 'not_run'
  started_at: string | null
  finished_at: string | null
  errors: string[]
  steps?: BuildStep[]
  planned_steps?: string[]
}

export interface BuildJob {
  id: string
  world: string
  branch: string | null
  engine: string | null
  force: boolean
  state: 'queued' | 'running' | 'succeeded' | 'failed'
  created_at: string
  started_at: string | null
  updated_at: string
  finished_at: string | null
  elapsed_seconds: number
  current_engine: string | null
  stages: BuildStage[]
  result: BuildSummary | null
  error: string | null
}
