import { describe, expect, it } from 'vitest'
import { temperatureTrialMapPath, temperatureTrialPath, temperatureTrialReturnPath } from './temperatureDraft'

const origin = { world: 'earth', planet: 'planet_earth', branch: 'ERE-if' }

describe('climate experiment navigation', () => {
  it('opens the 2D map with the lab expanded on the originating branch', () => {
    expect(temperatureTrialMapPath(origin)).toBe('/worlds/earth/map/planet_earth?trial=climate&branch=ERE-if')
    expect(temperatureTrialMapPath({ ...origin, branch: null })).toBe('/worlds/earth/map/planet_earth?trial=climate')
  })
  it.each(['map', 'globe'] as const)('returns to the same %s view and selection', kind => {
    const view = new URLSearchParams({ window: '24.1,121.45,150', layer: 'temperature', monthly: '1', terrain: 'original' })
    const trial = new URL(temperatureTrialPath(origin, undefined, { kind, search: view }), 'https://example.invalid')
    expect(trial.searchParams.get('branch')).toBe('ERE-if')
    const back = new URL(temperatureTrialReturnPath(origin, trial.searchParams), trial)
    expect(back.pathname).toBe(`/worlds/earth/${kind}/planet_earth`)
    expect(Object.fromEntries(back.searchParams)).toEqual({ ...Object.fromEntries(view), branch: 'ERE-if' })
  })

  it('keeps the originating branch and ignores unrelated or nested route parameters', () => {
    const trial = new URLSearchParams({ from: 'map', mapView: 'branch=other&creation=1&redirect=example.org&window=1,2,300' })
    expect(temperatureTrialReturnPath(origin, trial)).toBe('/worlds/earth/map/planet_earth?window=1%2C2%2C300&branch=ERE-if')
  })

  it('still accepts an old map link and returns world-page entries to Climate', () => {
    expect(temperatureTrialReturnPath(origin, new URLSearchParams('from=globe'))).toBe('/worlds/earth/globe/planet_earth?branch=ERE-if')
    expect(temperatureTrialReturnPath(origin, new URLSearchParams())).toBe('/worlds/earth?tab=climate&planet=planet_earth&branch=ERE-if')
    expect(temperatureTrialReturnPath({ ...origin, planet: '' }, new URLSearchParams())).toBe('/help')
  })
})
