import { describe, expect, it } from 'vitest'
import { legacyTemperatureTrialDestination, temperatureSampleOrigins, temperatureTrialMapPath } from './temperatureDraft'

const origin = { ...temperatureSampleOrigins.earth, branch: 'ERE-if' }

describe('climate experiment navigation', () => {
  it('opens the Earth and Nacrea samples on their respective main-world maps', () => {
    expect(temperatureTrialMapPath(temperatureSampleOrigins.earth)).toBe('/worlds/earth/map/planet_earth?trial=climate')
    expect(temperatureTrialMapPath(temperatureSampleOrigins.nacrea)).toBe('/worlds/nacrea/map/satellite_nacrea?trial=climate')
  })

  it('opens the 2D map with the lab expanded on the originating branch', () => {
    expect(temperatureTrialMapPath(origin)).toBe('/worlds/earth/map/planet_earth?trial=climate&branch=ERE-if')
    expect(temperatureTrialMapPath(origin, 'saved-id')).toBe('/worlds/earth/map/planet_earth?trial=climate&branch=ERE-if&draft=saved-id')
  })

  it.each(['map', 'globe'] as const)('redirects an old draft link to the same %s view and selection', kind => {
    const view = { window: '24.1,121.45,150', layer: 'temperature', monthly: '1', terrain: 'original' }
    const search = new URLSearchParams({ ...origin, draft: 'saved-id', from: kind,
      mapView: new URLSearchParams({ ...view, branch: 'wrong', creation: '1', redirect: 'example.org' }).toString() })
    const destination = new URL(legacyTemperatureTrialDestination(search)!, 'https://example.invalid')
    expect(destination.pathname).toBe(`/worlds/earth/${kind}/planet_earth`)
    expect(Object.fromEntries(destination.searchParams)).toEqual({ ...view, trial: 'climate', branch: 'ERE-if', draft: 'saved-id' })
  })

  it('redirects an old contextual link even before a draft has been saved', () => {
    expect(legacyTemperatureTrialDestination(new URLSearchParams({ ...origin, from: 'globe' })))
      .toBe('/worlds/earth/globe/planet_earth?trial=climate&branch=ERE-if')
  })

  it('does not infer a world or planet for a generic link', () => {
    expect(legacyTemperatureTrialDestination(new URLSearchParams())).toBeNull()
    expect(legacyTemperatureTrialDestination(new URLSearchParams({ world: 'earth', draft: 'saved-id' }))).toBeNull()
  })
})
