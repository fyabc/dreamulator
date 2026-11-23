/** Parameter lab state for one planet; values come from the shared registry. */
export interface LabParameter {
  id: string
  group: string
  value: number | null
  unit: string | null
  range: Record<string, number> | null
  consumers: string[]
  source: string | null
  editable: boolean
  reason: string | null
}

export interface ParameterLabState {
  planet: string | null
  branch: string | null
  fork_layer: string | null
  read_only: boolean
  revision: string
  parameters: LabParameter[]
  affected: string[]
  start_layer: string | null
}
