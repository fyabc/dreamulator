export interface WorldParameters {
  num_cells: number | null
  built_cells: number | null
  reuses_mesh: boolean
  source: string | null
  read_only: 'reference' | 'inherited' | 'fixed' | 'published' | 'unavailable' | null
  revision: string | null
  min_cells: number
  max_cells: number
}

export type WorldParameterUpdate = { num_cells: number; revision: string }

export const worldParametersKey = (world: string, branch: string | null) => ['worldParameters', world, branch] as const

export const worldParametersPath = (world: string, branch: string | null) =>
  `/worlds/${encodeURIComponent(world)}/world-parameters${branch ? `?branch=${encodeURIComponent(branch)}` : ''}`
