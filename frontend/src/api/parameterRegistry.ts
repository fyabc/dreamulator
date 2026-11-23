import registry from '@dreamulator/parameters'

/** Layers that can own a parameter or consume it. */
export type ParameterGroup =
  | 'physics'
  | 'chemistry'
  | 'astronomy'
  | 'geological'
  | 'climate'
  | 'ecology'
  | 'civilization'

export type ParameterType = 'number' | 'enum' | 'boolean'

export interface ParameterStorage {
  file: string
  /** YAML path inside the file; '*' iterates a list of mappings. */
  path: (string | number)[]
}

export interface ParameterRange {
  minimum?: number
  maximum?: number
  exclusiveMinimum?: number
}

export interface ParameterSpec {
  id: string
  group: ParameterGroup
  storage: ParameterStorage
  type: ParameterType
  unit?: string
  range?: ParameterRange
  consumers: ParameterGroup[]
  note?: string
}

interface RegistryDocument {
  schema: number
  parameters: ParameterSpec[]
}

const document = registry as unknown as RegistryDocument

/** The shared registry, in document order. */
export const parameterRegistry: readonly ParameterSpec[] = document.parameters

/** Parameters grouped under one UI layer, in document order. */
export function parametersForGroup(group: ParameterGroup): ParameterSpec[] {
  return document.parameters.filter(parameter => parameter.group === group)
}

/** Engine layers that read a parameter; empty when the id is unknown. */
export function consumersOf(parameterId: string): ParameterGroup[] {
  return document.parameters.find(parameter => parameter.id === parameterId)?.consumers ?? []
}
