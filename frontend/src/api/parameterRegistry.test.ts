import { describe, expect, it } from 'vitest'
import { consumersOf, parameterRegistry, parametersForGroup } from './parameterRegistry'

describe('parameterRegistry', () => {
  it('loads the shared first-slice entries', () => {
    expect(parameterRegistry.map(parameter => parameter.id)).toEqual([
      'planet.axial_tilt_deg',
      'planet.rotation_period_days',
      'planet.albedo',
      'planet.greenhouse_warming_k',
    ])
  })

  it('groups by the UI layer', () => {
    expect(parametersForGroup('astronomy').map(parameter => parameter.id)).toEqual([
      'planet.axial_tilt_deg',
      'planet.rotation_period_days',
    ])
    expect(parametersForGroup('climate').map(parameter => parameter.id)).toEqual([
      'planet.albedo',
      'planet.greenhouse_warming_k',
    ])
  })

  it('reports consumers and falls back for unknown ids', () => {
    expect(consumersOf('planet.albedo')).toEqual(['astronomy', 'climate'])
    expect(consumersOf('planet.not_a_parameter')).toEqual([])
  })
})
