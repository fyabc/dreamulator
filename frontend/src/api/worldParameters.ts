type ReadOnly = 'reference' | 'inherited' | 'fixed' | 'published' | 'unavailable'

export interface PlanetValues {
  rotation_period_days: number
  albedo: number
}

export interface WorldPlanet extends PlanetValues {
  id: string
  name: string
  source: string
  read_only: ReadOnly | null
  revision: string | null
  needs_rebuild: boolean
}

export interface WorldParameters {
  num_cells: number | null
  built_cells: number | null
  reuses_mesh: boolean
  source: string | null
  read_only: ReadOnly | null
  revision: string | null
  min_cells: number
  max_cells: number
  planet: WorldPlanet | null
}

export type WorldGridUpdate = { num_cells: number; revision: string }
export type WorldPlanetUpdate = { planet: PlanetValues; revision: string }
export type WorldParameterUpdate = WorldGridUpdate | WorldPlanetUpdate

export function validPlanetValues({ rotation_period_days, albedo }: PlanetValues) {
  return Number.isFinite(rotation_period_days) && rotation_period_days > 0 &&
    Number.isFinite(albedo) && albedo >= 0 && albedo <= 1
}

export const worldParametersKey = (world: string, branch: string | null) => ['worldParameters', world, branch] as const

export const worldParametersPath = (world: string, branch: string | null) =>
  `/worlds/${encodeURIComponent(world)}/world-parameters${branch ? `?branch=${encodeURIComponent(branch)}` : ''}`
